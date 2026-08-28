from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from compact_vio.learning.errors import LearningError
from compact_vio.learning.position_evaluate_cli import (
    CandidateDecisionInput,
    _enforce_validation_guardrail,
    apply_position_decision_rule,
    build_parser,
    load_position_evaluation_protocol,
    main,
)


def _protocol() -> dict[str, object]:
    return {
        "record_type": "euroc_position_only_checkpoint_evaluation",
        "schema_version": "1.0.0",
        "evaluation_id": "euroc-mh01-frozen-checkpoints-position-v1",
        "dataset": {
            "doi": "10.3929/ethz-b-000690084",
            "rights_statement": "In Copyright - Non-Commercial Use Permitted",
            "sequence_id": "MH_01_easy",
            "archive_filename": "machine_hall.zip",
            "archive_size_bytes": 12683729426,
            "archive_md5": "363f5c2502b469cdd97ef85997714806",
            "archive_sha256": "a" * 64,
            "sensor_sources_sha256": "b" * 64,
            "sensor_calibration_sha256": "c" * 64,
            "position_reference_sha256": "d" * 64,
        },
        "sampling": {
            "frame_stride": 1,
            "evaluation_unroll_pairs": 128,
            "max_reference_bracket_interval_ns": 100000000,
            "prediction_origin_id": "imu0",
            "reference_origin_id": "leica0",
            "sensor_origin_projection_policy_id": (
                "imu-to-leica-origin/from-native-t-bs/"
                "r-il-equals-r-bi-transpose-times-p-bl-minus-p-bi/"
                "delta-l-equals-t-i-plus-r-rel-r-il-minus-r-il/v1"
            ),
            "reference_association_policy_id": (
                "linear-within-leica-coverage/max-bracket-100ms/"
                "all-native-pairs-both-endpoints-valid/no-extrapolation/v1"
            ),
        },
        "metric_policy_id": (
            "sensor-point-displacement-magnitude/exact-preassociated-position-pairs/"
            "predicted-rotation-and-declared-lever-arm/no-reference-orientation/"
            "preassociated-input/no-internal-interpolation/"
            "no-alignment/no-scale-fitting/v1"
        ),
        "decision_rule_id": (
            "full-sensor-and-reference-coverage/beat-zero-pair-rmse/"
            "minimum-pair-displacement-magnitude-rmse/no-tie-break/v1"
        ),
        "candidates": [
            {
                "candidate_id": "v2",
                "checkpoint_sha256": "2" * 64,
                "inference_policy_id": "independent-zero-state-per-pair/v1",
            },
            {
                "candidate_id": "v3",
                "checkpoint_sha256": "3" * 64,
                "inference_policy_id": "stateful-contiguous-native-pairs/v1",
            },
            {
                "candidate_id": "v4",
                "checkpoint_sha256": "4" * 64,
                "inference_policy_id": "stateful-contiguous-native-pairs/v1",
            },
        ],
    }


def _controlled_magnitude_protocol() -> dict[str, object]:
    value = _protocol()
    value["evaluation_id"] = "euroc-mh02-v2-v5-magnitude-position-v1"
    value["dataset"]["sequence_id"] = "MH_02_easy"  # type: ignore[index]
    value["decision_rule_id"] = (
        "full-sensor-and-reference-coverage/beat-zero-pair-rmse/"
        "v5-beats-v2-on-pair-cumulative-and-distance-ratio/no-tie-no-retry/v1"
    )
    value["validation_guardrail"] = {
        "candidate_id": "v5",
        "max_selected_validation_translation_rmse_m": 0.058765891780989885,
        "max_selected_validation_rotation_rmse_rad": 0.0061899144990098035,
    }
    value["candidates"] = [
        {
            "candidate_id": "v2",
            "checkpoint_sha256": "2" * 64,
            "inference_policy_id": "independent-zero-state-per-pair/v1",
        },
        {
            "candidate_id": "v5",
            "checkpoint_sha256": "5" * 64,
            "inference_policy_id": "independent-zero-state-per-pair/v1",
        },
    ]
    return value


class PositionEvaluationCliTests(unittest.TestCase):
    def _load(self, value: dict[str, object] | None = None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "protocol.json"
        path.write_text(json.dumps(value if value is not None else _protocol()), encoding="utf-8")
        return load_position_evaluation_protocol(path)

    def test_checked_protocol_binds_exact_dataset_candidates_and_sha(self) -> None:
        protocol = self._load()

        self.assertEqual(protocol.dataset.sequence_id, "MH_01_easy")
        self.assertEqual(protocol.sampling.frame_stride, 1)
        self.assertEqual(
            tuple(candidate.candidate_id for candidate in protocol.candidates),
            ("v2", "v3", "v4"),
        )
        self.assertEqual(len(protocol.source_sha256), 64)
        self.assertTrue(protocol.source_path.is_absolute())

    def test_committed_machine_hall_protocol_binds_measured_sources_and_checkpoints(self) -> None:
        path = (
            Path(__file__).resolve().parent.parent
            / "configs/evaluation/euroc_mh01_frozen_checkpoints_position_v1.json"
        )
        protocol = load_position_evaluation_protocol(path)

        self.assertEqual(
            protocol.dataset.sensor_sources_sha256,
            "10dd5e711a8c063c16b65d2fe69baa979e8b39299bcaaf5643c5683f27a6977f",
        )
        self.assertEqual(protocol.sampling.max_reference_bracket_interval_ns, 100_000_000)
        self.assertEqual(
            tuple(candidate.checkpoint_sha256 for candidate in protocol.candidates),
            (
                "17698fbf70862bf1aae17925081b0baf536d2c5b84fa6dcaea7b69926e3c3605",
                "40d18a9a3a04131d04e06a4ab313279613d1dc2339d1758f99777ecb70de8c37",
                "e775adb16aa4f9522aa577a32704a54db5c82c53685b0e97fb8d149402bf159d",
            ),
        )

    def test_unknown_fields_bad_hash_duplicate_candidate_and_policy_fail(self) -> None:
        for mutate, message in (
            (lambda item: item.update({"unknown": 1}), "fields must equal"),
            (
                lambda item: item["dataset"].update({"archive_sha256": "A" * 64}),
                "lowercase hexadecimal",
            ),
            (
                lambda item: item["candidates"].append(dict(item["candidates"][0])),
                "identifiers must be unique",
            ),
            (
                lambda item: item["candidates"][0].update({"inference_policy_id": "infer-it/v0"}),
                "unsupported candidate",
            ),
            (
                lambda item: item["dataset"].update({"sequence_id": "../escape"}),
                "safe identifier",
            ),
            (
                lambda item: item["candidates"][0].update({"candidate_id": "/tmp/escape"}),
                "safe identifier",
            ),
        ):
            value = _protocol()
            mutate(value)
            with self.subTest(message=message), self.assertRaisesRegex(LearningError, message):
                self._load(value)

    def test_decision_selects_only_full_coverage_candidate_beating_zero(self) -> None:
        protocol = self._load()
        outcomes = (
            CandidateDecisionInput("v2", 100, 100, 90, 90, 0.08),
            CandidateDecisionInput("v3", 100, 100, 90, 90, 0.06),
            CandidateDecisionInput("v4", 100, 100, 90, 90, 0.07),
        )

        decision = apply_position_decision_rule(
            protocol,
            outcomes,
            zero_motion_pair_rmse_m=0.1,
        )

        self.assertEqual(decision["decision"], "selected_position_endpoint_candidate")
        self.assertEqual(decision["selected_candidate_id"], "v3")
        self.assertTrue(all(row["eligible"] for row in decision["candidate_eligibility"]))

    def test_decision_rejects_incomplete_zero_losing_and_exact_tie(self) -> None:
        protocol = self._load()
        incomplete = (
            CandidateDecisionInput("v2", 100, 99, 90, 90, 0.05),
            CandidateDecisionInput("v3", 100, 100, 90, 89, 0.04),
            CandidateDecisionInput("v4", 100, 100, 90, 90, 0.11),
        )
        rejected = apply_position_decision_rule(
            protocol,
            incomplete,
            zero_motion_pair_rmse_m=0.1,
        )
        self.assertEqual(rejected["decision"], "no_eligible_candidate")
        self.assertIsNone(rejected["selected_candidate_id"])

        tied = tuple(
            CandidateDecisionInput(candidate, 100, 100, 90, 90, 0.05)
            for candidate in ("v2", "v3", "v4")
        )
        tied_decision = apply_position_decision_rule(
            protocol,
            tied,
            zero_motion_pair_rmse_m=0.1,
        )
        self.assertEqual(tied_decision["decision"], "no_selection_exact_metric_tie")

    def test_decision_requires_exact_candidate_order(self) -> None:
        protocol = self._load()
        outcomes = (
            CandidateDecisionInput("v3", 1, 1, 1, 1, 0.1),
            CandidateDecisionInput("v2", 1, 1, 1, 1, 0.1),
            CandidateDecisionInput("v4", 1, 1, 1, 1, 0.1),
        )
        with self.assertRaisesRegex(LearningError, "protocol order"):
            apply_position_decision_rule(
                protocol,
                outcomes,
                zero_motion_pair_rmse_m=0.2,
            )

    def test_controlled_magnitude_rule_accepts_only_when_every_gate_passes(self) -> None:
        protocol = self._load(_controlled_magnitude_protocol())
        outcomes = (
            CandidateDecisionInput("v2", 100, 100, 90, 90, 0.08, 2.0, 0.60),
            CandidateDecisionInput("v5", 100, 100, 90, 90, 0.07, 1.5, 0.75),
        )

        accepted = apply_position_decision_rule(
            protocol,
            outcomes,
            zero_motion_pair_rmse_m=0.1,
        )

        self.assertEqual(accepted["decision"], "accept_v5")
        self.assertEqual(accepted["selected_candidate_id"], "v5")
        self.assertTrue(all(accepted["comparison_gates"].values()))

        # V2's earlier endpoint is not a new v5 eligibility gate. V5 is accepted
        # when it beats both V2 and zero motion with complete matched coverage.
        v2_loses_to_zero = (
            CandidateDecisionInput("v2", 100, 100, 90, 90, 0.11, 2.0, 0.60),
            CandidateDecisionInput("v5", 100, 100, 90, 90, 0.09, 1.5, 0.75),
        )
        accepted_against_both = apply_position_decision_rule(
            protocol,
            v2_loses_to_zero,
            zero_motion_pair_rmse_m=0.1,
        )
        self.assertEqual(accepted_against_both["decision"], "accept_v5")
        self.assertFalse(
            accepted_against_both["candidate_eligibility"][0]["beats_zero_motion_pair_rmse"]
        )

        failed_ratio = (
            outcomes[0],
            CandidateDecisionInput("v5", 100, 100, 90, 90, 0.07, 1.5, 0.50),
        )
        rejected = apply_position_decision_rule(
            protocol,
            failed_ratio,
            zero_motion_pair_rmse_m=0.1,
        )
        self.assertEqual(rejected["decision"], "retain_v2")
        self.assertEqual(rejected["selected_candidate_id"], "v2")
        self.assertFalse(rejected["comparison_gates"]["distance_ratio_error_lower_than_v2"])

    def test_controlled_magnitude_rule_rejects_missing_metrics_or_wrong_candidates(self) -> None:
        protocol = self._load(_controlled_magnitude_protocol())
        with self.assertRaisesRegex(LearningError, "requires cumulative RMSE"):
            apply_position_decision_rule(
                protocol,
                (
                    CandidateDecisionInput("v2", 1, 1, 1, 1, 0.08),
                    CandidateDecisionInput("v5", 1, 1, 1, 1, 0.07),
                ),
                zero_motion_pair_rmse_m=0.1,
            )

    def test_controlled_validation_guardrail_is_enforced_before_inference(self) -> None:
        protocol = self._load(_controlled_magnitude_protocol())
        passing = {
            "v2": {},
            "v5": {
                "validation/translation_rmse_m": 0.058765891780989885,
                "validation/rotation_rmse_rad": 0.0061899144990098035,
            },
        }
        _enforce_validation_guardrail(protocol, passing)

        failing = {
            **passing,
            "v5": {
                **passing["v5"],
                "validation/translation_rmse_m": 0.05876589178098989,
            },
        }
        with self.assertRaisesRegex(LearningError, "validation guardrail failed"):
            _enforce_validation_guardrail(protocol, failing)
        with self.assertRaisesRegex(LearningError, "missing, negative, or non-finite"):
            _enforce_validation_guardrail(protocol, {"v2": {}, "v5": {}})
        negative = {
            **passing,
            "v5": {
                **passing["v5"],
                "validation/rotation_rmse_rad": -0.001,
            },
        }
        with self.assertRaisesRegex(LearningError, "missing, negative, or non-finite"):
            _enforce_validation_guardrail(protocol, negative)

        wrong_guardrail = _controlled_magnitude_protocol()
        wrong_guardrail["validation_guardrail"]["candidate_id"] = "v2"  # type: ignore[index]
        with self.assertRaisesRegex(LearningError, "must apply to candidate_id 'v5'"):
            self._load(wrong_guardrail)

        relaxed_guardrail = _controlled_magnitude_protocol()
        relaxed_guardrail["validation_guardrail"][  # type: ignore[index]
            "max_selected_validation_rotation_rmse_rad"
        ] = 0.01
        with self.assertRaisesRegex(LearningError, "exact frozen selected-v2 limits"):
            self._load(relaxed_guardrail)

        wrong = _controlled_magnitude_protocol()
        wrong["candidates"][1]["candidate_id"] = "other"  # type: ignore[index]
        with self.assertRaisesRegex(LearningError, "exact v2, v5 order"):
            self._load(wrong)

        with self.assertRaisesRegex(LearningError, "identical candidate coverage counts"):
            apply_position_decision_rule(
                protocol,
                (
                    CandidateDecisionInput("v2", 100, 100, 90, 90, 0.08, 2.0, 0.6),
                    CandidateDecisionInput("v5", 99, 99, 89, 89, 0.07, 1.5, 0.7),
                ),
                zero_motion_pair_rmse_m=0.1,
            )

    def test_cli_accepts_only_declared_device_and_checkpoint_shape(self) -> None:
        args = build_parser().parse_args(
            [
                "--protocol",
                "protocol.json",
                "--archive",
                "machine_hall.zip",
                "--data-root",
                "data",
                "--checkpoint",
                "v2=checkpoint.pt",
                "--output-dir",
                "output",
                "--device",
                "cuda",
            ]
        )
        self.assertEqual(args.device, "cuda")
        self.assertEqual(args.checkpoint, ["v2=checkpoint.pt"])
        with self.assertRaises(SystemExit):
            build_parser().parse_args(
                [
                    "--protocol",
                    "p",
                    "--archive",
                    "a.zip",
                    "--data-root",
                    "d",
                    "--output-dir",
                    "o",
                    "--device",
                    "metal",
                ]
            )

    def test_main_returns_structured_failure_for_domain_value_errors(self) -> None:
        stderr = io.StringIO()
        with (
            patch(
                "compact_vio.learning.position_evaluate_cli._run",
                side_effect=ValueError("synthetic domain failure"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = main(
                [
                    "--protocol",
                    "protocol.json",
                    "--archive",
                    "machine_hall.zip",
                    "--data-root",
                    "data",
                    "--output-dir",
                    "output",
                ]
            )
        self.assertEqual(result, 2)
        failure = json.loads(stderr.getvalue())
        self.assertEqual(failure["event"], "evaluation_failed")
        self.assertEqual(failure["error_type"], "ValueError")


if __name__ == "__main__":
    unittest.main()

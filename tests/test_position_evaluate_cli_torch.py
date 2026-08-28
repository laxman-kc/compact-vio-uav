from __future__ import annotations

import contextlib
import copy
import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from compact_vio.learning.errors import LearningError

try:
    import torch
    from PIL import Image

    TORCH_STACK_AVAILABLE = True
except ImportError:
    TORCH_STACK_AVAILABLE = False

if TORCH_STACK_AVAILABLE:
    from compact_vio.data.euroc import (
        sensor_calibration_sources_sha256,
        sensor_sequence_sources_sha256,
    )
    from compact_vio.data.euroc_position import position_reference_sources_sha256
    from compact_vio.learning.checkpoint import CheckpointProvenance, save_checkpoint
    from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.position_evaluate_cli import _run, build_parser


_METRIC_POLICY_ID = (
    "sensor-point-displacement-magnitude/exact-preassociated-position-pairs/"
    "predicted-rotation-and-declared-lever-arm/no-reference-orientation/"
    "preassociated-input/no-internal-interpolation/"
    "no-alignment/no-scale-fitting/v1"
)
_DECISION_RULE_ID = (
    "full-sensor-and-reference-coverage/beat-zero-pair-rmse/"
    "minimum-pair-displacement-magnitude-rmse/no-tie-break/v1"
)
_PROJECTION_POLICY_ID = (
    "imu-to-leica-origin/from-native-t-bs/"
    "r-il-equals-r-bi-transpose-times-p-bl-minus-p-bi/"
    "delta-l-equals-t-i-plus-r-rel-r-il-minus-r-il/v1"
)
_ASSOCIATION_POLICY_ID = (
    "linear-within-leica-coverage/max-bracket-100ms/"
    "all-native-pairs-both-endpoints-valid/no-extrapolation/v1"
)


def _transform(*, x_m: float = 0.0) -> dict[str, object]:
    return {
        "rows": 4,
        "cols": 4,
        "data": [
            1.0,
            0.0,
            0.0,
            x_m,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
        ],
    }


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _write_sensor_position_fixture(data_root: Path) -> Path:
    sequence_root = data_root / "MH_01_easy"
    camera = sequence_root / "mav0/cam0"
    imu = sequence_root / "mav0/imu0"
    leica = sequence_root / "mav0/leica0"
    (camera / "data").mkdir(parents=True)
    imu.mkdir(parents=True)
    leica.mkdir(parents=True)
    timestamps = (100_000_000, 150_000_000, 200_000_000, 250_000_000)
    for index, timestamp_ns in enumerate(timestamps):
        Image.new("L", (48, 32), color=32 + index * 48).save(
            camera / "data" / f"{timestamp_ns}.png"
        )
    _write_csv(
        camera / "data.csv",
        ("#timestamp [ns]", "filename"),
        [(timestamp_ns, f"{timestamp_ns}.png") for timestamp_ns in timestamps],
    )
    (camera / "sensor.yaml").write_text(
        json.dumps(
            {
                "sensor_type": "camera",
                "comment": "synthetic position-evaluation smoke fixture",
                "T_BS": _transform(),
                "rate_hz": 20,
                "resolution": [48, 32],
                "camera_model": "pinhole",
                "intrinsics": [32.0, 32.0, 24.0, 16.0],
                "distortion_model": "radial-tangential",
                "distortion_coefficients": [0.0, 0.0, 0.0, 0.0],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _write_csv(
        imu / "data.csv",
        (
            "#timestamp [ns]",
            "w_RS_S_x [rad s^-1]",
            "w_RS_S_y [rad s^-1]",
            "w_RS_S_z [rad s^-1]",
            "a_RS_S_x [m s^-2]",
            "a_RS_S_y [m s^-2]",
            "a_RS_S_z [m s^-2]",
        ),
        [
            (100_000_000, 0.0, 0.0, 0.0, 0.0, 0.0, 9.81),
            (125_000_000, 0.01, 0.02, 0.03, 0.1, 0.2, 9.81),
            (150_000_000, 0.02, 0.03, 0.04, 0.2, 0.3, 9.81),
            (175_000_000, 0.03, 0.04, 0.05, 0.3, 0.4, 9.81),
            (200_000_000, 0.04, 0.05, 0.06, 0.4, 0.5, 9.81),
            (225_000_000, 0.05, 0.06, 0.07, 0.5, 0.6, 9.81),
            (250_000_000, 0.06, 0.07, 0.08, 0.6, 0.7, 9.81),
        ],
    )
    (imu / "sensor.yaml").write_text(
        json.dumps(
            {
                "sensor_type": "imu",
                "comment": "synthetic position-evaluation smoke fixture",
                "T_BS": _transform(),
                "rate_hz": 200,
                "gyroscope_noise_density": 0.001,
                "gyroscope_random_walk": 0.001,
                "accelerometer_noise_density": 0.01,
                "accelerometer_random_walk": 0.01,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    _write_csv(
        leica / "data.csv",
        (
            "#timestamp [ns]",
            "p_RS_R_x [m]",
            "p_RS_R_y [m]",
            "p_RS_R_z [m]",
        ),
        [
            (100_000_000, 0.0, 0.0, 0.0),
            (150_000_000, 0.1, 0.0, 0.0),
            (200_000_000, 0.2, 0.0, 0.0),
            (250_000_000, 0.3, 0.0, 0.0),
        ],
    )
    (leica / "sensor.yaml").write_text(
        json.dumps(
            {
                "sensor_type": "position",
                "comment": "synthetic Leica position reference",
                "T_BS": _transform(x_m=0.1),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return sequence_root


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(TORCH_STACK_AVAILABLE, "PyTorch and Pillow training extras are not installed")
class PositionEvaluationCliTorchTests(unittest.TestCase):
    def test_synthetic_frozen_checkpoint_evaluation_runs_end_to_end_without_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_root = root / "data"
            sequence_root = _write_sensor_position_fixture(data_root)
            archive = root / "machine_hall.zip"
            archive.write_bytes(b"synthetic Machine Hall archive identity\n")
            checkpoint_root = root / "checkpoints"
            checkpoint_root.mkdir()
            model_config = ModelConfig(
                image_height_px=32,
                image_width_px=48,
                visual_feature_dim=16,
                imu_hidden_dim=8,
                fusion_hidden_dim=16,
                dropout_probability=0.0,
            )
            training_config = TrainingConfig(
                model=model_config,
                data=DataConfig(),
                batch_size=2,
                epochs=1,
                num_workers=0,
                seed=23,
                use_amp=False,
            )
            provenance = CheckpointProvenance.create(
                dataset_id="EuRoC DOI 10.3929/ethz-b-000690084",
                split_id="synthetic-no-mh01-overlap-v1",
                train_sequence_ids=("V1_01_easy",),
                validation_sequence_ids=("V2_01_easy",),
                source_sha256={"V1_01_easy": "1" * 64, "V2_01_easy": "2" * 64},
                calibration_sha256={"V1_01_easy": "3" * 64, "V2_01_easy": "4" * 64},
                code_revision="a" * 40,
            )
            checkpoint_paths: dict[str, Path] = {}
            checkpoint_hashes: dict[str, str] = {}
            for candidate_index, candidate_id in enumerate(("v2", "v3", "v4"), start=2):
                torch.manual_seed(candidate_index)
                candidate_model_config = model_config
                if candidate_id == "v4":
                    candidate_model_config = ModelConfig(
                        image_height_px=32,
                        image_width_px=48,
                        visual_feature_dim=16,
                        imu_hidden_dim=8,
                        fusion_hidden_dim=16,
                        dropout_probability=0.0,
                        rotation_state_source=("current-pair-zero-initialized-fusion-state/v1"),
                    )
                candidate_config = replace(training_config, model=candidate_model_config)
                checkpoint_path = checkpoint_root / f"{candidate_id}.pt"
                save_checkpoint(
                    checkpoint_path,
                    model=CompactVIO(candidate_model_config),
                    config=candidate_config,
                    epoch=candidate_index,
                    metrics={"validation/total_loss": 1.0 / candidate_index},
                    provenance=provenance,
                )
                payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
                self.assertIsNone(payload["optimizer_state_dict"])
                checkpoint_paths[candidate_id] = checkpoint_path
                checkpoint_hashes[candidate_id] = _sha256(checkpoint_path)
            self.assertEqual(len(set(checkpoint_hashes.values())), 3)

            archive_bytes = archive.read_bytes()
            protocol_value = {
                "record_type": "euroc_position_only_checkpoint_evaluation",
                "schema_version": "2.0.0",
                "evaluation_id": "synthetic-position-evaluation-smoke-v2",
                "dataset": {
                    "doi": "10.3929/ethz-b-000690084",
                    "rights_statement": "In Copyright - Non-Commercial Use Permitted",
                    "sequence_id": "MH_01_easy",
                    "archive_filename": archive.name,
                    "archive_size_bytes": len(archive_bytes),
                    "archive_md5": hashlib.md5(archive_bytes).hexdigest(),
                    "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
                    "sensor_sources_sha256": sensor_sequence_sources_sha256(sequence_root),
                    "sensor_calibration_sha256": sensor_calibration_sources_sha256(sequence_root),
                    "position_reference_sha256": position_reference_sources_sha256(sequence_root),
                },
                "sampling": {
                    "frame_stride": 1,
                    "evaluation_unroll_pairs": 2,
                    "max_reference_bracket_interval_ns": 100_000_000,
                    "prediction_origin_id": "imu0",
                    "reference_origin_id": "leica0",
                    "sensor_origin_projection_policy_id": _PROJECTION_POLICY_ID,
                    "reference_association_policy_id": _ASSOCIATION_POLICY_ID,
                },
                "metric_policy_id": _METRIC_POLICY_ID,
                "decision_rule_id": _DECISION_RULE_ID,
                "candidates": [
                    {
                        "candidate_id": candidate_id,
                        "checkpoint_sha256": checkpoint_hashes[candidate_id],
                        "inference_policy_id": (
                            "independent-zero-state-per-pair/v1"
                            if candidate_id == "v2"
                            else "stateful-contiguous-native-pairs/v1"
                        ),
                        "checkpoint_provenance": {
                            "code_revision": provenance.code_revision,
                            "split_id": provenance.split_id,
                            "train_sequence_ids": list(provenance.train_sequence_ids),
                            "validation_sequence_ids": list(provenance.validation_sequence_ids),
                            "source_sha256": dict(provenance.source_sha256),
                            "calibration_sha256": dict(provenance.calibration_sha256),
                        },
                    }
                    for candidate_id in ("v2", "v3", "v4")
                ],
            }
            protocol = root / "protocol.json"
            protocol.write_text(
                json.dumps(protocol_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            mismatched_value = copy.deepcopy(protocol_value)
            mismatched_value["candidates"][0]["checkpoint_provenance"][  # type: ignore[index]
                "code_revision"
            ] = "b" * 40
            mismatched_protocol = root / "mismatched-protocol.json"
            mismatched_protocol.write_text(
                json.dumps(mismatched_value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            mismatched_output = root / "mismatched-output"
            mismatched_arguments = build_parser().parse_args(
                [
                    "--protocol",
                    str(mismatched_protocol),
                    "--archive",
                    str(archive),
                    "--data-root",
                    str(data_root),
                    "--checkpoint",
                    f"v2={checkpoint_paths['v2']}",
                    "--checkpoint",
                    f"v3={checkpoint_paths['v3']}",
                    "--checkpoint",
                    f"v4={checkpoint_paths['v4']}",
                    "--output-dir",
                    str(mismatched_output),
                    "--device",
                    "cpu",
                ]
            )
            with (
                patch(
                    "compact_vio.learning.position_evaluate_cli._git_revision",
                    return_value="a" * 40,
                ),
                patch("compact_vio.learning.position_evaluate_cli._archive_hashes") as hash_archive,
                patch("compact_vio.data.euroc.load_euroc_sensor_sequence") as load_sensors,
                patch(
                    "compact_vio.data.euroc_position.load_euroc_position_reference"
                ) as load_reference,
                patch(
                    "compact_vio.learning.position_evaluate_cli._candidate_predictions"
                ) as predict_candidate,
                self.assertRaisesRegex(LearningError, "provenance code_revision differs"),
            ):
                _run(mismatched_arguments)
            hash_archive.assert_not_called()
            load_sensors.assert_not_called()
            load_reference.assert_not_called()
            predict_candidate.assert_not_called()
            self.assertFalse(mismatched_output.exists())

            output = root / "output"
            arguments = build_parser().parse_args(
                [
                    "--protocol",
                    str(protocol),
                    "--archive",
                    str(archive),
                    "--data-root",
                    str(data_root),
                    "--checkpoint",
                    f"v2={checkpoint_paths['v2']}",
                    "--checkpoint",
                    f"v3={checkpoint_paths['v3']}",
                    "--checkpoint",
                    f"v4={checkpoint_paths['v4']}",
                    "--output-dir",
                    str(output),
                    "--device",
                    "cpu",
                ]
            )
            evaluation_checkpoint_hashes = {
                candidate_id: _sha256(path) for candidate_id, path in checkpoint_paths.items()
            }
            disallowed_calls: list[str] = []
            previous_profiler = sys.getprofile()

            def observe_calls(frame: object, event: str, argument: object) -> None:
                del argument
                if event != "call":
                    return
                globals_value = getattr(frame, "f_globals", {})
                module = globals_value.get("__name__", "")
                function = getattr(getattr(frame, "f_code", None), "co_name", "")
                if module.startswith("compact_vio.learning.training") or (
                    module.startswith("torch.optim") and function in {"__init__", "step"}
                ):
                    disallowed_calls.append(f"{module}.{function}")

            try:
                sys.setprofile(observe_calls)
                with (
                    patch(
                        "compact_vio.learning.position_evaluate_cli._git_revision",
                        return_value="a" * 40,
                    ) as git_revision,
                    contextlib.redirect_stdout(io.StringIO()) as stdout,
                ):
                    self.assertEqual(_run(arguments), 0)
            finally:
                sys.setprofile(previous_profiler)

            self.assertEqual(disallowed_calls, [])
            self.assertEqual(git_revision.call_count, 2)
            completion = json.loads(stdout.getvalue())
            self.assertEqual(completion["event"], "evaluation_complete")
            self.assertEqual(
                {candidate_id: _sha256(path) for candidate_id, path in checkpoint_paths.items()},
                evaluation_checkpoint_hashes,
            )
            expected_artifacts = {
                "evaluation-summary.json",
                "v2-metrics.json",
                "v2-predictions.jsonl",
                "v3-metrics.json",
                "v3-predictions.jsonl",
                "v4-metrics.json",
                "v4-predictions.jsonl",
            }
            self.assertEqual({path.name for path in output.iterdir()}, expected_artifacts)
            summary = json.loads((output / "evaluation-summary.json").read_text())
            self.assertEqual(summary["status"], "completed")
            self.assertEqual(summary["git_revision"], "a" * 40)
            self.assertEqual(summary["device"], "cpu")
            self.assertEqual(
                [candidate["candidate_id"] for candidate in summary["candidates"]],
                ["v2", "v3", "v4"],
            )
            association = summary["dataset"]["reference_association"]
            self.assertEqual(association["camera_frame_count"], 4)
            self.assertEqual(association["associated_camera_frame_count"], 4)
            self.assertEqual(association["eligible_native_pair_count"], 3)
            self.assertEqual(association["rejected_native_pair_count"], 0)

            for candidate in summary["candidates"]:
                candidate_id = candidate["candidate_id"]
                frozen_candidate = next(
                    item
                    for item in protocol_value["candidates"]  # type: ignore[union-attr]
                    if item["candidate_id"] == candidate_id
                )
                frozen_provenance = frozen_candidate["checkpoint_provenance"]
                observed_provenance = candidate["checkpoint"]["provenance"]
                self.assertEqual(
                    observed_provenance["code_revision"],
                    frozen_provenance["code_revision"],
                )
                self.assertEqual(observed_provenance["split_id"], frozen_provenance["split_id"])
                self.assertEqual(
                    observed_provenance["train_sequence_ids"],
                    frozen_provenance["train_sequence_ids"],
                )
                self.assertEqual(
                    observed_provenance["validation_sequence_ids"],
                    frozen_provenance["validation_sequence_ids"],
                )
                self.assertEqual(
                    dict(observed_provenance["source_sha256"]),
                    frozen_provenance["source_sha256"],
                )
                self.assertEqual(
                    dict(observed_provenance["calibration_sha256"]),
                    frozen_provenance["calibration_sha256"],
                )
                self.assertEqual(
                    candidate["coverage"],
                    {
                        "sensor_pair_count": 3,
                        "produced_pair_count": 3,
                        "reference_pair_count": 3,
                        "scored_pair_count": 3,
                        "reference_excluded_sensor_pair_count": 0,
                    },
                )
                expected_initializations = 3 if candidate_id == "v2" else 1
                self.assertEqual(
                    candidate["inference"]["state_initialization_count"],
                    expected_initializations,
                )
                predictions_path = output / candidate["predictions_artifact"]["filename"]
                self.assertEqual(
                    _sha256(predictions_path), candidate["predictions_artifact"]["sha256"]
                )
                rows = tuple(
                    json.loads(line)
                    for line in predictions_path.read_text(encoding="utf-8").splitlines()
                )
                self.assertEqual(len(rows), 3)
                self.assertTrue(all(row["position_reference"] is not None for row in rows))
                self.assertTrue(all(row["reference_rotation_available"] is False for row in rows))
                self.assertTrue(
                    all(
                        row["predicted_rotation_used_for_sensor_point_projection"] is True
                        for row in rows
                    )
                )


if __name__ == "__main__":
    unittest.main()

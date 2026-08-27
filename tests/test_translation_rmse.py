from __future__ import annotations

import math
import sys
import unittest
from dataclasses import FrozenInstanceError, replace

from compact_vio.evaluation import (
    EXACT_PAIR_TRANSLATION_RMSE_ID,
    ScaleCorrection,
    TimestampAssociation,
    TrajectoryAlignment,
    TrajectoryInterpolation,
    TranslationMetricError,
    TranslationRmsePolicy,
    TranslationRmseResult,
    exact_pair_translation_rmse,
)
from compact_vio.geometry import (
    CartesianPosition3,
    Trajectory,
    TrajectoryContractError,
    TrajectoryConvention,
    TrajectorySample,
)

CONVENTION = TrajectoryConvention(
    convention_id="synthetic-trajectory-convention-v1",
    reference_frame_id="synthetic-reference-frame",
    tracked_frame_id="synthetic-tracked-frame",
    transform_direction="synthetic-reference-to-tracked-direction",
    translation_unit="synthetic-translation-unit",
    clock_id="synthetic-clock",
    timestamp_semantics_id="synthetic-output-time-semantics",
)

POLICY = TranslationRmsePolicy(
    policy_id="synthetic-exact-raw-translation-policy-v1",
    timestamp_association=TimestampAssociation.EXACT,
    interpolation=TrajectoryInterpolation.NONE,
    alignment=TrajectoryAlignment.NONE,
    scale_correction=ScaleCorrection.NONE,
)


def _position(x: int | float, y: int | float, z: int | float) -> CartesianPosition3:
    return CartesianPosition3(x=x, y=y, z=z)


def _trajectory(
    trajectory_id: str,
    positions: tuple[CartesianPosition3, ...],
    *,
    sequence_id: str = "synthetic-sequence",
    segment_id: str = "synthetic-segment",
    convention: TrajectoryConvention = CONVENTION,
    sample_ids: tuple[str, ...] | None = None,
    timestamps_ns: tuple[int, ...] | None = None,
) -> Trajectory:
    if sample_ids is None:
        sample_ids = tuple(f"synthetic-pair-{index}" for index in range(len(positions)))
    if timestamps_ns is None:
        timestamps_ns = tuple((index + 1) * 10 for index in range(len(positions)))
    if len(sample_ids) != len(positions) or len(timestamps_ns) != len(positions):
        raise AssertionError("test helper inputs must have equal lengths")
    return Trajectory(
        trajectory_id=trajectory_id,
        sequence_id=sequence_id,
        segment_id=segment_id,
        convention=convention,
        samples=tuple(
            TrajectorySample(
                sample_id=sample_id,
                timestamp_ns=timestamp_ns,
                position=position,
            )
            for sample_id, timestamp_ns, position in zip(
                sample_ids,
                timestamps_ns,
                positions,
                strict=True,
            )
        ),
    )


class TrajectoryGeometryTests(unittest.TestCase):
    def test_convention_requires_every_spatial_and_temporal_declaration(self) -> None:
        values = {
            "convention_id": "convention",
            "reference_frame_id": "reference",
            "tracked_frame_id": "tracked",
            "transform_direction": "direction",
            "translation_unit": "unit",
            "clock_id": "clock",
            "timestamp_semantics_id": "timestamp-semantics",
        }
        for field in values:
            invalid = dict(values)
            invalid[field] = " "
            with self.subTest(field=field):
                with self.assertRaisesRegex(TrajectoryContractError, field):
                    TrajectoryConvention(**invalid)

    def test_position_rejects_nonfinite_or_unrepresentable_components(self) -> None:
        for value in (
            True,
            "1",
            complex(1, 0),
            math.nan,
            math.inf,
            -math.inf,
            10**1000,
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    TrajectoryContractError,
                    "finite real number|exactly representable",
                ):
                    CartesianPosition3(value, 0, 0)  # type: ignore[arg-type]

        self.assertEqual(_position(2**53, 0, 0).x, 2**53)
        with self.assertRaisesRegex(TrajectoryContractError, "exactly representable"):
            _position(2**53 + 1, 0, 0)

    def test_sample_requires_identity_time_and_position(self) -> None:
        with self.assertRaisesRegex(TrajectoryContractError, "sample_id"):
            TrajectorySample(" ", 0, _position(0, 0, 0))
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaisesRegex(TrajectoryContractError, "timestamp_ns"):
                    TrajectorySample(
                        "sample",
                        value,  # type: ignore[arg-type]
                        _position(0, 0, 0),
                    )
        with self.assertRaisesRegex(TrajectoryContractError, "CartesianPosition3"):
            TrajectorySample("sample", 0, (0, 0, 0))  # type: ignore[arg-type]

    def test_trajectory_preserves_empty_segments_but_requires_a_tuple(self) -> None:
        empty = _trajectory("empty-trajectory", ())
        self.assertEqual(empty.samples, ())
        self.assertFalse(hasattr(empty, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            empty.segment_id = "changed"  # type: ignore[misc]

        with self.assertRaisesRegex(TrajectoryContractError, "samples must be a tuple"):
            Trajectory(
                "trajectory",
                "sequence",
                "segment",
                CONVENTION,
                [],  # type: ignore[arg-type]
            )

    def test_trajectory_rejects_duplicate_ids_and_backward_time(self) -> None:
        positions = (_position(0, 0, 0), _position(1, 0, 0))
        with self.assertRaisesRegex(TrajectoryContractError, "sample_id"):
            _trajectory(
                "trajectory",
                positions,
                sample_ids=("same", "same"),
            )
        same_time = _trajectory(
            "same-time-trajectory",
            positions,
            timestamps_ns=(10, 10),
        )
        self.assertEqual(
            tuple(sample.sample_id for sample in same_time.samples),
            ("synthetic-pair-0", "synthetic-pair-1"),
        )

        with self.assertRaisesRegex(TrajectoryContractError, "backward"):
            _trajectory(
                "trajectory",
                positions,
                timestamps_ns=(20, 10),
            )


class TranslationRmsePolicyTests(unittest.TestCase):
    def test_policy_has_no_implicit_or_raw_string_modes(self) -> None:
        with self.assertRaisesRegex(TranslationMetricError, "policy_id"):
            replace(POLICY, policy_id=" ")
        invalid_modes = (
            ("timestamp_association", "exact"),
            ("interpolation", "none"),
            ("alignment", "none"),
            ("scale_correction", "none"),
        )
        for field, value in invalid_modes:
            with self.subTest(field=field):
                with self.assertRaisesRegex(TranslationMetricError, field):
                    replace(POLICY, **{field: value})

    def test_policy_is_required_at_each_metric_call(self) -> None:
        trajectory = _trajectory("trajectory", (_position(0, 0, 0),))
        with self.assertRaises(TypeError):
            exact_pair_translation_rmse(trajectory, trajectory)  # type: ignore[call-arg]


class ExactPairTranslationRmseTests(unittest.TestCase):
    def test_known_three_dimensional_rmse_and_result_metadata(self) -> None:
        reference = _trajectory(
            "reference",
            (_position(0, 0, 0), _position(0, 0, 0)),
        )
        estimated = _trajectory(
            "estimated",
            (_position(3, 4, 0), _position(0, 0, 12)),
        )

        result = exact_pair_translation_rmse(reference, estimated, policy=POLICY)

        self.assertEqual(result.metric_id, EXACT_PAIR_TRANSLATION_RMSE_ID)
        self.assertEqual(result.policy_id, POLICY.policy_id)
        self.assertEqual(result.reference_trajectory_id, "reference")
        self.assertEqual(result.estimated_trajectory_id, "estimated")
        self.assertEqual(result.sequence_id, "synthetic-sequence")
        self.assertEqual(result.segment_id, "synthetic-segment")
        self.assertEqual(result.translation_unit, "synthetic-translation-unit")
        self.assertEqual(result.pair_count, 2)
        self.assertAlmostEqual(result.value, math.sqrt(84.5))

    def test_identical_trajectory_has_finite_zero_error(self) -> None:
        reference = _trajectory(
            "reference",
            (_position(-1, 2, 3), _position(4, -5, 6)),
        )
        estimated = replace(reference, trajectory_id="estimated")

        result = exact_pair_translation_rmse(reference, estimated, policy=POLICY)

        self.assertEqual(result.value, 0.0)
        self.assertTrue(math.isfinite(result.value))

    def test_distinct_same_time_samples_remain_exactly_ordered(self) -> None:
        timestamps = (10, 10)
        reference = _trajectory(
            "reference",
            (_position(0, 0, 0), _position(1, 0, 0)),
            timestamps_ns=timestamps,
        )
        estimated = _trajectory(
            "estimated",
            (_position(0, 0, 0), _position(2, 0, 0)),
            timestamps_ns=timestamps,
        )

        result = exact_pair_translation_rmse(reference, estimated, policy=POLICY)

        self.assertEqual(result.pair_count, 2)
        self.assertAlmostEqual(result.value, math.sqrt(0.5))

    def test_no_translation_rotation_or_scale_alignment_is_hidden(self) -> None:
        origin_reference = _trajectory(
            "offset-reference",
            (_position(0, 0, 0), _position(1, 2, 3)),
        )
        offset_estimated = _trajectory(
            "offset-estimated",
            (_position(10, -20, 30), _position(11, -18, 33)),
        )
        offset = exact_pair_translation_rmse(
            origin_reference,
            offset_estimated,
            policy=POLICY,
        )
        self.assertAlmostEqual(offset.value, math.sqrt(1400))

        rotation_reference = _trajectory(
            "rotation-reference",
            (_position(1, 0, 0), _position(0, 1, 0)),
        )
        rotation_estimated = _trajectory(
            "rotation-estimated",
            (_position(0, 1, 0), _position(-1, 0, 0)),
        )
        rotation = exact_pair_translation_rmse(
            rotation_reference,
            rotation_estimated,
            policy=POLICY,
        )
        self.assertAlmostEqual(rotation.value, math.sqrt(2))

        scale_reference = _trajectory(
            "scale-reference",
            (_position(0, 0, 0), _position(1, 0, 0), _position(0, 1, 0)),
        )
        scale_estimated = _trajectory(
            "scale-estimated",
            (_position(0, 0, 0), _position(2, 0, 0), _position(0, 2, 0)),
        )
        scale = exact_pair_translation_rmse(
            scale_reference,
            scale_estimated,
            policy=POLICY,
        )
        self.assertAlmostEqual(scale.value, math.sqrt(2 / 3))

    def test_every_convention_field_must_match_exactly(self) -> None:
        reference = _trajectory("reference", (_position(0, 0, 0),))
        for field in (
            "convention_id",
            "reference_frame_id",
            "tracked_frame_id",
            "transform_direction",
            "translation_unit",
            "clock_id",
            "timestamp_semantics_id",
        ):
            with self.subTest(field=field):
                changed = replace(CONVENTION, **{field: f"different-{field}"})
                estimated = _trajectory(
                    "estimated",
                    (_position(0, 0, 0),),
                    convention=changed,
                )
                with self.assertRaisesRegex(TranslationMetricError, field):
                    exact_pair_translation_rmse(
                        reference,
                        estimated,
                        policy=POLICY,
                    )

    def test_segment_count_identity_and_timestamp_must_match(self) -> None:
        reference = _trajectory(
            "reference",
            (_position(0, 0, 0), _position(1, 0, 0)),
        )
        cases = (
            (
                _trajectory(
                    "estimated",
                    (_position(0, 0, 0), _position(1, 0, 0)),
                    sequence_id="other-sequence",
                ),
                "sequence_id",
            ),
            (
                _trajectory(
                    "estimated",
                    (_position(0, 0, 0), _position(1, 0, 0)),
                    segment_id="other-segment",
                ),
                "segment_id",
            ),
            (
                _trajectory("estimated", (_position(0, 0, 0),)),
                "sample counts",
            ),
            (
                _trajectory(
                    "estimated",
                    (_position(0, 0, 0), _position(1, 0, 0)),
                    sample_ids=("other-id", "synthetic-pair-1"),
                ),
                "sample_id",
            ),
            (
                _trajectory(
                    "estimated",
                    (_position(0, 0, 0), _position(1, 0, 0)),
                    timestamps_ns=(11, 20),
                ),
                "timestamps",
            ),
        )
        for estimated, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(TranslationMetricError, message):
                    exact_pair_translation_rmse(
                        reference,
                        estimated,
                        policy=POLICY,
                    )

    def test_empty_and_wrong_inputs_fail_instead_of_reporting_survivors(self) -> None:
        empty_reference = _trajectory("reference", ())
        empty_estimated = _trajectory("estimated", ())
        with self.assertRaisesRegex(TranslationMetricError, "at least one"):
            exact_pair_translation_rmse(
                empty_reference,
                empty_estimated,
                policy=POLICY,
            )
        with self.assertRaisesRegex(TranslationMetricError, "reference"):
            exact_pair_translation_rmse(  # type: ignore[arg-type]
                "not-a-trajectory",
                empty_estimated,
                policy=POLICY,
            )
        with self.assertRaisesRegex(TranslationMetricError, "estimated"):
            exact_pair_translation_rmse(  # type: ignore[arg-type]
                empty_reference,
                "not-a-trajectory",
                policy=POLICY,
            )
        with self.assertRaisesRegex(TranslationMetricError, "policy"):
            exact_pair_translation_rmse(  # type: ignore[arg-type]
                empty_reference,
                empty_estimated,
                policy="raw-string-policy",
            )

    def test_scaled_rms_preserves_large_and_tiny_finite_errors(self) -> None:
        maximum = sys.float_info.max
        large_reference = _trajectory(
            "large-reference",
            (_position(0, 0, 0), _position(0, 0, 0)),
        )
        large_estimated = _trajectory(
            "large-estimated",
            (_position(maximum, 0, 0), _position(maximum, 0, 0)),
        )
        large = exact_pair_translation_rmse(
            large_reference,
            large_estimated,
            policy=POLICY,
        )
        self.assertEqual(large.value, maximum)

        multi_axis_reference = _trajectory(
            "multi-axis-reference",
            tuple(_position(0, 0, 0) for _ in range(4)),
        )
        multi_axis_estimated = _trajectory(
            "multi-axis-estimated",
            (
                _position(maximum, maximum, 0),
                _position(0, 0, 0),
                _position(0, 0, 0),
                _position(0, 0, 0),
            ),
        )
        multi_axis = exact_pair_translation_rmse(
            multi_axis_reference,
            multi_axis_estimated,
            policy=POLICY,
        )
        self.assertTrue(
            math.isclose(
                multi_axis.value,
                maximum / math.sqrt(2),
                rel_tol=1e-15,
            )
        )

        tiny_reference = _trajectory("tiny-reference", (_position(0, 0, 0),))
        tiny_estimated = _trajectory("tiny-estimated", (_position(1e-200, 0, 0),))
        tiny = exact_pair_translation_rmse(
            tiny_reference,
            tiny_estimated,
            policy=POLICY,
        )
        self.assertGreater(tiny.value, 0.0)
        self.assertTrue(math.isclose(tiny.value, 1e-200, rel_tol=1e-15))

    def test_nonfinite_difference_fails_with_a_metric_domain_error(self) -> None:
        maximum = sys.float_info.max
        reference = _trajectory("reference", (_position(-maximum, 0, 0),))
        estimated = _trajectory("estimated", (_position(maximum, 0, 0),))

        with self.assertRaisesRegex(TranslationMetricError, "finite runtime domain"):
            exact_pair_translation_rmse(reference, estimated, policy=POLICY)

    def test_positive_error_cannot_silently_underflow_to_zero(self) -> None:
        minimum_subnormal = math.ulp(0.0)
        reference = _trajectory(
            "reference",
            tuple(_position(0, 0, 0) for _ in range(4)),
        )
        estimated = _trajectory(
            "estimated",
            (
                _position(minimum_subnormal, 0, 0),
                _position(0, 0, 0),
                _position(0, 0, 0),
                _position(0, 0, 0),
            ),
        )

        with self.assertRaisesRegex(TranslationMetricError, "underflows"):
            exact_pair_translation_rmse(reference, estimated, policy=POLICY)

    def test_result_contract_rejects_invalid_public_values(self) -> None:
        values = {
            "metric_id": EXACT_PAIR_TRANSLATION_RMSE_ID,
            "policy_id": POLICY.policy_id,
            "reference_trajectory_id": "reference",
            "estimated_trajectory_id": "estimated",
            "sequence_id": "sequence",
            "segment_id": "segment",
            "translation_unit": "unit",
            "pair_count": 1,
            "value": 0.0,
        }
        for field, invalid in (
            ("metric_id", " "),
            ("metric_id", "aligned-ate"),
            ("pair_count", 0),
            ("pair_count", True),
            ("value", -1.0),
            ("value", math.nan),
            ("value", 0),
        ):
            with self.subTest(field=field, invalid=invalid):
                changed = dict(values)
                changed[field] = invalid
                with self.assertRaisesRegex(TranslationMetricError, field):
                    TranslationRmseResult(**changed)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import math
import sys
import unittest
from dataclasses import FrozenInstanceError, replace

from compact_vio.evaluation import (
    EXACT_PAIR_TRANSLATION_RESIDUALS_ID,
    ScaleCorrection,
    TimestampAssociation,
    TrajectoryAlignment,
    TrajectoryInterpolation,
    TranslationMetricError,
    TranslationResidualSample,
    TranslationResidualSeries,
    TranslationRmsePolicy,
    exact_pair_translation_residuals,
    exact_pair_translation_rmse,
)
from compact_vio.geometry import (
    CartesianPosition3,
    Trajectory,
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


def _residual_components(
    series: TranslationResidualSeries,
) -> tuple[tuple[float, float, float], ...]:
    return tuple((sample.dx, sample.dy, sample.dz) for sample in series.samples)


def _valid_series_values() -> dict[str, object]:
    return {
        "series_id": EXACT_PAIR_TRANSLATION_RESIDUALS_ID,
        "policy_id": POLICY.policy_id,
        "reference_trajectory_id": "reference",
        "estimated_trajectory_id": "estimated",
        "sequence_id": "synthetic-sequence",
        "segment_id": "synthetic-segment",
        "convention": CONVENTION,
        "samples": (
            TranslationResidualSample(
                sample_id="pair-0",
                timestamp_ns=10,
                dx=0.0,
                dy=0.0,
                dz=0.0,
            ),
        ),
    }


class ExactPairTranslationResidualTests(unittest.TestCase):
    def test_known_signed_estimated_minus_reference_values_and_metadata(self) -> None:
        reference = _trajectory(
            "reference",
            (_position(1, 2, 3), _position(-4, 5, -6)),
            sample_ids=("pair-a", "pair-b"),
            timestamps_ns=(11, 22),
        )
        estimated = _trajectory(
            "estimated",
            (_position(4, -2, 3), _position(-10, 17, 0)),
            sample_ids=("pair-a", "pair-b"),
            timestamps_ns=(11, 22),
        )

        result = exact_pair_translation_residuals(reference, estimated, policy=POLICY)

        self.assertEqual(result.series_id, EXACT_PAIR_TRANSLATION_RESIDUALS_ID)
        self.assertEqual(result.policy_id, POLICY.policy_id)
        self.assertEqual(result.reference_trajectory_id, "reference")
        self.assertEqual(result.estimated_trajectory_id, "estimated")
        self.assertEqual(result.sequence_id, "synthetic-sequence")
        self.assertEqual(result.segment_id, "synthetic-segment")
        self.assertEqual(result.convention, CONVENTION)
        self.assertEqual(
            tuple((sample.sample_id, sample.timestamp_ns) for sample in result.samples),
            (("pair-a", 11), ("pair-b", 22)),
        )
        self.assertEqual(
            _residual_components(result),
            ((3.0, -4.0, 0.0), (-6.0, 12.0, 6.0)),
        )

    def test_distinct_same_time_samples_keep_declared_order_and_identity(self) -> None:
        reference = _trajectory(
            "reference",
            (_position(10, 0, 0), _position(20, 0, 0)),
            sample_ids=("first", "second"),
            timestamps_ns=(10, 10),
        )
        estimated = _trajectory(
            "estimated",
            (_position(11, 0, 0), _position(18, 0, 0)),
            sample_ids=("first", "second"),
            timestamps_ns=(10, 10),
        )

        result = exact_pair_translation_residuals(reference, estimated, policy=POLICY)

        self.assertEqual(
            tuple((sample.sample_id, sample.timestamp_ns, sample.dx) for sample in result.samples),
            (("first", 10, 1.0), ("second", 10, -2.0)),
        )

    def test_raw_offset_rotation_and_scale_remain_visible(self) -> None:
        cases = (
            (
                (_position(0, 0, 0), _position(1, 2, 3)),
                (_position(10, -20, 30), _position(11, -18, 33)),
                ((10.0, -20.0, 30.0), (10.0, -20.0, 30.0)),
            ),
            (
                (_position(1, 0, 0), _position(0, 1, 0)),
                (_position(0, 1, 0), _position(-1, 0, 0)),
                ((-1.0, 1.0, 0.0), (-1.0, -1.0, 0.0)),
            ),
            (
                (_position(0, 0, 0), _position(1, 0, 0), _position(0, 1, 0)),
                (_position(0, 0, 0), _position(2, 0, 0), _position(0, 2, 0)),
                ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            ),
        )
        for index, (reference_positions, estimated_positions, expected) in enumerate(cases):
            with self.subTest(case=index):
                reference = _trajectory("reference", reference_positions)
                estimated = _trajectory("estimated", estimated_positions)
                result = exact_pair_translation_residuals(
                    reference,
                    estimated,
                    policy=POLICY,
                )
                self.assertEqual(_residual_components(result), expected)

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
                    exact_pair_translation_residuals(
                        reference,
                        estimated,
                        policy=POLICY,
                    )

    def test_sequence_segment_count_identity_and_timestamp_must_match(self) -> None:
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
                    exact_pair_translation_residuals(
                        reference,
                        estimated,
                        policy=POLICY,
                    )

    def test_empty_partial_and_wrong_inputs_fail(self) -> None:
        empty_reference = _trajectory("reference", ())
        empty_estimated = _trajectory("estimated", ())
        one_estimated = _trajectory("estimated", (_position(0, 0, 0),))

        with self.assertRaisesRegex(TranslationMetricError, "at least one"):
            exact_pair_translation_residuals(
                empty_reference,
                empty_estimated,
                policy=POLICY,
            )
        with self.assertRaisesRegex(TranslationMetricError, "sample counts"):
            exact_pair_translation_residuals(
                empty_reference,
                one_estimated,
                policy=POLICY,
            )
        with self.assertRaisesRegex(TranslationMetricError, "reference"):
            exact_pair_translation_residuals(  # type: ignore[arg-type]
                "not-a-trajectory",
                one_estimated,
                policy=POLICY,
            )
        with self.assertRaisesRegex(TranslationMetricError, "estimated"):
            exact_pair_translation_residuals(  # type: ignore[arg-type]
                one_estimated,
                "not-a-trajectory",
                policy=POLICY,
            )
        with self.assertRaisesRegex(TranslationMetricError, "policy"):
            exact_pair_translation_residuals(  # type: ignore[arg-type]
                one_estimated,
                one_estimated,
                policy="raw-string-policy",
            )
        with self.assertRaises(TypeError):
            exact_pair_translation_residuals(  # type: ignore[call-arg]
                one_estimated,
                one_estimated,
            )

    def test_finite_extremes_preserve_sign_and_nonfinite_difference_fails(self) -> None:
        maximum = sys.float_info.max
        minimum_subnormal = math.ulp(0.0)
        reference = _trajectory(
            "reference",
            (
                _position(0, 0, 0),
                _position(maximum, 0, 0),
                _position(0, 0, 0),
            ),
        )
        estimated = _trajectory(
            "estimated",
            (
                _position(maximum, 0, 0),
                _position(0, 0, 0),
                _position(minimum_subnormal, 0, 0),
            ),
        )

        result = exact_pair_translation_residuals(reference, estimated, policy=POLICY)

        self.assertEqual(
            tuple(sample.dx for sample in result.samples),
            (maximum, -maximum, minimum_subnormal),
        )
        self.assertTrue(all(math.isfinite(sample.dx) for sample in result.samples))

        overflowing_reference = _trajectory(
            "overflowing-reference",
            (_position(-maximum, 0, 0),),
        )
        overflowing_estimated = _trajectory(
            "overflowing-estimated",
            (_position(maximum, 0, 0),),
        )
        with self.assertRaisesRegex(TranslationMetricError, "finite runtime domain"):
            exact_pair_translation_residuals(
                overflowing_reference,
                overflowing_estimated,
                policy=POLICY,
            )

    def test_integer_difference_that_is_not_float_exact_fails(self) -> None:
        reference = _trajectory("reference", (_position(-1, 0, 0),))
        estimated = _trajectory("estimated", (_position(2**53, 0, 0),))

        with self.assertRaisesRegex(TranslationMetricError, "exactly representable"):
            exact_pair_translation_residuals(reference, estimated, policy=POLICY)
        with self.assertRaisesRegex(TranslationMetricError, "exactly representable"):
            exact_pair_translation_rmse(reference, estimated, policy=POLICY)

    def test_residual_sample_is_frozen_slotted_and_rejects_forged_values(self) -> None:
        sample = TranslationResidualSample("pair", 10, 1.0, -2.0, 3.0)
        self.assertFalse(hasattr(sample, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            sample.dx = 4.0  # type: ignore[misc]

        for field, invalid in (
            ("sample_id", " "),
            ("timestamp_ns", -1),
            ("timestamp_ns", True),
            ("dx", 0),
            ("dx", True),
            ("dy", math.nan),
            ("dz", math.inf),
        ):
            with self.subTest(field=field, invalid=invalid):
                with self.assertRaisesRegex(TranslationMetricError, field):
                    replace(sample, **{field: invalid})

    def test_series_is_frozen_slotted_and_requires_exact_tuple_records(self) -> None:
        values = _valid_series_values()
        result = TranslationResidualSeries(**values)  # type: ignore[arg-type]
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.segment_id = "changed"  # type: ignore[misc]

        class TupleSpoof:
            @property
            def __class__(self) -> type[tuple[object, ...]]:
                return tuple

        class ResidualSampleSpoof:
            sample_id = "pair-0"
            timestamp_ns = 10
            dx = 0.0
            dy = 0.0
            dz = 0.0

            @property
            def __class__(self) -> type[TranslationResidualSample]:
                return TranslationResidualSample

        for invalid in (
            [values["samples"]],
            TupleSpoof(),
            (ResidualSampleSpoof(),),
        ):
            with self.subTest(invalid=type(invalid).__name__):
                changed = dict(values)
                changed["samples"] = invalid
                with self.assertRaisesRegex(TranslationMetricError, "samples"):
                    TranslationResidualSeries(**changed)  # type: ignore[arg-type]

    def test_series_contract_rejects_forged_identifiers_order_and_content(self) -> None:
        values = _valid_series_values()
        first = values["samples"][0]  # type: ignore[index]
        second = replace(first, sample_id="pair-1", timestamp_ns=20)
        for field, invalid, message in (
            ("series_id", " ", "series_id"),
            ("series_id", "aligned-residuals", "series_id"),
            ("policy_id", " ", "policy_id"),
            ("reference_trajectory_id", " ", "reference_trajectory_id"),
            ("estimated_trajectory_id", " ", "estimated_trajectory_id"),
            ("sequence_id", " ", "sequence_id"),
            ("segment_id", " ", "segment_id"),
            ("convention", "not-a-convention", "convention"),
            ("samples", (), "non-empty"),
            ("samples", (first, replace(second, sample_id="pair-0")), "sample_id"),
            ("samples", (second, first), "backward"),
        ):
            with self.subTest(field=field, message=message):
                changed = dict(values)
                changed[field] = invalid
                with self.assertRaisesRegex(TranslationMetricError, message):
                    TranslationResidualSeries(**changed)  # type: ignore[arg-type]

    def test_existing_rmse_result_is_unchanged(self) -> None:
        reference = _trajectory(
            "reference",
            (_position(0, 0, 0), _position(0, 0, 0)),
        )
        estimated = _trajectory(
            "estimated",
            (_position(3, 4, 0), _position(0, 0, 12)),
        )

        residuals = exact_pair_translation_residuals(reference, estimated, policy=POLICY)
        rmse = exact_pair_translation_rmse(reference, estimated, policy=POLICY)

        self.assertEqual(_residual_components(residuals), ((3.0, 4.0, 0.0), (0.0, 0.0, 12.0)))
        self.assertEqual(rmse.pair_count, 2)
        self.assertAlmostEqual(rmse.value, math.sqrt(84.5))


if __name__ == "__main__":
    unittest.main()

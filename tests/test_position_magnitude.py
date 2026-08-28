from __future__ import annotations

import math
import sys
import unittest
from dataclasses import FrozenInstanceError

from compact_vio.evaluation import (
    DISPLACEMENT_MAGNITUDE_METRIC_ID,
    DisplacementMagnitudeMetrics,
    PositionMagnitudeEvaluationError,
    RelativePoseIncrement,
    TimedPosition,
    TimedPositionPair,
    evaluate_displacement_magnitude_pairs,
    project_sensor_point_increment,
)
from compact_vio.evaluation import (
    evaluate_displacement_magnitude as _evaluate_displacement_magnitude,
)
from compact_vio.evaluation import (
    zero_motion_displacement_magnitude as _zero_motion_displacement_magnitude,
)

_ZERO_OFFSET = (0.0, 0.0, 0.0)


def evaluate_displacement_magnitude(reference, predicted):
    return _evaluate_displacement_magnitude(
        reference,
        predicted,
        sensor_origin_offset_prediction_frame_m=_ZERO_OFFSET,
    )


def zero_motion_displacement_magnitude(reference):
    return _zero_motion_displacement_magnitude(
        reference,
        sensor_origin_offset_prediction_frame_m=_ZERO_OFFSET,
    )


def _position(timestamp_ns: int, xyz: tuple[float, float, float]) -> TimedPosition:
    return TimedPosition("MH_01_easy", timestamp_ns, xyz)


def _prediction(
    sample_id: str,
    start: int,
    end: int,
    translation: tuple[float, float, float],
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> RelativePoseIncrement:
    return RelativePoseIncrement(
        sequence_id="MH_01_easy",
        sample_id=sample_id,
        start_timestamp_ns=start,
        end_timestamp_ns=end,
        translation_previous_body_m=translation,
        rotation_vector_previous_to_current_rad=rotation,
    )


class PositionMagnitudeTests(unittest.TestCase):
    def test_disjoint_preassociated_pairs_do_not_bridge_reference_gaps(self) -> None:
        pairs = (
            TimedPositionPair(
                _position(10, (0.0, 0.0, 0.0)),
                _position(20, (1.0, 0.0, 0.0)),
            ),
            TimedPositionPair(
                _position(100, (10.0, 0.0, 0.0)),
                _position(110, (12.0, 0.0, 0.0)),
            ),
        )
        predicted = (
            _prediction("a", 10, 20, (1.0, 0.0, 0.0)),
            _prediction("b", 100, 110, (2.0, 0.0, 0.0)),
        )

        result = evaluate_displacement_magnitude_pairs(
            pairs,
            predicted,
            sensor_origin_offset_prediction_frame_m=_ZERO_OFFSET,
        )

        self.assertEqual(result.pair_count, 2)
        self.assertEqual(result.pair_displacement_magnitude_rmse_m, 0.0)
        self.assertEqual(result.reference_scored_distance_m, 3.0)
        self.assertEqual(result.predicted_scored_distance_m, 3.0)

    def test_sensor_point_projection_uses_rotation_and_declared_lever_arm(self) -> None:
        pure_rotation = _prediction(
            "rotation",
            10,
            20,
            (0.0, 0.0, 0.0),
            (0.0, 0.0, math.pi / 2.0),
        )
        projected = project_sensor_point_increment(
            pure_rotation,
            sensor_origin_offset_prediction_frame_m=(1.0, 0.0, 0.0),
        )
        self.assertAlmostEqual(projected.translation_previous_body_m[0], -1.0)
        self.assertAlmostEqual(projected.translation_previous_body_m[1], 1.0)
        self.assertAlmostEqual(
            math.hypot(*projected.translation_previous_body_m),
            math.sqrt(2.0),
        )

        zero_offset = project_sensor_point_increment(
            pure_rotation,
            sensor_origin_offset_prediction_frame_m=_ZERO_OFFSET,
        )
        self.assertEqual(zero_offset.translation_previous_body_m, _ZERO_OFFSET)

        translated = project_sensor_point_increment(
            _prediction("translation", 10, 20, (1.0, -2.0, 3.0)),
            sensor_origin_offset_prediction_frame_m=(4.0, 5.0, 6.0),
        )
        self.assertEqual(translated.translation_previous_body_m, (1.0, -2.0, 3.0))

    def test_known_pair_and_cumulative_values(self) -> None:
        reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (1.0, 0.0, 0.0)),
            _position(30, (3.0, 0.0, 0.0)),
        )
        predicted = (
            _prediction("a", 10, 20, (0.0, 2.0, 0.0)),
            _prediction("b", 20, 30, (0.0, 0.0, -1.0)),
        )

        result = evaluate_displacement_magnitude(reference, predicted)

        self.assertEqual(result.metric_id, DISPLACEMENT_MAGNITUDE_METRIC_ID)
        self.assertEqual(result.sequence_id, "MH_01_easy")
        self.assertEqual(result.pair_count, 2)
        self.assertEqual(result.pair_displacement_magnitude_rmse_m, 1.0)
        self.assertAlmostEqual(result.cumulative_scored_distance_rmse_m, math.sqrt(0.5))
        self.assertEqual(result.total_scored_distance_error_m, 0.0)
        self.assertEqual(result.predicted_scored_distance_m, 3.0)
        self.assertEqual(result.reference_scored_distance_m, 3.0)
        self.assertEqual(result.scored_distance_ratio, 1.0)

    def test_perfect_stationary_chain_has_undefined_ratio(self) -> None:
        reference = (
            _position(10, (1.0, 2.0, 3.0)),
            _position(20, (1.0, 2.0, 3.0)),
        )
        result = evaluate_displacement_magnitude(
            reference,
            (_prediction("a", 10, 20, (0.0, 0.0, 0.0)),),
        )

        self.assertEqual(result.pair_displacement_magnitude_rmse_m, 0.0)
        self.assertEqual(result.cumulative_scored_distance_rmse_m, 0.0)
        self.assertEqual(result.total_scored_distance_error_m, 0.0)
        self.assertIsNone(result.scored_distance_ratio)

    def test_scaled_motion_retains_distance_scale_error(self) -> None:
        reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (1.0, 0.0, 0.0)),
            _position(30, (2.0, 0.0, 0.0)),
        )
        predicted = (
            _prediction("a", 10, 20, (2.0, 0.0, 0.0)),
            _prediction("b", 20, 30, (2.0, 0.0, 0.0)),
        )

        result = evaluate_displacement_magnitude(reference, predicted)

        self.assertEqual(result.pair_displacement_magnitude_rmse_m, 1.0)
        self.assertAlmostEqual(result.cumulative_scored_distance_rmse_m, math.sqrt(2.5))
        self.assertEqual(result.total_scored_distance_error_m, 2.0)
        self.assertEqual(result.scored_distance_ratio, 2.0)

    def test_prediction_direction_and_rotation_do_not_change_magnitude_metrics(self) -> None:
        reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (1.0, 0.0, 0.0)),
        )
        forward = (_prediction("a", 10, 20, (1.0, 0.0, 0.0)),)
        backward = (
            RelativePoseIncrement(
                sequence_id="MH_01_easy",
                sample_id="a",
                start_timestamp_ns=10,
                end_timestamp_ns=20,
                translation_previous_body_m=(-1.0, 0.0, 0.0),
                rotation_vector_previous_to_current_rad=(1.0, -2.0, 3.0),
            ),
        )

        self.assertEqual(
            evaluate_displacement_magnitude(reference, forward),
            evaluate_displacement_magnitude(reference, backward),
        )

    def test_zero_motion_baseline_uses_the_exact_reference_scope(self) -> None:
        reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (3.0, 4.0, 0.0)),
            _position(30, (3.0, 4.0, 12.0)),
        )

        baseline = zero_motion_displacement_magnitude(reference)

        self.assertEqual(baseline.sequence_id, "MH_01_easy")
        self.assertEqual(baseline.pair_count, 2)
        self.assertAlmostEqual(
            baseline.pair_displacement_magnitude_rmse_m,
            math.sqrt((5.0**2 + 12.0**2) / 2.0),
        )
        self.assertAlmostEqual(
            baseline.cumulative_scored_distance_rmse_m,
            math.sqrt((5.0**2 + 17.0**2) / 2.0),
        )
        self.assertEqual(baseline.total_scored_distance_error_m, 17.0)
        self.assertEqual(baseline.predicted_scored_distance_m, 0.0)
        self.assertEqual(baseline.reference_scored_distance_m, 17.0)
        self.assertEqual(baseline.scored_distance_ratio, 0.0)

    def test_rejects_scope_count_and_timestamp_chain_mismatches(self) -> None:
        reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (1.0, 0.0, 0.0)),
        )
        cases = (
            (
                "cover",
                reference,
                (),
            ),
            (
                "sequence_id mismatch",
                reference,
                (
                    RelativePoseIncrement(
                        "other",
                        "a",
                        10,
                        20,
                        (1.0, 0.0, 0.0),
                        (0.0, 0.0, 0.0),
                    ),
                ),
            ),
            (
                "timestamp-pair mismatch",
                reference,
                (_prediction("a", 11, 20, (1.0, 0.0, 0.0)),),
            ),
        )
        for message, positions, predictions in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(PositionMagnitudeEvaluationError, message):
                    evaluate_displacement_magnitude(positions, predictions)

        wrong_sequence = (
            reference[0],
            TimedPosition("other", 20, (1.0, 0.0, 0.0)),
        )
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "reference.*sequence_id"):
            evaluate_displacement_magnitude(wrong_sequence, ())

        reversed_time = (
            reference[0],
            TimedPosition("MH_01_easy", 9, (1.0, 0.0, 0.0)),
        )
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "strictly increasing"):
            evaluate_displacement_magnitude(reversed_time, ())

    def test_rejects_duplicate_prediction_identity(self) -> None:
        reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (1.0, 0.0, 0.0)),
            _position(30, (2.0, 0.0, 0.0)),
        )
        predicted = (
            _prediction("duplicate", 10, 20, (1.0, 0.0, 0.0)),
            _prediction("duplicate", 20, 30, (1.0, 0.0, 0.0)),
        )
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "sample_id.*unique"):
            evaluate_displacement_magnitude(reference, predicted)

    def test_extreme_finite_values_are_stable_and_domain_overflow_is_rejected(self) -> None:
        maximum = sys.float_info.max
        large_reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (maximum, 0.0, 0.0)),
        )
        result = evaluate_displacement_magnitude(
            large_reference,
            (_prediction("a", 10, 20, (maximum, 0.0, 0.0)),),
        )
        self.assertEqual(result.reference_scored_distance_m, maximum)
        self.assertEqual(result.pair_displacement_magnitude_rmse_m, 0.0)

        minimum = math.ulp(0.0)
        tiny_reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (minimum, 0.0, 0.0)),
        )
        tiny = zero_motion_displacement_magnitude(tiny_reference)
        self.assertEqual(tiny.pair_displacement_magnitude_rmse_m, minimum)
        self.assertEqual(tiny.cumulative_scored_distance_rmse_m, minimum)

        overflowing_reference = (
            _position(10, (-maximum, 0.0, 0.0)),
            _position(20, (maximum, 0.0, 0.0)),
        )
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "finite runtime domain"):
            zero_motion_displacement_magnitude(overflowing_reference)

        accumulated_overflow = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (maximum, 0.0, 0.0)),
            _position(30, (0.0, 0.0, 0.0)),
        )
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "finite runtime domain"):
            zero_motion_displacement_magnitude(accumulated_overflow)

    def test_exact_container_and_record_types_are_required_even_after_spoofing(self) -> None:
        class TupleSpoof(tuple):
            pass

        class PositionSpoof(TimedPosition):
            pass

        class IncrementSpoof(RelativePoseIncrement):
            pass

        reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (1.0, 0.0, 0.0)),
        )
        predicted = (_prediction("a", 10, 20, (1.0, 0.0, 0.0)),)

        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "exact tuple"):
            evaluate_displacement_magnitude(TupleSpoof(reference), predicted)
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "exact TimedPosition"):
            evaluate_displacement_magnitude(
                (PositionSpoof("MH_01_easy", 10, (0.0, 0.0, 0.0)), reference[1]),
                predicted,
            )
        with self.assertRaisesRegex(
            PositionMagnitudeEvaluationError,
            "exact RelativePoseIncrement",
        ):
            evaluate_displacement_magnitude(
                reference,
                (
                    IncrementSpoof(
                        "MH_01_easy",
                        "a",
                        10,
                        20,
                        (1.0, 0.0, 0.0),
                        (0.0, 0.0, 0.0),
                    ),
                ),
            )

        object.__setattr__(reference[0], "position_world_m", [0.0, 0.0, 0.0])
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "exact 3-tuple"):
            evaluate_displacement_magnitude(reference, predicted)

        fresh_reference = (
            _position(10, (0.0, 0.0, 0.0)),
            _position(20, (1.0, 0.0, 0.0)),
        )
        object.__setattr__(predicted[0], "translation_previous_body_m", (math.nan, 0.0, 0.0))
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "finite"):
            evaluate_displacement_magnitude(fresh_reference, predicted)

    def test_public_records_are_immutable_and_result_contract_rejects_forgery(self) -> None:
        position = _position(10, (0.0, 0.0, 0.0))
        with self.assertRaises(FrozenInstanceError):
            position.timestamp_ns = 11  # type: ignore[misc]

        valid = {
            "metric_id": DISPLACEMENT_MAGNITUDE_METRIC_ID,
            "sequence_id": "MH_01_easy",
            "pair_count": 1,
            "pair_displacement_magnitude_rmse_m": 0.0,
            "cumulative_scored_distance_rmse_m": 0.0,
            "total_scored_distance_error_m": 0.0,
            "predicted_scored_distance_m": 1.0,
            "reference_scored_distance_m": 1.0,
            "scored_distance_ratio": 1.0,
            "sensor_origin_offset_prediction_frame_m": _ZERO_OFFSET,
        }
        invalid_values = (
            ("metric_id", "aligned-ate", "metric_id"),
            ("sequence_id", " ", "sequence_id"),
            ("pair_count", True, "pair_count"),
            ("pair_count", 0, "pair_count"),
            ("pair_displacement_magnitude_rmse_m", 0, "pair_displacement"),
            ("cumulative_scored_distance_rmse_m", -1.0, "cumulative_scored"),
            ("total_scored_distance_error_m", math.nan, "total_scored"),
            ("predicted_scored_distance_m", math.inf, "predicted_scored"),
            ("scored_distance_ratio", None, "scored_distance_ratio"),
            ("scored_distance_ratio", 2.0, "scored_distance_ratio"),
        )
        for field, invalid, message in invalid_values:
            with self.subTest(field=field, invalid=invalid):
                changed = dict(valid)
                changed[field] = invalid
                with self.assertRaisesRegex(PositionMagnitudeEvaluationError, message):
                    DisplacementMagnitudeMetrics(**changed)  # type: ignore[arg-type]

        inconsistent_drift = dict(valid)
        inconsistent_drift["total_scored_distance_error_m"] = 1.0
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "scored-distance difference"):
            DisplacementMagnitudeMetrics(**inconsistent_drift)  # type: ignore[arg-type]

        stationary = dict(valid)
        stationary.update(
            predicted_scored_distance_m=0.0,
            reference_scored_distance_m=0.0,
            scored_distance_ratio=0.0,
        )
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "must be None"):
            DisplacementMagnitudeMetrics(**stationary)  # type: ignore[arg-type]

    def test_timed_position_rejects_nonfinite_and_inexact_public_values(self) -> None:
        invalid_positions = (
            ([0.0, 0.0, 0.0], "exact 3-tuple"),
            ((True, 0.0, 0.0), "finite built-in real"),
            ((math.nan, 0.0, 0.0), "finite"),
            ((2**54 + 1, 0.0, 0.0), "exactly representable"),
        )
        for value, message in invalid_positions:
            with self.subTest(value=value):
                with self.assertRaisesRegex(PositionMagnitudeEvaluationError, message):
                    TimedPosition("MH_01_easy", 10, value)  # type: ignore[arg-type]
        with self.assertRaisesRegex(PositionMagnitudeEvaluationError, "timestamp_ns"):
            TimedPosition("MH_01_easy", True, (0.0, 0.0, 0.0))


if __name__ == "__main__":
    unittest.main()

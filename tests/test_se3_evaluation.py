from __future__ import annotations

import math
import unittest

from compact_vio.evaluation.se3 import (
    RelativePoseIncrement,
    Se3EvaluationError,
    evaluate_relative_pose_sequence,
    rotation_vector_to_matrix,
    zero_motion_baseline,
)


def _increment(
    sample_id: str,
    start: int,
    end: int,
    translation: tuple[float, float, float],
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
) -> RelativePoseIncrement:
    return RelativePoseIncrement("V2_03_difficult", sample_id, start, end, translation, rotation)


class Se3EvaluationTests(unittest.TestCase):
    def test_zero_motion_baseline_preserves_reference_scope(self) -> None:
        reference = (
            _increment("a", 0, 1, (1.0, 0.0, 0.0)),
            _increment("b", 1, 2, (1.0, 0.0, 0.0)),
        )

        baseline = zero_motion_baseline(reference)

        self.assertEqual(baseline.sequence_id, "V2_03_difficult")
        self.assertEqual(baseline.pair_count, 2)
        self.assertEqual(baseline.predicted_path_length_m, 0.0)
        self.assertEqual(baseline.reference_path_length_m, 2.0)
        self.assertEqual(baseline.relative_translation_rmse_m, 1.0)
        self.assertEqual(baseline.expected_pair_count, 2)
        self.assertEqual(baseline.produced_pair_count, 2)
        self.assertEqual(baseline.failed_pair_count, 0)
        self.assertEqual(baseline.coverage_fraction, 1.0)
        self.assertTrue(baseline.complete)

    def test_perfect_sequence_is_zero(self) -> None:
        reference = (
            _increment("a", 0, 1, (1.0, 0.0, 0.0)),
            _increment("b", 1, 2, (1.0, 0.0, 0.0)),
        )
        result = evaluate_relative_pose_sequence(reference, reference)
        self.assertEqual(result.raw_translation_ate_rmse_m, 0.0)
        self.assertEqual(result.relative_rotation_rmse_rad, 0.0)
        self.assertEqual(result.final_rotation_drift_rad, 0.0)
        self.assertEqual(result.reference_path_length_m, 2.0)

    def test_raw_metric_does_not_align_constant_error(self) -> None:
        reference = (
            _increment("a", 0, 1, (1.0, 0.0, 0.0)),
            _increment("b", 1, 2, (1.0, 0.0, 0.0)),
        )
        predicted = (
            _increment("a", 0, 1, (2.0, 0.0, 0.0)),
            _increment("b", 1, 2, (2.0, 0.0, 0.0)),
        )
        result = evaluate_relative_pose_sequence(reference, predicted)
        self.assertAlmostEqual(result.raw_translation_ate_rmse_m, math.sqrt(2.5))
        self.assertEqual(result.final_translation_drift_m, 2.0)

    def test_rotation_error_is_retained(self) -> None:
        reference = (_increment("a", 0, 1, (0.0, 0.0, 0.0)),)
        predicted = (_increment("a", 0, 1, (0.0, 0.0, 0.0), (0.0, 0.0, math.pi / 2)),)
        result = evaluate_relative_pose_sequence(reference, predicted)
        self.assertAlmostEqual(result.relative_rotation_rmse_rad, math.pi / 2)
        self.assertAlmostEqual(result.final_rotation_drift_rad, math.pi / 2)

    def test_cumulative_pose_uses_previous_body_rotation_without_alignment(self) -> None:
        reference = (
            _increment("a", 0, 1, (1.0, 0.0, 0.0), (0.0, 0.0, math.pi / 2)),
            _increment("b", 1, 2, (1.0, 0.0, 0.0)),
        )
        predicted = (
            _increment("a", 0, 1, (1.0, 0.0, 0.0)),
            _increment("b", 1, 2, (1.0, 0.0, 0.0)),
        )

        result = evaluate_relative_pose_sequence(reference, predicted)

        self.assertEqual(result.relative_translation_rmse_m, 0.0)
        self.assertGreater(result.raw_translation_ate_rmse_m, 0.0)
        self.assertAlmostEqual(result.final_translation_drift_m, math.sqrt(2.0))
        self.assertAlmostEqual(result.final_rotation_drift_rad, math.pi / 2)

    def test_rejects_implicit_pairing(self) -> None:
        reference = (_increment("a", 0, 1, (0.0, 0.0, 0.0)),)
        predicted = (_increment("b", 0, 1, (0.0, 0.0, 0.0)),)
        with self.assertRaisesRegex(Se3EvaluationError, "identity mismatch"):
            evaluate_relative_pose_sequence(reference, predicted)

    def test_rotation_vector_matrix_is_right_handed(self) -> None:
        matrix = rotation_vector_to_matrix((0.0, 0.0, math.pi / 2))
        self.assertAlmostEqual(matrix[0][1], -1.0)
        self.assertAlmostEqual(matrix[1][0], 1.0)


if __name__ == "__main__":
    unittest.main()

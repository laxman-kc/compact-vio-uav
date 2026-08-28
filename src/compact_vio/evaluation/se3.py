"""Unaligned SE(3) metrics for sequence-ordered relative-pose predictions."""

from __future__ import annotations

import math
from dataclasses import dataclass

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]
_IDENTITY: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class Se3EvaluationError(ValueError):
    """Raised when trajectory inputs cannot be compared without guessing."""


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise Se3EvaluationError(f"{field} must be a non-empty string")
    return value


def _vector(value: object, field: str) -> Vector3:
    if type(value) is not tuple or len(value) != 3:
        raise Se3EvaluationError(f"{field} must be an exact 3-tuple")
    if any(
        type(component) not in (int, float) or not math.isfinite(float(component))
        for component in value
    ):
        raise Se3EvaluationError(f"{field} components must be finite real numbers")
    result = tuple(float(component) for component in value)
    return result  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class RelativePoseIncrement:
    sequence_id: str
    sample_id: str
    start_timestamp_ns: int
    end_timestamp_ns: int
    translation_previous_body_m: Vector3
    rotation_vector_previous_to_current_rad: Vector3

    def __post_init__(self) -> None:
        _text(self.sequence_id, "sequence_id")
        _text(self.sample_id, "sample_id")
        if type(self.start_timestamp_ns) is not int or self.start_timestamp_ns < 0:
            raise Se3EvaluationError("start_timestamp_ns must be a non-negative integer")
        if (
            type(self.end_timestamp_ns) is not int
            or self.end_timestamp_ns <= self.start_timestamp_ns
        ):
            raise Se3EvaluationError("end_timestamp_ns must be greater than start_timestamp_ns")
        _vector(self.translation_previous_body_m, "translation_previous_body_m")
        _vector(
            self.rotation_vector_previous_to_current_rad,
            "rotation_vector_previous_to_current_rad",
        )


@dataclass(frozen=True, slots=True)
class SequencePoseMetrics:
    metric_id: str
    sequence_id: str
    pair_count: int
    raw_translation_ate_rmse_m: float
    relative_translation_rmse_m: float
    relative_rotation_rmse_rad: float
    final_translation_drift_m: float
    predicted_path_length_m: float
    reference_path_length_m: float

    def __post_init__(self) -> None:
        if self.metric_id != "se3/raw-no-alignment/exact-sequence-pairs/v1":
            raise Se3EvaluationError("metric_id is not the exact raw SE(3) metric identifier")
        _text(self.sequence_id, "sequence_id")
        if type(self.pair_count) is not int or self.pair_count <= 0:
            raise Se3EvaluationError("pair_count must be positive")
        for field in (
            "raw_translation_ate_rmse_m",
            "relative_translation_rmse_m",
            "relative_rotation_rmse_rad",
            "final_translation_drift_m",
            "predicted_path_length_m",
            "reference_path_length_m",
        ):
            value = getattr(self, field)
            if type(value) is not float or not math.isfinite(value) or value < 0.0:
                raise Se3EvaluationError(f"{field} must be a finite non-negative float")


def _matmul(left: Matrix3, right: Matrix3) -> Matrix3:
    return tuple(
        tuple(
            math.fsum(left[row][index] * right[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _transpose(matrix: Matrix3) -> Matrix3:
    return tuple(tuple(matrix[column][row] for column in range(3)) for row in range(3))  # type: ignore[return-value]


def _matvec(matrix: Matrix3, vector: Vector3) -> Vector3:
    return tuple(
        math.fsum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3)
    )  # type: ignore[return-value]


def _add(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a + b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a - b for a, b in zip(left, right, strict=True))  # type: ignore[return-value]


def _norm(vector: Vector3) -> float:
    return math.hypot(*vector)


def rotation_vector_to_matrix(rotation_vector: Vector3) -> Matrix3:
    """Map one finite axis-angle vector to SO(3) with Rodrigues' formula."""

    vector = _vector(rotation_vector, "rotation_vector")
    angle = _norm(vector)
    if angle < 1e-10:
        x, y, z = vector
        return ((1.0, -z, y), (z, 1.0, -x), (-y, x, 1.0))
    x, y, z = (component / angle for component in vector)
    sine = math.sin(angle)
    cosine = math.cos(angle)
    one_minus = 1.0 - cosine
    return (
        (
            cosine + x * x * one_minus,
            x * y * one_minus - z * sine,
            x * z * one_minus + y * sine,
        ),
        (
            y * x * one_minus + z * sine,
            cosine + y * y * one_minus,
            y * z * one_minus - x * sine,
        ),
        (
            z * x * one_minus - y * sine,
            z * y * one_minus + x * sine,
            cosine + z * z * one_minus,
        ),
    )


def _rotation_error_rad(reference: Matrix3, predicted: Matrix3) -> float:
    error = _matmul(_transpose(reference), predicted)
    cosine = min(
        1.0,
        max(-1.0, (error[0][0] + error[1][1] + error[2][2] - 1.0) / 2.0),
    )
    return math.acos(cosine)


def _rmse(values: list[float]) -> float:
    maximum = max(values)
    if maximum == 0.0:
        return 0.0
    scaled = math.fsum((value / maximum) ** 2 for value in values)
    result = maximum * math.sqrt(scaled / len(values))
    if not math.isfinite(result):
        raise Se3EvaluationError("metric is outside the finite runtime domain")
    return result


def evaluate_relative_pose_sequence(
    reference: tuple[RelativePoseIncrement, ...],
    predicted: tuple[RelativePoseIncrement, ...],
) -> SequencePoseMetrics:
    """Evaluate exact paired motion with no association, alignment, or scale fitting."""

    if type(reference) is not tuple or type(predicted) is not tuple or not reference:
        raise Se3EvaluationError("reference and predicted must be non-empty exact tuples")
    if len(reference) != len(predicted):
        raise Se3EvaluationError("reference and predicted pair counts differ")
    if any(type(item) is not RelativePoseIncrement for item in (*reference, *predicted)):
        raise Se3EvaluationError("inputs must contain exact RelativePoseIncrement records")
    sequence_id = reference[0].sequence_id
    seen: set[str] = set()
    previous_end: int | None = None
    for index, (truth, estimate) in enumerate(zip(reference, predicted, strict=True)):
        if truth.sequence_id != sequence_id or estimate.sequence_id != sequence_id:
            raise Se3EvaluationError("all increments must share one sequence_id")
        identity = (truth.sample_id, truth.start_timestamp_ns, truth.end_timestamp_ns)
        estimate_identity = (
            estimate.sample_id,
            estimate.start_timestamp_ns,
            estimate.end_timestamp_ns,
        )
        if identity != estimate_identity:
            raise Se3EvaluationError(f"increment identity mismatch at index {index}")
        if truth.sample_id in seen:
            raise Se3EvaluationError("sample_id values must be unique")
        if previous_end is not None and truth.start_timestamp_ns < previous_end:
            raise Se3EvaluationError("increments must be in non-overlapping sequence order")
        seen.add(truth.sample_id)
        previous_end = truth.end_timestamp_ns

    reference_rotation = _IDENTITY
    predicted_rotation = _IDENTITY
    reference_position: Vector3 = (0.0, 0.0, 0.0)
    predicted_position: Vector3 = (0.0, 0.0, 0.0)
    endpoint_errors: list[float] = []
    translation_errors: list[float] = []
    rotation_errors: list[float] = []
    reference_length = 0.0
    predicted_length = 0.0

    for truth, estimate in zip(reference, predicted, strict=True):
        truth_translation = _vector(truth.translation_previous_body_m, "truth translation")
        estimate_translation = _vector(estimate.translation_previous_body_m, "estimate translation")
        reference_position = _add(
            reference_position, _matvec(reference_rotation, truth_translation)
        )
        predicted_position = _add(
            predicted_position, _matvec(predicted_rotation, estimate_translation)
        )
        truth_delta_rotation = rotation_vector_to_matrix(
            truth.rotation_vector_previous_to_current_rad
        )
        estimate_delta_rotation = rotation_vector_to_matrix(
            estimate.rotation_vector_previous_to_current_rad
        )
        reference_rotation = _matmul(reference_rotation, truth_delta_rotation)
        predicted_rotation = _matmul(predicted_rotation, estimate_delta_rotation)
        endpoint_errors.append(_norm(_subtract(predicted_position, reference_position)))
        translation_errors.append(_norm(_subtract(estimate_translation, truth_translation)))
        rotation_errors.append(_rotation_error_rad(truth_delta_rotation, estimate_delta_rotation))
        reference_length += _norm(truth_translation)
        predicted_length += _norm(estimate_translation)

    return SequencePoseMetrics(
        metric_id="se3/raw-no-alignment/exact-sequence-pairs/v1",
        sequence_id=sequence_id,
        pair_count=len(reference),
        raw_translation_ate_rmse_m=_rmse(endpoint_errors),
        relative_translation_rmse_m=_rmse(translation_errors),
        relative_rotation_rmse_rad=_rmse(rotation_errors),
        final_translation_drift_m=endpoint_errors[-1],
        predicted_path_length_m=float(predicted_length),
        reference_path_length_m=float(reference_length),
    )

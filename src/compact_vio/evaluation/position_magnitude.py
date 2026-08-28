"""Exact-chain sensor-point displacement metrics requiring no reference orientation.

This primitive compares scalar distance travelled by the same rigid-body sensor point
over each reference interval. Reference increments are Euclidean differences between
consecutive world positions. A prediction is projected from the learned model's source
sensor origin to the Leica origin with the declared constant lever arm and the model's
predicted relative rotation before its norm is compared. No reference orientation is
guessed or reconstructed.

This is intentionally *not* a spatial trajectory metric.  It cannot measure ATE,
heading error, final-position error, or motion-direction correctness: equal-length
translations in different (even opposite) directions are indistinguishable.  The
``total_scored_distance_error_m`` field is absolute accumulated-distance error over
the retained pair intervals, not Euclidean final-pose drift or a full-sequence path.
Inputs are neither filtered, associated, interpolated, aligned, nor rescaled inside
this primitive. ``scored_distance_ratio`` is ``None`` when the retained reference
distance is zero because that ratio is undefined.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from compact_vio.evaluation.se3 import RelativePoseIncrement, rotation_vector_to_matrix

Vector3 = tuple[float, float, float]

DISPLACEMENT_MAGNITUDE_METRIC_ID = (
    "sensor-point-displacement-magnitude/exact-preassociated-position-pairs/"
    "predicted-rotation-and-declared-lever-arm/no-reference-orientation/"
    "preassociated-input/no-internal-interpolation/no-alignment/no-scale-fitting/v1"
)


class PositionMagnitudeEvaluationError(ValueError):
    """Raised when displacement magnitude cannot be evaluated without guessing."""


def _require_text(value: object, *, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise PositionMagnitudeEvaluationError(f"{field} must be a non-empty string")
    return value


def _runtime_float(value: object, *, field: str) -> float:
    if type(value) not in (int, float):
        raise PositionMagnitudeEvaluationError(f"{field} must be a finite built-in real number")
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise PositionMagnitudeEvaluationError(
            f"{field} must be finite and representable by this runtime"
        ) from error
    if not math.isfinite(result):
        raise PositionMagnitudeEvaluationError(
            f"{field} must be finite and representable by this runtime"
        )
    if type(value) is int and int(result) != value:
        raise PositionMagnitudeEvaluationError(
            f"{field} integer must be exactly representable by this runtime"
        )
    return result


def _vector(value: object, *, field: str) -> Vector3:
    if type(value) is not tuple or len(value) != 3:
        raise PositionMagnitudeEvaluationError(f"{field} must be an exact 3-tuple")
    return (
        _runtime_float(value[0], field=f"{field}[0]"),
        _runtime_float(value[1], field=f"{field}[1]"),
        _runtime_float(value[2], field=f"{field}[2]"),
    )


def _require_non_negative_float(value: object, *, field: str) -> float:
    if type(value) is not float or not math.isfinite(value) or value < 0.0:
        raise PositionMagnitudeEvaluationError(f"{field} must be a finite non-negative float")
    return value


@dataclass(frozen=True, slots=True)
class TimedPosition:
    """One exact timestamped world position in metres.

    The record deliberately carries no orientation.  ``position_world_m`` must be
    an exact built-in tuple with three finite built-in real components.
    """

    sequence_id: str
    timestamp_ns: int
    position_world_m: Vector3

    def __post_init__(self) -> None:
        _validate_timed_position_fields(self)


@dataclass(frozen=True, slots=True)
class TimedPositionPair:
    """One exact ordered position interval; separate pairs may have gaps."""

    previous: TimedPosition
    current: TimedPosition

    def __post_init__(self) -> None:
        if type(self.previous) is not TimedPosition or type(self.current) is not TimedPosition:
            raise PositionMagnitudeEvaluationError(
                "position-pair endpoints must be exact TimedPosition records"
            )
        previous_sequence, previous_time, _ = _validate_timed_position_fields(self.previous)
        current_sequence, current_time, _ = _validate_timed_position_fields(self.current)
        if previous_sequence != current_sequence:
            raise PositionMagnitudeEvaluationError(
                "position-pair endpoints must share one sequence_id"
            )
        if current_time <= previous_time:
            raise PositionMagnitudeEvaluationError(
                "position-pair current timestamp must follow previous timestamp"
            )


@dataclass(frozen=True, slots=True)
class DisplacementMagnitudeMetrics:
    """Distance-only metrics for one exact timestamp chain.

    ``cumulative_scored_distance_rmse_m`` compares accumulated travelled distance
    across retained intervals. ``total_scored_distance_error_m`` compares the two
    final retained-distance totals; it is not a spatial endpoint error.
    """

    metric_id: str
    sequence_id: str
    pair_count: int
    pair_displacement_magnitude_rmse_m: float
    cumulative_scored_distance_rmse_m: float
    total_scored_distance_error_m: float
    predicted_scored_distance_m: float
    reference_scored_distance_m: float
    scored_distance_ratio: float | None
    sensor_origin_offset_prediction_frame_m: Vector3

    def __post_init__(self) -> None:
        if self.metric_id != DISPLACEMENT_MAGNITUDE_METRIC_ID:
            raise PositionMagnitudeEvaluationError(
                "metric_id must be the exact displacement-magnitude metric identifier"
            )
        _require_text(self.sequence_id, field="sequence_id")
        if type(self.pair_count) is not int or self.pair_count <= 0:
            raise PositionMagnitudeEvaluationError("pair_count must be a positive integer")
        for field in (
            "pair_displacement_magnitude_rmse_m",
            "cumulative_scored_distance_rmse_m",
            "total_scored_distance_error_m",
            "predicted_scored_distance_m",
            "reference_scored_distance_m",
        ):
            _require_non_negative_float(getattr(self, field), field=field)

        expected_drift = abs(self.predicted_scored_distance_m - self.reference_scored_distance_m)
        if self.total_scored_distance_error_m != expected_drift:
            raise PositionMagnitudeEvaluationError(
                "total_scored_distance_error_m must equal the absolute scored-distance difference"
            )

        if self.reference_scored_distance_m == 0.0:
            if self.scored_distance_ratio is not None:
                raise PositionMagnitudeEvaluationError(
                    "scored_distance_ratio must be None when reference scored distance is zero"
                )
        else:
            ratio = _require_non_negative_float(
                self.scored_distance_ratio,
                field="scored_distance_ratio",
            )
            expected_ratio = self.predicted_scored_distance_m / self.reference_scored_distance_m
            if not math.isfinite(expected_ratio):
                raise PositionMagnitudeEvaluationError(
                    "scored_distance_ratio is outside the finite runtime domain"
                )
            if ratio != expected_ratio:
                raise PositionMagnitudeEvaluationError(
                    "scored_distance_ratio must equal predicted / reference scored distance"
                )
        _vector(
            self.sensor_origin_offset_prediction_frame_m,
            field="sensor_origin_offset_prediction_frame_m",
        )


def _validate_timed_position_fields(position: TimedPosition) -> tuple[str, int, Vector3]:
    try:
        sequence_id = position.sequence_id
        timestamp_ns = position.timestamp_ns
        position_world_m = position.position_world_m
    except AttributeError as error:
        raise PositionMagnitudeEvaluationError("TimedPosition record is incomplete") from error
    _require_text(sequence_id, field="sequence_id")
    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise PositionMagnitudeEvaluationError("timestamp_ns must be a non-negative integer")
    return sequence_id, timestamp_ns, _vector(position_world_m, field="position_world_m")


def _validate_relative_increment_fields(
    increment: RelativePoseIncrement,
) -> tuple[str, str, int, int, Vector3, Vector3]:
    try:
        sequence_id = increment.sequence_id
        sample_id = increment.sample_id
        start_timestamp_ns = increment.start_timestamp_ns
        end_timestamp_ns = increment.end_timestamp_ns
        translation = increment.translation_previous_body_m
        rotation = increment.rotation_vector_previous_to_current_rad
    except AttributeError as error:
        raise PositionMagnitudeEvaluationError(
            "RelativePoseIncrement record is incomplete"
        ) from error
    _require_text(sequence_id, field="predicted sequence_id")
    _require_text(sample_id, field="predicted sample_id")
    if type(start_timestamp_ns) is not int or start_timestamp_ns < 0:
        raise PositionMagnitudeEvaluationError(
            "predicted start_timestamp_ns must be a non-negative integer"
        )
    if type(end_timestamp_ns) is not int or end_timestamp_ns <= start_timestamp_ns:
        raise PositionMagnitudeEvaluationError(
            "predicted end_timestamp_ns must be greater than start_timestamp_ns"
        )
    validated_translation = _vector(
        translation,
        field="predicted translation_previous_body_m",
    )
    validated_rotation = _vector(
        rotation,
        field="predicted rotation_vector_previous_to_current_rad",
    )
    return (
        sequence_id,
        sample_id,
        start_timestamp_ns,
        end_timestamp_ns,
        validated_translation,
        validated_rotation,
    )


def _finite_difference(left: float, right: float, *, field: str) -> float:
    result = left - right
    if not math.isfinite(result):
        raise PositionMagnitudeEvaluationError(
            f"{field} difference is outside the finite runtime domain"
        )
    return result


def _magnitude(vector: Vector3, *, field: str) -> float:
    result = math.hypot(*vector)
    if not math.isfinite(result):
        raise PositionMagnitudeEvaluationError(
            f"{field} magnitude is outside the finite runtime domain"
        )
    if result == 0.0 and any(component != 0.0 for component in vector):
        raise PositionMagnitudeEvaluationError(
            f"{field} magnitude underflows the finite runtime domain"
        )
    return result


def _sensor_point_translation(
    translation: Vector3,
    rotation_vector: Vector3,
    sensor_origin_offset: Vector3,
    *,
    field: str,
) -> Vector3:
    """Project source-sensor motion to a fixed target-sensor origin.

    If ``r`` is the target-sensor origin expressed in the source sensor frame,
    the target point moves by ``t + R*r - r`` in the previous source frame.
    """

    rotation = rotation_vector_to_matrix(rotation_vector)
    rotated_offset = tuple(
        math.fsum(rotation[row][column] * sensor_origin_offset[column] for column in range(3))
        for row in range(3)
    )
    projected = tuple(
        math.fsum((translation[index], rotated_offset[index], -sensor_origin_offset[index]))
        for index in range(3)
    )
    if any(not math.isfinite(component) for component in projected):
        raise PositionMagnitudeEvaluationError(
            f"{field} sensor-point translation is outside the finite runtime domain"
        )
    return projected  # type: ignore[return-value]


def project_sensor_point_increment(
    increment: RelativePoseIncrement,
    *,
    sensor_origin_offset_prediction_frame_m: Vector3,
) -> RelativePoseIncrement:
    """Return one increment translated to the declared rigid sensor point."""

    if type(increment) is not RelativePoseIncrement:
        raise PositionMagnitudeEvaluationError(
            "increment must be an exact RelativePoseIncrement record"
        )
    (
        sequence_id,
        sample_id,
        start_timestamp_ns,
        end_timestamp_ns,
        translation,
        rotation_vector,
    ) = _validate_relative_increment_fields(increment)
    offset = _vector(
        sensor_origin_offset_prediction_frame_m,
        field="sensor_origin_offset_prediction_frame_m",
    )
    return RelativePoseIncrement(
        sequence_id=sequence_id,
        sample_id=sample_id,
        start_timestamp_ns=start_timestamp_ns,
        end_timestamp_ns=end_timestamp_ns,
        translation_previous_body_m=_sensor_point_translation(
            translation,
            rotation_vector,
            offset,
            field="predicted",
        ),
        rotation_vector_previous_to_current_rad=rotation_vector,
    )


class _FiniteNonNegativeSum:
    """Incremental partials sum with a stable observable value."""

    __slots__ = ("_partials", "_field")

    def __init__(self, field: str) -> None:
        self._partials: list[float] = []
        self._field = field

    def add(self, value: float) -> float:
        partials: list[float] = []
        high = value
        for low in self._partials:
            if abs(high) < abs(low):
                high, low = low, high
            combined = high + low
            if not math.isfinite(combined):
                raise PositionMagnitudeEvaluationError(
                    f"{self._field} is outside the finite runtime domain"
                )
            remainder = low - (combined - high)
            if remainder != 0.0:
                partials.append(remainder)
            high = combined
        partials.append(high)
        self._partials = partials
        try:
            result = math.fsum(partials)
        except OverflowError as error:
            raise PositionMagnitudeEvaluationError(
                f"{self._field} is outside the finite runtime domain"
            ) from error
        if not math.isfinite(result):
            raise PositionMagnitudeEvaluationError(
                f"{self._field} is outside the finite runtime domain"
            )
        return result


def _stable_rmse(values: list[float], *, field: str) -> float:
    maximum = max(values)
    if maximum == 0.0:
        return 0.0
    try:
        scaled_sum_squares = math.fsum((value / maximum) ** 2 for value in values)
    except OverflowError as error:
        raise PositionMagnitudeEvaluationError(
            f"{field} is outside the finite runtime domain"
        ) from error
    result = maximum * math.sqrt(scaled_sum_squares / len(values))
    if not math.isfinite(result):
        raise PositionMagnitudeEvaluationError(f"{field} is outside the finite runtime domain")
    if result == 0.0:
        raise PositionMagnitudeEvaluationError(f"{field} underflows the finite runtime domain")
    return result


def _validate_reference_positions(
    reference_positions: tuple[TimedPosition, ...],
) -> tuple[str, tuple[tuple[int, Vector3], ...]]:
    if type(reference_positions) is not tuple or len(reference_positions) < 2:
        raise PositionMagnitudeEvaluationError(
            "reference_positions must be an exact tuple containing at least two positions"
        )
    if any(type(position) is not TimedPosition for position in reference_positions):
        raise PositionMagnitudeEvaluationError(
            "reference_positions must contain only exact TimedPosition records"
        )

    validated: list[tuple[int, Vector3]] = []
    sequence_id: str | None = None
    previous_timestamp: int | None = None
    for position in reference_positions:
        item_sequence_id, timestamp_ns, vector = _validate_timed_position_fields(position)
        if sequence_id is None:
            sequence_id = item_sequence_id
        elif item_sequence_id != sequence_id:
            raise PositionMagnitudeEvaluationError(
                "all reference positions must share one exact sequence_id"
            )
        if previous_timestamp is not None and timestamp_ns <= previous_timestamp:
            raise PositionMagnitudeEvaluationError(
                "reference position timestamps must be strictly increasing"
            )
        validated.append((timestamp_ns, vector))
        previous_timestamp = timestamp_ns
    if sequence_id is None:  # Defensive; length was already checked above.
        raise PositionMagnitudeEvaluationError("reference position sequence is empty")
    return sequence_id, tuple(validated)


def _validate_reference_pairs(
    reference_pairs: tuple[TimedPositionPair, ...],
) -> tuple[str, tuple[tuple[int, int, Vector3, Vector3], ...]]:
    if type(reference_pairs) is not tuple or not reference_pairs:
        raise PositionMagnitudeEvaluationError("reference_pairs must be a non-empty exact tuple")
    if any(type(pair) is not TimedPositionPair for pair in reference_pairs):
        raise PositionMagnitudeEvaluationError(
            "reference_pairs must contain only exact TimedPositionPair records"
        )
    sequence_id: str | None = None
    previous_end: int | None = None
    validated: list[tuple[int, int, Vector3, Vector3]] = []
    identities: set[tuple[int, int]] = set()
    for pair in reference_pairs:
        previous_sequence, start, previous_position = _validate_timed_position_fields(pair.previous)
        current_sequence, end, current_position = _validate_timed_position_fields(pair.current)
        if previous_sequence != current_sequence or end <= start:
            raise PositionMagnitudeEvaluationError(
                "each reference pair must share one sequence and increase in time"
            )
        if sequence_id is None:
            sequence_id = previous_sequence
        elif previous_sequence != sequence_id:
            raise PositionMagnitudeEvaluationError(
                "all reference pairs must share one exact sequence_id"
            )
        if previous_end is not None and start < previous_end:
            raise PositionMagnitudeEvaluationError(
                "reference pairs must be in non-overlapping timestamp order"
            )
        identity = (start, end)
        if identity in identities:
            raise PositionMagnitudeEvaluationError("reference pair identities must be unique")
        identities.add(identity)
        previous_end = end
        validated.append((start, end, previous_position, current_position))
    if sequence_id is None:
        raise PositionMagnitudeEvaluationError("reference pair set is empty")
    return sequence_id, tuple(validated)


def evaluate_displacement_magnitude_pairs(
    reference_pairs: tuple[TimedPositionPair, ...],
    predicted: tuple[RelativePoseIncrement, ...],
    *,
    sensor_origin_offset_prediction_frame_m: Vector3,
) -> DisplacementMagnitudeMetrics:
    """Evaluate exact preassociated sensor-point displacement pairs.

    Separate pairs may have declared gaps, but may not overlap or reorder. Each
    prediction must have the same sequence and exact start/end timestamps. No
    missing/extra prediction, timestamp association,
    interpolation, reference orientation, alignment, or scale fitting is permitted.
    Predicted relative rotation is used only to move the declared rigid lever arm.
    """

    sequence_id, reference = _validate_reference_pairs(reference_pairs)
    sensor_origin_offset = _vector(
        sensor_origin_offset_prediction_frame_m,
        field="sensor_origin_offset_prediction_frame_m",
    )
    pair_count = len(reference)
    if type(predicted) is not tuple:
        raise PositionMagnitudeEvaluationError("predicted must be an exact tuple")
    if len(predicted) != pair_count:
        raise PositionMagnitudeEvaluationError(
            "predicted must exactly cover every declared reference pair"
        )
    if any(type(increment) is not RelativePoseIncrement for increment in predicted):
        raise PositionMagnitudeEvaluationError(
            "predicted must contain only exact RelativePoseIncrement records"
        )

    reference_sum = _FiniteNonNegativeSum("reference_scored_distance_m")
    predicted_sum = _FiniteNonNegativeSum("predicted_scored_distance_m")
    pair_errors: list[float] = []
    cumulative_errors: list[float] = []
    seen_sample_ids: set[str] = set()

    for index, increment in enumerate(predicted):
        (
            increment_sequence_id,
            sample_id,
            start_timestamp_ns,
            end_timestamp_ns,
            predicted_translation,
            predicted_rotation,
        ) = _validate_relative_increment_fields(increment)
        expected_start, expected_end, previous_position, current_position = reference[index]
        if increment_sequence_id != sequence_id:
            raise PositionMagnitudeEvaluationError(
                f"predicted sequence_id mismatch at index {index}"
            )
        if (start_timestamp_ns, end_timestamp_ns) != (expected_start, expected_end):
            raise PositionMagnitudeEvaluationError(
                f"predicted timestamp-pair mismatch at index {index}"
            )
        if sample_id in seen_sample_ids:
            raise PositionMagnitudeEvaluationError("predicted sample_id values must be unique")
        seen_sample_ids.add(sample_id)

        reference_delta = (
            _finite_difference(
                current_position[0],
                previous_position[0],
                field=f"reference interval {index} x",
            ),
            _finite_difference(
                current_position[1],
                previous_position[1],
                field=f"reference interval {index} y",
            ),
            _finite_difference(
                current_position[2],
                previous_position[2],
                field=f"reference interval {index} z",
            ),
        )
        reference_magnitude = _magnitude(
            reference_delta,
            field=f"reference interval {index}",
        )
        predicted_sensor_translation = _sensor_point_translation(
            predicted_translation,
            predicted_rotation,
            sensor_origin_offset,
            field=f"predicted interval {index}",
        )
        predicted_magnitude = _magnitude(
            predicted_sensor_translation,
            field=f"predicted interval {index}",
        )
        pair_errors.append(abs(predicted_magnitude - reference_magnitude))
        cumulative_reference = reference_sum.add(reference_magnitude)
        cumulative_predicted = predicted_sum.add(predicted_magnitude)
        cumulative_errors.append(abs(cumulative_predicted - cumulative_reference))

    reference_scored_distance = reference_sum.add(0.0)
    predicted_scored_distance = predicted_sum.add(0.0)
    total_scored_distance_error = abs(predicted_scored_distance - reference_scored_distance)
    if reference_scored_distance == 0.0:
        scored_distance_ratio: float | None = None
    else:
        scored_distance_ratio = predicted_scored_distance / reference_scored_distance
        if not math.isfinite(scored_distance_ratio):
            raise PositionMagnitudeEvaluationError(
                "scored_distance_ratio is outside the finite runtime domain"
            )

    return DisplacementMagnitudeMetrics(
        metric_id=DISPLACEMENT_MAGNITUDE_METRIC_ID,
        sequence_id=sequence_id,
        pair_count=pair_count,
        pair_displacement_magnitude_rmse_m=_stable_rmse(
            pair_errors,
            field="pair_displacement_magnitude_rmse_m",
        ),
        cumulative_scored_distance_rmse_m=_stable_rmse(
            cumulative_errors,
            field="cumulative_scored_distance_rmse_m",
        ),
        total_scored_distance_error_m=float(total_scored_distance_error),
        predicted_scored_distance_m=float(predicted_scored_distance),
        reference_scored_distance_m=float(reference_scored_distance),
        scored_distance_ratio=scored_distance_ratio,
        sensor_origin_offset_prediction_frame_m=sensor_origin_offset,
    )


def evaluate_displacement_magnitude(
    reference_positions: tuple[TimedPosition, ...],
    predicted: tuple[RelativePoseIncrement, ...],
    *,
    sensor_origin_offset_prediction_frame_m: Vector3,
) -> DisplacementMagnitudeMetrics:
    """Convenience wrapper for one exact consecutive position chain."""

    _validate_reference_positions(reference_positions)
    pairs = tuple(
        TimedPositionPair(previous, current)
        for previous, current in zip(reference_positions, reference_positions[1:], strict=False)
    )
    return evaluate_displacement_magnitude_pairs(
        pairs,
        predicted,
        sensor_origin_offset_prediction_frame_m=(sensor_origin_offset_prediction_frame_m),
    )


def zero_motion_displacement_magnitude_pairs(
    reference_pairs: tuple[TimedPositionPair, ...],
    *,
    sensor_origin_offset_prediction_frame_m: Vector3,
) -> DisplacementMagnitudeMetrics:
    """Evaluate an exact zero-motion baseline on declared reference pairs."""

    sequence_id, reference = _validate_reference_pairs(reference_pairs)
    predicted = tuple(
        RelativePoseIncrement(
            sequence_id=sequence_id,
            sample_id=f"zero-motion:{index}",
            start_timestamp_ns=start,
            end_timestamp_ns=end,
            translation_previous_body_m=(0.0, 0.0, 0.0),
            rotation_vector_previous_to_current_rad=(0.0, 0.0, 0.0),
        )
        for index, (start, end, _, _) in enumerate(reference)
    )
    return evaluate_displacement_magnitude_pairs(
        reference_pairs,
        predicted,
        sensor_origin_offset_prediction_frame_m=(sensor_origin_offset_prediction_frame_m),
    )


def zero_motion_displacement_magnitude(
    reference_positions: tuple[TimedPosition, ...],
    *,
    sensor_origin_offset_prediction_frame_m: Vector3,
) -> DisplacementMagnitudeMetrics:
    """Evaluate an exact zero-translation baseline on the reference timestamp chain."""

    sequence_id, reference = _validate_reference_positions(reference_positions)
    del sequence_id, reference
    pairs = tuple(
        TimedPositionPair(previous, current)
        for previous, current in zip(reference_positions, reference_positions[1:], strict=False)
    )
    return zero_motion_displacement_magnitude_pairs(
        pairs,
        sensor_origin_offset_prediction_frame_m=(sensor_origin_offset_prediction_frame_m),
    )


__all__ = [
    "DISPLACEMENT_MAGNITUDE_METRIC_ID",
    "DisplacementMagnitudeMetrics",
    "PositionMagnitudeEvaluationError",
    "TimedPosition",
    "TimedPositionPair",
    "evaluate_displacement_magnitude",
    "evaluate_displacement_magnitude_pairs",
    "project_sensor_point_increment",
    "zero_motion_displacement_magnitude",
    "zero_motion_displacement_magnitude_pairs",
]

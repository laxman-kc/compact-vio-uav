"""Raw, exact-pair translation-error primitives.

This module does not associate, reorder, interpolate, align, rotate, rescale,
or convert trajectories. Those operations require separate explicit policies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from compact_vio.geometry import (
    CartesianPosition3,
    Trajectory,
    TrajectoryConvention,
    TrajectorySample,
)

EXACT_PAIR_TRANSLATION_RMSE_ID = (
    "translation-rmse/exact-pairs/no-interpolation/no-alignment/no-scale-correction/v1"
)
EXACT_PAIR_TRANSLATION_RESIDUALS_ID = (
    "translation-residuals/exact-pairs/estimated-minus-reference/"
    "no-interpolation/no-alignment/no-scale-correction/v1"
)


class TranslationMetricError(ValueError):
    """Raised when an exact-pair translation result cannot be produced honestly."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise TranslationMetricError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if type(value) is not int or value < 0:
        raise TranslationMetricError(f"{field} must be a non-negative integer")


def _require_finite_float(value: object, *, field: str) -> None:
    if type(value) is not float or not math.isfinite(value):
        raise TranslationMetricError(f"{field} must be a finite float")


class TimestampAssociation(Enum):
    """Supported timestamp-association behavior for this primitive."""

    EXACT = "exact"


class TrajectoryInterpolation(Enum):
    """Supported interpolation behavior for this primitive."""

    NONE = "none"


class TrajectoryAlignment(Enum):
    """Supported trajectory-alignment behavior for this primitive."""

    NONE = "none"


class ScaleCorrection(Enum):
    """Supported scale-correction behavior for this primitive."""

    NONE = "none"


@dataclass(frozen=True, slots=True)
class TranslationRmsePolicy:
    """Required no-default declaration of this metric invocation's semantics."""

    policy_id: str
    timestamp_association: TimestampAssociation
    interpolation: TrajectoryInterpolation
    alignment: TrajectoryAlignment
    scale_correction: ScaleCorrection

    def __post_init__(self) -> None:
        _require_non_empty_text(self.policy_id, field="policy_id")
        if type(self.timestamp_association) is not TimestampAssociation:
            raise TranslationMetricError("timestamp_association must be TimestampAssociation.EXACT")
        if type(self.interpolation) is not TrajectoryInterpolation:
            raise TranslationMetricError("interpolation must be TrajectoryInterpolation.NONE")
        if type(self.alignment) is not TrajectoryAlignment:
            raise TranslationMetricError("alignment must be TrajectoryAlignment.NONE")
        if type(self.scale_correction) is not ScaleCorrection:
            raise TranslationMetricError("scale_correction must be ScaleCorrection.NONE")


@dataclass(frozen=True, slots=True)
class TranslationRmseResult:
    """Result of the named raw translation-RMSE primitive."""

    metric_id: str
    policy_id: str
    reference_trajectory_id: str
    estimated_trajectory_id: str
    sequence_id: str
    segment_id: str
    translation_unit: str
    pair_count: int
    value: float

    def __post_init__(self) -> None:
        for field in (
            "metric_id",
            "policy_id",
            "reference_trajectory_id",
            "estimated_trajectory_id",
            "sequence_id",
            "segment_id",
            "translation_unit",
        ):
            _require_non_empty_text(getattr(self, field), field=field)
        if self.metric_id != EXACT_PAIR_TRANSLATION_RMSE_ID:
            raise TranslationMetricError(f"metric_id must equal {EXACT_PAIR_TRANSLATION_RMSE_ID!r}")
        if type(self.pair_count) is not int:
            raise TranslationMetricError("pair_count must be a positive integer")
        if self.pair_count <= 0:
            raise TranslationMetricError("pair_count must be a positive integer")
        if type(self.value) is not float:
            raise TranslationMetricError("value must be a finite non-negative float")
        if not math.isfinite(self.value) or self.value < 0:
            raise TranslationMetricError("value must be a finite non-negative float")


@dataclass(frozen=True, slots=True)
class TranslationResidualSample:
    """One signed estimated-minus-reference translation residual."""

    sample_id: str
    timestamp_ns: int
    dx: float
    dy: float
    dz: float

    def __post_init__(self) -> None:
        _require_non_empty_text(self.sample_id, field="sample_id")
        _require_non_negative_integer(self.timestamp_ns, field="timestamp_ns")
        for field in ("dx", "dy", "dz"):
            _require_finite_float(getattr(self, field), field=field)


@dataclass(frozen=True, slots=True)
class TranslationResidualSeries:
    """Exact ordered signed residuals for one already-paired trajectory segment."""

    series_id: str
    policy_id: str
    reference_trajectory_id: str
    estimated_trajectory_id: str
    sequence_id: str
    segment_id: str
    convention: TrajectoryConvention
    samples: tuple[TranslationResidualSample, ...]

    def __post_init__(self) -> None:
        for field in (
            "series_id",
            "policy_id",
            "reference_trajectory_id",
            "estimated_trajectory_id",
            "sequence_id",
            "segment_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)
        if self.series_id != EXACT_PAIR_TRANSLATION_RESIDUALS_ID:
            raise TranslationMetricError(
                f"series_id must equal {EXACT_PAIR_TRANSLATION_RESIDUALS_ID!r}"
            )
        if type(self.convention) is not TrajectoryConvention:
            raise TranslationMetricError("convention must be a TrajectoryConvention")
        if type(self.samples) is not tuple or not self.samples:
            raise TranslationMetricError("samples must be a non-empty exact tuple")
        if not all(type(sample) is TranslationResidualSample for sample in self.samples):
            raise TranslationMetricError(
                "samples must contain only TranslationResidualSample values"
            )
        sample_ids = tuple(sample.sample_id for sample in self.samples)
        if len(sample_ids) != len(set(sample_ids)):
            raise TranslationMetricError("samples must not repeat a sample_id")
        if any(
            current.timestamp_ns < previous.timestamp_ns
            for previous, current in zip(self.samples, self.samples[1:], strict=False)
        ):
            raise TranslationMetricError("sample timestamps must not move backward")

    @property
    def pair_count(self) -> int:
        """Return the number of retained exact sample pairs."""

        return len(self.samples)


def _validate_exact_pair_inputs(
    reference: Trajectory,
    estimated: Trajectory,
    policy: TranslationRmsePolicy,
) -> int:
    """Validate the shared exact-pair contract and return its pair count."""

    if type(reference) is not Trajectory:
        raise TranslationMetricError("reference must be a Trajectory")
    if type(estimated) is not Trajectory:
        raise TranslationMetricError("estimated must be a Trajectory")
    if type(policy) is not TranslationRmsePolicy:
        raise TranslationMetricError("policy must be a TranslationRmsePolicy")
    for role, trajectory in (("reference", reference), ("estimated", estimated)):
        if type(trajectory.convention) is not TrajectoryConvention:
            raise TranslationMetricError(f"{role} convention must be a TrajectoryConvention")
        if type(trajectory.samples) is not tuple or not all(
            type(sample) is TrajectorySample and type(sample.position) is CartesianPosition3
            for sample in trajectory.samples
        ):
            raise TranslationMetricError(
                f"{role} samples must be an exact tuple of TrajectorySample values"
            )
    if reference.sequence_id != estimated.sequence_id:
        raise TranslationMetricError("trajectory sequence_id values must match")
    if reference.segment_id != estimated.segment_id:
        raise TranslationMetricError("trajectory segment_id values must match")
    for field in (
        "convention_id",
        "reference_frame_id",
        "tracked_frame_id",
        "transform_direction",
        "translation_unit",
        "clock_id",
        "timestamp_semantics_id",
    ):
        if getattr(reference.convention, field) != getattr(
            estimated.convention,
            field,
        ):
            raise TranslationMetricError(f"trajectory {field} values must match exactly")
    if len(reference.samples) != len(estimated.samples):
        raise TranslationMetricError(
            "trajectory sample counts must match; partial pairing is not allowed"
        )
    if not reference.samples:
        raise TranslationMetricError("at least one exact sample pair is required")
    for reference_sample, estimated_sample in zip(
        reference.samples,
        estimated.samples,
        strict=True,
    ):
        if reference_sample.sample_id != estimated_sample.sample_id:
            raise TranslationMetricError("sample_id values must match in existing trajectory order")
        if reference_sample.timestamp_ns != estimated_sample.timestamp_ns:
            raise TranslationMetricError("sample timestamps must match exactly")
    return len(reference.samples)


def _finite_signed_delta(estimated_component: object, reference_component: object) -> float:
    """Subtract one component without permitting malformed or non-finite output."""

    if type(estimated_component) not in (int, float):
        raise TranslationMetricError("translation components must be finite runtime scalars")
    if type(reference_component) not in (int, float):
        raise TranslationMetricError("translation components must be finite runtime scalars")
    try:
        exact_delta = estimated_component - reference_component
        delta = float(exact_delta)
    except (OverflowError, TypeError, ValueError) as error:
        raise TranslationMetricError(
            "translation difference exceeds the finite runtime domain"
        ) from error
    if not math.isfinite(delta):
        raise TranslationMetricError("translation difference exceeds the finite runtime domain")
    if type(exact_delta) is int and int(delta) != exact_delta:
        raise TranslationMetricError(
            "integer translation difference is not exactly representable by the runtime"
        )
    return delta


def exact_pair_translation_rmse(
    reference: Trajectory,
    estimated: Trajectory,
    *,
    policy: TranslationRmsePolicy,
) -> TranslationRmseResult:
    """Compute raw translation RMSE for already exact-paired samples.

    The formula is ``sqrt(mean(||reference - estimated||_2**2))``. Every
    convention field, segment, sample identity, timestamp, and sample count must
    already match. No alignment or scale correction is performed.
    """

    pair_count = _validate_exact_pair_inputs(reference, estimated, policy)

    scale = 0.0
    scaled_sum_squares = 0.0
    for reference_sample, estimated_sample in zip(
        reference.samples,
        estimated.samples,
        strict=True,
    ):
        for reference_component, estimated_component in zip(
            reference_sample.position.components,
            estimated_sample.position.components,
            strict=True,
        ):
            delta = abs(_finite_signed_delta(estimated_component, reference_component))
            if delta == 0.0:
                continue
            if scale < delta:
                ratio = scale / delta
                scaled_sum_squares = 1.0 + scaled_sum_squares * ratio * ratio
                scale = delta
            else:
                ratio = delta / scale
                scaled_sum_squares += ratio * ratio

    value = 0.0 if scale == 0.0 else scale * math.sqrt(scaled_sum_squares / pair_count)
    if scale > 0.0 and value == 0.0:
        raise TranslationMetricError("translation RMSE underflows the finite runtime domain")
    if not math.isfinite(value):
        raise TranslationMetricError("translation RMSE exceeds the finite runtime domain")
    return TranslationRmseResult(
        metric_id=EXACT_PAIR_TRANSLATION_RMSE_ID,
        policy_id=policy.policy_id,
        reference_trajectory_id=reference.trajectory_id,
        estimated_trajectory_id=estimated.trajectory_id,
        sequence_id=reference.sequence_id,
        segment_id=reference.segment_id,
        translation_unit=reference.convention.translation_unit,
        pair_count=pair_count,
        value=value,
    )


def exact_pair_translation_residuals(
    reference: Trajectory,
    estimated: Trajectory,
    *,
    policy: TranslationRmsePolicy,
) -> TranslationResidualSeries:
    """Retain exact-pair signed ``estimated - reference`` translation deltas.

    This operation performs no timestamp association, interpolation, alignment,
    rotation, scale correction, norm, aggregation, ATE, or RPE computation.
    """

    _validate_exact_pair_inputs(reference, estimated, policy)
    samples = tuple(
        TranslationResidualSample(
            sample_id=reference_sample.sample_id,
            timestamp_ns=reference_sample.timestamp_ns,
            dx=_finite_signed_delta(
                estimated_sample.position.x,
                reference_sample.position.x,
            ),
            dy=_finite_signed_delta(
                estimated_sample.position.y,
                reference_sample.position.y,
            ),
            dz=_finite_signed_delta(
                estimated_sample.position.z,
                reference_sample.position.z,
            ),
        )
        for reference_sample, estimated_sample in zip(
            reference.samples,
            estimated.samples,
            strict=True,
        )
    )
    return TranslationResidualSeries(
        series_id=EXACT_PAIR_TRANSLATION_RESIDUALS_ID,
        policy_id=policy.policy_id,
        reference_trajectory_id=reference.trajectory_id,
        estimated_trajectory_id=estimated.trajectory_id,
        sequence_id=reference.sequence_id,
        segment_id=reference.segment_id,
        convention=reference.convention,
        samples=samples,
    )


__all__ = [
    "EXACT_PAIR_TRANSLATION_RESIDUALS_ID",
    "EXACT_PAIR_TRANSLATION_RMSE_ID",
    "ScaleCorrection",
    "TimestampAssociation",
    "TrajectoryAlignment",
    "TrajectoryInterpolation",
    "TranslationMetricError",
    "TranslationResidualSample",
    "TranslationResidualSeries",
    "TranslationRmsePolicy",
    "TranslationRmseResult",
    "exact_pair_translation_residuals",
    "exact_pair_translation_rmse",
]

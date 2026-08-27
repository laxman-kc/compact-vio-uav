"""One raw, exact-pair translation-error primitive.

This module does not associate, reorder, interpolate, align, rotate, rescale,
or convert trajectories. Those operations require separate explicit policies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum

from compact_vio.geometry import Trajectory

EXACT_PAIR_TRANSLATION_RMSE_ID = (
    "translation-rmse/exact-pairs/no-interpolation/no-alignment/no-scale-correction/v1"
)


class TranslationMetricError(ValueError):
    """Raised when exact-pair translation RMSE cannot be computed honestly."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TranslationMetricError(f"{field} must be a non-empty string")


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
        if not isinstance(self.timestamp_association, TimestampAssociation):
            raise TranslationMetricError("timestamp_association must be TimestampAssociation.EXACT")
        if not isinstance(self.interpolation, TrajectoryInterpolation):
            raise TranslationMetricError("interpolation must be TrajectoryInterpolation.NONE")
        if not isinstance(self.alignment, TrajectoryAlignment):
            raise TranslationMetricError("alignment must be TrajectoryAlignment.NONE")
        if not isinstance(self.scale_correction, ScaleCorrection):
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
        if isinstance(self.pair_count, bool) or not isinstance(self.pair_count, int):
            raise TranslationMetricError("pair_count must be a positive integer")
        if self.pair_count <= 0:
            raise TranslationMetricError("pair_count must be a positive integer")
        if isinstance(self.value, bool) or not isinstance(self.value, float):
            raise TranslationMetricError("value must be a finite non-negative float")
        if not math.isfinite(self.value) or self.value < 0:
            raise TranslationMetricError("value must be a finite non-negative float")


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

    if not isinstance(reference, Trajectory):
        raise TranslationMetricError("reference must be a Trajectory")
    if not isinstance(estimated, Trajectory):
        raise TranslationMetricError("estimated must be a Trajectory")
    if not isinstance(policy, TranslationRmsePolicy):
        raise TranslationMetricError("policy must be a TranslationRmsePolicy")
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

    scale = 0.0
    scaled_sum_squares = 0.0
    pair_count = 0
    for reference_sample, estimated_sample in zip(
        reference.samples,
        estimated.samples,
        strict=True,
    ):
        if reference_sample.sample_id != estimated_sample.sample_id:
            raise TranslationMetricError("sample_id values must match in existing trajectory order")
        if reference_sample.timestamp_ns != estimated_sample.timestamp_ns:
            raise TranslationMetricError("sample timestamps must match exactly")
        pair_count += 1
        for reference_component, estimated_component in zip(
            reference_sample.position.components,
            estimated_sample.position.components,
            strict=True,
        ):
            try:
                delta = abs(float(estimated_component - reference_component))
            except OverflowError as error:
                raise TranslationMetricError(
                    "translation difference exceeds the finite runtime domain"
                ) from error
            if not math.isfinite(delta):
                raise TranslationMetricError(
                    "translation difference exceeds the finite runtime domain"
                )
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


__all__ = [
    "EXACT_PAIR_TRANSLATION_RMSE_ID",
    "ScaleCorrection",
    "TimestampAssociation",
    "TrajectoryAlignment",
    "TrajectoryInterpolation",
    "TranslationMetricError",
    "TranslationRmsePolicy",
    "TranslationRmseResult",
    "exact_pair_translation_rmse",
]

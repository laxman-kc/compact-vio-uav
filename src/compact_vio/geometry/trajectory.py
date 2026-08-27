"""Immutable trajectory records with explicit spatial and temporal meaning."""

from __future__ import annotations

import math
from dataclasses import dataclass

Scalar = int | float


class TrajectoryContractError(ValueError):
    """Raised when trajectory geometry is incomplete or inconsistent."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise TrajectoryContractError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TrajectoryContractError(f"{field} must be a non-negative integer")


def _require_finite_runtime_scalar(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TrajectoryContractError(
            f"{field} must be a finite real number representable by this runtime"
        )
    try:
        runtime_value = float(value)
    except OverflowError as error:
        raise TrajectoryContractError(
            f"{field} must be a finite real number representable by this runtime"
        ) from error
    if not math.isfinite(runtime_value):
        raise TrajectoryContractError(
            f"{field} must be a finite real number representable by this runtime"
        )
    if isinstance(value, int) and int(runtime_value) != value:
        raise TrajectoryContractError(
            f"{field} integer must be exactly representable by this runtime"
        )


@dataclass(frozen=True, slots=True)
class CartesianPosition3:
    """One finite Cartesian position without an implicit frame or unit."""

    x: Scalar
    y: Scalar
    z: Scalar

    def __post_init__(self) -> None:
        for field in ("x", "y", "z"):
            _require_finite_runtime_scalar(getattr(self, field), field=field)

    @property
    def components(self) -> tuple[Scalar, Scalar, Scalar]:
        """Return components in declared Cartesian x/y/z order."""

        return (self.x, self.y, self.z)


@dataclass(frozen=True, slots=True)
class TrajectoryConvention:
    """Declarations required to interpret all samples in one trajectory."""

    convention_id: str
    reference_frame_id: str
    tracked_frame_id: str
    transform_direction: str
    translation_unit: str
    clock_id: str
    timestamp_semantics_id: str

    def __post_init__(self) -> None:
        for field in (
            "convention_id",
            "reference_frame_id",
            "tracked_frame_id",
            "transform_direction",
            "translation_unit",
            "clock_id",
            "timestamp_semantics_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)


@dataclass(frozen=True, slots=True)
class TrajectorySample:
    """One identified trajectory position at one declared timestamp."""

    sample_id: str
    timestamp_ns: int
    position: CartesianPosition3

    def __post_init__(self) -> None:
        _require_non_empty_text(self.sample_id, field="sample_id")
        _require_non_negative_integer(self.timestamp_ns, field="timestamp_ns")
        if not isinstance(self.position, CartesianPosition3):
            raise TrajectoryContractError("position must be a CartesianPosition3")


@dataclass(frozen=True, slots=True)
class Trajectory:
    """One time-ordered trajectory segment, including an observable empty segment."""

    trajectory_id: str
    sequence_id: str
    segment_id: str
    convention: TrajectoryConvention
    samples: tuple[TrajectorySample, ...]

    def __post_init__(self) -> None:
        _require_non_empty_text(self.trajectory_id, field="trajectory_id")
        _require_non_empty_text(self.sequence_id, field="sequence_id")
        _require_non_empty_text(self.segment_id, field="segment_id")
        if not isinstance(self.convention, TrajectoryConvention):
            raise TrajectoryContractError("convention must be a TrajectoryConvention")
        if not isinstance(self.samples, tuple):
            raise TrajectoryContractError("samples must be a tuple")
        if not all(isinstance(sample, TrajectorySample) for sample in self.samples):
            raise TrajectoryContractError("samples must contain only TrajectorySample values")

        sample_ids = [sample.sample_id for sample in self.samples]
        if len(sample_ids) != len(set(sample_ids)):
            raise TrajectoryContractError("samples must not repeat a sample_id")

        timestamps = [sample.timestamp_ns for sample in self.samples]
        if any(
            current < previous
            for previous, current in zip(timestamps, timestamps[1:], strict=False)
        ):
            raise TrajectoryContractError(
                "sample timestamps must not move backward within a segment"
            )


__all__ = [
    "CartesianPosition3",
    "Trajectory",
    "TrajectoryContractError",
    "TrajectoryConvention",
    "TrajectorySample",
]

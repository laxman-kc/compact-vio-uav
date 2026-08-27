"""Canonical camera, IMU, and calibration-reference records.

The existing :class:`compact_vio.replay.ReplayEvent` remains the only event
envelope.  These payload records therefore do not duplicate event identity,
stream, clock, measurement time, availability time, or validity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Generic, TypeVar

from compact_vio.replay import EventKind, ReplayEvent

ImageT = TypeVar("ImageT")
CalibrationT = TypeVar("CalibrationT")
Scalar = int | float


class SensorRecordError(ValueError):
    """Raised when a canonical sensor record is incomplete or inconsistent."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SensorRecordError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SensorRecordError(f"{field} must be a non-negative integer")


def _require_positive_integer(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SensorRecordError(f"{field} must be a positive integer")


@dataclass(frozen=True, slots=True)
class TimeInterval:
    """A declared interval in the containing replay event's clock."""

    start_time_ns: int
    end_time_ns: int

    def __post_init__(self) -> None:
        _require_non_negative_integer(self.start_time_ns, field="start_time_ns")
        _require_non_negative_integer(self.end_time_ns, field="end_time_ns")
        if self.end_time_ns < self.start_time_ns:
            raise SensorRecordError("end_time_ns must not precede start_time_ns")


@dataclass(frozen=True, slots=True)
class MeasurementContext:
    """Required profile, calibration, frame, time, and provenance declarations."""

    sensor_profile_id: str
    calibration_id: str
    calibration_revision_id: str
    frame_id: str
    timestamp_semantics_id: str
    provenance_id: str

    def __post_init__(self) -> None:
        for field in (
            "sensor_profile_id",
            "calibration_id",
            "calibration_revision_id",
            "frame_id",
            "timestamp_semantics_id",
            "provenance_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)


@dataclass(frozen=True, slots=True)
class CameraSample(Generic[ImageT]):
    """One opaque image plus declarations needed to interpret the sample."""

    context: MeasurementContext
    encoding_id: str
    width_px: int
    height_px: int
    exposure_interval: TimeInterval | None
    image: ImageT

    def __post_init__(self) -> None:
        if not isinstance(self.context, MeasurementContext):
            raise SensorRecordError("context must be a MeasurementContext")
        _require_non_empty_text(self.encoding_id, field="encoding_id")
        _require_positive_integer(self.width_px, field="width_px")
        _require_positive_integer(self.height_px, field="height_px")
        if self.exposure_interval is not None and not isinstance(
            self.exposure_interval, TimeInterval
        ):
            raise SensorRecordError("exposure_interval must be a TimeInterval or None")


@dataclass(frozen=True, slots=True)
class Vector3Measurement:
    """Three finite components with explicitly declared semantics and units."""

    quantity_id: str
    unit_id: str
    axis_convention_id: str
    values: tuple[Scalar, Scalar, Scalar]

    def __post_init__(self) -> None:
        _require_non_empty_text(self.quantity_id, field="quantity_id")
        _require_non_empty_text(self.unit_id, field="unit_id")
        _require_non_empty_text(self.axis_convention_id, field="axis_convention_id")
        if not isinstance(self.values, tuple) or len(self.values) != 3:
            raise SensorRecordError("values must be a tuple of exactly three components")
        for value in self.values:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SensorRecordError("values must contain only finite real numbers")
            if isinstance(value, float) and not math.isfinite(value):
                raise SensorRecordError("values must contain only finite real numbers")


@dataclass(frozen=True, slots=True)
class ImuSample:
    """One IMU sample with no pairing, quantity, axis, or unit defaults."""

    context: MeasurementContext
    gyroscope: Vector3Measurement | None
    accelerometer: Vector3Measurement | None
    sample_interval: TimeInterval | None

    def __post_init__(self) -> None:
        if not isinstance(self.context, MeasurementContext):
            raise SensorRecordError("context must be a MeasurementContext")
        if self.gyroscope is not None and not isinstance(self.gyroscope, Vector3Measurement):
            raise SensorRecordError("gyroscope must be a Vector3Measurement or None")
        if self.accelerometer is not None and not isinstance(
            self.accelerometer, Vector3Measurement
        ):
            raise SensorRecordError("accelerometer must be a Vector3Measurement or None")
        if self.sample_interval is not None and not isinstance(self.sample_interval, TimeInterval):
            raise SensorRecordError("sample_interval must be a TimeInterval or None")


@dataclass(frozen=True, slots=True)
class SensorBinding:
    """Exact stream, modality, and coordinate-frame scope of a calibration."""

    stream_id: str
    kind: EventKind
    frame_id: str

    def __post_init__(self) -> None:
        _require_non_empty_text(self.stream_id, field="stream_id")
        if not isinstance(self.kind, EventKind) or self.kind is EventKind.RESET:
            raise SensorRecordError("kind must be EventKind.CAMERA or EventKind.IMU")
        _require_non_empty_text(self.frame_id, field="frame_id")


@dataclass(frozen=True, slots=True)
class CalibrationRecord(Generic[CalibrationT]):
    """Versioned identity envelope around an explicitly schematized payload.

    This record does not claim that the opaque payload is sufficient or accepted
    for a real dataset or physical sensor.  A later profile schema must define
    and validate its actual calibration fields.
    """

    calibration_id: str
    sensor_profile_id: str
    revision_id: str
    schema_id: str
    provenance_id: str
    validity_conditions_id: str
    clock_id: str
    sensor_bindings: tuple[SensorBinding, ...]
    payload: CalibrationT

    def __post_init__(self) -> None:
        for field in (
            "calibration_id",
            "sensor_profile_id",
            "revision_id",
            "schema_id",
            "provenance_id",
            "validity_conditions_id",
            "clock_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)
        if not isinstance(self.sensor_bindings, tuple) or not self.sensor_bindings:
            raise SensorRecordError("sensor_bindings must be a non-empty tuple")
        if not all(isinstance(binding, SensorBinding) for binding in self.sensor_bindings):
            raise SensorRecordError("sensor_bindings must contain only SensorBinding values")
        stream_ids = [binding.stream_id for binding in self.sensor_bindings]
        if len(stream_ids) != len(set(stream_ids)):
            raise SensorRecordError("sensor_bindings must not repeat a stream_id")


def validate_sensor_event(
    event: ReplayEvent[object],
    calibration: CalibrationRecord[object],
) -> None:
    """Validate payload kind and exact calibration binding for one replay event."""

    if not isinstance(event, ReplayEvent):
        raise SensorRecordError("event must be a ReplayEvent")
    if not isinstance(calibration, CalibrationRecord):
        raise SensorRecordError("calibration must be a CalibrationRecord")

    if isinstance(event.payload, CameraSample):
        if event.kind is not EventKind.CAMERA:
            raise SensorRecordError("CameraSample requires EventKind.CAMERA")
        if event.valid and event.payload.image is None:
            raise SensorRecordError("valid camera event must carry image data")
        interval = event.payload.exposure_interval
        context = event.payload.context
    elif isinstance(event.payload, ImuSample):
        if event.kind is not EventKind.IMU:
            raise SensorRecordError("ImuSample requires EventKind.IMU")
        if event.valid and event.payload.gyroscope is None and event.payload.accelerometer is None:
            raise SensorRecordError("valid IMU event must carry at least one measurement")
        interval = event.payload.sample_interval
        context = event.payload.context
    else:
        raise SensorRecordError("event payload must be a CameraSample or ImuSample")

    if interval is not None and interval.end_time_ns > event.available_time_ns:
        raise SensorRecordError("sample interval cannot end after event availability")

    if context.calibration_id != calibration.calibration_id:
        raise SensorRecordError("calibration_id does not match the calibration record")
    if context.calibration_revision_id != calibration.revision_id:
        raise SensorRecordError("calibration revision does not match the calibration record")
    if context.sensor_profile_id != calibration.sensor_profile_id:
        raise SensorRecordError("sensor_profile_id does not match the calibration record")
    if event.clock_id != calibration.clock_id:
        raise SensorRecordError("event clock_id does not match the calibration record")
    binding = SensorBinding(
        stream_id=event.stream_id,
        kind=event.kind,
        frame_id=context.frame_id,
    )
    if binding not in calibration.sensor_bindings:
        raise SensorRecordError("event stream, kind, and frame are outside the calibration scope")


__all__ = [
    "CalibrationRecord",
    "CameraSample",
    "ImuSample",
    "MeasurementContext",
    "SensorBinding",
    "SensorRecordError",
    "TimeInterval",
    "Vector3Measurement",
    "validate_sensor_event",
]

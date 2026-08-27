from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError

from compact_vio.contracts.sensors import (
    CalibrationRecord,
    CameraSample,
    ImuSample,
    MeasurementContext,
    SensorBinding,
    SensorRecordError,
    TimeInterval,
    Vector3Measurement,
    validate_sensor_event,
)
from compact_vio.replay import EventKind, ReplayEvent


def _context(
    *,
    sensor_profile_id: str = "profile-under-test",
    calibration_id: str = "calibration-under-test",
    calibration_revision_id: str = "revision-under-test",
    frame_id: str = "declared-sensor-frame",
    timestamp_semantics_id: str = "declared-timestamp-semantics",
    provenance_id: str = "synthetic-provenance",
) -> MeasurementContext:
    return MeasurementContext(
        sensor_profile_id=sensor_profile_id,
        calibration_id=calibration_id,
        calibration_revision_id=calibration_revision_id,
        frame_id=frame_id,
        timestamp_semantics_id=timestamp_semantics_id,
        provenance_id=provenance_id,
    )


def _camera(*, image: object = "opaque-image") -> CameraSample[object]:
    return CameraSample(
        context=_context(),
        encoding_id="declared-image-encoding",
        width_px=17,
        height_px=11,
        exposure_interval=TimeInterval(start_time_ns=8, end_time_ns=10),
        image=image,
    )


def _vector(*, quantity_id: str, unit_id: str, axis_id: str) -> Vector3Measurement:
    return Vector3Measurement(
        quantity_id=quantity_id,
        unit_id=unit_id,
        axis_convention_id=axis_id,
        values=(1, 2.5, -3),
    )


def _imu() -> ImuSample:
    return ImuSample(
        context=_context(),
        gyroscope=_vector(
            quantity_id="declared-angular-quantity",
            unit_id="declared-angular-unit",
            axis_id="declared-gyro-axis-order",
        ),
        accelerometer=_vector(
            quantity_id="declared-acceleration-quantity",
            unit_id="declared-acceleration-unit",
            axis_id="declared-accelerometer-axis-order",
        ),
        sample_interval=None,
    )


def _calibration(
    *,
    calibration_id: str = "calibration-under-test",
    sensor_profile_id: str = "profile-under-test",
    revision_id: str = "revision-under-test",
    clock_id: str = "sensor-clock",
    sensor_bindings: tuple[SensorBinding, ...] | None = None,
    payload: object = None,
) -> CalibrationRecord[object]:
    if sensor_bindings is None:
        sensor_bindings = (
            SensorBinding(
                stream_id="camera-stream",
                kind=EventKind.CAMERA,
                frame_id="declared-sensor-frame",
            ),
            SensorBinding(
                stream_id="imu-stream",
                kind=EventKind.IMU,
                frame_id="declared-sensor-frame",
            ),
        )
    return CalibrationRecord(
        calibration_id=calibration_id,
        sensor_profile_id=sensor_profile_id,
        revision_id=revision_id,
        schema_id="synthetic-calibration-schema",
        provenance_id="synthetic-calibration-provenance",
        validity_conditions_id="synthetic-validity-conditions",
        clock_id=clock_id,
        sensor_bindings=sensor_bindings,
        payload=payload,
    )


def _event(
    payload: object,
    *,
    kind: EventKind,
    stream_id: str,
    clock_id: str = "sensor-clock",
    valid: bool = True,
    available_time_ns: int = 12,
) -> ReplayEvent[object]:
    return ReplayEvent(
        event_id="synthetic-event",
        sequence_index=0,
        stream_id=stream_id,
        kind=kind,
        clock_id=clock_id,
        measurement_time_ns=10,
        available_time_ns=available_time_ns,
        payload=payload,
        valid=valid,
    )


class SensorRecordTests(unittest.TestCase):
    def test_camera_preserves_opaque_image_and_declared_metadata(self) -> None:
        image = object()
        sample = _camera(image=image)

        self.assertIs(sample.image, image)
        self.assertEqual(sample.width_px, 17)
        self.assertEqual(sample.height_px, 11)
        self.assertEqual(sample.context.timestamp_semantics_id, "declared-timestamp-semantics")
        self.assertEqual(sample.exposure_interval, TimeInterval(8, 10))

    def test_distinct_camera_streams_do_not_select_mono_or_stereo(self) -> None:
        first = _event(_camera(), kind=EventKind.CAMERA, stream_id="camera-a")
        second = _event(_camera(), kind=EventKind.CAMERA, stream_id="camera-b")
        calibration = _calibration(
            sensor_bindings=(
                SensorBinding("camera-a", EventKind.CAMERA, "declared-sensor-frame"),
                SensorBinding("camera-b", EventKind.CAMERA, "declared-sensor-frame"),
            )
        )

        validate_sensor_event(first, calibration)
        validate_sensor_event(second, calibration)

    def test_imu_preserves_independent_quantity_unit_and_axis_declarations(self) -> None:
        sample = _imu()

        self.assertEqual(sample.gyroscope.quantity_id, "declared-angular-quantity")
        self.assertEqual(sample.gyroscope.unit_id, "declared-angular-unit")
        self.assertEqual(sample.gyroscope.axis_convention_id, "declared-gyro-axis-order")
        self.assertEqual(sample.accelerometer.quantity_id, "declared-acceleration-quantity")
        self.assertEqual(sample.accelerometer.unit_id, "declared-acceleration-unit")
        self.assertEqual(
            sample.accelerometer.axis_convention_id,
            "declared-accelerometer-axis-order",
        )

    def test_calibration_preserves_opaque_payload_and_explicit_identity(self) -> None:
        payload = {"synthetic": (1, 2, 3)}
        calibration = _calibration(payload=payload)

        self.assertIs(calibration.payload, payload)
        self.assertEqual(calibration.calibration_id, "calibration-under-test")
        self.assertEqual(calibration.revision_id, "revision-under-test")
        self.assertEqual(calibration.schema_id, "synthetic-calibration-schema")
        self.assertEqual(calibration.validity_conditions_id, "synthetic-validity-conditions")

    def test_required_identifiers_have_no_empty_fallback(self) -> None:
        context_values = {
            "sensor_profile_id": "profile",
            "calibration_id": "calibration",
            "calibration_revision_id": "revision",
            "frame_id": "frame",
            "timestamp_semantics_id": "timestamp-semantics",
            "provenance_id": "provenance",
        }
        for field in context_values:
            invalid = dict(context_values)
            invalid[field] = " "
            with self.subTest(field=field):
                with self.assertRaisesRegex(SensorRecordError, field):
                    MeasurementContext(**invalid)

        with self.assertRaisesRegex(SensorRecordError, "encoding_id"):
            CameraSample(_context(), "", 1, 1, None, object())

    def test_dimensions_and_intervals_reject_invalid_integers_and_order(self) -> None:
        with self.assertRaisesRegex(SensorRecordError, "width_px"):
            CameraSample(_context(), "encoding", True, 1, None, object())
        with self.assertRaisesRegex(SensorRecordError, "height_px"):
            CameraSample(_context(), "encoding", 1, 0, None, object())
        with self.assertRaisesRegex(SensorRecordError, "start_time_ns"):
            TimeInterval(-1, 1)
        with self.assertRaisesRegex(SensorRecordError, "start_time_ns"):
            TimeInterval(True, 1)
        with self.assertRaisesRegex(SensorRecordError, "must not precede"):
            TimeInterval(2, 1)
        self.assertIsNone(
            CameraSample(_context(), "encoding", 1, 1, None, object()).exposure_interval
        )

    def test_vector_requires_exactly_three_finite_real_components(self) -> None:
        def vector(values: object) -> Vector3Measurement:
            return Vector3Measurement(
                quantity_id="quantity",
                unit_id="unit",
                axis_convention_id="axes",
                values=values,  # type: ignore[arg-type]
            )

        for invalid in (
            [1, 2, 3],
            (1, 2),
            (1, 2, 3, 4),
            (True, 2, 3),
            ("1", 2, 3),
            (math.nan, 2, 3),
            (math.inf, 2, 3),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(SensorRecordError):
                    vector(invalid)

    def test_calibration_scope_is_nonempty_unique_and_immutable(self) -> None:
        with self.assertRaisesRegex(SensorRecordError, "non-empty tuple"):
            _calibration(sensor_bindings=[])
        repeated_stream = SensorBinding(
            "repeated-stream",
            EventKind.CAMERA,
            "declared-sensor-frame",
        )
        with self.assertRaisesRegex(SensorRecordError, "repeat a stream_id"):
            _calibration(sensor_bindings=(repeated_stream, repeated_stream))
        with self.assertRaisesRegex(SensorRecordError, "CAMERA or EventKind.IMU"):
            SensorBinding("control", EventKind.RESET, "declared-sensor-frame")
        with self.assertRaisesRegex(SensorRecordError, "CAMERA or EventKind.IMU"):
            SensorBinding(
                "camera-stream",
                "camera",  # type: ignore[arg-type]
                "declared-sensor-frame",
            )

        calibration = _calibration()
        with self.assertRaises(FrozenInstanceError):
            calibration.clock_id = "other"  # type: ignore[misc]
        self.assertFalse(hasattr(calibration, "__dict__"))

    def test_matching_camera_and_imu_events_bind_to_calibration(self) -> None:
        calibration = _calibration()

        validate_sensor_event(
            _event(_camera(), kind=EventKind.CAMERA, stream_id="camera-stream"),
            calibration,
        )
        validate_sensor_event(
            _event(_imu(), kind=EventKind.IMU, stream_id="imu-stream"),
            calibration,
        )

    def test_invalid_sensor_event_remains_validatable_and_observable(self) -> None:
        camera_event = _event(
            _camera(image=None),
            kind=EventKind.CAMERA,
            stream_id="camera-stream",
            valid=False,
        )
        imu_event = _event(
            ImuSample(
                context=_context(),
                gyroscope=None,
                accelerometer=None,
                sample_interval=None,
            ),
            kind=EventKind.IMU,
            stream_id="imu-stream",
            valid=False,
        )

        validate_sensor_event(camera_event, _calibration())
        validate_sensor_event(imu_event, _calibration())
        self.assertFalse(camera_event.valid)
        self.assertIsNone(camera_event.payload.image)
        self.assertFalse(imu_event.valid)
        self.assertIsNone(imu_event.payload.gyroscope)

    def test_valid_sensor_event_cannot_silently_omit_measurements(self) -> None:
        with self.assertRaisesRegex(SensorRecordError, "must carry image"):
            validate_sensor_event(
                _event(
                    _camera(image=None),
                    kind=EventKind.CAMERA,
                    stream_id="camera-stream",
                ),
                _calibration(),
            )

        missing_imu = ImuSample(
            context=_context(),
            gyroscope=None,
            accelerometer=None,
            sample_interval=None,
        )
        with self.assertRaisesRegex(SensorRecordError, "at least one measurement"):
            validate_sensor_event(
                _event(missing_imu, kind=EventKind.IMU, stream_id="imu-stream"),
                _calibration(),
            )

        gyro_only = ImuSample(
            context=_context(),
            gyroscope=_vector(
                quantity_id="declared-angular-quantity",
                unit_id="declared-angular-unit",
                axis_id="declared-axis-order",
            ),
            accelerometer=None,
            sample_interval=None,
        )
        validate_sensor_event(
            _event(gyro_only, kind=EventKind.IMU, stream_id="imu-stream"),
            _calibration(),
        )

    def test_sample_interval_cannot_finish_after_event_availability(self) -> None:
        camera = CameraSample(
            context=_context(),
            encoding_id="encoding",
            width_px=1,
            height_px=1,
            exposure_interval=TimeInterval(8, 13),
            image=object(),
        )
        with self.assertRaisesRegex(SensorRecordError, "after event availability"):
            validate_sensor_event(
                _event(
                    camera,
                    kind=EventKind.CAMERA,
                    stream_id="camera-stream",
                    available_time_ns=12,
                ),
                _calibration(),
            )

    def test_event_kind_and_payload_type_must_match(self) -> None:
        calibration = _calibration()
        with self.assertRaisesRegex(SensorRecordError, "CameraSample requires"):
            validate_sensor_event(
                _event(_camera(), kind=EventKind.IMU, stream_id="camera-stream"),
                calibration,
            )
        with self.assertRaisesRegex(SensorRecordError, "ImuSample requires"):
            validate_sensor_event(
                _event(_imu(), kind=EventKind.CAMERA, stream_id="imu-stream"),
                calibration,
            )
        with self.assertRaisesRegex(SensorRecordError, "CameraSample or ImuSample"):
            validate_sensor_event(
                _event(object(), kind=EventKind.RESET, stream_id="control"),
                calibration,
            )

    def test_calibration_binding_rejects_every_identity_or_scope_mismatch(self) -> None:
        event = _event(_camera(), kind=EventKind.CAMERA, stream_id="camera-stream")
        cases = (
            (_calibration(calibration_id="other"), "calibration_id"),
            (_calibration(revision_id="other"), "revision"),
            (_calibration(sensor_profile_id="other"), "sensor_profile_id"),
            (_calibration(clock_id="other"), "clock_id"),
            (
                _calibration(
                    sensor_bindings=(
                        SensorBinding("other", EventKind.CAMERA, "declared-sensor-frame"),
                    )
                ),
                "stream, kind, and frame",
            ),
            (
                _calibration(
                    sensor_bindings=(
                        SensorBinding("camera-stream", EventKind.CAMERA, "other-frame"),
                    )
                ),
                "stream, kind, and frame",
            ),
            (
                _calibration(
                    sensor_bindings=(
                        SensorBinding(
                            "camera-stream",
                            EventKind.IMU,
                            "declared-sensor-frame",
                        ),
                    )
                ),
                "stream, kind, and frame",
            ),
        )
        for calibration, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(SensorRecordError, message):
                    validate_sensor_event(event, calibration)


if __name__ == "__main__":
    unittest.main()

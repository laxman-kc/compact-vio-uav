from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from compact_vio.data import (
    EuRoCDataError,
    EuRoCSensorSequence,
    iter_causal_sensor_frame_pairs,
    load_euroc_sensor_sequence,
    load_euroc_sequence,
    sensor_calibration_sources_sha256,
    sensor_sequence_sources_sha256,
    source_files_sha256,
)

CAMERA_HEADER = ("#timestamp [ns]", "filename")
IMU_HEADER = (
    "#timestamp [ns]",
    "w_RS_S_x [rad s^-1]",
    "w_RS_S_y [rad s^-1]",
    "w_RS_S_z [rad s^-1]",
    "a_RS_S_x [m s^-2]",
    "a_RS_S_y [m s^-2]",
    "a_RS_S_z [m s^-2]",
)


def _transform() -> dict[str, object]:
    return {
        "rows": 4,
        "cols": 4,
        "data": [
            1.0,
            0.0,
            0.0,
            0.1,
            0.0,
            1.0,
            0.0,
            -0.2,
            0.0,
            0.0,
            1.0,
            0.3,
            0.0,
            0.0,
            0.0,
            1.0,
        ],
    }


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


class SensorOnlyFixture:
    def __init__(self, directory: str) -> None:
        self.root = Path(directory) / "MH_01_easy"
        self.camera = self.root / "mav0/cam0"
        self.imu = self.root / "mav0/imu0"
        (self.camera / "data").mkdir(parents=True)
        self.imu.mkdir(parents=True)
        for filename in ("100.png", "200.png", "300.png"):
            (self.camera / "data" / filename).write_bytes(b"synthetic-image")
        _write_csv(
            self.camera / "data.csv",
            CAMERA_HEADER,
            [(100, "100.png"), (200, "200.png"), (300, "300.png")],
        )
        _write_csv(
            self.imu / "data.csv",
            IMU_HEADER,
            [
                (100, 1, 2, 3, 4, 5, 6),
                (150, 2, 3, 4, 5, 6, 7),
                (200, 3, 4, 5, 6, 7, 8),
                (250, 4, 5, 6, 7, 8, 9),
                (300, 5, 6, 7, 8, 9, 10),
            ],
        )
        (self.camera / "sensor.yaml").write_text(
            json.dumps(
                {
                    "sensor_type": "camera",
                    "T_BS": _transform(),
                    "rate_hz": 20,
                    "resolution": [752, 480],
                    "camera_model": "pinhole",
                    "intrinsics": [458.0, 457.0, 367.0, 248.0],
                    "distortion_model": "radial-tangential",
                    "distortion_coefficients": [-0.28, 0.07, 0.0001, -0.0002],
                }
            ),
            encoding="utf-8",
        )
        (self.imu / "sensor.yaml").write_text(
            json.dumps(
                {
                    "sensor_type": "imu",
                    "T_BS": _transform(),
                    "rate_hz": 200,
                    "gyroscope_noise_density": 0.0002,
                    "gyroscope_random_walk": 0.00002,
                    "accelerometer_noise_density": 0.002,
                    "accelerometer_random_walk": 0.003,
                }
            ),
            encoding="utf-8",
        )


class EuRoCSensorOnlyTests(unittest.TestCase):
    def test_loads_exact_cam0_and_imu_without_ground_truth_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SensorOnlyFixture(directory)

            sequence = load_euroc_sensor_sequence(fixture.root)

            self.assertIs(type(sequence), EuRoCSensorSequence)
            self.assertEqual(sequence.sequence_id, "MH_01_easy")
            self.assertEqual(sequence.root, fixture.root.resolve())
            self.assertEqual(len(sequence.camera_frames), 3)
            self.assertEqual(len(sequence.imu_measurements), 5)
            self.assertEqual(sequence.camera_calibration.intrinsics[0], 458.0)
            self.assertEqual(sequence.imu_calibration.rate_hz, 200.0)
            with self.assertRaises(FrozenInstanceError):
                sequence.sequence_id = "changed"  # type: ignore[misc]
            self.assertFalse(hasattr(sequence, "__dict__"))

    def test_pairs_preserve_native_timing_and_never_attach_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sequence = load_euroc_sensor_sequence(SensorOnlyFixture(directory).root)

            pairs = tuple(iter_causal_sensor_frame_pairs(sequence))

            self.assertEqual(len(pairs), 2)
            self.assertEqual(
                tuple(item.timestamp_ns for item in pairs[0].imu_measurements),
                (150, 200),
            )
            self.assertEqual(
                tuple(item.timestamp_ns for item in pairs[1].imu_measurements),
                (250, 300),
            )
            self.assertIsNone(pairs[0].previous_ground_truth)
            self.assertIsNone(pairs[0].current_ground_truth)

            stride_two = tuple(iter_causal_sensor_frame_pairs(sequence, frame_stride=2))
            self.assertEqual(stride_two[0].previous_frame.timestamp_ns, 100)
            self.assertEqual(stride_two[0].current_frame.timestamp_ns, 300)
            self.assertEqual(
                tuple(item.timestamp_ns for item in stride_two[0].imu_measurements),
                (150, 200, 250, 300),
            )

    def test_sensor_loader_keeps_strict_camera_and_imu_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SensorOnlyFixture(directory)
            _write_csv(
                fixture.imu / "data.csv",
                IMU_HEADER,
                [(100, 1, 2, 3, 4, 5, 6), (100, 2, 3, 4, 5, 6, 7)],
            )
            with self.assertRaisesRegex(EuRoCDataError, "strictly increasing"):
                load_euroc_sensor_sequence(fixture.root)

        with tempfile.TemporaryDirectory() as directory:
            fixture = SensorOnlyFixture(directory)
            (fixture.camera / "data/200.png").unlink()
            with self.assertRaisesRegex(EuRoCDataError, "image does not exist"):
                load_euroc_sensor_sequence(fixture.root)

    def test_sensor_loader_requires_every_cam0_and_imu_source(self) -> None:
        required_paths = (
            "mav0/cam0/data.csv",
            "mav0/cam0/sensor.yaml",
            "mav0/imu0/data.csv",
            "mav0/imu0/sensor.yaml",
        )
        for relative_path in required_paths:
            with self.subTest(path=relative_path), tempfile.TemporaryDirectory() as directory:
                fixture = SensorOnlyFixture(directory)
                (fixture.root / relative_path).unlink()
                with self.assertRaisesRegex(EuRoCDataError, "missing required EuRoC file"):
                    load_euroc_sensor_sequence(fixture.root)

    def test_sensor_hashes_bind_only_exact_cam0_and_imu_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SensorOnlyFixture(directory)
            expected_calibration = source_files_sha256(
                fixture.root,
                ("mav0/cam0/sensor.yaml", "mav0/imu0/sensor.yaml"),
            )
            calibration_hash = sensor_calibration_sources_sha256(fixture.root)
            sequence_hash = sensor_sequence_sources_sha256(fixture.root)

            self.assertEqual(calibration_hash, expected_calibration)
            self.assertRegex(sequence_hash, r"^[0-9a-f]{64}$")
            (fixture.camera / "data/200.png").write_bytes(b"changed-image")
            self.assertEqual(
                calibration_hash,
                sensor_calibration_sources_sha256(fixture.root),
            )
            self.assertNotEqual(sequence_hash, sensor_sequence_sources_sha256(fixture.root))

    def test_sensor_pair_arguments_and_empty_imu_windows_fail_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SensorOnlyFixture(directory)
            sequence = load_euroc_sensor_sequence(fixture.root)
            with self.assertRaisesRegex(EuRoCDataError, "EuRoCSensorSequence"):
                tuple(iter_causal_sensor_frame_pairs(object()))  # type: ignore[arg-type]
            for stride in (0, -1, True, 1.0):
                with (
                    self.subTest(stride=stride),
                    self.assertRaisesRegex(EuRoCDataError, "frame_stride"),
                ):
                    tuple(
                        iter_causal_sensor_frame_pairs(
                            sequence,
                            frame_stride=stride,  # type: ignore[arg-type]
                        )
                    )
            with self.assertRaisesRegex(EuRoCDataError, "require_imu"):
                tuple(
                    iter_causal_sensor_frame_pairs(
                        sequence,
                        require_imu=1,  # type: ignore[arg-type]
                    )
                )

            _write_csv(
                fixture.imu / "data.csv",
                IMU_HEADER,
                [(100, 1, 2, 3, 4, 5, 6), (300, 2, 3, 4, 5, 6, 7)],
            )
            sparse_sequence = load_euroc_sensor_sequence(fixture.root)
            with self.assertRaisesRegex(EuRoCDataError, r"\(100, 200\]"):
                tuple(iter_causal_sensor_frame_pairs(sparse_sequence))
            pairs = tuple(iter_causal_sensor_frame_pairs(sparse_sequence, require_imu=False))
            self.assertEqual(pairs[0].imu_measurements, ())

    def test_ground_truth_loader_contract_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = SensorOnlyFixture(directory)

            with self.assertRaisesRegex(EuRoCDataError, "missing required EuRoC file"):
                load_euroc_sequence(fixture.root)


if __name__ == "__main__":
    unittest.main()

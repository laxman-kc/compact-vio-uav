from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from compact_vio.data.euroc import (
    EuRoCDataError,
    GroundTruthState,
    calibration_sources_sha256,
    interpolate_ground_truth,
    iter_causal_frame_pairs,
    load_euroc_sequence,
    sequence_sources_sha256,
    sha256_file,
    source_files_sha256,
    validate_sequence_splits,
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
GROUND_TRUTH_HEADER = (
    "#timestamp",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
    "q_RS_w []",
    "q_RS_x []",
    "q_RS_y []",
    "q_RS_z []",
    "v_RS_R_x [m s^-1]",
    "v_RS_R_y [m s^-1]",
    "v_RS_R_z [m s^-1]",
    "b_w_RS_S_x [rad s^-1]",
    "b_w_RS_S_y [rad s^-1]",
    "b_w_RS_S_z [rad s^-1]",
    "b_a_RS_S_x [m s^-2]",
    "b_a_RS_S_y [m s^-2]",
    "b_a_RS_S_z [m s^-2]",
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


def _camera_calibration() -> dict[str, object]:
    return {
        "sensor_type": "camera",
        "comment": "synthetic cam0 fixture",
        "T_BS": _transform(),
        "rate_hz": 20,
        "resolution": [752, 480],
        "camera_model": "pinhole",
        "intrinsics": [458.0, 457.0, 367.0, 248.0],
        "distortion_model": "radial-tangential",
        "distortion_coefficients": [-0.28, 0.07, 0.0001, -0.0002],
    }


def _imu_calibration() -> dict[str, object]:
    return {
        "sensor_type": "imu",
        "comment": "synthetic imu0 fixture",
        "T_BS": _transform(),
        "rate_hz": 200,
        "gyroscope_noise_density": 0.0002,
        "gyroscope_random_walk": 0.00002,
        "accelerometer_noise_density": 0.002,
        "accelerometer_random_walk": 0.003,
    }


def _ground_truth_calibration() -> dict[str, object]:
    return {
        "sensor_type": "visual-inertial",
        "comment": "synthetic ground-truth fixture",
        "T_BS": _transform(),
        "rate_hz": 100,
    }


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _ground_truth_row(
    timestamp: int,
    *,
    position_x: float,
    quaternion: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
) -> tuple[object, ...]:
    return (
        timestamp,
        position_x,
        position_x + 1.0,
        position_x + 2.0,
        *quaternion,
        position_x + 3.0,
        position_x + 4.0,
        position_x + 5.0,
        0.01 + position_x,
        0.02 + position_x,
        0.03 + position_x,
        0.10 + position_x,
        0.20 + position_x,
        0.30 + position_x,
    )


class EuRoCFixture:
    def __init__(self, directory: str) -> None:
        self.root = Path(directory) / "MH_01_easy"
        self.camera = self.root / "mav0/cam0"
        self.imu = self.root / "mav0/imu0"
        self.ground_truth = self.root / "mav0/state_groundtruth_estimate0"
        (self.camera / "data").mkdir(parents=True)
        self.imu.mkdir(parents=True)
        self.ground_truth.mkdir(parents=True)
        self.camera_yaml = self.camera / "sensor.yaml"
        self.imu_yaml = self.imu / "sensor.yaml"
        self.ground_truth_yaml = self.ground_truth / "sensor.yaml"
        self.camera_json = _camera_calibration()
        self.imu_json = _imu_calibration()
        self.ground_truth_json = _ground_truth_calibration()
        self.write_calibrations()
        self.write_camera([(100, "100.png"), (200, "200.png"), (300, "300.png")])
        self.write_imu(
            [
                (100, 1, 2, 3, 4, 5, 6),
                (150, 2, 3, 4, 5, 6, 7),
                (200, 3, 4, 5, 6, 7, 8),
                (250, 4, 5, 6, 7, 8, 9),
                (300, 5, 6, 7, 8, 9, 10),
            ]
        )
        self.write_ground_truth(
            [
                _ground_truth_row(100, position_x=0.0),
                _ground_truth_row(300, position_x=2.0),
            ]
        )

    def write_calibrations(self) -> None:
        for path, document in (
            (self.camera_yaml, self.camera_json),
            (self.imu_yaml, self.imu_json),
            (self.ground_truth_yaml, self.ground_truth_json),
        ):
            # JSON is valid YAML, keeping this parser test independent of PyYAML.
            path.write_text(json.dumps(document), encoding="utf-8")

    def write_camera(self, rows: list[tuple[object, ...]]) -> None:
        for row in rows:
            filename = str(row[1])
            if Path(filename).name == filename:
                (self.camera / "data" / filename).write_bytes(b"synthetic-image")
        _write_csv(self.camera / "data.csv", CAMERA_HEADER, rows)

    def write_imu(self, rows: list[tuple[object, ...]]) -> None:
        _write_csv(self.imu / "data.csv", IMU_HEADER, rows)

    def write_ground_truth(self, rows: list[tuple[object, ...]]) -> None:
        _write_csv(self.ground_truth / "data.csv", GROUND_TRUTH_HEADER, rows)


class EuRoCDataTests(unittest.TestCase):
    def test_loads_exact_asl_sources_and_preserves_native_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)

            sequence = load_euroc_sequence(fixture.root)

            self.assertEqual(sequence.sequence_id, "MH_01_easy")
            self.assertEqual(len(sequence.camera_frames), 3)
            self.assertEqual(len(sequence.imu_measurements), 5)
            self.assertEqual(len(sequence.ground_truth_states), 2)
            self.assertEqual(sequence.camera_frames[0].timestamp_ns, 100)
            self.assertEqual(sequence.camera_frames[0].filename, "100.png")
            self.assertEqual(
                sequence.imu_measurements[0].angular_velocity_rs_s_rad_s,
                (1.0, 2.0, 3.0),
            )
            self.assertEqual(sequence.camera_calibration.intrinsics[0], 458.0)
            self.assertEqual(sequence.camera_calibration.resolution_width_px, 752)
            self.assertEqual(sequence.imu_calibration.rate_hz, 200.0)
            self.assertEqual(sequence.camera_calibration.t_bs[0][3], 0.1)
            self.assertEqual(
                sequence.ground_truth_states[0].quaternion_rs_wxyz,
                (1.0, 0.0, 0.0, 0.0),
            )
            with self.assertRaises(FrozenInstanceError):
                sequence.sequence_id = "changed"  # type: ignore[misc]
            self.assertFalse(hasattr(sequence, "__dict__"))

    def test_frame_pairs_use_strictly_causal_imu_interval_and_interpolated_gt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sequence = load_euroc_sequence(EuRoCFixture(directory).root)

            pairs = tuple(iter_causal_frame_pairs(sequence))

            self.assertEqual(len(pairs), 2)
            self.assertEqual(
                tuple(item.timestamp_ns for item in pairs[0].imu_measurements),
                (150, 200),
            )
            self.assertEqual(
                tuple(item.timestamp_ns for item in pairs[1].imu_measurements),
                (250, 300),
            )
            self.assertEqual(pairs[0].previous_ground_truth.timestamp_ns, 100)
            self.assertEqual(pairs[0].current_ground_truth.timestamp_ns, 200)
            self.assertEqual(pairs[0].current_ground_truth.position_rs_r_m, (1.0, 2.0, 3.0))

    def test_frame_pairs_can_omit_ground_truth_but_never_invent_imu(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            fixture.write_imu([(100, 1, 2, 3, 4, 5, 6), (300, 1, 2, 3, 4, 5, 6)])
            sequence = load_euroc_sequence(fixture.root)

            with self.assertRaisesRegex(EuRoCDataError, r"\(100, 200\]"):
                tuple(iter_causal_frame_pairs(sequence))
            pairs = tuple(
                iter_causal_frame_pairs(
                    sequence,
                    include_ground_truth=False,
                    require_imu=False,
                )
            )
            self.assertEqual(pairs[0].imu_measurements, ())
            self.assertIsNone(pairs[0].previous_ground_truth)
            self.assertIsNone(pairs[0].current_ground_truth)

    def test_ground_truth_interpolation_is_linear_and_shortest_arc_slerp(self) -> None:
        first = GroundTruthState(
            10,
            (0.0, 1.0, 2.0),
            (1.0, 0.0, 0.0, 0.0),
            (3.0, 4.0, 5.0),
            (0.0, 0.1, 0.2),
            (0.3, 0.4, 0.5),
        )
        second = GroundTruthState(
            30,
            (2.0, 3.0, 4.0),
            (0.0, 0.0, 0.0, 1.0),
            (5.0, 6.0, 7.0),
            (0.2, 0.3, 0.4),
            (0.5, 0.6, 0.7),
        )

        middle = interpolate_ground_truth((first, second), 20)

        self.assertEqual(middle.position_rs_r_m, (1.0, 2.0, 3.0))
        self.assertEqual(middle.velocity_rs_r_m_s, (4.0, 5.0, 6.0))
        self.assertAlmostEqual(middle.quaternion_rs_wxyz[0], math.sqrt(0.5))
        self.assertAlmostEqual(middle.quaternion_rs_wxyz[3], math.sqrt(0.5))
        self.assertAlmostEqual(
            sum(value * value for value in middle.quaternion_rs_wxyz),
            1.0,
        )

        antipodal = interpolate_ground_truth(
            (first, replace(second, quaternion_rs_wxyz=(-1.0, 0.0, 0.0, 0.0))),
            20,
        )
        self.assertEqual(antipodal.quaternion_rs_wxyz, (1.0, 0.0, 0.0, 0.0))

    def test_interpolation_rejects_extrapolation_and_unordered_states(self) -> None:
        state = GroundTruthState(
            10,
            (0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 0.0),
        )
        with self.assertRaisesRegex(EuRoCDataError, "outside ground-truth coverage"):
            interpolate_ground_truth((state,), 9)
        with self.assertRaisesRegex(EuRoCDataError, "strictly increasing"):
            interpolate_ground_truth((state, state), 10)

    def test_sequence_splits_must_be_nonempty_unique_and_disjoint(self) -> None:
        splits = validate_sequence_splits(
            train=("MH_01_easy", "MH_02_easy"),
            validation=("V1_01_easy",),
            test=("V2_01_easy",),
        )
        self.assertEqual(splits.validation, ("V1_01_easy",))
        with self.assertRaises(FrozenInstanceError):
            splits.test = ()  # type: ignore[misc]
        with self.assertRaisesRegex(EuRoCDataError, "both train and test"):
            validate_sequence_splits(train=("same",), validation=("validation",), test=("same",))
        with self.assertRaisesRegex(EuRoCDataError, "duplicate"):
            validate_sequence_splits(
                train=("one", "one"), validation=("validation",), test=("test",)
            )
        with self.assertRaisesRegex(EuRoCDataError, "at least one"):
            validate_sequence_splits(train=(), validation=("validation",), test=("test",))

    def test_hashes_bind_exact_file_bytes_paths_and_calibration_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            first = source_files_sha256(
                fixture.root,
                ("mav0/cam0/data.csv", "mav0/imu0/data.csv"),
            )
            reordered = source_files_sha256(
                fixture.root,
                ("mav0/imu0/data.csv", "mav0/cam0/data.csv"),
            )
            self.assertEqual(first, reordered)
            self.assertRegex(first, r"^[0-9a-f]{64}$")
            self.assertRegex(calibration_sources_sha256(fixture.root), r"^[0-9a-f]{64}$")
            self.assertEqual(
                sha256_file(fixture.camera_yaml),
                __import__("hashlib").sha256(fixture.camera_yaml.read_bytes()).hexdigest(),
            )
            with (fixture.camera / "data.csv").open("a", encoding="utf-8") as handle:
                handle.write("400,400.png\n")
            changed = source_files_sha256(
                fixture.root,
                ("mav0/cam0/data.csv", "mav0/imu0/data.csv"),
            )
            self.assertNotEqual(first, changed)
            with self.assertRaisesRegex(EuRoCDataError, "root-relative"):
                source_files_sha256(fixture.root, ("../outside",))

    def test_sequence_hash_binds_every_consumed_image_and_sensor_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            before = sequence_sources_sha256(fixture.root)

            (fixture.camera / "data" / "200.png").write_bytes(b"changed-image")

            self.assertNotEqual(before, sequence_sources_sha256(fixture.root))

    def test_missing_required_path_and_missing_image_fail_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            fixture.ground_truth_yaml.unlink()
            with self.assertRaisesRegex(EuRoCDataError, "missing required EuRoC file"):
                load_euroc_sequence(fixture.root)
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            (fixture.camera / "data/200.png").unlink()
            with self.assertRaisesRegex(EuRoCDataError, "image does not exist"):
                load_euroc_sequence(fixture.root)

    def test_camera_filename_must_not_escape_exact_data_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            fixture.write_camera([(100, "../outside.png")])
            with self.assertRaisesRegex(EuRoCDataError, "safe basename"):
                load_euroc_sequence(fixture.root)

    def test_every_sensor_stream_requires_strictly_increasing_unique_timestamps(self) -> None:
        writers = (
            lambda fixture: fixture.write_camera([(100, "a.png"), (100, "b.png")]),
            lambda fixture: fixture.write_imu([(100, 1, 2, 3, 4, 5, 6), (100, 1, 2, 3, 4, 5, 6)]),
            lambda fixture: fixture.write_ground_truth(
                [
                    _ground_truth_row(100, position_x=0.0),
                    _ground_truth_row(100, position_x=1.0),
                ]
            ),
        )
        for writer in writers:
            with self.subTest(writer=writer), tempfile.TemporaryDirectory() as directory:
                fixture = EuRoCFixture(directory)
                writer(fixture)
                with self.assertRaisesRegex(EuRoCDataError, "strictly increasing"):
                    load_euroc_sequence(fixture.root)

    def test_nonfinite_measurement_and_bad_quaternion_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            fixture.write_imu([(100, float("nan"), 2, 3, 4, 5, 6)])
            with self.assertRaisesRegex(EuRoCDataError, "must be finite"):
                load_euroc_sequence(fixture.root)
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            fixture.write_ground_truth(
                [
                    _ground_truth_row(
                        100,
                        position_x=0.0,
                        quaternion=(2.0, 0.0, 0.0, 0.0),
                    )
                ]
            )
            with self.assertRaisesRegex(EuRoCDataError, "quaternion norm"):
                load_euroc_sequence(fixture.root)

    def test_calibration_requires_valid_intrinsics_rates_noise_and_rigid_transform(self) -> None:
        invalid_mutations = (
            (
                "camera focal length",
                lambda fixture: fixture.camera_json.__setitem__(
                    "intrinsics", [0.0, 457.0, 367.0, 248.0]
                ),
                "focal lengths",
            ),
            (
                "camera resolution",
                lambda fixture: fixture.camera_json.__setitem__("resolution", [0, 480]),
                "resolution",
            ),
            (
                "camera rate",
                lambda fixture: fixture.camera_json.__setitem__("rate_hz", float("inf")),
                "finite positive",
            ),
            (
                "imu noise",
                lambda fixture: fixture.imu_json.__setitem__("gyroscope_noise_density", -1.0),
                "finite positive",
            ),
            (
                "rigid transform",
                lambda fixture: fixture.camera_json["T_BS"].__setitem__(
                    "data",
                    [
                        2.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                    ],
                ),
                "orthonormal",
            ),
        )
        for name, mutate, message in invalid_mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                fixture = EuRoCFixture(directory)
                mutate(fixture)
                fixture.write_calibrations()
                with self.assertRaisesRegex(EuRoCDataError, message):
                    load_euroc_sequence(fixture.root)

    def test_csv_header_and_row_width_are_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            _write_csv(
                fixture.imu / "data.csv",
                ("timestamp", *IMU_HEADER[1:]),
                [(100, 1, 2, 3, 4, 5, 6)],
            )
            with self.assertRaisesRegex(EuRoCDataError, "unexpected CSV header"):
                load_euroc_sequence(fixture.root)
        with tempfile.TemporaryDirectory() as directory:
            fixture = EuRoCFixture(directory)
            fixture.write_imu([(100, 1, 2)])
            with self.assertRaisesRegex(EuRoCDataError, "exactly 7 columns"):
                load_euroc_sequence(fixture.root)


if __name__ == "__main__":
    unittest.main()

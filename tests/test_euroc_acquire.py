from __future__ import annotations

import csv
import hashlib
import io
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path

from compact_vio.data.acquire import (
    ArchivePlan,
    EuRoCAcquisitionError,
    extract_sequences,
    load_archive_plans,
    verify_archive,
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
LEICA_HEADER = (
    "#timestamp [ns]",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
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


def _csv_bytes(header: tuple[str, ...], rows: tuple[tuple[object, ...], ...]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue().encode()


def _sensor_files() -> dict[str, bytes]:
    camera_calibration = {
        "sensor_type": "camera",
        "T_BS": _transform(),
        "rate_hz": 20,
        "resolution": [752, 480],
        "camera_model": "pinhole",
        "intrinsics": [458.0, 457.0, 367.0, 248.0],
        "distortion_model": "radial-tangential",
        "distortion_coefficients": [-0.28, 0.07, 0.0001, -0.0002],
    }
    imu_calibration = {
        "sensor_type": "imu",
        "T_BS": _transform(),
        "rate_hz": 200,
        "gyroscope_noise_density": 0.0002,
        "gyroscope_random_walk": 0.00002,
        "accelerometer_noise_density": 0.002,
        "accelerometer_random_walk": 0.003,
    }
    return {
        "mav0/cam0/data.csv": _csv_bytes(
            CAMERA_HEADER,
            ((100, "100.png"), (200, "200.png"), (300, "300.png")),
        ),
        "mav0/cam0/sensor.yaml": json.dumps(camera_calibration).encode(),
        "mav0/cam0/data/100.png": b"image-100",
        "mav0/cam0/data/200.png": b"image-200",
        "mav0/cam0/data/300.png": b"image-300",
        "mav0/imu0/data.csv": _csv_bytes(
            IMU_HEADER,
            (
                (100, 1, 2, 3, 4, 5, 6),
                (150, 2, 3, 4, 5, 6, 7),
                (200, 3, 4, 5, 6, 7, 8),
                (250, 4, 5, 6, 7, 8, 9),
                (300, 5, 6, 7, 8, 9, 10),
            ),
        ),
        "mav0/imu0/sensor.yaml": json.dumps(imu_calibration).encode(),
    }


def _ground_truth_files() -> dict[str, bytes]:
    calibration = {
        "sensor_type": "visual-inertial",
        "T_BS": _transform(),
        "rate_hz": 100,
    }
    row = (
        100,
        0,
        1,
        2,
        1,
        0,
        0,
        0,
        3,
        4,
        5,
        0.01,
        0.02,
        0.03,
        0.1,
        0.2,
        0.3,
    )
    return {
        "mav0/state_groundtruth_estimate0/data.csv": _csv_bytes(
            GROUND_TRUTH_HEADER,
            (row, (300, *row[1:])),
        ),
        "mav0/state_groundtruth_estimate0/sensor.yaml": json.dumps(calibration).encode(),
    }


def _leica_files() -> dict[str, bytes]:
    calibration = {
        "sensor_type": "position",
        "T_BS": _transform(),
    }
    return {
        "mav0/leica0/data.csv": _csv_bytes(
            LEICA_HEADER,
            ((100, 1.0, 2.0, 3.0), (300, 4.0, 5.0, 6.0)),
        ),
        "mav0/leica0/sensor.yaml": json.dumps(calibration).encode(),
    }


def _write_direct_archive(
    path: Path,
    sequence: str,
    files: dict[str, bytes],
) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for relative, content in files.items():
            archive.writestr(f"dataset/{sequence}/{relative}", content)


def _write_nested_archive(
    path: Path,
    sequence: str,
    files: dict[str, bytes],
) -> None:
    inner_stream = io.BytesIO()
    with zipfile.ZipFile(inner_stream, "w") as inner:
        for relative, content in files.items():
            inner.writestr(relative, content)
    with zipfile.ZipFile(path, "w") as outer:
        outer.writestr(f"dataset/{sequence}/{sequence}.zip", inner_stream.getvalue())


class EuRoCAcquisitionTests(unittest.TestCase):
    def test_load_and_verify_exact_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "room.zip"
            archive.write_bytes(b"exact archive bytes")
            plan_document = {
                "record_type": "euroc_acquisition_plan",
                "archives": [
                    {
                        "archive_id": "room",
                        "filename": "room.zip",
                        "url": "https://example.invalid/room.zip",
                        "size_bytes": archive.stat().st_size,
                        "md5": hashlib.md5(archive.read_bytes()).hexdigest(),
                        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                        "sequences": ["V1_01_easy"],
                    }
                ],
            }
            plan_path = root / "plan.json"
            plan_path.write_text(json.dumps(plan_document), encoding="utf-8")
            plan = load_archive_plans(plan_path)["room"]
            identity = verify_archive(archive, plan)
            self.assertEqual(identity["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_verify_rejects_size_and_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "room.zip"
            archive.write_bytes(b"wrong")
            plan = ArchivePlan(
                "room",
                "room.zip",
                "https://example.invalid/room.zip",
                99,
                "0" * 32,
                "0" * 64,
                ("V1_01_easy",),
            )
            with self.assertRaisesRegex(EuRoCAcquisitionError, "size mismatch"):
                verify_archive(archive, plan)

    def test_extracts_direct_machine_hall_with_position_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "machine_hall.zip"
            files = {**_sensor_files(), **_leica_files()}
            files["mav0/cam1/data.csv"] = b"must-not-be-extracted"
            _write_direct_archive(archive, "MH_01_easy", files)

            reports = extract_sequences(archive, root / "data", ("MH_01_easy",))

            self.assertEqual(
                reports,
                (
                    {
                        "sequence_id": "MH_01_easy",
                        "camera_frame_count": 3,
                        "imu_measurement_count": 5,
                        "ground_truth_state_count": 0,
                        "position_reference_count": 2,
                        "extracted_file_count": 9,
                    },
                ),
            )
            extracted = root / "data/MH_01_easy/mav0"
            self.assertTrue((extracted / "leica0/data.csv").is_file())
            self.assertFalse((extracted / "cam1").exists())

    def test_extracts_nested_vicon_and_preserves_full_state_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "vicon_room.zip"
            _write_nested_archive(
                archive,
                "V1_01_easy",
                {**_sensor_files(), **_ground_truth_files()},
            )

            reports = extract_sequences(archive, root / "data", ("V1_01_easy",))

            self.assertEqual(reports[0]["camera_frame_count"], 3)
            self.assertEqual(reports[0]["imu_measurement_count"], 5)
            self.assertEqual(reports[0]["ground_truth_state_count"], 2)
            self.assertEqual(reports[0]["position_reference_count"], 0)
            self.assertEqual(reports[0]["extracted_file_count"], 9)
            self.assertTrue(
                (root / "data/V1_01_easy/mav0/state_groundtruth_estimate0/data.csv").is_file()
            )

    def test_extract_requires_camera_imu_and_a_supported_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "sensor_only.zip"
            _write_direct_archive(archive, "MH_01_easy", _sensor_files())
            with self.assertRaisesRegex(EuRoCAcquisitionError, "no supported reference stream"):
                extract_sequences(archive, root / "data", ("MH_01_easy",))
            self.assertFalse((root / "data/MH_01_easy").exists())

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "missing_imu_calibration.zip"
            files = {**_sensor_files(), **_leica_files()}
            del files["mav0/imu0/sensor.yaml"]
            _write_direct_archive(archive, "MH_01_easy", files)
            with self.assertRaisesRegex(EuRoCAcquisitionError, "missing required EuRoC file"):
                extract_sequences(archive, root / "data", ("MH_01_easy",))
            self.assertFalse((root / "data/MH_01_easy").exists())

    def test_extract_validates_every_present_reference_stream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "both_references.zip"
            files = {**_sensor_files(), **_ground_truth_files(), **_leica_files()}
            files["mav0/leica0/data.csv"] = _csv_bytes(LEICA_HEADER, ())
            _write_direct_archive(archive, "MH_01_easy", files)

            with self.assertRaisesRegex(EuRoCAcquisitionError, "contains no data rows"):
                extract_sequences(archive, root / "data", ("MH_01_easy",))
            self.assertFalse((root / "data/MH_01_easy").exists())

    def test_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "room.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../V1_01_easy/mav0/cam0/data/1.png", b"x")
            with self.assertRaisesRegex(EuRoCAcquisitionError, "unsafe ZIP member"):
                extract_sequences(archive, root / "data", ("V1_01_easy",))

    def test_extract_rejects_nested_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "room.zip"
            _write_nested_archive(
                archive,
                "V1_01_easy",
                {"../mav0/cam0/data/1.png": b"x"},
            )
            with self.assertRaisesRegex(EuRoCAcquisitionError, "unsafe nested ZIP member"):
                extract_sequences(archive, root / "data", ("V1_01_easy",))

    def test_extract_rejects_direct_and_nested_zip_symlinks(self) -> None:
        for nested in (False, True):
            with self.subTest(nested=nested), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                archive = root / "room.zip"
                link = zipfile.ZipInfo("mav0/leica0/data.csv")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                if nested:
                    inner_stream = io.BytesIO()
                    with zipfile.ZipFile(inner_stream, "w") as inner:
                        inner.writestr(link, "target")
                    with zipfile.ZipFile(archive, "w") as outer:
                        outer.writestr(
                            "V1_01_easy/V1_01_easy.zip",
                            inner_stream.getvalue(),
                        )
                    expected = "nested ZIP symlink"
                else:
                    link.filename = "V1_01_easy/mav0/leica0/data.csv"
                    with zipfile.ZipFile(archive, "w") as outer:
                        outer.writestr(link, "target")
                    expected = "ZIP symlink"

                with self.assertRaisesRegex(EuRoCAcquisitionError, expected):
                    extract_sequences(archive, root / "data", ("V1_01_easy",))

    def test_archive_plan_rejects_insecure_url(self) -> None:
        with self.assertRaisesRegex(EuRoCAcquisitionError, "HTTPS"):
            ArchivePlan(
                "room",
                "room.zip",
                "http://example.invalid/room.zip",
                1,
                "0" * 32,
                "0" * 64,
                ("V1_01_easy",),
            )

    def test_archive_plan_and_extraction_reject_path_like_identifiers(self) -> None:
        for sequence in ("../escape", "/absolute", "nested\\escape"):
            with (
                self.subTest(sequence=sequence),
                self.assertRaisesRegex(
                    EuRoCAcquisitionError,
                    "safe identifier",
                ),
            ):
                ArchivePlan(
                    "room",
                    "room.zip",
                    "https://example.invalid/room.zip",
                    1,
                    "0" * 32,
                    "0" * 64,
                    (sequence,),
                )


if __name__ == "__main__":
    unittest.main()

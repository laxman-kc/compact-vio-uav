from __future__ import annotations

import csv
import json
import math
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from compact_vio.data import (
    EuRoCDataError,
    EuRoCPositionReference,
    ImuCalibration,
    LeicaCalibration,
    LeicaPosition,
    interpolate_euroc_position,
    leica_origin_in_imu_frame,
    load_euroc_position_reference,
    position_reference_sources_sha256,
    source_files_sha256,
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


def _write_csv(path: Path, rows: list[tuple[object, ...]], *, header=LEICA_HEADER) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


class LeicaFixture:
    def __init__(self, directory: str) -> None:
        self.root = Path(directory) / "MH_01_easy"
        self.leica = self.root / "mav0/leica0"
        self.leica.mkdir(parents=True)
        self.csv_path = self.leica / "data.csv"
        self.yaml_path = self.leica / "sensor.yaml"
        self.document = {
            "sensor_type": "position",
            "comment": "synthetic Leica fixture",
            "T_BS": _transform(),
        }
        self.write_yaml()
        self.write_rows(
            [
                (100, 0.0, 1.0, 2.0),
                (300, 2.0, 3.0, 4.0),
                (500, 6.0, 7.0, 8.0),
            ]
        )

    def write_yaml(self) -> None:
        self.yaml_path.write_text(json.dumps(self.document), encoding="utf-8")

    def write_rows(self, rows: list[tuple[object, ...]]) -> None:
        _write_csv(self.csv_path, rows)


class EuRoCPositionTests(unittest.TestCase):
    def test_leica_origin_is_derived_in_the_imu_sensor_frame(self) -> None:
        imu_t_bs = (
            (0.0, -1.0, 0.0, 1.0),
            (1.0, 0.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        leica_t_bs = (
            (1.0, 0.0, 0.0, 1.0),
            (0.0, 1.0, 0.0, 1.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        imu = ImuCalibration(
            "imu",
            None,
            imu_t_bs,
            200.0,
            0.1,
            0.1,
            0.1,
            0.1,
            Path("imu.yaml"),
        )
        leica = LeicaCalibration("position", None, leica_t_bs, Path("leica.yaml"))

        self.assertEqual(leica_origin_in_imu_frame(imu, leica), (1.0, 0.0, 0.0))

        reflected = (
            (-1.0, 0.0, 0.0, 0.0),
            (0.0, 1.0, 0.0, 0.0),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
        object.__setattr__(imu, "t_bs", reflected)
        with self.assertRaisesRegex(EuRoCDataError, "determinant"):
            leica_origin_in_imu_frame(imu, leica)

    def test_loads_exact_position_only_reference_and_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LeicaFixture(directory)

            reference = load_euroc_position_reference(fixture.root)

            self.assertIs(type(reference), EuRoCPositionReference)
            self.assertEqual(reference.sequence_id, "MH_01_easy")
            self.assertEqual(reference.root, fixture.root.resolve())
            self.assertIs(type(reference.calibration), LeicaCalibration)
            self.assertEqual(reference.calibration.sensor_type, "position")
            self.assertEqual(reference.calibration.comment, "synthetic Leica fixture")
            self.assertEqual(reference.calibration.t_bs[0][3], 0.1)
            self.assertEqual(reference.calibration.source_path, fixture.yaml_path.resolve())
            self.assertEqual(reference.positions[0], LeicaPosition(100, (0.0, 1.0, 2.0)))
            with self.assertRaises(FrozenInstanceError):
                reference.sequence_id = "changed"  # type: ignore[misc]
            self.assertFalse(hasattr(reference, "__dict__"))

    def test_exact_and_linear_interpolation_accept_reference_or_positions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            reference = load_euroc_position_reference(LeicaFixture(directory).root)

            self.assertEqual(
                interpolate_euroc_position(reference, 100),
                LeicaPosition(100, (0.0, 1.0, 2.0)),
            )
            self.assertEqual(
                interpolate_euroc_position(reference.positions, 200),
                LeicaPosition(200, (1.0, 2.0, 3.0)),
            )
            with self.assertRaisesRegex(EuRoCDataError, "exceeding"):
                interpolate_euroc_position(
                    reference.positions,
                    200,
                    max_bracket_interval_ns=100,
                )
            self.assertEqual(
                interpolate_euroc_position(reference, 500),
                LeicaPosition(500, (6.0, 7.0, 8.0)),
            )

    def test_interpolation_rejects_extrapolation_and_invalid_records(self) -> None:
        positions = (
            LeicaPosition(100, (0.0, 1.0, 2.0)),
            LeicaPosition(300, (2.0, 3.0, 4.0)),
        )
        for timestamp in (99, 301):
            with (
                self.subTest(timestamp=timestamp),
                self.assertRaisesRegex(EuRoCDataError, "outside Leica position coverage"),
            ):
                interpolate_euroc_position(positions, timestamp)
        for timestamp in (-1, True, 1.0):
            with (
                self.subTest(timestamp=timestamp),
                self.assertRaisesRegex(EuRoCDataError, "timestamp_ns"),
            ):
                interpolate_euroc_position(positions, timestamp)  # type: ignore[arg-type]
        with self.assertRaisesRegex(EuRoCDataError, "must not be empty"):
            interpolate_euroc_position((), 100)
        with self.assertRaisesRegex(EuRoCDataError, "strictly increasing"):
            interpolate_euroc_position((positions[1], positions[0]), 200)
        with self.assertRaisesRegex(EuRoCDataError, "finite"):
            interpolate_euroc_position(
                (LeicaPosition(100, (math.nan, 0.0, 0.0)), positions[1]),
                200,
            )

    def test_loader_rejects_wrong_header_timestamp_rows_and_nonfinite_positions(self) -> None:
        cases = (
            ("header", [(100, 0, 1, 2)], ("#timestamp", *LEICA_HEADER[1:])),
            ("unsigned", [("-1", 0, 1, 2)], LEICA_HEADER),
            ("columns", [(100, 0, 1)], LEICA_HEADER),
            ("finite", [(100, "nan", 1, 2)], LEICA_HEADER),
        )
        for message, rows, header in cases:
            with self.subTest(case=message), tempfile.TemporaryDirectory() as directory:
                fixture = LeicaFixture(directory)
                _write_csv(fixture.csv_path, rows, header=header)
                with self.assertRaisesRegex(EuRoCDataError, message):
                    load_euroc_position_reference(fixture.root)

        for timestamps in ((100, 100), (200, 100)):
            with self.subTest(timestamps=timestamps), tempfile.TemporaryDirectory() as directory:
                fixture = LeicaFixture(directory)
                fixture.write_rows([(timestamps[0], 0, 1, 2), (timestamps[1], 1, 2, 3)])
                with self.assertRaisesRegex(EuRoCDataError, "strictly increasing"):
                    load_euroc_position_reference(fixture.root)

    def test_loader_rejects_missing_or_forged_sources_and_wrong_sensor_type(self) -> None:
        for name in ("data.csv", "sensor.yaml"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                fixture = LeicaFixture(directory)
                (fixture.leica / name).unlink()
                with self.assertRaisesRegex(EuRoCDataError, "missing required EuRoC file"):
                    load_euroc_position_reference(fixture.root)

        with tempfile.TemporaryDirectory() as directory:
            fixture = LeicaFixture(directory)
            fixture.document["sensor_type"] = "visual-inertial"
            fixture.write_yaml()
            with self.assertRaisesRegex(EuRoCDataError, "must equal 'position'"):
                load_euroc_position_reference(fixture.root)

        with tempfile.TemporaryDirectory() as directory:
            fixture = LeicaFixture(directory)
            target = fixture.root / "forged.csv"
            target.write_bytes(fixture.csv_path.read_bytes())
            fixture.csv_path.unlink()
            fixture.csv_path.symlink_to(target)
            with self.assertRaisesRegex(EuRoCDataError, "contained regular file"):
                load_euroc_position_reference(fixture.root)

    def test_t_bs_and_yaml_duplicates_fail_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LeicaFixture(directory)
            transform = _transform()
            transform["data"] = [0.0] * 16
            fixture.document["T_BS"] = transform
            fixture.write_yaml()
            with self.assertRaisesRegex(EuRoCDataError, "bottom row"):
                load_euroc_position_reference(fixture.root)

        with tempfile.TemporaryDirectory() as directory:
            fixture = LeicaFixture(directory)
            fixture.yaml_path.write_text(
                '{"sensor_type":"position","sensor_type":"position",'
                '"T_BS":{"rows":4,"cols":4,"data":'
                "[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]}}",
                encoding="utf-8",
            )
            # JSON is a strict YAML subset and exercises duplicate-key rejection
            # without making this unit test depend on the optional PyYAML extra.
            with self.assertRaisesRegex(EuRoCDataError, "duplicate YAML/JSON key"):
                load_euroc_position_reference(fixture.root)

    def test_reference_hash_binds_only_exact_leica_csv_and_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LeicaFixture(directory)
            expected = source_files_sha256(
                fixture.root,
                ("mav0/leica0/data.csv", "mav0/leica0/sensor.yaml"),
            )

            first = position_reference_sources_sha256(fixture.root)

            self.assertEqual(first, expected)
            self.assertRegex(first, r"^[0-9a-f]{64}$")
            fixture.write_rows([(100, 9, 9, 9), (300, 2, 3, 4)])
            self.assertNotEqual(first, position_reference_sources_sha256(fixture.root))


if __name__ == "__main__":
    unittest.main()

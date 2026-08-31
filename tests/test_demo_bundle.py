from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from compact_vio.learning.demo_bundle import (
    RecordingBundleError,
    create_workflow_example_bundle,
    open_recording_bundle,
)
from compact_vio.learning.recording_inference import camera_samples


def _calibration() -> str:
    return json.dumps({"camera": {"resolution": [12, 8]}, "imu": {"T_BS": "identity"}})


def _corrupt_stored_member(path: Path, member_name: str) -> None:
    with zipfile.ZipFile(path) as archive:
        member = archive.getinfo(member_name)
        offset = (
            member.header_offset + 30 + len(member.filename.encode("utf-8")) + len(member.extra)
        )
    with path.open("r+b") as handle:
        handle.seek(offset)
        original = handle.read(1)
        handle.seek(offset)
        handle.write(bytes((original[0] ^ 0xFF,)))


class RecordingBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _write_bundle(self, entries: dict[str, bytes], *, name: str = "recording.zip") -> Path:
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member, payload in entries.items():
                archive.writestr(member, payload)
        return path

    def test_opens_direct_and_wrapped_payloads(self) -> None:
        entries = {
            "imu.csv": b"timestamp_ns,gx,gy,gz,ax,ay,az\n1,0,0,0,0,0,0\n",
            "calibration.json": _calibration().encode(),
            "frames/100.png": b"frame-one",
            "frames/200.png": b"frame-two",
            "compact-vio-bundle.json": json.dumps(
                {"schema_version": "1.0", "name": "Flight 7", "workflow_example": False}
            ).encode(),
        }
        for wrapped in (False, True):
            source = self._write_bundle(
                {(f"flight/{name}" if wrapped else name): value for name, value in entries.items()},
                name=f"bundle-{wrapped}.zip",
            )
            with open_recording_bundle(source) as opened:
                self.assertEqual(opened.display_name, "Flight 7")
                self.assertFalse(opened.is_workflow_example)
                self.assertEqual(opened.recording_path.name, "frames")
                self.assertTrue(opened.imu_csv_path.is_file())
                self.assertEqual(opened.calibration_path.name, "calibration.json")
                self.assertIsNone(opened.camera_timestamps_path)
                extracted_root = opened.recording_path.parent
            self.assertFalse(extracted_root.exists())

    def test_rejects_unsafe_ambiguous_and_unsupported_payloads(self) -> None:
        base = {
            "imu.csv": b"imu",
            "calibration.json": b"{}",
            "frames/100.png": b"one",
            "frames/200.png": b"two",
        }
        bad_cases = (
            ({**base, "../escape.png": b"bad"}, "unsafe path"),
            ({**base, "CALIBRATION.JSON": b"{}"}, "repeats a path"),
            ({**base, "notes.txt": b"extra"}, "unsupported bundle entry"),
            ({key: value for key, value in base.items() if key != "imu.csv"}, "imu.csv"),
            ({**base, "calibration.yaml": b"camera: {}"}, "exactly one calibration"),
        )
        for index, (entries, expected) in enumerate(bad_cases):
            with self.subTest(index=index):
                source = self._write_bundle(entries, name=f"bad-{index}.zip")
                with self.assertRaisesRegex(RecordingBundleError, expected):
                    with open_recording_bundle(source):
                        pass

    def test_rejects_symbolic_link_member(self) -> None:
        source = self.root / "symlink.zip"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("imu.csv", b"imu")
            archive.writestr("calibration.json", b"{}")
            archive.writestr("frames/100.png", b"one")
            archive.writestr("frames/200.png", b"two")
            link = zipfile.ZipInfo("frames/link.png")
            link.create_system = 3
            link.external_attr = 0o120777 << 16
            archive.writestr(link, b"100.png")
        with self.assertRaisesRegex(RecordingBundleError, "symbolic links"):
            with open_recording_bundle(source):
                pass

    def test_creates_deterministic_workflow_example(self) -> None:
        first = create_workflow_example_bundle(self.root / "example-a.zip")
        second = create_workflow_example_bundle(self.root / "example-b.zip")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        with open_recording_bundle(first) as opened:
            self.assertTrue(opened.is_workflow_example)
            self.assertIn("synthetic workflow", opened.display_name)
            self.assertEqual(len(tuple(opened.recording_path.glob("*.png"))), 12)
            self.assertGreater(len(opened.imu_csv_path.read_text().splitlines()), 400)
            self.assertEqual(opened.calibration_path.suffix, ".json")
        with zipfile.ZipFile(first) as left, zipfile.ZipFile(second) as right:
            self.assertEqual(left.namelist(), right.namelist())
            for name in left.namelist():
                self.assertEqual(left.read(name), right.read(name))

    def test_documented_camera_csv_frame_paths_resolve_inside_bundle(self) -> None:
        source = self._write_bundle(
            {
                "imu.csv": b"timestamp_ns,gx,gy,gz,ax,ay,az\n1,0,0,0,0,0,0\n",
                "calibration.json": _calibration().encode(),
                "camera.csv": (
                    b"timestamp_ns,filename\n100,frames/frame-0001.png\n200,frames/frame-0002.png\n"
                ),
                "frames/frame-0001.png": b"frame-one",
                "frames/frame-0002.png": b"frame-two",
            }
        )
        with open_recording_bundle(source) as opened:
            with camera_samples(opened.recording_path, opened.camera_timestamps_path) as frames:
                self.assertEqual(
                    tuple(frame.image_path.name for frame in frames),
                    ("frame-0001.png", "frame-0002.png"),
                )

    def test_rejects_corrupted_member_and_duplicate_manifest_keys(self) -> None:
        entries = {
            "imu.csv": b"timestamp_ns,gx,gy,gz,ax,ay,az\n1,0,0,0,0,0,0\n",
            "calibration.json": _calibration().encode(),
            "frames/100.png": b"frame-one",
            "frames/200.png": b"frame-two",
        }
        corrupted = self.root / "corrupted.zip"
        with zipfile.ZipFile(corrupted, "w", compression=zipfile.ZIP_STORED) as archive:
            for name, payload in entries.items():
                archive.writestr(name, payload)
        _corrupt_stored_member(corrupted, "imu.csv")
        with self.assertRaisesRegex(RecordingBundleError, "cannot extract recording bundle"):
            with open_recording_bundle(corrupted):
                pass

        duplicated = self._write_bundle(
            {
                **entries,
                "compact-vio-bundle.json": (
                    b'{"schema_version":"1.0","name":"first","name":"second"}'
                ),
            },
            name="duplicate-manifest.zip",
        )
        with self.assertRaisesRegex(RecordingBundleError, "duplicate JSON key"):
            with open_recording_bundle(duplicated):
                pass

    def test_rejects_bundle_over_compressed_source_limit(self) -> None:
        source = self._write_bundle(
            {
                "imu.csv": b"imu",
                "calibration.json": b"{}",
                "frames/100.png": b"one",
                "frames/200.png": b"two",
            },
            name="source-limit.zip",
        )
        with patch("compact_vio.learning.demo_bundle._MAX_SOURCE_BYTES", 1):
            with self.assertRaisesRegex(RecordingBundleError, "compressed size limit"):
                with open_recording_bundle(source):
                    pass


if __name__ == "__main__":
    unittest.main()

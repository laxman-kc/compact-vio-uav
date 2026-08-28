from __future__ import annotations

import hashlib
import json
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

    def test_extract_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "room.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../V1_01_easy/mav0/cam0/data/1.png", b"x")
            with self.assertRaisesRegex(EuRoCAcquisitionError, "unsafe ZIP member"):
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


if __name__ == "__main__":
    unittest.main()

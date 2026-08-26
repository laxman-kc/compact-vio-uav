from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from compact_vio.artifacts import (
    ArtifactIOError,
    ManifestFormatError,
    UnsafeBundleError,
    create_manifest,
    inventory_bundle,
    load_manifest,
    main,
    manifest_from_dict,
    verify_bundle,
)


class ArtifactManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, relative: str, content: bytes) -> Path:
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        return destination

    def test_create_is_deterministic_sorted_and_excludes_itself(self) -> None:
        first_root = self.root / "first"
        second_root = self.root / "second"
        for bundle_root in (first_root, second_root):
            (bundle_root / "nested").mkdir(parents=True)
            (bundle_root / "z-last.bin").write_bytes(b"z")
            (bundle_root / "nested/alpha.txt").write_bytes(b"alpha")
            (bundle_root / "empty").write_bytes(b"")

        first = create_manifest(first_root)
        first_bytes = (first_root / "artifact-manifest.json").read_bytes()
        second = create_manifest(second_root)
        second_bytes = (second_root / "artifact-manifest.json").read_bytes()

        self.assertEqual(first, second)
        self.assertEqual(first_bytes, second_bytes)
        with self.assertRaises(UnsafeBundleError):
            create_manifest(first_root)
        self.assertEqual((first_root / "artifact-manifest.json").read_bytes(), first_bytes)
        self.assertEqual(
            [record.path for record in first.files],
            ["empty", "nested/alpha.txt", "z-last.bin"],
        )
        self.assertNotIn("artifact-manifest.json", [record.path for record in first.files])
        parsed = json.loads(first_bytes)
        self.assertEqual(parsed["schema_version"], 1)
        self.assertEqual(parsed["hash_algorithm"], "sha256")
        alpha = next(item for item in parsed["files"] if item["path"] == "nested/alpha.txt")
        self.assertEqual(alpha["bytes"], 5)
        self.assertEqual(alpha["sha256"], hashlib.sha256(b"alpha").hexdigest())

    def test_custom_nested_manifest_is_excluded(self) -> None:
        self.write("payload.txt", b"payload")
        manifest = create_manifest(self.root, manifest_path="metadata/files.json")

        self.assertEqual([record.path for record in manifest.files], ["payload.txt"])
        self.assertTrue((self.root / "metadata/files.json").is_file())
        self.assertTrue(verify_bundle(self.root, manifest_path="metadata/files.json").ok)

    def test_verification_reports_every_difference_in_stable_order(self) -> None:
        self.write("gone.txt", b"gone")
        self.write("hash.txt", b"same")
        self.write("size.txt", b"short")
        self.write("ok.txt", b"ok")
        create_manifest(self.root)

        (self.root / "gone.txt").unlink()
        (self.root / "hash.txt").write_bytes(b"diff")
        (self.root / "size.txt").write_bytes(b"much-longer")
        self.write("unexpected-b.txt", b"b")
        self.write("unexpected-a.txt", b"a")

        report = verify_bundle(self.root)

        self.assertFalse(report.ok)
        self.assertEqual(report.missing, ("gone.txt",))
        self.assertEqual(report.unexpected, ("unexpected-a.txt", "unexpected-b.txt"))
        self.assertEqual([mismatch.path for mismatch in report.size_mismatches], ["size.txt"])
        self.assertEqual(
            [mismatch.path for mismatch in report.hash_mismatches],
            ["hash.txt", "size.txt"],
        )
        self.assertEqual(report.to_dict()["ok"], False)

    def test_manifest_tampering_is_detected(self) -> None:
        self.write("payload.txt", b"payload")
        create_manifest(self.root)
        manifest_path = self.root / "artifact-manifest.json"
        document = json.loads(manifest_path.read_text(encoding="utf-8"))
        document["files"][0]["sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(document), encoding="utf-8")

        report = verify_bundle(self.root)

        self.assertEqual([item.path for item in report.hash_mismatches], ["payload.txt"])

    def test_existing_manifest_path_is_never_overwritten(self) -> None:
        self.write("payload.txt", b"payload")
        destination = self.write("checkpoint.bin", b"irreplaceable-checkpoint")

        with self.assertRaises(UnsafeBundleError):
            create_manifest(self.root, manifest_path="checkpoint.bin")

        self.assertEqual(destination.read_bytes(), b"irreplaceable-checkpoint")
        self.assertEqual(list(self.root.glob(".compact-vio-manifest-*.tmp")), [])

    def test_failed_atomic_publish_leaves_no_partial_manifest(self) -> None:
        self.write("payload.txt", b"payload")

        with mock.patch("compact_vio.artifacts.os.link", side_effect=OSError("boom")):
            with self.assertRaises(ArtifactIOError):
                create_manifest(self.root)

        self.assertFalse((self.root / "artifact-manifest.json").exists())
        self.assertEqual(list(self.root.glob(".compact-vio-manifest-*.tmp")), [])

    def test_rejects_manifest_path_traversal_and_absolute_path(self) -> None:
        with self.assertRaises(UnsafeBundleError):
            create_manifest(self.root, manifest_path="../outside.json")
        with self.assertRaises(UnsafeBundleError):
            create_manifest(self.root, manifest_path="/tmp/outside.json")
        with self.assertRaises(UnsafeBundleError):
            create_manifest(self.root, manifest_path="a\\b.json")
        with self.assertRaises(UnsafeBundleError):
            create_manifest(self.root, manifest_path=".")

    def test_rejects_manifest_symlink(self) -> None:
        outside = Path(self.temporary_directory.name).parent / "outside-manifest-test"
        outside.write_bytes(b"do-not-touch")
        link = self.root / "artifact-manifest.json"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        try:
            with self.assertRaises(UnsafeBundleError):
                create_manifest(self.root)
            self.assertEqual(outside.read_bytes(), b"do-not-touch")
        finally:
            outside.unlink(missing_ok=True)

    def test_rejects_file_and_directory_symlinks_in_bundle(self) -> None:
        outside_file = self.root.parent / "outside-payload-test"
        outside_directory = self.root.parent / "outside-directory-test"
        outside_file.write_bytes(b"secret")
        outside_directory.mkdir(exist_ok=True)
        try:
            file_link = self.root / "file-link"
            directory_link = self.root / "directory-link"
            try:
                file_link.symlink_to(outside_file)
                directory_link.symlink_to(outside_directory, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaises(UnsafeBundleError):
                inventory_bundle(self.root)
            file_link.unlink()
            with self.assertRaises(UnsafeBundleError):
                inventory_bundle(self.root)
        finally:
            outside_file.unlink(missing_ok=True)
            outside_directory.rmdir()

    def test_rejects_symlink_bundle_root(self) -> None:
        link = self.root.parent / "bundle-root-link-test"
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")
        try:
            with self.assertRaises(UnsafeBundleError):
                inventory_bundle(link)
        finally:
            link.unlink(missing_ok=True)

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO creation is unavailable")
    def test_rejects_special_files(self) -> None:
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        with self.assertRaises(UnsafeBundleError):
            inventory_bundle(self.root)

    def test_manifest_schema_validation_is_strict(self) -> None:
        digest = "0" * 64
        valid = {
            "schema_version": 1,
            "hash_algorithm": "sha256",
            "files": [{"path": "a", "bytes": 1, "sha256": digest}],
        }
        self.assertEqual(manifest_from_dict(valid).files[0].path, "a")

        malformed_documents = [
            {**valid, "extra": True},
            {**valid, "schema_version": True},
            {**valid, "schema_version": 2},
            {**valid, "hash_algorithm": "md5"},
            {**valid, "files": "not-a-list"},
            {**valid, "files": [{"path": "../a", "bytes": 1, "sha256": digest}]},
            {**valid, "files": [{"path": "a", "bytes": -1, "sha256": digest}]},
            {**valid, "files": [{"path": "a", "bytes": True, "sha256": digest}]},
            {**valid, "files": [{"path": "a", "bytes": 1, "sha256": "A" * 64}]},
            {
                **valid,
                "files": [
                    {"path": "a", "bytes": 1, "sha256": digest},
                    {"path": "a", "bytes": 1, "sha256": digest},
                ],
            },
            {
                **valid,
                "files": [
                    {"path": "b", "bytes": 1, "sha256": digest},
                    {"path": "a", "bytes": 1, "sha256": digest},
                ],
            },
        ]
        for document in malformed_documents:
            with self.subTest(document=document):
                with self.assertRaises((ManifestFormatError, UnsafeBundleError)):
                    manifest_from_dict(document)

    def test_load_rejects_invalid_utf8_and_json(self) -> None:
        manifest = self.root / "artifact-manifest.json"
        manifest.write_bytes(b"\xff")
        with self.assertRaises(ManifestFormatError):
            load_manifest(self.root)
        manifest.write_text("{", encoding="utf-8")
        with self.assertRaises(ManifestFormatError):
            load_manifest(self.root)
        manifest.write_text(
            '{"schema_version":1,"schema_version":1,"hash_algorithm":"sha256","files":[]}',
            encoding="utf-8",
        )
        with self.assertRaises(ManifestFormatError):
            load_manifest(self.root)

    def test_cli_exit_codes_and_json_output(self) -> None:
        self.write("payload.txt", b"payload")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["create", str(self.root)]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["files"], 1)

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["verify", str(self.root)]), 0)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])

        (self.root / "payload.txt").write_bytes(b"changed")
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(["verify", str(self.root)]), 1)
        self.assertFalse(json.loads(stdout.getvalue())["ok"])

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.assertEqual(main(["verify", str(self.root), "--manifest", "../escape"]), 2)
        self.assertIn("error:", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

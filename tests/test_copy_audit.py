from __future__ import annotations

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from compact_vio.artifacts import create_manifest, read_manifest_bytes
from compact_vio.copy_audit import (
    EXIT_DIFFERENCES,
    EXIT_INVALID,
    EXIT_VERIFIED,
    CopyAuditError,
    audit_copies,
    main,
)


class CopyAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_bundle(
        self,
        name: str,
        *,
        manifest_path: str = "artifact-manifest.json",
        payload: bytes = b"representative-payload",
    ) -> Path:
        bundle = self.root / name
        (bundle / "nested").mkdir(parents=True)
        (bundle / "nested/payload.bin").write_bytes(payload)
        (bundle / "metadata.txt").write_text("fixture\n", encoding="utf-8")
        create_manifest(bundle, manifest_path=manifest_path)
        return bundle

    @staticmethod
    def manifest_hash(bundle: Path, manifest_path: str = "artifact-manifest.json") -> str:
        return hashlib.sha256(read_manifest_bytes(bundle, manifest_path=manifest_path)).hexdigest()

    def test_matching_copies_verify_content_but_never_restore_gate(self) -> None:
        primary = self.make_bundle("primary")
        backup = self.make_bundle("backup")

        result = audit_copies(
            expected_manifest_sha256=self.manifest_hash(primary),
            primary_bundle=primary,
            backup_bundle=backup,
            observed_at="2026-08-26T00:00:00+00:00",
        )

        self.assertEqual(result["assessment"], "copy_content_verified")
        self.assertTrue(result["content_identity_verified"])
        self.assertFalse(result["artifact_restore_gate_passed"])
        self.assertFalse(result["independent_failure_domains_verified"])
        self.assertFalse(result["outside_worker_locations_verified"])
        self.assertFalse(result["source_copy_deletion_verified"])
        self.assertFalse(result["restore_chronology_verified"])
        self.assertFalse(result["representative_load_verified"])
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["limitations"])
        observation = result["primary"]
        manifest_bytes = len(read_manifest_bytes(primary))
        self.assertEqual(observation["payload_file_count"], 2)
        self.assertEqual(observation["artifact_manifest_bytes"], manifest_bytes)
        self.assertEqual(observation["bundle_file_count"], 3)
        self.assertEqual(
            observation["bundle_bytes"],
            observation["payload_bytes"] + manifest_bytes,
        )

    def test_payload_difference_reports_bundle_mismatch(self) -> None:
        primary = self.make_bundle("primary")
        backup = self.make_bundle("backup")
        (backup / "nested/payload.bin").write_bytes(b"tampered")

        result = audit_copies(
            expected_manifest_sha256=self.manifest_hash(primary),
            primary_bundle=primary,
            backup_bundle=backup,
        )

        self.assertFalse(result["content_identity_verified"])
        self.assertIn(
            "backup_bundle_mismatch",
            {blocker["code"] for blocker in result["blockers"]},
        )
        self.assertTrue(result["backup"]["bundle_verification"]["hash_mismatches"])

    def test_frozen_manifest_hash_mismatch_is_reported(self) -> None:
        primary = self.make_bundle("primary")
        backup = self.make_bundle("backup")

        result = audit_copies(
            expected_manifest_sha256="0" * 64,
            primary_bundle=primary,
            backup_bundle=backup,
        )

        self.assertFalse(result["content_identity_verified"])
        self.assertEqual(
            {blocker["code"] for blocker in result["blockers"]},
            {"primary_manifest_hash_mismatch", "backup_manifest_hash_mismatch"},
        )

    def test_same_path_is_not_two_copies(self) -> None:
        primary = self.make_bundle("primary")

        result = audit_copies(
            expected_manifest_sha256=self.manifest_hash(primary),
            primary_bundle=primary,
            backup_bundle=primary,
        )

        self.assertFalse(result["content_identity_verified"])
        self.assertIn(
            "copy_paths_not_separate",
            {blocker["code"] for blocker in result["blockers"]},
        )

    def test_custom_manifest_path_is_supported(self) -> None:
        manifest_path = "metadata/files.json"
        primary = self.make_bundle("primary", manifest_path=manifest_path)
        backup = self.make_bundle("backup", manifest_path=manifest_path)

        result = audit_copies(
            expected_manifest_sha256=self.manifest_hash(primary, manifest_path),
            primary_bundle=primary,
            backup_bundle=backup,
            manifest_path=manifest_path,
        )

        self.assertTrue(result["content_identity_verified"])
        self.assertEqual(result["artifact_manifest_path"], manifest_path)

    def test_cli_exit_codes_and_json_contract(self) -> None:
        primary = self.make_bundle("primary")
        backup = self.make_bundle("backup")
        arguments = [
            "--expected-manifest-sha256",
            self.manifest_hash(primary),
            "--primary",
            str(primary),
            "--backup",
            str(backup),
            "--primary-ref",
            "primary-vault-copy",
            "--backup-ref",
            "independent-backup-copy",
        ]

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(arguments), EXIT_VERIFIED)
        self.assertTrue(json.loads(stdout.getvalue())["content_identity_verified"])

        (backup / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(arguments), EXIT_DIFFERENCES)
        self.assertFalse(json.loads(stdout.getvalue())["content_identity_verified"])

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(
                main(
                    [
                        "--expected-manifest-sha256",
                        "not-a-hash",
                        "--primary",
                        str(primary),
                        "--backup",
                        str(backup),
                        "--primary-ref",
                        "primary-vault-copy",
                        "--backup-ref",
                        "independent-backup-copy",
                    ]
                ),
                EXIT_INVALID,
            )
        invalid = json.loads(stderr.getvalue())
        self.assertEqual(invalid["assessment"], "invalid")
        self.assertFalse(invalid["artifact_restore_gate_passed"])

    def test_success_output_uses_opaque_refs_and_omits_local_paths(self) -> None:
        primary = self.make_bundle("primary-private-path")
        backup = self.make_bundle("backup-private-path")

        result = audit_copies(
            expected_manifest_sha256=self.manifest_hash(primary),
            primary_bundle=primary,
            backup_bundle=backup,
            primary_ref="primary-vault-copy",
            backup_ref="independent-backup-copy",
        )

        rendered = json.dumps(result)
        self.assertEqual(result["primary"]["copy_ref"], "primary-vault-copy")
        self.assertEqual(result["backup"]["copy_ref"], "independent-backup-copy")
        self.assertNotIn(str(primary), rendered)
        self.assertNotIn(str(backup), rendered)

    def test_copy_refs_must_be_distinct_credential_free_opaque_ids(self) -> None:
        primary = self.make_bundle("primary")
        backup = self.make_bundle("backup")
        expected = self.manifest_hash(primary)

        for primary_ref, backup_ref in (
            ("same-copy", "same-copy"),
            ("https://user:secret@example.invalid/copy", "backup-copy"),
            ("primary@private", "backup-copy"),
        ):
            with self.subTest(primary_ref=primary_ref, backup_ref=backup_ref):
                with self.assertRaises(CopyAuditError):
                    audit_copies(
                        expected_manifest_sha256=expected,
                        primary_bundle=primary,
                        backup_bundle=backup,
                        primary_ref=primary_ref,
                        backup_ref=backup_ref,
                    )

    def test_symlink_bundle_root_is_invalid(self) -> None:
        primary = self.make_bundle("primary")
        backup = self.make_bundle("backup")
        link = self.root / "primary-link"
        try:
            link.symlink_to(primary, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")

        with self.assertRaises(CopyAuditError):
            audit_copies(
                expected_manifest_sha256=self.manifest_hash(primary),
                primary_bundle=link,
                backup_bundle=backup,
            )

    def test_manifest_change_during_audit_is_invalid(self) -> None:
        primary = self.make_bundle("primary")
        backup = self.make_bundle("backup")
        expected = self.manifest_hash(primary)
        original = read_manifest_bytes(primary)

        with mock.patch(
            "compact_vio.copy_audit.read_manifest_bytes",
            side_effect=[original, original + b" ", original, original],
        ):
            with self.assertRaises(CopyAuditError):
                audit_copies(
                    expected_manifest_sha256=expected,
                    primary_bundle=primary,
                    backup_bundle=backup,
                )


if __name__ == "__main__":
    unittest.main()

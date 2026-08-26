from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from compact_vio.preflight import (
    EXIT_BLOCKED,
    EXIT_INVALID,
    FailureDomainRecordObservation,
    StorageObservation,
    assess_durability,
    main,
)


def _storage(path: str, *, device: int, free: int = 1_000_000) -> StorageObservation:
    return StorageObservation(
        supplied_path=path,
        resolved_path=path,
        exists=True,
        is_directory=True,
        has_symlink_component=False,
        writable_hint=True,
        filesystem_device=device,
        total_bytes=2_000_000,
        used_bytes=2_000_000 - free,
        free_bytes=free,
    )


def _record(path: str = "/failure-domain-record.md") -> FailureDomainRecordObservation:
    return FailureDomainRecordObservation(
        supplied_path=path,
        resolved_path=path,
        exists=True,
        is_regular_file=True,
        has_symlink_component=False,
        non_empty=True,
    )


class DurabilityPreflightTests(unittest.TestCase):
    def test_missing_inputs_are_blocked_and_never_pass_gate(self) -> None:
        result = assess_durability(
            vault=None,
            backup=None,
            required_bytes=None,
            reserve_bytes=None,
            failure_domain_record=None,
            observed_at="2026-08-26T00:00:00+00:00",
        )
        self.assertEqual(result["assessment"], "blocked")
        self.assertFalse(result["artifact_restore_gate_passed"])
        self.assertEqual(
            {blocker["code"] for blocker in result["blockers"]},
            {
                "vault_not_supplied",
                "backup_not_supplied",
                "required_capacity_not_supplied",
                "reserve_not_supplied",
                "failure_domain_record_not_supplied",
            },
        )

    def test_distinct_identifiers_only_satisfy_static_checks(self) -> None:
        result = assess_durability(
            vault=_storage("/vault", device=1),
            backup=_storage("/backup", device=2),
            required_bytes=100,
            reserve_bytes=200,
            failure_domain_record=_record(),
            observed_at="2026-08-26T00:00:00+00:00",
        )
        self.assertEqual(result["assessment"], "static_checks_satisfied")
        self.assertFalse(result["artifact_restore_gate_passed"])
        self.assertFalse(result["independent_failure_domains_verified"])
        self.assertFalse(result["outside_worker_locations_verified"])
        self.assertFalse(result["restore_verified"])
        self.assertEqual(result["blockers"], [])
        self.assertTrue(result["limitations"])

    def test_same_filesystem_is_blocked_despite_evidence_record(self) -> None:
        result = assess_durability(
            vault=_storage("/vault", device=7),
            backup=_storage("/backup", device=7),
            required_bytes=100,
            reserve_bytes=0,
            failure_domain_record=_record(),
            observed_at="2026-08-26T00:00:00+00:00",
        )
        self.assertIn(
            "same_filesystem_device",
            {blocker["code"] for blocker in result["blockers"]},
        )

    def test_nested_locations_are_blocked(self) -> None:
        result = assess_durability(
            vault=_storage("/storage", device=1),
            backup=_storage("/storage/backup", device=2),
            required_bytes=100,
            reserve_bytes=0,
            failure_domain_record=_record(),
            observed_at="2026-08-26T00:00:00+00:00",
        )
        self.assertIn(
            "locations_not_separate",
            {blocker["code"] for blocker in result["blockers"]},
        )

    def test_capacity_includes_explicit_reserve(self) -> None:
        result = assess_durability(
            vault=_storage("/vault", device=1, free=299),
            backup=_storage("/backup", device=2, free=300),
            required_bytes=100,
            reserve_bytes=200,
            failure_domain_record=_record(),
            observed_at="2026-08-26T00:00:00+00:00",
        )
        codes = {blocker["code"] for blocker in result["blockers"]}
        self.assertIn("vault_capacity_insufficient", codes)
        self.assertNotIn("backup_capacity_insufficient", codes)

    def test_negative_values_are_invalid(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = main(["--required-bytes", "-1", "--reserve-bytes", "0"])
        self.assertEqual(exit_code, EXIT_INVALID)
        self.assertEqual(json.loads(stderr.getvalue())["assessment"], "invalid")

    def test_cli_is_read_only_and_reports_same_device_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "vault"
            backup = root / "backup"
            vault.mkdir()
            backup.mkdir()
            marker = vault / "unchanged.txt"
            marker.write_text("unchanged", encoding="utf-8")
            record = root / "failure-domain-record.md"
            record.write_text("Caller-supplied record; review pending.\n", encoding="utf-8")
            before = sorted(str(item.relative_to(root)) for item in root.rglob("*"))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(
                    [
                        "--vault",
                        str(vault),
                        "--backup",
                        str(backup),
                        "--required-bytes",
                        "1",
                        "--reserve-bytes",
                        "0",
                        "--failure-domain-record",
                        str(record),
                    ]
                )

            after = sorted(str(item.relative_to(root)) for item in root.rglob("*"))
            self.assertEqual(exit_code, EXIT_BLOCKED)
            self.assertEqual(before, after)
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
            result = json.loads(stdout.getvalue())
            self.assertIn(
                "same_filesystem_device",
                {blocker["code"] for blocker in result["blockers"]},
            )

    def test_cli_rejects_symlinked_storage_location(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_vault = root / "real-vault"
            real_vault.mkdir()
            linked_vault = root / "linked-vault"
            linked_vault.symlink_to(real_vault, target_is_directory=True)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["--vault", str(linked_vault)])

            self.assertEqual(exit_code, EXIT_BLOCKED)
            result = json.loads(stdout.getvalue())
            self.assertIn(
                "vault_symlinked",
                {blocker["code"] for blocker in result["blockers"]},
            )

    @unittest.skipIf(os.name == "nt", "POSIX malformed-path behavior")
    def test_cli_reports_malformed_path_without_traceback(self) -> None:
        stdout = io.StringIO()
        malformed_path = str(Path(os.devnull) / "child")
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--vault", malformed_path])

        self.assertEqual(exit_code, EXIT_BLOCKED)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["assessment"], "blocked")
        self.assertTrue(result["vault"]["error"].startswith("filesystem inspection failed:"))

    def test_cli_reports_unresolvable_home_without_traceback(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main(["--vault", "~compact-vio-user-that-does-not-exist/vault"])

        self.assertEqual(exit_code, EXIT_BLOCKED)
        result = json.loads(stdout.getvalue())
        self.assertEqual(result["assessment"], "blocked")
        self.assertTrue(result["vault"]["error"].startswith("filesystem inspection failed:"))


if __name__ == "__main__":
    unittest.main()

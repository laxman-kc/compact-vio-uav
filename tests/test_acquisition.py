from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
import types
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import compact_vio.data.acquisition as acquisition_module
from compact_vio.data.acquisition import (
    AcquisitionError,
    load_transfer_authorization,
    main,
    run_authorized_transfer,
)
from compact_vio.data.archive import (
    ArchiveError,
    ArchiveVerification,
    AuthorizedArchiveAcquisition,
    TarInventory,
    TarMemberRecord,
    load_dataset_archive_candidate,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CANDIDATE_SOURCE = _PROJECT_ROOT / "configs/data/tumvi_room4_512_16_candidate_v1.json"
_NOW = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)
_REAL_ASSERT_RUNTIME_SOURCES = acquisition_module._assert_runtime_sources


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
    )


class _RepositoryFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "configs/data").mkdir(parents=True)
        (self.root / "src/compact_vio/data").mkdir(parents=True)
        (self.root / "governance/datasets/acquisitions").mkdir(parents=True)
        (self.root / ".gitignore").write_text("/data/\n", encoding="utf-8")
        (self.root / "configs/data/tumvi_room4_512_16_candidate_v1.json").write_bytes(
            _CANDIDATE_SOURCE.read_bytes()
        )
        for name in ("acquisition.py", "archive.py"):
            source = _PROJECT_ROOT / f"src/compact_vio/data/{name}"
            (self.root / f"src/compact_vio/data/{name}").write_bytes(source.read_bytes())
        _run_git(self.root, "init", "-q")
        _run_git(self.root, "config", "user.email", "tests@example.invalid")
        _run_git(self.root, "config", "user.name", "Acquisition Tests")
        _run_git(self.root, "add", ".")
        _run_git(self.root, "commit", "-q", "-m", "fixture foundation")
        self.authorization_path = (
            self.root / "governance/datasets/acquisitions/"
            "tumvi-room4-512-16-transfer-2026-08-28.authorization.json"
        )
        self.write_authorization()
        _run_git(self.root, "add", ".")
        _run_git(self.root, "commit", "-q", "-m", "authorize transfer")

    def close(self) -> None:
        self.temporary.cleanup()

    @property
    def authorization_relative(self) -> str:
        return self.authorization_path.relative_to(self.root).as_posix()

    @property
    def archive_path(self) -> Path:
        return self.root / "data/quarantine/tum-vi/room4-512-16/dataset-room4_512_16.tar"

    @property
    def claim_path(self) -> Path:
        return self.archive_path.parent / "transfer.claim.json"

    @property
    def inventory_path(self) -> Path:
        return self.archive_path.parent / "tar-inventory.json"

    @property
    def receipt_path(self) -> Path:
        return (
            self.root / "governance/datasets/acquisitions/"
            "tumvi-room4-512-16-transfer-2026-08-28.receipt.json"
        )

    def document(self) -> dict[str, object]:
        candidate_relative = "configs/data/tumvi_room4_512_16_candidate_v1.json"
        candidate_path = self.root / candidate_relative
        candidate = load_dataset_archive_candidate(candidate_path)
        identity = candidate.published_identity
        authorized = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires = (_NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        review = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        authorization_id = "tumvi-room4-512-16-transfer-2026-08-28"
        return {
            "archive_identity": {
                "allowed_redirect_origins": list(identity.allowed_redirect_origins),
                "allowed_redirect_urls": list(identity.allowed_redirect_urls),
                "archive_id": identity.archive_id,
                "filename": identity.filename,
                "md5": identity.md5,
                "sha256": None,
                "size_bytes": identity.size_bytes,
                "url": identity.url,
            },
            "authority_basis": {
                "captured_at": authorized,
                "identity_authentication": "not_independently_authenticated",
                "instruction_summary": "Continue the bounded production execution plan.",
                "kind": "active_workspace_user_instruction",
            },
            "authorization_id": authorization_id,
            "authorized_at": authorized,
            "candidate": {"path": candidate_relative, "sha256": _sha256(candidate_path)},
            "destination": {
                "archive_path": ("data/quarantine/tum-vi/room4-512-16/dataset-room4_512_16.tar"),
                "initial_archive_state": "absent",
                "initial_partial_state": "absent",
                "minimum_initial_free_bytes": (
                    identity.size_bytes + 2_147_483_648 + 268_435_456 + 1_048_576
                ),
                "minimum_post_transfer_free_bytes": 2_147_483_648,
                "must_be_git_ignored": True,
            },
            "execution": {
                "maximum_elapsed_seconds": 3_600,
                "maximum_paid_compute_cost_usd": 0,
                "requires_clean_worktree": True,
                "tool_files": [
                    {
                        "path": "src/compact_vio/data/acquisition.py",
                        "sha256": _sha256(self.root / "src/compact_vio/data/acquisition.py"),
                    },
                    {
                        "path": "src/compact_vio/data/archive.py",
                        "sha256": _sha256(self.root / "src/compact_vio/data/archive.py"),
                    },
                ],
            },
            "expires_at": expires,
            "inventory_limits": {
                "max_expanded_size_bytes": 274_877_906_944,
                "max_member_size_bytes": 8_589_934_592,
                "max_members": 250_000,
                "maximum_inventory_bytes": 268_435_456,
            },
            "max_executions": 1,
            "outputs": {
                "claim_path": ("data/quarantine/tum-vi/room4-512-16/transfer.claim.json"),
                "inventory_path": ("data/quarantine/tum-vi/room4-512-16/tar-inventory.json"),
                "receipt_path": (
                    f"governance/datasets/acquisitions/{authorization_id}.receipt.json"
                ),
            },
            "permitted_operations": [
                "write_claim",
                "download",
                "verify_size",
                "verify_md5",
                "compute_sha256",
                "inventory_tar_headers",
                "write_inventory",
                "write_receipt",
            ],
            "prohibited_operations": [
                "extract",
                "decode_images",
                "load_dataset_samples",
                "select_dataset",
                "train",
                "infer",
                "evaluate",
                "load_checkpoint",
                "delete_archive",
            ],
            "record_status": "approved",
            "record_type": "dataset_archive_transfer_authorization",
            "retention": {
                "deletion_authorized": False,
                "policy": "retain_in_quarantine_until_review",
                "review_at": review,
            },
            "schema_version": "1.0.0",
            "scope": "operational_byte_transfer_and_read_only_inventory_only",
            "scientific_authority": {
                "approves_evaluation": False,
                "approves_inference": False,
                "approves_publication": False,
                "approves_training": False,
                "assigns_membership": False,
                "selects_dataset": False,
            },
        }

    def write_authorization(self, document: dict[str, object] | None = None) -> None:
        self.authorization_path.write_text(
            json.dumps(document or self.document(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def commit_authorization(self, document: dict[str, object], message: str) -> None:
        self.write_authorization(document)
        _run_git(self.root, "add", ".")
        _run_git(self.root, "commit", "-q", "-m", message)


def _verification(
    fixture: _RepositoryFixture,
    authorization: AuthorizedArchiveAcquisition,
) -> ArchiveVerification:
    candidate = load_dataset_archive_candidate(
        fixture.root / "configs/data/tumvi_room4_512_16_candidate_v1.json"
    )
    identity = candidate.published_identity
    return ArchiveVerification(
        archive_id=identity.archive_id,
        filename=identity.filename,
        source_url=identity.url,
        size_bytes=identity.size_bytes,
        md5=identity.md5,
        sha256=hashlib.sha256(b"synthetic archive bytes").hexdigest(),
        resolved_url=identity.allowed_redirect_urls[-1],
        redirect_chain=identity.allowed_redirect_urls,
        authorization_record_id=authorization.authorization_record_id,
        authorization_record_sha256=authorization.authorization_record_sha256,
    )


def _inventory() -> TarInventory:
    members = (TarMemberRecord(path="dataset-room4/mav0/cam0/data.csv", kind="file", size_bytes=9),)
    return TarInventory(
        members=members,
        file_count=1,
        expanded_size_bytes=9,
        archive_sha256=hashlib.sha256(b"synthetic archive bytes").hexdigest(),
    )


class AcquisitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _RepositoryFixture()
        self.runtime_source_patch = mock.patch(
            "compact_vio.data.acquisition._assert_runtime_sources"
        )
        self.runtime_source_patch.start()
        self.addCleanup(self.runtime_source_patch.stop)

    def tearDown(self) -> None:
        self.fixture.close()

    def _runtime_patches(self) -> tuple[mock._patch, mock._patch, mock._patch]:
        times = iter((_NOW + timedelta(minutes=1),) * 4)

        def download(
            authorization: AuthorizedArchiveAcquisition,
            destination: Path,
            **_kwargs: object,
        ) -> ArchiveVerification:
            destination.write_bytes(b"synthetic archive bytes")
            return _verification(self.fixture, authorization)

        return (
            mock.patch("compact_vio.data.acquisition._utc_now", side_effect=lambda: next(times)),
            mock.patch(
                "compact_vio.data.acquisition._disk_usage",
                return_value=types.SimpleNamespace(free=10_000_000_000),
            ),
            mock.patch("compact_vio.data.acquisition.download_archive", side_effect=download),
        )

    def test_loads_exact_authorization_without_executing(self) -> None:
        result = load_transfer_authorization(
            self.fixture.authorization_path,
            repo_root=self.fixture.root,
        )
        self.assertEqual(result.authorization_id, "tumvi-room4-512-16-transfer-2026-08-28")
        self.assertEqual(result.candidate.dataset_id, "tum-vi")
        self.assertEqual(result.maximum_elapsed_seconds, 3_600)
        self.assertFalse(self.fixture.claim_path.exists())

    def test_runtime_sources_match_repository_checkout(self) -> None:
        _REAL_ASSERT_RUNTIME_SOURCES(_PROJECT_ROOT)

    def test_runtime_source_mismatch_rejects_before_claim_or_network(self) -> None:
        with (
            mock.patch(
                "compact_vio.data.acquisition._assert_runtime_sources",
                side_effect=AcquisitionError(
                    "executing acquisition module is not the authorized repository source"
                ),
            ),
            mock.patch(
                "compact_vio.data.acquisition._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            mock.patch("compact_vio.data.acquisition.download_archive") as download,
            self.assertRaisesRegex(AcquisitionError, "authorized repository source"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        download.assert_not_called()
        self.assertFalse(self.fixture.claim_path.exists())

    def test_rejects_unknown_fields_bool_as_int_and_relaxed_scope(self) -> None:
        cases = (
            ("unknown", lambda item: item.__setitem__("extra", 1)),
            ("max_executions", lambda item: item.__setitem__("max_executions", True)),
            ("scope", lambda item: item.__setitem__("scope", "download_and_extract")),
        )
        for label, mutate in cases:
            with self.subTest(label=label):
                document = self.fixture.document()
                mutate(document)
                self.fixture.write_authorization(document)
                with self.assertRaises(AcquisitionError):
                    load_transfer_authorization(
                        self.fixture.authorization_path,
                        repo_root=self.fixture.root,
                    )

    def test_success_writes_claim_inventory_then_tracked_receipt(self) -> None:
        candidate_before = (
            self.fixture.root / "configs/data/tumvi_room4_512_16_candidate_v1.json"
        ).read_bytes()
        now_patch, disk_patch, download_patch = self._runtime_patches()
        with (
            now_patch,
            disk_patch,
            download_patch as download,
            mock.patch(
                "compact_vio.data.acquisition.inventory_tar", return_value=_inventory()
            ) as inventory,
        ):
            result = run_authorized_transfer(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        download.assert_called_once()
        inventory.assert_called_once()
        self.assertEqual(
            result.archive_sha256,
            hashlib.sha256(b"synthetic archive bytes").hexdigest(),
        )
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertTrue(self.fixture.inventory_path.is_file())
        self.assertTrue(self.fixture.receipt_path.is_file())
        receipt = json.loads(self.fixture.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(receipt["scientific_authority"], "none")
        self.assertIn("extract", receipt["operations_not_performed"])
        self.assertEqual(
            candidate_before,
            (self.fixture.root / "configs/data/tumvi_room4_512_16_candidate_v1.json").read_bytes(),
        )

    def test_expired_authorization_rejects_before_claim_or_network(self) -> None:
        with (
            mock.patch(
                "compact_vio.data.acquisition._utc_now",
                return_value=_NOW + timedelta(days=2),
            ),
            mock.patch("compact_vio.data.acquisition.download_archive") as download,
            self.assertRaisesRegex(AcquisitionError, "not active"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        download.assert_not_called()
        self.assertFalse(self.fixture.claim_path.exists())

    def test_dirty_authorization_is_rejected_before_claim(self) -> None:
        document = self.fixture.document()
        document["authority_basis"]["instruction_summary"] = "Modified after review."
        self.fixture.write_authorization(document)
        with (
            mock.patch(
                "compact_vio.data.acquisition._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            mock.patch("compact_vio.data.acquisition.download_archive") as download,
            self.assertRaisesRegex(AcquisitionError, "clean"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        download.assert_not_called()
        self.assertFalse(self.fixture.claim_path.exists())

    def test_insufficient_space_rejects_before_claim(self) -> None:
        with (
            mock.patch(
                "compact_vio.data.acquisition._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            mock.patch(
                "compact_vio.data.acquisition._disk_usage",
                return_value=types.SimpleNamespace(free=1),
            ),
            mock.patch("compact_vio.data.acquisition.download_archive") as download,
            self.assertRaisesRegex(AcquisitionError, "insufficient free space"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        download.assert_not_called()
        self.assertFalse(self.fixture.claim_path.exists())

    def test_symlink_ancestor_is_rejected_before_claim(self) -> None:
        with tempfile.TemporaryDirectory() as outside_directory:
            outside = Path(outside_directory)
            (self.fixture.root / "data").mkdir()
            os.symlink(outside, self.fixture.root / "data/quarantine")
            with (
                mock.patch(
                    "compact_vio.data.acquisition._utc_now",
                    return_value=_NOW + timedelta(minutes=1),
                ),
                mock.patch("compact_vio.data.acquisition.download_archive") as download,
                self.assertRaisesRegex(AcquisitionError, "real directory"),
            ):
                run_authorized_transfer(
                    self.fixture.authorization_relative,
                    repo_root=self.fixture.root,
                )
            download.assert_not_called()
            self.assertFalse((outside / "quarantine").exists())

    def test_failed_download_consumes_claim_and_prevents_retry(self) -> None:
        now_patch, disk_patch, _download_patch = self._runtime_patches()
        with (
            now_patch,
            disk_patch,
            mock.patch(
                "compact_vio.data.acquisition.download_archive",
                side_effect=ArchiveError("network interrupted"),
            ) as download,
            self.assertRaisesRegex(AcquisitionError, "network interrupted"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertFalse(self.fixture.receipt_path.exists())
        with (
            mock.patch(
                "compact_vio.data.acquisition._utc_now",
                return_value=_NOW + timedelta(minutes=2),
            ),
            self.assertRaisesRegex(AcquisitionError, "must be absent"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        self.assertEqual(download.call_count, 1)

    def test_inventory_failure_leaves_claim_and_no_receipt(self) -> None:
        now_patch, disk_patch, download_patch = self._runtime_patches()
        with (
            now_patch,
            disk_patch,
            download_patch,
            mock.patch(
                "compact_vio.data.acquisition.inventory_tar",
                side_effect=ArchiveError("invalid TAR"),
            ),
            self.assertRaisesRegex(AcquisitionError, "invalid TAR"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.inventory_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_expiry_during_work_prevents_success_receipt(self) -> None:
        times = iter(
            (
                _NOW + timedelta(minutes=1),
                _NOW + timedelta(minutes=1),
                _NOW + timedelta(days=2),
            )
        )

        def download(
            authorization: AuthorizedArchiveAcquisition,
            destination: Path,
            **_kwargs: object,
        ) -> ArchiveVerification:
            destination.write_bytes(b"archive")
            return _verification(self.fixture, authorization)

        with (
            mock.patch("compact_vio.data.acquisition._utc_now", side_effect=lambda: next(times)),
            mock.patch(
                "compact_vio.data.acquisition._disk_usage",
                return_value=types.SimpleNamespace(free=10_000_000_000),
            ),
            mock.patch("compact_vio.data.acquisition.download_archive", side_effect=download),
            mock.patch("compact_vio.data.acquisition.inventory_tar", return_value=_inventory()),
            self.assertRaisesRegex(AcquisitionError, "expire"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertTrue(self.fixture.inventory_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_tool_hash_mismatch_rejects_before_claim(self) -> None:
        document = self.fixture.document()
        document["execution"]["tool_files"][0]["sha256"] = "0" * 64
        self.fixture.write_authorization(document)
        _run_git(self.fixture.root, "add", ".")
        _run_git(self.fixture.root, "commit", "-q", "-m", "bad tool identity")
        with (
            mock.patch(
                "compact_vio.data.acquisition._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            self.assertRaisesRegex(AcquisitionError, "SHA-256 mismatch"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative, repo_root=self.fixture.root
            )
        self.assertFalse(self.fixture.claim_path.exists())

    def test_atomic_publication_cleans_staged_file_after_write_error(self) -> None:
        target = self.fixture.root / "atomic-evidence.json"
        with (
            mock.patch(
                "compact_vio.data.acquisition.os.write",
                side_effect=OSError("injected write failure"),
            ),
            self.assertRaisesRegex(OSError, "injected write failure"),
        ):
            acquisition_module._write_new_atomic(target, b"evidence\n")
        self.assertFalse(target.exists())
        self.assertEqual(list(self.fixture.root.glob(".atomic-evidence.json.staged-*")), [])

    def test_claim_mutation_prevents_receipt_publication(self) -> None:
        now_patch, disk_patch, download_patch = self._runtime_patches()
        real_write = acquisition_module._write_new_atomic

        def write_and_mutate(path: Path, payload: bytes) -> str:
            result = real_write(path, payload)
            if path.name == "tar-inventory.json":
                self.fixture.claim_path.write_text("mutated\n", encoding="utf-8")
            return result

        with (
            now_patch,
            disk_patch,
            download_patch,
            mock.patch("compact_vio.data.acquisition.inventory_tar", return_value=_inventory()),
            mock.patch(
                "compact_vio.data.acquisition._write_new_atomic",
                side_effect=write_and_mutate,
            ),
            self.assertRaisesRegex(AcquisitionError, "claim bytes changed"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_archive_mutation_after_inventory_prevents_receipt(self) -> None:
        now_patch, disk_patch, download_patch = self._runtime_patches()

        def inventory_and_mutate(*_args: object, **_kwargs: object) -> TarInventory:
            result = _inventory()
            self.fixture.archive_path.write_bytes(b"mutated archive")
            return result

        with (
            now_patch,
            disk_patch,
            download_patch,
            mock.patch(
                "compact_vio.data.acquisition.inventory_tar",
                side_effect=inventory_and_mutate,
            ),
            self.assertRaisesRegex(AcquisitionError, "archive SHA-256 changed"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_hard_elapsed_deadline_interrupts_download(self) -> None:
        document = self.fixture.document()
        document["execution"]["maximum_elapsed_seconds"] = 1
        self.fixture.commit_authorization(document, "one-second deadline")

        def slow_download(*_args: object, **_kwargs: object) -> ArchiveVerification:
            time.sleep(2)
            raise AssertionError("hard deadline did not interrupt the blocking operation")

        with (
            mock.patch(
                "compact_vio.data.acquisition._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            mock.patch(
                "compact_vio.data.acquisition._disk_usage",
                return_value=types.SimpleNamespace(free=10_000_000_000),
            ),
            mock.patch(
                "compact_vio.data.acquisition.download_archive",
                side_effect=slow_download,
            ),
            self.assertRaisesRegex(AcquisitionError, "maximum elapsed"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_inventory_hard_cap_rejects_authorization(self) -> None:
        document = self.fixture.document()
        document["inventory_limits"]["maximum_inventory_bytes"] = 268_435_457
        self.fixture.write_authorization(document)
        with self.assertRaisesRegex(AcquisitionError, "maximum_inventory_bytes"):
            load_transfer_authorization(
                self.fixture.authorization_path,
                repo_root=self.fixture.root,
            )

    def test_archive_result_authorization_mismatch_prevents_receipt(self) -> None:
        now_patch, disk_patch, _download_patch = self._runtime_patches()

        def download(
            authorization: AuthorizedArchiveAcquisition,
            destination: Path,
            **_kwargs: object,
        ) -> ArchiveVerification:
            destination.write_bytes(b"synthetic archive bytes")
            return replace(
                _verification(self.fixture, authorization),
                authorization_record_id="wrong-authorization",
            )

        with (
            now_patch,
            disk_patch,
            mock.patch("compact_vio.data.acquisition.download_archive", side_effect=download),
            self.assertRaisesRegex(AcquisitionError, "authorization ID mismatch"),
        ):
            run_authorized_transfer(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_cli_parse_failure_is_one_json_object(self) -> None:
        with mock.patch("sys.stderr") as stderr:
            result = main([])
        self.assertEqual(result, 2)
        payload = json.loads(stderr.write.call_args_list[0].args[0])
        self.assertEqual(payload["event"], "archive_acquisition_failed")

    def test_cli_unexpected_failure_is_structured_json(self) -> None:
        with (
            mock.patch(
                "compact_vio.data.acquisition.run_authorized_transfer",
                side_effect=TypeError("unexpected test failure"),
            ),
            mock.patch("sys.stderr") as stderr,
        ):
            result = main(["--authorization", "authorization.json"])
        self.assertEqual(result, 2)
        payload = json.loads(stderr.write.call_args_list[0].args[0])
        self.assertEqual(payload["error_type"], "TypeError")


if __name__ == "__main__":
    unittest.main()

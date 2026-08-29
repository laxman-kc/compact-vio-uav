from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import compact_vio.data.archive_audit as audit_module
from compact_vio.data.acquisition import AcquisitionError
from compact_vio.data.archive_audit import (
    load_structural_audit_authorization,
    main,
    run_authorized_structural_audit,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CHECKED_AUTHORIZATION = (
    _PROJECT_ROOT / "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-structural-audit-2026-08-29.authorization.json"
)
_NOW = datetime(2026, 8, 29, 22, 0, 0, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


def _write_test_tar(path: Path) -> None:
    with tarfile.open(path, "w") as archive:
        directory = tarfile.TarInfo("dataset-room4_512_16/")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        content = b"camera\n"
        camera = tarfile.TarInfo("dataset-room4_512_16/mav0/cam0/data.csv")
        camera.size = len(content)
        archive.addfile(camera, io.BytesIO(content))
        link = tarfile.TarInfo("dataset-room4_512_16/dso/cam1/images")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../cam0/images"
        archive.addfile(link)


class _AuditRepositoryFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "configs/data").mkdir(parents=True)
        (self.root / "src/compact_vio/data").mkdir(parents=True)
        (self.root / "governance/datasets/acquisitions").mkdir(parents=True)
        self.archive_path = (
            self.root / "data/quarantine/tum-vi/room4-512-16/dataset-room4_512_16.tar"
        )
        self.archive_path.parent.mkdir(parents=True)
        _write_test_tar(self.archive_path)
        self.archive_before = self.archive_path.read_bytes()
        self.archive_sha256 = _sha256(self.archive_path)
        self.archive_md5 = hashlib.md5(self.archive_before).hexdigest()
        (self.root / ".gitignore").write_text("/data/\n", encoding="utf-8")

        candidate = json.loads(
            (_PROJECT_ROOT / "configs/data/tumvi_room4_512_16_candidate_v1.json").read_text(
                encoding="utf-8"
            )
        )
        candidate["candidate_unit"]["http_observations"]["observed_content_length_bytes"] = len(
            self.archive_before
        )
        candidate["candidate_unit"]["md5_sidecar"]["published_md5"] = self.archive_md5
        candidate["candidate_unit"]["md5_sidecar"]["exact_body"] = (
            f"{self.archive_md5}  dataset-room4_512_16.tar\n"
        )
        self.candidate_relative = "configs/data/tumvi_room4_512_16_candidate_v1.json"
        self.candidate_path = self.root / self.candidate_relative
        self.candidate_path.write_text(
            json.dumps(candidate, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.failure_relative = "governance/datasets/acquisitions/synthetic-transfer.failure.json"
        self.failure_path = self.root / self.failure_relative
        self.failure_path.write_text(
            json.dumps(
                {
                    "archive_sha256": self.archive_sha256,
                    "outcome": "failed",
                    "record_type": "synthetic_source_failure",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        for name in ("archive_audit.py", "acquisition.py", "archive.py"):
            source = _PROJECT_ROOT / f"src/compact_vio/data/{name}"
            (self.root / f"src/compact_vio/data/{name}").write_bytes(source.read_bytes())

        _run_git(self.root, "init", "-q")
        _run_git(self.root, "config", "user.email", "tests@example.invalid")
        _run_git(self.root, "config", "user.name", "Audit Tests")
        _run_git(self.root, "add", ".")
        _run_git(self.root, "commit", "-q", "-m", "fixture foundation")

        self.authorization_id = "tumvi-room4-structural-audit-synthetic"
        self.authorization_relative = (
            f"governance/datasets/acquisitions/{self.authorization_id}.authorization.json"
        )
        self.authorization_path = self.root / self.authorization_relative
        self.claim_path = self.archive_path.parent / "structural-audit.claim.json"
        self.audit_path = self.archive_path.parent / "tar-structural-audit.json"
        self.receipt_path = (
            self.root / f"governance/datasets/acquisitions/{self.authorization_id}.receipt.json"
        )
        self.write_authorization()
        _run_git(self.root, "add", ".")
        _run_git(self.root, "commit", "-q", "-m", "authorize structural audit")

    def close(self) -> None:
        self.temporary.cleanup()

    def document(self) -> dict[str, object]:
        authorized = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires = (_NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        review = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        request_url = (
            "https://cdn3.vision.in.tum.de/tumvi/exported/euroc/512_16/dataset-room4_512_16.tar"
        )
        redirect_url = (
            "https://cdn2.vision.in.tum.de/tumvi/exported/euroc/512_16/dataset-room4_512_16.tar"
        )
        return {
            "archive_identity": {
                "allowed_redirect_origins": ["https://cdn2.vision.in.tum.de"],
                "allowed_redirect_urls": [redirect_url],
                "archive_id": "tum-vi-room4",
                "filename": "dataset-room4_512_16.tar",
                "md5": self.archive_md5,
                "sha256": self.archive_sha256,
                "size_bytes": len(self.archive_before),
                "url": request_url,
            },
            "archive_path": ("data/quarantine/tum-vi/room4-512-16/dataset-room4_512_16.tar"),
            "audit_limits": {
                "max_expanded_size_bytes": 274_877_906_944,
                "max_member_size_bytes": 8_589_934_592,
                "max_members": 250_000,
                "maximum_audit_bytes": 268_435_456,
            },
            "authority_basis": {
                "captured_at": authorized,
                "identity_authentication": "not_independently_authenticated",
                "instruction_summary": "Audit retained synthetic archive headers only.",
                "kind": "active_workspace_user_instruction",
            },
            "authorization_id": self.authorization_id,
            "authorized_at": authorized,
            "candidate": {
                "path": self.candidate_relative,
                "sha256": _sha256(self.candidate_path),
            },
            "execution": {
                "maximum_elapsed_seconds": 600,
                "maximum_paid_compute_cost_usd": 0,
                "minimum_free_bytes": 2_416_967_680,
                "requires_clean_worktree": True,
                "tool_files": [
                    {
                        "path": f"src/compact_vio/data/{name}",
                        "sha256": _sha256(self.root / f"src/compact_vio/data/{name}"),
                    }
                    for name in ("archive_audit.py", "acquisition.py", "archive.py")
                ],
            },
            "expires_at": expires,
            "max_executions": 1,
            "outputs": {
                "claim_path": ("data/quarantine/tum-vi/room4-512-16/structural-audit.claim.json"),
                "audit_path": ("data/quarantine/tum-vi/room4-512-16/tar-structural-audit.json"),
                "receipt_path": (
                    f"governance/datasets/acquisitions/{self.authorization_id}.receipt.json"
                ),
            },
            "permitted_operations": [
                "write_claim",
                "verify_size",
                "verify_md5",
                "verify_sha256",
                "audit_tar_headers",
                "write_audit",
                "write_receipt",
            ],
            "prohibited_operations": [
                "download",
                "modify_archive",
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
            "record_type": "dataset_archive_structural_audit_authorization",
            "retention": {
                "deletion_authorized": False,
                "policy": "retain_audit_evidence_until_review",
                "review_at": review,
            },
            "schema_version": "1.0.0",
            "scope": "retained_archive_read_only_structural_audit_only",
            "scientific_authority": {
                "approves_evaluation": False,
                "approves_extraction": False,
                "approves_inference": False,
                "approves_publication": False,
                "approves_training": False,
                "assigns_membership": False,
                "selects_dataset": False,
            },
            "source_failure": {
                "path": self.failure_relative,
                "sha256": _sha256(self.failure_path),
            },
        }

    def write_authorization(self, document: dict[str, object] | None = None) -> None:
        self.authorization_path.write_text(
            json.dumps(document or self.document(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class ArchiveAuditControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _AuditRepositoryFixture()
        self.runtime_patch = mock.patch("compact_vio.data.archive_audit._assert_runtime_sources")
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)

    def tearDown(self) -> None:
        self.fixture.close()

    def _runtime_patches(self) -> tuple[mock._patch, mock._patch]:
        times = iter((_NOW + timedelta(minutes=1),) * 5)
        return (
            mock.patch(
                "compact_vio.data.archive_audit._utc_now",
                side_effect=lambda: next(times),
            ),
            mock.patch(
                "compact_vio.data.archive_audit._disk_usage",
                return_value=types.SimpleNamespace(free=10_000_000_000),
            ),
        )

    def test_checked_authorization_binds_frozen_real_inputs_without_execution(self) -> None:
        result = load_structural_audit_authorization(
            _CHECKED_AUTHORIZATION,
            repo_root=_PROJECT_ROOT,
        )
        self.assertEqual(
            result.authorization_id,
            "tumvi-room4-512-16-structural-audit-2026-08-29",
        )
        self.assertEqual(
            result.authorization_sha256,
            "cff468e9fd2702fb9c62176067e23db6a0d32b66502d5e92e37a42ea8324fbb8",
        )
        self.assertEqual(
            result.archive_identity.sha256,
            "2c3633407693988cf24faef5f874cba08bbc3c2d2ec1168c86b6da55ae9f2e68",
        )
        self.assertEqual(_sha256(_PROJECT_ROOT / result.candidate_path), result.candidate_sha256)
        self.assertEqual(
            _sha256(_PROJECT_ROOT / result.source_failure_path),
            result.source_failure_sha256,
        )

    def test_loads_exact_authorization_without_archive_access(self) -> None:
        before = self.fixture.archive_path.stat()
        result = load_structural_audit_authorization(
            self.fixture.authorization_relative,
            repo_root=self.fixture.root,
        )
        after = self.fixture.archive_path.stat()
        self.assertEqual(result.authorization_id, self.fixture.authorization_id)
        self.assertEqual(result.archive_identity.sha256, self.fixture.archive_sha256)
        self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
        self.assertFalse(self.fixture.claim_path.exists())

    def test_success_records_inert_symlink_and_never_extracts_or_modifies_archive(self) -> None:
        now_patch, disk_patch = self._runtime_patches()
        with (
            now_patch,
            disk_patch,
            mock.patch.object(
                tarfile.TarFile,
                "extractall",
                side_effect=AssertionError("extraction must not run"),
            ) as extractall,
        ):
            result = run_authorized_structural_audit(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        extractall.assert_not_called()
        self.assertEqual(self.fixture.archive_path.read_bytes(), self.fixture.archive_before)
        self.assertTrue(self.fixture.claim_path.is_file())
        self.assertTrue(self.fixture.audit_path.is_file())
        self.assertTrue(self.fixture.receipt_path.is_file())
        audit = json.loads(self.fixture.audit_path.read_text(encoding="utf-8"))
        receipt = json.loads(self.fixture.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(result.audit_sha256, _sha256(self.fixture.audit_path))
        self.assertEqual(audit["non_regular_member_count"], 1)
        self.assertFalse(audit["strict_extraction_compatible"])
        self.assertEqual(audit["members"][2]["kind"], "symlink")
        self.assertEqual(audit["members"][2]["link_target"], "../../cam0/images")
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(receipt["scientific_authority"], "none")
        self.assertIn("extract", receipt["operations_not_performed"])

    def test_schema_and_frozen_operation_lists_fail_closed(self) -> None:
        for label, mutate in (
            ("extra", lambda item: item.__setitem__("extra", 1)),
            ("max_executions", lambda item: item.__setitem__("max_executions", True)),
            (
                "operation",
                lambda item: item["permitted_operations"].append("extract"),
            ),
        ):
            with self.subTest(label=label):
                document = self.fixture.document()
                mutate(document)
                self.fixture.write_authorization(document)
                with self.assertRaises(AcquisitionError):
                    load_structural_audit_authorization(
                        self.fixture.authorization_path,
                        repo_root=self.fixture.root,
                    )

    def test_runtime_mismatch_rejects_before_claim(self) -> None:
        with (
            mock.patch(
                "compact_vio.data.archive_audit._assert_runtime_sources",
                side_effect=AcquisitionError("modules are not authorized sources"),
            ),
            mock.patch(
                "compact_vio.data.archive_audit._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            self.assertRaisesRegex(AcquisitionError, "authorized sources"),
        ):
            run_authorized_structural_audit(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.claim_path.exists())

    def test_wrong_received_sha_consumes_claim_without_audit_or_receipt(self) -> None:
        document = self.fixture.document()
        document["archive_identity"]["sha256"] = "0" * 64
        self.fixture.write_authorization(document)
        _run_git(self.fixture.root, "add", ".")
        _run_git(self.fixture.root, "commit", "-q", "-m", "wrong received SHA")
        now_patch, disk_patch = self._runtime_patches()
        with (
            now_patch,
            disk_patch,
            self.assertRaisesRegex(AcquisitionError, "archive SHA-256 mismatch"),
        ):
            run_authorized_structural_audit(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.audit_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_archive_mutation_after_audit_prevents_receipt(self) -> None:
        now_patch, disk_patch = self._runtime_patches()
        real_write = audit_module._write_new_atomic

        def write_and_mutate(path: Path, payload: bytes) -> str:
            result = real_write(path, payload)
            if path.name == "tar-structural-audit.json":
                self.fixture.archive_path.write_bytes(b"mutated")
            return result

        with (
            now_patch,
            disk_patch,
            mock.patch(
                "compact_vio.data.archive_audit._write_new_atomic",
                side_effect=write_and_mutate,
            ),
            self.assertRaisesRegex(AcquisitionError, "archive size mismatch"),
        ):
            run_authorized_structural_audit(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertTrue(self.fixture.audit_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_existing_output_rejects_before_new_claim(self) -> None:
        self.fixture.audit_path.write_text("existing\n", encoding="utf-8")
        with (
            mock.patch(
                "compact_vio.data.archive_audit._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            self.assertRaisesRegex(AcquisitionError, "must be absent"),
        ):
            run_authorized_structural_audit(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.claim_path.exists())

    def test_cli_failures_are_one_structured_json_object(self) -> None:
        with mock.patch("sys.stderr") as stderr:
            result = main([])
        self.assertEqual(result, 2)
        payload = json.loads(stderr.write.call_args_list[0].args[0])
        self.assertEqual(payload["error_code"], "archive_structural_audit_failed")


if __name__ == "__main__":
    unittest.main()

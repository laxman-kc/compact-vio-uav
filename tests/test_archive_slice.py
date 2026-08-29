from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import subprocess
import tarfile
import tempfile
import types
import unittest
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import compact_vio.data.archive_slice as slice_module
from compact_vio.data.acquisition import AcquisitionError
from compact_vio.data.archive import ArchiveError, ExtractedFileReceipt, audit_tar_structure
from compact_vio.data.archive_slice import (
    load_regular_slice_allowlist,
    load_regular_slice_authorization,
    main,
    run_authorized_regular_slice,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CHECKED_ALLOWLIST = _PROJECT_ROOT / "configs/data/tumvi_room4_512_16_compatibility_slice_v1.json"
_CHECKED_AUTHORIZATION = (
    _PROJECT_ROOT / "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-compatibility-slice-2026-08-29.authorization.json"
)
_CHECKED_RECEIPT = (
    _PROJECT_ROOT / "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json"
)
_NOW = datetime(2026, 8, 29, 23, 0, 0, tzinfo=timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_git(root: Path, *arguments: str) -> None:
    subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)


def _write_tar(path: Path) -> None:
    with tarfile.open(path, "w") as archive:
        directory = tarfile.TarInfo("dataset/")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        for name, content in (
            ("dataset/mav0/cam0/data.csv", b"camera-index"),
            ("dataset/mav0/cam1/data.csv", b"camera1-index"),
            ("dataset/mav0/imu0/data.csv", b"imu-index"),
            ("dataset/mav0/mocap0/data.csv", b"mocap-index"),
            ("dataset/mav0/cam0/data/first.png", b"pixels"),
            ("dataset/mav0/cam1/data/first.png", b"pixels1"),
            ("dataset/mav0/cam0/data/second.png", b"pixels-2"),
            ("dataset/mav0/cam1/data/second.png", b"pixels--2"),
            ("dataset/mav0/cam0/data/third.png", b"third-cam0"),
            ("dataset/mav0/cam1/data/third.png", b"third-cam1"),
            ("dataset/mav0/ignored.txt", b"ignored"),
        ):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
        link = tarfile.TarInfo("dataset/dso/cam1/images")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../cam0/images"
        archive.addfile(link)


class _SliceRepositoryFixture:
    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for relative in (
            "src/compact_vio/data",
            "configs/data",
            "governance/datasets/acquisitions",
            "data/quarantine/tum-vi/room4-512-16",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        (self.root / ".gitignore").write_text("/data/\n", encoding="utf-8")
        for name in ("archive_slice.py", "acquisition.py", "archive.py"):
            (self.root / f"src/compact_vio/data/{name}").write_text(
                f"# synthetic {name}\n", encoding="utf-8"
            )

        self.archive_relative = "data/quarantine/tum-vi/room4-512-16/dataset-room4.tar"
        self.archive_path = self.root / self.archive_relative
        _write_tar(self.archive_path)
        self.archive_before = self.archive_path.read_bytes()
        self.archive_sha256 = _sha256(self.archive_path)
        self.archive_md5 = hashlib.md5(self.archive_before).hexdigest()

        self.candidate_relative = "configs/data/synthetic_candidate.json"
        self.candidate_path = self.root / self.candidate_relative
        self.candidate_path.write_text('{"candidate":"synthetic"}\n', encoding="utf-8")
        self.transfer_authorization_relative = (
            "governance/datasets/acquisitions/synthetic-transfer.authorization.json"
        )
        self.transfer_authorization_path = self.root / self.transfer_authorization_relative
        self.transfer_authorization_path.write_text(
            '{"authorization":"synthetic-transfer"}\n', encoding="utf-8"
        )
        self.audit_authorization_relative = (
            "governance/datasets/acquisitions/synthetic-audit.authorization.json"
        )
        self.audit_authorization_path = self.root / self.audit_authorization_relative
        self.audit_authorization_path.write_text(
            '{"authorization":"synthetic-audit"}\n', encoding="utf-8"
        )

        audit = audit_tar_structure(
            self.archive_path,
            expected_sha256=self.archive_sha256,
        )
        self.audit_relative = "data/quarantine/tum-vi/room4-512-16/tar-structural-audit.json"
        self.audit_path = self.root / self.audit_relative
        audit_document = {
            "archive_sha256": audit.archive_sha256,
            "expanded_regular_size_bytes": audit.expanded_regular_size_bytes,
            "member_count": audit.member_count,
            "members": [asdict(item) for item in audit.members],
            "non_regular_member_count": audit.non_regular_member_count,
            "policy_id": "inert-tar-header-metadata-no-follow-no-extract/v1",
            "record_type": "dataset_archive_structural_audit",
            "regular_file_count": audit.regular_file_count,
            "schema_version": "1.0.0",
            "strict_extraction_compatible": audit.strict_extraction_compatible,
        }
        self.audit_path.write_text(
            json.dumps(audit_document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        self.transfer_claim_relative = "data/quarantine/tum-vi/room4-512-16/transfer.claim.json"
        self.transfer_claim_path = self.root / self.transfer_claim_relative
        self.transfer_claim_path.write_text(
            json.dumps(
                {
                    "authorization_sha256": _sha256(self.transfer_authorization_path),
                    "candidate_sha256": _sha256(self.candidate_path),
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.audit_claim_relative = (
            "data/quarantine/tum-vi/room4-512-16/structural-audit.claim.json"
        )
        self.audit_claim_path = self.root / self.audit_claim_relative
        self.audit_claim_path.write_text('{"claim":"audit"}\n', encoding="utf-8")

        self.transfer_failure_relative = (
            "governance/datasets/acquisitions/synthetic-transfer.failure.json"
        )
        self.transfer_failure_path = self.root / self.transfer_failure_relative
        self.transfer_failure_path.write_text(
            json.dumps(
                {
                    "archive": {
                        "path": self.archive_relative,
                        "sha256": self.archive_sha256,
                    },
                    "authorization": {
                        "path": self.transfer_authorization_relative,
                        "sha256": _sha256(self.transfer_authorization_path),
                    },
                    "claim": {
                        "path": self.transfer_claim_relative,
                        "sha256": _sha256(self.transfer_claim_path),
                    },
                    "outcome": "failed",
                    "scientific_authority": "none",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        self.audit_receipt_relative = (
            "governance/datasets/acquisitions/synthetic-audit.receipt.json"
        )
        self.audit_receipt_path = self.root / self.audit_receipt_relative
        self.audit_receipt_path.write_text(
            json.dumps(
                {
                    "authorization": {
                        "path": self.audit_authorization_relative,
                        "sha256": _sha256(self.audit_authorization_path),
                    },
                    "archive": {
                        "path": self.archive_relative,
                        "sha256": self.archive_sha256,
                    },
                    "audit": {
                        "path": self.audit_relative,
                        "sha256": _sha256(self.audit_path),
                    },
                    "claim": {
                        "path": self.audit_claim_relative,
                        "sha256": _sha256(self.audit_claim_path),
                    },
                    "outcome": "completed",
                    "scientific_authority": "none",
                    "source_failure": {
                        "path": self.transfer_failure_relative,
                        "sha256": _sha256(self.transfer_failure_path),
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        self.allowlist_id = "synthetic-tumvi-format-slice"
        self.allowlist_relative = "configs/data/synthetic_tumvi_format_slice.json"
        self.allowlist_path = self.root / self.allowlist_relative
        self.allowlist_path.write_text(
            json.dumps(self.allowlist_document(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        _run_git(self.root, "init", "-q")
        _run_git(self.root, "config", "user.email", "slice-tests@example.invalid")
        _run_git(self.root, "config", "user.name", "Slice Tests")
        _run_git(self.root, "add", ".")
        _run_git(self.root, "commit", "-q", "-m", "fixture foundation")

        self.authorization_id = "synthetic-tumvi-regular-slice"
        self.authorization_relative = (
            f"governance/datasets/acquisitions/{self.authorization_id}.authorization.json"
        )
        self.authorization_path = self.root / self.authorization_relative
        self.claim_relative = "data/quarantine/tum-vi/room4-512-16/regular-slice.claim.json"
        self.claim_path = self.root / self.claim_relative
        self.destination_relative = f"data/quarantine/tum-vi/room4-512-16/{self.allowlist_id}"
        self.destination_path = self.root / self.destination_relative
        self.receipt_relative = (
            f"governance/datasets/acquisitions/{self.authorization_id}.receipt.json"
        )
        self.receipt_path = self.root / self.receipt_relative
        self.write_authorization()
        _run_git(self.root, "add", ".")
        _run_git(self.root, "commit", "-q", "-m", "authorize regular slice")

    def close(self) -> None:
        self.temporary.cleanup()

    def allowlist_document(self) -> dict[str, object]:
        selected = [
            {"path": "dataset/mav0/cam0/data.csv", "size_bytes": 12},
            {"path": "dataset/mav0/cam1/data.csv", "size_bytes": 13},
            {"path": "dataset/mav0/imu0/data.csv", "size_bytes": 9},
            {"path": "dataset/mav0/mocap0/data.csv", "size_bytes": 11},
            {"path": "dataset/mav0/cam0/data/first.png", "size_bytes": 6},
            {"path": "dataset/mav0/cam1/data/first.png", "size_bytes": 7},
            {"path": "dataset/mav0/cam0/data/second.png", "size_bytes": 8},
            {"path": "dataset/mav0/cam1/data/second.png", "size_bytes": 9},
        ]
        return {
            "allowed_root": "dataset/mav0",
            "allowlist_id": self.allowlist_id,
            "archive": {"path": self.archive_relative, "sha256": self.archive_sha256},
            "record_type": "dataset_archive_regular_slice_allowlist",
            "schema_version": "1.0.0",
            "selected_expanded_size_bytes": 75,
            "selected_file_count": 8,
            "selected_files": selected,
            "selection_basis": (
                "The four mav0 CSV paths are exact audited regular files; the two PNG "
                "basenames are the lexicographically earliest two filenames in the exact "
                "intersection of audited regular-image paths under cam0/data and cam1/data."
            ),
            "selection_purpose": "tumvi_format_compatibility_smoke_only",
            "scientific_limitations": [
                "does_not_select_a_dataset",
                "does_not_assign_protocol_membership",
                "does_not_validate_csv_membership",
                "does_not_validate_camera_synchronization",
                "does_not_approve_model_access_training_inference_evaluation_or_publication",
            ],
            "structural_audit": {
                "authorization_path": self.audit_authorization_relative,
                "authorization_sha256": _sha256(self.audit_authorization_path),
                "claim_path": self.audit_claim_relative,
                "claim_sha256": _sha256(self.audit_claim_path),
                "member_count": 13,
                "path": self.audit_relative,
                "receipt_path": self.audit_receipt_relative,
                "receipt_sha256": _sha256(self.audit_receipt_path),
                "sha256": _sha256(self.audit_path),
                "source_failure_path": self.transfer_failure_relative,
                "source_failure_sha256": _sha256(self.transfer_failure_path),
            },
        }

    def authorization_document(self) -> dict[str, object]:
        authorized = _NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires = (_NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        review = (_NOW + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "archive_identity": {
                "allowed_redirect_origins": [],
                "allowed_redirect_urls": [],
                "archive_id": "synthetic-room4",
                "filename": "dataset-room4.tar",
                "md5": self.archive_md5,
                "sha256": self.archive_sha256,
                "size_bytes": len(self.archive_before),
                "url": "https://example.invalid/dataset-room4.tar",
            },
            "archive_path": self.archive_relative,
            "authority_basis": {
                "captured_at": authorized,
                "identity_authentication": "not_independently_authenticated",
                "instruction_summary": "Extract one synthetic compatibility slice.",
                "kind": "active_workspace_user_instruction",
            },
            "authorization_id": self.authorization_id,
            "authorized_at": authorized,
            "execution": {
                "maximum_elapsed_seconds": 600,
                "maximum_paid_compute_cost_usd": 0,
                "minimum_free_bytes": 2_149_580_875,
                "requires_clean_worktree": True,
                "tool_files": [
                    {
                        "path": f"src/compact_vio/data/{name}",
                        "sha256": _sha256(self.root / f"src/compact_vio/data/{name}"),
                    }
                    for name in ("archive_slice.py", "acquisition.py", "archive.py")
                ],
            },
            "expires_at": expires,
            "max_executions": 1,
            "outputs": {
                "claim_path": self.claim_relative,
                "destination_path": self.destination_relative,
                "receipt_path": self.receipt_relative,
            },
            "permitted_operations": [
                "write_claim",
                "verify_bound_source_evidence",
                "verify_archive_identity",
                "compare_all_tar_headers_to_structural_audit",
                "copy_allowlisted_regular_files",
                "hash_selected_files",
                "validate_exact_staging_tree",
                "publish_slice_atomically_no_replace",
                "write_receipt",
                "retract_exact_new_receipt_on_truth_gate_failure",
            ],
            "prohibited_operations": [
                "download",
                "modify_archive",
                "follow_links",
                "copy_unselected_members",
                "use_tar_extract",
                "use_tar_extractall",
                "decode_images",
                "parse_sensor_csv",
                "load_dataset_samples",
                "assign_protocol_membership",
                "select_dataset",
                "load_checkpoint",
                "train",
                "infer",
                "evaluate",
                "publish_scientific_result",
                "delete_source_evidence",
            ],
            "record_status": "approved",
            "record_type": "dataset_archive_regular_slice_authorization",
            "retention": {
                "deletion_authorized": False,
                "policy": "retain_slice_and_evidence_until_review",
                "review_at": review,
            },
            "schema_version": "1.0.0",
            "scope": "audit_bound_regular_file_compatibility_slice_only",
            "scientific_authority": {
                "approves_evaluation": False,
                "approves_inference": False,
                "approves_model_access": False,
                "approves_publication": False,
                "approves_training": False,
                "assigns_membership": False,
                "selects_dataset": False,
            },
            "slice_limits": {
                "max_expanded_size_bytes": 1000,
                "max_member_size_bytes": 1000,
                "max_members": 100,
                "maximum_receipt_bytes": 1048576,
                "selected_expanded_size_bytes": 75,
                "selected_file_count": 8,
            },
            "source_evidence": {
                "allowlist": {
                    "path": self.allowlist_relative,
                    "sha256": _sha256(self.allowlist_path),
                },
                "candidate": {
                    "path": self.candidate_relative,
                    "sha256": _sha256(self.candidate_path),
                },
                "structural_audit": {
                    "path": self.audit_relative,
                    "sha256": _sha256(self.audit_path),
                },
                "structural_audit_authorization": {
                    "path": self.audit_authorization_relative,
                    "sha256": _sha256(self.audit_authorization_path),
                },
                "structural_audit_claim": {
                    "path": self.audit_claim_relative,
                    "sha256": _sha256(self.audit_claim_path),
                },
                "structural_audit_receipt": {
                    "path": self.audit_receipt_relative,
                    "sha256": _sha256(self.audit_receipt_path),
                },
                "transfer_claim": {
                    "path": self.transfer_claim_relative,
                    "sha256": _sha256(self.transfer_claim_path),
                },
                "transfer_authorization": {
                    "path": self.transfer_authorization_relative,
                    "sha256": _sha256(self.transfer_authorization_path),
                },
                "transfer_failure": {
                    "path": self.transfer_failure_relative,
                    "sha256": _sha256(self.transfer_failure_path),
                },
            },
        }

    def write_authorization(self, document: dict[str, object] | None = None) -> None:
        self.authorization_path.write_text(
            json.dumps(document or self.authorization_document(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


class ArchiveRegularSliceControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _SliceRepositoryFixture()
        self.runtime_patch = mock.patch("compact_vio.data.archive_slice._assert_runtime_sources")
        self.runtime_patch.start()
        self.addCleanup(self.runtime_patch.stop)

    def tearDown(self) -> None:
        self.fixture.close()

    def _runtime_patches(self) -> tuple[mock._patch, mock._patch]:
        return (
            mock.patch(
                "compact_vio.data.archive_slice._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            mock.patch(
                "compact_vio.data.archive_slice._disk_usage",
                return_value=types.SimpleNamespace(free=10_000_000_000),
            ),
        )

    def test_checked_allowlist_freezes_exact_eight_file_tumvi_slice(self) -> None:
        allowlist = load_regular_slice_allowlist(
            _CHECKED_ALLOWLIST,
            repo_root=_PROJECT_ROOT,
        )
        self.assertEqual(
            allowlist.sha256,
            "db8a24c18a62bb0e74140a20799d1e7414c34c5bbc75f284ec907736ae2dacd0",
        )
        self.assertEqual(allowlist.allowed_root, "dataset-room4_512_16/mav0")
        self.assertEqual(len(allowlist.selected_files), 8)
        self.assertEqual(allowlist.selected_expanded_size_bytes, 5_043_300)
        self.assertEqual(
            [item.size_bytes for item in allowlist.selected_files],
            [98_057, 98_057, 2_232_296, 1_481_244, 284_188, 283_001, 283_946, 282_511],
        )
        self.assertEqual(
            [Path(item.path).name for item in allowlist.selected_files[4:]],
            [
                "1520531124150444163.png",
                "1520531124150444163.png",
                "1520531124200446163.png",
                "1520531124200446163.png",
            ],
        )

    def test_checked_authorization_and_receipt_bind_exact_real_execution(self) -> None:
        authorization = load_regular_slice_authorization(
            _CHECKED_AUTHORIZATION,
            repo_root=_PROJECT_ROOT,
        )
        self.assertEqual(
            authorization.authorization_sha256,
            "f39ba7598eac1a0301ced5b13d835231c79757b26e096219145737a139f79e81",
        )
        self.assertEqual(authorization.maximum_elapsed_seconds, 3_600)
        self.assertEqual(authorization.minimum_free_bytes, 2_154_624_100)
        self.assertEqual(len(authorization.allowlist.selected_files), 8)
        self.assertEqual(authorization.allowlist.selected_expanded_size_bytes, 5_043_300)
        claim = _PROJECT_ROOT / "data/quarantine/tum-vi/room4-512-16/compatibility-slice.claim.json"
        self.assertEqual(
            _sha256(claim),
            "8e4e8a8ad8c58c96e10535600caacaed51776c173c3b6babec557c3f973c4271",
        )
        self.assertEqual(
            _sha256(_CHECKED_RECEIPT),
            "a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820",
        )
        receipt = json.loads(_CHECKED_RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(receipt["scientific_authority"], "none")
        self.assertEqual(receipt["slice"]["file_count"], 8)
        self.assertEqual(receipt["slice"]["expanded_size_bytes"], 5_043_300)

    def test_loads_exact_authorization_without_reading_archive(self) -> None:
        original_read_bytes = Path.read_bytes

        def guarded_read_bytes(path: Path) -> bytes:
            if path == self.fixture.archive_path:
                raise AssertionError("authorization loading must not read archive bytes")
            return original_read_bytes(path)

        with mock.patch.object(
            Path,
            "read_bytes",
            autospec=True,
            side_effect=guarded_read_bytes,
        ) as read:
            result = load_regular_slice_authorization(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertEqual(result.authorization_id, self.fixture.authorization_id)
        self.assertEqual(result.allowlist.selected_expanded_size_bytes, 75)
        self.assertNotIn(self.fixture.archive_path, [call.args[0] for call in read.call_args_list])
        self.assertFalse(self.fixture.claim_path.exists())

    def test_success_copies_only_regular_allowlist_and_writes_receipt_last(self) -> None:
        now_patch, disk_patch = self._runtime_patches()
        with (
            now_patch,
            disk_patch,
            mock.patch.object(
                tarfile.TarFile,
                "extract",
                side_effect=AssertionError("extract must not run"),
            ) as extract,
            mock.patch.object(
                tarfile.TarFile,
                "extractall",
                side_effect=AssertionError("extractall must not run"),
            ) as extractall,
        ):
            result = run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        extract.assert_not_called()
        extractall.assert_not_called()
        self.assertEqual(self.fixture.archive_path.read_bytes(), self.fixture.archive_before)
        self.assertEqual(len(result.extracted_files), 8)
        self.assertEqual(
            (self.fixture.destination_path / "dataset/mav0/cam0/data.csv").read_bytes(),
            b"camera-index",
        )
        self.assertFalse((self.fixture.destination_path / "dataset/mav0/ignored.txt").exists())
        self.assertFalse((self.fixture.destination_path / "dataset/dso").exists())
        receipt = json.loads(self.fixture.receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["outcome"], "completed")
        self.assertEqual(receipt["scientific_authority"], "none")
        self.assertEqual(receipt["slice"]["file_count"], 8)
        self.assertIn("decode_images", receipt["operations_not_performed"])
        self.assertNotIn(
            "retract_exact_new_receipt_on_truth_gate_failure",
            receipt["operations_performed"],
        )
        self.assertIn("controller_started_at", receipt)
        self.assertIn("claim_prepared_at", receipt)

    def test_schema_or_evidence_mismatch_fails_before_claim(self) -> None:
        for label, mutate in (
            ("extra", lambda item: item.__setitem__("extra", 1)),
            (
                "operation",
                lambda item: item["permitted_operations"].append("decode_images"),
            ),
            (
                "audit hash",
                lambda item: item["source_evidence"]["structural_audit"].__setitem__(
                    "sha256", "0" * 64
                ),
            ),
        ):
            with self.subTest(label=label):
                document = self.fixture.authorization_document()
                mutate(document)
                self.fixture.write_authorization(document)
                with self.assertRaises(AcquisitionError):
                    load_regular_slice_authorization(
                        self.fixture.authorization_path,
                        repo_root=self.fixture.root,
                    )
        self.assertFalse(self.fixture.claim_path.exists())

    def test_wrong_archive_bytes_consume_claim_without_slice_or_receipt(self) -> None:
        self.fixture.archive_path.write_bytes(b"changed")
        now_patch, disk_patch = self._runtime_patches()
        with (
            now_patch,
            disk_patch,
            self.assertRaisesRegex(AcquisitionError, "archive size mismatch"),
        ):
            run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.destination_path.exists())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_existing_destination_rejects_before_claim(self) -> None:
        self.fixture.destination_path.mkdir()
        with (
            mock.patch(
                "compact_vio.data.archive_slice._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            self.assertRaisesRegex(AcquisitionError, "must be absent"),
        ):
            run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.claim_path.exists())

    def test_rechecks_authorization_window_immediately_before_claim(self) -> None:
        times = iter((_NOW + timedelta(minutes=1), _NOW + timedelta(days=1)))
        with (
            mock.patch(
                "compact_vio.data.archive_slice._utc_now",
                side_effect=lambda: next(times),
            ),
            mock.patch(
                "compact_vio.data.archive_slice._disk_usage",
                return_value=types.SimpleNamespace(free=10_000_000_000),
            ),
            self.assertRaisesRegex(AcquisitionError, "immediately before claim"),
        ):
            run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.destination_path.exists())

    def test_elapsed_bound_includes_preclaim_validation(self) -> None:
        with (
            mock.patch(
                "compact_vio.data.archive_slice._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            mock.patch(
                "compact_vio.data.archive_slice.time.monotonic",
                side_effect=(100.0, 701.0),
            ),
            mock.patch(
                "compact_vio.data.archive_slice._disk_usage",
                return_value=types.SimpleNamespace(free=10_000_000_000),
            ),
            self.assertRaisesRegex(AcquisitionError, "elapsed-time bound expired before claim"),
        ):
            run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertFalse(self.fixture.claim_path.exists())
        self.assertFalse(self.fixture.destination_path.exists())

    def test_post_slice_low_space_prevents_receipt(self) -> None:
        with (
            mock.patch(
                "compact_vio.data.archive_slice._utc_now",
                return_value=_NOW + timedelta(minutes=1),
            ),
            mock.patch(
                "compact_vio.data.archive_slice._disk_usage",
                side_effect=(
                    types.SimpleNamespace(free=10_000_000_000),
                    types.SimpleNamespace(free=1),
                ),
            ),
            self.assertRaisesRegex(AcquisitionError, "post-slice reserve"),
        ):
            run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertTrue(self.fixture.destination_path.is_dir())
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_hard_deadline_remains_active_during_receipt_publication(self) -> None:
        now_patch, disk_patch = self._runtime_patches()
        real_write = slice_module._write_new_atomic
        timer_observations: list[tuple[Path, float]] = []

        def observe_timer(path: Path, payload: bytes) -> str:
            timer_observations.append((path, signal.getitimer(signal.ITIMER_REAL)[0]))
            return real_write(path, payload)

        with (
            now_patch,
            disk_patch,
            mock.patch(
                "compact_vio.data.archive_slice._write_new_atomic",
                side_effect=observe_timer,
            ),
        ):
            run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        receipt_timers = [
            remaining
            for path, remaining in timer_observations
            if path.name == self.fixture.receipt_path.name
        ]
        self.assertEqual(len(receipt_timers), 1)
        self.assertGreater(receipt_timers[0], 0)

    def test_post_receipt_git_gate_allows_only_the_exact_new_receipt(self) -> None:
        revision = slice_module._assert_clean_repository(self.fixture.root)
        self.fixture.receipt_path.write_bytes(b"{}\n")
        slice_module._assert_repository_with_new_receipt(
            self.fixture.root,
            expected_revision=revision,
            receipt_relative=self.fixture.receipt_relative,
        )

        (self.fixture.root / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
        with self.assertRaisesRegex(AcquisitionError, "beyond the exact new receipt"):
            slice_module._assert_repository_with_new_receipt(
                self.fixture.root,
                expected_revision=revision,
                receipt_relative=self.fixture.receipt_relative,
            )

    def test_hardlink_swap_at_final_root_gate_retracts_completed_receipt(self) -> None:
        now_patch, disk_patch = self._runtime_patches()
        real_assert_bound_directory = slice_module._assert_bound_directory
        gate_calls = 0

        def mutate_at_final_gate(
            path: Path,
            descriptor: int,
            expected: tuple[int, int, int],
        ) -> None:
            nonlocal gate_calls
            real_assert_bound_directory(path, descriptor, expected)
            gate_calls += 1
            if gate_calls != 7:
                return
            selected = self.fixture.destination_path / "dataset/mav0/cam0/data.csv"
            external = self.fixture.destination_path.parent / "same-byte-external.bin"
            external.write_bytes(selected.read_bytes())
            selected.unlink()
            os.link(external, selected)

        with (
            now_patch,
            disk_patch,
            mock.patch(
                "compact_vio.data.archive_slice._assert_bound_directory",
                side_effect=mutate_at_final_gate,
            ),
            self.assertRaisesRegex(AcquisitionError, "unsafe file"),
        ):
            run_authorized_regular_slice(
                self.fixture.authorization_relative,
                repo_root=self.fixture.root,
            )
        self.assertGreaterEqual(gate_calls, 8)
        self.assertTrue(self.fixture.claim_path.exists())
        self.assertTrue(self.fixture.destination_path.is_dir())
        self.assertEqual(
            os.lstat(self.fixture.destination_path / "dataset/mav0/cam0/data.csv").st_nlink,
            2,
        )
        self.assertFalse(self.fixture.receipt_path.exists())

    def test_published_verifier_rejects_empty_directory_and_root_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "slice"
            selected = destination / "dataset/mav0/cam0/data.csv"
            selected.parent.mkdir(parents=True)
            selected.write_bytes(b"camera-index")
            receipt = ExtractedFileReceipt(
                "dataset/mav0/cam0/data.csv",
                12,
                hashlib.sha256(b"camera-index").hexdigest(),
            )
            descriptor, identity = slice_module._open_bound_directory(destination)
            self.addCleanup(os.close, descriptor)
            (destination / "unexpected-empty").mkdir()
            with self.assertRaisesRegex(AcquisitionError, "unexpected directory"):
                slice_module._verify_published_slice(
                    destination,
                    (receipt,),
                    root_descriptor=descriptor,
                    root_identity=identity,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "slice"
            selected = destination / "dataset/mav0/cam0/data.csv"
            selected.parent.mkdir(parents=True)
            selected.write_bytes(b"camera-index")
            external = root / "external"
            external_selected = external / "dataset/mav0/cam0/data.csv"
            external_selected.parent.mkdir(parents=True)
            external_selected.write_bytes(b"camera-index")
            receipt = ExtractedFileReceipt(
                "dataset/mav0/cam0/data.csv",
                12,
                hashlib.sha256(b"camera-index").hexdigest(),
            )
            descriptor, identity = slice_module._open_bound_directory(destination)
            real_walk = os.walk

            def swap_root(*_args: object, **_kwargs: object) -> object:
                destination.rename(root / "original")
                destination.symlink_to(external, target_is_directory=True)
                return real_walk(destination, followlinks=False)

            try:
                with (
                    mock.patch(
                        "compact_vio.data.archive_slice.os.walk",
                        side_effect=swap_root,
                    ),
                    self.assertRaisesRegex(AcquisitionError, "root identity changed"),
                ):
                    slice_module._verify_published_slice(
                        destination,
                        (receipt,),
                        root_descriptor=descriptor,
                        root_identity=identity,
                    )
            finally:
                os.close(descriptor)

    def test_open_staging_binding_failure_cleans_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "archive.tar"
            _write_tar(archive)
            audit = audit_tar_structure(archive, expected_sha256=_sha256(archive))
            with (
                mock.patch(
                    "compact_vio.data.archive._open_staging_directory",
                    side_effect=OSError("bind failed"),
                ),
                self.assertRaisesRegex(ArchiveError, "bind failed"),
            ):
                slice_module.extract_tar_regular_slice(
                    archive,
                    root / "output",
                    expected_sha256=_sha256(archive),
                    expected_structure=audit,
                    allowed_root="dataset/mav0",
                    selected_files=(
                        slice_module.TarRegularSliceMember("dataset/mav0/cam0/data.csv", 12),
                    ),
                    validate_staging=lambda _path, _receipts: None,
                )
            self.assertFalse(any(root.glob(".output.staging-*")))

    def test_cli_failures_are_one_structured_json_object(self) -> None:
        with mock.patch("sys.stderr") as stderr:
            result = main([])
        self.assertEqual(result, 2)
        payload = json.loads(stderr.write.call_args_list[0].args[0])
        self.assertEqual(payload["error_code"], "archive_regular_slice_failed")


if __name__ == "__main__":
    unittest.main()

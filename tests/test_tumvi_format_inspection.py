from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import compact_vio.data.tumvi_format_inspection as inspection_module
from compact_vio.data.acquisition import AcquisitionError, ToolIdentity
from compact_vio.data.tumvi_format import TumviFormatError
from compact_vio.data.tumvi_format_inspection import (
    _ADAPTER,
    _ADAPTER_SHA256,
    _CAMERA_HEADER,
    _CANDIDATE,
    _CANDIDATE_SHA256,
    _CLAIM_PATH,
    _CROSS_FILE_CHECKS,
    _FULL_STATE_HEADERS,
    _IMU_HEADER,
    _MINIMUM_FREE_BYTES,
    _PERMITTED_OPERATIONS,
    _PROHIBITED_OPERATIONS,
    _RECEIPT_PATH,
    _REVIEW_REPORT,
    _REVIEW_REPORT_SHA256,
    _SLICE_DESTINATION,
    _SLICE_RECEIPT,
    _SLICE_RECEIPT_SHA256,
    _SOURCE_SIZE_BYTES,
    _SPEC_PATH,
    _TOOL_PATHS,
    EvidenceIdentity,
    FormatInspectionAuthorization,
    FormatInspectionSpec,
    InspectionFile,
    InspectionOutputs,
    _assert_bound_slice_tree,
    _bind_exact_slice_tree,
    _inspect_bound_tree,
    load_format_inspection_authorization,
    load_format_inspection_spec,
    main,
    run_authorized_format_inspection,
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _checked_spec_path() -> Path:
    return Path(__file__).resolve().parents[1] / _SPEC_PATH


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _png_prefix() -> bytes:
    chunk = b"IHDR" + struct.pack(">IIBBBBB", 512, 512, 16, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + chunk
        + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)
    )


def _csv(header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    return (",".join(header) + "\n" + "".join(",".join(row) + "\n" for row in rows)).encode()


def _synthetic_payloads() -> dict[str, bytes]:
    camera = _csv(_CAMERA_HEADER, (("1", "1.png"), ("2", "2.png")))
    imu = _csv(
        _IMU_HEADER,
        (("0", "0", "0", "0", "0", "0", "0"), ("3", "1", "1", "1", "1", "1", "1")),
    )

    def mocap_row(timestamp: str) -> tuple[str, ...]:
        return (timestamp,) + ("0",) * (len(_FULL_STATE_HEADERS[0]) - 1)

    mocap = _csv(_FULL_STATE_HEADERS[0], (mocap_row("0"), mocap_row("3")))
    png = _png_prefix()
    root = "dataset-room4_512_16/mav0"
    return {
        f"{root}/cam0/data.csv": camera,
        f"{root}/cam1/data.csv": camera,
        f"{root}/imu0/data.csv": imu,
        f"{root}/mocap0/data.csv": mocap,
        f"{root}/cam0/data/1.png": png,
        f"{root}/cam1/data/1.png": png,
        f"{root}/cam0/data/2.png": png,
        f"{root}/cam1/data/2.png": png,
    }


def _synthetic_spec(payloads: dict[str, bytes]) -> FormatInspectionSpec:
    role_paths = (
        ("cam0_index", "dataset-room4_512_16/mav0/cam0/data.csv"),
        ("cam1_index", "dataset-room4_512_16/mav0/cam1/data.csv"),
        ("imu_stream", "dataset-room4_512_16/mav0/imu0/data.csv"),
        ("mocap_stream", "dataset-room4_512_16/mav0/mocap0/data.csv"),
        ("cam0_png_0", "dataset-room4_512_16/mav0/cam0/data/1.png"),
        ("cam1_png_0", "dataset-room4_512_16/mav0/cam1/data/1.png"),
        ("cam0_png_1", "dataset-room4_512_16/mav0/cam0/data/2.png"),
        ("cam1_png_1", "dataset-room4_512_16/mav0/cam1/data/2.png"),
    )
    files = tuple(
        InspectionFile(role, path, len(payloads[path]), _sha(payloads[path]))
        for role, path in role_paths
    )
    return FormatInspectionSpec(
        _SPEC_PATH,
        "0" * 64,
        "synthetic",
        EvidenceIdentity(_SLICE_RECEIPT, _SLICE_RECEIPT_SHA256),
        EvidenceIdentity(_REVIEW_REPORT, _REVIEW_REPORT_SHA256),
        _SLICE_DESTINATION,
        EvidenceIdentity(_CANDIDATE, _CANDIDATE_SHA256),
        EvidenceIdentity(_ADAPTER, _ADAPTER_SHA256),
        files,
        _CAMERA_HEADER,
        _IMU_HEADER,
        _FULL_STATE_HEADERS,
        _CROSS_FILE_CHECKS,
    )


def _authorization_document(spec_sha256: str) -> dict[str, object]:
    evidence = {
        "inspection_spec": {"path": _SPEC_PATH, "sha256": spec_sha256},
        "slice_receipt": {"path": _SLICE_RECEIPT, "sha256": _SLICE_RECEIPT_SHA256},
        "review_report": {"path": _REVIEW_REPORT, "sha256": _REVIEW_REPORT_SHA256},
        "candidate": {"path": _CANDIDATE, "sha256": _CANDIDATE_SHA256},
        "current_euroc_adapter": {"path": _ADAPTER, "sha256": _ADAPTER_SHA256},
    }
    return {
        "authority_basis": {
            "kind": "active_workspace_user_instruction",
            "instruction_summary": "Synthetic parser fixture; grants no real execution authority.",
            "captured_at": "2026-08-29T20:00:00Z",
            "identity_authentication": "not_independently_authenticated",
        },
        "authorization_id": "synthetic-format-inspection",
        "authorized_at": "2026-08-29T20:00:00Z",
        "execution": {
            "requires_clean_worktree": True,
            "maximum_elapsed_seconds": 600,
            "maximum_paid_compute_cost_usd": 0,
            "minimum_free_bytes": _MINIMUM_FREE_BYTES,
            "tool_files": [{"path": path, "sha256": "0" * 64} for path in _TOOL_PATHS],
        },
        "expires_at": "2026-08-30T20:00:00Z",
        "max_executions": 1,
        "outputs": {"claim_path": _CLAIM_PATH, "receipt_path": _RECEIPT_PATH},
        "permitted_operations": list(_PERMITTED_OPERATIONS),
        "prohibited_operations": list(_PROHIBITED_OPERATIONS),
        "record_status": "approved",
        "record_type": "dataset_format_inspection_authorization",
        "retention": {
            "policy": "retain_format_inspection_evidence_until_review",
            "review_at": "2026-09-06T20:00:00Z",
            "deletion_authorized": False,
        },
        "schema_version": "1.0.0",
        "scientific_authority": {
            "selects_dataset": False,
            "assigns_membership": False,
            "approves_adapter": False,
            "approves_calibration": False,
            "approves_ground_truth": False,
            "approves_model_access": False,
            "approves_training": False,
            "approves_inference": False,
            "approves_evaluation": False,
            "approves_publication": False,
        },
        "scope": "bounded_opaque_csv_and_png_ihdr_observation_only",
        "inspection_limits": {
            "source_file_count": 8,
            "source_size_bytes": _SOURCE_SIZE_BYTES,
            "csv_file_count": 4,
            "png_file_count": 4,
            "png_interpreted_bytes_per_file": 33,
            "maximum_csv_rows_per_file": 1_000_000,
            "maximum_csv_line_bytes": 1_048_576,
            "maximum_claim_bytes": 1_048_576,
            "maximum_receipt_bytes": 1_048_576,
            "post_inspection_reserve_bytes": 2_147_483_648,
        },
        "source_evidence": evidence,
    }


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _git_backed_fixture(
    root: Path,
    payloads: dict[str, bytes],
) -> tuple[Path, FormatInspectionAuthorization, FormatInspectionSpec]:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".gitignore").write_text("/data/\n", encoding="utf-8")
    base = _synthetic_spec(payloads)

    spec_bytes = b'{"synthetic_checked_spec":true}\n'
    spec_path = root / _SPEC_PATH
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_bytes(spec_bytes)
    report_bytes = b"synthetic reviewed compatibility-slice report\n"
    report_path = root / _REVIEW_REPORT
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(report_bytes)
    candidate_document = {
        "record_status": "candidate_non_executable",
        "authority": {"selects_dataset": False},
        "candidate_unit": {
            "image_resolution": [512, 512],
            "published_image_bit_depth": 16,
        },
    }
    candidate_path = root / _CANDIDATE
    _write_json(candidate_path, candidate_document)
    candidate_bytes = candidate_path.read_bytes()
    adapter_bytes = b"# synthetic tracked adapter comparison source\n"
    adapter_path = root / _ADAPTER
    adapter_path.parent.mkdir(parents=True, exist_ok=True)
    adapter_path.write_bytes(adapter_bytes)
    source_receipt_path = root / _SLICE_RECEIPT
    source_receipt = {
        "outcome": "completed",
        "scientific_authority": "none",
        "slice": {
            "destination_path": _SLICE_DESTINATION,
            "files": [
                {"path": item.path, "sha256": item.sha256, "size_bytes": item.size_bytes}
                for item in base.files
            ],
        },
        "source_evidence": {"candidate": {"path": _CANDIDATE, "sha256": _sha(candidate_bytes)}},
    }
    _write_json(source_receipt_path, source_receipt)
    source_receipt_bytes = source_receipt_path.read_bytes()

    spec = replace(
        base,
        path=_SPEC_PATH,
        sha256=_sha(spec_bytes),
        slice_receipt=EvidenceIdentity(_SLICE_RECEIPT, _sha(source_receipt_bytes)),
        review_report=EvidenceIdentity(_REVIEW_REPORT, _sha(report_bytes)),
        candidate=EvidenceIdentity(_CANDIDATE, _sha(candidate_bytes)),
        current_euroc_adapter=EvidenceIdentity(_ADAPTER, _sha(adapter_bytes)),
    )
    for relative, payload in payloads.items():
        path = root / _SLICE_DESTINATION / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    tool_files: list[ToolIdentity] = []
    for relative in _TOOL_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = f"# synthetic tracked tool: {relative}\n".encode()
        path.write_bytes(payload)
        tool_files.append(ToolIdentity(relative, _sha(payload)))
    authorization_relative = (
        "governance/datasets/acquisitions/synthetic-format-inspection.authorization.json"
    )
    authorization_path = root / authorization_relative
    authorization_bytes = b'{"synthetic_authorization":true}\n'
    authorization_path.write_bytes(authorization_bytes)

    _git(root, "init", "-q")
    _git(root, "config", "user.name", "compact-vio-test")
    _git(root, "config", "user.email", "compact-vio-test@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "synthetic format inspection fixture")
    authorization = FormatInspectionAuthorization(
        authorization_id="synthetic-format-inspection",
        authorization_path=authorization_relative,
        authorization_sha256=_sha(authorization_bytes),
        authorized_at=datetime(2026, 8, 29, 20, tzinfo=timezone.utc),
        expires_at=datetime(2026, 8, 30, 20, tzinfo=timezone.utc),
        spec_identity=EvidenceIdentity(_SPEC_PATH, _sha(spec_bytes)),
        spec=spec,
        maximum_elapsed_seconds=600,
        minimum_free_bytes=_MINIMUM_FREE_BYTES,
        tool_files=tuple(tool_files),
        retention_review_at=datetime(2026, 9, 6, 20, tzinfo=timezone.utc),
        outputs=InspectionOutputs(_CLAIM_PATH, _RECEIPT_PATH),
    )
    return authorization_path, authorization, spec


def _run_fixture(
    root: Path,
    authorization_path: Path,
    authorization: FormatInspectionAuthorization,
) -> object:
    fixed_now = datetime(2026, 8, 29, 21, tzinfo=timezone.utc)
    with (
        mock.patch.object(
            inspection_module,
            "load_format_inspection_authorization",
            return_value=authorization,
        ),
        mock.patch.object(inspection_module, "_runtime_sources"),
        mock.patch.object(inspection_module, "_utc_now", return_value=fixed_now),
    ):
        return run_authorized_format_inspection(authorization_path, repo_root=root)


class FormatInspectionSpecTests(unittest.TestCase):
    def test_checked_spec_loads_with_exact_contract(self) -> None:
        root = _checked_spec_path().parents[2]
        spec = load_format_inspection_spec(_checked_spec_path(), repo_root=root)
        self.assertEqual(spec.inspection_id, "tumvi-room4-512-16-format-inspection-v1")
        self.assertEqual(len(spec.files), 8)
        self.assertEqual(sum(item.size_bytes for item in spec.files), _SOURCE_SIZE_BYTES)
        self.assertEqual(spec.cross_file_checks, _CROSS_FILE_CHECKS)

    def test_spec_rejects_extra_field_and_file_reordering(self) -> None:
        document = json.loads(_checked_spec_path().read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / _SPEC_PATH
            extra = copy.deepcopy(document)
            extra["unexpected"] = True
            _write_json(path, extra)
            with self.assertRaisesRegex(AcquisitionError, "fields must equal"):
                load_format_inspection_spec(path, repo_root=root)
            reordered = copy.deepcopy(document)
            reordered["files"][0], reordered["files"][1] = (
                reordered["files"][1],
                reordered["files"][0],
            )
            _write_json(path, reordered)
            with self.assertRaisesRegex(AcquisitionError, "exact ordered"):
                load_format_inspection_spec(path, repo_root=root)


class FormatInspectionAuthorizationTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, dict[str, object]]:
        spec_path = root / _SPEC_PATH
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_bytes = _checked_spec_path().read_bytes()
        spec_path.write_bytes(spec_bytes)
        document = _authorization_document(_sha(spec_bytes))
        authorization = root / "authorization.json"
        _write_json(authorization, document)
        return authorization, document

    def test_strict_future_authorization_loads_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization, _ = self._fixture(root)
            loaded = load_format_inspection_authorization(authorization, repo_root=root)
            self.assertEqual(loaded.maximum_elapsed_seconds, 600)
            self.assertEqual(loaded.outputs.receipt_path, _RECEIPT_PATH)

    def test_authorization_rejects_non_24_hour_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization, document = self._fixture(root)
            document["expires_at"] = "2026-08-30T19:59:59Z"
            _write_json(authorization, document)
            with self.assertRaisesRegex(AcquisitionError, "exactly 24 hours"):
                load_format_inspection_authorization(authorization, repo_root=root)

    def test_authorization_rejects_tool_order_and_broader_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization, document = self._fixture(root)
            document["execution"]["tool_files"].reverse()
            _write_json(authorization, document)
            with self.assertRaisesRegex(AcquisitionError, "tool_files paths"):
                load_format_inspection_authorization(authorization, repo_root=root)
            document["execution"]["tool_files"].reverse()
            document["scientific_authority"]["selects_dataset"] = True
            _write_json(authorization, document)
            with self.assertRaisesRegex(AcquisitionError, "must equal False"):
                load_format_inspection_authorization(authorization, repo_root=root)


class BoundSliceTests(unittest.TestCase):
    def _write_tree(self, root: Path, payloads: dict[str, bytes]) -> None:
        for relative, payload in payloads.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

    def test_fd_bound_exact_tree_and_streamed_observations(self) -> None:
        payloads = _synthetic_payloads()
        spec = _synthetic_spec(payloads)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory)
            self._write_tree(root, payloads)
            tree = _bind_exact_slice_tree(root, spec.files, cleanup=cleanup)
            stereo, imu, mocap, pngs, predicates = _inspect_bound_tree(tree, spec)
            self.assertTrue(stereo.exact_index_equality)
            self.assertTrue(imu.conforms)
            self.assertTrue(mocap.conforms)
            self.assertTrue(all(item.conforms for item in pngs.values()))
            self.assertTrue(all(predicates.values()))
            _assert_bound_slice_tree(tree, spec.files)

    def test_exact_tree_rejects_extra_file(self) -> None:
        payloads = _synthetic_payloads()
        spec = _synthetic_spec(payloads)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory)
            self._write_tree(root, payloads)
            (root / "unexpected.txt").write_text("no", encoding="utf-8")
            with self.assertRaisesRegex(AcquisitionError, "slice tree differs"):
                _bind_exact_slice_tree(root, spec.files, cleanup=cleanup)

    def test_exact_tree_rejects_symlinked_selected_file(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        payloads = _synthetic_payloads()
        spec = _synthetic_spec(payloads)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory)
            self._write_tree(root, payloads)
            target = root / spec.files[0].path
            target.unlink()
            os.symlink(root / spec.files[1].path, target)
            with self.assertRaises(AcquisitionError):
                _bind_exact_slice_tree(root, spec.files, cleanup=cleanup)

    def test_bound_identity_rejects_same_bytes_mutate_then_restore(self) -> None:
        payloads = _synthetic_payloads()
        spec = _synthetic_spec(payloads)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory)
            self._write_tree(root, payloads)
            tree = _bind_exact_slice_tree(root, spec.files, cleanup=cleanup)
            target = root / spec.files[0].path
            original = target.read_bytes()
            target.write_bytes(original)
            with self.assertRaisesRegex(AcquisitionError, "became unsafe"):
                _assert_bound_slice_tree(tree, spec.files)

    def test_content_mismatch_is_bounded_observation_not_operational_error(self) -> None:
        payloads = _synthetic_payloads()
        imu_path = "dataset-room4_512_16/mav0/imu0/data.csv"
        payloads[imu_path] = payloads[imu_path].replace(b"#timestamp [ns]", b"#time [ns]", 1)
        spec = _synthetic_spec(payloads)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory)
            self._write_tree(root, payloads)
            tree = _bind_exact_slice_tree(root, spec.files, cleanup=cleanup)
            _, imu, _, _, _ = _inspect_bound_tree(tree, spec)
            self.assertFalse(imu.conforms)
            self.assertIn("header_mismatch", imu.violations)


class GitBackedFormatInspectionRunnerTests(unittest.TestCase):
    def test_end_to_end_success_writes_claim_then_receipt_and_rejects_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            watched = {
                name for name in sys.modules if name.split(".")[0] in {"PIL", "cv2", "torch"}
            }
            result = _run_fixture(root, authorization_path, authorization)
            self.assertEqual(result.format_comparison_outcome, "conforms")
            self.assertTrue((root / _CLAIM_PATH).is_file())
            receipt_path = root / _RECEIPT_PATH
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["execution_outcome"], "completed")
            self.assertEqual(receipt["comparison"]["format_comparison_outcome"], "conforms")
            self.assertEqual(receipt["scientific_authority"], "none")
            self.assertIn(
                "elapsed_seconds_at_receipt_preparation",
                receipt["execution"],
            )
            self.assertNotIn("elapsed_seconds", receipt["execution"])
            self.assertEqual(receipt["limitations"], list(inspection_module._LIMITATIONS))
            self.assertEqual(
                receipt["inspection"]["full_indexed_image_existence"],
                "not_checked",
            )
            self.assertEqual(
                {name for name in sys.modules if name.split(".")[0] in {"PIL", "cv2", "torch"}},
                watched,
            )
            with self.assertRaises(AcquisitionError):
                _run_fixture(root, authorization_path, authorization)

    def test_content_mismatch_completes_as_does_not_conform(self) -> None:
        payloads = _synthetic_payloads()
        imu_path = "dataset-room4_512_16/mav0/imu0/data.csv"
        payloads[imu_path] = payloads[imu_path].replace(b"#timestamp [ns]", b"#time [ns]", 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, payloads)
            result = _run_fixture(root, authorization_path, authorization)
            self.assertEqual(result.format_comparison_outcome, "does_not_conform")
            receipt = json.loads((root / _RECEIPT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(receipt["execution_outcome"], "completed")
            self.assertEqual(
                receipt["comparison"]["format_comparison_outcome"],
                "does_not_conform",
            )

    def test_operational_parser_failure_consumes_claim_without_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            with (
                mock.patch.object(
                    inspection_module,
                    "inspect_numeric_csv",
                    side_effect=TumviFormatError("synthetic parser I/O failure"),
                ),
                self.assertRaisesRegex(AcquisitionError, "failed operationally"),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_all_source_safety_failures_precede_claim(self) -> None:
        cases = ("tracked", "hash", "symlink", "hardlink", "extra")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authorization_path, authorization, spec = _git_backed_fixture(
                    root, _synthetic_payloads()
                )
                if case == "tracked":
                    (root / _REVIEW_REPORT).write_text("changed\n", encoding="utf-8")
                elif case == "hash":
                    selected = root / _SLICE_DESTINATION / spec.files[0].path
                    selected.write_bytes(b"x" * spec.files[0].size_bytes)
                elif case == "symlink":
                    selected = root / _SLICE_DESTINATION / spec.files[0].path
                    selected.unlink()
                    os.symlink(root / _SLICE_DESTINATION / spec.files[1].path, selected)
                elif case == "hardlink":
                    selected = root / _SLICE_DESTINATION / spec.files[0].path
                    selected.unlink()
                    os.link(root / _SLICE_DESTINATION / spec.files[1].path, selected)
                else:
                    (root / _SLICE_DESTINATION / "unexpected.bin").write_bytes(b"no")
                with self.assertRaises(AcquisitionError):
                    _run_fixture(root, authorization_path, authorization)
                self.assertFalse(os.path.lexists(root / _CLAIM_PATH))
                self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_deadline_covers_preclaim_and_receipt_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            with (
                mock.patch.object(
                    inspection_module.time,
                    "monotonic",
                    side_effect=(0.0, 601.0),
                ),
                self.assertRaisesRegex(AcquisitionError, "pre-claim"),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertFalse(os.path.lexists(root / _CLAIM_PATH))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            real_check = inspection_module._check_deadline

            def fail_receipt(started: float, maximum: int, *, phase: str) -> float:
                if phase == "format receipt":
                    raise AcquisitionError("synthetic receipt deadline")
                return real_check(started, maximum, phase=phase)

            with (
                mock.patch.object(
                    inspection_module,
                    "_check_deadline",
                    side_effect=fail_receipt,
                ),
                self.assertRaisesRegex(AcquisitionError, "receipt deadline"),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_final_mutations_retract_exact_new_receipt(self) -> None:
        for mutation in ("claim", "tree", "tracked_source"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authorization_path, authorization, spec = _git_backed_fixture(
                    root, _synthetic_payloads()
                )
                real_publish = inspection_module._write_owned_receipt_atomic

                def publish_then_mutate(
                    path: Path,
                    payload: bytes,
                    *,
                    publish: Callable[..., inspection_module._ReceiptPublication] = real_publish,
                    fixture_root: Path = root,
                    mutation_kind: str = mutation,
                    fixture_spec: FormatInspectionSpec = spec,
                    ownership: inspection_module._ReceiptOwnership,
                ) -> inspection_module._ReceiptPublication:
                    publication = publish(path, payload, ownership=ownership)
                    if mutation_kind == "claim":
                        (fixture_root / _CLAIM_PATH).write_bytes(b"changed claim\n")
                    elif mutation_kind == "tree":
                        target = fixture_root / _SLICE_DESTINATION / fixture_spec.files[0].path
                        target.write_bytes(target.read_bytes() + b"changed")
                    else:
                        (fixture_root / _REVIEW_REPORT).write_text(
                            "changed tracked source\n", encoding="utf-8"
                        )
                    return publication

                with (
                    mock.patch.object(
                        inspection_module,
                        "_write_owned_receipt_atomic",
                        side_effect=publish_then_mutate,
                    ),
                    self.assertRaises(AcquisitionError),
                ):
                    _run_fixture(root, authorization_path, authorization)
                self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))
                self.assertTrue((root / _CLAIM_PATH).is_file())

    def test_exception_immediately_after_receipt_publication_retracts_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            real_publish = inspection_module._write_owned_receipt_atomic

            def publish_then_fail(
                path: Path,
                payload: bytes,
                *,
                ownership: inspection_module._ReceiptOwnership,
            ) -> inspection_module._ReceiptPublication:
                real_publish(path, payload, ownership=ownership)
                raise AcquisitionError("synthetic post-publication timeout")

            with (
                mock.patch.object(
                    inspection_module,
                    "_write_owned_receipt_atomic",
                    side_effect=publish_then_fail,
                ),
                self.assertRaisesRegex(AcquisitionError, "post-publication timeout"),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_deadline_context_exit_failure_retracts_owned_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            real_deadline = inspection_module._hard_deadline

            @contextlib.contextmanager
            def fail_when_deadline_exits(seconds: float) -> Iterator[None]:
                with real_deadline(seconds):
                    yield
                raise AcquisitionError("synthetic deadline context-exit failure")

            with (
                mock.patch.object(
                    inspection_module,
                    "_hard_deadline",
                    side_effect=fail_when_deadline_exits,
                ),
                self.assertRaisesRegex(AcquisitionError, "context-exit failure"),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_mutation_during_final_status_gate_retracts_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, spec = _git_backed_fixture(
                root, _synthetic_payloads()
            )
            target = root / _SLICE_DESTINATION / spec.files[0].path
            real_status = inspection_module._assert_repository_with_new_receipt
            status_calls = 0

            def mutate_after_final_status(
                repo_root: Path,
                *,
                expected_revision: str,
                receipt_relative: str,
            ) -> None:
                nonlocal status_calls
                real_status(
                    repo_root,
                    expected_revision=expected_revision,
                    receipt_relative=receipt_relative,
                )
                status_calls += 1
                if status_calls == 2:
                    target.write_bytes(target.read_bytes() + b"ignored mutation")

            with (
                mock.patch.object(
                    inspection_module,
                    "_assert_repository_with_new_receipt",
                    side_effect=mutate_after_final_status,
                ),
                self.assertRaisesRegex(AcquisitionError, "became unsafe"),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertEqual(status_calls, 2)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_identical_race_winner_receipt_is_never_retracted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            real_publish = inspection_module._write_owned_receipt_atomic
            winner_payload: list[bytes] = []

            def plant_race_winner(
                path: Path,
                payload: bytes,
                *,
                ownership: inspection_module._ReceiptOwnership,
            ) -> inspection_module._ReceiptPublication:
                winner_payload.append(payload)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                descriptor = os.open(path, flags, 0o600)
                try:
                    written = 0
                    while written < len(payload):
                        written += os.write(descriptor, payload[written:])
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                return real_publish(path, payload, ownership=ownership)

            with (
                mock.patch.object(
                    inspection_module,
                    "_write_owned_receipt_atomic",
                    side_effect=plant_race_winner,
                ),
                self.assertRaisesRegex(AcquisitionError, "refusing to overwrite"),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertEqual(len(winner_payload), 1)
            self.assertEqual((root / _RECEIPT_PATH).read_bytes(), winner_payload[0])
            self.assertTrue((root / _CLAIM_PATH).is_file())

    def test_hard_timer_remains_active_through_publication_and_final_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            real_publish = inspection_module._write_owned_receipt_atomic
            real_status = inspection_module._assert_repository_with_new_receipt
            real_owned_receipt = inspection_module._assert_owned_receipt
            observed: list[tuple[str, bool]] = []

            def timer_active() -> bool:
                return signal.getitimer(signal.ITIMER_REAL)[0] > 0

            def observe_publish(
                path: Path,
                payload: bytes,
                *,
                ownership: inspection_module._ReceiptOwnership,
            ) -> inspection_module._ReceiptPublication:
                observed.append(("writer", timer_active()))
                return real_publish(path, payload, ownership=ownership)

            def observe_status(
                repo_root: Path,
                *,
                expected_revision: str,
                receipt_relative: str,
            ) -> None:
                observed.append(("status", timer_active()))
                real_status(
                    repo_root,
                    expected_revision=expected_revision,
                    receipt_relative=receipt_relative,
                )

            def observe_owned_receipt(
                path: Path,
                payload: bytes,
                publication: inspection_module._ReceiptPublication,
            ) -> str:
                observed.append(("receipt", timer_active()))
                return real_owned_receipt(path, payload, publication)

            with (
                mock.patch.object(
                    inspection_module,
                    "_write_owned_receipt_atomic",
                    side_effect=observe_publish,
                ),
                mock.patch.object(
                    inspection_module,
                    "_assert_repository_with_new_receipt",
                    side_effect=observe_status,
                ),
                mock.patch.object(
                    inspection_module,
                    "_assert_owned_receipt",
                    side_effect=observe_owned_receipt,
                ),
            ):
                _run_fixture(root, authorization_path, authorization)
            self.assertEqual([name for name, _ in observed].count("status"), 2)
            self.assertEqual(observed[-1][0], "receipt")
            self.assertTrue(all(active for _, active in observed))

    @unittest.skipUnless(
        hasattr(signal, "pthread_sigmask") and hasattr(signal, "SIGALRM"),
        "requires POSIX signal-mask inspection",
    )
    def test_preblocked_sigalrm_rejects_before_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _synthetic_payloads())
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
            try:
                with self.assertRaisesRegex(AcquisitionError, "SIGALRM is blocked"):
                    _run_fixture(root, authorization_path, authorization)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            self.assertFalse(os.path.lexists(root / _CLAIM_PATH))
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))


class FormatInspectionCliTests(unittest.TestCase):
    def test_argument_error_is_one_structured_json_document(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            status = main([])
        self.assertEqual(status, 1)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["execution_outcome"], "failed")
        self.assertEqual(parsed["scientific_authority"], "none")


if __name__ == "__main__":
    unittest.main()

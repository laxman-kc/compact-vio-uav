from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import tempfile
import types
import unittest
from contextlib import ExitStack
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from unittest import mock

import compact_vio.data.tumvi_real_csv_grammar_probe as probe_module
from compact_vio.data.acquisition import AcquisitionError, ToolIdentity
from compact_vio.data.tumvi_adapter_contract import load_tumvi_adapter_contract
from compact_vio.data.tumvi_adapter_parser import (
    TumviAdapterParserError,
    parse_tumvi_camera_index,
    parse_tumvi_imu_stream,
    parse_tumvi_pose_reference_stream,
    parse_tumvi_stereo_indexes,
)
from compact_vio.data.tumvi_real_csv_grammar_probe import (
    _AUTHORIZATION_ID,
    _AUTHORIZATION_PATH,
    _CAMERA_HEADER,
    _CLAIM_PATH,
    _IMU_HEADER,
    _MAXIMUM_CLAIM_BYTES,
    _MAXIMUM_CSV_COLUMNS,
    _MAXIMUM_CSV_LINE_BYTES,
    _MAXIMUM_CSV_ROWS,
    _MAXIMUM_ELAPSED_SECONDS,
    _MAXIMUM_RECEIPT_BYTES,
    _MINIMUM_FREE_BYTES,
    _PERMITTED_OPERATIONS,
    _POSE_HEADER,
    _POST_PROBE_RESERVE_BYTES,
    _PROHIBITED_OPERATIONS,
    _RECEIPT_PATH,
    _SOURCE_ROOT,
    _SOURCE_SCOPE,
    _SPEC_PATH,
    _TOOL_PATHS,
    EvidenceIdentity,
    ProbeOutputs,
    ProbeSourceFile,
    RealCsvGrammarProbeAuthorization,
    RealCsvGrammarProbeResult,
    RealCsvGrammarProbeSpec,
    _assert_bound_sources,
    _bind_exact_sources_after_claim,
    _expected_evidence,
    _scan_bound_sources,
    load_real_csv_grammar_probe_authorization,
    load_real_csv_grammar_probe_receipt,
    load_real_csv_grammar_probe_spec,
    main,
    run_authorized_real_csv_grammar_probe,
)

_WORKSPACE = Path(__file__).resolve().parents[1]
_FIXED_NOW = datetime(2026, 8, 29, 21, 0, 0, tzinfo=timezone.utc)
_CONSUMED_AUTHORIZATION_ID = "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29"
_CONSUMED_CLAIM_PATH = (
    "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29.claim.json"
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _csv(header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    return (",".join(header) + "\n" + "".join(",".join(row) + "\n" for row in rows)).encode("ascii")


def _valid_payloads() -> dict[str, bytes]:
    camera = _csv(_CAMERA_HEADER, (("1", "1.png"), ("2", "2.png")))
    imu = _csv(
        _IMU_HEADER,
        (
            ("0", "0", "+1.0", "-.5", "2e+3", "4.", ".25"),
            ("3", "1", "2", "3", "4", "5", "6"),
        ),
    )
    pose = _csv(
        _POSE_HEADER,
        (
            ("0", "0", "0", "0", "1", "0", "0", "0"),
            ("3", "1", "2", "3", "1", "0", "0", "0"),
        ),
    )
    return {"cam0": camera, "cam1": camera, "imu": imu, "pose": pose}


def _source_files(payloads: dict[str, bytes]) -> tuple[ProbeSourceFile, ...]:
    paths = {
        "cam0": ("mav0/cam0/data.csv", "dataset-room4_512_16/mav0/cam0/data.csv"),
        "cam1": ("mav0/cam1/data.csv", "dataset-room4_512_16/mav0/cam1/data.csv"),
        "imu": ("mav0/imu0/data.csv", "dataset-room4_512_16/mav0/imu0/data.csv"),
        "pose": ("mav0/mocap0/data.csv", "dataset-room4_512_16/mav0/mocap0/data.csv"),
    }
    return tuple(
        ProbeSourceFile(role, *paths[role], len(payloads[role]), _sha(payloads[role]))
        for role in ("cam0", "cam1", "imu", "pose")
    )


def _write_payload_tree(
    root: Path, payloads: dict[str, bytes], files: tuple[ProbeSourceFile, ...]
) -> None:
    for source in files:
        target = root / source.slice_relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payloads[source.role])


def _scan_payloads(
    payloads: dict[str, bytes],
    *,
    expected_files: tuple[ProbeSourceFile, ...] | None = None,
) -> tuple[probe_module.StreamAggregate, ...]:
    files = expected_files or _source_files(payloads)
    with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
        root = Path(directory)
        _write_payload_tree(root, payloads, files)
        tree = _bind_exact_sources_after_claim(root, files, cleanup=cleanup)
        streams = _scan_bound_sources(tree)
        _assert_bound_sources(tree)
        return streams


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _authorization_document(spec_sha256: str) -> dict[str, object]:
    spec_document = json.loads((_WORKSPACE / _SPEC_PATH).read_text(encoding="utf-8"))
    evidence = {"probe_spec": {"path": _SPEC_PATH, "sha256": spec_sha256}}
    evidence.update(copy.deepcopy(spec_document["source_evidence"]))
    return {
        "authority_basis": {
            "kind": "active_workspace_user_instruction",
            "instruction_summary": "Authorize one reviewed synthetic-fixture test execution only.",
            "captured_at": "2026-08-29T20:00:00Z",
            "identity_authentication": "not_independently_authenticated",
        },
        "authorization_id": _AUTHORIZATION_ID,
        "authorized_at": "2026-08-29T20:00:00Z",
        "execution": {
            "requires_clean_worktree": True,
            "maximum_elapsed_seconds": _MAXIMUM_ELAPSED_SECONDS,
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
        "record_type": "dataset_real_csv_grammar_probe_authorization",
        "retention": {
            "policy": "retain_real_csv_grammar_probe_evidence_until_review",
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
        "scope": "one_use_exact_four_real_csv_grammar_probe_aggregate_only",
        "probe_limits": {
            "source_file_count": 4,
            "source_size_bytes": 3_909_654,
            "maximum_csv_rows_per_file": _MAXIMUM_CSV_ROWS,
            "maximum_csv_line_bytes": _MAXIMUM_CSV_LINE_BYTES,
            "maximum_csv_columns": _MAXIMUM_CSV_COLUMNS,
            "maximum_claim_bytes": _MAXIMUM_CLAIM_BYTES,
            "maximum_receipt_bytes": _MAXIMUM_RECEIPT_BYTES,
            "post_probe_reserve_bytes": _POST_PROBE_RESERVE_BYTES,
        },
        "source_evidence": evidence,
    }


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _copy_exact_tracked_files(root: Path) -> None:
    paths = {_SPEC_PATH, *(identity.path for _, identity in _expected_evidence()), *_TOOL_PATHS}
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_WORKSPACE / relative, target)


def _git_backed_fixture(
    root: Path, payloads: dict[str, bytes]
) -> tuple[Path, RealCsvGrammarProbeAuthorization, RealCsvGrammarProbeSpec]:
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "Synthetic Test")
    _git(root, "config", "user.email", "synthetic@example.invalid")
    (root / ".gitignore").write_text("/data/\n", encoding="utf-8")
    _copy_exact_tracked_files(root)
    spec_bytes = (root / _SPEC_PATH).read_bytes()
    authorization_path = root / _AUTHORIZATION_PATH
    authorization_path.parent.mkdir(parents=True, exist_ok=True)
    authorization_bytes = b"synthetic checked authorization placeholder\n"
    authorization_path.write_bytes(authorization_bytes)
    files = _source_files(payloads)
    _write_payload_tree(root / _SOURCE_ROOT, payloads, files)
    spec = RealCsvGrammarProbeSpec(
        _SPEC_PATH,
        _sha(spec_bytes),
        "tumvi-room4-512-16-real-csv-grammar-probe-v1",
        _expected_evidence(),
        _SOURCE_ROOT,
        _SOURCE_SCOPE,
        files,
    )
    tools = tuple(
        ToolIdentity(relative, _sha((root / relative).read_bytes())) for relative in _TOOL_PATHS
    )
    authorization = RealCsvGrammarProbeAuthorization(
        _AUTHORIZATION_ID,
        _AUTHORIZATION_PATH,
        _sha(authorization_bytes),
        datetime(2026, 8, 29, 20, tzinfo=timezone.utc),
        datetime(2026, 8, 30, 20, tzinfo=timezone.utc),
        EvidenceIdentity(_SPEC_PATH, _sha(spec_bytes)),
        spec,
        _MAXIMUM_ELAPSED_SECONDS,
        _MINIMUM_FREE_BYTES,
        tools,
        datetime(2026, 9, 6, 20, tzinfo=timezone.utc),
        ProbeOutputs(_CLAIM_PATH, _RECEIPT_PATH),
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "synthetic real CSV grammar probe fixture")
    return authorization_path, authorization, spec


@contextlib.contextmanager
def _runner_patches(authorization: RealCsvGrammarProbeAuthorization):
    with (
        mock.patch.object(
            probe_module,
            "load_real_csv_grammar_probe_authorization",
            return_value=authorization,
        ),
        mock.patch.object(probe_module, "_runtime_sources"),
        mock.patch.object(probe_module, "_utc_now", return_value=_FIXED_NOW),
        mock.patch.object(
            probe_module,
            "_disk_usage",
            return_value=types.SimpleNamespace(free=_MINIMUM_FREE_BYTES + 10_000_000),
        ),
    ):
        yield


def _run_fixture(
    root: Path,
    authorization_path: Path,
    authorization: RealCsvGrammarProbeAuthorization,
) -> RealCsvGrammarProbeResult:
    with _runner_patches(authorization):
        return run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)


class ProbeSpecAndAuthorizationTests(unittest.TestCase):
    def test_superseding_operational_identity_is_exact_and_scientific_probe_is_unchanged(
        self,
    ) -> None:
        self.assertEqual(
            _AUTHORIZATION_ID,
            "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-30",
        )
        self.assertEqual(
            _AUTHORIZATION_PATH,
            "governance/datasets/acquisitions/"
            "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-30.authorization.json",
        )
        self.assertEqual(
            _CLAIM_PATH,
            "governance/datasets/acquisitions/"
            "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-30.claim.json",
        )
        self.assertEqual(
            _RECEIPT_PATH,
            "governance/datasets/acquisitions/"
            "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-30.receipt.json",
        )
        self.assertNotEqual(_AUTHORIZATION_ID, _CONSUMED_AUTHORIZATION_ID)
        self.assertNotEqual(_CLAIM_PATH, _CONSUMED_CLAIM_PATH)
        self.assertEqual(
            probe_module._PROBE_ID,
            "tumvi-room4-512-16-real-csv-grammar-probe-v1",
        )
        self.assertEqual(
            probe_module._SPEC_PATH,
            "configs/data/tumvi_room4_512_16_real_csv_grammar_probe_v1.json",
        )

    def test_checked_spec_loads_without_payload_access(self) -> None:
        with mock.patch.object(
            probe_module, "_bind_exact_sources_after_claim", side_effect=AssertionError
        ):
            spec = load_real_csv_grammar_probe_spec(_WORKSPACE / _SPEC_PATH, repo_root=_WORKSPACE)
        self.assertEqual(spec.files, probe_module._expected_sources())
        self.assertEqual(sum(item.source_size_bytes for item in spec.files), 3_909_654)
        self.assertEqual(spec.source_scope, _SOURCE_SCOPE)

    def test_spec_rejects_duplicate_extra_missing_reordered_and_bool_fields(self) -> None:
        checked = json.loads((_WORKSPACE / _SPEC_PATH).read_text(encoding="utf-8"))
        cases: list[tuple[str, object]] = []
        extra = copy.deepcopy(checked)
        extra["extra"] = 1
        cases.append(("extra", extra))
        missing = copy.deepcopy(checked)
        del missing["scope"]
        cases.append(("missing", missing))
        reordered = copy.deepcopy(checked)
        reordered["source"]["files"].reverse()
        cases.append(("reordered", reordered))
        boolean = copy.deepcopy(checked)
        boolean["resource_limits"]["source_file_count"] = True
        cases.append(("boolean", boolean))
        for name, document in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / _SPEC_PATH
                _write_json(path, document)
                with self.assertRaises(AcquisitionError):
                    load_real_csv_grammar_probe_spec(path, repo_root=root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / _SPEC_PATH
            path.parent.mkdir(parents=True)
            path.write_text('{"record_type":"x","record_type":"y"}\n', encoding="utf-8")
            with self.assertRaisesRegex(AcquisitionError, "duplicate"):
                load_real_csv_grammar_probe_spec(path, repo_root=root)

    def test_future_authorization_is_strict_and_does_not_touch_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec_path = root / _SPEC_PATH
            spec_path.parent.mkdir(parents=True)
            shutil.copyfile(_WORKSPACE / _SPEC_PATH, spec_path)
            document = _authorization_document(_sha(spec_path.read_bytes()))
            authorization_path = root / _AUTHORIZATION_PATH
            _write_json(authorization_path, document)
            with mock.patch.object(
                probe_module, "_bind_exact_sources_after_claim", side_effect=AssertionError
            ):
                loaded = load_real_csv_grammar_probe_authorization(
                    authorization_path, repo_root=root
                )
            self.assertEqual(loaded.outputs, ProbeOutputs(_CLAIM_PATH, _RECEIPT_PATH))
            self.assertEqual(loaded.maximum_elapsed_seconds, 600)

    def test_authorization_closes_order_authority_bounds_and_paths(self) -> None:
        mutations = {
            "tool order": lambda value: value["execution"]["tool_files"].reverse(),
            "operation order": lambda value: value["permitted_operations"].reverse(),
            "authority": lambda value: value["scientific_authority"].__setitem__(
                "selects_dataset", True
            ),
            "elapsed bool": lambda value: value["execution"].__setitem__(
                "maximum_elapsed_seconds", True
            ),
            "claim path": lambda value: value["outputs"].__setitem__(
                "claim_path", "data/claim.json"
            ),
            "expiry": lambda value: value.__setitem__("expires_at", "2026-08-30T19:59:59Z"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                spec_path = root / _SPEC_PATH
                spec_path.parent.mkdir(parents=True)
                shutil.copyfile(_WORKSPACE / _SPEC_PATH, spec_path)
                document = _authorization_document(_sha(spec_path.read_bytes()))
                mutate(document)
                path = root / _AUTHORIZATION_PATH
                _write_json(path, document)
                with self.assertRaises(AcquisitionError):
                    load_real_csv_grammar_probe_authorization(path, repo_root=root)

    def test_spec_and_authorization_readers_are_bounded_and_never_follow_links(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        for relative, loader in (
            (_SPEC_PATH, load_real_csv_grammar_probe_spec),
            (_AUTHORIZATION_PATH, load_real_csv_grammar_probe_authorization),
        ):
            with self.subTest(fifo=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                fifo = root / relative
                fifo.parent.mkdir(parents=True)
                os.mkfifo(fifo)
                with (
                    mock.patch.object(
                        probe_module,
                        "_bind_exact_sources_after_claim",
                        side_effect=AssertionError("FIFO checked reader touched payload"),
                    ),
                    self.assertRaisesRegex(AcquisitionError, "regular file"),
                ):
                    loader(fifo, repo_root=root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / _SPEC_PATH
            path.parent.mkdir(parents=True)
            path.write_bytes(b" " * (probe_module._MAXIMUM_SPEC_BYTES + 1))
            with (
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=AssertionError("bounded spec reader touched payload"),
                ),
                self.assertRaisesRegex(AcquisitionError, "bound"),
            ):
                load_real_csv_grammar_probe_spec(path, repo_root=root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            replacement = root / "replacement"
            (replacement / "data").mkdir(parents=True)
            shutil.copyfile(
                _WORKSPACE / _SPEC_PATH,
                replacement / "data" / PurePosixPath(_SPEC_PATH).name,
            )
            os.symlink(replacement, root / "configs")
            with self.assertRaises(AcquisitionError):
                load_real_csv_grammar_probe_spec(root / _SPEC_PATH, repo_root=root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            spec_path = root / _SPEC_PATH
            spec_path.parent.mkdir(parents=True)
            shutil.copyfile(_WORKSPACE / _SPEC_PATH, spec_path)
            external = root / "external.authorization.json"
            _write_json(external, _authorization_document(_sha(spec_path.read_bytes())))
            authorization_path = root / _AUTHORIZATION_PATH
            authorization_path.parent.mkdir(parents=True)
            os.symlink(external, authorization_path)
            with self.assertRaises(AcquisitionError):
                load_real_csv_grammar_probe_authorization(
                    authorization_path,
                    repo_root=root,
                )


class AggregateScannerTests(unittest.TestCase):
    def test_accepts_exact_gate1_grammar_with_constant_memory_accounting(self) -> None:
        streams = _scan_payloads(_valid_payloads())
        self.assertEqual(tuple(item.role for item in streams), ("cam0", "cam1", "imu", "pose"))
        self.assertTrue(all(item.grammar_state == "accepted" for item in streams))
        self.assertTrue(all(item.bytes_read == item.source_size_bytes for item in streams))
        self.assertTrue(all(item.physical_line_count == 3 for item in streams))
        self.assertTrue(all(item.total_data_line_count == 2 for item in streams))
        self.assertTrue(all(item.validated_data_row_count == 2 for item in streams))
        self.assertNotIn("rows", probe_module._GrammarAccumulator.__slots__)

        rows = tuple((str(index), "0", "0", "0", "0", "0", "0") for index in range(20_000))
        payloads = _valid_payloads()
        payloads["imu"] = _csv(_IMU_HEADER, rows)
        large = _scan_payloads(payloads)[2]
        self.assertEqual(large.validated_data_row_count, 20_000)
        self.assertLessEqual(
            probe_module._MAXIMUM_CSV_LINE_BYTES + probe_module._READ_CHUNK_BYTES,
            2 * 1024 * 1024,
        )

    def test_closed_rejection_corpus_has_only_code_and_line(self) -> None:
        base = _valid_payloads()
        camera_header = ",".join(_CAMERA_HEADER).encode()
        cases = {
            "exact_header_mismatch": ("imu", b"bad\n1,0,0,0,0,0,0\n"),
            "carriage_return_forbidden": (
                "imu",
                _csv(_IMU_HEADER, (("1", "0", "0", "0", "0", "0", "0"),)).replace(
                    b"\n", b"\r\n", 1
                ),
            ),
            "nul_forbidden": (
                "imu",
                _csv(_IMU_HEADER, (("1", "0", "0", "0", "0", "0", "0"),)).replace(
                    b",0", b",\x00", 1
                ),
            ),
            "quoting_forbidden": (
                "imu",
                _csv(_IMU_HEADER, (("1", '"0"', "0", "0", "0", "0", "0"),)),
            ),
            "utf8_bom_forbidden": ("imu", b"\xef\xbb\xbf" + base["imu"]),
            "non_ascii_forbidden": ("imu", base["imu"].replace(b"+1.0", b"\xff", 1)),
            "final_line_missing_lf": ("imu", base["imu"][:-1]),
            "blank_data_row": ("imu", ",".join(_IMU_HEADER).encode() + b"\n\n"),
            "comment_data_row": (
                "imu",
                ",".join(_IMU_HEADER).encode() + b"\n#comment\n",
            ),
            "data_row_arity": (
                "imu",
                ",".join(_IMU_HEADER).encode() + b"\n1,0\n",
            ),
            "timestamp_lexeme": (
                "imu",
                _csv(_IMU_HEADER, (("01", "0", "0", "0", "0", "0", "0"),)),
            ),
            "timestamp_range": (
                "imu",
                _csv(
                    _IMU_HEADER,
                    (("9223372036854775808", "0", "0", "0", "0", "0", "0"),),
                ),
            ),
            "timestamp_not_strictly_increasing": (
                "imu",
                _csv(
                    _IMU_HEADER,
                    (
                        ("1", "0", "0", "0", "0", "0", "0"),
                        ("1", "0", "0", "0", "0", "0", "0"),
                    ),
                ),
            ),
            "numeric_lexeme": (
                "imu",
                _csv(_IMU_HEADER, (("1", "NaN", "0", "0", "0", "0", "0"),)),
            ),
            "camera_filename_lexeme": (
                "camera",
                camera_header + b"\n1,../1.png\n",
            ),
            "camera_filename_stem": ("camera", camera_header + b"\n1,2.png\n"),
            "minimum_data_rows": ("imu", ",".join(_IMU_HEADER).encode() + b"\n"),
        }
        for expected_code, (role, payload) in cases.items():
            with self.subTest(code=expected_code):
                payloads = dict(base)
                if role == "camera":
                    payloads["cam0"] = payload
                    payloads["cam1"] = payload
                    observed = _scan_payloads(payloads)[0]
                else:
                    payloads[role] = payload
                    observed = _scan_payloads(payloads)[2 if role == "imu" else 3]
                self.assertEqual(observed.grammar_state, "rejected")
                self.assertEqual(observed.first_violation.code, expected_code)
                serialized = json.dumps(probe_module._stream_document(observed), sort_keys=True)
                self.assertNotIn("NaN", serialized)
                self.assertNotIn("../1.png", serialized)

    def test_resource_limits_are_operational_even_after_grammar_rejection(self) -> None:
        for transport_failure in (
            b"bad\r,,,,,,,,\n",
            b'bad",,,,,,,,\n',
            b"\xef\xbb\xbfbad,,,,,,,,\n",
            b"\xffbad,,,,,,,,\n",
        ):
            with self.subTest(transport_failure=transport_failure[:4]):
                payloads = _valid_payloads()
                payloads["imu"] = transport_failure
                with self.assertRaisesRegex(AcquisitionError, "column bound"):
                    _scan_payloads(payloads)

        payloads = _valid_payloads()
        payloads["imu"] = b"bad-header\n1,0,0,0,0,0,0,0,0\n"
        with self.assertRaisesRegex(AcquisitionError, "column bound"):
            _scan_payloads(payloads)

        payloads = _valid_payloads()
        payloads["imu"] = b"bad-header\n" + b"x" * (_MAXIMUM_CSV_LINE_BYTES + 1) + b"\n"
        with self.assertRaisesRegex(AcquisitionError, "line exceeds"):
            _scan_payloads(payloads)

        payloads = _valid_payloads()
        payloads["imu"] = b"bad-header\n1,0,0,0,0,0,0\n2,0,0,0,0,0,0\n"
        with (
            mock.patch.object(probe_module, "_MAXIMUM_CSV_ROWS", 1),
            self.assertRaisesRegex(AcquisitionError, "row count"),
        ):
            _scan_payloads(payloads)

    def test_stereo_raw_lockstep_precedence_and_simultaneous_eof(self) -> None:
        payloads = _valid_payloads()
        payloads["cam1"] = payloads["cam1"].replace(b"2,2.png", b"2,3.png")
        streams = _scan_payloads(payloads)
        self.assertEqual(streams[0].first_violation.code, "stereo_raw_bytes_mismatch")
        self.assertEqual(streams[1].first_violation.code, "stereo_raw_bytes_mismatch")
        self.assertEqual(streams[0].first_violation.physical_line_number, 3)

        payloads = _valid_payloads()
        bad = b"bad\n1,1.png\n"
        payloads["cam0"] = bad
        payloads["cam1"] = bad.replace(b"1.png", b"2.png")
        streams = _scan_payloads(payloads)
        self.assertEqual(streams[0].first_violation.code, "exact_header_mismatch")
        self.assertEqual(streams[0].check_states["stereo_raw_lockstep"], "fail")

        payloads = _valid_payloads()
        payloads["cam1"] += b"3,3.png\n"
        streams = _scan_payloads(payloads)
        self.assertEqual(streams[0].first_violation.code, "stereo_simultaneous_eof_mismatch")

    def test_source_size_digest_and_stability_fail_operationally(self) -> None:
        payloads = _valid_payloads()
        expected_files = _source_files(payloads)
        changed = dict(payloads)
        changed["imu"] = changed["imu"].replace(b"+1.0", b"+1.1")
        with self.assertRaisesRegex(AcquisitionError, "digest"):
            _scan_payloads(changed, expected_files=expected_files)
        changed = dict(payloads)
        changed["imu"] += b"4,0,0,0,0,0,0\n"
        with self.assertRaisesRegex(AcquisitionError, "size"):
            _scan_payloads(changed, expected_files=expected_files)

    def test_single_pass_reads_each_descriptor_once_through_eof(self) -> None:
        payloads = _valid_payloads()
        files = _source_files(payloads)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            root = Path(directory)
            _write_payload_tree(root, payloads, files)
            tree = _bind_exact_sources_after_claim(root, files, cleanup=cleanup)
            source_descriptors = {item.descriptor for item in tree.sources.values()}
            totals = {descriptor: 0 for descriptor in source_descriptors}
            real_read = os.read

            def observed_read(descriptor: int, count: int) -> bytes:
                chunk = real_read(descriptor, count)
                if descriptor in totals:
                    totals[descriptor] += len(chunk)
                return chunk

            with mock.patch.object(probe_module.os, "read", side_effect=observed_read):
                streams = _scan_bound_sources(tree)
            expected_by_descriptor = {
                tree.sources[role].descriptor: len(payloads[role]) for role in payloads
            }
            self.assertEqual(totals, expected_by_descriptor)
            self.assertTrue(
                all(stream.bytes_read == stream.source_size_bytes for stream in streams)
            )

    def test_no_source_values_are_emitted_or_retained(self) -> None:
        sentinel = "SENSITIVE_314159265358979"
        payloads = _valid_payloads()
        payloads["imu"] = _csv(
            _IMU_HEADER,
            (("1", sentinel, "0", "0", "0", "0", "0"),),
        )
        observed = _scan_payloads(payloads)[2]
        rendered = json.dumps(probe_module._stream_document(observed), sort_keys=True)
        self.assertNotIn(sentinel, rendered)
        self.assertEqual(
            set(probe_module._stream_document(observed)["first_violation"]),
            {
                "code",
                "physical_line_number",
            },
        )


class DescriptorBindingTests(unittest.TestCase):
    def test_repository_bound_source_root_rejects_ancestor_symlink_and_swap(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        payloads = _valid_payloads()
        files = _source_files(payloads)
        source_relative = "data/synthetic-source"
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            parent = Path(directory).resolve()
            repository = parent / "repository"
            repository.mkdir()
            outside = parent / "outside"
            _write_payload_tree(outside / "synthetic-source", payloads, files)
            os.symlink(outside, repository / "data")
            with self.assertRaises(AcquisitionError):
                _bind_exact_sources_after_claim(
                    repository / source_relative,
                    files,
                    cleanup=cleanup,
                    repository_root=repository,
                    source_root_relative=source_relative,
                )

        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            repository = Path(directory).resolve()
            source = repository / source_relative
            _write_payload_tree(source, payloads, files)
            tree = _bind_exact_sources_after_claim(
                source,
                files,
                cleanup=cleanup,
                repository_root=repository,
                source_root_relative=source_relative,
            )
            data = repository / "data"
            moved = repository / "data-moved"
            data.rename(moved)
            _write_payload_tree(repository / source_relative, payloads, files)
            with self.assertRaisesRegex(AcquisitionError, "ancestor identity changed"):
                _assert_bound_sources(tree)

    def test_rejects_symlink_hardlink_fifo_directory_and_symlinked_ancestor(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("POSIX link tests unavailable")
        cases = ("symlink", "hardlink", "fifo", "directory", "ancestor")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payloads = _valid_payloads()
                files = _source_files(payloads)
                _write_payload_tree(root, payloads, files)
                target = root / files[0].slice_relative_path
                if case == "symlink":
                    target.unlink()
                    os.symlink(root / files[1].slice_relative_path, target)
                elif case == "hardlink":
                    target.unlink()
                    os.link(root / files[1].slice_relative_path, target)
                elif case == "fifo":
                    target.unlink()
                    os.mkfifo(target)
                elif case == "directory":
                    target.unlink()
                    target.mkdir()
                else:
                    ancestor = target.parent
                    replacement = root / "replacement"
                    replacement.mkdir()
                    (replacement / "data.csv").write_bytes(payloads["cam0"])
                    shutil.rmtree(ancestor)
                    os.symlink(replacement, ancestor)
                with ExitStack() as cleanup, self.assertRaises(AcquisitionError):
                    _bind_exact_sources_after_claim(root, files, cleanup=cleanup)

    def test_rejects_symlinked_root_without_following_it(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as directory, ExitStack() as cleanup:
            parent = Path(directory)
            real_root = parent / "real"
            payloads = _valid_payloads()
            files = _source_files(payloads)
            _write_payload_tree(real_root, payloads, files)
            link = parent / "source"
            os.symlink(real_root, link)
            with self.assertRaises(AcquisitionError):
                _bind_exact_sources_after_claim(link, files, cleanup=cleanup)

    def test_detects_file_replacement_mutate_restore_hardlink_and_ancestor_swap(self) -> None:
        cases = ("replace", "mutate_restore", "hardlink", "ancestor_swap")
        for case in cases:
            with (
                self.subTest(case=case),
                tempfile.TemporaryDirectory() as directory,
                ExitStack() as cleanup,
            ):
                root = Path(directory)
                payloads = _valid_payloads()
                files = _source_files(payloads)
                _write_payload_tree(root, payloads, files)
                tree = _bind_exact_sources_after_claim(root, files, cleanup=cleanup)
                target = root / files[0].slice_relative_path
                original = target.read_bytes()
                if case == "replace":
                    replacement = target.with_name("replacement.csv")
                    replacement.write_bytes(original)
                    os.replace(replacement, target)
                elif case == "mutate_restore":
                    target.write_bytes(original[:-1] + b"X")
                    target.write_bytes(original)
                elif case == "hardlink":
                    os.link(target, target.with_name("extra-link.csv"))
                else:
                    ancestor = target.parent
                    moved = ancestor.with_name("cam0-moved")
                    ancestor.rename(moved)
                    ancestor.mkdir()
                    (ancestor / target.name).write_bytes(original)
                with self.assertRaisesRegex(AcquisitionError, "identity changed"):
                    _assert_bound_sources(tree)

    def test_no_images_dso_archive_model_or_network_modules_are_reachable(self) -> None:
        source = (_WORKSPACE / probe_module.__file__).read_text(encoding="utf-8")
        forbidden_imports = (
            "compact_vio.data.euroc",
            "compact_vio.learning",
            "PIL",
            "numpy",
            "torch",
            "requests",
            "urllib",
        )
        self.assertFalse(any(item in source for item in forbidden_imports))
        self.assertNotIn("archive.py", source)

    def test_checked_json_detects_same_inode_mutate_restore_at_path_truth_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "checked.json"
            original = b'{"safe":true}\n'
            target.write_bytes(original)
            real_stat = os.stat
            mutated = False

            def mutate_then_stat(
                path: os.PathLike[str] | str,
                *args: object,
                **kwargs: object,
            ) -> os.stat_result:
                nonlocal mutated
                if path == target.name and kwargs.get("dir_fd") is not None and not mutated:
                    mutated = True
                    target.write_bytes(original[:-2] + b"X\n")
                    target.write_bytes(original)
                return real_stat(path, *args, **kwargs)

            with (
                mock.patch.object(probe_module.os, "stat", side_effect=mutate_then_stat),
                self.assertRaisesRegex(AcquisitionError, "path identity changed"),
            ):
                probe_module._read_single_link_json(
                    target,
                    maximum_bytes=1024,
                    field="synthetic checked JSON",
                )

    def test_checked_repo_read_detects_ancestor_swap_during_leaf_revalidation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            target = root / "one" / "two" / "checked.json"
            target.parent.mkdir(parents=True)
            original = b'{"safe":true}\n'
            target.write_bytes(original)
            real_stat = os.stat
            swapped = False

            def swap_then_stat(
                path: os.PathLike[str] | str,
                *args: object,
                **kwargs: object,
            ) -> os.stat_result:
                nonlocal swapped
                if path == target.name and kwargs.get("dir_fd") is not None and not swapped:
                    swapped = True
                    ancestor = target.parent
                    moved = ancestor.with_name("two-moved")
                    ancestor.rename(moved)
                    ancestor.mkdir()
                    (ancestor / target.name).write_bytes(original)
                return real_stat(path, *args, **kwargs)

            with (
                mock.patch.object(probe_module.os, "stat", side_effect=swap_then_stat),
                self.assertRaisesRegex(AcquisitionError, "ancestor identity changed"),
            ):
                probe_module._read_repo_bytes(
                    root,
                    "one/two/checked.json",
                    expected=original,
                    maximum_bytes=1024,
                    field="synthetic tracked file",
                )


class Gate2DifferentialAndFreezeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_tumvi_adapter_contract(
            _WORKSPACE / "configs/data/tumvi_room4_512_16_adapter_contract_v1.json",
            repo_root=_WORKSPACE,
        )

    def _gate2_accepts(self, role: str, payload: bytes) -> bool:
        size = len(payload)
        digest = _sha(payload)
        try:
            if role in ("cam0", "cam1"):
                parse_tumvi_camera_index(
                    io.BytesIO(payload),
                    contract=self.contract,
                    stream_role=role,
                    source_path=f"mav0/{role}/data.csv",
                    expected_source_size_bytes=size,
                    expected_source_sha256=digest,
                )
            elif role == "imu":
                parse_tumvi_imu_stream(
                    io.BytesIO(payload),
                    contract=self.contract,
                    source_path="mav0/imu0/data.csv",
                    expected_source_size_bytes=size,
                    expected_source_sha256=digest,
                )
            else:
                parse_tumvi_pose_reference_stream(
                    io.BytesIO(payload),
                    contract=self.contract,
                    source_path="mav0/mocap0/data.csv",
                    expected_source_size_bytes=size,
                    expected_source_sha256=digest,
                )
        except TumviAdapterParserError:
            return False
        return True

    def test_valid_and_rejection_corpus_matches_gate2_synthetic_oracle(self) -> None:
        base = _valid_payloads()
        cases = [
            ("imu", base["imu"], True),
            ("pose", base["pose"], True),
            ("cam0", base["cam0"], True),
            ("imu", base["imu"].replace(b"+1.0", b"NaN", 1), False),
            ("imu", base["imu"].replace(b"\n0,0,+1.0", b"\n00,0,+1.0", 1), False),
            ("pose", base["pose"].replace(b"q_RS_z []", b"wrong", 1), False),
            ("cam0", base["cam0"].replace(b"1.png", b"2.png", 1), False),
            ("cam0", base["cam0"][:-1], False),
        ]
        for role, payload, expected in cases:
            with self.subTest(role=role, digest=_sha(payload)):
                payloads = dict(base)
                payloads[role] = payload
                if role == "cam0":
                    payloads["cam1"] = payload
                observed_index = {"cam0": 0, "cam1": 1, "imu": 2, "pose": 3}[role]
                probe_accepts = _scan_payloads(payloads)[observed_index].grammar_state == "accepted"
                self.assertEqual(probe_accepts, expected)
                self.assertEqual(self._gate2_accepts(role, payload), expected)

    def test_stereo_acceptance_matches_gate2_and_real_hash_denylist_remains_frozen(self) -> None:
        camera = _valid_payloads()["cam0"]
        batch = parse_tumvi_stereo_indexes(
            io.BytesIO(camera),
            io.BytesIO(camera),
            contract=self.contract,
            cam0_source_path="mav0/cam0/data.csv",
            cam1_source_path="mav0/cam1/data.csv",
            cam0_expected_source_size_bytes=len(camera),
            cam1_expected_source_size_bytes=len(camera),
            cam0_expected_source_sha256=_sha(camera),
            cam1_expected_source_sha256=_sha(camera),
        )
        self.assertEqual(len(batch.rows), 2)
        self.assertTrue(
            all(item.grammar_state == "accepted" for item in _scan_payloads(_valid_payloads())[:2])
        )
        self.assertEqual(
            _sha((_WORKSPACE / "src/compact_vio/data/tumvi_adapter_parser.py").read_bytes()),
            "4d5186a9559a4c111edda6df3d49a1484952ab6028a9269904ce4577efdc99e1",
        )
        self.assertEqual(
            _sha((_WORKSPACE / "src/compact_vio/data/tumvi_adapter_contract.py").read_bytes()),
            "26a018504568c213dfa94dca9988544bd3bc7a5ce28770a30b932c9b0f25bf20",
        )
        self.assertEqual(
            _sha((_WORKSPACE / "src/compact_vio/data/__init__.py").read_bytes()),
            "c3a6a55891323874481b1877fd703ec401cd601d0dd340b72c16d2a0463c8fa5",
        )
        expected_hashes = {item.source_sha256 for item in probe_module._expected_sources()}
        for real_hash in (
            "feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67",
            "4249d4036b3c03c55b709f6f634d975d024999fb017ab3539cfa71580793a3be",
            "073a3e957efa8ff638ea41402cac9654b40897631d566a3ffee090208597db2a",
        ):
            self.assertIn(real_hash, expected_hashes)


class GitBackedProbeRunnerTests(unittest.TestCase):
    def test_tracked_consumed_claim_cannot_collide_with_superseding_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            consumed_claim = root / _CONSUMED_CLAIM_PATH
            consumed_claim.parent.mkdir(parents=True, exist_ok=True)
            consumed_bytes = b'{"synthetic_incident":"preserve-no-retry"}\n'
            consumed_claim.write_bytes(consumed_bytes)
            _git(root, "add", _CONSUMED_CLAIM_PATH)
            _git(root, "commit", "-qm", "preserve synthetic consumed claim")

            result = _run_fixture(root, authorization_path, authorization)

            self.assertEqual(result.grammar_outcome, "accepts_frozen_gate1_grammar")
            self.assertEqual(consumed_claim.read_bytes(), consumed_bytes)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertTrue((root / _RECEIPT_PATH).is_file())
            self.assertNotEqual(consumed_claim, root / _CLAIM_PATH)

    def test_mid_truth_gate_head_swap_is_rejected_against_entry_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            _, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            expected_revision = _git(root, "rev-parse", "HEAD")
            _git(root, "commit", "--allow-empty", "-qm", "synthetic second revision")
            replacement_revision = _git(root, "rev-parse", "HEAD")
            _git(root, "update-ref", "HEAD", expected_revision)
            real_check = probe_module._assert_tracked_gate3_bytes
            checks = 0

            def swap_head_after_first_check(*args: object, **kwargs: object) -> None:
                nonlocal checks
                real_check(*args, **kwargs)
                checks += 1
                if checks == 1:
                    _git(root, "update-ref", "HEAD", replacement_revision)

            with (
                mock.patch.object(
                    probe_module,
                    "_assert_tracked_gate3_bytes",
                    side_effect=swap_head_after_first_check,
                ),
                mock.patch.object(probe_module, "_runtime_sources"),
                self.assertRaisesRegex(AcquisitionError, "revision changed"),
            ):
                probe_module._assert_repository_state(
                    root,
                    authorization,
                    expected_revision=expected_revision,
                    expected_outputs=(),
                )

    def test_success_claim_precedes_first_open_receipt_is_aggregate_and_retry_is_zero_read(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            real_bind = probe_module._bind_exact_sources_after_claim
            bind_calls = 0

            def claim_ordered_bind(*args: object, **kwargs: object) -> object:
                nonlocal bind_calls
                bind_calls += 1
                claim_path = root / _CLAIM_PATH
                self.assertTrue(claim_path.is_file())
                self.assertGreater(claim_path.stat().st_size, 0)
                return real_bind(*args, **kwargs)

            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=claim_ordered_bind,
                ),
            ):
                result = run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            self.assertEqual(bind_calls, 1)
            self.assertEqual(result.grammar_outcome, "accepts_frozen_gate1_grammar")
            receipt = json.loads((root / _RECEIPT_PATH).read_text(encoding="utf-8"))
            self.assertEqual(receipt["execution_outcome"], "completed")
            self.assertEqual(receipt["scientific_authority"], "none")
            self.assertTrue(all(value is False for value in receipt["readiness"].values()))
            rendered = json.dumps(receipt, sort_keys=True)
            for prohibited_value in ("+1.0", "1.png", "#timestamp [ns]", "q_RS_w []"):
                self.assertNotIn(prohibited_value, rendered)
            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=AssertionError("retry opened payload"),
                ) as bind,
                self.assertRaises(AcquisitionError),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            bind.assert_not_called()

    def test_grammar_rejection_is_completed_with_no_source_value_leakage(self) -> None:
        sentinel = "SENSITIVE_TOKEN_8675309"
        payloads = _valid_payloads()
        payloads["imu"] = _csv(
            _IMU_HEADER,
            (("1", sentinel, "0", "0", "0", "0", "0"),),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, payloads)
            result = _run_fixture(root, authorization_path, authorization)
            self.assertEqual(result.grammar_outcome, "rejects_frozen_gate1_grammar")
            receipt_bytes = (root / _RECEIPT_PATH).read_bytes()
            self.assertNotIn(sentinel.encode(), receipt_bytes)
            receipt = json.loads(receipt_bytes)
            imu = receipt["grammar"]["streams"][2]
            self.assertEqual(
                imu["first_violation"],
                {
                    "code": "numeric_lexeme",
                    "physical_line_number": 2,
                },
            )
            self.assertEqual(imu["grammar_state"], "rejected")

    def test_preclaim_git_capacity_expiry_timer_and_existing_output_fail_with_zero_reads(
        self,
    ) -> None:
        cases = ("git", "capacity", "expiry", "existing", "blocked_timer", "preexisting_timer")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
                if case == "git":
                    (_WORKSPACE / "README.md").exists()  # no fixture mutation through source paths
                    (root / ".gitignore").write_text("/data/\nchanged\n", encoding="utf-8")
                elif case == "expiry":
                    authorization = replace(
                        authorization,
                        expires_at=datetime(2026, 8, 29, 20, 30, tzinfo=timezone.utc),
                    )
                elif case == "existing":
                    existing = root / _CLAIM_PATH
                    existing.parent.mkdir(parents=True, exist_ok=True)
                    existing.write_text("existing\n", encoding="utf-8")

                patches: list[contextlib.AbstractContextManager[object]] = [
                    mock.patch.object(
                        probe_module,
                        "load_real_csv_grammar_probe_authorization",
                        return_value=authorization,
                    ),
                    mock.patch.object(probe_module, "_runtime_sources"),
                    mock.patch.object(probe_module, "_utc_now", return_value=_FIXED_NOW),
                    mock.patch.object(
                        probe_module,
                        "_bind_exact_sources_after_claim",
                        side_effect=AssertionError("preclaim payload access"),
                    ),
                ]
                if case == "capacity":
                    patches.append(
                        mock.patch.object(
                            probe_module,
                            "_disk_usage",
                            return_value=types.SimpleNamespace(free=1),
                        )
                    )
                else:
                    patches.append(
                        mock.patch.object(
                            probe_module,
                            "_disk_usage",
                            return_value=types.SimpleNamespace(
                                free=_MINIMUM_FREE_BYTES + 10_000_000
                            ),
                        )
                    )
                previous_mask: set[signal.Signals] | None = None
                previous_timer: tuple[float, float] | None = None
                if case == "blocked_timer":
                    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
                if case == "preexisting_timer":
                    previous_timer = signal.getitimer(signal.ITIMER_REAL)
                    signal.setitimer(signal.ITIMER_REAL, 30)
                try:
                    with ExitStack() as stack:
                        for patcher in patches:
                            stack.enter_context(patcher)
                        with self.assertRaises(AcquisitionError):
                            run_authorized_real_csv_grammar_probe(
                                authorization_path, repo_root=root
                            )
                finally:
                    if previous_mask is not None:
                        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                    if previous_timer is not None:
                        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
                if case not in ("existing",):
                    self.assertFalse(os.path.lexists(root / _CLAIM_PATH))
                self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_delayed_output_binding_rechecks_true_remaining_time_before_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            real_binding = probe_module._bound_probe_output_parent
            clock = [0.0]

            @contextlib.contextmanager
            def delayed_binding(*args: object, **kwargs: object):
                with real_binding(*args, **kwargs) as binding:
                    clock[0] = _MAXIMUM_ELAPSED_SECONDS + 1.0
                    yield binding

            with (
                _runner_patches(authorization),
                mock.patch.object(probe_module.time, "monotonic", side_effect=lambda: clock[0]),
                mock.patch.object(
                    probe_module,
                    "_bound_probe_output_parent",
                    side_effect=delayed_binding,
                ),
                mock.patch.object(
                    probe_module,
                    "_write_new_atomic",
                    side_effect=AssertionError("expired output binding published a claim"),
                ) as claim,
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=AssertionError("expired output binding opened payload"),
                ) as bind,
                self.assertRaises(AcquisitionError),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            claim.assert_not_called()
            bind.assert_not_called()
            self.assertFalse(os.path.lexists(root / _CLAIM_PATH))

    def test_deadline_exit_failure_retracts_owned_receipt_but_preserves_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())

            @contextlib.contextmanager
            def fail_on_exit(seconds: float):
                del seconds
                yield
                raise AcquisitionError("synthetic deadline teardown failure")

            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module,
                    "_hard_deadline",
                    side_effect=fail_on_exit,
                ),
                self.assertRaisesRegex(AcquisitionError, "deadline teardown failure"),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_rollback_unlinks_owned_receipt_name_despite_external_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            extra_link = root / "synthetic-receipt-extra-link"

            def link_then_fail(*args: object, **kwargs: object) -> str:
                del args, kwargs
                os.link(root / _RECEIPT_PATH, extra_link)
                raise AcquisitionError("synthetic post-publication failure")

            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module,
                    "_assert_owned_receipt",
                    side_effect=link_then_fail,
                ),
                self.assertRaisesRegex(AcquisitionError, "post-publication failure"),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))
            self.assertTrue(extra_link.is_file())
            self.assertEqual(extra_link.stat().st_nlink, 1)

    def test_staged_receipt_cleanup_failure_still_retracts_published_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            real_unlink_staged = probe_module._unlink_exact_staged

            def fail_receipt_staged_cleanup(*args: object, **kwargs: object) -> None:
                if kwargs.get("field") == "probe receipt":
                    raise AcquisitionError("synthetic staged cleanup failure")
                real_unlink_staged(*args, **kwargs)

            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module,
                    "_unlink_exact_staged",
                    side_effect=fail_receipt_staged_cleanup,
                ),
                self.assertRaisesRegex(AcquisitionError, "staged cleanup failure"),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_claim_race_and_postclaim_failure_consume_without_payload_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            real_write = probe_module._write_new_atomic

            def lose_claim_race(
                path: Path,
                payload: bytes,
                *,
                parent_binding: probe_module._BoundRepoParent,
            ) -> str:
                real_write(path, payload, parent_binding=parent_binding)
                return real_write(path, payload, parent_binding=parent_binding)

            with (
                _runner_patches(authorization),
                mock.patch.object(probe_module, "_write_new_atomic", side_effect=lose_claim_race),
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=AssertionError("claim loser opened payload"),
                ) as bind,
                self.assertRaises(AcquisitionError),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            bind.assert_not_called()
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_output_parent_swap_after_claim_is_detected_before_payload_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            real_claim = probe_module._write_new_atomic

            def publish_then_swap_parent(
                path: Path,
                payload: bytes,
                *,
                parent_binding: probe_module._BoundRepoParent,
            ) -> str:
                digest = real_claim(path, payload, parent_binding=parent_binding)
                parent = path.parent
                moved = parent.with_name("acquisitions-moved")
                parent.rename(moved)
                parent.mkdir()
                return digest

            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module,
                    "_write_new_atomic",
                    side_effect=publish_then_swap_parent,
                ),
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=AssertionError("output-parent race opened payload"),
                ) as bind,
                self.assertRaises(AcquisitionError),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            bind.assert_not_called()
            self.assertFalse(os.path.lexists(root / _CLAIM_PATH))
            self.assertTrue(
                (
                    root
                    / "governance/datasets/acquisitions-moved"
                    / PurePosixPath(_CLAIM_PATH).name
                ).is_file()
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=AcquisitionError("synthetic postclaim failure"),
                ),
                self.assertRaisesRegex(AcquisitionError, "postclaim"),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            self.assertTrue((root / _CLAIM_PATH).is_file())
            self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_hash_and_source_mutation_are_operational_and_consume_claim(self) -> None:
        cases = ("hash", "append", "restore")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authorization_path, authorization, spec = _git_backed_fixture(
                    root, _valid_payloads()
                )
                target = root / _SOURCE_ROOT / spec.files[2].slice_relative_path
                original = target.read_bytes()
                if case == "hash":
                    target.write_bytes(original.replace(b"+1.0", b"+1.1", 1))
                    patches = contextlib.nullcontext()
                elif case == "append":
                    target.write_bytes(original + b"4,0,0,0,0,0,0\n")
                    patches = contextlib.nullcontext()
                else:
                    real_scan = probe_module._scan_bound_sources

                    def mutate_restore(
                        tree: object,
                        *,
                        scan: object = real_scan,
                        target_path: Path = target,
                        original_bytes: bytes = original,
                    ) -> object:
                        result = scan(tree)
                        target_path.write_bytes(original_bytes[:-1] + b"X")
                        target_path.write_bytes(original_bytes)
                        return result

                    patches = mock.patch.object(
                        probe_module, "_scan_bound_sources", side_effect=mutate_restore
                    )
                with (
                    _runner_patches(authorization),
                    patches,
                    self.assertRaises(AcquisitionError),
                ):
                    run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
                self.assertTrue((root / _CLAIM_PATH).is_file())
                self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_final_claim_source_and_head_mutations_retract_owned_receipt(self) -> None:
        cases = ("claim", "source", "head")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authorization_path, authorization, spec = _git_backed_fixture(
                    root, _valid_payloads()
                )
                real_publish = probe_module._write_owned_receipt_atomic

                def publish_then_mutate(
                    path: Path,
                    payload: bytes,
                    *,
                    ownership: probe_module._ReceiptOwnership,
                    parent_binding: probe_module._BoundRepoParent,
                    publish: object = real_publish,
                    mutation: str = case,
                    fixture_root: Path = root,
                    fixture_spec: RealCsvGrammarProbeSpec = spec,
                ) -> probe_module._ReceiptPublication:
                    publication = publish(
                        path,
                        payload,
                        ownership=ownership,
                        parent_binding=parent_binding,
                    )
                    if mutation == "claim":
                        (fixture_root / _CLAIM_PATH).write_text("changed\n", encoding="utf-8")
                    elif mutation == "source":
                        target = (
                            fixture_root / _SOURCE_ROOT / fixture_spec.files[0].slice_relative_path
                        )
                        target.write_bytes(target.read_bytes())
                    else:
                        target = (
                            fixture_root
                            / dict(fixture_spec.source_evidence)["format_inspection_report"].path
                        )
                        target.write_text("changed tracked evidence\n", encoding="utf-8")
                    return publication

                with (
                    _runner_patches(authorization),
                    mock.patch.object(
                        probe_module,
                        "_write_owned_receipt_atomic",
                        side_effect=publish_then_mutate,
                    ),
                    self.assertRaises(AcquisitionError),
                ):
                    run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
                self.assertTrue((root / _CLAIM_PATH).is_file())
                self.assertFalse(os.path.lexists(root / _RECEIPT_PATH))

    def test_identical_foreign_receipt_is_never_retracted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            real_publish = probe_module._write_owned_receipt_atomic
            winner: list[bytes] = []

            def plant_winner(
                path: Path,
                payload: bytes,
                *,
                ownership: probe_module._ReceiptOwnership,
                parent_binding: probe_module._BoundRepoParent,
            ) -> probe_module._ReceiptPublication:
                winner.append(payload)
                path.write_bytes(payload)
                return real_publish(
                    path,
                    payload,
                    ownership=ownership,
                    parent_binding=parent_binding,
                )

            with (
                _runner_patches(authorization),
                mock.patch.object(
                    probe_module, "_write_owned_receipt_atomic", side_effect=plant_winner
                ),
                self.assertRaisesRegex(AcquisitionError, "overwrite"),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            self.assertEqual((root / _RECEIPT_PATH).read_bytes(), winner[0])

    def test_hard_timer_covers_claim_scan_receipt_and_final_gates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            real_claim = probe_module._write_new_atomic
            real_scan = probe_module._scan_bound_sources
            real_receipt = probe_module._write_owned_receipt_atomic
            real_final = probe_module._assert_owned_receipt
            observed: list[tuple[str, bool]] = []

            def timer_active(name: str) -> None:
                observed.append((name, signal.getitimer(signal.ITIMER_REAL)[0] > 0))

            def claim(*args: object, **kwargs: object) -> str:
                timer_active("claim")
                return real_claim(*args, **kwargs)

            def scan(*args: object, **kwargs: object) -> object:
                timer_active("scan")
                return real_scan(*args, **kwargs)

            def receipt(*args: object, **kwargs: object) -> object:
                timer_active("receipt")
                return real_receipt(*args, **kwargs)

            def final(*args: object, **kwargs: object) -> str:
                timer_active("final")
                return real_final(*args, **kwargs)

            with (
                _runner_patches(authorization),
                mock.patch.object(probe_module, "_write_new_atomic", side_effect=claim),
                mock.patch.object(probe_module, "_scan_bound_sources", side_effect=scan),
                mock.patch.object(probe_module, "_write_owned_receipt_atomic", side_effect=receipt),
                mock.patch.object(probe_module, "_assert_owned_receipt", side_effect=final),
            ):
                run_authorized_real_csv_grammar_probe(authorization_path, repo_root=root)
            self.assertEqual({name for name, _ in observed}, {"claim", "scan", "receipt", "final"})
            self.assertTrue(all(active for _, active in observed))

    def test_receipt_publication_masks_signals_and_prearms_ownership_before_link(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "receipt.json"
            ownership = probe_module._ReceiptOwnership()
            real_link = os.link
            link_observation: list[tuple[set[signal.Signals], object]] = []

            def observed_link(*args: object, **kwargs: object) -> None:
                mask = signal.pthread_sigmask(signal.SIG_BLOCK, set())
                link_observation.append((set(mask), ownership.publication))
                real_link(*args, **kwargs)

            with mock.patch.object(probe_module.os, "link", side_effect=observed_link):
                publication = probe_module._write_owned_receipt_atomic(
                    target, b'{"safe":true}\n', ownership=ownership
                )
            self.assertEqual(len(link_observation), 1)
            blocked, before_publication = link_observation[0]
            self.assertEqual(before_publication, publication)
            self.assertTrue({signal.SIGALRM, signal.SIGINT, signal.SIGTERM} <= blocked)
            self.assertEqual(ownership.publication, publication)

    def test_receipt_publication_prearms_ownership_before_unmasked_signal_after_link(
        self,
    ) -> None:
        if not hasattr(signal, "SIGHUP"):
            self.skipTest("SIGHUP unavailable")

        class SyntheticHangup(Exception):
            pass

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory).resolve() / "receipt.json"
            ownership = probe_module._ReceiptOwnership()
            real_link = os.link

            def link_then_signal(*args: object, **kwargs: object) -> None:
                real_link(*args, **kwargs)
                os.kill(os.getpid(), signal.SIGHUP)

            def raise_hangup(signum: int, frame: object) -> None:
                del signum, frame
                raise SyntheticHangup

            previous_handler = signal.signal(signal.SIGHUP, raise_hangup)
            try:
                with (
                    mock.patch.object(probe_module.os, "link", side_effect=link_then_signal),
                    self.assertRaises(SyntheticHangup),
                    probe_module._rollback_owned_receipt_on_failure(target, ownership),
                ):
                    probe_module._write_owned_receipt_atomic(
                        target,
                        b'{"safe":true}\n',
                        ownership=ownership,
                    )
            finally:
                signal.signal(signal.SIGHUP, previous_handler)
            self.assertIsNotNone(ownership.publication)
            self.assertFalse(os.path.lexists(target))

    def test_checked_receipt_loads_without_payload_and_rejects_forged_truth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
            _run_fixture(root, authorization_path, authorization)
            with (
                mock.patch.object(
                    probe_module,
                    "load_real_csv_grammar_probe_authorization",
                    return_value=authorization,
                ),
                mock.patch.object(
                    probe_module,
                    "_bind_exact_sources_after_claim",
                    side_effect=AssertionError("receipt loader opened payload"),
                ),
            ):
                checked = load_real_csv_grammar_probe_receipt(root / _RECEIPT_PATH, repo_root=root)
            self.assertEqual(checked.grammar_outcome, "accepts_frozen_gate1_grammar")
            self.assertEqual(len(checked.streams), 4)

            receipt_path = root / _RECEIPT_PATH
            original = json.loads(receipt_path.read_text(encoding="utf-8"))

            def forge_camera_counts(value: dict[str, object]) -> None:
                streams = value["grammar"]["streams"]
                for camera in streams[:2]:
                    camera["physical_line_count"] = _MAXIMUM_CSV_ROWS + 1
                    camera["total_data_line_count"] = _MAXIMUM_CSV_ROWS
                    camera["validated_data_row_count"] = _MAXIMUM_CSV_ROWS

            def forge_impossible_camera_transitions(value: dict[str, object]) -> None:
                value["grammar"]["grammar_outcome"] = "rejects_frozen_gate1_grammar"
                streams = value["grammar"]["streams"]
                for camera in streams[:2]:
                    camera["grammar_state"] = "rejected"
                    camera["validated_data_row_count"] = 0
                    camera["first_violation"] = {
                        "code": "data_row_arity",
                        "physical_line_number": 2,
                    }
                    camera["check_states"]["row_arity"] = "fail"

            def forge_camera_transport_location(
                value: dict[str, object],
                *,
                code: str,
                line_number: int,
                validated_rows: int,
            ) -> None:
                value["grammar"]["grammar_outcome"] = "rejects_frozen_gate1_grammar"
                streams = value["grammar"]["streams"]
                for camera in streams[:2]:
                    camera["grammar_state"] = "rejected"
                    camera["validated_data_row_count"] = validated_rows
                    camera["first_violation"] = {
                        "code": code,
                        "physical_line_number": line_number,
                    }
                    camera["check_states"] = {
                        name: "not_reached" for name in camera["check_states"]
                    }
                    camera["check_states"].update(
                        {
                            "source_identity": "pass",
                            "exact_header": "pass",
                            "line_transport": "fail",
                            "stereo_raw_lockstep": "pass",
                        }
                    )

            for name, mutate in {
                "unknown code": lambda value: value["grammar"]["streams"][0].update(
                    {
                        "grammar_state": "rejected",
                        "first_violation": {
                            "code": "source_value_8675309",
                            "physical_line_number": 2,
                        },
                        "check_states": {
                            **value["grammar"]["streams"][0]["check_states"],
                            "role_lexemes": "fail",
                        },
                    }
                ),
                "nan elapsed": lambda value: value["execution"].__setitem__(
                    "elapsed_seconds_at_receipt_preparation", float("nan")
                ),
                "capacity": lambda value: value["capacity"].__setitem__(
                    "free_bytes_before_receipt", 1
                ),
                "chronology": lambda value: value.__setitem__(
                    "receipt_prepared_at", "2026-08-29T19:59:59Z"
                ),
                "readiness": lambda value: value["readiness"].__setitem__("adapter_ready", True),
                "source-size impossible counts": forge_camera_counts,
                "impossible check transitions": forge_impossible_camera_transitions,
                "transport violation after EOF": lambda value: forge_camera_transport_location(
                    value,
                    code="carriage_return_forbidden",
                    line_number=4,
                    validated_rows=2,
                ),
                "missing LF before final line": lambda value: forge_camera_transport_location(
                    value,
                    code="final_line_missing_lf",
                    line_number=2,
                    validated_rows=0,
                ),
            }.items():
                with self.subTest(name=name):
                    document = copy.deepcopy(original)
                    mutate(document)
                    _write_json(receipt_path, document)
                    with (
                        mock.patch.object(
                            probe_module,
                            "load_real_csv_grammar_probe_authorization",
                            return_value=authorization,
                        ),
                        self.assertRaises(AcquisitionError),
                    ):
                        load_real_csv_grammar_probe_receipt(receipt_path, repo_root=root)
            _write_json(receipt_path, original)

    def test_checked_receipt_rejects_hardlink_and_symlink_leaves_without_payload(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("POSIX links unavailable")
        for kind in ("receipt_hardlink", "claim_hardlink", "receipt_symlink", "claim_symlink"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                authorization_path, authorization, _ = _git_backed_fixture(root, _valid_payloads())
                _run_fixture(root, authorization_path, authorization)
                target = root / (_RECEIPT_PATH if kind.startswith("receipt") else _CLAIM_PATH)
                if kind.endswith("hardlink"):
                    os.link(target, target.with_name(target.name + ".link"))
                else:
                    replacement = target.with_name(target.name + ".real")
                    target.rename(replacement)
                    os.symlink(replacement, target)
                with (
                    mock.patch.object(
                        probe_module,
                        "load_real_csv_grammar_probe_authorization",
                        return_value=authorization,
                    ),
                    mock.patch.object(
                        probe_module,
                        "_bind_exact_sources_after_claim",
                        side_effect=AssertionError("checked loader opened payload"),
                    ),
                    self.assertRaises(AcquisitionError),
                ):
                    load_real_csv_grammar_probe_receipt(root / _RECEIPT_PATH, repo_root=root)

    def test_checked_receipt_round_trips_early_grammar_then_late_stereo_failure(self) -> None:
        payloads = _valid_payloads()
        payloads["cam0"] = b"bad\n1,1.png\n"
        payloads["cam1"] = b"bad\n1,2.png\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, payloads)
            _run_fixture(root, authorization_path, authorization)
            with mock.patch.object(
                probe_module,
                "load_real_csv_grammar_probe_authorization",
                return_value=authorization,
            ):
                checked = load_real_csv_grammar_probe_receipt(root / _RECEIPT_PATH, repo_root=root)
            for camera in checked.streams[:2]:
                self.assertEqual(camera.first_violation.code, "exact_header_mismatch")
                self.assertEqual(camera.check_states["exact_header"], "fail")
                self.assertEqual(camera.check_states["stereo_raw_lockstep"], "fail")

    def test_checked_receipt_round_trips_early_rejection_with_unterminated_tails(self) -> None:
        payloads = _valid_payloads()
        payloads["cam0"] = b"bad-header\nunterminated-camera-zero"
        payloads["cam1"] = b"bad-header\nunterminated-camera-one"
        payloads["imu"] = b"bad-header\nunterminated-imu"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            authorization_path, authorization, _ = _git_backed_fixture(root, payloads)
            _run_fixture(root, authorization_path, authorization)
            with mock.patch.object(
                probe_module,
                "load_real_csv_grammar_probe_authorization",
                return_value=authorization,
            ):
                checked = load_real_csv_grammar_probe_receipt(
                    root / _RECEIPT_PATH,
                    repo_root=root,
                )
            for camera in checked.streams[:2]:
                self.assertEqual(camera.first_violation.code, "exact_header_mismatch")
                self.assertEqual(camera.check_states["exact_header"], "fail")
                self.assertEqual(camera.check_states["line_transport"], "not_reached")
                self.assertEqual(camera.check_states["stereo_raw_lockstep"], "fail")
                self.assertEqual(camera.physical_line_count, 2)
            imu = checked.streams[2]
            self.assertEqual(imu.first_violation.code, "exact_header_mismatch")
            self.assertEqual(imu.check_states["exact_header"], "fail")
            self.assertEqual(imu.check_states["line_transport"], "not_reached")
            self.assertEqual(imu.physical_line_count, 2)


class ProbeCliTests(unittest.TestCase):
    def test_argument_error_is_one_canonical_json_document(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            status = main([])
        self.assertEqual(status, 1)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["execution_outcome"], "failed")
        self.assertEqual(parsed["scientific_authority"], "none")

    def test_success_is_one_json_document_without_source_values(self) -> None:
        result = RealCsvGrammarProbeResult(
            _AUTHORIZATION_ID,
            "accepts_frozen_gate1_grammar",
            Path(_CLAIM_PATH),
            Path(_RECEIPT_PATH),
            "0" * 64,
        )
        output = io.StringIO()
        with (
            mock.patch.object(
                probe_module,
                "run_authorized_real_csv_grammar_probe",
                return_value=result,
            ),
            contextlib.redirect_stdout(output),
        ):
            status = main(["--authorization", _AUTHORIZATION_PATH])
        self.assertEqual(status, 0)
        lines = output.getvalue().splitlines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["status"], "ok")
        self.assertNotIn("timestamp", lines[0])
        self.assertNotIn("filename", lines[0])


if __name__ == "__main__":
    unittest.main()

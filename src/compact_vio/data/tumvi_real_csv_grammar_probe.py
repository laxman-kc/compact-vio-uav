"""One-use aggregate-only grammar probe for four exact TUM-VI CSV files.

The checked spec is inert.  Real payload access is possible only through a
separately committed, 24-hour, one-execution authorization.  The controller
durably publishes a trackable claim before its first payload descriptor open,
then scans and hashes the four receipt-bound files once with bounded memory.
It never emits or retains source rows, tokens, timestamps, filenames, headers,
or numeric values.  Grammar rejection is a completed observation; provenance,
identity, resource, deadline, or I/O failure consumes the claim and produces no
receipt.  Every readiness flag remains false and scientific authority is none.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import stat
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import compact_vio.data.acquisition as acquisition_module
from compact_vio.data.acquisition import (
    AcquisitionError,
    ToolIdentity,
    _assert_clean_repository,
    _canonical_json_bytes,
    _canonical_relative,
    _check_deadline,
    _disk_usage,
    _exact_string_list,
    _format_utc,
    _hard_deadline,
    _is_ignored,
    _literal,
    _mapping,
    _sha256,
    _text,
    _utc_now,
    _utc_timestamp,
)

_SCHEMA_VERSION = "1.0.0"
_SPEC_RECORD_TYPE = "dataset_real_csv_grammar_probe_spec"
_AUTHORIZATION_RECORD_TYPE = "dataset_real_csv_grammar_probe_authorization"
_CLAIM_RECORD_TYPE = "dataset_real_csv_grammar_probe_claim"
_RECEIPT_RECORD_TYPE = "dataset_real_csv_grammar_probe_receipt"
_PROBE_ID = "tumvi-room4-512-16-real-csv-grammar-probe-v1"
_SPEC_SCOPE = (
    "one-use-exact-four-receipt-bound-real-csv-grammar-probe-aggregate-only-no-readiness/v1"
)
_AUTHORIZATION_SCOPE = "one_use_exact_four_real_csv_grammar_probe_aggregate_only"
_SPEC_PATH = "configs/data/tumvi_room4_512_16_real_csv_grammar_probe_v1.json"
_AUTHORIZATION_ID = "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29"
_AUTHORIZATION_PATH = (
    "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29.authorization.json"
)
_CLAIM_PATH = (
    "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29.claim.json"
)
_RECEIPT_PATH = (
    "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-real-csv-grammar-probe-2026-08-29.receipt.json"
)
_SOURCE_ROOT = "data/quarantine/tum-vi/room4-512-16/tumvi-room4-512-16-compatibility-slice-v1"
_SOURCE_SCOPE = (
    "compatibility-slice-receipt-bound-real-csv-bytes-not-independent-origin-authentication/v1"
)
_ONE_USE_POLICY = "claim-before-first-payload-descriptor-open-consumes-authorization-no-retry/v1"
_CONTRACT_ID = "tumvi-room4-512-16-adapter-contract-v1"
_CONTRACT_PATH = "configs/data/tumvi_room4_512_16_adapter_contract_v1.json"
_CONTRACT_SHA256 = "4368580eb601958f1c402ee6f85d3207d9bb41282c51f4dee505482c1a6542d5"
_MAXIMUM_ELAPSED_SECONDS = 600
_MINIMUM_FREE_BYTES = 2_149_580_800
_MAXIMUM_SPEC_BYTES = 1_048_576
_MAXIMUM_AUTHORIZATION_BYTES = 1_048_576
_MAXIMUM_TRACKED_FILE_BYTES = 1_048_576
_MAXIMUM_CLAIM_BYTES = 1_048_576
_MAXIMUM_RECEIPT_BYTES = 1_048_576
_POST_PROBE_RESERVE_BYTES = 2_147_483_648
_MAXIMUM_CSV_ROWS = 1_000_000
_MAXIMUM_CSV_LINE_BYTES = 1_048_576
_MAXIMUM_CSV_COLUMNS = 8
_SOURCE_SIZE_BYTES = 3_909_654
_READ_CHUNK_BYTES = 65_536
_SCIENTIFIC_AUTHORITY = "none"
_TOOL_PATHS = (
    "src/compact_vio/data/tumvi_real_csv_grammar_probe.py",
    "src/compact_vio/data/acquisition.py",
)

_PERMITTED_OPERATIONS = (
    "write_claim",
    "open_exact_four_bound_csv_descriptors_after_claim",
    "verify_exact_four_source_identities_single_pass",
    "scan_strict_gate1_grammar_single_pass",
    "compare_camera_indexes_raw_lockstep",
    "revalidate_claim_source_git_runtime_truth",
    "write_aggregate_receipt",
    "retract_exact_new_receipt_on_truth_gate_failure",
)
_SUCCESS_OPERATIONS = _PERMITTED_OPERATIONS[:-1]
_PROHIBITED_OPERATIONS = (
    "download",
    "network_access",
    "access_archive",
    "access_png",
    "access_dso",
    "access_calibration",
    "open_unlisted_file",
    "follow_links",
    "mutate_source",
    "delete_source_or_evidence",
    "persist_source_rows_or_tokens",
    "log_source_rows_or_tokens",
    "convert_numeric_sensor_lexemes",
    "interpret_clock_units_frames_pose_or_ground_truth",
    "reuse_gate2_synthetic_api_for_real_payload",
    "modify_gate2_parser_or_denylist",
    "decode_images",
    "construct_segments",
    "select_dataset",
    "assign_dataset_membership",
    "load_checkpoint",
    "train",
    "infer",
    "evaluate",
    "publish_scientific_result",
    "deploy",
)
_LIMITATIONS = (
    "grammar_acceptance_does_not_authenticate_origin_or_scientific_semantics",
    "source_header_labels_do_not_establish_units_frames_or_pose_meaning",
    "timestamp_token_order_does_not_establish_clock_equivalence",
    "no_image_calibration_model_segment_or_dataset_membership_access",
    "does_not_approve_adapter_readiness_training_inference_evaluation_or_publication",
)
_READINESS_FIELDS = (
    "real_payload_execution_authorized",
    "adapter_implemented",
    "adapter_ready",
    "calibration_ready",
    "clock_mapping_ready",
    "pose_semantics_ready",
    "ground_truth_ready",
    "png_decode_ready",
    "preprocessing_ready",
    "full_image_population_ready",
    "segment_construction_ready",
    "dataset_selected",
    "membership_assigned",
    "model_access_authorized",
)
_CHECK_NAMES = (
    "source_identity",
    "line_transport",
    "exact_header",
    "row_arity",
    "timestamp_lexeme",
    "timestamps_strictly_increasing",
    "role_lexemes",
    "minimum_data_rows",
    "stereo_raw_lockstep",
)
_CHECK_STATES = frozenset({"pass", "fail", "not_reached"})
_GRAMMAR_STATES = frozenset({"accepted", "rejected"})
_GRAMMAR_OUTCOMES = (
    "accepts_frozen_gate1_grammar",
    "rejects_frozen_gate1_grammar",
)
_COMMON_VIOLATION_CHECKS = {
    "carriage_return_forbidden": "line_transport",
    "nul_forbidden": "line_transport",
    "quoting_forbidden": "line_transport",
    "utf8_bom_forbidden": "line_transport",
    "non_ascii_forbidden": "line_transport",
    "final_line_missing_lf": "line_transport",
    "exact_header_mismatch": "exact_header",
    "blank_data_row": "row_arity",
    "comment_data_row": "row_arity",
    "data_row_arity": "row_arity",
    "timestamp_lexeme": "timestamp_lexeme",
    "timestamp_range": "timestamp_lexeme",
    "timestamp_not_strictly_increasing": "timestamps_strictly_increasing",
    "minimum_data_rows": "minimum_data_rows",
}
_CAMERA_VIOLATION_CHECKS = {
    **_COMMON_VIOLATION_CHECKS,
    "camera_filename_lexeme": "role_lexemes",
    "camera_filename_stem": "role_lexemes",
    "stereo_raw_bytes_mismatch": "stereo_raw_lockstep",
    "stereo_simultaneous_eof_mismatch": "stereo_raw_lockstep",
}
_NUMERIC_VIOLATION_CHECKS = {
    **_COMMON_VIOLATION_CHECKS,
    "numeric_lexeme": "role_lexemes",
}

_TIMESTAMP_PATTERN = re.compile(rb"(?:0|[1-9][0-9]*)")
_NUMERIC_PATTERN = re.compile(rb"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?")
_FILENAME_PATTERN = re.compile(rb"(?:0|[1-9][0-9]*)\.png")
_GIT_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")

_CAMERA_HEADER = ("#timestamp [ns]", "filename")
_IMU_HEADER = (
    "#timestamp [ns]",
    "w_RS_S_x [rad s^-1]",
    "w_RS_S_y [rad s^-1]",
    "w_RS_S_z [rad s^-1]",
    "a_RS_S_x [m s^-2]",
    "a_RS_S_y [m s^-2]",
    "a_RS_S_z [m s^-2]",
)
_POSE_HEADER = (
    "#timestamp [ns]",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
    "q_RS_w []",
    "q_RS_x []",
    "q_RS_y []",
    "q_RS_z []",
)


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class ProbeSourceFile:
    role: str
    contract_source_path: str
    slice_relative_path: str
    source_size_bytes: int
    source_sha256: str


@dataclass(frozen=True, slots=True)
class RealCsvGrammarProbeSpec:
    path: str
    sha256: str
    probe_id: str
    source_evidence: tuple[tuple[str, EvidenceIdentity], ...]
    source_root: str
    source_scope: str
    files: tuple[ProbeSourceFile, ...]


@dataclass(frozen=True, slots=True)
class ProbeOutputs:
    claim_path: str
    receipt_path: str


@dataclass(frozen=True, slots=True)
class RealCsvGrammarProbeAuthorization:
    authorization_id: str
    authorization_path: str
    authorization_sha256: str
    authorized_at: datetime
    expires_at: datetime
    spec_identity: EvidenceIdentity
    spec: RealCsvGrammarProbeSpec
    maximum_elapsed_seconds: int
    minimum_free_bytes: int
    tool_files: tuple[ToolIdentity, ...]
    retention_review_at: datetime
    outputs: ProbeOutputs


@dataclass(frozen=True, slots=True)
class FirstViolation:
    code: str
    physical_line_number: int


@dataclass(frozen=True, slots=True)
class StreamAggregate:
    role: str
    contract_source_path: str
    slice_relative_path: str
    source_size_bytes: int
    source_sha256: str
    bytes_read: int
    physical_line_count: int
    total_data_line_count: int
    validated_data_row_count: int
    grammar_state: str
    check_states: dict[str, str]
    first_violation: FirstViolation | None


@dataclass(frozen=True, slots=True)
class RealCsvGrammarProbeResult:
    authorization_id: str
    grammar_outcome: str
    claim_path: Path
    receipt_path: Path
    receipt_sha256: str


@dataclass(frozen=True, slots=True)
class CheckedRealCsvGrammarProbeReceipt:
    path: str
    sha256: str
    authorization_id: str
    grammar_outcome: str
    streams: tuple[StreamAggregate, ...]
    scientific_authority: str


@dataclass(frozen=True, slots=True)
class _SourceIdentity:
    device: int
    inode: int
    mode: int
    link_count: int
    size_bytes: int
    modified_ns: int
    changed_ns: int


@dataclass(slots=True)
class _BoundDirectory:
    descriptor: int
    identity: _SourceIdentity
    parent_descriptor: int | None
    entry_name: str | None


@dataclass(slots=True)
class _BoundSource:
    spec: ProbeSourceFile
    descriptor: int
    identity: _SourceIdentity
    parent_descriptor: int
    entry_name: str


@dataclass(slots=True)
class _BoundSourceTree:
    root_path: Path
    directories: dict[tuple[str, ...], _BoundDirectory]
    sources: dict[str, _BoundSource]
    repository_binding: _BoundRepoParent | None = None


@dataclass(frozen=True, slots=True)
class _RepoDirectoryIdentity:
    device: int
    inode: int
    mode: int


@dataclass(slots=True)
class _BoundRepoDirectory:
    descriptor: int
    identity: _RepoDirectoryIdentity
    parent_descriptor: int | None
    entry_name: str | None


@dataclass(slots=True)
class _BoundRepoParent:
    root_path: Path
    relative_parent: tuple[str, ...]
    directories: tuple[_BoundRepoDirectory, ...]

    @property
    def descriptor(self) -> int:
        return self.directories[-1].descriptor


@dataclass(frozen=True, slots=True)
class _ReceiptPublication:
    sha256: str
    device: int
    inode: int


@dataclass(slots=True)
class _ReceiptOwnership:
    publication: _ReceiptPublication | None = None
    payload: bytes | None = None


def _expected_evidence() -> tuple[tuple[str, EvidenceIdentity], ...]:
    return (
        (
            "compatibility_slice_receipt",
            EvidenceIdentity(
                "governance/datasets/acquisitions/"
                "tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json",
                "a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820",
            ),
        ),
        (
            "format_inspection_spec",
            EvidenceIdentity(
                "configs/data/tumvi_room4_512_16_format_inspection_v1.json",
                "e8dd0bc98c7be85fed6d92d319bafec75c9f658584ea83d17ac93c6f47bdf1a7",
            ),
        ),
        (
            "format_inspection_receipt",
            EvidenceIdentity(
                "governance/datasets/acquisitions/"
                "tumvi-room4-512-16-format-inspection-2026-08-29.receipt.json",
                "30697326550331146f676c88ad5a50756701c91e57084e0ff7178e9d3fbb7846",
            ),
        ),
        (
            "format_inspection_report",
            EvidenceIdentity(
                "reports/tumvi-room4-512-16-format-inspection-2026-08-29.md",
                "8048a399d611051e807c9824cdb141a5e6db1bcf77f9bd197483223fe887ef30",
            ),
        ),
        (
            "adapter_contract",
            EvidenceIdentity(_CONTRACT_PATH, _CONTRACT_SHA256),
        ),
        (
            "adapter_contract_loader",
            EvidenceIdentity(
                "src/compact_vio/data/tumvi_adapter_contract.py",
                "26a018504568c213dfa94dca9988544bd3bc7a5ce28770a30b932c9b0f25bf20",
            ),
        ),
        (
            "synthetic_parser",
            EvidenceIdentity(
                "src/compact_vio/data/tumvi_adapter_parser.py",
                "4d5186a9559a4c111edda6df3d49a1484952ab6028a9269904ce4577efdc99e1",
            ),
        ),
        (
            "synthetic_parser_report",
            EvidenceIdentity(
                "reports/tumvi-room4-512-16-synthetic-parser-gate2-2026-08-29.md",
                "04418a55c97d7ad71d7545129004f3760c62d818a81be3ffb97c0ee7b73ee6c8",
            ),
        ),
        (
            "data_package_boundary",
            EvidenceIdentity(
                "src/compact_vio/data/__init__.py",
                "c3a6a55891323874481b1877fd703ec401cd601d0dd340b72c16d2a0463c8fa5",
            ),
        ),
    )


def _expected_sources() -> tuple[ProbeSourceFile, ...]:
    root = "dataset-room4_512_16/mav0"
    return (
        ProbeSourceFile(
            "cam0",
            "mav0/cam0/data.csv",
            f"{root}/cam0/data.csv",
            98_057,
            "feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67",
        ),
        ProbeSourceFile(
            "cam1",
            "mav0/cam1/data.csv",
            f"{root}/cam1/data.csv",
            98_057,
            "feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67",
        ),
        ProbeSourceFile(
            "imu",
            "mav0/imu0/data.csv",
            f"{root}/imu0/data.csv",
            2_232_296,
            "4249d4036b3c03c55b709f6f634d975d024999fb017ab3539cfa71580793a3be",
        ),
        ProbeSourceFile(
            "pose",
            "mav0/mocap0/data.csv",
            f"{root}/mocap0/data.csv",
            1_481_244,
            "073a3e957efa8ff638ea41402cac9654b40897631d566a3ffee090208597db2a",
        ),
    )


def _resolve_repo_file(
    path: os.PathLike[str] | str, *, repo_root: Path, field: str
) -> tuple[Path, str]:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    candidate = Path(os.path.abspath(candidate))
    lexical_root = Path(os.path.abspath(repo_root))
    try:
        relative = candidate.relative_to(lexical_root).as_posix()
    except ValueError:
        try:
            normalized = candidate.parent.resolve(strict=True) / candidate.name
            relative = normalized.relative_to(lexical_root).as_posix()
        except (OSError, ValueError) as exc:
            raise AcquisitionError(f"{field} must be inside the repository") from exc
    return candidate, _canonical_relative(relative, field=field)


def _evidence(value: object, *, field: str) -> EvidenceIdentity:
    item = _mapping(value, field=field, keys={"path", "sha256"})
    return EvidenceIdentity(
        _canonical_relative(item["path"], field=f"{field}.path"),
        _sha256(item["sha256"], field=f"{field}.sha256"),
    )


def _repo_directory_identity(metadata: os.stat_result) -> _RepoDirectoryIdentity:
    return _RepoDirectoryIdentity(
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
    )


def _require_repo_directory(metadata: os.stat_result, *, field: str) -> _RepoDirectoryIdentity:
    if not stat.S_ISDIR(metadata.st_mode):
        raise AcquisitionError(f"checked {field} ancestor must be a real directory")
    return _repo_directory_identity(metadata)


def _bind_repo_directory_chain(
    root: Path,
    parts: tuple[str, ...],
    *,
    field: str,
    cleanup: ExitStack,
) -> _BoundRepoParent:
    """Retain a no-follow descriptor for every named directory from a trusted root."""

    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise AcquisitionError("checked repository paths require POSIX no-follow directory opens")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    directories: list[_BoundRepoDirectory] = []
    try:
        root_descriptor = os.open(root, directory_flags)
    except OSError as exc:
        raise AcquisitionError(f"cannot bind checked {field} repository root") from exc
    cleanup.callback(os.close, root_descriptor)
    try:
        root_identity = _require_repo_directory(os.fstat(root_descriptor), field=field)
    except OSError as exc:
        raise AcquisitionError(f"cannot inspect checked {field} repository root") from exc
    directories.append(_BoundRepoDirectory(root_descriptor, root_identity, None, None))
    for part in parts:
        if part in ("", ".", "..") or PurePosixPath(part).parts != (part,):
            raise AcquisitionError(f"checked {field} contains an unsafe directory component")
        parent_descriptor = directories[-1].descriptor
        try:
            descriptor = os.open(part, directory_flags, dir_fd=parent_descriptor)
        except OSError as exc:
            raise AcquisitionError(f"cannot bind checked {field} ancestor") from exc
        cleanup.callback(os.close, descriptor)
        try:
            identity = _require_repo_directory(os.fstat(descriptor), field=field)
        except OSError as exc:
            raise AcquisitionError(f"cannot inspect checked {field} ancestor") from exc
        directories.append(_BoundRepoDirectory(descriptor, identity, parent_descriptor, part))
    binding = _BoundRepoParent(
        Path(os.path.abspath(root)),
        parts,
        tuple(directories),
    )
    _assert_bound_repo_parent(binding, field=field)
    return binding


def _bind_repo_file_parent(
    root: Path,
    relative: str,
    *,
    field: str,
    cleanup: ExitStack,
) -> tuple[_BoundRepoParent, str]:
    """Retain every no-follow directory descriptor leading to one repository file."""

    canonical = _canonical_relative(relative, field=field)
    parts = PurePosixPath(canonical).parts
    binding = _bind_repo_directory_chain(
        root,
        tuple(parts[:-1]),
        field=field,
        cleanup=cleanup,
    )
    return binding, parts[-1]


def _bind_repo_directory(
    root: Path,
    relative: str,
    *,
    field: str,
    cleanup: ExitStack,
) -> _BoundRepoParent:
    canonical = _canonical_relative(relative, field=field)
    return _bind_repo_directory_chain(
        root,
        tuple(PurePosixPath(canonical).parts),
        field=field,
        cleanup=cleanup,
    )


def _assert_bound_repo_parent(binding: _BoundRepoParent, *, field: str) -> None:
    """Revalidate every retained repository directory descriptor and path edge."""

    root = binding.directories[0]
    try:
        descriptor_identity = _repo_directory_identity(os.fstat(root.descriptor))
        path_identity = _repo_directory_identity(os.lstat(binding.root_path))
    except OSError as exc:
        raise AcquisitionError(f"checked {field} repository-root identity is unavailable") from exc
    if (
        descriptor_identity != root.identity
        or path_identity != root.identity
        or not stat.S_ISDIR(path_identity.mode)
    ):
        raise AcquisitionError(f"checked {field} repository-root identity changed")
    for directory in binding.directories[1:]:
        if directory.parent_descriptor is None or directory.entry_name is None:
            raise AcquisitionError(f"checked {field} ancestor binding is incomplete")
        try:
            descriptor_identity = _repo_directory_identity(os.fstat(directory.descriptor))
            path_identity = _repo_directory_identity(
                os.stat(
                    directory.entry_name,
                    dir_fd=directory.parent_descriptor,
                    follow_symlinks=False,
                )
            )
        except OSError as exc:
            raise AcquisitionError(f"checked {field} ancestor identity is unavailable") from exc
        if (
            descriptor_identity != directory.identity
            or path_identity != directory.identity
            or not stat.S_ISDIR(path_identity.mode)
        ):
            raise AcquisitionError(f"checked {field} ancestor identity changed")


def _bound_leaf_for_path(path: Path, binding: _BoundRepoParent, *, field: str) -> str:
    absolute = Path(os.path.abspath(path))
    expected_parent = binding.root_path.joinpath(*binding.relative_parent)
    if absolute.parent != expected_parent or absolute.name in ("", ".", ".."):
        raise AcquisitionError(f"checked {field} is outside its retained parent binding")
    return absolute.name


def _full_file_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_exact_at(
    binding: _BoundRepoParent,
    leaf: str,
    *,
    expected: bytes | None,
    maximum_bytes: int,
    field: str,
    expected_device_inode: tuple[int, int] | None = None,
    required_link_count: int = 1,
    allow_additional_links: bool = False,
) -> bytes:
    """Read bounded bytes through one retained parent FD and seal all path identities."""

    if (
        type(maximum_bytes) is not int
        or maximum_bytes < 0
        or type(required_link_count) is not int
        or required_link_count <= 0
        or type(allow_additional_links) is not bool
    ):
        raise AcquisitionError("checked byte and link bounds must be positive exact integers")
    if PurePosixPath(leaf).parts != (leaf,) or leaf in ("", ".", ".."):
        raise AcquisitionError(f"checked {field} leaf name is unsafe")
    if expected is not None and len(expected) > maximum_bytes:
        raise AcquisitionError(f"checked {field} expected bytes exceed their bound")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(leaf, flags, dir_fd=binding.descriptor)
    except OSError as exc:
        raise AcquisitionError(f"cannot open checked {field}") from exc
    try:
        initial = os.fstat(descriptor)
        link_count_is_valid = (
            initial.st_nlink >= required_link_count
            if allow_additional_links
            else initial.st_nlink == required_link_count
        )
        if (
            not stat.S_ISREG(initial.st_mode)
            or not link_count_is_valid
            or initial.st_size > maximum_bytes
        ):
            raise AcquisitionError(
                f"checked {field} must be a bounded regular file with its exact link count"
            )
        if expected_device_inode is not None and (initial.st_dev, initial.st_ino) != (
            expected_device_inode
        ):
            raise AcquisitionError(f"checked {field} is not the owned publication inode")
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = os.read(
                    descriptor,
                    max(1, min(65_536, maximum_bytes + 1 - total)),
                )
            except OSError as exc:
                raise AcquisitionError(f"cannot read checked {field}") from exc
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise AcquisitionError(f"checked {field} exceeds its byte bound")
            chunks.append(chunk)
        final = os.fstat(descriptor)
        initial_identity = _full_file_identity(initial)
        final_identity = _full_file_identity(final)
        if initial_identity != final_identity or total != initial.st_size:
            raise AcquisitionError(f"checked {field} changed while reading")
        try:
            path_metadata = os.stat(
                leaf,
                dir_fd=binding.descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise AcquisitionError(f"checked {field} path identity became unavailable") from exc
        if _full_file_identity(path_metadata) != final_identity:
            raise AcquisitionError(f"checked {field} path identity changed")
        _assert_bound_repo_parent(binding, field=field)
        try:
            final_path_metadata = os.stat(
                leaf,
                dir_fd=binding.descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            raise AcquisitionError(f"checked {field} path identity became unavailable") from exc
        if _full_file_identity(final_path_metadata) != final_identity:
            raise AcquisitionError(f"checked {field} path identity changed")
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    if expected is not None and raw != expected:
        raise AcquisitionError(f"checked {field} bytes changed")
    return raw


def _bind_absolute_file_parent(
    path: Path, *, field: str, cleanup: ExitStack
) -> tuple[_BoundRepoParent, str]:
    supplied = Path(os.path.abspath(path))
    try:
        absolute = supplied.parent.resolve(strict=True) / supplied.name
    except OSError as exc:
        raise AcquisitionError(f"checked {field} parent is unavailable") from exc
    anchor = Path(absolute.anchor)
    try:
        relative = absolute.relative_to(anchor).as_posix()
    except ValueError as exc:
        raise AcquisitionError(f"checked {field} path is not absolute") from exc
    return _bind_repo_file_parent(anchor, relative, field=field, cleanup=cleanup)


def _read_repo_bytes(
    root: Path,
    relative: str,
    *,
    expected: bytes | None,
    maximum_bytes: int,
    field: str,
) -> bytes:
    with ExitStack() as cleanup:
        binding, leaf = _bind_repo_file_parent(
            root,
            relative,
            field=field,
            cleanup=cleanup,
        )
        return _read_exact_at(
            binding,
            leaf,
            expected=expected,
            maximum_bytes=maximum_bytes,
            field=field,
        )


def _parse_checked_json(raw: bytes, *, field: str) -> dict[str, Any]:
    if not raw:
        raise AcquisitionError(f"checked {field} must not be empty")

    def reject_constant(value: str) -> None:
        raise AcquisitionError(f"checked {field} contains forbidden JSON constant {value}")

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=acquisition_module._reject_duplicate_keys,  # noqa: SLF001
            parse_constant=reject_constant,
        )
    except AcquisitionError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError(f"checked {field} is not strict UTF-8 JSON") from exc
    if type(parsed) is not dict:
        raise AcquisitionError(f"checked {field} must be a JSON object")
    return parsed


def _read_repo_json(
    root: Path,
    relative: str,
    *,
    maximum_bytes: int,
    field: str,
) -> tuple[bytes, dict[str, Any]]:
    raw = _read_repo_bytes(
        root,
        relative,
        expected=None,
        maximum_bytes=maximum_bytes,
        field=field,
    )
    return raw, _parse_checked_json(raw, field=field)


def _read_single_link_json(
    path: Path, *, maximum_bytes: int, field: str
) -> tuple[bytes, dict[str, Any]]:
    raw = _read_exact_single_link_bytes(
        path,
        expected=None,
        maximum_bytes=maximum_bytes,
        field=field,
    )
    return raw, _parse_checked_json(raw, field=field)


def _read_exact_single_link_bytes(
    path: Path,
    *,
    expected: bytes | None,
    maximum_bytes: int,
    field: str,
    expected_device_inode: tuple[int, int] | None = None,
    required_link_count: int = 1,
) -> bytes:
    """Read a bounded absolute path through retained no-follow ancestor descriptors."""

    with ExitStack() as cleanup:
        binding, leaf = _bind_absolute_file_parent(path, field=field, cleanup=cleanup)
        return _read_exact_at(
            binding,
            leaf,
            expected=expected,
            maximum_bytes=maximum_bytes,
            field=field,
            expected_device_inode=expected_device_inode,
            required_link_count=required_link_count,
        )


def _assert_tracked_gate3_bytes(
    root: Path,
    relative: str,
    expected_sha256: str,
    *,
    expected_revision: str,
) -> None:
    """Bind one tracked worktree path to exact HEAD bytes without a path-following read."""

    canonical = _canonical_relative(relative, field="tracked Gate3 evidence path")
    if _GIT_REVISION_PATTERN.fullmatch(expected_revision) is None:
        raise AcquisitionError("tracked Gate3 evidence revision is invalid")
    acquisition_module._git(  # noqa: SLF001
        root, "ls-files", "--error-unmatch", "--", canonical
    )
    revision_path = f"{expected_revision}:{canonical}"
    kind = acquisition_module._git(root, "cat-file", "-t", revision_path).stdout.strip()  # noqa: SLF001
    if kind != b"blob":
        raise AcquisitionError("tracked Gate3 evidence must be a HEAD blob")
    size_raw = acquisition_module._git(root, "cat-file", "-s", revision_path).stdout.strip()  # noqa: SLF001
    try:
        size = int(size_raw.decode("ascii"))
    except (UnicodeError, ValueError) as exc:
        raise AcquisitionError("tracked Gate3 evidence HEAD size is invalid") from exc
    if size < 0 or size > _MAXIMUM_TRACKED_FILE_BYTES:
        raise AcquisitionError("tracked Gate3 evidence HEAD blob exceeds its byte bound")
    head = acquisition_module._git(root, "cat-file", "-p", revision_path).stdout  # noqa: SLF001
    if len(head) != size:
        raise AcquisitionError("tracked Gate3 evidence HEAD blob size changed")
    if hashlib.sha256(head).hexdigest() != expected_sha256:
        raise AcquisitionError("tracked Gate3 evidence HEAD digest mismatch")
    current = _read_repo_bytes(
        root,
        canonical,
        expected=head,
        maximum_bytes=size,
        field="tracked Gate3 evidence",
    )
    if hashlib.sha256(current).hexdigest() != expected_sha256:
        raise AcquisitionError("tracked Gate3 evidence worktree digest mismatch")


def _assert_exact_gate3_file(
    path: Path,
    expected: bytes,
    *,
    maximum_bytes: int,
    field: str,
    expected_device_inode: tuple[int, int] | None = None,
    parent_binding: _BoundRepoParent | None = None,
    required_link_count: int = 1,
) -> str:
    if parent_binding is None:
        raw = _read_exact_single_link_bytes(
            path,
            expected=expected,
            maximum_bytes=maximum_bytes,
            field=field,
            expected_device_inode=expected_device_inode,
            required_link_count=required_link_count,
        )
    else:
        leaf = _bound_leaf_for_path(path, parent_binding, field=field)
        raw = _read_exact_at(
            parent_binding,
            leaf,
            expected=expected,
            maximum_bytes=maximum_bytes,
            field=field,
            expected_device_inode=expected_device_inode,
            required_link_count=required_link_count,
        )
    return hashlib.sha256(raw).hexdigest()


def _positive_exact_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise AcquisitionError(f"{field} must be a positive exact integer")
    return value


def _non_negative_exact_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise AcquisitionError(f"{field} must be a non-negative exact integer")
    return value


def _source_file(value: object, *, field: str) -> ProbeSourceFile:
    item = _mapping(
        value,
        field=field,
        keys={
            "role",
            "contract_source_path",
            "slice_relative_path",
            "source_size_bytes",
            "source_sha256",
        },
    )
    return ProbeSourceFile(
        _text(item["role"], field=f"{field}.role"),
        _canonical_relative(item["contract_source_path"], field=f"{field}.contract_source_path"),
        _canonical_relative(item["slice_relative_path"], field=f"{field}.slice_relative_path"),
        _positive_exact_int(item["source_size_bytes"], field=f"{field}.source_size_bytes"),
        _sha256(item["source_sha256"], field=f"{field}.source_sha256"),
    )


def load_real_csv_grammar_probe_spec(
    path: os.PathLike[str] | str, *, repo_root: os.PathLike[str] | str
) -> RealCsvGrammarProbeSpec:
    """Load the inert checked probe spec without touching any payload path."""

    root_path = Path(repo_root).resolve()
    _, relative = _resolve_repo_file(path, repo_root=root_path, field="probe spec path")
    _literal(relative, _SPEC_PATH, field="probe spec path")
    raw, parsed = _read_repo_json(
        root_path,
        relative,
        maximum_bytes=_MAXIMUM_SPEC_BYTES,
        field="real-CSV grammar-probe spec",
    )
    root = _mapping(
        parsed,
        field="real-CSV grammar-probe spec",
        keys={
            "record_type",
            "schema_version",
            "probe_id",
            "scope",
            "source_evidence",
            "source",
            "grammar_binding",
            "capability_boundary",
            "resource_limits",
            "result_contract",
        },
    )
    _literal(root["record_type"], _SPEC_RECORD_TYPE, field="record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="schema_version")
    _literal(root["probe_id"], _PROBE_ID, field="probe_id")
    _literal(root["scope"], _SPEC_SCOPE, field="scope")

    expected_evidence = _expected_evidence()
    evidence_root = _mapping(
        root["source_evidence"],
        field="source_evidence",
        keys={name for name, _ in expected_evidence},
    )
    evidence: list[tuple[str, EvidenceIdentity]] = []
    for name, expected in expected_evidence:
        actual = _evidence(evidence_root[name], field=f"source_evidence.{name}")
        _literal(actual, expected, field=f"source_evidence.{name}")
        evidence.append((name, actual))

    source = _mapping(
        root["source"],
        field="source",
        keys={"root_path", "source_scope", "files"},
    )
    source_root = _canonical_relative(source["root_path"], field="source.root_path")
    _literal(source_root, _SOURCE_ROOT, field="source.root_path")
    _literal(source["source_scope"], _SOURCE_SCOPE, field="source.source_scope")
    file_values = source["files"]
    if type(file_values) is not list:
        raise AcquisitionError("source.files must be a JSON array")
    files = tuple(
        _source_file(value, field=f"source.files[{index}]")
        for index, value in enumerate(file_values)
    )
    _literal(files, _expected_sources(), field="source.files exact ordered identities")

    grammar = _mapping(
        root["grammar_binding"],
        field="grammar_binding",
        keys={
            "contract_id",
            "contract_path",
            "contract_sha256",
            "grammar_object",
            "transport_and_token_policy",
            "camera_comparison",
            "gate2_relationship",
        },
    )
    expected_grammar: dict[str, object] = {
        "contract_id": _CONTRACT_ID,
        "contract_path": _CONTRACT_PATH,
        "contract_sha256": _CONTRACT_SHA256,
        "grammar_object": "csv_grammars",
        "transport_and_token_policy": (
            "exact-gate1-csv-grammar-no-normalization-or-numeric-conversion/v1"
        ),
        "camera_comparison": "raw-byte-lockstep-through-simultaneous-eof/v1",
        "gate2_relationship": "differential-oracle-only-never-real-payload-input/v1",
    }
    for field, expected in expected_grammar.items():
        _literal(grammar[field], expected, field=f"grammar_binding.{field}")

    capability = _mapping(
        root["capability_boundary"],
        field="capability_boundary",
        keys={
            "first_payload_descriptor_open_requires_durable_claim",
            "payload_access",
            "source_access",
            "input_processing",
            "output",
            "retain_rows_or_tokens",
            "emit_rows_tokens_timestamps_filenames_headers_or_numeric_values",
            "maximum_image_bytes_read",
            "calibration_access",
            "model_access",
        },
    )
    expected_capability: dict[str, object] = {
        "first_payload_descriptor_open_requires_durable_claim": True,
        "payload_access": "future-separate-one-use-authorization-only",
        "source_access": "exact-four-receipt-bound-csv-files-only",
        "input_processing": "single-pass-constant-memory-hash-and-grammar-scan/v1",
        "output": "aggregate-counts-check-states-and-first-violation-location-only/v1",
        "retain_rows_or_tokens": False,
        "emit_rows_tokens_timestamps_filenames_headers_or_numeric_values": False,
        "maximum_image_bytes_read": 0,
        "calibration_access": "prohibited",
        "model_access": "prohibited",
    }
    for field, expected in expected_capability.items():
        _literal(capability[field], expected, field=f"capability_boundary.{field}")

    limits = _mapping(
        root["resource_limits"],
        field="resource_limits",
        keys={
            "source_file_count",
            "source_size_bytes",
            "maximum_csv_rows_per_file",
            "maximum_csv_line_bytes",
            "maximum_csv_columns",
            "maximum_claim_bytes",
            "maximum_receipt_bytes",
            "post_probe_reserve_bytes",
            "streaming_required",
            "fail_on_operational_limit",
        },
    )
    expected_limits: dict[str, object] = {
        "source_file_count": 4,
        "source_size_bytes": _SOURCE_SIZE_BYTES,
        "maximum_csv_rows_per_file": _MAXIMUM_CSV_ROWS,
        "maximum_csv_line_bytes": _MAXIMUM_CSV_LINE_BYTES,
        "maximum_csv_columns": _MAXIMUM_CSV_COLUMNS,
        "maximum_claim_bytes": _MAXIMUM_CLAIM_BYTES,
        "maximum_receipt_bytes": _MAXIMUM_RECEIPT_BYTES,
        "post_probe_reserve_bytes": _POST_PROBE_RESERVE_BYTES,
        "streaming_required": True,
        "fail_on_operational_limit": True,
    }
    for field, expected in expected_limits.items():
        _literal(limits[field], expected, field=f"resource_limits.{field}")

    result = _mapping(
        root["result_contract"],
        field="result_contract",
        keys={
            "execution_outcomes",
            "grammar_outcomes",
            "readiness",
            "scientific_authority",
            "limitations",
        },
    )
    _exact_string_list(
        result["execution_outcomes"], ("completed", "failed"), field="execution_outcomes"
    )
    _exact_string_list(result["grammar_outcomes"], _GRAMMAR_OUTCOMES, field="grammar_outcomes")
    readiness = _mapping(
        result["readiness"], field="result_contract.readiness", keys=set(_READINESS_FIELDS)
    )
    for field in _READINESS_FIELDS:
        _literal(readiness[field], False, field=f"result_contract.readiness.{field}")
    _literal(
        result["scientific_authority"],
        _SCIENTIFIC_AUTHORITY,
        field="result_contract.scientific_authority",
    )
    _exact_string_list(result["limitations"], _LIMITATIONS, field="result_contract.limitations")
    return RealCsvGrammarProbeSpec(
        relative,
        hashlib.sha256(raw).hexdigest(),
        _PROBE_ID,
        tuple(evidence),
        source_root,
        _SOURCE_SCOPE,
        files,
    )


def load_real_csv_grammar_probe_authorization(
    path: os.PathLike[str] | str, *, repo_root: os.PathLike[str] | str
) -> RealCsvGrammarProbeAuthorization:
    """Load a future separately committed one-use authorization without payload access."""

    root_path = Path(repo_root).resolve()
    _, relative = _resolve_repo_file(path, repo_root=root_path, field="probe authorization path")
    _literal(relative, _AUTHORIZATION_PATH, field="probe authorization path")
    raw, parsed = _read_repo_json(
        root_path,
        relative,
        maximum_bytes=_MAXIMUM_AUTHORIZATION_BYTES,
        field="real-CSV grammar-probe authorization",
    )
    root = _mapping(
        parsed,
        field="real-CSV grammar-probe authorization",
        keys={
            "authority_basis",
            "authorization_id",
            "authorized_at",
            "execution",
            "expires_at",
            "max_executions",
            "outputs",
            "permitted_operations",
            "prohibited_operations",
            "record_status",
            "record_type",
            "retention",
            "schema_version",
            "scientific_authority",
            "scope",
            "probe_limits",
            "source_evidence",
        },
    )
    _literal(root["record_type"], _AUTHORIZATION_RECORD_TYPE, field="record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="schema_version")
    _literal(root["record_status"], "approved", field="record_status")
    _literal(root["authorization_id"], _AUTHORIZATION_ID, field="authorization_id")
    _literal(root["scope"], _AUTHORIZATION_SCOPE, field="scope")
    _literal(root["max_executions"], 1, field="max_executions")

    authority = _mapping(
        root["authority_basis"],
        field="authority_basis",
        keys={"kind", "instruction_summary", "captured_at", "identity_authentication"},
    )
    _literal(authority["kind"], "active_workspace_user_instruction", field="authority_basis.kind")
    _text(authority["instruction_summary"], field="authority_basis.instruction_summary")
    captured_at = _utc_timestamp(authority["captured_at"], field="authority_basis.captured_at")
    _literal(
        authority["identity_authentication"],
        "not_independently_authenticated",
        field="authority_basis.identity_authentication",
    )
    authorized_at = _utc_timestamp(root["authorized_at"], field="authorized_at")
    expires_at = _utc_timestamp(root["expires_at"], field="expires_at")
    if captured_at > authorized_at:
        raise AcquisitionError("authority capture must not follow authorization")
    if (expires_at - authorized_at).total_seconds() != 86_400:
        raise AcquisitionError("authorization must expire exactly 24 hours after authorization")

    source_evidence = _mapping(
        root["source_evidence"],
        field="source_evidence",
        keys={"probe_spec", *(name for name, _ in _expected_evidence())},
    )
    spec_identity = _evidence(source_evidence["probe_spec"], field="source_evidence.probe_spec")
    _literal(spec_identity.path, _SPEC_PATH, field="source_evidence.probe_spec.path")
    spec = load_real_csv_grammar_probe_spec(root_path / spec_identity.path, repo_root=root_path)
    _literal(spec_identity.sha256, spec.sha256, field="source_evidence.probe_spec.sha256")
    for name, expected in spec.source_evidence:
        actual = _evidence(source_evidence[name], field=f"source_evidence.{name}")
        _literal(actual, expected, field=f"source_evidence.{name}")

    execution = _mapping(
        root["execution"],
        field="execution",
        keys={
            "requires_clean_worktree",
            "maximum_elapsed_seconds",
            "maximum_paid_compute_cost_usd",
            "minimum_free_bytes",
            "tool_files",
        },
    )
    _literal(execution["requires_clean_worktree"], True, field="requires_clean_worktree")
    _literal(
        execution["maximum_elapsed_seconds"],
        _MAXIMUM_ELAPSED_SECONDS,
        field="maximum_elapsed_seconds",
    )
    _literal(execution["maximum_paid_compute_cost_usd"], 0, field="paid compute")
    _literal(execution["minimum_free_bytes"], _MINIMUM_FREE_BYTES, field="minimum_free_bytes")
    tool_values = execution["tool_files"]
    if type(tool_values) is not list:
        raise AcquisitionError("execution.tool_files must be a JSON array")
    tools: list[ToolIdentity] = []
    for index, value in enumerate(tool_values):
        item = _mapping(
            value,
            field=f"execution.tool_files[{index}]",
            keys={"path", "sha256"},
        )
        tools.append(
            ToolIdentity(
                _canonical_relative(item["path"], field=f"execution.tool_files[{index}].path"),
                _sha256(item["sha256"], field=f"execution.tool_files[{index}].sha256"),
            )
        )
    if tuple(item.path for item in tools) != _TOOL_PATHS:
        raise AcquisitionError(f"execution.tool_files paths must equal {list(_TOOL_PATHS)!r}")

    limits = _mapping(
        root["probe_limits"],
        field="probe_limits",
        keys={
            "source_file_count",
            "source_size_bytes",
            "maximum_csv_rows_per_file",
            "maximum_csv_line_bytes",
            "maximum_csv_columns",
            "maximum_claim_bytes",
            "maximum_receipt_bytes",
            "post_probe_reserve_bytes",
        },
    )
    expected_limits = {
        "source_file_count": 4,
        "source_size_bytes": _SOURCE_SIZE_BYTES,
        "maximum_csv_rows_per_file": _MAXIMUM_CSV_ROWS,
        "maximum_csv_line_bytes": _MAXIMUM_CSV_LINE_BYTES,
        "maximum_csv_columns": _MAXIMUM_CSV_COLUMNS,
        "maximum_claim_bytes": _MAXIMUM_CLAIM_BYTES,
        "maximum_receipt_bytes": _MAXIMUM_RECEIPT_BYTES,
        "post_probe_reserve_bytes": _POST_PROBE_RESERVE_BYTES,
    }
    for field, expected in expected_limits.items():
        _literal(limits[field], expected, field=f"probe_limits.{field}")
    _exact_string_list(
        root["permitted_operations"], _PERMITTED_OPERATIONS, field="permitted_operations"
    )
    _exact_string_list(
        root["prohibited_operations"], _PROHIBITED_OPERATIONS, field="prohibited_operations"
    )
    scientific = _mapping(
        root["scientific_authority"],
        field="scientific_authority",
        keys={
            "selects_dataset",
            "assigns_membership",
            "approves_adapter",
            "approves_calibration",
            "approves_ground_truth",
            "approves_model_access",
            "approves_training",
            "approves_inference",
            "approves_evaluation",
            "approves_publication",
        },
    )
    for field, value in scientific.items():
        _literal(value, False, field=f"scientific_authority.{field}")
    retention = _mapping(
        root["retention"],
        field="retention",
        keys={"policy", "review_at", "deletion_authorized"},
    )
    _literal(
        retention["policy"],
        "retain_real_csv_grammar_probe_evidence_until_review",
        field="retention.policy",
    )
    review_at = _utc_timestamp(retention["review_at"], field="retention.review_at")
    if review_at <= expires_at:
        raise AcquisitionError("retention.review_at must follow expires_at")
    _literal(retention["deletion_authorized"], False, field="retention.deletion_authorized")
    output = _mapping(root["outputs"], field="outputs", keys={"claim_path", "receipt_path"})
    outputs = ProbeOutputs(
        _canonical_relative(output["claim_path"], field="outputs.claim_path"),
        _canonical_relative(output["receipt_path"], field="outputs.receipt_path"),
    )
    _literal(outputs.claim_path, _CLAIM_PATH, field="outputs.claim_path")
    _literal(outputs.receipt_path, _RECEIPT_PATH, field="outputs.receipt_path")
    return RealCsvGrammarProbeAuthorization(
        _AUTHORIZATION_ID,
        relative,
        hashlib.sha256(raw).hexdigest(),
        authorized_at,
        expires_at,
        spec_identity,
        spec,
        _MAXIMUM_ELAPSED_SECONDS,
        _MINIMUM_FREE_BYTES,
        tuple(tools),
        review_at,
        outputs,
    )


def _identity(metadata: os.stat_result) -> _SourceIdentity:
    return _SourceIdentity(
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _open_directory(
    path_or_name: os.PathLike[str] | str,
    *,
    directory_descriptor: int | None = None,
) -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise AcquisitionError("descriptor-safe payload access requires POSIX open flags")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        if directory_descriptor is None:
            return os.open(path_or_name, flags)
        return os.open(path_or_name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise AcquisitionError("payload directory binding failed") from exc


def _open_regular_file(name: str, *, directory_descriptor: int) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise AcquisitionError("descriptor-safe payload access requires O_NOFOLLOW")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        return os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise AcquisitionError("payload file binding failed") from exc


def _require_directory_identity(metadata: os.stat_result) -> _SourceIdentity:
    if not stat.S_ISDIR(metadata.st_mode):
        raise AcquisitionError("bound payload ancestor is not a directory")
    return _identity(metadata)


def _require_source_identity(metadata: os.stat_result, *, expected_size: int) -> _SourceIdentity:
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise AcquisitionError("bound payload source must be one regular single-link file")
    if metadata.st_size != expected_size:
        raise AcquisitionError("bound payload source size does not match its receipt identity")
    return _identity(metadata)


def _bind_exact_sources_after_claim(
    root_path: Path,
    files: tuple[ProbeSourceFile, ...],
    *,
    cleanup: ExitStack,
    repository_root: Path | None = None,
    source_root_relative: str | None = None,
) -> _BoundSourceTree:
    """Open only the four fixed files through retained no-follow directory FDs."""

    if (repository_root is None) != (source_root_relative is None):
        raise AcquisitionError(
            "payload repository-root binding arguments must be supplied together"
        )
    repository_binding: _BoundRepoParent | None = None
    if repository_root is None:
        root_descriptor = _open_directory(root_path)
        cleanup.callback(os.close, root_descriptor)
    else:
        assert source_root_relative is not None
        expected_root = Path(os.path.abspath(repository_root / source_root_relative))
        if Path(os.path.abspath(root_path)) != expected_root:
            raise AcquisitionError("payload root path differs from its exact repository scope")
        repository_binding = _bind_repo_directory(
            repository_root,
            source_root_relative,
            field="payload source root",
            cleanup=cleanup,
        )
        root_descriptor = repository_binding.descriptor
    try:
        root_metadata = os.fstat(root_descriptor)
    except OSError as exc:
        raise AcquisitionError("cannot inspect the bound payload root") from exc
    directories: dict[tuple[str, ...], _BoundDirectory] = {
        (): _BoundDirectory(
            root_descriptor,
            _require_directory_identity(root_metadata),
            None,
            None,
        )
    }
    sources: dict[str, _BoundSource] = {}
    for source in files:
        parts = PurePosixPath(source.slice_relative_path).parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise AcquisitionError("probe source contains an unsafe path")
        parent_key: tuple[str, ...] = ()
        for part in parts[:-1]:
            child_key = (*parent_key, part)
            if child_key not in directories:
                parent = directories[parent_key]
                descriptor = _open_directory(part, directory_descriptor=parent.descriptor)
                cleanup.callback(os.close, descriptor)
                try:
                    metadata = os.fstat(descriptor)
                except OSError as exc:
                    raise AcquisitionError("cannot inspect a bound payload ancestor") from exc
                directories[child_key] = _BoundDirectory(
                    descriptor,
                    _require_directory_identity(metadata),
                    parent.descriptor,
                    part,
                )
            parent_key = child_key
        parent = directories[parent_key]
        descriptor = _open_regular_file(parts[-1], directory_descriptor=parent.descriptor)
        cleanup.callback(os.close, descriptor)
        try:
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise AcquisitionError("cannot inspect a bound payload source") from exc
        sources[source.role] = _BoundSource(
            source,
            descriptor,
            _require_source_identity(metadata, expected_size=source.source_size_bytes),
            parent.descriptor,
            parts[-1],
        )
    if tuple(sources) != tuple(item.role for item in files):
        raise AcquisitionError("bound source roles are not the exact ordered four-source set")
    return _BoundSourceTree(root_path, directories, sources, repository_binding)


def _safe_stat_entry(name: str, *, directory_descriptor: int) -> os.stat_result:
    try:
        return os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
    except OSError as exc:
        raise AcquisitionError("bound payload path identity became unavailable") from exc


def _assert_bound_sources(tree: _BoundSourceTree) -> None:
    """Revalidate descriptor state and every retained path edge without reopening payloads."""

    root = tree.directories[()]
    if tree.repository_binding is not None:
        _assert_bound_repo_parent(tree.repository_binding, field="payload source root")
        try:
            root_descriptor_identity = _identity(os.fstat(root.descriptor))
        except OSError as exc:
            raise AcquisitionError("bound payload root identity became unavailable") from exc
        if root_descriptor_identity != root.identity:
            raise AcquisitionError("bound payload root identity changed")
    else:
        try:
            root_descriptor_identity = _identity(os.fstat(root.descriptor))
            root_path_identity = _identity(os.lstat(tree.root_path))
        except OSError as exc:
            raise AcquisitionError("bound payload root identity became unavailable") from exc
        if (
            root_descriptor_identity != root.identity
            or root_path_identity != root.identity
            or not stat.S_ISDIR(root_path_identity.mode)
        ):
            raise AcquisitionError("bound payload root identity changed")
    for key, directory in tree.directories.items():
        if not key:
            continue
        if directory.parent_descriptor is None or directory.entry_name is None:
            raise AcquisitionError("bound payload directory metadata is incomplete")
        try:
            descriptor_identity = _identity(os.fstat(directory.descriptor))
        except OSError as exc:
            raise AcquisitionError("bound payload directory identity became unavailable") from exc
        path_identity = _identity(
            _safe_stat_entry(
                directory.entry_name,
                directory_descriptor=directory.parent_descriptor,
            )
        )
        if (
            descriptor_identity != directory.identity
            or path_identity != directory.identity
            or not stat.S_ISDIR(path_identity.mode)
        ):
            raise AcquisitionError("bound payload ancestor identity changed")
    for source in tree.sources.values():
        try:
            descriptor_identity = _identity(os.fstat(source.descriptor))
        except OSError as exc:
            raise AcquisitionError("bound payload source identity became unavailable") from exc
        path_identity = _identity(
            _safe_stat_entry(
                source.entry_name,
                directory_descriptor=source.parent_descriptor,
            )
        )
        if (
            descriptor_identity != source.identity
            or path_identity != source.identity
            or not stat.S_ISREG(path_identity.mode)
            or path_identity.link_count != 1
        ):
            raise AcquisitionError("bound payload source identity changed")


class _SourceStream:
    __slots__ = ("_bound", "_digest", "_eof", "_total")

    def __init__(self, bound: _BoundSource) -> None:
        self._bound = bound
        self._digest = hashlib.sha256()
        self._eof = False
        self._total = 0

    @property
    def total(self) -> int:
        return self._total

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    @property
    def eof(self) -> bool:
        return self._eof

    def read_chunk(self) -> bytes:
        if self._eof:
            return b""
        try:
            chunk = os.read(self._bound.descriptor, _READ_CHUNK_BYTES)
        except OSError as exc:
            raise AcquisitionError("payload source read failed") from exc
        if type(chunk) is not bytes:
            raise AcquisitionError("payload source read returned a non-bytes result")
        if not chunk:
            self._eof = True
            return b""
        self._total += len(chunk)
        if self._total > self._bound.spec.source_size_bytes:
            raise AcquisitionError("payload source exceeds its receipt-bound size")
        self._digest.update(chunk)
        return chunk

    def finish(self) -> None:
        if not self._eof:
            raise AcquisitionError("payload source was not consumed through EOF")
        if self._total != self._bound.spec.source_size_bytes:
            raise AcquisitionError("payload source size does not match its receipt identity")
        if self.sha256 != self._bound.spec.source_sha256:
            raise AcquisitionError("payload source digest does not match its receipt identity")


def _checks_for_role(role: str) -> tuple[str, ...]:
    if role in ("cam0", "cam1"):
        return _CHECK_NAMES
    return tuple(name for name in _CHECK_NAMES if name != "stereo_raw_lockstep")


def _violation_checks_for_role(role: str) -> Mapping[str, str]:
    return _CAMERA_VIOLATION_CHECKS if role in ("cam0", "cam1") else _NUMERIC_VIOLATION_CHECKS


class _GrammarAccumulator:
    __slots__ = (
        "_buffer",
        "_checks",
        "_current_line_commas",
        "_current_line_bytes",
        "_first_violation",
        "_last_byte_lf",
        "_physical_lines",
        "_previous_timestamp",
        "_role",
        "_validated_rows",
    )

    def __init__(self, role: str) -> None:
        if role not in ("cam0", "cam1", "imu", "pose"):
            raise AcquisitionError("unsupported grammar-probe source role")
        self._role = role
        self._buffer = bytearray()
        self._checks = {name: "not_reached" for name in _checks_for_role(role)}
        self._current_line_commas = 0
        self._current_line_bytes = 0
        self._first_violation: FirstViolation | None = None
        self._last_byte_lf = False
        self._physical_lines = 0
        self._validated_rows = 0
        self._previous_timestamp: int | None = None

    @property
    def next_physical_line_number(self) -> int:
        return self._physical_lines + 1

    def reject(self, code: str, line_number: int, *, check: str) -> None:
        if check in self._checks:
            self._checks[check] = "fail"
        if self._first_violation is None:
            self._first_violation = FirstViolation(code, max(line_number, 1))

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        self._last_byte_lf = chunk.endswith(b"\n")
        if self._first_violation is not None:
            self._feed_after_rejection(chunk)
            return
        self._buffer.extend(chunk)
        while (newline := self._buffer.find(b"\n")) >= 0:
            line = bytes(self._buffer[: newline + 1])
            del self._buffer[: newline + 1]
            self._process_line(line)
            if self._first_violation is not None:
                remainder = bytes(self._buffer)
                self._buffer.clear()
                self._feed_after_rejection(remainder)
                return
        if len(self._buffer) > _MAXIMUM_CSV_LINE_BYTES:
            raise AcquisitionError("payload physical line exceeds its operational byte bound")

    def _complete_physical_line(self) -> None:
        self._physical_lines += 1
        if self._physical_lines > _MAXIMUM_CSV_ROWS + 1:
            raise AcquisitionError("payload data-row count exceeds its operational bound")

    def _feed_after_rejection(self, chunk: bytes) -> None:
        if self._buffer:
            self._current_line_bytes += len(self._buffer)
            self._current_line_commas += self._buffer.count(b",")
            self._buffer.clear()
        parts = chunk.split(b"\n")
        for part in parts[:-1]:
            self._current_line_bytes += len(part) + 1
            self._current_line_commas += part.count(b",")
            if self._current_line_bytes > _MAXIMUM_CSV_LINE_BYTES:
                raise AcquisitionError("payload physical line exceeds its operational byte bound")
            if self._current_line_commas + 1 > _MAXIMUM_CSV_COLUMNS:
                raise AcquisitionError("payload physical row exceeds its operational column bound")
            self._complete_physical_line()
            self._current_line_bytes = 0
            self._current_line_commas = 0
        self._current_line_bytes += len(parts[-1])
        self._current_line_commas += parts[-1].count(b",")
        if self._current_line_bytes > _MAXIMUM_CSV_LINE_BYTES:
            raise AcquisitionError("payload physical line exceeds its operational byte bound")
        if self._current_line_commas + 1 > _MAXIMUM_CSV_COLUMNS:
            raise AcquisitionError("payload physical row exceeds its operational column bound")

    def _process_line(self, raw: bytes) -> None:
        self._complete_physical_line()
        line_number = self._physical_lines
        if len(raw) > _MAXIMUM_CSV_LINE_BYTES:
            raise AcquisitionError("payload physical line exceeds its operational byte bound")
        if raw.count(b",") + 1 > _MAXIMUM_CSV_COLUMNS:
            raise AcquisitionError("payload physical row exceeds its operational column bound")
        if b"\r" in raw:
            self.reject("carriage_return_forbidden", line_number, check="line_transport")
            return
        if b"\x00" in raw:
            self.reject("nul_forbidden", line_number, check="line_transport")
            return
        if b'"' in raw:
            self.reject("quoting_forbidden", line_number, check="line_transport")
            return
        if b"\xef\xbb\xbf" in raw:
            self.reject("utf8_bom_forbidden", line_number, check="line_transport")
            return
        if any(byte > 0x7F for byte in raw):
            self.reject("non_ascii_forbidden", line_number, check="line_transport")
            return
        body = raw[:-1]
        if line_number == 1:
            expected = {
                "cam0": _CAMERA_HEADER,
                "cam1": _CAMERA_HEADER,
                "imu": _IMU_HEADER,
                "pose": _POSE_HEADER,
            }[self._role]
            if body != b",".join(item.encode("ascii") for item in expected):
                self.reject("exact_header_mismatch", line_number, check="exact_header")
                return
            self._checks["exact_header"] = "pass"
            return
        if not body:
            self.reject("blank_data_row", line_number, check="row_arity")
            return
        if body.startswith(b"#"):
            self.reject("comment_data_row", line_number, check="row_arity")
            return
        cells = tuple(body.split(b","))
        expected_arity = {"cam0": 2, "cam1": 2, "imu": 7, "pose": 8}[self._role]
        if len(cells) != expected_arity:
            self.reject("data_row_arity", line_number, check="row_arity")
            return
        timestamp_raw = cells[0]
        if len(timestamp_raw) > 19 or _TIMESTAMP_PATTERN.fullmatch(timestamp_raw) is None:
            self.reject("timestamp_lexeme", line_number, check="timestamp_lexeme")
            return
        timestamp = int(timestamp_raw)
        if timestamp > 9_223_372_036_854_775_807:
            self.reject("timestamp_range", line_number, check="timestamp_lexeme")
            return
        if self._previous_timestamp is not None and timestamp <= self._previous_timestamp:
            self.reject(
                "timestamp_not_strictly_increasing",
                line_number,
                check="timestamps_strictly_increasing",
            )
            return
        if self._role in ("cam0", "cam1"):
            filename = cells[1]
            if len(filename) > 23 or _FILENAME_PATTERN.fullmatch(filename) is None:
                self.reject("camera_filename_lexeme", line_number, check="role_lexemes")
                return
            if filename[:-4] != timestamp_raw:
                self.reject("camera_filename_stem", line_number, check="role_lexemes")
                return
        elif any(
            len(value) > 128 or _NUMERIC_PATTERN.fullmatch(value) is None for value in cells[1:]
        ):
            self.reject("numeric_lexeme", line_number, check="role_lexemes")
            return
        self._previous_timestamp = timestamp
        self._validated_rows += 1

    def finish(self) -> None:
        if self._buffer:
            if len(self._buffer) > _MAXIMUM_CSV_LINE_BYTES:
                raise AcquisitionError("payload physical line exceeds its operational byte bound")
            if self._buffer.count(b",") + 1 > _MAXIMUM_CSV_COLUMNS:
                raise AcquisitionError("payload physical row exceeds its operational column bound")
            already_rejected = self._first_violation is not None
            self._complete_physical_line()
            if not already_rejected:
                self.reject(
                    "final_line_missing_lf",
                    self._physical_lines,
                    check="line_transport",
                )
            self._buffer.clear()
        elif self._current_line_bytes:
            self._complete_physical_line()
            self._current_line_bytes = 0
            self._current_line_commas = 0
            if self._first_violation is None:
                self.reject(
                    "final_line_missing_lf",
                    self._physical_lines,
                    check="line_transport",
                )
        elif self._physical_lines == 0:
            self.reject("empty_source", 1, check="exact_header")
        if self._first_violation is None and self._validated_rows < 1:
            self.reject(
                "minimum_data_rows",
                self._physical_lines + 1,
                check="minimum_data_rows",
            )
        if self._first_violation is None:
            for check in self._checks:
                if check != "stereo_raw_lockstep":
                    self._checks[check] = "pass"

    def mark_stereo_pass(self) -> None:
        if "stereo_raw_lockstep" in self._checks:
            if self._checks["stereo_raw_lockstep"] != "fail":
                self._checks["stereo_raw_lockstep"] = "pass"

    def aggregate(self, stream: _SourceStream) -> StreamAggregate:
        source = stream._bound.spec  # noqa: SLF001
        checks = dict(self._checks)
        checks["source_identity"] = "pass"
        return StreamAggregate(
            source.role,
            source.contract_source_path,
            source.slice_relative_path,
            source.source_size_bytes,
            source.source_sha256,
            stream.total,
            self._physical_lines,
            max(self._physical_lines - 1, 0),
            self._validated_rows,
            "accepted" if self._first_violation is None else "rejected",
            checks,
            self._first_violation,
        )


def _scan_stereo(
    cam0_bound: _BoundSource, cam1_bound: _BoundSource
) -> tuple[StreamAggregate, StreamAggregate]:
    streams = (_SourceStream(cam0_bound), _SourceStream(cam1_bound))
    accumulators = (_GrammarAccumulator("cam0"), _GrammarAccumulator("cam1"))
    pending = [b"", b""]
    eof = [False, False]
    while not (eof[0] and eof[1] and not pending[0] and not pending[1]):
        for index in (0, 1):
            if not pending[index] and not eof[index]:
                pending[index] = streams[index].read_chunk()
                eof[index] = streams[index].eof
        if pending[0] and pending[1]:
            count = min(len(pending[0]), len(pending[1]))
            left = pending[0][:count]
            right = pending[1][:count]
            if left != right:
                mismatch = next(
                    index for index, (a, b) in enumerate(zip(left, right, strict=True)) if a != b
                )
                prefix0 = left[:mismatch]
                prefix1 = right[:mismatch]
                accumulators[0].feed(prefix0)
                accumulators[1].feed(prefix1)
                line0 = accumulators[0].next_physical_line_number
                line1 = accumulators[1].next_physical_line_number
                accumulators[0].reject(
                    "stereo_raw_bytes_mismatch", line0, check="stereo_raw_lockstep"
                )
                accumulators[1].reject(
                    "stereo_raw_bytes_mismatch", line1, check="stereo_raw_lockstep"
                )
                accumulators[0].feed(left[mismatch:])
                accumulators[1].feed(right[mismatch:])
            else:
                accumulators[0].feed(left)
                accumulators[1].feed(right)
            pending[0] = pending[0][count:]
            pending[1] = pending[1][count:]
            continue
        if eof[0] and pending[1]:
            accumulators[0].reject(
                "stereo_simultaneous_eof_mismatch",
                accumulators[0].next_physical_line_number,
                check="stereo_raw_lockstep",
            )
            accumulators[1].reject(
                "stereo_simultaneous_eof_mismatch",
                accumulators[1].next_physical_line_number,
                check="stereo_raw_lockstep",
            )
            accumulators[1].feed(pending[1])
            pending[1] = b""
            continue
        if eof[1] and pending[0]:
            accumulators[0].reject(
                "stereo_simultaneous_eof_mismatch",
                accumulators[0].next_physical_line_number,
                check="stereo_raw_lockstep",
            )
            accumulators[1].reject(
                "stereo_simultaneous_eof_mismatch",
                accumulators[1].next_physical_line_number,
                check="stereo_raw_lockstep",
            )
            accumulators[0].feed(pending[0])
            pending[0] = b""
            continue
    for accumulator in accumulators:
        accumulator.finish()
    for stream in streams:
        stream.finish()
    if all(
        accumulator._checks["stereo_raw_lockstep"] != "fail"  # noqa: SLF001
        for accumulator in accumulators
    ):
        for accumulator in accumulators:
            accumulator.mark_stereo_pass()
    return (
        accumulators[0].aggregate(streams[0]),
        accumulators[1].aggregate(streams[1]),
    )


def _scan_numeric(bound: _BoundSource) -> StreamAggregate:
    stream = _SourceStream(bound)
    accumulator = _GrammarAccumulator(bound.spec.role)
    while chunk := stream.read_chunk():
        accumulator.feed(chunk)
    accumulator.finish()
    stream.finish()
    return accumulator.aggregate(stream)


def _scan_bound_sources(tree: _BoundSourceTree) -> tuple[StreamAggregate, ...]:
    cam0, cam1 = _scan_stereo(tree.sources["cam0"], tree.sources["cam1"])
    imu = _scan_numeric(tree.sources["imu"])
    pose = _scan_numeric(tree.sources["pose"])
    return cam0, cam1, imu, pose


def _runtime_sources(root: Path) -> None:
    actual = (Path(__file__).resolve(), Path(acquisition_module.__file__).resolve())
    expected = tuple((root / relative).resolve() for relative in _TOOL_PATHS)
    if actual != expected:
        raise AcquisitionError("loaded probe runtime does not match authorized repository sources")


def _tracked_evidence(
    authorization: RealCsvGrammarProbeAuthorization,
) -> tuple[EvidenceIdentity, ...]:
    return (
        EvidenceIdentity(
            authorization.authorization_path,
            authorization.authorization_sha256,
        ),
        authorization.spec_identity,
        *(identity for _, identity in authorization.spec.source_evidence),
    )


def _git_status_entries(root: Path) -> tuple[tuple[str, str], ...]:
    raw = acquisition_module._git(  # noqa: SLF001
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    entries: list[tuple[str, str]] = []
    parts = raw.split(b"\x00")
    for part in parts:
        if not part:
            continue
        try:
            decoded = part.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AcquisitionError("Git status contains a non-UTF-8 path") from exc
        if len(decoded) < 4 or decoded[2] != " ":
            raise AcquisitionError("Git status contains an unsupported record")
        entries.append((decoded[:2], decoded[3:]))
    return tuple(entries)


def _assert_repository_state(
    root: Path,
    authorization: RealCsvGrammarProbeAuthorization,
    *,
    expected_revision: str,
    expected_outputs: tuple[str, ...],
) -> None:
    revision = acquisition_module._git(root, "rev-parse", "HEAD").stdout.decode().strip()  # noqa: SLF001
    if revision != expected_revision or _GIT_REVISION_PATTERN.fullmatch(revision) is None:
        raise AcquisitionError("Git revision changed during real-CSV grammar probe")
    expected_status = tuple(("??", path) for path in expected_outputs)
    if tuple(sorted(_git_status_entries(root))) != tuple(sorted(expected_status)):
        raise AcquisitionError("repository state differs from the exact probe-output allowance")
    for evidence in _tracked_evidence(authorization):
        _assert_tracked_gate3_bytes(
            root,
            evidence.path,
            evidence.sha256,
            expected_revision=expected_revision,
        )
    for tool in authorization.tool_files:
        _assert_tracked_gate3_bytes(
            root,
            tool.path,
            tool.sha256,
            expected_revision=expected_revision,
        )
    _runtime_sources(root)
    final_revision = acquisition_module._git(root, "rev-parse", "HEAD").stdout.decode().strip()  # noqa: SLF001
    if final_revision != expected_revision:
        raise AcquisitionError("Git revision changed during real-CSV grammar probe")
    if tuple(sorted(_git_status_entries(root))) != tuple(sorted(expected_status)):
        raise AcquisitionError("repository state changed during real-CSV grammar probe truth gate")


def _claim_document(
    authorization: RealCsvGrammarProbeAuthorization,
    *,
    controller_started_at: datetime,
    claim_prepared_at: datetime,
    git_revision: str,
) -> dict[str, object]:
    evidence = dict(authorization.spec.source_evidence)
    return {
        "adapter_contract_sha256": evidence["adapter_contract"].sha256,
        "authorization_id": authorization.authorization_id,
        "authorization_sha256": authorization.authorization_sha256,
        "claim_prepared_at": _format_utc(claim_prepared_at),
        "compatibility_slice_receipt_sha256": evidence["compatibility_slice_receipt"].sha256,
        "controller_started_at": _format_utc(controller_started_at),
        "execution_ordinal": 1,
        "format_inspection_receipt_sha256": evidence["format_inspection_receipt"].sha256,
        "git_revision": git_revision,
        "one_use_policy": _ONE_USE_POLICY,
        "payload_access_state": "not_started_at_claim_publication",
        "probe_spec_sha256": authorization.spec_identity.sha256,
        "record_type": _CLAIM_RECORD_TYPE,
        "schema_version": _SCHEMA_VERSION,
    }


def _validate_claim_mapping(
    value: object,
    *,
    authorization: RealCsvGrammarProbeAuthorization,
    expected: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    claim = _mapping(
        value,
        field="real-CSV grammar-probe claim",
        keys={
            "record_type",
            "schema_version",
            "authorization_id",
            "authorization_sha256",
            "probe_spec_sha256",
            "adapter_contract_sha256",
            "compatibility_slice_receipt_sha256",
            "format_inspection_receipt_sha256",
            "controller_started_at",
            "claim_prepared_at",
            "git_revision",
            "execution_ordinal",
            "payload_access_state",
            "one_use_policy",
        },
    )
    evidence = dict(authorization.spec.source_evidence)
    literals: dict[str, object] = {
        "record_type": _CLAIM_RECORD_TYPE,
        "schema_version": _SCHEMA_VERSION,
        "authorization_id": authorization.authorization_id,
        "authorization_sha256": authorization.authorization_sha256,
        "probe_spec_sha256": authorization.spec_identity.sha256,
        "adapter_contract_sha256": _CONTRACT_SHA256,
        "compatibility_slice_receipt_sha256": evidence["compatibility_slice_receipt"].sha256,
        "format_inspection_receipt_sha256": evidence["format_inspection_receipt"].sha256,
        "execution_ordinal": 1,
        "payload_access_state": "not_started_at_claim_publication",
        "one_use_policy": _ONE_USE_POLICY,
    }
    for field, literal in literals.items():
        _literal(claim[field], literal, field=f"claim.{field}")
    _utc_timestamp(claim["controller_started_at"], field="claim.controller_started_at")
    _utc_timestamp(claim["claim_prepared_at"], field="claim.claim_prepared_at")
    if (
        type(claim["git_revision"]) is not str
        or _GIT_REVISION_PATTERN.fullmatch(claim["git_revision"]) is None
    ):
        raise AcquisitionError("claim.git_revision must be a full lowercase Git revision")
    if expected is not None and claim != expected:
        raise AcquisitionError("claim bytes do not encode this invocation's exact claim")
    return claim


def _stat_bound_entry(
    binding: _BoundRepoParent,
    leaf: str,
    *,
    field: str,
    allow_missing: bool,
) -> os.stat_result | None:
    try:
        metadata = os.stat(leaf, dir_fd=binding.descriptor, follow_symlinks=False)
    except FileNotFoundError:
        if allow_missing:
            _assert_bound_repo_parent(binding, field=field)
            return None
        raise AcquisitionError(f"checked {field} is missing") from None
    except OSError as exc:
        raise AcquisitionError(f"cannot inspect checked {field}") from exc
    _assert_bound_repo_parent(binding, field=field)
    return metadata


@contextmanager
def _bound_parent_for_path(
    path: Path,
    *,
    field: str,
    parent_binding: _BoundRepoParent | None,
) -> Iterator[tuple[_BoundRepoParent, str]]:
    if parent_binding is not None:
        yield parent_binding, _bound_leaf_for_path(path, parent_binding, field=field)
        return
    with ExitStack() as cleanup:
        binding, leaf = _bind_absolute_file_parent(path, field=field, cleanup=cleanup)
        yield binding, leaf


def _mask_publication_signals(*, field: str) -> set[signal.Signals]:
    if not hasattr(signal, "pthread_sigmask"):
        raise AcquisitionError(f"checked {field} publication requires POSIX signal masking")
    try:
        return signal.pthread_sigmask(
            signal.SIG_BLOCK,
            {signal.SIGALRM, signal.SIGINT, signal.SIGTERM},
        )
    except (OSError, ValueError) as exc:
        raise AcquisitionError(f"cannot mask signals for checked {field} publication") from exc


def _restore_publication_signals(previous_mask: set[signal.Signals], *, field: str) -> None:
    try:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    except (OSError, ValueError) as exc:
        raise AcquisitionError(f"cannot restore signals after checked {field} publication") from exc


def _unlink_exact_staged(
    binding: _BoundRepoParent,
    leaf: str,
    identity: tuple[int, int],
    *,
    field: str,
    allow_missing: bool,
) -> None:
    metadata = _stat_bound_entry(binding, leaf, field=field, allow_missing=allow_missing)
    if metadata is None:
        return
    if (metadata.st_dev, metadata.st_ino) != identity or not stat.S_ISREG(metadata.st_mode):
        raise AcquisitionError(f"checked {field} staged identity changed")
    try:
        os.unlink(leaf, dir_fd=binding.descriptor)
        os.fsync(binding.descriptor)
    except OSError as exc:
        raise AcquisitionError(f"cannot retract checked {field} staged file") from exc
    if _stat_bound_entry(binding, leaf, field=field, allow_missing=True) is not None:
        raise AcquisitionError(f"checked {field} staged file remains after retraction")


def _publish_new_bound_atomic(
    path: Path,
    payload: bytes,
    *,
    maximum_bytes: int,
    field: str,
    parent_binding: _BoundRepoParent | None,
    ownership: _ReceiptOwnership | None,
) -> _ReceiptPublication:
    """Create and durably link one exact file through a retained output-parent FD."""

    if len(payload) > maximum_bytes:
        raise AcquisitionError(f"checked {field} payload exceeds its byte bound")
    digest = hashlib.sha256(payload).hexdigest()
    with _bound_parent_for_path(
        path,
        field=field,
        parent_binding=parent_binding,
    ) as (binding, leaf):
        bound_path = binding.root_path.joinpath(*binding.relative_parent, leaf)
        if _stat_bound_entry(binding, leaf, field=field, allow_missing=True) is not None:
            raise AcquisitionError(f"refusing to overwrite a {field}")
        staged_leaf = f".{leaf}.staged-{os.getpid()}-{time.time_ns()}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        staged_identity: tuple[int, int] | None = None
        staged_removed = False
        try:
            try:
                descriptor = os.open(
                    staged_leaf,
                    flags,
                    0o600,
                    dir_fd=binding.descriptor,
                )
            except OSError as exc:
                raise AcquisitionError(f"cannot create staged {field}") from exc
            try:
                initial = os.fstat(descriptor)
                if not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1:
                    raise AcquisitionError(
                        f"staged {field} must begin as one regular single-link file"
                    )
                staged_identity = (initial.st_dev, initial.st_ino)
                written = 0
                while written < len(payload):
                    try:
                        count = os.write(descriptor, payload[written:])
                    except OSError as exc:
                        raise AcquisitionError(f"cannot write staged {field}") from exc
                    if count <= 0:
                        raise AcquisitionError(f"short write while creating staged {field}")
                    written += count
                os.fsync(descriptor)
                final = os.fstat(descriptor)
                if (
                    not stat.S_ISREG(final.st_mode)
                    or final.st_nlink != 1
                    or (final.st_dev, final.st_ino) != staged_identity
                    or final.st_size != len(payload)
                ):
                    raise AcquisitionError(f"staged {field} lost its owned inode binding")
            finally:
                os.close(descriptor)
            if (
                staged_identity is None
                or _assert_exact_gate3_file(
                    bound_path.with_name(staged_leaf),
                    payload,
                    maximum_bytes=maximum_bytes,
                    field=f"staged {field}",
                    expected_device_inode=staged_identity,
                    parent_binding=binding,
                )
                != digest
            ):
                raise AcquisitionError(f"staged {field} digest mismatch")
            previous_mask = _mask_publication_signals(field=field)
            publication: _ReceiptPublication | None = None
            try:
                publication = _ReceiptPublication(digest, *staged_identity)
                if ownership is not None:
                    ownership.publication = publication
                    ownership.payload = payload
                try:
                    os.link(
                        staged_leaf,
                        leaf,
                        src_dir_fd=binding.descriptor,
                        dst_dir_fd=binding.descriptor,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise AcquisitionError(f"refusing to overwrite a {field}") from exc
                except OSError as exc:
                    raise AcquisitionError(f"cannot publish {field}") from exc
                os.fsync(binding.descriptor)
            finally:
                _restore_publication_signals(previous_mask, field=field)
            if publication is None:
                raise AcquisitionError(f"checked {field} publication identity was not armed")
            if (
                _assert_exact_gate3_file(
                    bound_path,
                    payload,
                    maximum_bytes=maximum_bytes,
                    field=field,
                    expected_device_inode=staged_identity,
                    parent_binding=binding,
                    required_link_count=2,
                )
                != digest
            ):
                raise AcquisitionError(f"published {field} digest mismatch")
            _unlink_exact_staged(
                binding,
                staged_leaf,
                staged_identity,
                field=field,
                allow_missing=False,
            )
            staged_removed = True
            if (
                _assert_exact_gate3_file(
                    bound_path,
                    payload,
                    maximum_bytes=maximum_bytes,
                    field=field,
                    expected_device_inode=staged_identity,
                    parent_binding=binding,
                )
                != digest
            ):
                raise AcquisitionError(f"published {field} digest mismatch")
            return publication
        finally:
            if staged_identity is not None and not staged_removed:
                _unlink_exact_staged(
                    binding,
                    staged_leaf,
                    staged_identity,
                    field=field,
                    allow_missing=True,
                )


def _write_new_atomic(
    path: Path,
    payload: bytes,
    *,
    parent_binding: _BoundRepoParent | None = None,
) -> str:
    """Durably publish the one-use claim through its retained parent descriptor."""

    return _publish_new_bound_atomic(
        path,
        payload,
        maximum_bytes=_MAXIMUM_CLAIM_BYTES,
        field="probe claim",
        parent_binding=parent_binding,
        ownership=None,
    ).sha256


def _write_owned_receipt_atomic(
    path: Path,
    payload: bytes,
    *,
    ownership: _ReceiptOwnership,
    parent_binding: _BoundRepoParent | None = None,
) -> _ReceiptPublication:
    """Publish a receipt and record its exact inode before any catchable signal."""

    return _publish_new_bound_atomic(
        path,
        payload,
        maximum_bytes=_MAXIMUM_RECEIPT_BYTES,
        field="probe receipt",
        parent_binding=parent_binding,
        ownership=ownership,
    )


def _assert_owned_receipt(
    path: Path,
    payload: bytes,
    publication: _ReceiptPublication,
    *,
    parent_binding: _BoundRepoParent | None = None,
) -> str:
    return _assert_exact_gate3_file(
        path,
        payload,
        maximum_bytes=_MAXIMUM_RECEIPT_BYTES,
        field="real-CSV grammar-probe receipt",
        expected_device_inode=(publication.device, publication.inode),
        parent_binding=parent_binding,
    )


@contextmanager
def _rollback_owned_receipt_on_failure(
    path: Path,
    ownership: _ReceiptOwnership,
    *,
    parent_binding: _BoundRepoParent | None = None,
) -> Iterator[None]:
    try:
        yield
    except BaseException:
        publication = ownership.publication
        payload = ownership.payload
        if publication is not None and payload is not None:
            with _bound_parent_for_path(
                path,
                field="owned probe receipt rollback",
                parent_binding=parent_binding,
            ) as (binding, leaf):
                metadata = _stat_bound_entry(
                    binding,
                    leaf,
                    field="owned probe receipt rollback",
                    allow_missing=True,
                )
                if metadata is not None and (metadata.st_dev, metadata.st_ino) == (
                    publication.device,
                    publication.inode,
                ):
                    if (
                        hashlib.sha256(
                            _read_exact_at(
                                binding,
                                leaf,
                                expected=payload,
                                maximum_bytes=_MAXIMUM_RECEIPT_BYTES,
                                field="owned probe receipt rollback",
                                expected_device_inode=(publication.device, publication.inode),
                                required_link_count=1,
                                allow_additional_links=True,
                            )
                        ).hexdigest()
                        != hashlib.sha256(payload).hexdigest()
                    ):
                        raise AcquisitionError(
                            "cannot safely retract changed owned probe receipt"
                        ) from None
                    previous_mask = _mask_publication_signals(field="owned probe receipt rollback")
                    try:
                        try:
                            os.unlink(leaf, dir_fd=binding.descriptor)
                            os.fsync(binding.descriptor)
                        except OSError as exc:
                            raise AcquisitionError("cannot retract owned probe receipt") from exc
                    finally:
                        _restore_publication_signals(
                            previous_mask,
                            field="owned probe receipt rollback",
                        )
                    if (
                        _stat_bound_entry(
                            binding,
                            leaf,
                            field="owned probe receipt rollback",
                            allow_missing=True,
                        )
                        is not None
                    ):
                        raise AcquisitionError(
                            "owned probe receipt remains after rollback"
                        ) from None
        raise


@contextmanager
def _bound_probe_output_parent(
    root: Path,
    claim_relative: str,
    receipt_relative: str,
) -> Iterator[_BoundRepoParent]:
    claim_canonical = _canonical_relative(claim_relative, field="probe claim path")
    receipt_canonical = _canonical_relative(receipt_relative, field="probe receipt path")
    claim_parts = PurePosixPath(claim_canonical).parts
    receipt_parts = PurePosixPath(receipt_canonical).parts
    if claim_parts[:-1] != receipt_parts[:-1] or claim_parts[-1] == receipt_parts[-1]:
        raise AcquisitionError("probe claim and receipt require one exact shared output parent")
    with ExitStack() as cleanup:
        binding, claim_leaf = _bind_repo_file_parent(
            root,
            claim_canonical,
            field="probe output parent",
            cleanup=cleanup,
        )
        if claim_leaf != claim_parts[-1]:
            raise AcquisitionError("probe claim leaf binding changed")
        _bound_leaf_for_path(root / receipt_canonical, binding, field="probe receipt")
        yield binding


@contextmanager
def _bound_probe_output_deadline(
    root: Path,
    authorization: RealCsvGrammarProbeAuthorization,
    *,
    receipt_path: Path,
    ownership: _ReceiptOwnership,
    started_monotonic: float,
) -> Iterator[tuple[_BoundRepoParent, datetime]]:
    """Bind outputs and keep rollback outside every deadline teardown."""

    with _bound_probe_output_parent(
        root,
        authorization.outputs.claim_path,
        authorization.outputs.receipt_path,
    ) as binding:
        with _rollback_owned_receipt_on_failure(
            receipt_path,
            ownership,
            parent_binding=binding,
        ):
            claim_prepared_at = _utc_now()
            elapsed = _check_deadline(
                started_monotonic,
                authorization.maximum_elapsed_seconds,
                phase="post-output-binding pre-claim validation",
            )
            remaining = authorization.maximum_elapsed_seconds - elapsed
            if remaining <= 0:
                raise AcquisitionError("elapsed-time bound expired before claim")
            if not authorization.authorized_at <= claim_prepared_at < authorization.expires_at:
                raise AcquisitionError("authorization is not active immediately before claim")
            if remaining > (authorization.expires_at - claim_prepared_at).total_seconds():
                raise AcquisitionError(
                    "authorization lifetime is shorter than remaining execution bound"
                )
            with _hard_deadline(remaining):
                yield binding, claim_prepared_at


def _stream_document(stream: StreamAggregate) -> dict[str, object]:
    return {
        "bytes_read": stream.bytes_read,
        "check_states": dict(stream.check_states),
        "contract_source_path": stream.contract_source_path,
        "first_violation": (
            asdict(stream.first_violation) if stream.first_violation is not None else None
        ),
        "grammar_state": stream.grammar_state,
        "physical_line_count": stream.physical_line_count,
        "role": stream.role,
        "slice_relative_path": stream.slice_relative_path,
        "source_sha256": stream.source_sha256,
        "source_size_bytes": stream.source_size_bytes,
        "total_data_line_count": stream.total_data_line_count,
        "validated_data_row_count": stream.validated_data_row_count,
    }


def _readiness_document() -> dict[str, bool]:
    return {field: False for field in _READINESS_FIELDS}


def _receipt_document(
    authorization: RealCsvGrammarProbeAuthorization,
    *,
    claim_sha256: str,
    controller_started_at: datetime,
    receipt_prepared_at: datetime,
    git_revision: str,
    elapsed_seconds: float,
    initial_free_bytes: int,
    free_bytes_before_receipt: int,
    streams: tuple[StreamAggregate, ...],
) -> dict[str, object]:
    accepts = all(stream.grammar_state == "accepted" for stream in streams)
    grammar_outcome = _GRAMMAR_OUTCOMES[0] if accepts else _GRAMMAR_OUTCOMES[1]
    return {
        "authorization": {
            "id": authorization.authorization_id,
            "path": authorization.authorization_path,
            "sha256": authorization.authorization_sha256,
        },
        "capacity": {
            "authorized_minimum_free_bytes": authorization.minimum_free_bytes,
            "free_bytes_before_receipt": free_bytes_before_receipt,
            "initial_free_bytes": initial_free_bytes,
            "maximum_claim_bytes": _MAXIMUM_CLAIM_BYTES,
            "maximum_receipt_bytes": _MAXIMUM_RECEIPT_BYTES,
            "post_probe_reserve_bytes": _POST_PROBE_RESERVE_BYTES,
        },
        "claim": {"path": authorization.outputs.claim_path, "sha256": claim_sha256},
        "controller_started_at": _format_utc(controller_started_at),
        "execution": {
            "controller_initiated_paid_service_cost_usd": 0,
            "elapsed_seconds_at_receipt_preparation": elapsed_seconds,
            "git_revision": git_revision,
            "maximum_elapsed_seconds": authorization.maximum_elapsed_seconds,
            "tool_files": [asdict(item) for item in authorization.tool_files],
        },
        "execution_outcome": "completed",
        "grammar": {
            "contract_id": _CONTRACT_ID,
            "contract_path": _CONTRACT_PATH,
            "contract_sha256": _CONTRACT_SHA256,
            "grammar_outcome": grammar_outcome,
            "observation_policy": (
                "aggregate-only-no-source-row-token-timestamp-filename-header-or-numeric-values/v1"
            ),
            "streams": [_stream_document(stream) for stream in streams],
        },
        "limitations": list(_LIMITATIONS),
        "operations_not_performed": list(_PROHIBITED_OPERATIONS),
        "operations_performed": list(_SUCCESS_OPERATIONS),
        "readiness": _readiness_document(),
        "receipt_prepared_at": _format_utc(receipt_prepared_at),
        "record_type": _RECEIPT_RECORD_TYPE,
        "retention": {
            "deletion_authorized": False,
            "policy": "retain_real_csv_grammar_probe_evidence_until_review",
            "review_at": _format_utc(authorization.retention_review_at),
        },
        "schema_version": _SCHEMA_VERSION,
        "scientific_authority": _SCIENTIFIC_AUTHORITY,
        "source": {
            "probe_spec": asdict(authorization.spec_identity),
            "root_path": authorization.spec.source_root,
            "source_scope": authorization.spec.source_scope,
        },
    }


def run_authorized_real_csv_grammar_probe(
    authorization_path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str | None = None,
) -> RealCsvGrammarProbeResult:
    """Run one authorized probe; a durable claim irreversibly precedes payload open."""

    root = Path(repo_root or Path.cwd()).resolve()
    authorization = load_real_csv_grammar_probe_authorization(authorization_path, repo_root=root)
    controller_started_at = _utc_now()
    started_monotonic = time.monotonic()
    if not authorization.authorized_at <= controller_started_at < authorization.expires_at:
        raise AcquisitionError("authorization is not active at execution start")
    if (
        authorization.maximum_elapsed_seconds
        > (authorization.expires_at - controller_started_at).total_seconds()
    ):
        raise AcquisitionError("remaining authorization lifetime is shorter than execution bound")
    revision = _assert_clean_repository(root)
    _runtime_sources(root)
    for evidence in _tracked_evidence(authorization):
        _assert_tracked_gate3_bytes(
            root,
            evidence.path,
            evidence.sha256,
            expected_revision=revision,
        )
    for tool in authorization.tool_files:
        _assert_tracked_gate3_bytes(
            root,
            tool.path,
            tool.sha256,
            expected_revision=revision,
        )

    spec = authorization.spec
    if not _is_ignored(root, spec.source_root):
        raise AcquisitionError("receipt-bound source root must remain Git-ignored")
    for relative in (authorization.outputs.claim_path, authorization.outputs.receipt_path):
        if _is_ignored(root, relative):
            raise AcquisitionError("probe claim and receipt paths must remain trackable")
    claim_path = root / authorization.outputs.claim_path
    receipt_path = root / authorization.outputs.receipt_path
    initial_free_bytes = _disk_usage(root).free
    if initial_free_bytes < authorization.minimum_free_bytes:
        raise AcquisitionError("insufficient free space for probe claim, receipt, and reserve")
    _check_deadline(
        started_monotonic,
        authorization.maximum_elapsed_seconds,
        phase="pre-claim validation",
    )

    ownership = _ReceiptOwnership()
    receipt_sha256: str | None = None
    grammar_outcome: str | None = None
    with _bound_probe_output_deadline(
        root,
        authorization,
        receipt_path=receipt_path,
        ownership=ownership,
        started_monotonic=started_monotonic,
    ) as (output_binding, claim_prepared_at):
        claim = _claim_document(
            authorization,
            controller_started_at=controller_started_at,
            claim_prepared_at=claim_prepared_at,
            git_revision=revision,
        )
        _validate_claim_mapping(claim, authorization=authorization, expected=claim)
        claim_bytes = _canonical_json_bytes(claim)
        if len(claim_bytes) > _MAXIMUM_CLAIM_BYTES:
            raise AcquisitionError("probe claim exceeds its byte bound")
        claim_leaf = _bound_leaf_for_path(claim_path, output_binding, field="probe claim")
        receipt_leaf = _bound_leaf_for_path(receipt_path, output_binding, field="probe receipt")
        if (
            _stat_bound_entry(
                output_binding,
                claim_leaf,
                field="probe claim",
                allow_missing=True,
            )
            is not None
            or _stat_bound_entry(
                output_binding,
                receipt_leaf,
                field="probe receipt",
                allow_missing=True,
            )
            is not None
        ):
            raise AcquisitionError("one-use probe claim and receipt must both be absent")
        claim_sha256 = _write_new_atomic(
            claim_path,
            claim_bytes,
            parent_binding=output_binding,
        )
        _assert_repository_state(
            root,
            authorization,
            expected_revision=revision,
            expected_outputs=(authorization.outputs.claim_path,),
        )
        if (
            _assert_exact_gate3_file(
                claim_path,
                claim_bytes,
                maximum_bytes=_MAXIMUM_CLAIM_BYTES,
                field="probe claim",
                parent_binding=output_binding,
            )
            != claim_sha256
        ):
            raise AcquisitionError("probe claim changed before payload access")
        with ExitStack() as source_cleanup:
            tree = _bind_exact_sources_after_claim(
                root / spec.source_root,
                spec.files,
                cleanup=source_cleanup,
                repository_root=root,
                source_root_relative=spec.source_root,
            )
            streams = _scan_bound_sources(tree)
            _assert_bound_sources(tree)
            _check_deadline(
                started_monotonic,
                authorization.maximum_elapsed_seconds,
                phase="payload grammar scan",
            )
            if (authorization.expires_at - _utc_now()).total_seconds() < 5:
                raise AcquisitionError("authorization expires too soon for receipt publication")
            _assert_repository_state(
                root,
                authorization,
                expected_revision=revision,
                expected_outputs=(authorization.outputs.claim_path,),
            )
            _assert_bound_sources(tree)
            if (
                _assert_exact_gate3_file(
                    claim_path,
                    claim_bytes,
                    maximum_bytes=_MAXIMUM_CLAIM_BYTES,
                    field="probe claim",
                    parent_binding=output_binding,
                )
                != claim_sha256
            ):
                raise AcquisitionError("probe claim changed before receipt preparation")
            if (
                _stat_bound_entry(
                    output_binding,
                    receipt_leaf,
                    field="probe receipt",
                    allow_missing=True,
                )
                is not None
            ):
                raise AcquisitionError("probe receipt appeared before publication")
            free_bytes_before_receipt = _disk_usage(root).free
            if free_bytes_before_receipt < (_POST_PROBE_RESERVE_BYTES + _MAXIMUM_RECEIPT_BYTES):
                raise AcquisitionError("insufficient retained reserve for probe receipt")
            elapsed = _check_deadline(
                started_monotonic,
                authorization.maximum_elapsed_seconds,
                phase="receipt preparation",
            )
            receipt_prepared_at = _utc_now()
            if (authorization.expires_at - receipt_prepared_at).total_seconds() < 5:
                raise AcquisitionError("authorization expired before receipt publication")
            receipt = _receipt_document(
                authorization,
                claim_sha256=claim_sha256,
                controller_started_at=controller_started_at,
                receipt_prepared_at=receipt_prepared_at,
                git_revision=revision,
                elapsed_seconds=elapsed,
                initial_free_bytes=initial_free_bytes,
                free_bytes_before_receipt=free_bytes_before_receipt,
                streams=streams,
            )
            grammar_outcome = str(receipt["grammar"]["grammar_outcome"])
            receipt_bytes = _canonical_json_bytes(receipt)
            if len(receipt_bytes) > _MAXIMUM_RECEIPT_BYTES:
                raise AcquisitionError("probe receipt exceeds its byte bound")

            _assert_repository_state(
                root,
                authorization,
                expected_revision=revision,
                expected_outputs=(authorization.outputs.claim_path,),
            )
            _assert_bound_sources(tree)
            if (
                _assert_exact_gate3_file(
                    claim_path,
                    claim_bytes,
                    maximum_bytes=_MAXIMUM_CLAIM_BYTES,
                    field="probe claim",
                    parent_binding=output_binding,
                )
                != claim_sha256
            ):
                raise AcquisitionError("probe claim changed before atomic receipt publication")
            if (
                _stat_bound_entry(
                    output_binding,
                    receipt_leaf,
                    field="probe receipt",
                    allow_missing=True,
                )
                is not None
            ):
                raise AcquisitionError("probe receipt appeared before atomic publication")
            publication = _write_owned_receipt_atomic(
                receipt_path,
                receipt_bytes,
                ownership=ownership,
                parent_binding=output_binding,
            )
            receipt_sha256 = publication.sha256
            for _ in range(2):
                _assert_repository_state(
                    root,
                    authorization,
                    expected_revision=revision,
                    expected_outputs=(
                        authorization.outputs.claim_path,
                        authorization.outputs.receipt_path,
                    ),
                )
                _assert_bound_sources(tree)
                if (
                    _assert_exact_gate3_file(
                        claim_path,
                        claim_bytes,
                        maximum_bytes=_MAXIMUM_CLAIM_BYTES,
                        field="probe claim",
                        parent_binding=output_binding,
                    )
                    != claim_sha256
                ):
                    raise AcquisitionError("probe claim changed during final truth gate")
                if (
                    _assert_owned_receipt(
                        receipt_path,
                        receipt_bytes,
                        publication,
                        parent_binding=output_binding,
                    )
                    != receipt_sha256
                ):
                    raise AcquisitionError("probe receipt changed during final truth gate")
                _check_deadline(
                    started_monotonic,
                    authorization.maximum_elapsed_seconds,
                    phase="final truth gate",
                )
    if receipt_sha256 is None or grammar_outcome not in _GRAMMAR_OUTCOMES:
        raise AcquisitionError("probe completed without a terminal receipt identity")
    return RealCsvGrammarProbeResult(
        authorization.authorization_id,
        grammar_outcome,
        claim_path,
        receipt_path,
        receipt_sha256,
    )


def _load_stream_aggregate(
    value: object, *, expected: ProbeSourceFile, field: str
) -> StreamAggregate:
    item = _mapping(
        value,
        field=field,
        keys={
            "role",
            "contract_source_path",
            "slice_relative_path",
            "source_size_bytes",
            "source_sha256",
            "bytes_read",
            "physical_line_count",
            "total_data_line_count",
            "validated_data_row_count",
            "grammar_state",
            "check_states",
            "first_violation",
        },
    )
    for name, expected_value in (
        ("role", expected.role),
        ("contract_source_path", expected.contract_source_path),
        ("slice_relative_path", expected.slice_relative_path),
        ("source_size_bytes", expected.source_size_bytes),
        ("source_sha256", expected.source_sha256),
        ("bytes_read", expected.source_size_bytes),
    ):
        _literal(item[name], expected_value, field=f"{field}.{name}")
    physical = _positive_exact_int(
        item["physical_line_count"], field=f"{field}.physical_line_count"
    )
    total_data = _non_negative_exact_int(
        item["total_data_line_count"], field=f"{field}.total_data_line_count"
    )
    validated = _non_negative_exact_int(
        item["validated_data_row_count"], field=f"{field}.validated_data_row_count"
    )
    if (
        physical > _MAXIMUM_CSV_ROWS + 1
        or physical > expected.source_size_bytes
        or total_data != max(physical - 1, 0)
        or validated > total_data
    ):
        raise AcquisitionError(f"{field} aggregate line accounting is inconsistent")
    grammar_state = _text(item["grammar_state"], field=f"{field}.grammar_state")
    if grammar_state not in _GRAMMAR_STATES:
        raise AcquisitionError(f"{field}.grammar_state is unsupported")
    expected_checks = _checks_for_role(expected.role)
    check_values = _mapping(
        item["check_states"], field=f"{field}.check_states", keys=set(expected_checks)
    )
    checks: dict[str, str] = {}
    for check in expected_checks:
        state = _text(check_values[check], field=f"{field}.check_states.{check}")
        if state not in _CHECK_STATES:
            raise AcquisitionError(f"{field}.check_states contains an invalid state")
        checks[check] = state
    if checks["source_identity"] != "pass":
        raise AcquisitionError(f"{field} must have a verified source identity")
    violation_value = item["first_violation"]
    violation: FirstViolation | None
    if violation_value is None:
        violation = None
    else:
        violation_item = _mapping(
            violation_value,
            field=f"{field}.first_violation",
            keys={"code", "physical_line_number"},
        )
        code = _text(violation_item["code"], field=f"{field}.first_violation.code")
        violation_checks = _violation_checks_for_role(expected.role)
        if code not in violation_checks:
            raise AcquisitionError(f"{field}.first_violation.code is not in the closed contract")
        line_number = _positive_exact_int(
            violation_item["physical_line_number"],
            field=f"{field}.first_violation.physical_line_number",
        )
        if line_number > physical + 1:
            raise AcquisitionError(f"{field}.first_violation line is outside aggregate bounds")
        violation = FirstViolation(code, line_number)
    if grammar_state == "accepted":
        if (
            violation is not None
            or any(state != "pass" for state in checks.values())
            or validated != total_data
            or total_data < 1
        ):
            raise AcquisitionError(f"{field} accepted state is inconsistent")
    else:
        if violation is None:
            raise AcquisitionError(f"{field} rejected state requires a closed violation")
        expected_failed_check = _violation_checks_for_role(expected.role)[violation.code]
        failed_checks = {name for name, state in checks.items() if state == "fail"}
        allowed_failed_checks = {expected_failed_check}
        if expected.role in ("cam0", "cam1"):
            allowed_failed_checks.add("stereo_raw_lockstep")
        if expected_failed_check not in failed_checks or not failed_checks <= allowed_failed_checks:
            raise AcquisitionError(f"{field} violation and failed check are inconsistent")
        if validated != max(violation.physical_line_number - 2, 0):
            raise AcquisitionError(f"{field} validated-row count is impossible for first failure")
        transition_checks = {name: "not_reached" for name in expected_checks}
        transition_checks["source_identity"] = "pass"
        if violation.physical_line_number > 1:
            transition_checks["exact_header"] = "pass"
        transition_checks[expected_failed_check] = "fail"
        if expected.role in ("cam0", "cam1"):
            stereo_state = checks["stereo_raw_lockstep"]
            if stereo_state not in ("pass", "fail"):
                raise AcquisitionError(f"{field} stereo check did not reach a terminal state")
            transition_checks["stereo_raw_lockstep"] = stereo_state
        if checks != transition_checks:
            raise AcquisitionError(f"{field} check states are impossible for first failure")
        if violation.code == "exact_header_mismatch" and violation.physical_line_number != 1:
            raise AcquisitionError(f"{field} header violation must be on physical line one")
        if violation.code == "minimum_data_rows" and (
            total_data != 0 or violation.physical_line_number != physical + 1
        ):
            raise AcquisitionError(f"{field} minimum-row violation location is inconsistent")
        if (
            violation.code
            not in {
                "minimum_data_rows",
                "stereo_simultaneous_eof_mismatch",
            }
            and violation.physical_line_number > physical
        ):
            raise AcquisitionError(f"{field} violation cannot occur after the final physical line")
        if violation.code == "final_line_missing_lf" and violation.physical_line_number != physical:
            raise AcquisitionError(f"{field} missing-LF violation must be on the final line")
        data_line_codes = {
            "blank_data_row",
            "comment_data_row",
            "data_row_arity",
            "timestamp_lexeme",
            "timestamp_range",
            "timestamp_not_strictly_increasing",
            "camera_filename_lexeme",
            "camera_filename_stem",
            "numeric_lexeme",
        }
        if violation.code in data_line_codes and not (
            2 <= violation.physical_line_number <= physical
        ):
            raise AcquisitionError(f"{field} data-row violation location is inconsistent")
    return StreamAggregate(
        expected.role,
        expected.contract_source_path,
        expected.slice_relative_path,
        expected.source_size_bytes,
        expected.source_sha256,
        expected.source_size_bytes,
        physical,
        total_data,
        validated,
        grammar_state,
        checks,
        violation,
    )


def load_real_csv_grammar_probe_receipt(
    path: os.PathLike[str] | str, *, repo_root: os.PathLike[str] | str
) -> CheckedRealCsvGrammarProbeReceipt:
    """Validate terminal claim/receipt/evidence bytes without opening payload paths."""

    root_path = Path(repo_root).resolve()
    _, relative = _resolve_repo_file(path, repo_root=root_path, field="probe receipt path")
    _literal(relative, _RECEIPT_PATH, field="probe receipt path")
    raw, parsed = _read_repo_json(
        root_path,
        relative,
        maximum_bytes=_MAXIMUM_RECEIPT_BYTES,
        field="real-CSV grammar-probe receipt",
    )
    root = _mapping(
        parsed,
        field="real-CSV grammar-probe receipt",
        keys={
            "authorization",
            "capacity",
            "claim",
            "controller_started_at",
            "execution",
            "execution_outcome",
            "grammar",
            "limitations",
            "operations_not_performed",
            "operations_performed",
            "readiness",
            "receipt_prepared_at",
            "record_type",
            "retention",
            "schema_version",
            "scientific_authority",
            "source",
        },
    )
    _literal(root["record_type"], _RECEIPT_RECORD_TYPE, field="record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="schema_version")
    _literal(root["execution_outcome"], "completed", field="execution_outcome")
    _literal(root["scientific_authority"], _SCIENTIFIC_AUTHORITY, field="scientific_authority")
    authorization_identity = _mapping(
        root["authorization"],
        field="authorization",
        keys={"id", "path", "sha256"},
    )
    _literal(authorization_identity["id"], _AUTHORIZATION_ID, field="authorization.id")
    _literal(authorization_identity["path"], _AUTHORIZATION_PATH, field="authorization.path")
    authorization_sha256 = _sha256(authorization_identity["sha256"], field="authorization.sha256")
    authorization = load_real_csv_grammar_probe_authorization(
        root_path / _AUTHORIZATION_PATH, repo_root=root_path
    )
    _literal(
        authorization_sha256,
        authorization.authorization_sha256,
        field="authorization.sha256",
    )

    claim_identity = _mapping(root["claim"], field="claim", keys={"path", "sha256"})
    _literal(claim_identity["path"], _CLAIM_PATH, field="claim.path")
    claim_sha256 = _sha256(claim_identity["sha256"], field="claim.sha256")
    claim_raw, claim_parsed = _read_repo_json(
        root_path,
        _CLAIM_PATH,
        maximum_bytes=_MAXIMUM_CLAIM_BYTES,
        field="real-CSV grammar-probe claim",
    )
    _literal(hashlib.sha256(claim_raw).hexdigest(), claim_sha256, field="claim.sha256")
    claim = _validate_claim_mapping(claim_parsed, authorization=authorization)

    controller_started_at = _utc_timestamp(
        root["controller_started_at"], field="controller_started_at"
    )
    receipt_prepared_at = _utc_timestamp(root["receipt_prepared_at"], field="receipt_prepared_at")
    _literal(
        root["controller_started_at"],
        claim["controller_started_at"],
        field="controller_started_at claim binding",
    )
    claim_prepared_at = _utc_timestamp(claim["claim_prepared_at"], field="claim.claim_prepared_at")
    if not (
        authorization.authorized_at
        <= controller_started_at
        <= claim_prepared_at
        <= receipt_prepared_at
        < authorization.expires_at
    ):
        raise AcquisitionError("receipt chronology is outside the live authorization window")
    if (
        authorization.expires_at - controller_started_at
    ).total_seconds() < authorization.maximum_elapsed_seconds:
        raise AcquisitionError("recorded controller start lacks the full execution authority")

    capacity = _mapping(
        root["capacity"],
        field="capacity",
        keys={
            "authorized_minimum_free_bytes",
            "free_bytes_before_receipt",
            "initial_free_bytes",
            "maximum_claim_bytes",
            "maximum_receipt_bytes",
            "post_probe_reserve_bytes",
        },
    )
    for field, expected in (
        ("authorized_minimum_free_bytes", _MINIMUM_FREE_BYTES),
        ("maximum_claim_bytes", _MAXIMUM_CLAIM_BYTES),
        ("maximum_receipt_bytes", _MAXIMUM_RECEIPT_BYTES),
        ("post_probe_reserve_bytes", _POST_PROBE_RESERVE_BYTES),
    ):
        _literal(capacity[field], expected, field=f"capacity.{field}")
    initial_free = _non_negative_exact_int(
        capacity["initial_free_bytes"], field="capacity.initial_free_bytes"
    )
    free_before_receipt = _non_negative_exact_int(
        capacity["free_bytes_before_receipt"], field="capacity.free_bytes_before_receipt"
    )
    if initial_free < _MINIMUM_FREE_BYTES:
        raise AcquisitionError("recorded initial capacity is below the authorized minimum")
    if free_before_receipt < _POST_PROBE_RESERVE_BYTES + _MAXIMUM_RECEIPT_BYTES:
        raise AcquisitionError("recorded receipt capacity is below the retained reserve")

    execution = _mapping(
        root["execution"],
        field="execution",
        keys={
            "controller_initiated_paid_service_cost_usd",
            "elapsed_seconds_at_receipt_preparation",
            "git_revision",
            "maximum_elapsed_seconds",
            "tool_files",
        },
    )
    _literal(execution["controller_initiated_paid_service_cost_usd"], 0, field="execution.cost")
    elapsed = execution["elapsed_seconds_at_receipt_preparation"]
    if (
        type(elapsed) not in (int, float)
        or not math.isfinite(elapsed)
        or elapsed < 0
        or elapsed > _MAXIMUM_ELAPSED_SECONDS
    ):
        raise AcquisitionError("execution elapsed seconds are outside the authorized bound")
    revision = execution["git_revision"]
    if type(revision) is not str or _GIT_REVISION_PATTERN.fullmatch(revision) is None:
        raise AcquisitionError("execution.git_revision is invalid")
    _literal(revision, claim["git_revision"], field="execution.git_revision claim binding")
    _literal(
        execution["maximum_elapsed_seconds"],
        _MAXIMUM_ELAPSED_SECONDS,
        field="execution.maximum_elapsed_seconds",
    )
    tool_values = execution["tool_files"]
    if type(tool_values) is not list:
        raise AcquisitionError("execution.tool_files must be a JSON array")
    parsed_tools = tuple(
        ToolIdentity(
            _canonical_relative(
                _mapping(
                    value,
                    field=f"execution.tool_files[{index}]",
                    keys={"path", "sha256"},
                )["path"],
                field=f"execution.tool_files[{index}].path",
            ),
            _sha256(
                _mapping(
                    value,
                    field=f"execution.tool_files[{index}]",
                    keys={"path", "sha256"},
                )["sha256"],
                field=f"execution.tool_files[{index}].sha256",
            ),
        )
        for index, value in enumerate(tool_values)
    )
    _literal(parsed_tools, authorization.tool_files, field="execution.tool_files")

    grammar = _mapping(
        root["grammar"],
        field="grammar",
        keys={
            "contract_id",
            "contract_path",
            "contract_sha256",
            "grammar_outcome",
            "observation_policy",
            "streams",
        },
    )
    for field, expected in (
        ("contract_id", _CONTRACT_ID),
        ("contract_path", _CONTRACT_PATH),
        ("contract_sha256", _CONTRACT_SHA256),
        (
            "observation_policy",
            "aggregate-only-no-source-row-token-timestamp-filename-header-or-numeric-values/v1",
        ),
    ):
        _literal(grammar[field], expected, field=f"grammar.{field}")
    grammar_outcome = _text(grammar["grammar_outcome"], field="grammar.grammar_outcome")
    if grammar_outcome not in _GRAMMAR_OUTCOMES:
        raise AcquisitionError("grammar.grammar_outcome is unsupported")
    stream_values = grammar["streams"]
    if type(stream_values) is not list or len(stream_values) != 4:
        raise AcquisitionError("grammar.streams must contain the exact four ordered streams")
    streams = tuple(
        _load_stream_aggregate(
            value,
            expected=expected,
            field=f"grammar.streams[{index}]",
        )
        for index, (value, expected) in enumerate(
            zip(stream_values, authorization.spec.files, strict=True)
        )
    )
    cam0, cam1 = streams[:2]
    stereo_states = (
        cam0.check_states["stereo_raw_lockstep"],
        cam1.check_states["stereo_raw_lockstep"],
    )
    if stereo_states[0] != stereo_states[1] or stereo_states[0] == "not_reached":
        raise AcquisitionError("camera aggregate states violate exact raw-lockstep consistency")
    if stereo_states[0] == "pass":
        if (
            cam0.source_size_bytes != cam1.source_size_bytes
            or cam0.source_sha256 != cam1.source_sha256
            or cam0.bytes_read != cam1.bytes_read
            or cam0.physical_line_count != cam1.physical_line_count
            or cam0.total_data_line_count != cam1.total_data_line_count
            or cam0.validated_data_row_count != cam1.validated_data_row_count
            or cam0.grammar_state != cam1.grammar_state
            or cam0.check_states != cam1.check_states
            or cam0.first_violation != cam1.first_violation
        ):
            raise AcquisitionError("camera aggregate states violate exact raw-lockstep consistency")
    elif (
        cam0.grammar_state != "rejected"
        or cam1.grammar_state != "rejected"
        or cam0.validated_data_row_count != cam1.validated_data_row_count
        or cam0.check_states != cam1.check_states
        or cam0.first_violation != cam1.first_violation
    ):
        raise AcquisitionError("failed camera lockstep must have one symmetric first failure")
    if (
        cam0.first_violation is not None
        and cam0.first_violation.code == "stereo_simultaneous_eof_mismatch"
        and cam0.first_violation.physical_line_number
        > max(cam0.physical_line_count, cam1.physical_line_count)
    ):
        raise AcquisitionError("camera EOF mismatch cannot occur after both final physical lines")
    expected_outcome = (
        _GRAMMAR_OUTCOMES[0]
        if all(stream.grammar_state == "accepted" for stream in streams)
        else _GRAMMAR_OUTCOMES[1]
    )
    _literal(grammar_outcome, expected_outcome, field="grammar.grammar_outcome consistency")

    source = _mapping(
        root["source"],
        field="source",
        keys={"probe_spec", "root_path", "source_scope"},
    )
    _literal(
        _evidence(source["probe_spec"], field="source.probe_spec"),
        authorization.spec_identity,
        field="source.probe_spec",
    )
    _literal(source["root_path"], _SOURCE_ROOT, field="source.root_path")
    _literal(source["source_scope"], _SOURCE_SCOPE, field="source.source_scope")
    _exact_string_list(
        root["operations_performed"], _SUCCESS_OPERATIONS, field="operations_performed"
    )
    _exact_string_list(
        root["operations_not_performed"],
        _PROHIBITED_OPERATIONS,
        field="operations_not_performed",
    )
    _exact_string_list(root["limitations"], _LIMITATIONS, field="limitations")
    readiness = _mapping(root["readiness"], field="readiness", keys=set(_READINESS_FIELDS))
    for field in _READINESS_FIELDS:
        _literal(readiness[field], False, field=f"readiness.{field}")
    retention = _mapping(
        root["retention"],
        field="retention",
        keys={"deletion_authorized", "policy", "review_at"},
    )
    _literal(retention["deletion_authorized"], False, field="retention.deletion_authorized")
    _literal(
        retention["policy"],
        "retain_real_csv_grammar_probe_evidence_until_review",
        field="retention.policy",
    )
    _literal(
        retention["review_at"],
        _format_utc(authorization.retention_review_at),
        field="retention.review_at",
    )
    return CheckedRealCsvGrammarProbeReceipt(
        relative,
        hashlib.sha256(raw).hexdigest(),
        authorization.authorization_id,
        grammar_outcome,
        streams,
        _SCIENTIFIC_AUTHORITY,
    )


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AcquisitionError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="compact-vio-probe-tumvi-real-csv-grammar",
        description="Execute one authorized aggregate-only TUM-VI real-CSV grammar probe.",
    )
    parser.add_argument("--authorization", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = run_authorized_real_csv_grammar_probe(args.authorization)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": {"message": str(exc), "type": type(exc).__name__},
                    "execution_outcome": "failed",
                    "scientific_authority": _SCIENTIFIC_AUTHORITY,
                    "status": "error",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "authorization_id": result.authorization_id,
                "grammar_outcome": result.grammar_outcome,
                "receipt_path": str(result.receipt_path),
                "receipt_sha256": result.receipt_sha256,
                "scientific_authority": _SCIENTIFIC_AUTHORITY,
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

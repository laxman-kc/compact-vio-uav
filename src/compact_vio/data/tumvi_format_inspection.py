"""One-use, non-scientific inspection of an exact opaque TUM VI format slice.

The controller may stream four CSV files and interpret only the first 33 bytes
of four PNG files.  Content mismatches are completed observations; broken
provenance, resources, I/O, or execution controls are operational failures.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import stat
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import compact_vio.data.acquisition as acquisition_module
import compact_vio.data.euroc as euroc_module
import compact_vio.data.tumvi_format as format_module
from compact_vio.data.acquisition import (
    AcquisitionError,
    ToolIdentity,
    _assert_clean_repository,
    _assert_exact_file,
    _assert_no_symlink_ancestors,
    _assert_tracked_head_bytes,
    _canonical_json_bytes,
    _canonical_relative,
    _check_deadline,
    _disk_usage,
    _exact_string_list,
    _format_utc,
    _hard_deadline,
    _identifier,
    _is_ignored,
    _literal,
    _mapping,
    _positive_int,
    _read_json_bytes,
    _sha256,
    _text,
    _utc_now,
    _utc_timestamp,
    _write_new_atomic,
)
from compact_vio.data.tumvi_format import (
    CsvInspectionLimits,
    CsvStructureObservation,
    PngIhdrContract,
    PngIhdrObservation,
    StereoCameraIndexObservation,
    TumviFormatError,
    inspect_numeric_csv,
    inspect_png_ihdr,
    inspect_stereo_camera_indexes,
)

_SCHEMA_VERSION = "1.0.0"
_SPEC_RECORD_TYPE = "dataset_format_inspection_spec"
_SPEC_ID = "tumvi-room4-512-16-format-inspection-v1"
_SPEC_SCOPE = "bounded-opaque-csv-and-png-ihdr-observation-only/v1"
_AUTHORIZATION_RECORD_TYPE = "dataset_format_inspection_authorization"
_AUTHORIZATION_SCOPE = "bounded_opaque_csv_and_png_ihdr_observation_only"
_PNG_STANDARD_ID = "W3C-PNG-Third-Edition-2025-06-24"
_PNG_STANDARD_URL = "https://www.w3.org/TR/2025/REC-png-3-20250624/"
_SLICE_DESTINATION = "data/quarantine/tum-vi/room4-512-16/tumvi-room4-512-16-compatibility-slice-v1"
_SPEC_PATH = "configs/data/tumvi_room4_512_16_format_inspection_v1.json"
_SLICE_RECEIPT = (
    "governance/datasets/acquisitions/"
    "tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json"
)
_SLICE_RECEIPT_SHA256 = "a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820"
_REVIEW_REPORT = "reports/tumvi-room4-512-16-compatibility-slice-2026-08-29.md"
_REVIEW_REPORT_SHA256 = "b1f4a346eeedd9d8dbadf92bf8042754d5ef640626cf4931265b1efa4b4c966e"
_CANDIDATE = "configs/data/tumvi_room4_512_16_candidate_v1.json"
_CANDIDATE_SHA256 = "0de942674afcadd2f768385a82c52b8cb65eea14d5e8c4d17dc9e48262023740"
_ADAPTER = "src/compact_vio/data/euroc.py"
_ADAPTER_SHA256 = "bfcddb06e7516d148253e8db38a7247ce51064ef13c28b934cdbb3980fc238fd"
_CLAIM_PATH = "data/quarantine/tum-vi/room4-512-16/format-inspection.claim.json"
_RECEIPT_PATH = (
    "governance/datasets/acquisitions/tumvi-room4-512-16-format-inspection-2026-08-29.receipt.json"
)
_TOOL_PATHS = (
    "src/compact_vio/data/tumvi_format_inspection.py",
    "src/compact_vio/data/tumvi_format.py",
    "src/compact_vio/data/acquisition.py",
)
_MAXIMUM_ELAPSED_SECONDS = 600
_MAXIMUM_CSV_ROWS = 1_000_000
_MAXIMUM_CSV_LINE_BYTES = 1_048_576
_MAXIMUM_CLAIM_BYTES = 1_048_576
_MAXIMUM_RECEIPT_BYTES = 1_048_576
_POST_INSPECTION_RESERVE_BYTES = 2_147_483_648
_MINIMUM_FREE_BYTES = 2_149_580_800
_PNG_INTERPRETED_BYTES = 33
_SOURCE_SIZE_BYTES = 5_043_300
_PERMITTED_OPERATIONS = (
    "write_claim",
    "verify_bound_spec_and_source_receipt",
    "verify_exact_slice_tree_as_opaque_bytes",
    "inspect_four_csv_structures",
    "inspect_four_png_signature_ihdr_records",
    "compare_frozen_format_predicates",
    "write_receipt",
    "retract_exact_new_receipt_on_truth_gate_failure",
)
_SUCCESS_OPERATIONS = _PERMITTED_OPERATIONS[:-1]
_PROHIBITED_OPERATIONS = (
    "network_access",
    "archive_access",
    "reextract_or_copy_files",
    "access_unlisted_files",
    "read_dso",
    "follow_links",
    "interpret_png_bytes_after_33",
    "decode_images",
    "decompress_images",
    "retain_sensor_row_values",
    "infer_units_frames_calibration_or_ground_truth",
    "resample_interpolate_or_correct_synchronization",
    "load_dataset_samples",
    "assign_protocol_membership",
    "select_dataset",
    "load_checkpoint",
    "train",
    "infer",
    "evaluate",
    "publish_scientific_result",
    "modify_or_delete_source_evidence",
)
_CROSS_FILE_CHECKS = (
    "cam0_cam1_index_bytes_equal",
    "selected_png_names_present_once_in_own_index",
    "selected_filename_stem_equals_row_timestamp",
    "selected_names_common_to_both_camera_indexes",
    "selected_camera_timestamps_within_observed_imu_range",
    "selected_camera_timestamps_within_observed_mocap_range",
    "four_png_ihdr_tuples_equal",
)
_LIMITATIONS = (
    "deterministic_four_png_headers_only_not_full_image_population",
    "csv_structure_does_not_establish_units_frames_or_semantics",
    "png_ihdr_does_not_establish_whole_file_validity_decodability_or_preprocessing",
    "full_indexed_image_existence_not_checked_sparse_slice",
    "mocap_reference_semantics_and_calibration_remain_uninterpreted",
    "does_not_select_dataset_or_assign_membership",
    "does_not_approve_model_access_training_inference_evaluation_or_publication",
)
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
_FULL_STATE_HEADER_SUFFIX = (
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
    "q_RS_w []",
    "q_RS_x []",
    "q_RS_y []",
    "q_RS_z []",
    "v_RS_R_x [m s^-1]",
    "v_RS_R_y [m s^-1]",
    "v_RS_R_z [m s^-1]",
    "b_w_RS_S_x [rad s^-1]",
    "b_w_RS_S_y [rad s^-1]",
    "b_w_RS_S_z [rad s^-1]",
    "b_a_RS_S_x [m s^-2]",
    "b_a_RS_S_y [m s^-2]",
    "b_a_RS_S_z [m s^-2]",
)
_FULL_STATE_HEADERS = (
    ("#timestamp",) + _FULL_STATE_HEADER_SUFFIX,
    _CAMERA_HEADER[:1] + _FULL_STATE_HEADER_SUFFIX,
)


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class InspectionFile:
    role: str
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class FormatInspectionSpec:
    path: str
    sha256: str
    inspection_id: str
    slice_receipt: EvidenceIdentity
    review_report: EvidenceIdentity
    slice_destination_path: str
    candidate: EvidenceIdentity
    current_euroc_adapter: EvidenceIdentity
    files: tuple[InspectionFile, ...]
    camera_header_target: tuple[str, ...]
    imu_header_target: tuple[str, ...]
    full_state_reference_header_targets: tuple[tuple[str, ...], ...]
    cross_file_checks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InspectionOutputs:
    claim_path: str
    receipt_path: str


@dataclass(frozen=True, slots=True)
class FormatInspectionAuthorization:
    authorization_id: str
    authorization_path: str
    authorization_sha256: str
    authorized_at: datetime
    expires_at: datetime
    spec_identity: EvidenceIdentity
    spec: FormatInspectionSpec
    maximum_elapsed_seconds: int
    minimum_free_bytes: int
    tool_files: tuple[ToolIdentity, ...]
    retention_review_at: datetime
    outputs: InspectionOutputs


@dataclass(frozen=True, slots=True)
class FormatInspectionResult:
    authorization_id: str
    format_comparison_outcome: str
    claim_path: Path
    receipt_path: Path
    receipt_sha256: str


@dataclass(slots=True)
class _BoundSliceTree:
    root_path: Path
    root_descriptor: int
    root_identity: tuple[int, int, int, int, int]
    descriptors: dict[str, int]
    identities: dict[str, tuple[int, int, int, int, int]]


@dataclass(frozen=True, slots=True)
class _ReceiptPublication:
    sha256: str
    device: int
    inode: int


@dataclass(slots=True)
class _ReceiptOwnership:
    publication: _ReceiptPublication | None = None
    payload: bytes | None = None


def _evidence(value: object, *, field: str) -> EvidenceIdentity:
    item = _mapping(value, field=field, keys={"path", "sha256"})
    return EvidenceIdentity(
        _canonical_relative(item["path"], field=f"{field}.path"),
        _sha256(item["sha256"], field=f"{field}.sha256"),
    )


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise AcquisitionError(f"{field} must be a non-empty JSON string array")
    result = tuple(_text(item, field=f"{field}[{index}]") for index, item in enumerate(value))
    return result


def _resolve_repo_file(
    path: os.PathLike[str] | str, *, repo_root: Path, field: str
) -> tuple[Path, str]:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    candidate = candidate.resolve(strict=False)
    try:
        relative = candidate.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise AcquisitionError(f"{field} must be inside the repository") from exc
    return candidate, _canonical_relative(relative, field=field)


def _expected_files() -> tuple[InspectionFile, ...]:
    root = "dataset-room4_512_16/mav0"
    return (
        InspectionFile(
            "cam0_index",
            f"{root}/cam0/data.csv",
            98_057,
            "feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67",
        ),
        InspectionFile(
            "cam1_index",
            f"{root}/cam1/data.csv",
            98_057,
            "feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67",
        ),
        InspectionFile(
            "imu_stream",
            f"{root}/imu0/data.csv",
            2_232_296,
            "4249d4036b3c03c55b709f6f634d975d024999fb017ab3539cfa71580793a3be",
        ),
        InspectionFile(
            "mocap_stream",
            f"{root}/mocap0/data.csv",
            1_481_244,
            "073a3e957efa8ff638ea41402cac9654b40897631d566a3ffee090208597db2a",
        ),
        InspectionFile(
            "cam0_png_0",
            f"{root}/cam0/data/1520531124150444163.png",
            284_188,
            "1c8371dd64a55790c561f98611f132a645a1944291da63f18c054263ed0c5963",
        ),
        InspectionFile(
            "cam1_png_0",
            f"{root}/cam1/data/1520531124150444163.png",
            283_001,
            "e5a853fc43776237e9536e90443fdbd2ae3f8349c6385cbea77133c66542be1f",
        ),
        InspectionFile(
            "cam0_png_1",
            f"{root}/cam0/data/1520531124200446163.png",
            283_946,
            "77f022fd752680fde1ad52d3347eb0c7548f7939ecd3742bc7be807984c38c65",
        ),
        InspectionFile(
            "cam1_png_1",
            f"{root}/cam1/data/1520531124200446163.png",
            282_511,
            "cb616c08af29f4a413577fc00ad189fc029597800cdead394435ef52ebf1dc42",
        ),
    )


def load_format_inspection_spec(
    path: os.PathLike[str] | str, *, repo_root: os.PathLike[str] | str
) -> FormatInspectionSpec:
    """Load the exact checked observation spec without opening slice payloads."""

    root_path = Path(repo_root).resolve()
    spec_path, relative = _resolve_repo_file(path, repo_root=root_path, field="spec path")
    raw, parsed = _read_json_bytes(spec_path, field="format-inspection spec")
    root = _mapping(
        parsed,
        field="format-inspection spec",
        keys={
            "record_type",
            "schema_version",
            "inspection_id",
            "scope",
            "source",
            "comparison_sources",
            "files",
            "csv_comparison",
            "png_header_comparison",
            "cross_file_checks",
            "result_contract",
        },
    )
    _literal(root["record_type"], _SPEC_RECORD_TYPE, field="record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="schema_version")
    _literal(root["inspection_id"], _SPEC_ID, field="inspection_id")
    _literal(root["scope"], _SPEC_SCOPE, field="scope")
    source = _mapping(
        root["source"],
        field="source",
        keys={"slice_receipt", "review_report", "slice_destination_path"},
    )
    slice_receipt = _evidence(source["slice_receipt"], field="source.slice_receipt")
    review_report = _evidence(source["review_report"], field="source.review_report")
    _literal(
        slice_receipt,
        EvidenceIdentity(_SLICE_RECEIPT, _SLICE_RECEIPT_SHA256),
        field="source.slice_receipt",
    )
    _literal(
        review_report,
        EvidenceIdentity(_REVIEW_REPORT, _REVIEW_REPORT_SHA256),
        field="source.review_report",
    )
    _literal(
        source["slice_destination_path"], _SLICE_DESTINATION, field="source.slice_destination_path"
    )
    comparisons = _mapping(
        root["comparison_sources"],
        field="comparison_sources",
        keys={"candidate", "current_euroc_adapter", "png_standard"},
    )
    candidate = _evidence(comparisons["candidate"], field="comparison_sources.candidate")
    adapter = _evidence(
        comparisons["current_euroc_adapter"], field="comparison_sources.current_euroc_adapter"
    )
    _literal(
        candidate,
        EvidenceIdentity(_CANDIDATE, _CANDIDATE_SHA256),
        field="comparison_sources.candidate",
    )
    _literal(
        adapter,
        EvidenceIdentity(_ADAPTER, _ADAPTER_SHA256),
        field="comparison_sources.current_euroc_adapter",
    )
    standard = _mapping(
        comparisons["png_standard"], field="comparison_sources.png_standard", keys={"id", "url"}
    )
    _literal(standard["id"], _PNG_STANDARD_ID, field="comparison_sources.png_standard.id")
    _literal(standard["url"], _PNG_STANDARD_URL, field="comparison_sources.png_standard.url")

    values = root["files"]
    if type(values) is not list:
        raise AcquisitionError("files must be a JSON array")
    files: list[InspectionFile] = []
    for index, value in enumerate(values):
        item = _mapping(
            value, field=f"files[{index}]", keys={"role", "path", "size_bytes", "sha256"}
        )
        files.append(
            InspectionFile(
                _identifier(item["role"], field=f"files[{index}].role"),
                _canonical_relative(item["path"], field=f"files[{index}].path"),
                _positive_int(item["size_bytes"], field=f"files[{index}].size_bytes"),
                _sha256(item["sha256"], field=f"files[{index}].sha256"),
            )
        )
    if tuple(files) != _expected_files():
        raise AcquisitionError("files must equal the exact ordered eight-file slice receipt")
    if sum(item.size_bytes for item in files) != _SOURCE_SIZE_BYTES:
        raise AcquisitionError("files do not total the frozen source byte count")

    csv_value = _mapping(
        root["csv_comparison"],
        field="csv_comparison",
        keys={
            "camera_header_target",
            "imu_header_target",
            "full_state_reference_header_targets",
            "timestamp_lexeme_policy",
            "camera_filename_policy",
        },
    )
    camera_header = _string_tuple(
        csv_value["camera_header_target"], field="csv_comparison.camera_header_target"
    )
    imu_header = _string_tuple(
        csv_value["imu_header_target"], field="csv_comparison.imu_header_target"
    )
    full_values = csv_value["full_state_reference_header_targets"]
    if type(full_values) is not list:
        raise AcquisitionError(
            "csv_comparison.full_state_reference_header_targets must be an array"
        )
    full_headers = tuple(
        _string_tuple(value, field=f"csv_comparison.full_state_reference_header_targets[{index}]")
        for index, value in enumerate(full_values)
    )
    _literal(camera_header, _CAMERA_HEADER, field="csv_comparison.camera_header_target")
    _literal(imu_header, _IMU_HEADER, field="csv_comparison.imu_header_target")
    _literal(
        full_headers,
        _FULL_STATE_HEADERS,
        field="csv_comparison.full_state_reference_header_targets",
    )
    _literal(
        csv_value["timestamp_lexeme_policy"],
        "unsigned-decimal-int64-nanosecond-token-observation/v1",
        field="csv_comparison.timestamp_lexeme_policy",
    )
    _literal(
        csv_value["camera_filename_policy"],
        "single-safe-png-basename/v1",
        field="csv_comparison.camera_filename_policy",
    )

    png = _mapping(
        root["png_header_comparison"],
        field="png_header_comparison",
        keys={
            "interpreted_bytes_per_file",
            "width_px",
            "height_px",
            "bit_depth",
            "color_type_policy",
        },
    )
    for key, expected in (
        ("interpreted_bytes_per_file", 33),
        ("width_px", 512),
        ("height_px", 512),
        ("bit_depth", 16),
    ):
        _literal(png[key], expected, field=f"png_header_comparison.{key}")
    _literal(
        png["color_type_policy"],
        "observe-and-require-legal-bit-depth-pair-no-source-color-assumption/v1",
        field="png_header_comparison.color_type_policy",
    )
    _exact_string_list(root["cross_file_checks"], _CROSS_FILE_CHECKS, field="cross_file_checks")
    result = _mapping(
        root["result_contract"],
        field="result_contract",
        keys={
            "execution_outcomes",
            "format_comparison_outcomes",
            "adapter_ready",
            "calibration_ready",
            "ground_truth_ready",
            "scientific_authority",
            "limitations",
        },
    )
    _exact_string_list(
        result["execution_outcomes"],
        ("completed", "failed"),
        field="result_contract.execution_outcomes",
    )
    _exact_string_list(
        result["format_comparison_outcomes"],
        ("conforms", "does_not_conform"),
        field="result_contract.format_comparison_outcomes",
    )
    for key in ("adapter_ready", "calibration_ready", "ground_truth_ready"):
        _literal(result[key], False, field=f"result_contract.{key}")
    _literal(result["scientific_authority"], "none", field="result_contract.scientific_authority")
    _exact_string_list(
        result["limitations"],
        _LIMITATIONS,
        field="result_contract.limitations",
    )
    return FormatInspectionSpec(
        relative,
        hashlib.sha256(raw).hexdigest(),
        _SPEC_ID,
        slice_receipt,
        review_report,
        _SLICE_DESTINATION,
        candidate,
        adapter,
        tuple(files),
        camera_header,
        imu_header,
        full_headers,
        _CROSS_FILE_CHECKS,
    )


def load_format_inspection_authorization(
    path: os.PathLike[str] | str, *, repo_root: os.PathLike[str] | str
) -> FormatInspectionAuthorization:
    """Parse a future separately committed one-use authorization."""

    root_path = Path(repo_root).resolve()
    authorization_path, relative = _resolve_repo_file(
        path, repo_root=root_path, field="authorization path"
    )
    raw, parsed = _read_json_bytes(authorization_path, field="format-inspection authorization")
    root = _mapping(
        parsed,
        field="format-inspection authorization",
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
            "inspection_limits",
            "source_evidence",
        },
    )
    _literal(root["record_type"], _AUTHORIZATION_RECORD_TYPE, field="record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="schema_version")
    _literal(root["record_status"], "approved", field="record_status")
    authorization_id = _identifier(root["authorization_id"], field="authorization_id")
    _literal(root["scope"], _AUTHORIZATION_SCOPE, field="scope")
    _literal(root["max_executions"], 1, field="max_executions")

    authority = _mapping(
        root["authority_basis"],
        field="authority_basis",
        keys={"kind", "instruction_summary", "captured_at", "identity_authentication"},
    )
    _literal(
        authority["kind"],
        "active_workspace_user_instruction",
        field="authority_basis.kind",
    )
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
        raise AcquisitionError("authority_basis.captured_at must not follow authorized_at")
    if (expires_at - authorized_at).total_seconds() != 86_400:
        raise AcquisitionError("authorization must expire exactly 24 hours after authorization")

    evidence = _mapping(
        root["source_evidence"],
        field="source_evidence",
        keys={
            "inspection_spec",
            "slice_receipt",
            "review_report",
            "candidate",
            "current_euroc_adapter",
        },
    )
    spec_identity = _evidence(evidence["inspection_spec"], field="source_evidence.inspection_spec")
    if spec_identity.path != _SPEC_PATH:
        raise AcquisitionError(f"source_evidence.inspection_spec.path must equal {_SPEC_PATH!r}")
    spec = load_format_inspection_spec(root_path / spec_identity.path, repo_root=root_path)
    if spec.sha256 != spec_identity.sha256:
        raise AcquisitionError("source_evidence.inspection_spec SHA-256 mismatch")
    expected_evidence = (
        ("slice_receipt", spec.slice_receipt),
        ("review_report", spec.review_report),
        ("candidate", spec.candidate),
        ("current_euroc_adapter", spec.current_euroc_adapter),
    )
    for field, expected in expected_evidence:
        actual = _evidence(evidence[field], field=f"source_evidence.{field}")
        if actual != expected:
            raise AcquisitionError(f"source_evidence.{field} does not equal the checked spec")

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
    _literal(
        execution["requires_clean_worktree"],
        True,
        field="execution.requires_clean_worktree",
    )
    _literal(
        execution["maximum_elapsed_seconds"],
        _MAXIMUM_ELAPSED_SECONDS,
        field="execution.maximum_elapsed_seconds",
    )
    _literal(
        execution["maximum_paid_compute_cost_usd"],
        0,
        field="execution.maximum_paid_compute_cost_usd",
    )
    _literal(
        execution["minimum_free_bytes"],
        _MINIMUM_FREE_BYTES,
        field="execution.minimum_free_bytes",
    )
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
        root["inspection_limits"],
        field="inspection_limits",
        keys={
            "source_file_count",
            "source_size_bytes",
            "csv_file_count",
            "png_file_count",
            "png_interpreted_bytes_per_file",
            "maximum_csv_rows_per_file",
            "maximum_csv_line_bytes",
            "maximum_claim_bytes",
            "maximum_receipt_bytes",
            "post_inspection_reserve_bytes",
        },
    )
    expected_limits = {
        "source_file_count": 8,
        "source_size_bytes": _SOURCE_SIZE_BYTES,
        "csv_file_count": 4,
        "png_file_count": 4,
        "png_interpreted_bytes_per_file": _PNG_INTERPRETED_BYTES,
        "maximum_csv_rows_per_file": _MAXIMUM_CSV_ROWS,
        "maximum_csv_line_bytes": _MAXIMUM_CSV_LINE_BYTES,
        "maximum_claim_bytes": _MAXIMUM_CLAIM_BYTES,
        "maximum_receipt_bytes": _MAXIMUM_RECEIPT_BYTES,
        "post_inspection_reserve_bytes": _POST_INSPECTION_RESERVE_BYTES,
    }
    for field, expected in expected_limits.items():
        _literal(limits[field], expected, field=f"inspection_limits.{field}")
    _exact_string_list(
        root["permitted_operations"],
        _PERMITTED_OPERATIONS,
        field="permitted_operations",
    )
    _exact_string_list(
        root["prohibited_operations"],
        _PROHIBITED_OPERATIONS,
        field="prohibited_operations",
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
        "retain_format_inspection_evidence_until_review",
        field="retention.policy",
    )
    review_at = _utc_timestamp(retention["review_at"], field="retention.review_at")
    if review_at <= expires_at:
        raise AcquisitionError("retention.review_at must follow expires_at")
    _literal(retention["deletion_authorized"], False, field="retention.deletion_authorized")
    output = _mapping(root["outputs"], field="outputs", keys={"claim_path", "receipt_path"})
    outputs = InspectionOutputs(
        _canonical_relative(output["claim_path"], field="outputs.claim_path"),
        _canonical_relative(output["receipt_path"], field="outputs.receipt_path"),
    )
    _literal(outputs.claim_path, _CLAIM_PATH, field="outputs.claim_path")
    _literal(outputs.receipt_path, _RECEIPT_PATH, field="outputs.receipt_path")
    return FormatInspectionAuthorization(
        authorization_id,
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


def _runtime_sources(root: Path) -> None:
    actual = (
        Path(__file__).resolve(),
        Path(format_module.__file__).resolve(),
        Path(acquisition_module.__file__).resolve(),
    )
    expected = tuple((root / path).resolve() for path in _TOOL_PATHS)
    if actual != expected:
        raise AcquisitionError("executing format-inspection modules are not authorized sources")
    if Path(euroc_module.__file__).resolve() != (root / _ADAPTER).resolve():
        raise AcquisitionError("loaded EuRoC adapter is not the bound comparison source")


def _metadata_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _hash_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while chunk := os.pread(descriptor, 1024 * 1024, offset):
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _expected_tree(
    files: tuple[InspectionFile, ...],
) -> tuple[dict[str, InspectionFile], set[str]]:
    by_path = {item.path: item for item in files}
    directories: set[str] = set()
    for path in by_path:
        directories.update(
            str(parent) for parent in PurePosixPath(path).parents if str(parent) != "."
        )
    return by_path, directories


def _bind_exact_slice_tree(
    path: Path,
    files: tuple[InspectionFile, ...],
    *,
    cleanup: ExitStack,
) -> _BoundSliceTree:
    """Bind and hash an exact eight-file tree without following any link."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        root_descriptor = os.open(path, flags)
    except OSError as exc:
        raise AcquisitionError(f"cannot bind exact slice root: {exc}") from exc
    cleanup.callback(os.close, root_descriptor)
    root_metadata = os.fstat(root_descriptor)
    if not stat.S_ISDIR(root_metadata.st_mode):
        raise AcquisitionError("slice root must be a real directory")
    expected_files, expected_directories = _expected_tree(files)
    descriptors: dict[str, int] = {}
    identities: dict[str, tuple[int, int, int, int, int]] = {}

    def scan(directory_descriptor: int, relative: PurePosixPath) -> None:
        prefix = "" if str(relative) == "." else f"{relative.as_posix()}/"
        child_directories = {
            PurePosixPath(value[len(prefix) :]).parts[0]
            for value in expected_directories
            if value.startswith(prefix) and value != relative.as_posix()
        }
        child_files = {
            PurePosixPath(value[len(prefix) :]).parts[0]
            for value in expected_files
            if value.startswith(prefix) and len(PurePosixPath(value[len(prefix) :]).parts) == 1
        }
        expected_names = child_directories | child_files
        try:
            observed_names = set(os.listdir(directory_descriptor))
        except OSError as exc:
            raise AcquisitionError(f"cannot list exact slice directory {relative}: {exc}") from exc
        if observed_names != expected_names:
            raise AcquisitionError(
                f"slice tree differs at {relative}: expected {sorted(expected_names)!r}, "
                f"observed {sorted(observed_names)!r}"
            )
        for name in sorted(child_directories):
            try:
                metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                child = os.open(name, flags, dir_fd=directory_descriptor)
            except OSError as exc:
                raise AcquisitionError(
                    f"cannot bind slice directory {prefix}{name}: {exc}"
                ) from exc
            cleanup.callback(os.close, child)
            open_metadata = os.fstat(child)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISDIR(metadata.st_mode)
                or _metadata_identity(metadata) != _metadata_identity(open_metadata)
            ):
                raise AcquisitionError(f"unsafe slice directory: {prefix}{name}")
            scan(child, relative / name)
        for name in sorted(child_files):
            relative_file = f"{prefix}{name}"
            expected = expected_files[relative_file]
            file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
                descriptor = os.open(name, file_flags, dir_fd=directory_descriptor)
            except OSError as exc:
                raise AcquisitionError(f"cannot bind slice file {relative_file}: {exc}") from exc
            cleanup.callback(os.close, descriptor)
            opened = os.fstat(descriptor)
            if (
                stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or opened.st_nlink != 1
                or _metadata_identity(metadata) != _metadata_identity(opened)
                or opened.st_size != expected.size_bytes
            ):
                raise AcquisitionError(f"unsafe or size-mismatched slice file: {relative_file}")
            initial = _metadata_identity(opened)
            if _hash_descriptor(descriptor) != expected.sha256:
                raise AcquisitionError(f"slice file SHA-256 mismatch: {relative_file}")
            if _metadata_identity(os.fstat(descriptor)) != initial:
                raise AcquisitionError(f"slice file changed while hashing: {relative_file}")
            descriptors[expected.role] = descriptor
            identities[expected.role] = initial

    scan(root_descriptor, PurePosixPath())
    if set(descriptors) != {item.role for item in files}:
        raise AcquisitionError("bound slice roles do not equal the exact eight-file spec")
    return _BoundSliceTree(
        path,
        root_descriptor,
        _metadata_identity(root_metadata),
        descriptors,
        identities,
    )


def _assert_bound_slice_tree(tree: _BoundSliceTree, files: tuple[InspectionFile, ...]) -> None:
    path_metadata = os.lstat(tree.root_path)
    open_metadata = os.fstat(tree.root_descriptor)
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISDIR(path_metadata.st_mode)
        or _metadata_identity(path_metadata) != tree.root_identity
        or _metadata_identity(open_metadata) != tree.root_identity
    ):
        raise AcquisitionError("bound slice root identity changed")
    for item in files:
        descriptor = tree.descriptors[item.role]
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or _metadata_identity(metadata) != tree.identities[item.role]
        ):
            raise AcquisitionError(f"bound slice file became unsafe: {item.path}")
        if _hash_descriptor(descriptor) != item.sha256:
            raise AcquisitionError(f"bound slice file identity changed: {item.path}")
        if _metadata_identity(os.fstat(descriptor)) != tree.identities[item.role]:
            raise AcquisitionError(f"bound slice file metadata changed: {item.path}")
    expected_files, expected_directories = _expected_tree(files)

    def scan(directory_descriptor: int, relative: PurePosixPath) -> None:
        prefix = "" if str(relative) == "." else f"{relative.as_posix()}/"
        child_directories = {
            PurePosixPath(value[len(prefix) :]).parts[0]
            for value in expected_directories
            if value.startswith(prefix) and value != relative.as_posix()
        }
        child_files = {
            PurePosixPath(value[len(prefix) :]).parts[0]
            for value in expected_files
            if value.startswith(prefix) and len(PurePosixPath(value[len(prefix) :]).parts) == 1
        }
        if set(os.listdir(directory_descriptor)) != child_directories | child_files:
            raise AcquisitionError(f"bound slice tree names changed at {relative}")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        for name in child_directories:
            child = os.open(name, directory_flags, dir_fd=directory_descriptor)
            try:
                scan(child, relative / name)
            finally:
                os.close(child)
        by_path = {item.path: item for item in files}
        for name in child_files:
            item = by_path[f"{prefix}{name}"]
            path_metadata = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if _metadata_identity(path_metadata) != tree.identities[item.role]:
                raise AcquisitionError(f"bound slice path identity changed: {item.path}")

    scan(tree.root_descriptor, PurePosixPath())


def _duplicate_binary(descriptor: int) -> BinaryIO:
    duplicate = os.dup(descriptor)
    try:
        return os.fdopen(duplicate, "rb")
    except Exception:
        os.close(duplicate)
        raise


def _assert_source_receipt(spec: FormatInspectionSpec, root: Path) -> None:
    _, receipt = _read_json_bytes(root / spec.slice_receipt.path, field="slice receipt")
    try:
        outcome = receipt["outcome"]
        authority = receipt["scientific_authority"]
        destination = receipt["slice"]["destination_path"]
        files = receipt["slice"]["files"]
        candidate = receipt["source_evidence"]["candidate"]
    except (KeyError, TypeError) as exc:
        raise AcquisitionError("slice receipt lacks required inspection bindings") from exc
    if outcome != "completed" or authority != "none" or destination != spec.slice_destination_path:
        raise AcquisitionError("slice receipt completion, authority, or destination mismatch")
    expected_files = [
        {"path": item.path, "sha256": item.sha256, "size_bytes": item.size_bytes}
        for item in spec.files
    ]
    if type(files) is not list or files != expected_files:
        raise AcquisitionError("slice receipt files do not equal the checked inspection spec")
    if candidate != asdict(spec.candidate):
        raise AcquisitionError("slice receipt candidate does not equal the checked spec")


def _assert_candidate_format(spec: FormatInspectionSpec, root: Path) -> None:
    _, candidate = _read_json_bytes(root / spec.candidate.path, field="dataset candidate")
    try:
        unit = candidate["candidate_unit"]
        resolution = unit["image_resolution"]
        bit_depth = unit["published_image_bit_depth"]
        status = candidate["record_status"]
        selects = candidate["authority"]["selects_dataset"]
    except (KeyError, TypeError) as exc:
        raise AcquisitionError("candidate lacks source-published format bindings") from exc
    if resolution != [512, 512] or bit_depth != 16:
        raise AcquisitionError("candidate does not publish the checked 512x512/16-bit format")
    if status != "candidate_non_executable" or selects is not False:
        raise AcquisitionError("candidate authority changed before format inspection")


def _assert_adapter_headers(spec: FormatInspectionSpec) -> None:
    if (
        euroc_module._CAMERA_HEADER != spec.camera_header_target  # noqa: SLF001
        or euroc_module._IMU_HEADER != spec.imu_header_target  # noqa: SLF001
        or euroc_module._GROUND_TRUTH_HEADERS  # noqa: SLF001
        != spec.full_state_reference_header_targets
    ):
        raise AcquisitionError("loaded EuRoC adapter headers differ from the checked spec")


def _csv_limits(spec: FormatInspectionSpec) -> CsvInspectionLimits:
    maximum_csv_bytes = max(
        _MAXIMUM_CSV_LINE_BYTES,
        *(item.size_bytes for item in spec.files if item.path.endswith(".csv")),
    )
    return CsvInspectionLimits(
        max_bytes=maximum_csv_bytes,
        max_rows=_MAXIMUM_CSV_ROWS,
        max_columns=64,
        max_line_bytes=_MAXIMUM_CSV_LINE_BYTES,
        max_violations=32,
    )


def _structurally_conforming_with_allowed_header(
    observation: CsvStructureObservation,
    allowed_headers: tuple[tuple[str, ...], ...],
) -> bool:
    remaining = tuple(code for code in observation.violations if code != "header_mismatch")
    return observation.header in allowed_headers and not remaining


def _inspect_bound_tree(
    tree: _BoundSliceTree,
    spec: FormatInspectionSpec,
) -> tuple[
    StereoCameraIndexObservation,
    CsvStructureObservation,
    CsvStructureObservation,
    dict[str, PngIhdrObservation],
    dict[str, bool],
]:
    required_names = tuple(
        PurePosixPath(item.path).name
        for item in spec.files
        if item.role in ("cam0_png_0", "cam0_png_1")
    )
    limits = _csv_limits(spec)
    by_role = {item.role: item for item in spec.files}
    try:
        with (
            _duplicate_binary(tree.descriptors["cam0_index"]) as cam0,
            _duplicate_binary(tree.descriptors["cam1_index"]) as cam1,
        ):
            stereo = inspect_stereo_camera_indexes(
                cam0,
                cam1,
                expected_header=spec.camera_header_target,
                required_png_basenames=required_names,
                limits=limits,
            )
        with _duplicate_binary(tree.descriptors["imu_stream"]) as imu_source:
            imu = inspect_numeric_csv(
                imu_source,
                role="imu_stream",
                expected_header=spec.imu_header_target,
                limits=limits,
            )
        with _duplicate_binary(tree.descriptors["mocap_stream"]) as mocap_source:
            mocap = inspect_numeric_csv(
                mocap_source,
                role="mocap_stream",
                expected_header=spec.full_state_reference_header_targets[0],
                limits=limits,
            )
        csv_observations = {
            "cam0_index": stereo.cam0,
            "cam1_index": stereo.cam1,
            "imu_stream": imu,
            "mocap_stream": mocap,
        }
        for role, observation in csv_observations.items():
            expected_file = by_role[role]
            if (
                observation.source_size_bytes != expected_file.size_bytes
                or observation.source_sha256 != expected_file.sha256
                or _metadata_identity(os.fstat(tree.descriptors[role])) != tree.identities[role]
            ):
                raise AcquisitionError(f"{role} streamed observation lost its exact byte binding")
        png_contract = PngIhdrContract(width=512, height=512, bit_depth=16)
        pngs: dict[str, PngIhdrObservation] = {}
        for role in ("cam0_png_0", "cam1_png_0", "cam0_png_1", "cam1_png_1"):
            if _metadata_identity(os.fstat(tree.descriptors[role])) != tree.identities[role]:
                raise AcquisitionError(f"{role} changed before its 33-byte PNG observation")
            prefix = os.pread(tree.descriptors[role], _PNG_INTERPRETED_BYTES, 0)
            if len(prefix) != _PNG_INTERPRETED_BYTES:
                raise AcquisitionError(f"{role} lacks the exact 33-byte PNG header boundary")
            pngs[role] = inspect_png_ihdr(
                prefix,
                total_size_bytes=by_role[role].size_bytes,
                expected=png_contract,
                max_total_bytes=by_role[role].size_bytes,
            )
            if (
                _hash_descriptor(tree.descriptors[role]) != by_role[role].sha256
                or _metadata_identity(os.fstat(tree.descriptors[role])) != tree.identities[role]
            ):
                raise AcquisitionError(f"{role} changed across its 33-byte PNG observation")
    except TumviFormatError as exc:
        raise AcquisitionError(f"bounded format inspection failed operationally: {exc}") from exc

    selected_timestamps = tuple(int(PurePosixPath(name).stem) for name in required_names)
    own_indexes = (
        stereo.cam0.observed_required_png_basenames == required_names
        and stereo.cam1.observed_required_png_basenames == required_names
        and stereo.cam0.required_png_occurrence_counts == (1,) * len(required_names)
        and stereo.cam1.required_png_occurrence_counts == (1,) * len(required_names)
    )
    stem_matches = all(
        "required_png_stem_timestamp_mismatch" not in observation.violations
        for observation in (stereo.cam0, stereo.cam1)
    )
    common_names = own_indexes

    def inside(observation: CsvStructureObservation) -> bool:
        return (
            observation.first_timestamp_ns is not None
            and observation.last_timestamp_ns is not None
            and all(
                observation.first_timestamp_ns <= value <= observation.last_timestamp_ns
                for value in selected_timestamps
            )
        )

    ihdr_values = {
        (
            value.width,
            value.height,
            value.bit_depth,
            value.color_type,
            value.compression_method,
            value.filter_method,
            value.interlace_method,
            value.ihdr_crc32,
        )
        for value in pngs.values()
    }
    predicates = {
        "cam0_cam1_index_bytes_equal": stereo.exact_index_equality,
        "selected_png_names_present_once_in_own_index": own_indexes,
        "selected_filename_stem_equals_row_timestamp": stem_matches,
        "selected_names_common_to_both_camera_indexes": common_names,
        "selected_camera_timestamps_within_observed_imu_range": inside(imu),
        "selected_camera_timestamps_within_observed_mocap_range": inside(mocap),
        "four_png_ihdr_tuples_equal": len(ihdr_values) == 1,
    }
    if tuple(predicates) != spec.cross_file_checks:
        raise AcquisitionError("implemented predicate order differs from the checked spec")
    return stereo, imu, mocap, pngs, predicates


def _assert_repository_with_new_receipt(
    root: Path, *, expected_revision: str, receipt_relative: str
) -> None:
    top = Path(
        acquisition_module._git(root, "rev-parse", "--show-toplevel")  # noqa: SLF001
        .stdout.decode()
        .strip()
    ).resolve()
    if top != root:
        raise AcquisitionError("repo_root changed during format receipt publication")
    revision = (
        acquisition_module._git(root, "rev-parse", "HEAD")  # noqa: SLF001
        .stdout.decode()
        .strip()
    )
    if revision != expected_revision:
        raise AcquisitionError("Git revision changed during format receipt publication")
    status = acquisition_module._git(  # noqa: SLF001
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    expected = b"?? " + os.fsencode(receipt_relative) + b"\0"
    if status != expected:
        raise AcquisitionError(
            "repository changed during publication beyond the exact new format receipt"
        )


def _write_owned_receipt_atomic(
    path: Path,
    payload: bytes,
    *,
    ownership: _ReceiptOwnership,
) -> _ReceiptPublication:
    """Publish a new receipt and return the exact inode owned by this invocation."""

    digest = hashlib.sha256(payload).hexdigest()
    staged = path.with_name(f".{path.name}.staged-{os.getpid()}-{time.time_ns()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(staged, flags, 0o600)
    except FileExistsError as exc:
        raise AcquisitionError(f"staged receipt path already exists: {staged}") from exc
    except OSError as exc:
        raise AcquisitionError(f"cannot create staged format receipt {staged}: {exc}") from exc

    staged_identity: tuple[int, int] | None = None
    publication: _ReceiptPublication | None = None
    try:
        try:
            initial_metadata = os.fstat(descriptor)
            if not stat.S_ISREG(initial_metadata.st_mode) or initial_metadata.st_nlink != 1:
                raise AcquisitionError("staged format receipt must be one regular single-link file")
            staged_identity = (initial_metadata.st_dev, initial_metadata.st_ino)
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise AcquisitionError(f"short write while creating {staged}")
                written += count
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or (metadata.st_dev, metadata.st_ino) != staged_identity
            ):
                raise AcquisitionError("staged format receipt must be one regular single-link file")
        finally:
            os.close(descriptor)

        staged_metadata = os.lstat(staged)
        if (
            staged_identity is None
            or (staged_metadata.st_dev, staged_metadata.st_ino) != staged_identity
            or not stat.S_ISREG(staged_metadata.st_mode)
            or staged_metadata.st_nlink != 1
            or _assert_exact_file(staged, payload, field="staged format receipt") != digest
        ):
            raise AcquisitionError("staged format receipt lost its owned inode binding")
        if not hasattr(signal, "pthread_sigmask"):
            raise AcquisitionError("owned receipt publication requires POSIX signal masking")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
        try:
            try:
                os.link(staged, path, follow_symlinks=False)
            except FileExistsError as exc:
                raise AcquisitionError(f"refusing to overwrite format receipt: {path}") from exc
            except OSError as exc:
                raise AcquisitionError(f"cannot publish format receipt {path}: {exc}") from exc
            publication = _ReceiptPublication(digest, *staged_identity)
            ownership.publication = publication
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        published_metadata = os.lstat(path)
        if (
            (published_metadata.st_dev, published_metadata.st_ino)
            != (publication.device, publication.inode)
            or not stat.S_ISREG(published_metadata.st_mode)
            or published_metadata.st_nlink != 2
        ):
            raise AcquisitionError("published format receipt is not the owned staged inode")
        acquisition_module._fsync_directory(path.parent)  # noqa: SLF001

        current_staged = os.lstat(staged)
        if (current_staged.st_dev, current_staged.st_ino) != staged_identity:
            raise AcquisitionError("staged format receipt identity changed before cleanup")
        staged.unlink()
        acquisition_module._fsync_directory(path.parent)  # noqa: SLF001
        if _assert_owned_receipt(path, payload, publication) != publication.sha256:
            raise AcquisitionError("published format receipt digest changed")
        return publication
    except Exception:
        if publication is not None:
            try:
                current = os.lstat(path)
                if (current.st_dev, current.st_ino) == (
                    publication.device,
                    publication.inode,
                ):
                    path.unlink()
                    acquisition_module._fsync_directory(path.parent)  # noqa: SLF001
            except FileNotFoundError:
                pass
            except OSError:
                pass
        raise
    finally:
        if staged_identity is not None:
            try:
                current = os.lstat(staged)
                if (current.st_dev, current.st_ino) == staged_identity:
                    staged.unlink()
                    acquisition_module._fsync_directory(path.parent)  # noqa: SLF001
            except FileNotFoundError:
                pass
            except OSError:
                pass


def _assert_owned_receipt(
    path: Path,
    payload: bytes,
    publication: _ReceiptPublication,
) -> str:
    metadata = os.lstat(path)
    if (metadata.st_dev, metadata.st_ino) != (publication.device, publication.inode):
        raise AcquisitionError("format-inspection receipt is not this invocation's inode")
    return _assert_exact_file(path, payload, field="format-inspection receipt")


def _retract_exact_new_receipt(
    path: Path,
    payload: bytes,
    publication: _ReceiptPublication,
) -> None:
    expected_sha256 = hashlib.sha256(payload).hexdigest()
    if _assert_owned_receipt(path, payload, publication) != expected_sha256:
        raise AcquisitionError("cannot safely retract changed format-inspection receipt")
    try:
        path.unlink()
        acquisition_module._fsync_directory(path.parent)  # noqa: SLF001
    except OSError as exc:
        raise AcquisitionError(f"cannot retract invalid format-inspection receipt: {exc}") from exc


@contextmanager
def _rollback_owned_receipt_on_failure(
    path: Path,
    ownership: _ReceiptOwnership,
) -> Iterator[None]:
    """Enclose deadline teardown so every failed run reconciles its owned receipt."""

    try:
        yield
    except BaseException:
        if (
            ownership.publication is not None
            and ownership.payload is not None
            and os.path.lexists(path)
        ):
            _retract_exact_new_receipt(
                path,
                ownership.payload,
                ownership.publication,
            )
        raise


def _tracked_evidence(
    authorization: FormatInspectionAuthorization,
) -> tuple[EvidenceIdentity, ...]:
    spec = authorization.spec
    return (
        EvidenceIdentity(
            authorization.authorization_path,
            authorization.authorization_sha256,
        ),
        authorization.spec_identity,
        spec.slice_receipt,
        spec.review_report,
        spec.candidate,
        spec.current_euroc_adapter,
    )


def _assert_tracked_execution_state(
    root: Path,
    authorization: FormatInspectionAuthorization,
    *,
    expected_revision: str,
) -> None:
    revision = _assert_clean_repository(root)
    if revision != expected_revision:
        raise AcquisitionError("Git revision changed during format inspection")
    for evidence in _tracked_evidence(authorization):
        _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
    for tool in authorization.tool_files:
        _assert_tracked_head_bytes(root, tool.path, tool.sha256)


def run_authorized_format_inspection(
    authorization_path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str | None = None,
) -> FormatInspectionResult:
    """Execute one authorized observation and publish its receipt last."""

    root = Path(repo_root or Path.cwd()).resolve()
    authorization = load_format_inspection_authorization(authorization_path, repo_root=root)
    controller_started_at = _utc_now()
    started_monotonic = time.monotonic()
    if not authorization.authorized_at <= controller_started_at < authorization.expires_at:
        raise AcquisitionError("authorization is not active at execution start")
    if (
        authorization.maximum_elapsed_seconds
        > (authorization.expires_at - controller_started_at).total_seconds()
    ):
        raise AcquisitionError(
            "remaining authorization lifetime is shorter than the execution bound"
        )
    revision = _assert_clean_repository(root)
    _runtime_sources(root)
    for evidence in _tracked_evidence(authorization):
        _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
    for tool in authorization.tool_files:
        _assert_tracked_head_bytes(root, tool.path, tool.sha256)

    spec = authorization.spec
    _assert_source_receipt(spec, root)
    _assert_candidate_format(spec, root)
    _assert_adapter_headers(spec)
    _assert_no_symlink_ancestors(
        root,
        spec.slice_destination_path,
        allow_missing_leaf=False,
    )
    if not _is_ignored(root, spec.slice_destination_path):
        raise AcquisitionError("format-inspection source slice must remain Git-ignored")
    for relative in (authorization.outputs.claim_path, authorization.outputs.receipt_path):
        _assert_no_symlink_ancestors(root, relative, allow_missing_leaf=True)
    if not _is_ignored(root, authorization.outputs.claim_path):
        raise AcquisitionError("format-inspection claim must remain Git-ignored")
    if _is_ignored(root, authorization.outputs.receipt_path):
        raise AcquisitionError("format-inspection receipt must remain trackable")
    claim_path = root / authorization.outputs.claim_path
    receipt_path = root / authorization.outputs.receipt_path
    if os.path.lexists(claim_path) or os.path.lexists(receipt_path):
        raise AcquisitionError("one-use format-inspection claim and receipt must be absent")
    initial_free_bytes = _disk_usage(root / spec.slice_destination_path).free
    if initial_free_bytes < authorization.minimum_free_bytes:
        raise AcquisitionError("insufficient free space for claim, receipt, and retained reserve")

    cleanup = ExitStack()
    try:
        tree = _bind_exact_slice_tree(
            root / spec.slice_destination_path,
            spec.files,
            cleanup=cleanup,
        )
        _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="pre-claim source verification",
        )
        claim_prepared_at = _utc_now()
        if not authorization.authorized_at <= claim_prepared_at < authorization.expires_at:
            raise AcquisitionError("authorization is not active immediately before claim")
        remaining = authorization.maximum_elapsed_seconds - (time.monotonic() - started_monotonic)
        if remaining <= 0:
            raise AcquisitionError("elapsed-time bound expired before claim")
        if remaining > (authorization.expires_at - claim_prepared_at).total_seconds():
            raise AcquisitionError(
                "remaining authorization lifetime is shorter than the remaining execution bound"
            )
        claim = {
            "authorization_id": authorization.authorization_id,
            "authorization_sha256": authorization.authorization_sha256,
            "claim_prepared_at": _format_utc(claim_prepared_at),
            "controller_started_at": _format_utc(controller_started_at),
            "git_revision": revision,
            "inspection_spec_sha256": authorization.spec_identity.sha256,
            "record_type": "dataset_format_inspection_claim",
            "schema_version": _SCHEMA_VERSION,
            "slice_receipt_sha256": spec.slice_receipt.sha256,
        }
        claim_bytes = _canonical_json_bytes(claim)
        if len(claim_bytes) > _MAXIMUM_CLAIM_BYTES:
            raise AcquisitionError("format-inspection claim exceeds its byte bound")
    except Exception:
        cleanup.close()
        raise

    ownership = _ReceiptOwnership()
    with (
        _rollback_owned_receipt_on_failure(receipt_path, ownership),
        _hard_deadline(remaining),
        cleanup,
    ):
        claim_sha256 = _write_new_atomic(claim_path, claim_bytes)
        stereo, imu, mocap, pngs, predicates = _inspect_bound_tree(tree, spec)
        camera_headers_match = (
            stereo.cam0.header == spec.camera_header_target
            and stereo.cam1.header == spec.camera_header_target
        )
        imu_header_matches = imu.header == spec.imu_header_target
        mocap_header_matches = mocap.header in spec.full_state_reference_header_targets
        mocap_structure_conforms = _structurally_conforming_with_allowed_header(
            mocap,
            spec.full_state_reference_header_targets,
        )
        format_conforms = (
            camera_headers_match
            and imu_header_matches
            and mocap_header_matches
            and stereo.conforms
            and imu.conforms
            and mocap_structure_conforms
            and all(item.conforms for item in pngs.values())
            and all(predicates.values())
        )
        format_outcome = "conforms" if format_conforms else "does_not_conform"

        _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="format inspection",
        )
        if (authorization.expires_at - _utc_now()).total_seconds() < 5:
            raise AcquisitionError("authorization expires too soon for receipt publication")
        _assert_tracked_execution_state(root, authorization, expected_revision=revision)
        _assert_no_symlink_ancestors(
            root,
            spec.slice_destination_path,
            allow_missing_leaf=False,
        )
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.claim_path,
            allow_missing_leaf=False,
        )
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.receipt_path,
            allow_missing_leaf=True,
        )
        _assert_source_receipt(spec, root)
        _assert_candidate_format(spec, root)
        _assert_adapter_headers(spec)
        _assert_bound_slice_tree(tree, spec.files)
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("format-inspection claim changed before receipt")
        if os.path.lexists(receipt_path):
            raise AcquisitionError("format-inspection receipt appeared before publication")
        free_bytes_before_receipt = _disk_usage(tree.root_path).free
        if free_bytes_before_receipt < _POST_INSPECTION_RESERVE_BYTES + _MAXIMUM_RECEIPT_BYTES:
            raise AcquisitionError("insufficient retained reserve for format receipt")

        elapsed = _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="format receipt",
        )
        receipt_prepared_at = _utc_now()
        if (authorization.expires_at - receipt_prepared_at).total_seconds() < 5:
            raise AcquisitionError("authorization expired before format receipt publication")
        receipt = {
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
                "post_inspection_reserve_bytes": _POST_INSPECTION_RESERVE_BYTES,
            },
            "claim": {"path": authorization.outputs.claim_path, "sha256": claim_sha256},
            "comparison": {
                "adapter_headers": {
                    "camera_matches": camera_headers_match,
                    "imu_matches": imu_header_matches,
                    "mocap_matches_one_full_state_target": mocap_header_matches,
                },
                "format_comparison_outcome": format_outcome,
                "predicates": predicates,
            },
            "controller_started_at": _format_utc(controller_started_at),
            "execution": {
                "controller_initiated_paid_service_cost_usd": 0,
                "elapsed_seconds_at_receipt_preparation": elapsed,
                "git_revision": revision,
                "maximum_elapsed_seconds": authorization.maximum_elapsed_seconds,
                "tool_files": [asdict(item) for item in authorization.tool_files],
            },
            "execution_outcome": "completed",
            "inspection": {
                "csv": {
                    "imu": asdict(imu),
                    "mocap": asdict(mocap),
                    "stereo_camera_indexes": asdict(stereo),
                },
                "full_indexed_image_existence": "not_checked",
                "observation_field_contract": "tumvi-bounded-format-observations/v1",
                "png_ihdr": {
                    role: {
                        "decodability": "not_checked",
                        "interpreted_bytes": _PNG_INTERPRETED_BYTES,
                        "observation": asdict(observation),
                        "whole_file_validity": "not_checked",
                    }
                    for role, observation in pngs.items()
                },
                "png_standard": {"id": _PNG_STANDARD_ID, "url": _PNG_STANDARD_URL},
            },
            "limitations": list(_LIMITATIONS),
            "operations_not_performed": list(_PROHIBITED_OPERATIONS),
            "operations_performed": list(_SUCCESS_OPERATIONS),
            "readiness": {
                "adapter_ready": False,
                "calibration_ready": False,
                "ground_truth_ready": False,
            },
            "receipt_prepared_at": _format_utc(receipt_prepared_at),
            "record_type": "dataset_format_inspection_receipt",
            "retention": {
                "deletion_authorized": False,
                "policy": "retain_format_inspection_evidence_until_review",
                "review_at": _format_utc(authorization.retention_review_at),
            },
            "schema_version": _SCHEMA_VERSION,
            "scientific_authority": "none",
            "source": {
                "candidate": asdict(spec.candidate),
                "current_euroc_adapter": asdict(spec.current_euroc_adapter),
                "files": [asdict(item) for item in spec.files],
                "inspection_spec": asdict(authorization.spec_identity),
                "review_report": asdict(spec.review_report),
                "slice_destination_path": spec.slice_destination_path,
                "slice_receipt": asdict(spec.slice_receipt),
            },
        }
        receipt_bytes = _canonical_json_bytes(receipt)
        if len(receipt_bytes) > _MAXIMUM_RECEIPT_BYTES:
            raise AcquisitionError("format-inspection receipt exceeds its byte bound")

        _assert_tracked_execution_state(root, authorization, expected_revision=revision)
        _assert_bound_slice_tree(tree, spec.files)
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("format-inspection claim changed before atomic publication")
        if os.path.lexists(receipt_path):
            raise AcquisitionError("format-inspection receipt appeared before atomic publication")
        receipt_sha256: str | None = None
        ownership.payload = receipt_bytes
        publication = _write_owned_receipt_atomic(
            receipt_path,
            receipt_bytes,
            ownership=ownership,
        )
        receipt_sha256 = publication.sha256
        _assert_repository_with_new_receipt(
            root,
            expected_revision=revision,
            receipt_relative=authorization.outputs.receipt_path,
        )
        for evidence in _tracked_evidence(authorization):
            _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
        for tool in authorization.tool_files:
            _assert_tracked_head_bytes(root, tool.path, tool.sha256)
        _assert_bound_slice_tree(tree, spec.files)
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("format-inspection claim changed during publication")
        if (
            _assert_exact_file(
                receipt_path,
                receipt_bytes,
                field="format-inspection receipt",
            )
            != receipt_sha256
        ):
            raise AcquisitionError("format-inspection receipt changed during publication")
        _assert_repository_with_new_receipt(
            root,
            expected_revision=revision,
            receipt_relative=authorization.outputs.receipt_path,
        )
        for evidence in _tracked_evidence(authorization):
            _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
        for tool in authorization.tool_files:
            _assert_tracked_head_bytes(root, tool.path, tool.sha256)
        _assert_bound_slice_tree(tree, spec.files)
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("format-inspection claim changed at final truth gate")
        if _assert_owned_receipt(receipt_path, receipt_bytes, publication) != receipt_sha256:
            raise AcquisitionError("format-inspection receipt changed at final truth gate")
        if receipt_sha256 is None:
            raise AcquisitionError("format-inspection receipt publication returned no identity")
    return FormatInspectionResult(
        authorization.authorization_id,
        format_outcome,
        claim_path,
        receipt_path,
        receipt_sha256,
    )


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AcquisitionError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="compact-vio-inspect-tumvi-format",
        description="Execute one authorized bounded TUM VI CSV/PNG-header inspection.",
    )
    parser.add_argument("--authorization", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = run_authorized_format_inspection(args.authorization)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": {"message": str(exc), "type": type(exc).__name__},
                    "execution_outcome": "failed",
                    "scientific_authority": "none",
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
                "format_comparison_outcome": result.format_comparison_outcome,
                "receipt_path": str(result.receipt_path),
                "receipt_sha256": result.receipt_sha256,
                "scientific_authority": "none",
                "status": "ok",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

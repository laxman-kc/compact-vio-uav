"""One-use controller for an audit-bound regular-file compatibility slice."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import compact_vio.data.acquisition as acquisition_module
import compact_vio.data.archive as archive_module
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
    _file_sha256,
    _format_utc,
    _fsync_directory,
    _hard_deadline,
    _identifier,
    _is_ignored,
    _literal,
    _mapping,
    _parse_archive_identity,
    _positive_int,
    _read_json_bytes,
    _sha256,
    _text,
    _utc_now,
    _utc_timestamp,
    _write_new_atomic,
)
from compact_vio.data.archive import (
    ArchiveError,
    ExtractedFileReceipt,
    PublishedArchiveIdentity,
    TarLimits,
    TarRegularSliceMember,
    TarStructuralAudit,
    TarStructuralMemberRecord,
    extract_tar_regular_slice,
    verify_archive,
)

_AUTHORIZATION_RECORD_TYPE = "dataset_archive_regular_slice_authorization"
_ALLOWLIST_RECORD_TYPE = "dataset_archive_regular_slice_allowlist"
_SCHEMA_VERSION = "1.0.0"
_SCOPE = "audit_bound_regular_file_compatibility_slice_only"
_POLICY_ID = "exact-audit-bound-regular-slice-no-link-follow/v1"
_POST_SLICE_RESERVE_BYTES = 2_147_483_648
_MAX_CLAIM_BYTES = 1_048_576
_MAX_RECEIPT_BYTES = 1_048_576
_MAX_SELECTED_FILES = 64
_MAX_SELECTED_BYTES = 67_108_864
_MAX_MEMBERS = 250_000
_MAX_MEMBER_SIZE_BYTES = 8_589_934_592
_MAX_EXPANDED_SIZE_BYTES = 274_877_906_944
_TOOL_PATHS = (
    "src/compact_vio/data/archive_slice.py",
    "src/compact_vio/data/acquisition.py",
    "src/compact_vio/data/archive.py",
)
_PERMITTED_OPERATIONS = (
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
)
_SUCCESS_OPERATIONS = tuple(
    operation
    for operation in _PERMITTED_OPERATIONS
    if operation != "retract_exact_new_receipt_on_truth_gate_failure"
)
_PROHIBITED_OPERATIONS = (
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
)
_SCIENTIFIC_LIMITATIONS = (
    "does_not_select_a_dataset",
    "does_not_assign_protocol_membership",
    "does_not_validate_csv_membership",
    "does_not_validate_camera_synchronization",
    "does_not_approve_model_access_training_inference_evaluation_or_publication",
)
_SELECTION_BASIS = (
    "The four mav0 CSV paths are exact audited regular files; the two PNG basenames are "
    "the lexicographically earliest two filenames in the exact intersection of audited "
    "regular-image paths under cam0/data and cam1/data."
)


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class RegularSliceAllowlist:
    allowlist_id: str
    path: str
    sha256: str
    archive: EvidenceIdentity
    structural_audit: EvidenceIdentity
    structural_audit_authorization: EvidenceIdentity
    structural_audit_claim: EvidenceIdentity
    structural_audit_receipt: EvidenceIdentity
    source_failure: EvidenceIdentity
    structural_member_count: int
    allowed_root: str
    selected_files: tuple[TarRegularSliceMember, ...]
    selected_expanded_size_bytes: int


@dataclass(frozen=True, slots=True)
class SliceOutputs:
    claim_path: str
    destination_path: str
    receipt_path: str


@dataclass(frozen=True, slots=True)
class RegularSliceAuthorization:
    authorization_id: str
    authorization_path: str
    authorization_sha256: str
    authorized_at: datetime
    expires_at: datetime
    archive_path: str
    archive_identity: PublishedArchiveIdentity
    candidate: EvidenceIdentity
    transfer_authorization: EvidenceIdentity
    transfer_claim: EvidenceIdentity
    transfer_failure: EvidenceIdentity
    structural_audit: EvidenceIdentity
    structural_audit_authorization: EvidenceIdentity
    structural_audit_claim: EvidenceIdentity
    structural_audit_receipt: EvidenceIdentity
    allowlist_identity: EvidenceIdentity
    allowlist: RegularSliceAllowlist
    maximum_elapsed_seconds: int
    minimum_free_bytes: int
    tool_files: tuple[ToolIdentity, ...]
    limits: TarLimits
    retention_review_at: datetime
    outputs: SliceOutputs


@dataclass(frozen=True, slots=True)
class RegularSliceResult:
    authorization_id: str
    archive_sha256: str
    destination_path: Path
    claim_path: Path
    receipt_path: Path
    receipt_sha256: str
    extracted_files: tuple[ExtractedFileReceipt, ...]


def _resolve_repo_file(
    path: os.PathLike[str] | str,
    *,
    repo_root: Path,
    field: str,
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


def _evidence(value: object, *, field: str) -> EvidenceIdentity:
    item = _mapping(value, field=field, keys={"path", "sha256"})
    return EvidenceIdentity(
        path=_canonical_relative(item["path"], field=f"{field}.path"),
        sha256=_sha256(item["sha256"], field=f"{field}.sha256"),
    )


def _non_negative_int(value: object, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise AcquisitionError(f"{field} must be a non-negative integer")
    return value


def _is_under(path: str, root: str) -> bool:
    candidate = PurePosixPath(path)
    parent = PurePosixPath(root)
    return candidate != parent and parent in candidate.parents


def load_regular_slice_allowlist(
    path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str,
) -> RegularSliceAllowlist:
    """Strictly load a non-executable exact regular-file allowlist."""

    root_path = Path(repo_root).resolve()
    allowlist_path, relative = _resolve_repo_file(
        path,
        repo_root=root_path,
        field="allowlist path",
    )
    raw, parsed = _read_json_bytes(allowlist_path, field="regular-slice allowlist")
    root = _mapping(
        parsed,
        field="regular-slice allowlist",
        keys={
            "record_type",
            "schema_version",
            "allowlist_id",
            "archive",
            "structural_audit",
            "allowed_root",
            "selected_files",
            "selected_file_count",
            "selected_expanded_size_bytes",
            "selection_basis",
            "selection_purpose",
            "scientific_limitations",
        },
    )
    _literal(root["record_type"], _ALLOWLIST_RECORD_TYPE, field="record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="schema_version")
    allowlist_id = _identifier(root["allowlist_id"], field="allowlist_id")
    archive = _evidence(root["archive"], field="archive")
    if not archive.path.startswith("data/quarantine/") or not archive.path.endswith(".tar"):
        raise AcquisitionError("allowlist archive.path must be a quarantined TAR path")

    audit_item = _mapping(
        root["structural_audit"],
        field="structural_audit",
        keys={
            "path",
            "sha256",
            "authorization_path",
            "authorization_sha256",
            "claim_path",
            "claim_sha256",
            "receipt_path",
            "receipt_sha256",
            "source_failure_path",
            "source_failure_sha256",
            "member_count",
        },
    )
    structural_audit = EvidenceIdentity(
        _canonical_relative(audit_item["path"], field="structural_audit.path"),
        _sha256(audit_item["sha256"], field="structural_audit.sha256"),
    )
    structural_audit_claim = EvidenceIdentity(
        _canonical_relative(audit_item["claim_path"], field="structural_audit.claim_path"),
        _sha256(audit_item["claim_sha256"], field="structural_audit.claim_sha256"),
    )
    structural_audit_receipt = EvidenceIdentity(
        _canonical_relative(audit_item["receipt_path"], field="structural_audit.receipt_path"),
        _sha256(audit_item["receipt_sha256"], field="structural_audit.receipt_sha256"),
    )
    structural_audit_authorization = EvidenceIdentity(
        _canonical_relative(
            audit_item["authorization_path"],
            field="structural_audit.authorization_path",
        ),
        _sha256(
            audit_item["authorization_sha256"],
            field="structural_audit.authorization_sha256",
        ),
    )
    source_failure = EvidenceIdentity(
        _canonical_relative(
            audit_item["source_failure_path"],
            field="structural_audit.source_failure_path",
        ),
        _sha256(
            audit_item["source_failure_sha256"],
            field="structural_audit.source_failure_sha256",
        ),
    )
    structural_member_count = _positive_int(
        audit_item["member_count"], field="structural_audit.member_count"
    )
    if structural_member_count > _MAX_MEMBERS:
        raise AcquisitionError("structural_audit.member_count exceeds the hard cap")

    allowed_root = _canonical_relative(root["allowed_root"], field="allowed_root")
    if "dso" in PurePosixPath(allowed_root).parts:
        raise AcquisitionError("allowed_root must not name a DSO tree")

    values = root["selected_files"]
    if type(values) is not list or not values:
        raise AcquisitionError("selected_files must be a non-empty JSON array")
    if len(values) > _MAX_SELECTED_FILES:
        raise AcquisitionError("selected_files exceeds the hard file-count cap")
    selected: list[TarRegularSliceMember] = []
    for index, value in enumerate(values):
        item = _mapping(
            value,
            field=f"selected_files[{index}]",
            keys={"path", "size_bytes"},
        )
        member_path = _canonical_relative(item["path"], field=f"selected_files[{index}].path")
        if "dso" in PurePosixPath(member_path).parts:
            raise AcquisitionError("selected_files must not include a DSO path")
        if not _is_under(member_path, allowed_root):
            raise AcquisitionError("selected_files path is outside allowed_root")
        try:
            selected.append(
                TarRegularSliceMember(
                    path=member_path,
                    size_bytes=_positive_int(
                        item["size_bytes"], field=f"selected_files[{index}].size_bytes"
                    ),
                )
            )
        except ArchiveError as exc:
            raise AcquisitionError(f"invalid selected_files[{index}]: {exc}") from exc
    if len({item.path for item in selected}) != len(selected):
        raise AcquisitionError("selected_files must not contain duplicate paths")
    selected_file_count = _positive_int(root["selected_file_count"], field="selected_file_count")
    if selected_file_count != len(selected):
        raise AcquisitionError("selected_file_count does not equal selected_files length")
    expanded_size = _positive_int(
        root["selected_expanded_size_bytes"], field="selected_expanded_size_bytes"
    )
    if expanded_size != sum(item.size_bytes for item in selected):
        raise AcquisitionError("selected_expanded_size_bytes does not equal selected file sizes")
    if expanded_size > _MAX_SELECTED_BYTES:
        raise AcquisitionError("selected_expanded_size_bytes exceeds the hard cap")
    _literal(root["selection_basis"], _SELECTION_BASIS, field="selection_basis")
    _literal(
        root["selection_purpose"],
        "tumvi_format_compatibility_smoke_only",
        field="selection_purpose",
    )
    _exact_string_list(
        root["scientific_limitations"],
        _SCIENTIFIC_LIMITATIONS,
        field="scientific_limitations",
    )
    return RegularSliceAllowlist(
        allowlist_id=allowlist_id,
        path=relative,
        sha256=hashlib.sha256(raw).hexdigest(),
        archive=archive,
        structural_audit=structural_audit,
        structural_audit_authorization=structural_audit_authorization,
        structural_audit_claim=structural_audit_claim,
        structural_audit_receipt=structural_audit_receipt,
        source_failure=source_failure,
        structural_member_count=structural_member_count,
        allowed_root=allowed_root,
        selected_files=tuple(selected),
        selected_expanded_size_bytes=expanded_size,
    )


def load_regular_slice_authorization(
    path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str,
) -> RegularSliceAuthorization:
    """Strictly parse one authorization without reading the retained archive."""

    root_path = Path(repo_root).resolve()
    authorization_path, relative = _resolve_repo_file(
        path,
        repo_root=root_path,
        field="authorization path",
    )
    raw, parsed = _read_json_bytes(authorization_path, field="regular-slice authorization")
    root = _mapping(
        parsed,
        field="regular-slice authorization",
        keys={
            "record_type",
            "schema_version",
            "record_status",
            "authorization_id",
            "scope",
            "authority_basis",
            "authorized_at",
            "expires_at",
            "max_executions",
            "archive_path",
            "archive_identity",
            "source_evidence",
            "execution",
            "slice_limits",
            "permitted_operations",
            "prohibited_operations",
            "scientific_authority",
            "retention",
            "outputs",
        },
    )
    _literal(root["record_type"], _AUTHORIZATION_RECORD_TYPE, field="record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="schema_version")
    _literal(root["record_status"], "approved", field="record_status")
    authorization_id = _identifier(root["authorization_id"], field="authorization_id")
    _literal(root["scope"], _SCOPE, field="scope")
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

    archive_path = _canonical_relative(root["archive_path"], field="archive_path")
    archive_identity = _parse_archive_identity(root["archive_identity"])
    if archive_identity.sha256 is None:
        raise AcquisitionError("archive_identity.sha256 must bind the retained archive")
    if archive_path.startswith("data/quarantine/") is False:
        raise AcquisitionError("archive_path must remain under data/quarantine/")
    if PurePosixPath(archive_path).name != archive_identity.filename:
        raise AcquisitionError("archive_path basename must equal archive_identity.filename")

    evidence = _mapping(
        root["source_evidence"],
        field="source_evidence",
        keys={
            "candidate",
            "transfer_authorization",
            "transfer_claim",
            "transfer_failure",
            "structural_audit",
            "structural_audit_authorization",
            "structural_audit_claim",
            "structural_audit_receipt",
            "allowlist",
        },
    )
    candidate = _evidence(evidence["candidate"], field="source_evidence.candidate")
    transfer_authorization = _evidence(
        evidence["transfer_authorization"],
        field="source_evidence.transfer_authorization",
    )
    transfer_claim = _evidence(evidence["transfer_claim"], field="source_evidence.transfer_claim")
    transfer_failure = _evidence(
        evidence["transfer_failure"], field="source_evidence.transfer_failure"
    )
    structural_audit = _evidence(
        evidence["structural_audit"], field="source_evidence.structural_audit"
    )
    structural_audit_authorization = _evidence(
        evidence["structural_audit_authorization"],
        field="source_evidence.structural_audit_authorization",
    )
    structural_audit_claim = _evidence(
        evidence["structural_audit_claim"],
        field="source_evidence.structural_audit_claim",
    )
    structural_audit_receipt = _evidence(
        evidence["structural_audit_receipt"],
        field="source_evidence.structural_audit_receipt",
    )
    allowlist_identity = _evidence(evidence["allowlist"], field="source_evidence.allowlist")
    allowlist = load_regular_slice_allowlist(
        root_path / allowlist_identity.path,
        repo_root=root_path,
    )
    if allowlist.sha256 != allowlist_identity.sha256:
        raise AcquisitionError("source_evidence.allowlist SHA-256 does not match its bytes")
    expected_evidence = (
        ("archive", EvidenceIdentity(archive_path, archive_identity.sha256), allowlist.archive),
        ("structural_audit", structural_audit, allowlist.structural_audit),
        (
            "structural_audit_claim",
            structural_audit_claim,
            allowlist.structural_audit_claim,
        ),
        (
            "structural_audit_receipt",
            structural_audit_receipt,
            allowlist.structural_audit_receipt,
        ),
        ("transfer_failure", transfer_failure, allowlist.source_failure),
        (
            "structural_audit_authorization",
            structural_audit_authorization,
            allowlist.structural_audit_authorization,
        ),
    )
    for field, actual, expected in expected_evidence:
        if actual != expected:
            raise AcquisitionError(f"{field} does not equal the bound allowlist evidence")

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
    _literal(execution["requires_clean_worktree"], True, field="execution.requires_clean_worktree")
    maximum_elapsed = _positive_int(
        execution["maximum_elapsed_seconds"], field="execution.maximum_elapsed_seconds"
    )
    if maximum_elapsed > 3_600:
        raise AcquisitionError("maximum_elapsed_seconds must not exceed 3600")
    _literal(
        execution["maximum_paid_compute_cost_usd"],
        0,
        field="execution.maximum_paid_compute_cost_usd",
    )
    minimum_free_bytes = _positive_int(
        execution["minimum_free_bytes"], field="execution.minimum_free_bytes"
    )
    required_free = (
        _POST_SLICE_RESERVE_BYTES
        + allowlist.selected_expanded_size_bytes
        + _MAX_CLAIM_BYTES
        + _MAX_RECEIPT_BYTES
    )
    if minimum_free_bytes != required_free:
        raise AcquisitionError(
            "minimum_free_bytes must equal reserve, selected bytes, claim, and receipt bounds"
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

    limit_values = _mapping(
        root["slice_limits"],
        field="slice_limits",
        keys={
            "max_members",
            "max_member_size_bytes",
            "max_expanded_size_bytes",
            "selected_file_count",
            "selected_expanded_size_bytes",
            "maximum_receipt_bytes",
        },
    )
    try:
        limits = TarLimits(
            _positive_int(limit_values["max_members"], field="slice_limits.max_members"),
            _positive_int(
                limit_values["max_member_size_bytes"],
                field="slice_limits.max_member_size_bytes",
            ),
            _positive_int(
                limit_values["max_expanded_size_bytes"],
                field="slice_limits.max_expanded_size_bytes",
            ),
        )
    except ArchiveError as exc:
        raise AcquisitionError(f"invalid slice_limits: {exc}") from exc
    if limits.max_members > _MAX_MEMBERS:
        raise AcquisitionError("slice_limits.max_members exceeds the hard cap")
    if limits.max_member_size_bytes > _MAX_MEMBER_SIZE_BYTES:
        raise AcquisitionError("slice_limits.max_member_size_bytes exceeds the hard cap")
    if limits.max_expanded_size_bytes > _MAX_EXPANDED_SIZE_BYTES:
        raise AcquisitionError("slice_limits.max_expanded_size_bytes exceeds the hard cap")
    _literal(
        limit_values["selected_file_count"],
        len(allowlist.selected_files),
        field="slice_limits.selected_file_count",
    )
    _literal(
        limit_values["selected_expanded_size_bytes"],
        allowlist.selected_expanded_size_bytes,
        field="slice_limits.selected_expanded_size_bytes",
    )
    _literal(
        limit_values["maximum_receipt_bytes"],
        _MAX_RECEIPT_BYTES,
        field="slice_limits.maximum_receipt_bytes",
    )
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
            "approves_model_access",
            "approves_training",
            "approves_inference",
            "approves_evaluation",
            "approves_publication",
        },
    )
    for key, value in scientific.items():
        _literal(value, False, field=f"scientific_authority.{key}")

    retention = _mapping(
        root["retention"],
        field="retention",
        keys={"policy", "review_at", "deletion_authorized"},
    )
    _literal(
        retention["policy"],
        "retain_slice_and_evidence_until_review",
        field="retention.policy",
    )
    retention_review_at = _utc_timestamp(retention["review_at"], field="retention.review_at")
    if retention_review_at <= expires_at:
        raise AcquisitionError("retention.review_at must follow expires_at")
    _literal(retention["deletion_authorized"], False, field="retention.deletion_authorized")

    output = _mapping(
        root["outputs"],
        field="outputs",
        keys={"claim_path", "destination_path", "receipt_path"},
    )
    outputs = SliceOutputs(
        _canonical_relative(output["claim_path"], field="outputs.claim_path"),
        _canonical_relative(output["destination_path"], field="outputs.destination_path"),
        _canonical_relative(output["receipt_path"], field="outputs.receipt_path"),
    )
    archive_parent = PurePosixPath(archive_path).parent
    if PurePosixPath(outputs.claim_path).parent != archive_parent:
        raise AcquisitionError("outputs.claim_path must share the archive quarantine directory")
    if PurePosixPath(outputs.destination_path).parent != archive_parent:
        raise AcquisitionError(
            "outputs.destination_path must share the archive quarantine directory"
        )
    if PurePosixPath(outputs.destination_path).name != allowlist.allowlist_id:
        raise AcquisitionError("outputs.destination_path basename must equal allowlist_id")
    expected_receipt = f"governance/datasets/acquisitions/{authorization_id}.receipt.json"
    if outputs.receipt_path != expected_receipt:
        raise AcquisitionError(f"outputs.receipt_path must equal {expected_receipt!r}")
    all_paths = {
        archive_path,
        candidate.path,
        transfer_authorization.path,
        transfer_claim.path,
        transfer_failure.path,
        structural_audit_authorization.path,
        structural_audit.path,
        structural_audit_claim.path,
        structural_audit_receipt.path,
        allowlist.path,
        outputs.claim_path,
        outputs.destination_path,
        outputs.receipt_path,
    }
    if len(all_paths) != 13:
        raise AcquisitionError("source evidence and output paths must all be distinct")

    return RegularSliceAuthorization(
        authorization_id=authorization_id,
        authorization_path=relative,
        authorization_sha256=hashlib.sha256(raw).hexdigest(),
        authorized_at=authorized_at,
        expires_at=expires_at,
        archive_path=archive_path,
        archive_identity=archive_identity,
        candidate=candidate,
        transfer_authorization=transfer_authorization,
        transfer_claim=transfer_claim,
        transfer_failure=transfer_failure,
        structural_audit=structural_audit,
        structural_audit_authorization=structural_audit_authorization,
        structural_audit_claim=structural_audit_claim,
        structural_audit_receipt=structural_audit_receipt,
        allowlist_identity=allowlist_identity,
        allowlist=allowlist,
        maximum_elapsed_seconds=maximum_elapsed,
        minimum_free_bytes=minimum_free_bytes,
        tool_files=tuple(tools),
        limits=limits,
        retention_review_at=retention_review_at,
        outputs=outputs,
    )


def _assert_runtime_sources(root: Path) -> None:
    expected = tuple((root / path).resolve() for path in _TOOL_PATHS)
    acquisition_file = getattr(acquisition_module, "__file__", None)
    archive_file = getattr(archive_module, "__file__", None)
    if type(acquisition_file) is not str or type(archive_file) is not str:
        raise AcquisitionError("loaded operational modules lack filesystem source identity")
    actual = (
        Path(__file__).resolve(),
        Path(acquisition_file).resolve(),
        Path(archive_file).resolve(),
    )
    if actual != expected:
        raise AcquisitionError("executing regular-slice modules are not authorized sources")


def _load_bound_structural_audit(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[bytes, TarStructuralAudit]:
    raw, parsed = _read_json_bytes(path, field="bound structural audit")
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        raise AcquisitionError("bound structural audit SHA-256 mismatch")
    root = _mapping(
        parsed,
        field="bound structural audit",
        keys={
            "archive_sha256",
            "expanded_regular_size_bytes",
            "member_count",
            "members",
            "non_regular_member_count",
            "policy_id",
            "record_type",
            "regular_file_count",
            "schema_version",
            "strict_extraction_compatible",
        },
    )
    _literal(root["record_type"], "dataset_archive_structural_audit", field="audit.record_type")
    _literal(root["schema_version"], _SCHEMA_VERSION, field="audit.schema_version")
    _literal(
        root["policy_id"],
        "inert-tar-header-metadata-no-follow-no-extract/v1",
        field="audit.policy_id",
    )
    members_value = root["members"]
    if type(members_value) is not list:
        raise AcquisitionError("audit.members must be a JSON array")
    if len(members_value) > _MAX_MEMBERS:
        raise AcquisitionError("audit.members exceeds the hard cap")
    members: list[TarStructuralMemberRecord] = []
    for index, value in enumerate(members_value):
        item = _mapping(
            value,
            field=f"audit.members[{index}]",
            keys={"path", "kind", "size_bytes", "link_target"},
        )
        try:
            members.append(
                TarStructuralMemberRecord(
                    path=item["path"],
                    kind=item["kind"],
                    size_bytes=item["size_bytes"],
                    link_target=item["link_target"],
                )
            )
        except ArchiveError as exc:
            raise AcquisitionError(f"invalid audit.members[{index}]: {exc}") from exc
    member_count = _positive_int(root["member_count"], field="audit.member_count")
    if member_count != len(members):
        raise AcquisitionError("audit.member_count does not equal audit.members length")
    strict_value = root["strict_extraction_compatible"]
    if type(strict_value) is not bool:
        raise AcquisitionError("audit.strict_extraction_compatible must be a boolean")
    audit = TarStructuralAudit(
        members=tuple(members),
        regular_file_count=_positive_int(
            root["regular_file_count"], field="audit.regular_file_count"
        ),
        non_regular_member_count=_non_negative_int(
            root["non_regular_member_count"], field="audit.non_regular_member_count"
        ),
        expanded_regular_size_bytes=_positive_int(
            root["expanded_regular_size_bytes"],
            field="audit.expanded_regular_size_bytes",
        ),
        archive_sha256=_sha256(root["archive_sha256"], field="audit.archive_sha256"),
        strict_extraction_compatible=strict_value,
    )
    return raw, audit


def _assert_receipt_bindings(
    path: Path,
    authorization: RegularSliceAuthorization,
) -> None:
    _, parsed = _read_json_bytes(path, field="structural-audit receipt")
    try:
        archive_path = parsed["archive"]["path"]
        archive_sha256 = parsed["archive"]["sha256"]
        audit_path = parsed["audit"]["path"]
        audit_sha256 = parsed["audit"]["sha256"]
        claim_path = parsed["claim"]["path"]
        claim_sha256 = parsed["claim"]["sha256"]
        authorization_path = parsed["authorization"]["path"]
        authorization_sha256 = parsed["authorization"]["sha256"]
        source_failure_path = parsed["source_failure"]["path"]
        source_failure_sha256 = parsed["source_failure"]["sha256"]
        outcome = parsed["outcome"]
        scientific_authority = parsed["scientific_authority"]
    except (KeyError, TypeError) as exc:
        raise AcquisitionError("structural-audit receipt lacks required bindings") from exc
    expected = (
        ("archive path", archive_path, authorization.archive_path),
        ("archive SHA-256", archive_sha256, authorization.archive_identity.sha256),
        ("audit path", audit_path, authorization.structural_audit.path),
        ("audit SHA-256", audit_sha256, authorization.structural_audit.sha256),
        ("claim path", claim_path, authorization.structural_audit_claim.path),
        ("claim SHA-256", claim_sha256, authorization.structural_audit_claim.sha256),
        (
            "authorization path",
            authorization_path,
            authorization.structural_audit_authorization.path,
        ),
        (
            "authorization SHA-256",
            authorization_sha256,
            authorization.structural_audit_authorization.sha256,
        ),
        ("source failure path", source_failure_path, authorization.transfer_failure.path),
        (
            "source failure SHA-256",
            source_failure_sha256,
            authorization.transfer_failure.sha256,
        ),
        ("outcome", outcome, "completed"),
        ("scientific_authority", scientific_authority, "none"),
    )
    for field, actual, wanted in expected:
        if type(actual) is not type(wanted) or actual != wanted:
            raise AcquisitionError(f"structural-audit receipt {field} mismatch")


def _assert_transfer_bindings(
    root: Path,
    authorization: RegularSliceAuthorization,
) -> None:
    _, claim = _read_json_bytes(root / authorization.transfer_claim.path, field="transfer claim")
    _, failure = _read_json_bytes(
        root / authorization.transfer_failure.path,
        field="transfer failure",
    )
    try:
        claim_authorization_sha256 = claim["authorization_sha256"]
        claim_candidate_sha256 = claim["candidate_sha256"]
        failure_archive_path = failure["archive"]["path"]
        failure_archive_sha256 = failure["archive"]["sha256"]
        failure_authorization_path = failure["authorization"]["path"]
        failure_authorization_sha256 = failure["authorization"]["sha256"]
        failure_claim_path = failure["claim"]["path"]
        failure_claim_sha256 = failure["claim"]["sha256"]
        failure_outcome = failure["outcome"]
        failure_scientific_authority = failure["scientific_authority"]
    except (KeyError, TypeError) as exc:
        raise AcquisitionError("transfer evidence lacks required chain bindings") from exc
    expected = (
        (
            "claim authorization SHA-256",
            claim_authorization_sha256,
            authorization.transfer_authorization.sha256,
        ),
        ("claim candidate SHA-256", claim_candidate_sha256, authorization.candidate.sha256),
        ("failure archive path", failure_archive_path, authorization.archive_path),
        (
            "failure archive SHA-256",
            failure_archive_sha256,
            authorization.archive_identity.sha256,
        ),
        (
            "failure authorization path",
            failure_authorization_path,
            authorization.transfer_authorization.path,
        ),
        (
            "failure authorization SHA-256",
            failure_authorization_sha256,
            authorization.transfer_authorization.sha256,
        ),
        ("failure claim path", failure_claim_path, authorization.transfer_claim.path),
        ("failure claim SHA-256", failure_claim_sha256, authorization.transfer_claim.sha256),
        ("failure outcome", failure_outcome, "failed"),
        ("failure scientific_authority", failure_scientific_authority, "none"),
    )
    for field, actual, wanted in expected:
        if type(actual) is not type(wanted) or actual != wanted:
            raise AcquisitionError(f"transfer evidence {field} mismatch")


def _validate_slice_staging(
    allowlist: RegularSliceAllowlist,
    receipts: tuple[ExtractedFileReceipt, ...],
) -> None:
    expected = tuple((item.path, item.size_bytes) for item in allowlist.selected_files)
    actual = tuple((item.path, item.size_bytes) for item in receipts)
    if actual != expected:
        raise ArchiveError("staged regular slice does not equal the ordered allowlist")


def _validate_deterministic_selection(
    allowlist: RegularSliceAllowlist,
    audit: TarStructuralAudit,
) -> None:
    root = allowlist.allowed_root
    csv_paths = (
        f"{root}/cam0/data.csv",
        f"{root}/cam1/data.csv",
        f"{root}/imu0/data.csv",
        f"{root}/mocap0/data.csv",
    )
    cam0_parent = PurePosixPath(f"{root}/cam0/data")
    cam1_parent = PurePosixPath(f"{root}/cam1/data")
    cam0_names = {
        PurePosixPath(member.path).name
        for member in audit.members
        if member.kind == "file"
        and PurePosixPath(member.path).parent == cam0_parent
        and PurePosixPath(member.path).suffix.lower() == ".png"
    }
    cam1_names = {
        PurePosixPath(member.path).name
        for member in audit.members
        if member.kind == "file"
        and PurePosixPath(member.path).parent == cam1_parent
        and PurePosixPath(member.path).suffix.lower() == ".png"
    }
    common = sorted(cam0_names & cam1_names)
    if len(common) < 2:
        raise AcquisitionError("structural audit has fewer than two common camera PNG basenames")
    first, second = common[:2]
    expected_paths = csv_paths + (
        f"{root}/cam0/data/{first}",
        f"{root}/cam1/data/{first}",
        f"{root}/cam0/data/{second}",
        f"{root}/cam1/data/{second}",
    )
    actual_paths = tuple(item.path for item in allowlist.selected_files)
    if actual_paths != expected_paths:
        raise AcquisitionError(
            "allowlist does not equal the deterministic four-CSV/two-common-PNG selection"
        )


def _open_bound_directory(path: Path) -> tuple[int, tuple[int, int, int]]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise AcquisitionError(f"cannot bind published regular-slice root: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise AcquisitionError("published regular-slice root must be a real directory")
    return descriptor, (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _assert_bound_directory(
    path: Path,
    descriptor: int,
    expected: tuple[int, int, int],
) -> None:
    try:
        path_metadata = os.lstat(path)
        open_metadata = os.fstat(descriptor)
    except OSError as exc:
        raise AcquisitionError(f"published regular-slice root changed: {exc}") from exc
    path_identity = (path_metadata.st_dev, path_metadata.st_ino, path_metadata.st_mode)
    open_identity = (open_metadata.st_dev, open_metadata.st_ino, open_metadata.st_mode)
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISDIR(path_metadata.st_mode)
        or path_identity != expected
        or open_identity != expected
    ):
        raise AcquisitionError("published regular-slice root identity changed")


def _retract_exact_new_receipt(path: Path, payload: bytes) -> None:
    """Retract only this run's exact newly published receipt after a truth-gate failure."""

    expected_sha256 = hashlib.sha256(payload).hexdigest()
    if _assert_exact_file(path, payload, field="new regular-slice receipt") != expected_sha256:
        raise AcquisitionError("cannot safely retract changed regular-slice receipt")
    try:
        path.unlink()
        _fsync_directory(path.parent)
    except OSError as exc:
        raise AcquisitionError(f"cannot retract invalid regular-slice receipt: {exc}") from exc


def _assert_repository_with_new_receipt(
    root: Path,
    *,
    expected_revision: str,
    receipt_relative: str,
) -> None:
    """Allow exactly this run's untracked receipt and no other Git state change."""

    top = Path(
        acquisition_module._git(root, "rev-parse", "--show-toplevel")  # noqa: SLF001
        .stdout.decode()
        .strip()
    ).resolve()
    if top != root.resolve():
        raise AcquisitionError("repo_root changed during receipt publication")
    revision = (
        acquisition_module._git(root, "rev-parse", "HEAD")  # noqa: SLF001
        .stdout.decode()
        .strip()
    )
    if revision != expected_revision:
        raise AcquisitionError("Git revision changed during receipt publication")
    status = acquisition_module._git(  # noqa: SLF001
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
    ).stdout
    expected_status = b"?? " + os.fsencode(receipt_relative) + b"\0"
    if status != expected_status:
        raise AcquisitionError(
            "repository changed during receipt publication beyond the exact new receipt"
        )


def _verify_published_slice(
    destination: Path,
    receipts: tuple[ExtractedFileReceipt, ...],
    *,
    root_descriptor: int,
    root_identity: tuple[int, int, int],
) -> None:
    _assert_bound_directory(destination, root_descriptor, root_identity)
    expected = {item.path: item for item in receipts}
    expected_directories = {
        str(parent)
        for receipt in receipts
        for parent in PurePosixPath(receipt.path).parents
        if str(parent) != "."
    }
    observed: set[str] = set()
    for current_root, directory_names, file_names in os.walk(destination, followlinks=False):
        current = Path(current_root)
        for name in directory_names:
            item = current / name
            item_metadata = os.lstat(item)
            if stat.S_ISLNK(item_metadata.st_mode) or not stat.S_ISDIR(item_metadata.st_mode):
                raise AcquisitionError("published regular slice contains a non-directory")
            relative_directory = item.relative_to(destination).as_posix()
            if relative_directory not in expected_directories:
                raise AcquisitionError(
                    f"published regular slice has unexpected directory: {relative_directory}"
                )
        for name in file_names:
            item = current / name
            relative = item.relative_to(destination).as_posix()
            receipt = expected.get(relative)
            if receipt is None:
                raise AcquisitionError(f"published regular slice has unexpected file: {relative}")
            item_metadata = os.lstat(item)
            if not stat.S_ISREG(item_metadata.st_mode) or item_metadata.st_nlink != 1:
                raise AcquisitionError(f"published regular slice has unsafe file: {relative}")
            if _file_sha256(item) != receipt.sha256:
                raise AcquisitionError(f"published regular slice hash mismatch: {relative}")
            if item_metadata.st_size != receipt.size_bytes:
                raise AcquisitionError(f"published regular slice size mismatch: {relative}")
            observed.add(relative)
    if observed != set(expected):
        raise AcquisitionError("published regular slice is missing selected files")
    _assert_bound_directory(destination, root_descriptor, root_identity)


def run_authorized_regular_slice(
    authorization_path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str | None = None,
) -> RegularSliceResult:
    """Execute one exact regular-file slice and publish its receipt last."""

    root = Path(repo_root or Path.cwd()).resolve()
    authorization = load_regular_slice_authorization(authorization_path, repo_root=root)
    controller_started_at = _utc_now()
    started_monotonic = time.monotonic()
    if not authorization.authorized_at <= controller_started_at < authorization.expires_at:
        raise AcquisitionError("authorization is not active at execution start")
    if (
        authorization.maximum_elapsed_seconds
        > (authorization.expires_at - controller_started_at).total_seconds()
    ):
        raise AcquisitionError(
            "remaining authorization lifetime is shorter than elapsed-time bound"
        )

    revision = _assert_clean_repository(root)
    _assert_runtime_sources(root)
    tracked_evidence = (
        EvidenceIdentity(authorization.authorization_path, authorization.authorization_sha256),
        authorization.candidate,
        authorization.transfer_authorization,
        authorization.transfer_failure,
        authorization.structural_audit_authorization,
        authorization.structural_audit_receipt,
        authorization.allowlist_identity,
    )
    for evidence in tracked_evidence:
        _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
    for tool in authorization.tool_files:
        _assert_tracked_head_bytes(root, tool.path, tool.sha256)

    source_identities = (
        EvidenceIdentity(authorization.archive_path, authorization.archive_identity.sha256 or ""),
        authorization.transfer_claim,
        authorization.structural_audit,
        authorization.structural_audit_claim,
    )
    for evidence in source_identities:
        _assert_no_symlink_ancestors(root, evidence.path, allow_missing_leaf=False)
        if not _is_ignored(root, evidence.path):
            raise AcquisitionError(
                f"runtime source evidence must remain Git-ignored: {evidence.path}"
            )
    source_bytes: dict[str, bytes] = {}
    for evidence in source_identities[1:]:
        try:
            payload = (root / evidence.path).read_bytes()
        except OSError as exc:
            raise AcquisitionError(f"cannot read source evidence {evidence.path}: {exc}") from exc
        if (
            _assert_exact_file(root / evidence.path, payload, field=evidence.path)
            != evidence.sha256
        ):
            raise AcquisitionError(f"source evidence SHA-256 mismatch: {evidence.path}")
        source_bytes[evidence.path] = payload

    audit_bytes, structural_audit = _load_bound_structural_audit(
        root / authorization.structural_audit.path,
        expected_sha256=authorization.structural_audit.sha256,
    )
    if structural_audit.archive_sha256 != authorization.archive_identity.sha256:
        raise AcquisitionError("bound structural audit archive SHA-256 mismatch")
    if structural_audit.member_count != authorization.allowlist.structural_member_count:
        raise AcquisitionError("bound structural audit member count differs from allowlist")
    audited_by_path = {item.path: item for item in structural_audit.members}
    for selected in authorization.allowlist.selected_files:
        member = audited_by_path.get(selected.path)
        if member is None or member.kind != "file" or member.size_bytes != selected.size_bytes:
            raise AcquisitionError(
                "allowlisted file does not equal a regular structural-audit member: "
                f"{selected.path}"
            )
    _validate_deterministic_selection(authorization.allowlist, structural_audit)
    _assert_receipt_bindings(root / authorization.structural_audit_receipt.path, authorization)
    _assert_transfer_bindings(root, authorization)

    claim_path = root / authorization.outputs.claim_path
    destination_path = root / authorization.outputs.destination_path
    receipt_path = root / authorization.outputs.receipt_path
    for relative in (
        authorization.outputs.claim_path,
        authorization.outputs.destination_path,
        authorization.outputs.receipt_path,
    ):
        _assert_no_symlink_ancestors(root, relative, allow_missing_leaf=True)
    for path in (claim_path, destination_path, receipt_path):
        if os.path.lexists(path):
            raise AcquisitionError(f"one-use regular-slice path must be absent: {path}")
    for relative in (
        authorization.outputs.claim_path,
        authorization.outputs.destination_path,
    ):
        if not _is_ignored(root, relative):
            raise AcquisitionError(f"runtime regular-slice path must be Git-ignored: {relative}")
    if _is_ignored(root, authorization.outputs.receipt_path):
        raise AcquisitionError("tracked regular-slice receipt must not be Git-ignored")
    initial_free_bytes = _disk_usage((root / authorization.archive_path).parent).free
    if initial_free_bytes < authorization.minimum_free_bytes:
        raise AcquisitionError("insufficient free space for bounded regular slice and reserve")

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
        "allowlist_sha256": authorization.allowlist_identity.sha256,
        "archive_sha256": authorization.archive_identity.sha256,
        "authorization_id": authorization.authorization_id,
        "authorization_sha256": authorization.authorization_sha256,
        "git_revision": revision,
        "record_type": "dataset_archive_regular_slice_claim",
        "schema_version": _SCHEMA_VERSION,
        "claim_prepared_at": _format_utc(claim_prepared_at),
        "controller_started_at": _format_utc(controller_started_at),
        "structural_audit_sha256": authorization.structural_audit.sha256,
    }
    claim_bytes = _canonical_json_bytes(claim)
    if len(claim_bytes) > _MAX_CLAIM_BYTES:
        raise AcquisitionError("regular-slice claim exceeds its byte bound")
    with _hard_deadline(remaining), ExitStack() as cleanup:
        claim_sha256 = _write_new_atomic(claim_path, claim_bytes)
        try:
            verification = verify_archive(
                root / authorization.archive_path,
                authorization.archive_identity,
            )
            report = extract_tar_regular_slice(
                root / authorization.archive_path,
                destination_path,
                expected_sha256=verification.sha256,
                expected_structure=structural_audit,
                allowed_root=authorization.allowlist.allowed_root,
                selected_files=authorization.allowlist.selected_files,
                validate_staging=lambda _path, receipts: _validate_slice_staging(
                    authorization.allowlist, receipts
                ),
                limits=authorization.limits,
            )
        except ArchiveError as exc:
            raise AcquisitionError(f"regular TAR slice failed: {exc}") from exc
        if len(report.extracted_files) != len(authorization.allowlist.selected_files):
            raise AcquisitionError("regular-slice report file count mismatch")
        if report.expanded_size_bytes != authorization.allowlist.selected_expanded_size_bytes:
            raise AcquisitionError("regular-slice report expanded size mismatch")
        destination_descriptor, destination_identity = _open_bound_directory(destination_path)
        cleanup.callback(os.close, destination_descriptor)

        _check_deadline(
            started_monotonic, authorization.maximum_elapsed_seconds, phase="regular slice"
        )
        if (authorization.expires_at - _utc_now()).total_seconds() < 5:
            raise AcquisitionError("authorization expires too soon for receipt publication")
        final_revision = _assert_clean_repository(root)
        if final_revision != revision:
            raise AcquisitionError("Git revision changed during regular-slice execution")
        for evidence in tracked_evidence:
            _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
        for tool in authorization.tool_files:
            _assert_tracked_head_bytes(root, tool.path, tool.sha256)
        for evidence in source_identities:
            _assert_no_symlink_ancestors(root, evidence.path, allow_missing_leaf=False)
        for relative in (
            authorization.outputs.claim_path,
            authorization.outputs.destination_path,
        ):
            _assert_no_symlink_ancestors(root, relative, allow_missing_leaf=False)
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.receipt_path,
            allow_missing_leaf=True,
        )
        if os.path.lexists(receipt_path):
            raise AcquisitionError("regular-slice receipt appeared before publication")
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("regular-slice claim changed before receipt publication")
        for evidence in source_identities[1:]:
            if (
                _assert_exact_file(
                    root / evidence.path,
                    source_bytes[evidence.path],
                    field=evidence.path,
                )
                != evidence.sha256
            ):
                raise AcquisitionError(f"source evidence changed: {evidence.path}")
        if source_bytes[authorization.structural_audit.path] != audit_bytes:
            raise AcquisitionError("structural audit bytes changed in memory")
        _assert_receipt_bindings(
            root / authorization.structural_audit_receipt.path,
            authorization,
        )
        _assert_transfer_bindings(root, authorization)
        final_verification = verify_archive(
            root / authorization.archive_path,
            authorization.archive_identity,
        )
        if final_verification.sha256 != report.archive_sha256:
            raise AcquisitionError("archive changed before receipt publication")
        _verify_published_slice(
            destination_path,
            report.extracted_files,
            root_descriptor=destination_descriptor,
            root_identity=destination_identity,
        )
        free_bytes_before_receipt = _disk_usage(destination_path.parent).free
        if free_bytes_before_receipt < _POST_SLICE_RESERVE_BYTES + _MAX_RECEIPT_BYTES:
            raise AcquisitionError("insufficient post-slice reserve for receipt publication")

        elapsed = _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="receipt",
        )
        prepared_at = _utc_now()
        if (authorization.expires_at - prepared_at).total_seconds() < 5:
            raise AcquisitionError("authorization expires too soon for atomic receipt publication")
        receipt = {
            "allowlist": {
                "id": authorization.allowlist.allowlist_id,
                "path": authorization.allowlist.path,
                "sha256": authorization.allowlist.sha256,
            },
            "archive": {
                "archive_id": verification.archive_id,
                "md5": verification.md5,
                "path": authorization.archive_path,
                "sha256": verification.sha256,
                "size_bytes": verification.size_bytes,
            },
            "authorization": {
                "id": authorization.authorization_id,
                "path": authorization.authorization_path,
                "sha256": authorization.authorization_sha256,
            },
            "claim": {"path": authorization.outputs.claim_path, "sha256": claim_sha256},
            "capacity": {
                "authorized_minimum_free_bytes": authorization.minimum_free_bytes,
                "free_bytes_before_receipt": free_bytes_before_receipt,
                "initial_free_bytes": initial_free_bytes,
                "maximum_claim_bytes": _MAX_CLAIM_BYTES,
                "maximum_receipt_bytes": _MAX_RECEIPT_BYTES,
                "post_slice_reserve_bytes": _POST_SLICE_RESERVE_BYTES,
                "selected_expanded_size_bytes": (
                    authorization.allowlist.selected_expanded_size_bytes
                ),
            },
            "execution": {
                "controller_initiated_paid_service_cost_usd": 0,
                "elapsed_seconds": elapsed,
                "git_revision": revision,
                "maximum_elapsed_seconds": authorization.maximum_elapsed_seconds,
                "tool_files": [asdict(item) for item in authorization.tool_files],
            },
            "operations_not_performed": list(_PROHIBITED_OPERATIONS),
            "operations_performed": list(_SUCCESS_OPERATIONS),
            "outcome": "completed",
            "receipt_prepared_at": _format_utc(prepared_at),
            "record_type": "dataset_archive_regular_slice_receipt",
            "retention": {
                "deletion_authorized": False,
                "policy": "retain_slice_and_evidence_until_review",
                "review_at": _format_utc(authorization.retention_review_at),
            },
            "schema_version": _SCHEMA_VERSION,
            "scientific_authority": "none",
            "scientific_limitations": list(_SCIENTIFIC_LIMITATIONS),
            "slice": {
                "destination_path": authorization.outputs.destination_path,
                "expanded_size_bytes": report.expanded_size_bytes,
                "file_count": len(report.extracted_files),
                "files": [asdict(item) for item in report.extracted_files],
                "policy_id": _POLICY_ID,
            },
            "source_evidence": {
                "candidate": asdict(authorization.candidate),
                "structural_audit": asdict(authorization.structural_audit),
                "structural_audit_authorization": asdict(
                    authorization.structural_audit_authorization
                ),
                "structural_audit_claim": asdict(authorization.structural_audit_claim),
                "structural_audit_receipt": asdict(authorization.structural_audit_receipt),
                "transfer_authorization": asdict(authorization.transfer_authorization),
                "transfer_claim": asdict(authorization.transfer_claim),
                "transfer_failure": asdict(authorization.transfer_failure),
            },
            "claim_prepared_at": _format_utc(claim_prepared_at),
            "controller_started_at": _format_utc(controller_started_at),
        }
        receipt_bytes = _canonical_json_bytes(receipt)
        if len(receipt_bytes) > _MAX_RECEIPT_BYTES:
            raise AcquisitionError("regular-slice receipt exceeds its byte bound")

        publication_revision = _assert_clean_repository(root)
        if publication_revision != revision:
            raise AcquisitionError("Git revision changed before atomic receipt publication")
        for evidence in tracked_evidence:
            _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
        for tool in authorization.tool_files:
            _assert_tracked_head_bytes(root, tool.path, tool.sha256)
        for evidence in source_identities:
            _assert_no_symlink_ancestors(root, evidence.path, allow_missing_leaf=False)
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.claim_path,
            allow_missing_leaf=False,
        )
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.destination_path,
            allow_missing_leaf=False,
        )
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.receipt_path,
            allow_missing_leaf=True,
        )
        _assert_bound_directory(
            destination_path,
            destination_descriptor,
            destination_identity,
        )
        if os.path.lexists(receipt_path):
            raise AcquisitionError("regular-slice receipt appeared before atomic publication")
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("regular-slice claim changed before atomic publication")
        for evidence in source_identities[1:]:
            if (
                _assert_exact_file(
                    root / evidence.path,
                    source_bytes[evidence.path],
                    field=evidence.path,
                )
                != evidence.sha256
            ):
                raise AcquisitionError(f"source evidence changed: {evidence.path}")
        _assert_receipt_bindings(
            root / authorization.structural_audit_receipt.path,
            authorization,
        )
        _assert_transfer_bindings(root, authorization)
        publication_verification = verify_archive(
            root / authorization.archive_path,
            authorization.archive_identity,
        )
        if publication_verification.sha256 != report.archive_sha256:
            raise AcquisitionError("archive changed before atomic receipt publication")
        archive_metadata = os.stat(root / authorization.archive_path, follow_symlinks=False)
        archive_identity = (
            archive_metadata.st_dev,
            archive_metadata.st_ino,
            archive_metadata.st_size,
            archive_metadata.st_mtime_ns,
            archive_metadata.st_ctime_ns,
        )
        _verify_published_slice(
            destination_path,
            report.extracted_files,
            root_descriptor=destination_descriptor,
            root_identity=destination_identity,
        )
        free_bytes_before_receipt = _disk_usage(destination_path.parent).free
        if free_bytes_before_receipt < _POST_SLICE_RESERVE_BYTES + _MAX_RECEIPT_BYTES:
            raise AcquisitionError("insufficient post-slice reserve for atomic receipt publication")
        elapsed = _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="atomic receipt publication",
        )
        prepared_at = _utc_now()
        if (authorization.expires_at - prepared_at).total_seconds() < 5:
            raise AcquisitionError("authorization expired before atomic receipt publication")
        receipt["capacity"]["free_bytes_before_receipt"] = free_bytes_before_receipt
        receipt["execution"]["elapsed_seconds"] = elapsed
        receipt["receipt_prepared_at"] = _format_utc(prepared_at)
        receipt_bytes = _canonical_json_bytes(receipt)
        if len(receipt_bytes) > _MAX_RECEIPT_BYTES:
            raise AcquisitionError("regular-slice receipt exceeds its byte bound")
        _verify_published_slice(
            destination_path,
            report.extracted_files,
            root_descriptor=destination_descriptor,
            root_identity=destination_identity,
        )
        receipt_sha256 = _write_new_atomic(receipt_path, receipt_bytes)
        try:
            _assert_repository_with_new_receipt(
                root,
                expected_revision=revision,
                receipt_relative=authorization.outputs.receipt_path,
            )
            for evidence in tracked_evidence:
                _assert_tracked_head_bytes(root, evidence.path, evidence.sha256)
            for tool in authorization.tool_files:
                _assert_tracked_head_bytes(root, tool.path, tool.sha256)
            for evidence in source_identities:
                _assert_no_symlink_ancestors(root, evidence.path, allow_missing_leaf=False)
            _assert_no_symlink_ancestors(
                root,
                authorization.outputs.claim_path,
                allow_missing_leaf=False,
            )
            _assert_no_symlink_ancestors(
                root,
                authorization.outputs.destination_path,
                allow_missing_leaf=False,
            )
            if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
                raise AcquisitionError("regular-slice claim changed during receipt publication")
            _assert_bound_directory(
                destination_path,
                destination_descriptor,
                destination_identity,
            )
            _verify_published_slice(
                destination_path,
                report.extracted_files,
                root_descriptor=destination_descriptor,
                root_identity=destination_identity,
            )
            for evidence in source_identities[1:]:
                if (
                    _assert_exact_file(
                        root / evidence.path,
                        source_bytes[evidence.path],
                        field=evidence.path,
                    )
                    != evidence.sha256
                ):
                    raise AcquisitionError(f"source evidence changed: {evidence.path}")
            current_archive = os.stat(
                root / authorization.archive_path,
                follow_symlinks=False,
            )
            current_archive_identity = (
                current_archive.st_dev,
                current_archive.st_ino,
                current_archive.st_size,
                current_archive.st_mtime_ns,
                current_archive.st_ctime_ns,
            )
            if current_archive_identity != archive_identity:
                raise AcquisitionError("archive metadata changed during receipt publication")
            if (
                _assert_exact_file(
                    receipt_path,
                    receipt_bytes,
                    field="regular-slice receipt",
                )
                != receipt_sha256
            ):
                raise AcquisitionError("regular-slice receipt changed during publication")
            _assert_repository_with_new_receipt(
                root,
                expected_revision=revision,
                receipt_relative=authorization.outputs.receipt_path,
            )
        except Exception:
            _retract_exact_new_receipt(receipt_path, receipt_bytes)
            raise
    return RegularSliceResult(
        authorization.authorization_id,
        report.archive_sha256,
        destination_path,
        claim_path,
        receipt_path,
        receipt_sha256,
        report.extracted_files,
    )


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AcquisitionError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="compact-vio-extract-regular-slice",
        description="Execute one authorized audit-bound regular-file compatibility slice.",
    )
    parser.add_argument("--authorization", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = run_authorized_regular_slice(args.authorization)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_code": "archive_regular_slice_failed",
                    "error_type": type(exc).__name__,
                    "event": "archive_regular_slice_failed",
                },
                allow_nan=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "archive_sha256": result.archive_sha256,
                "authorization_id": result.authorization_id,
                "destination_path": str(result.destination_path),
                "event": "archive_regular_slice_completed",
                "receipt_path": str(result.receipt_path),
                "receipt_sha256": result.receipt_sha256,
                "selected_file_count": len(result.extracted_files),
            },
            allow_nan=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

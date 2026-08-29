"""One-use controller for an existing archive's inert TAR-header audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
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
    _format_utc,
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
    DatasetArchiveCandidate,
    PublishedArchiveIdentity,
    TarLimits,
    TarStructuralAudit,
    audit_tar_structure,
    load_dataset_archive_candidate,
    verify_archive,
)

_RECORD_TYPE = "dataset_archive_structural_audit_authorization"
_SCHEMA_VERSION = "1.0.0"
_SCOPE = "retained_archive_read_only_structural_audit_only"
_POLICY_ID = "inert-tar-header-metadata-no-follow-no-extract/v1"
_POST_AUDIT_RESERVE_BYTES = 2_147_483_648
_MAX_AUDIT_BYTES = 268_435_456
_MAX_RECEIPT_BYTES = 1_048_576
_MAX_MEMBERS = 250_000
_MAX_MEMBER_SIZE_BYTES = 8_589_934_592
_MAX_EXPANDED_SIZE_BYTES = 274_877_906_944
_TOOL_PATHS = (
    "src/compact_vio/data/archive_audit.py",
    "src/compact_vio/data/acquisition.py",
    "src/compact_vio/data/archive.py",
)
_PERMITTED_OPERATIONS = (
    "write_claim",
    "verify_size",
    "verify_md5",
    "verify_sha256",
    "audit_tar_headers",
    "write_audit",
    "write_receipt",
)
_PROHIBITED_OPERATIONS = (
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
)


@dataclass(frozen=True, slots=True)
class StructuralAuditAuthorization:
    authorization_id: str
    authorization_path: str
    authorization_sha256: str
    authorized_at: datetime
    expires_at: datetime
    candidate_path: str
    candidate_sha256: str
    candidate: DatasetArchiveCandidate
    source_failure_path: str
    source_failure_sha256: str
    archive_path: str
    archive_identity: PublishedArchiveIdentity
    maximum_elapsed_seconds: int
    minimum_free_bytes: int
    tool_files: tuple[ToolIdentity, ...]
    limits: TarLimits
    maximum_audit_bytes: int
    retention_review_at: datetime
    outputs: AuditOutputs


@dataclass(frozen=True, slots=True)
class AuditOutputs:
    claim_path: str
    audit_path: str
    receipt_path: str


@dataclass(frozen=True, slots=True)
class StructuralAuditResult:
    authorization_id: str
    archive_sha256: str
    audit_sha256: str
    receipt_sha256: str
    audit_path: Path
    receipt_path: Path
    claim_path: Path


def _candidate_identity_with_sha(
    candidate: DatasetArchiveCandidate,
    sha256: str,
) -> PublishedArchiveIdentity:
    return replace(candidate.published_identity, sha256=sha256)


def load_structural_audit_authorization(
    path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str,
) -> StructuralAuditAuthorization:
    """Strictly parse an authorization without touching the retained archive."""

    root_path = Path(repo_root).resolve()
    authorization_path = Path(path)
    if not authorization_path.is_absolute():
        authorization_path = root_path / authorization_path
    authorization_path = authorization_path.resolve(strict=False)
    try:
        relative_authorization = authorization_path.relative_to(root_path).as_posix()
    except ValueError as exc:
        raise AcquisitionError("authorization must be inside the repository") from exc
    relative_authorization = _canonical_relative(
        relative_authorization,
        field="authorization path",
    )
    raw, parsed = _read_json_bytes(authorization_path, field="authorization")
    root = _mapping(
        parsed,
        field="authorization",
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
            "candidate",
            "source_failure",
            "archive_path",
            "archive_identity",
            "execution",
            "audit_limits",
            "permitted_operations",
            "prohibited_operations",
            "scientific_authority",
            "retention",
            "outputs",
        },
    )
    _literal(root["record_type"], _RECORD_TYPE, field="record_type")
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

    candidate_item = _mapping(root["candidate"], field="candidate", keys={"path", "sha256"})
    candidate_path = _canonical_relative(candidate_item["path"], field="candidate.path")
    candidate_sha256 = _sha256(candidate_item["sha256"], field="candidate.sha256")
    try:
        candidate = load_dataset_archive_candidate(root_path / candidate_path)
    except ArchiveError as exc:
        raise AcquisitionError(f"candidate record is invalid: {exc}") from exc

    source_failure = _mapping(
        root["source_failure"],
        field="source_failure",
        keys={"path", "sha256"},
    )
    source_failure_path = _canonical_relative(
        source_failure["path"],
        field="source_failure.path",
    )
    source_failure_sha256 = _sha256(
        source_failure["sha256"],
        field="source_failure.sha256",
    )

    archive_path = _canonical_relative(root["archive_path"], field="archive_path")
    archive_identity = _parse_archive_identity(root["archive_identity"])
    if archive_identity.sha256 is None:
        raise AcquisitionError("archive_identity.sha256 must bind the retained archive")
    if archive_identity != _candidate_identity_with_sha(candidate, archive_identity.sha256):
        raise AcquisitionError(
            "archive_identity must equal candidate identity plus received SHA-256"
        )
    if PurePosixPath(archive_path).name != archive_identity.filename:
        raise AcquisitionError("archive_path basename must equal archive_identity.filename")
    if not archive_path.startswith("data/quarantine/"):
        raise AcquisitionError("archive_path must remain under data/quarantine/")

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
        execution["maximum_elapsed_seconds"],
        field="execution.maximum_elapsed_seconds",
    )
    if maximum_elapsed > 3_600:
        raise AcquisitionError("maximum_elapsed_seconds must not exceed 3600")
    paid_cost = execution["maximum_paid_compute_cost_usd"]
    if type(paid_cost) is not int or paid_cost != 0:
        raise AcquisitionError("maximum_paid_compute_cost_usd must equal integer zero")
    minimum_free_bytes = _positive_int(
        execution["minimum_free_bytes"],
        field="execution.minimum_free_bytes",
    )
    required_free = _POST_AUDIT_RESERVE_BYTES + _MAX_AUDIT_BYTES + _MAX_RECEIPT_BYTES
    if minimum_free_bytes != required_free:
        raise AcquisitionError(
            "minimum_free_bytes must equal reserve plus maximum audit and receipt bytes"
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
                path=_canonical_relative(item["path"], field=f"execution.tool_files[{index}].path"),
                sha256=_sha256(item["sha256"], field=f"execution.tool_files[{index}].sha256"),
            )
        )
    if tuple(tool.path for tool in tools) != _TOOL_PATHS:
        raise AcquisitionError(f"execution.tool_files paths must equal {list(_TOOL_PATHS)!r}")

    audit_limits = _mapping(
        root["audit_limits"],
        field="audit_limits",
        keys={
            "max_members",
            "max_member_size_bytes",
            "max_expanded_size_bytes",
            "maximum_audit_bytes",
        },
    )
    try:
        limits = TarLimits(
            max_members=_positive_int(
                audit_limits["max_members"], field="audit_limits.max_members"
            ),
            max_member_size_bytes=_positive_int(
                audit_limits["max_member_size_bytes"],
                field="audit_limits.max_member_size_bytes",
            ),
            max_expanded_size_bytes=_positive_int(
                audit_limits["max_expanded_size_bytes"],
                field="audit_limits.max_expanded_size_bytes",
            ),
        )
    except ArchiveError as exc:
        raise AcquisitionError(f"invalid audit_limits: {exc}") from exc
    maximum_audit_bytes = _positive_int(
        audit_limits["maximum_audit_bytes"],
        field="audit_limits.maximum_audit_bytes",
    )
    if limits.max_members > _MAX_MEMBERS:
        raise AcquisitionError(f"audit_limits.max_members must not exceed {_MAX_MEMBERS}")
    if limits.max_member_size_bytes > _MAX_MEMBER_SIZE_BYTES:
        raise AcquisitionError("audit_limits.max_member_size_bytes exceeds the hard cap")
    if limits.max_expanded_size_bytes > _MAX_EXPANDED_SIZE_BYTES:
        raise AcquisitionError("audit_limits.max_expanded_size_bytes exceeds the hard cap")
    if maximum_audit_bytes > _MAX_AUDIT_BYTES:
        raise AcquisitionError("audit_limits.maximum_audit_bytes exceeds the hard cap")
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
            "approves_extraction",
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
        "retain_audit_evidence_until_review",
        field="retention.policy",
    )
    retention_review_at = _utc_timestamp(retention["review_at"], field="retention.review_at")
    if retention_review_at <= expires_at:
        raise AcquisitionError("retention.review_at must follow expires_at")
    _literal(retention["deletion_authorized"], False, field="retention.deletion_authorized")

    output_value = _mapping(
        root["outputs"],
        field="outputs",
        keys={"claim_path", "audit_path", "receipt_path"},
    )
    outputs = AuditOutputs(
        claim_path=_canonical_relative(output_value["claim_path"], field="outputs.claim_path"),
        audit_path=_canonical_relative(
            output_value["audit_path"],
            field="outputs.audit_path",
        ),
        receipt_path=_canonical_relative(
            output_value["receipt_path"],
            field="outputs.receipt_path",
        ),
    )
    archive_parent = PurePosixPath(archive_path).parent
    if PurePosixPath(outputs.claim_path).parent != archive_parent:
        raise AcquisitionError("outputs.claim_path must share the archive quarantine directory")
    if PurePosixPath(outputs.audit_path).parent != archive_parent:
        raise AcquisitionError("outputs.audit_path must share the archive quarantine directory")
    expected_receipt = f"governance/datasets/acquisitions/{authorization_id}.receipt.json"
    if outputs.receipt_path != expected_receipt:
        raise AcquisitionError(f"outputs.receipt_path must equal {expected_receipt!r}")
    if len({archive_path, outputs.claim_path, outputs.audit_path, outputs.receipt_path}) != 4:
        raise AcquisitionError("archive and output paths must be distinct")

    return StructuralAuditAuthorization(
        authorization_id=authorization_id,
        authorization_path=relative_authorization,
        authorization_sha256=hashlib.sha256(raw).hexdigest(),
        authorized_at=authorized_at,
        expires_at=expires_at,
        candidate_path=candidate_path,
        candidate_sha256=candidate_sha256,
        candidate=candidate,
        source_failure_path=source_failure_path,
        source_failure_sha256=source_failure_sha256,
        archive_path=archive_path,
        archive_identity=archive_identity,
        maximum_elapsed_seconds=maximum_elapsed,
        minimum_free_bytes=minimum_free_bytes,
        tool_files=tuple(tools),
        limits=limits,
        maximum_audit_bytes=maximum_audit_bytes,
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
        raise AcquisitionError("executing structural-audit modules are not authorized sources")


def _audit_document(audit: TarStructuralAudit) -> dict[str, object]:
    return {
        "archive_sha256": audit.archive_sha256,
        "expanded_regular_size_bytes": audit.expanded_regular_size_bytes,
        "member_count": audit.member_count,
        "members": [asdict(member) for member in audit.members],
        "non_regular_member_count": audit.non_regular_member_count,
        "policy_id": _POLICY_ID,
        "record_type": "dataset_archive_structural_audit",
        "regular_file_count": audit.regular_file_count,
        "schema_version": "1.0.0",
        "strict_extraction_compatible": audit.strict_extraction_compatible,
    }


def run_authorized_structural_audit(
    authorization_path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str | None = None,
) -> StructuralAuditResult:
    """Execute one header-only audit and publish its receipt last."""

    root = Path(repo_root or Path.cwd()).resolve()
    authorization = load_structural_audit_authorization(authorization_path, repo_root=root)
    now = _utc_now()
    if not authorization.authorized_at <= now < authorization.expires_at:
        raise AcquisitionError("authorization is not active at execution start")
    if authorization.maximum_elapsed_seconds > (authorization.expires_at - now).total_seconds():
        raise AcquisitionError(
            "remaining authorization lifetime is shorter than elapsed-time bound"
        )

    revision = _assert_clean_repository(root)
    _assert_runtime_sources(root)
    for relative, sha256 in (
        (authorization.authorization_path, authorization.authorization_sha256),
        (authorization.candidate_path, authorization.candidate_sha256),
        (authorization.source_failure_path, authorization.source_failure_sha256),
    ):
        _assert_tracked_head_bytes(root, relative, sha256)
    for tool in authorization.tool_files:
        _assert_tracked_head_bytes(root, tool.path, tool.sha256)

    archive_path = _assert_no_symlink_ancestors(
        root,
        authorization.archive_path,
        allow_missing_leaf=False,
    )
    claim_path = root / authorization.outputs.claim_path
    audit_path = root / authorization.outputs.audit_path
    receipt_path = root / authorization.outputs.receipt_path
    _assert_no_symlink_ancestors(root, authorization.outputs.claim_path, allow_missing_leaf=True)
    _assert_no_symlink_ancestors(
        root,
        authorization.outputs.audit_path,
        allow_missing_leaf=True,
    )
    _assert_no_symlink_ancestors(root, authorization.outputs.receipt_path, allow_missing_leaf=True)
    for path in (claim_path, audit_path, receipt_path):
        if os.path.lexists(path):
            raise AcquisitionError(f"one-use structural-audit path must be absent: {path}")
    if not _is_ignored(root, authorization.archive_path):
        raise AcquisitionError("retained archive path must remain Git-ignored")
    for relative in (authorization.outputs.claim_path, authorization.outputs.audit_path):
        if not _is_ignored(root, relative):
            raise AcquisitionError(f"runtime structural-audit path must be Git-ignored: {relative}")
    if _is_ignored(root, authorization.outputs.receipt_path):
        raise AcquisitionError("tracked structural-audit receipt must not be Git-ignored")
    if _disk_usage(archive_path.parent).free < authorization.minimum_free_bytes:
        raise AcquisitionError("insufficient free space for bounded audit evidence and reserve")

    started_at = _utc_now()
    started_monotonic = time.monotonic()
    claim = {
        "authorization_id": authorization.authorization_id,
        "authorization_sha256": authorization.authorization_sha256,
        "archive_sha256": authorization.archive_identity.sha256,
        "git_revision": revision,
        "record_type": "dataset_archive_structural_audit_claim",
        "schema_version": "1.0.0",
        "started_at": _format_utc(started_at),
    }
    claim_bytes = _canonical_json_bytes(claim)
    claim_sha256 = _write_new_atomic(claim_path, claim_bytes)
    remaining = authorization.maximum_elapsed_seconds - (time.monotonic() - started_monotonic)
    with _hard_deadline(remaining):
        try:
            verification = verify_archive(archive_path, authorization.archive_identity)
            audit = audit_tar_structure(
                archive_path,
                expected_sha256=verification.sha256,
                limits=authorization.limits,
            )
        except ArchiveError as exc:
            raise AcquisitionError(f"structural TAR audit failed: {exc}") from exc
        audit_bytes = _canonical_json_bytes(_audit_document(audit))
        if len(audit_bytes) > authorization.maximum_audit_bytes:
            raise AcquisitionError("canonical structural audit exceeds its byte bound")
        audit_sha256 = _write_new_atomic(audit_path, audit_bytes)

        _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="structural audit",
        )
        if (authorization.expires_at - _utc_now()).total_seconds() < 5:
            raise AcquisitionError("authorization expires too soon for receipt publication")
        final_revision = _assert_clean_repository(root)
        if final_revision != revision:
            raise AcquisitionError("Git revision changed during structural audit")
        for relative, sha256 in (
            (authorization.authorization_path, authorization.authorization_sha256),
            (authorization.candidate_path, authorization.candidate_sha256),
            (authorization.source_failure_path, authorization.source_failure_sha256),
        ):
            _assert_tracked_head_bytes(root, relative, sha256)
        for tool in authorization.tool_files:
            _assert_tracked_head_bytes(root, tool.path, tool.sha256)
        _assert_no_symlink_ancestors(root, authorization.archive_path, allow_missing_leaf=False)
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.claim_path,
            allow_missing_leaf=False,
        )
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.audit_path,
            allow_missing_leaf=False,
        )
        _assert_no_symlink_ancestors(
            root,
            authorization.outputs.receipt_path,
            allow_missing_leaf=True,
        )
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("claim SHA-256 changed before receipt publication")
        if _assert_exact_file(audit_path, audit_bytes, field="audit") != audit_sha256:
            raise AcquisitionError("audit SHA-256 changed before receipt publication")
        try:
            final_verification = verify_archive(archive_path, authorization.archive_identity)
        except ArchiveError as exc:
            raise AcquisitionError(f"final archive revalidation failed: {exc}") from exc
        if final_verification.sha256 != verification.sha256:
            raise AcquisitionError("archive identity changed before receipt publication")

        elapsed = _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="receipt",
        )
        receipt_prepared_at = _utc_now()
        if (authorization.expires_at - receipt_prepared_at).total_seconds() < 5:
            raise AcquisitionError("authorization expires too soon for atomic receipt publication")
        receipt = {
            "archive": {
                "archive_id": verification.archive_id,
                "filename": verification.filename,
                "md5": verification.md5,
                "path": authorization.archive_path,
                "sha256": verification.sha256,
                "size_bytes": verification.size_bytes,
            },
            "audit": {
                "expanded_regular_size_bytes": audit.expanded_regular_size_bytes,
                "maximum_serialized_bytes": authorization.maximum_audit_bytes,
                "member_count": audit.member_count,
                "non_regular_member_count": audit.non_regular_member_count,
                "path": authorization.outputs.audit_path,
                "policy_id": _POLICY_ID,
                "regular_file_count": audit.regular_file_count,
                "serialized_bytes": len(audit_bytes),
                "sha256": audit_sha256,
                "strict_extraction_compatible": audit.strict_extraction_compatible,
            },
            "authorization": {
                "id": authorization.authorization_id,
                "path": authorization.authorization_path,
                "sha256": authorization.authorization_sha256,
            },
            "claim": {
                "path": authorization.outputs.claim_path,
                "sha256": claim_sha256,
            },
            "execution": {
                "controller_initiated_paid_service_cost_usd": 0,
                "elapsed_seconds": elapsed,
                "git_revision": revision,
                "maximum_elapsed_seconds": authorization.maximum_elapsed_seconds,
                "tool_files": [asdict(tool) for tool in authorization.tool_files],
            },
            "operations_not_performed": list(_PROHIBITED_OPERATIONS),
            "operations_performed": list(_PERMITTED_OPERATIONS),
            "outcome": "completed",
            "receipt_prepared_at": _format_utc(receipt_prepared_at),
            "record_type": "dataset_archive_structural_audit_receipt",
            "retention": {
                "deletion_authorized": False,
                "policy": "retain_audit_evidence_until_review",
                "review_at": _format_utc(authorization.retention_review_at),
            },
            "schema_version": "1.0.0",
            "scientific_authority": "none",
            "scientific_limitations": (
                "Header classification neither follows nor extracts links and does not approve "
                "extraction, dataset selection, model access, training, inference, evaluation, "
                "publication, deployment, UAV-domain, or superiority claims."
            ),
            "source_failure": {
                "path": authorization.source_failure_path,
                "sha256": authorization.source_failure_sha256,
            },
            "started_at": _format_utc(started_at),
        }
        receipt_bytes = _canonical_json_bytes(receipt)
        if len(receipt_bytes) > _MAX_RECEIPT_BYTES:
            raise AcquisitionError("structural-audit receipt exceeds its byte bound")
        signal.setitimer(signal.ITIMER_REAL, 0)
        receipt_sha256 = _write_new_atomic(receipt_path, receipt_bytes)
    return StructuralAuditResult(
        authorization_id=authorization.authorization_id,
        archive_sha256=verification.sha256,
        audit_sha256=audit_sha256,
        receipt_sha256=receipt_sha256,
        audit_path=audit_path,
        receipt_path=receipt_path,
        claim_path=claim_path,
    )


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AcquisitionError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="compact-vio-audit-archive-structure",
        description="Execute one authorized inert TAR-header structural audit.",
    )
    parser.add_argument("--authorization", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = run_authorized_structural_audit(args.authorization)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_code": "archive_structural_audit_failed",
                    "error_type": type(exc).__name__,
                    "event": "archive_structural_audit_failed",
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
                "audit_path": str(result.audit_path),
                "audit_sha256": result.audit_sha256,
                "authorization_id": result.authorization_id,
                "event": "archive_structural_audit_completed",
                "receipt_path": str(result.receipt_path),
                "receipt_sha256": result.receipt_sha256,
            },
            allow_nan=False,
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

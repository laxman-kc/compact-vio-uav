"""One-use, operational-only dataset archive acquisition.

The controller in this module is intentionally narrower than a dataset adapter.
It may transfer one pre-authorized archive, verify the publisher identity,
compute SHA-256, and inventory TAR headers.  It never extracts data, decodes
samples, loads checkpoints, trains, infers, evaluates, or selects a dataset.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

import compact_vio.data.archive as archive_module
from compact_vio.data.archive import (
    ArchiveError,
    AuthorizedArchiveAcquisition,
    DatasetArchiveCandidate,
    PublishedArchiveIdentity,
    TarInventory,
    TarLimits,
    download_archive,
    inventory_tar,
    load_dataset_archive_candidate,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_UTC_SECONDS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_RECORD_TYPE = "dataset_archive_transfer_authorization"
_SCHEMA_VERSION = "1.0.0"
_SCOPE = "operational_byte_transfer_and_read_only_inventory_only"
_POST_TRANSFER_RESERVE_BYTES = 2_147_483_648
_MAX_INVENTORY_BYTES = 268_435_456
_MAX_RECEIPT_BYTES = 1_048_576
_MAX_MEMBERS = 250_000
_MAX_MEMBER_SIZE_BYTES = 8_589_934_592
_MAX_EXPANDED_SIZE_BYTES = 274_877_906_944
_PERMITTED_OPERATIONS = (
    "write_claim",
    "download",
    "verify_size",
    "verify_md5",
    "compute_sha256",
    "inventory_tar_headers",
    "write_inventory",
    "write_receipt",
)
_PROHIBITED_OPERATIONS = (
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
_TOOL_PATHS = (
    "src/compact_vio/data/acquisition.py",
    "src/compact_vio/data/archive.py",
)


class AcquisitionError(RuntimeError):
    """Raised when the one-use acquisition boundary cannot be preserved."""


@dataclass(frozen=True, slots=True)
class ToolIdentity:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class TransferOutputs:
    claim_path: str
    inventory_path: str
    receipt_path: str


@dataclass(frozen=True, slots=True)
class TransferAuthorization:
    """Strictly validated operational authority for one workspace execution."""

    authorization_id: str
    authorization_path: str
    authorization_sha256: str
    authority_instruction: str
    authorized_at: datetime
    expires_at: datetime
    candidate_path: str
    candidate_sha256: str
    candidate: DatasetArchiveCandidate
    archive_identity: PublishedArchiveIdentity
    archive_path: str
    minimum_post_transfer_free_bytes: int
    minimum_initial_free_bytes: int
    maximum_elapsed_seconds: int
    tool_files: tuple[ToolIdentity, ...]
    inventory_limits: TarLimits
    maximum_inventory_bytes: int
    retention_review_at: datetime
    outputs: TransferOutputs


@dataclass(frozen=True, slots=True)
class AcquisitionResult:
    authorization_id: str
    archive_sha256: str
    inventory_sha256: str
    receipt_sha256: str
    receipt_path: Path
    inventory_path: Path
    claim_path: Path


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str:
            raise AcquisitionError("JSON object keys must be strings")
        if key in result:
            raise AcquisitionError(f"duplicate JSON field is prohibited: {key!r}")
        result[key] = value
    return result


def _mapping(value: object, *, field: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise AcquisitionError(f"{field} must be a JSON object with string keys")
    if set(value) != keys:
        raise AcquisitionError(f"{field} fields must equal {sorted(keys)!r}")
    return value


def _text(value: object, *, field: str) -> str:
    if type(value) is not str or not value:
        raise AcquisitionError(f"{field} must be a non-empty string")
    return value


def _identifier(value: object, *, field: str) -> str:
    result = _text(value, field=field)
    if _SAFE_ID.fullmatch(result) is None or result in (".", ".."):
        raise AcquisitionError(f"{field} must be one safe identifier")
    return result


def _sha256(value: object, *, field: str) -> str:
    if type(value) is not str or _HEX_64.fullmatch(value) is None:
        raise AcquisitionError(f"{field} must be 64 lowercase hexadecimal characters")
    return value


def _positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise AcquisitionError(f"{field} must be a positive integer")
    return value


def _literal(value: object, expected: object, *, field: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise AcquisitionError(f"{field} must equal {expected!r}")


def _utc_timestamp(value: object, *, field: str) -> datetime:
    text = _text(value, field=field)
    if _UTC_SECONDS.fullmatch(text) is None:
        raise AcquisitionError(f"{field} must be a second-precision UTC timestamp")
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AcquisitionError(f"{field} is not a valid UTC timestamp") from exc
    return parsed


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_relative(value: object, *, field: str) -> str:
    text = _text(value, field=field)
    if "\\" in text or "\x00" in text:
        raise AcquisitionError(f"{field} must be a canonical repository-relative POSIX path")
    path = PurePosixPath(text)
    if path.is_absolute() or path.as_posix() != text:
        raise AcquisitionError(f"{field} must be a canonical repository-relative POSIX path")
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise AcquisitionError(f"{field} contains an unsafe component")
    return text


def _exact_string_list(value: object, expected: tuple[str, ...], *, field: str) -> None:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise AcquisitionError(f"{field} must be a JSON string array")
    if tuple(value) != expected:
        raise AcquisitionError(f"{field} must equal {list(expected)!r}")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AcquisitionError(f"cannot open regular file {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise AcquisitionError(f"path is not a regular file: {path}")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        final = os.fstat(descriptor)
        if (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        ) != (
            final.st_dev,
            final.st_ino,
            final.st_size,
            final.st_mtime_ns,
            final.st_ctime_ns,
        ):
            raise AcquisitionError(f"file changed while hashing: {path}")
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        text = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise AcquisitionError(f"record is not canonical-JSON serializable: {exc}") from exc
    return (text + "\n").encode("utf-8")


def _read_json_bytes(path: Path, *, field: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except AcquisitionError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AcquisitionError(f"cannot read {field} {path}: {exc}") from exc
    if type(parsed) is not dict:
        raise AcquisitionError(f"{field} must be a JSON object")
    return raw, parsed


def _parse_archive_identity(value: object) -> PublishedArchiveIdentity:
    item = _mapping(
        value,
        field="archive_identity",
        keys={
            "archive_id",
            "filename",
            "url",
            "size_bytes",
            "md5",
            "sha256",
            "allowed_redirect_urls",
            "allowed_redirect_origins",
        },
    )
    if type(item["allowed_redirect_urls"]) is not list or any(
        type(entry) is not str for entry in item["allowed_redirect_urls"]
    ):
        raise AcquisitionError("archive_identity.allowed_redirect_urls must be a string array")
    if type(item["allowed_redirect_origins"]) is not list or any(
        type(entry) is not str for entry in item["allowed_redirect_origins"]
    ):
        raise AcquisitionError("archive_identity.allowed_redirect_origins must be a string array")
    try:
        return PublishedArchiveIdentity(
            archive_id=item["archive_id"],
            filename=item["filename"],
            url=item["url"],
            size_bytes=item["size_bytes"],
            md5=item["md5"],
            sha256=item["sha256"],
            allowed_redirect_urls=tuple(item["allowed_redirect_urls"]),
            allowed_redirect_origins=tuple(item["allowed_redirect_origins"]),
        )
    except ArchiveError as exc:
        raise AcquisitionError(f"invalid archive_identity: {exc}") from exc


def _identity_mapping(identity: PublishedArchiveIdentity) -> dict[str, object]:
    return {
        "archive_id": identity.archive_id,
        "filename": identity.filename,
        "url": identity.url,
        "size_bytes": identity.size_bytes,
        "md5": identity.md5,
        "sha256": identity.sha256,
        "allowed_redirect_urls": list(identity.allowed_redirect_urls),
        "allowed_redirect_origins": list(identity.allowed_redirect_origins),
    }


def load_transfer_authorization(
    path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str,
) -> TransferAuthorization:
    """Parse the exact authorization schema without performing a transfer."""

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
            "archive_identity",
            "destination",
            "execution",
            "inventory_limits",
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
    instruction = _text(
        authority["instruction_summary"],
        field="authority_basis.instruction_summary",
    )
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
    archive_identity = _parse_archive_identity(root["archive_identity"])
    if _identity_mapping(archive_identity) != _identity_mapping(candidate.published_identity):
        raise AcquisitionError("archive_identity must equal the strict candidate identity")
    if archive_identity.sha256 is not None:
        raise AcquisitionError("first-transfer archive_identity.sha256 must be null")

    destination = _mapping(
        root["destination"],
        field="destination",
        keys={
            "archive_path",
            "initial_archive_state",
            "initial_partial_state",
            "must_be_git_ignored",
            "minimum_post_transfer_free_bytes",
            "minimum_initial_free_bytes",
        },
    )
    archive_path = _canonical_relative(
        destination["archive_path"], field="destination.archive_path"
    )
    if (
        not archive_path.startswith("data/")
        or PurePosixPath(archive_path).name != archive_identity.filename
    ):
        raise AcquisitionError(
            "destination.archive_path must be the exact archive basename under data/"
        )
    _literal(
        destination["initial_archive_state"], "absent", field="destination.initial_archive_state"
    )
    _literal(
        destination["initial_partial_state"], "absent", field="destination.initial_partial_state"
    )
    _literal(destination["must_be_git_ignored"], True, field="destination.must_be_git_ignored")
    minimum_post = _positive_int(
        destination["minimum_post_transfer_free_bytes"],
        field="destination.minimum_post_transfer_free_bytes",
    )
    if minimum_post != _POST_TRANSFER_RESERVE_BYTES:
        raise AcquisitionError("minimum_post_transfer_free_bytes must equal 2147483648")
    minimum_initial = _positive_int(
        destination["minimum_initial_free_bytes"],
        field="destination.minimum_initial_free_bytes",
    )
    required_initial = (
        archive_identity.size_bytes + minimum_post + _MAX_INVENTORY_BYTES + _MAX_RECEIPT_BYTES
    )
    if minimum_initial != required_initial:
        raise AcquisitionError(
            "minimum_initial_free_bytes must equal archive, reserve, and bounded evidence"
        )

    execution = _mapping(
        root["execution"],
        field="execution",
        keys={
            "requires_clean_worktree",
            "maximum_elapsed_seconds",
            "maximum_paid_compute_cost_usd",
            "tool_files",
        },
    )
    _literal(execution["requires_clean_worktree"], True, field="execution.requires_clean_worktree")
    maximum_elapsed = _positive_int(
        execution["maximum_elapsed_seconds"],
        field="execution.maximum_elapsed_seconds",
    )
    if maximum_elapsed > 14_400:
        raise AcquisitionError("maximum_elapsed_seconds must not exceed 14400")
    paid_cost = execution["maximum_paid_compute_cost_usd"]
    if type(paid_cost) is not int or paid_cost != 0:
        raise AcquisitionError("maximum_paid_compute_cost_usd must equal integer zero")
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

    inventory_value = _mapping(
        root["inventory_limits"],
        field="inventory_limits",
        keys={
            "max_members",
            "max_member_size_bytes",
            "max_expanded_size_bytes",
            "maximum_inventory_bytes",
        },
    )
    try:
        limits = TarLimits(
            max_members=_positive_int(
                inventory_value["max_members"], field="inventory_limits.max_members"
            ),
            max_member_size_bytes=_positive_int(
                inventory_value["max_member_size_bytes"],
                field="inventory_limits.max_member_size_bytes",
            ),
            max_expanded_size_bytes=_positive_int(
                inventory_value["max_expanded_size_bytes"],
                field="inventory_limits.max_expanded_size_bytes",
            ),
        )
    except ArchiveError as exc:
        raise AcquisitionError(f"invalid inventory_limits: {exc}") from exc
    maximum_inventory_bytes = _positive_int(
        inventory_value["maximum_inventory_bytes"],
        field="inventory_limits.maximum_inventory_bytes",
    )
    if limits.max_members > _MAX_MEMBERS:
        raise AcquisitionError(f"inventory_limits.max_members must not exceed {_MAX_MEMBERS}")
    if limits.max_member_size_bytes > _MAX_MEMBER_SIZE_BYTES:
        raise AcquisitionError(
            "inventory_limits.max_member_size_bytes exceeds the project hard cap"
        )
    if limits.max_expanded_size_bytes > _MAX_EXPANDED_SIZE_BYTES:
        raise AcquisitionError(
            "inventory_limits.max_expanded_size_bytes exceeds the project hard cap"
        )
    if maximum_inventory_bytes > _MAX_INVENTORY_BYTES:
        raise AcquisitionError(
            f"inventory_limits.maximum_inventory_bytes must not exceed {_MAX_INVENTORY_BYTES}"
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
        "retain_in_quarantine_until_review",
        field="retention.policy",
    )
    review_at = _utc_timestamp(retention["review_at"], field="retention.review_at")
    if review_at <= expires_at:
        raise AcquisitionError("retention.review_at must follow expires_at")
    _literal(retention["deletion_authorized"], False, field="retention.deletion_authorized")

    output_value = _mapping(
        root["outputs"],
        field="outputs",
        keys={"claim_path", "inventory_path", "receipt_path"},
    )
    outputs = TransferOutputs(
        claim_path=_canonical_relative(output_value["claim_path"], field="outputs.claim_path"),
        inventory_path=_canonical_relative(
            output_value["inventory_path"], field="outputs.inventory_path"
        ),
        receipt_path=_canonical_relative(
            output_value["receipt_path"], field="outputs.receipt_path"
        ),
    )
    archive_parent = PurePosixPath(archive_path).parent
    if PurePosixPath(outputs.claim_path).parent != archive_parent:
        raise AcquisitionError("outputs.claim_path must share the archive quarantine directory")
    if PurePosixPath(outputs.inventory_path).parent != archive_parent:
        raise AcquisitionError("outputs.inventory_path must share the archive quarantine directory")
    expected_receipt = f"governance/datasets/acquisitions/{authorization_id}.receipt.json"
    if outputs.receipt_path != expected_receipt:
        raise AcquisitionError(f"outputs.receipt_path must equal {expected_receipt!r}")
    if len({archive_path, outputs.claim_path, outputs.inventory_path, outputs.receipt_path}) != 4:
        raise AcquisitionError("archive and output paths must be distinct")
    if (
        outputs.claim_path == f"{archive_path}.part"
        or outputs.inventory_path == f"{archive_path}.part"
    ):
        raise AcquisitionError("output paths must not collide with the resumable partial archive")

    return TransferAuthorization(
        authorization_id=authorization_id,
        authorization_path=relative_authorization,
        authorization_sha256=hashlib.sha256(raw).hexdigest(),
        authority_instruction=instruction,
        authorized_at=authorized_at,
        expires_at=expires_at,
        candidate_path=candidate_path,
        candidate_sha256=candidate_sha256,
        candidate=candidate,
        archive_identity=archive_identity,
        archive_path=archive_path,
        minimum_post_transfer_free_bytes=minimum_post,
        minimum_initial_free_bytes=minimum_initial,
        maximum_elapsed_seconds=maximum_elapsed,
        tool_files=tuple(tools),
        inventory_limits=limits,
        maximum_inventory_bytes=maximum_inventory_bytes,
        retention_review_at=review_at,
        outputs=outputs,
    )


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=check,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AcquisitionError(f"Git provenance check failed: {' '.join(arguments)}") from exc


def _assert_no_symlink_ancestors(root: Path, relative: str, *, allow_missing_leaf: bool) -> Path:
    current = root
    parts = PurePosixPath(relative).parts
    for index, part in enumerate(parts):
        current = current / part
        is_leaf = index == len(parts) - 1
        try:
            metadata = os.lstat(current)
        except FileNotFoundError:
            if is_leaf and allow_missing_leaf:
                return current
            raise AcquisitionError(f"required path component does not exist: {current}") from None
        if stat.S_ISLNK(metadata.st_mode):
            raise AcquisitionError(f"symlink path component is prohibited: {current}")
        if not is_leaf and not stat.S_ISDIR(metadata.st_mode):
            raise AcquisitionError(f"path ancestor is not a directory: {current}")
    return current


def _ensure_real_directory(root: Path, relative_parent: PurePosixPath) -> Path:
    current = root
    for part in relative_parent.parts:
        current = current / part
        try:
            os.mkdir(current, 0o700)
        except FileExistsError:
            pass
        metadata = os.lstat(current)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise AcquisitionError(f"quarantine ancestor must be a real directory: {current}")
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o022:
            raise AcquisitionError(
                "quarantine ancestor must be owner-controlled and not group/world "
                f"writable: {current}"
            )
    return current


def _assert_tracked_head_bytes(root: Path, relative: str, expected_sha256: str) -> None:
    path = _assert_no_symlink_ancestors(root, relative, allow_missing_leaf=False)
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode):
        raise AcquisitionError(f"tracked evidence is not a regular file: {relative}")
    _git(root, "ls-files", "--error-unmatch", "--", relative)
    head = _git(root, "show", f"HEAD:{relative}").stdout
    try:
        current = path.read_bytes()
    except OSError as exc:
        raise AcquisitionError(f"cannot read tracked evidence {relative}: {exc}") from exc
    if current != head:
        raise AcquisitionError(f"tracked evidence differs from HEAD: {relative}")
    if hashlib.sha256(current).hexdigest() != expected_sha256:
        raise AcquisitionError(f"tracked evidence SHA-256 mismatch: {relative}")


def _assert_clean_repository(root: Path) -> str:
    top = Path(_git(root, "rev-parse", "--show-toplevel").stdout.decode().strip()).resolve()
    if top != root.resolve():
        raise AcquisitionError("repo_root must be the exact Git worktree root")
    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    if status:
        raise AcquisitionError("repository worktree and index must be clean")
    revision = _git(root, "rev-parse", "HEAD").stdout.decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise AcquisitionError("Git HEAD must be a full SHA-1 revision")
    return revision


def _assert_runtime_sources(root: Path) -> None:
    expected_acquisition = (root / _TOOL_PATHS[0]).resolve()
    expected_archive = (root / _TOOL_PATHS[1]).resolve()
    actual_acquisition = Path(__file__).resolve()
    archive_file = getattr(archive_module, "__file__", None)
    if type(archive_file) is not str:
        raise AcquisitionError("loaded archive module has no filesystem source identity")
    actual_archive = Path(archive_file).resolve()
    if actual_acquisition != expected_acquisition:
        raise AcquisitionError(
            "executing acquisition module is not the authorized repository source"
        )
    if actual_archive != expected_archive:
        raise AcquisitionError("executing archive module is not the authorized repository source")


def _is_ignored(root: Path, relative: str) -> bool:
    result = _git(root, "check-ignore", "-q", "--", relative, check=False)
    return result.returncode == 0


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new_atomic(path: Path, payload: bytes) -> str:
    """Publish complete bytes at a new path using a same-directory hard link."""

    digest = hashlib.sha256(payload).hexdigest()
    staged = path.with_name(f".{path.name}.staged-{os.getpid()}-{time.time_ns()}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(staged, flags, 0o600)
    except FileExistsError as exc:
        raise AcquisitionError(f"staged evidence path already exists: {staged}") from exc
    except OSError as exc:
        raise AcquisitionError(
            f"cannot create staged acquisition evidence {staged}: {exc}"
        ) from exc
    published_metadata: os.stat_result | None = None
    try:
        try:
            written = 0
            while written < len(payload):
                count = os.write(descriptor, payload[written:])
                if count <= 0:
                    raise AcquisitionError(f"short write while creating {staged}")
                written += count
            os.fsync(descriptor)
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise AcquisitionError("staged evidence must be one regular single-link file")
        finally:
            os.close(descriptor)
        if _file_sha256(staged) != digest:
            raise AcquisitionError("staged evidence digest mismatch")
        try:
            os.link(staged, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise AcquisitionError(f"refusing to overwrite acquisition evidence: {path}") from exc
        published_metadata = os.stat(path, follow_symlinks=False)
        _fsync_directory(path.parent)
        if _file_sha256(path) != digest:
            raise AcquisitionError("published evidence digest mismatch")
    except Exception:
        if published_metadata is not None:
            try:
                current = os.stat(path, follow_symlinks=False)
                if (
                    current.st_dev == published_metadata.st_dev
                    and current.st_ino == published_metadata.st_ino
                ):
                    path.unlink()
                    _fsync_directory(path.parent)
            except OSError:
                pass
        raise
    finally:
        try:
            staged.unlink()
        except FileNotFoundError:
            pass
        _fsync_directory(path.parent)
    return digest


def _assert_exact_file(path: Path, expected: bytes, *, field: str) -> str:
    metadata = os.lstat(path)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise AcquisitionError(f"{field} must be one regular single-link file")
    try:
        actual = path.read_bytes()
    except OSError as exc:
        raise AcquisitionError(f"cannot re-read {field}: {exc}") from exc
    if actual != expected:
        raise AcquisitionError(f"{field} bytes changed before receipt publication")
    return hashlib.sha256(actual).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _disk_usage(path: Path) -> shutil._ntuple_diskusage:  # type: ignore[name-defined]
    return shutil.disk_usage(path)


def _inventory_document(inventory: TarInventory) -> dict[str, object]:
    return {
        "archive_sha256": inventory.archive_sha256,
        "expanded_size_bytes": inventory.expanded_size_bytes,
        "file_count": inventory.file_count,
        "members": [asdict(member) for member in inventory.members],
        "record_type": "dataset_archive_tar_inventory",
        "schema_version": "1.0.0",
    }


def _check_deadline(started: float, maximum: int, *, phase: str) -> float:
    elapsed = time.monotonic() - started
    if elapsed > maximum:
        raise AcquisitionError(f"maximum elapsed time exceeded during {phase}")
    return elapsed


@contextmanager
def _hard_deadline(seconds: float) -> Iterator[None]:
    if seconds <= 0:
        raise AcquisitionError("no elapsed-time authority remains")
    if not hasattr(signal, "SIGALRM") or not hasattr(signal, "setitimer"):
        raise AcquisitionError("hard acquisition deadlines require POSIX interval timers")
    if not hasattr(signal, "pthread_sigmask"):
        raise AcquisitionError("hard acquisition deadlines require signal-mask inspection")
    try:
        blocked_signals = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    except (OSError, ValueError) as exc:
        raise AcquisitionError("cannot inspect the process signal mask") from exc
    if signal.SIGALRM in blocked_signals:
        raise AcquisitionError("SIGALRM is blocked; hard elapsed deadline is unavailable")

    def timeout_handler(_signum: int, _frame: object) -> None:
        raise AcquisitionError("maximum elapsed time exceeded")

    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0] > 0 or previous_timer[1] > 0:
        raise AcquisitionError("a preexisting process timer prevents a bounded acquisition")
    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def run_authorized_transfer(
    authorization_path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str | None = None,
) -> AcquisitionResult:
    """Execute one authorized transfer and publish receipt evidence last."""

    root = Path(repo_root or Path.cwd()).resolve()
    authorization = load_transfer_authorization(authorization_path, repo_root=root)
    now = _utc_now()
    if not authorization.authorized_at <= now < authorization.expires_at:
        raise AcquisitionError("authorization is not active at execution start")
    if authorization.maximum_elapsed_seconds > (authorization.expires_at - now).total_seconds():
        raise AcquisitionError(
            "remaining authorization lifetime is shorter than elapsed-time bound"
        )

    revision = _assert_clean_repository(root)
    _assert_runtime_sources(root)
    _assert_tracked_head_bytes(
        root,
        authorization.authorization_path,
        authorization.authorization_sha256,
    )
    _assert_tracked_head_bytes(
        root,
        authorization.candidate_path,
        authorization.candidate_sha256,
    )
    for tool in authorization.tool_files:
        _assert_tracked_head_bytes(root, tool.path, tool.sha256)

    archive_relative = PurePosixPath(authorization.archive_path)
    quarantine = _ensure_real_directory(root, archive_relative.parent)
    archive_path = root / authorization.archive_path
    partial_path = archive_path.with_name(f"{archive_path.name}.part")
    claim_path = root / authorization.outputs.claim_path
    inventory_path = root / authorization.outputs.inventory_path
    receipt_path = root / authorization.outputs.receipt_path
    _assert_no_symlink_ancestors(root, authorization.outputs.receipt_path, allow_missing_leaf=True)
    for path in (archive_path, partial_path, claim_path, inventory_path, receipt_path):
        if os.path.lexists(path):
            raise AcquisitionError(f"one-use acquisition path must be absent: {path}")
    for relative in (
        authorization.archive_path,
        authorization.outputs.claim_path,
        authorization.outputs.inventory_path,
    ):
        if not _is_ignored(root, relative):
            raise AcquisitionError(f"runtime acquisition path must be Git-ignored: {relative}")
    if _is_ignored(root, authorization.outputs.receipt_path):
        raise AcquisitionError("tracked receipt path must not be Git-ignored")

    before_free = _disk_usage(quarantine).free
    if before_free < authorization.minimum_initial_free_bytes:
        raise AcquisitionError("insufficient free space for archive plus retained reserve")

    started_at = _utc_now()
    started_monotonic = time.monotonic()
    claim = {
        "authorization_id": authorization.authorization_id,
        "authorization_sha256": authorization.authorization_sha256,
        "candidate_sha256": authorization.candidate_sha256,
        "git_revision": revision,
        "record_type": "dataset_archive_transfer_claim",
        "schema_version": "1.0.0",
        "started_at": _format_utc(started_at),
    }
    claim_bytes = _canonical_json_bytes(claim)
    claim_sha256 = _write_new_atomic(claim_path, claim_bytes)
    _check_deadline(started_monotonic, authorization.maximum_elapsed_seconds, phase="claim")

    capability = AuthorizedArchiveAcquisition._from_validated_record(
        identity=authorization.archive_identity,
        authorization_record_id=authorization.authorization_id,
        authorization_record_sha256=authorization.authorization_sha256,
        destination_path=str(archive_path.absolute()),
        reviewed_by="active_workspace_user_instruction",
        reviewed_at=_format_utc(authorization.authorized_at),
    )
    remaining = authorization.maximum_elapsed_seconds - (time.monotonic() - started_monotonic)
    with _hard_deadline(remaining):
        try:
            verification = download_archive(
                capability,
                archive_path,
                timeout_seconds=min(120.0, max(1.0, remaining)),
            )
        except ArchiveError as exc:
            raise AcquisitionError(f"archive transfer failed: {exc}") from exc
        _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="download",
        )
        if verification.resolved_url is None:
            raise AcquisitionError("first transfer must record a resolved source URL")
        expected_result_fields = (
            verification.archive_id == authorization.archive_identity.archive_id,
            verification.filename == authorization.archive_identity.filename,
            verification.source_url == authorization.archive_identity.url,
            verification.size_bytes == authorization.archive_identity.size_bytes,
            verification.md5 == authorization.archive_identity.md5,
        )
        if not all(expected_result_fields):
            raise AcquisitionError(
                "archive result does not match the authorized publisher identity"
            )
        if verification.authorization_record_id != authorization.authorization_id:
            raise AcquisitionError("archive result authorization ID mismatch")
        if verification.authorization_record_sha256 != authorization.authorization_sha256:
            raise AcquisitionError("archive result authorization SHA-256 mismatch")
        _assert_no_symlink_ancestors(root, authorization.archive_path, allow_missing_leaf=False)
        remaining_metadata = authorization.maximum_inventory_bytes + _MAX_RECEIPT_BYTES
        if (
            _disk_usage(quarantine).free
            < authorization.minimum_post_transfer_free_bytes + remaining_metadata
        ):
            raise AcquisitionError("post-transfer evidence reserve was not preserved")

        try:
            inventory = inventory_tar(
                archive_path,
                expected_sha256=verification.sha256,
                limits=authorization.inventory_limits,
            )
        except ArchiveError as exc:
            raise AcquisitionError(f"read-only TAR inventory failed: {exc}") from exc
        if inventory.archive_sha256 != verification.sha256:
            raise AcquisitionError("TAR inventory archive SHA-256 mismatch")
        inventory_bytes = _canonical_json_bytes(_inventory_document(inventory))
        if len(inventory_bytes) > authorization.maximum_inventory_bytes:
            raise AcquisitionError("canonical inventory exceeds its authorized byte bound")
        free_before_inventory = _disk_usage(quarantine).free
        required_inventory_free = (
            authorization.minimum_post_transfer_free_bytes
            + len(inventory_bytes)
            + _MAX_RECEIPT_BYTES
        )
        if free_before_inventory < required_inventory_free:
            raise AcquisitionError("insufficient reserve for canonical inventory evidence")
        inventory_sha256 = _write_new_atomic(inventory_path, inventory_bytes)
        _check_deadline(
            started_monotonic,
            authorization.maximum_elapsed_seconds,
            phase="inventory",
        )

        now_before_receipt = _utc_now()
        if (authorization.expires_at - now_before_receipt).total_seconds() < 5:
            raise AcquisitionError("authorization expires too soon for success receipt")
        if (
            _disk_usage(quarantine).free
            < authorization.minimum_post_transfer_free_bytes + _MAX_RECEIPT_BYTES
        ):
            raise AcquisitionError("final evidence reserve was not preserved")
        final_revision = _assert_clean_repository(root)
        if final_revision != revision:
            raise AcquisitionError("Git revision changed during acquisition")
        _assert_tracked_head_bytes(
            root,
            authorization.authorization_path,
            authorization.authorization_sha256,
        )
        _assert_tracked_head_bytes(
            root, authorization.candidate_path, authorization.candidate_sha256
        )
        for tool in authorization.tool_files:
            _assert_tracked_head_bytes(root, tool.path, tool.sha256)
        _assert_no_symlink_ancestors(root, authorization.archive_path, allow_missing_leaf=False)
        _assert_no_symlink_ancestors(
            root, authorization.outputs.claim_path, allow_missing_leaf=False
        )
        _assert_no_symlink_ancestors(
            root, authorization.outputs.inventory_path, allow_missing_leaf=False
        )
        _assert_no_symlink_ancestors(
            root, authorization.outputs.receipt_path, allow_missing_leaf=True
        )
        if _assert_exact_file(claim_path, claim_bytes, field="claim") != claim_sha256:
            raise AcquisitionError("claim SHA-256 changed before receipt publication")
        if (
            _assert_exact_file(inventory_path, inventory_bytes, field="inventory")
            != inventory_sha256
        ):
            raise AcquisitionError("inventory SHA-256 changed before receipt publication")
        if _file_sha256(archive_path) != verification.sha256:
            raise AcquisitionError("archive SHA-256 changed before receipt publication")

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
                "redirect_chain": list(verification.redirect_chain),
                "resolved_url": verification.resolved_url,
                "sha256": verification.sha256,
                "size_bytes": verification.size_bytes,
                "source_url": verification.source_url,
            },
            "archive_layout_status": "bounded_syntactic_tar_header_inventory_completed",
            "authorization": {
                "id": authorization.authorization_id,
                "path": authorization.authorization_path,
                "sha256": authorization.authorization_sha256,
            },
            "candidate": {
                "dataset_id": authorization.candidate.dataset_id,
                "path": authorization.candidate_path,
                "sequence_id": authorization.candidate.sequence_id,
                "sha256": authorization.candidate_sha256,
            },
            "dataset_status": "candidate",
            "disk": {
                "free_bytes_before": before_free,
                "free_bytes_before_receipt": _disk_usage(quarantine).free,
                "minimum_post_transfer_free_bytes": authorization.minimum_post_transfer_free_bytes,
            },
            "execution": {
                "controller_initiated_paid_service_cost_usd": 0,
                "elapsed_seconds": elapsed,
                "git_revision": revision,
                "maximum_elapsed_seconds": authorization.maximum_elapsed_seconds,
                "tool_files": [asdict(tool) for tool in authorization.tool_files],
            },
            "inventory": {
                "expanded_size_bytes": inventory.expanded_size_bytes,
                "file_count": inventory.file_count,
                "limits": asdict(authorization.inventory_limits),
                "maximum_serialized_bytes": authorization.maximum_inventory_bytes,
                "member_count": len(inventory.members),
                "path": authorization.outputs.inventory_path,
                "serialized_bytes": len(inventory_bytes),
                "sha256": inventory_sha256,
            },
            "claim": {
                "path": authorization.outputs.claim_path,
                "sha256": claim_sha256,
            },
            "operations_not_performed": list(_PROHIBITED_OPERATIONS),
            "operations_performed": list(_PERMITTED_OPERATIONS),
            "outcome": "completed",
            "record_type": "dataset_archive_acquisition_receipt",
            "retention": {
                "deletion_authorized": False,
                "policy": "retain_in_quarantine_until_review",
                "review_at": _format_utc(authorization.retention_review_at),
            },
            "schema_version": "1.0.0",
            "receipt_prepared_at": _format_utc(receipt_prepared_at),
            "scientific_authority": "none",
            "scientific_limitations": (
                "No extraction, calibration validation, ground-truth schema validation, "
                "adapter validation, selection, training, inference, evaluation, UAV-domain, "
                "deployment, or superiority claim occurred."
            ),
            "retained_archive_path": authorization.archive_path,
            "started_at": _format_utc(started_at),
        }
        receipt_bytes = _canonical_json_bytes(receipt)
        if len(receipt_bytes) > _MAX_RECEIPT_BYTES:
            raise AcquisitionError("success receipt exceeds its authorized byte bound")
        signal.setitimer(signal.ITIMER_REAL, 0)
        receipt_sha256 = _write_new_atomic(receipt_path, receipt_bytes)
    return AcquisitionResult(
        authorization_id=authorization.authorization_id,
        archive_sha256=verification.sha256,
        inventory_sha256=inventory_sha256,
        receipt_sha256=receipt_sha256,
        receipt_path=receipt_path,
        inventory_path=inventory_path,
        claim_path=claim_path,
    )


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise AcquisitionError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="compact-vio-acquire-archive",
        description="Execute one committed operational-only archive transfer authorization.",
    )
    parser.add_argument("--authorization", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = run_authorized_transfer(args.authorization)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_code": "archive_acquisition_failed",
                    "error_type": type(exc).__name__,
                    "event": "archive_acquisition_failed",
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
                "event": "archive_acquisition_completed",
                "inventory_path": str(result.inventory_path),
                "inventory_sha256": result.inventory_sha256,
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


__all__ = [
    "AcquisitionError",
    "AcquisitionResult",
    "TransferAuthorization",
    "build_parser",
    "load_transfer_authorization",
    "main",
    "run_authorized_transfer",
]

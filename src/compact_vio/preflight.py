"""Read-only durability preflight for research artifact storage.

This module deliberately evaluates only the static prerequisites for a restore
drill.  It never writes to a candidate storage location and never claims that
the project's durability gate has passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

EXIT_STATIC_CHECKS_SATISFIED = 0
EXIT_BLOCKED = 1
EXIT_INVALID = 2


@dataclass(frozen=True)
class StorageObservation:
    """Filesystem facts collected without modifying the inspected path."""

    supplied_path: str
    resolved_path: str | None
    exists: bool
    is_directory: bool
    has_symlink_component: bool
    writable_hint: bool | None
    filesystem_device: int | None
    total_bytes: int | None
    used_bytes: int | None
    free_bytes: int | None
    error: str | None = None


@dataclass(frozen=True)
class FailureDomainRecordObservation:
    """Facts about a caller-supplied record; its contents are not verified."""

    supplied_path: str
    resolved_path: str | None
    exists: bool
    is_regular_file: bool
    has_symlink_component: bool
    non_empty: bool
    error: str | None = None


def _absolute_lexical(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _has_symlink_component(path: Path) -> bool:
    """Return whether any existing component is a symbolic link."""

    try:
        absolute = _absolute_lexical(path)
    except (OSError, RuntimeError):
        return False
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            mode = os.lstat(current).st_mode
        except OSError:
            return False
        if stat.S_ISLNK(mode):
            return True
    return False


def inspect_storage(path_value: str) -> StorageObservation:
    """Inspect an existing storage directory without creating or changing it."""

    supplied = Path(path_value)
    symlinked = _has_symlink_component(supplied)
    try:
        resolved = supplied.expanduser().resolve(strict=True)
        path_stat = resolved.stat()
        is_directory = stat.S_ISDIR(path_stat.st_mode)
        if not is_directory:
            return StorageObservation(
                supplied_path=path_value,
                resolved_path=str(resolved),
                exists=True,
                is_directory=False,
                has_symlink_component=symlinked,
                writable_hint=None,
                filesystem_device=path_stat.st_dev,
                total_bytes=None,
                used_bytes=None,
                free_bytes=None,
            )
        usage = shutil.disk_usage(resolved)
        return StorageObservation(
            supplied_path=path_value,
            resolved_path=str(resolved),
            exists=True,
            is_directory=True,
            has_symlink_component=symlinked,
            writable_hint=os.access(resolved, os.W_OK),
            filesystem_device=path_stat.st_dev,
            total_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
        )
    except FileNotFoundError:
        return StorageObservation(
            supplied_path=path_value,
            resolved_path=None,
            exists=False,
            is_directory=False,
            has_symlink_component=symlinked,
            writable_hint=None,
            filesystem_device=None,
            total_bytes=None,
            used_bytes=None,
            free_bytes=None,
            error="path does not exist",
        )
    except (OSError, RuntimeError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        return StorageObservation(
            supplied_path=path_value,
            resolved_path=None,
            exists=False,
            is_directory=False,
            has_symlink_component=symlinked,
            writable_hint=None,
            filesystem_device=None,
            total_bytes=None,
            used_bytes=None,
            free_bytes=None,
            error=f"filesystem inspection failed: {detail or exc.__class__.__name__}",
        )


def inspect_failure_domain_record(path_value: str) -> FailureDomainRecordObservation:
    """Inspect a caller-supplied failure-domain record without reading its contents."""

    supplied = Path(path_value)
    symlinked = _has_symlink_component(supplied)
    try:
        resolved = supplied.expanduser().resolve(strict=True)
        path_stat = resolved.stat()
        regular = stat.S_ISREG(path_stat.st_mode)
        return FailureDomainRecordObservation(
            supplied_path=path_value,
            resolved_path=str(resolved),
            exists=True,
            is_regular_file=regular,
            has_symlink_component=symlinked,
            non_empty=regular and path_stat.st_size > 0,
        )
    except FileNotFoundError:
        return FailureDomainRecordObservation(
            supplied_path=path_value,
            resolved_path=None,
            exists=False,
            is_regular_file=False,
            has_symlink_component=symlinked,
            non_empty=False,
            error="evidence record does not exist",
        )
    except (OSError, RuntimeError) as exc:
        detail = exc.strerror if isinstance(exc, OSError) else str(exc)
        return FailureDomainRecordObservation(
            supplied_path=path_value,
            resolved_path=None,
            exists=False,
            is_regular_file=False,
            has_symlink_component=symlinked,
            non_empty=False,
            error=f"evidence inspection failed: {detail or exc.__class__.__name__}",
        )


def _nested_or_equal(first: str, second: str) -> bool:
    first_path = Path(first)
    second_path = Path(second)
    return (
        first_path == second_path
        or first_path in second_path.parents
        or second_path in first_path.parents
    )


def assess_durability(
    *,
    vault: StorageObservation | None,
    backup: StorageObservation | None,
    required_bytes: int | None,
    reserve_bytes: int | None,
    failure_domain_record: FailureDomainRecordObservation | None,
    observed_at: str | None = None,
) -> dict[str, object]:
    """Assess whether static prerequisites permit a representative restore drill."""

    if required_bytes is not None and required_bytes <= 0:
        raise ValueError("required_bytes must be greater than zero")
    if reserve_bytes is not None and reserve_bytes < 0:
        raise ValueError("reserve_bytes must be zero or greater")

    blockers: list[dict[str, str]] = []

    if vault is None:
        blockers.append(
            {"code": "vault_not_supplied", "message": "an artifact-vault path is required"}
        )
    if backup is None:
        blockers.append(
            {"code": "backup_not_supplied", "message": "an independent backup path is required"}
        )
    if required_bytes is None:
        blockers.append(
            {"code": "required_capacity_not_supplied", "message": "required bytes are required"}
        )
    if reserve_bytes is None:
        blockers.append(
            {"code": "reserve_not_supplied", "message": "reserved free bytes are required"}
        )

    for label, location in (("vault", vault), ("backup", backup)):
        if location is None:
            continue
        if not location.exists:
            blockers.append(
                {"code": f"{label}_missing", "message": f"the {label} path does not exist"}
            )
        elif not location.is_directory:
            blockers.append(
                {
                    "code": f"{label}_not_directory",
                    "message": f"the {label} path is not a directory",
                }
            )
        if location.has_symlink_component:
            blockers.append(
                {
                    "code": f"{label}_symlinked",
                    "message": f"the {label} path contains a symbolic-link component",
                }
            )
        if location.writable_hint is False:
            blockers.append(
                {
                    "code": f"{label}_not_writable",
                    "message": f"the {label} path is not writable by the current process",
                }
            )

    if required_bytes is not None and reserve_bytes is not None:
        needed = required_bytes + reserve_bytes
        for label, location in (("vault", vault), ("backup", backup)):
            if location is not None and location.free_bytes is not None:
                if location.free_bytes < needed:
                    blockers.append(
                        {
                            "code": f"{label}_capacity_insufficient",
                            "message": f"the {label} has fewer than required_bytes + reserve_bytes",
                        }
                    )

    if vault is not None and backup is not None:
        if vault.resolved_path is not None and backup.resolved_path is not None:
            if _nested_or_equal(vault.resolved_path, backup.resolved_path):
                blockers.append(
                    {
                        "code": "locations_not_separate",
                        "message": "vault and backup paths are equal or nested",
                    }
                )
        if (
            vault.filesystem_device is not None
            and backup.filesystem_device is not None
            and vault.filesystem_device == backup.filesystem_device
        ):
            blockers.append(
                {
                    "code": "same_filesystem_device",
                    "message": "vault and backup report the same filesystem device",
                }
            )

    if failure_domain_record is None:
        blockers.append(
            {
                "code": "failure_domain_record_not_supplied",
                "message": "a caller-supplied failure-domain record is required",
            }
        )
    else:
        if not failure_domain_record.exists:
            blockers.append(
                {
                    "code": "failure_domain_record_missing",
                    "message": "the failure-domain evidence record does not exist",
                }
            )
        elif not failure_domain_record.is_regular_file or not failure_domain_record.non_empty:
            blockers.append(
                {
                    "code": "failure_domain_record_invalid",
                    "message": (
                        "the failure-domain evidence record must be a non-empty regular file"
                    ),
                }
            )
        if failure_domain_record.has_symlink_component:
            blockers.append(
                {
                    "code": "failure_domain_record_symlinked",
                    "message": "the failure-domain evidence path contains a symbolic link",
                }
            )

    ready = not blockers
    return {
        "schema_version": "1.0",
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "scope": "static_filesystem_storage_preflight_only",
        "assessment": "static_checks_satisfied" if ready else "blocked",
        "artifact_restore_gate_passed": False,
        "independent_failure_domains_verified": False,
        "outside_worker_locations_verified": False,
        "restore_verified": False,
        "inputs": {
            "required_bytes": required_bytes,
            "reserve_bytes": reserve_bytes,
        },
        "vault": asdict(vault) if vault is not None else None,
        "backup": asdict(backup) if backup is not None else None,
        "failure_domain_record": (
            asdict(failure_domain_record) if failure_domain_record is not None else None
        ),
        "blockers": blockers,
        "limitations": [
            (
                "filesystem_device is only a client-visible identifier; distinct values do not "
                "prove independent physical, provider, account, region, or administrative "
                "failure domains"
            ),
            (
                "the failure-domain record is checked only for safe path type and non-zero size; "
                "its contents, reviewer, and assertions are not machine-verified"
            ),
            (
                "writable_hint uses an access check and does not prove authenticated transfer, "
                "encryption, retention, recovery-point objective, or successful writes"
            ),
            (
                "the preflight does not prove that either location is outside the GPU worker or "
                "perform a backup, deletion, restore, checksum, or load test"
            ),
            "object stores and non-filesystem providers require a provider-specific preflight",
        ],
        "next_action": (
            "Run and record a representative worker-to-vault-to-backup restore drill; "
            "this preflight alone does not pass the artifact restore gate."
            if ready
            else "Resolve every blocker, then rerun this read-only preflight."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-preflight",
        description=(
            "Inspect filesystem-backed static durability prerequisites without writing to "
            "storage or passing the artifact restore gate."
        ),
    )
    parser.add_argument("--vault", help="existing candidate artifact-vault directory")
    parser.add_argument("--backup", help="existing candidate independent-backup directory")
    parser.add_argument("--required-bytes", type=int, help="estimated retained artifact bytes")
    parser.add_argument(
        "--reserve-bytes",
        type=int,
        help="minimum bytes that must remain free after the estimate",
    )
    parser.add_argument(
        "--failure-domain-record",
        help=(
            "non-empty caller-supplied failure-domain record; presence is checked but contents "
            "and review are not verified"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = assess_durability(
            vault=inspect_storage(args.vault) if args.vault else None,
            backup=inspect_storage(args.backup) if args.backup else None,
            required_bytes=args.required_bytes,
            reserve_bytes=args.reserve_bytes,
            failure_domain_record=(
                inspect_failure_domain_record(args.failure_domain_record)
                if args.failure_domain_record
                else None
            ),
        )
    except ValueError as exc:
        print(
            json.dumps(
                {
                    "assessment": "invalid",
                    "error": str(exc),
                    "artifact_restore_gate_passed": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return EXIT_INVALID

    print(json.dumps(result, indent=2, sort_keys=True))
    if result["assessment"] == "static_checks_satisfied":
        return EXIT_STATIC_CHECKS_SATISFIED
    return EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())

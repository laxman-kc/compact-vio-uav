"""Read-only content audit for two restored artifact-bundle copies.

This module verifies byte identity against a caller-supplied frozen manifest
hash.  It deliberately does not claim that export, deletion, restoration,
loadability, outside-worker placement, or failure-domain independence occurred.
Those facts belong in the separately reviewed artifact-storage evidence record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from compact_vio import __version__
from compact_vio.artifacts import (
    DEFAULT_MANIFEST_PATH,
    ArtifactError,
    ArtifactManifest,
    VerificationReport,
    load_manifest,
    read_manifest_bytes,
    verify_bundle,
)

EXIT_VERIFIED = 0
EXIT_DIFFERENCES = 1
EXIT_INVALID = 2


class CopyAuditError(Exception):
    """Raised when copy-audit inputs are invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class CopyObservation:
    """Content and filesystem observations for one supplied bundle."""

    copy_ref: str
    client_visible_filesystem_identifier: int
    artifact_manifest_sha256: str
    artifact_manifest_matches_expected: bool
    payload_file_count: int
    payload_bytes: int
    artifact_manifest_bytes: int
    bundle_file_count: int
    bundle_bytes: int
    bundle_verification: VerificationReport

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["bundle_verification"] = self.bundle_verification.to_dict()
        return value


def _validate_sha256(value: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CopyAuditError(
            "expected manifest SHA-256 must be 64 lowercase hexadecimal characters"
        )
    return value


def _validate_copy_ref(value: str) -> str:
    valid = isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{2,255}", value)
    if valid is None or valid is False:
        raise CopyAuditError(
            "copy reference must be a credential-free opaque identifier of 3 to 256 "
            "characters using only letters, digits, dot, underscore, colon, or hyphen"
        )
    return value


def _observe_copy(
    supplied_path: os.PathLike[str] | str,
    *,
    copy_ref: str,
    manifest_path: str,
    expected_manifest_sha256: str,
) -> tuple[CopyObservation, ArtifactManifest, Path]:
    supplied = Path(supplied_path)
    try:
        if supplied.is_symlink():
            raise CopyAuditError(f"bundle root must not be a symbolic link: {supplied}")
        resolved = supplied.resolve(strict=True)
        status = resolved.stat()
    except CopyAuditError:
        raise
    except OSError as exc:
        raise CopyAuditError(f"cannot inspect bundle root {supplied}: {exc}") from exc
    if not resolved.is_dir():
        raise CopyAuditError(f"bundle root is not a directory: {resolved}")

    manifest_before = read_manifest_bytes(resolved, manifest_path=manifest_path)
    manifest = load_manifest(resolved, manifest_path=manifest_path)
    verification = verify_bundle(resolved, manifest_path=manifest_path)
    manifest_after = read_manifest_bytes(resolved, manifest_path=manifest_path)
    if manifest_before != manifest_after:
        raise CopyAuditError(f"manifest changed during copy audit: {resolved / manifest_path}")

    digest = hashlib.sha256(manifest_before).hexdigest()
    observation = CopyObservation(
        copy_ref=copy_ref,
        client_visible_filesystem_identifier=status.st_dev,
        artifact_manifest_sha256=digest,
        artifact_manifest_matches_expected=digest == expected_manifest_sha256,
        payload_file_count=len(manifest.files),
        payload_bytes=sum(record.bytes for record in manifest.files),
        artifact_manifest_bytes=len(manifest_before),
        bundle_file_count=len(manifest.files) + 1,
        bundle_bytes=sum(record.bytes for record in manifest.files) + len(manifest_before),
        bundle_verification=verification,
    )
    return observation, manifest, resolved


def _paths_overlap(first: str, second: str) -> bool:
    first_path = Path(first)
    second_path = Path(second)
    return (
        first_path == second_path
        or first_path in second_path.parents
        or second_path in first_path.parents
    )


def audit_copies(
    *,
    expected_manifest_sha256: str,
    primary_bundle: os.PathLike[str] | str,
    backup_bundle: os.PathLike[str] | str,
    primary_ref: str = "primary-copy",
    backup_ref: str = "backup-copy",
    manifest_path: str = DEFAULT_MANIFEST_PATH,
    observed_at: str | None = None,
) -> dict[str, object]:
    """Audit two bundle copies against a frozen raw manifest-file hash."""

    expected = _validate_sha256(expected_manifest_sha256)
    validated_primary_ref = _validate_copy_ref(primary_ref)
    validated_backup_ref = _validate_copy_ref(backup_ref)
    if validated_primary_ref == validated_backup_ref:
        raise CopyAuditError("primary and backup copy references must be distinct")
    primary, primary_manifest, primary_resolved = _observe_copy(
        primary_bundle,
        copy_ref=validated_primary_ref,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected,
    )
    backup, backup_manifest, backup_resolved = _observe_copy(
        backup_bundle,
        copy_ref=validated_backup_ref,
        manifest_path=manifest_path,
        expected_manifest_sha256=expected,
    )

    blockers: list[dict[str, str]] = []
    if _paths_overlap(str(primary_resolved), str(backup_resolved)):
        blockers.append(
            {
                "code": "copy_paths_not_separate",
                "message": "primary and backup bundle paths are equal or nested",
            }
        )
    for role, observation in (("primary", primary), ("backup", backup)):
        if not observation.artifact_manifest_matches_expected:
            blockers.append(
                {
                    "code": f"{role}_manifest_hash_mismatch",
                    "message": f"the {role} manifest does not match the frozen manifest hash",
                }
            )
        if not observation.bundle_verification.ok:
            blockers.append(
                {
                    "code": f"{role}_bundle_mismatch",
                    "message": f"the {role} bundle differs from its manifest",
                }
            )
    if primary_manifest != backup_manifest:
        blockers.append(
            {
                "code": "copy_manifests_differ",
                "message": "primary and backup manifests describe different payloads",
            }
        )

    verified = not blockers
    distinct_devices = (
        primary.client_visible_filesystem_identifier != backup.client_visible_filesystem_identifier
    )
    return {
        "schema_version": "1.0.0",
        "tool": "compact-vio-copy-audit",
        "tool_version": __version__,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_bundle_copy_content_audit",
        "assessment": "copy_content_verified" if verified else "differences_found",
        "content_identity_verified": verified,
        "artifact_restore_gate_passed": False,
        "expected_artifact_manifest_sha256": expected,
        "artifact_manifest_path": manifest_path,
        "primary": primary.to_dict(),
        "backup": backup.to_dict(),
        "client_visible_filesystem_identifiers_distinct": distinct_devices,
        "independent_failure_domains_verified": False,
        "outside_worker_locations_verified": False,
        "source_copy_deletion_verified": False,
        "restore_chronology_verified": False,
        "representative_load_verified": False,
        "blockers": blockers,
        "limitations": [
            (
                "matching content does not prove that either copy is outside the worker or in an "
                "independent physical, provider, account, region, credential, or administrative "
                "failure domain"
            ),
            (
                "client-visible filesystem identifiers are observations only and cannot establish "
                "failure-domain independence"
            ),
            (
                "the audit does not perform or prove export, deletion of the disposable source "
                "copy, restore chronology, representative load/open behavior, retention, or RPO"
            ),
            (
                "the frozen expected manifest hash must come from a separately preserved and "
                "reviewed record; this command does not establish that chain of custody"
            ),
            (
                "filesystem paths are inputs only and are omitted from successful JSON; "
                "copy_ref values are caller-supplied opaque labels, not proof of location"
            ),
        ],
        "next_action": (
            "Attach this content audit to a reviewed artifact-storage evidence record; complete "
            "the independent failure-domain, deletion, restore, and load/open evidence before "
            "considering the artifact restore gate."
            if verified
            else "Resolve every reported difference and rerun the read-only copy audit."
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-copy-audit",
        description=(
            "Read-only audit of two bundle copies against a frozen artifact-manifest SHA-256."
        ),
    )
    parser.add_argument(
        "--expected-manifest-sha256",
        required=True,
        help="raw SHA-256 recorded for the frozen artifact-manifest.json",
    )
    parser.add_argument("--primary", required=True, help="primary restored bundle directory")
    parser.add_argument("--backup", required=True, help="backup restored bundle directory")
    parser.add_argument(
        "--primary-ref",
        required=True,
        help="credential-free opaque identifier for the primary copy",
    )
    parser.add_argument(
        "--backup-ref",
        required=True,
        help="credential-free opaque identifier for the backup copy",
    )
    parser.add_argument(
        "--manifest",
        default=DEFAULT_MANIFEST_PATH,
        help=f"relative manifest path (default: {DEFAULT_MANIFEST_PATH})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        result = audit_copies(
            expected_manifest_sha256=arguments.expected_manifest_sha256,
            primary_bundle=arguments.primary,
            backup_bundle=arguments.backup,
            primary_ref=arguments.primary_ref,
            backup_ref=arguments.backup_ref,
            manifest_path=arguments.manifest,
        )
    except (ArtifactError, CopyAuditError, OSError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "assessment": "invalid",
                    "artifact_restore_gate_passed": False,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return EXIT_INVALID

    print(json.dumps(result, indent=2, sort_keys=True))
    if result["content_identity_verified"]:
        return EXIT_VERIFIED
    return EXIT_DIFFERENCES


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CopyAuditError",
    "CopyObservation",
    "EXIT_DIFFERENCES",
    "EXIT_INVALID",
    "EXIT_VERIFIED",
    "audit_copies",
    "main",
]

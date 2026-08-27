"""Validate project JSON Schemas, templates, and cross-record contracts."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import stat
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - exercised by CI with dependency installed.
    raise SystemExit(
        "jsonschema with format support is required; install jsonschema[format-nongpl]==4.26.0"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
CONFIG_SCHEMA_DIRECTORY = ROOT / "configs/schemas"
CONFIG_TEMPLATE_DIRECTORY = ROOT / "configs/templates"
SCHEMA_DIRECTORIES = (
    CONFIG_SCHEMA_DIRECTORY,
    ROOT / "experiments/schemas",
    ROOT / "governance/schemas",
)
TEMPLATE_DIRECTORY = ROOT / "governance/records/templates"
DEFAULT_RECORDS_ROOT = TEMPLATE_DIRECTORY.parent
ZERO_HASH = "0" * 64
MAX_JSON_BYTES = 64 * 1024 * 1024
RECORD_TYPE_SCHEMA_FILES = {
    "project_release_scope": "project-release-scope.schema.json",
    "rights_matrix": "rights-matrix.schema.json",
    "artifact_storage_plan": "artifact-storage-plan.schema.json",
    "worker_authorization": "worker-authorization.schema.json",
    "artifact_storage_evidence": "artifact-storage-evidence.schema.json",
}
CONFIG_RECORD_TYPE_SCHEMA_FILES = {
    "sensor_calibration_profile": "calibration-profile.schema.json",
    "calibration_profile_assessment": "calibration-assessment.schema.json",
}


class RecordValidationError(Exception):
    """Raised when a governed JSON record is unsafe or semantically invalid."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise RecordValidationError(f"duplicate JSON object key: {key!r}")
        value[key] = item
    return value


def _reject_non_finite_number(value: str) -> None:
    raise RecordValidationError(f"non-finite JSON number is forbidden: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise RecordValidationError(f"non-finite JSON number is forbidden: {value}")
    return parsed


def _read_exact_regular_file(path: Path) -> bytes:
    """Read stable bytes from one regular file without following the final symlink."""

    supplied = Path(path)
    if supplied.is_symlink():
        raise RecordValidationError(f"governed JSON path must not be a symbolic link: {supplied}")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(supplied, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RecordValidationError(f"governed JSON path is not a regular file: {supplied}")
        if before.st_size > MAX_JSON_BYTES:
            raise RecordValidationError(f"governed JSON exceeds {MAX_JSON_BYTES} bytes: {supplied}")
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise RecordValidationError(f"governed JSON changed while reading: {supplied}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RecordValidationError(f"governed JSON changed while reading: {supplied}")
        after = os.fstat(descriptor)
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
            or before.st_dev != after.st_dev
        ):
            raise RecordValidationError(f"governed JSON changed while reading: {supplied}")
        return b"".join(chunks)
    except RecordValidationError:
        raise
    except OSError as exc:
        raise RecordValidationError(f"cannot read governed JSON {supplied}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _decode_json_object(raw: bytes, *, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
            parse_float=_parse_finite_float,
        )
    except UnicodeDecodeError as exc:
        raise RecordValidationError(f"governed JSON is not UTF-8: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RecordValidationError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise RecordValidationError(f"JSON root is not an object: {path}")
    return value


def _load_with_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_exact_regular_file(path)
    return _decode_json_object(raw, path=path), raw


def _load(path: Path) -> dict[str, Any]:
    return _load_with_bytes(path)[0]


def _canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _schema_paths() -> list[Path]:
    paths = sorted(
        path for directory in SCHEMA_DIRECTORIES for path in directory.glob("*.schema.json")
    )
    if not paths:
        raise AssertionError("no JSON Schemas found")
    return paths


def _matching_template(schema_path: Path) -> Path | None:
    suffix = ".schema.json"
    if not schema_path.name.endswith(suffix):
        return None
    stem = schema_path.name.removesuffix(suffix)
    candidates = [
        CONFIG_TEMPLATE_DIRECTORY / f"{stem}.template.json",
        CONFIG_TEMPLATE_DIRECTORY / f"{stem}.draft.json",
        TEMPLATE_DIRECTORY / f"{stem}.template.json",
        TEMPLATE_DIRECTORY / f"{stem}.draft.json",
    ]
    matches = [candidate for candidate in candidates if candidate.is_file()]
    if len(matches) > 1:
        raise AssertionError(f"multiple templates match {schema_path}: {matches}")
    return matches[0] if matches else None


def _load_schema_registry() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for schema_path in _schema_paths():
        if schema_path.name in schemas:
            raise AssertionError(
                f"duplicate schema filename across schema directories: {schema_path.name}"
            )
        schema = _load(schema_path)
        Draft202012Validator.check_schema(schema)
        schemas[schema_path.name] = schema
    expected_schema_files = set(RECORD_TYPE_SCHEMA_FILES.values()) | set(
        CONFIG_RECORD_TYPE_SCHEMA_FILES.values()
    )
    missing = sorted(expected_schema_files - set(schemas))
    if missing:
        raise AssertionError(f"record-type schema mapping names absent schemas: {missing}")
    return schemas


def _json_path(error: Any) -> str:
    parts = [str(part) for part in error.absolute_path]
    return ".".join(parts) if parts else "<root>"


def _schema_errors(
    schema: dict[str, Any],
    value: object,
    *,
    format_checker: FormatChecker,
) -> list[str]:
    errors = Draft202012Validator(schema, format_checker=format_checker).iter_errors(value)
    return [
        f"{_json_path(error)}: {error.message}"
        for error in sorted(
            errors,
            key=lambda item: (tuple(str(part) for part in item.absolute_path), item.message),
        )
    ]


def _require_schema_valid(
    schema: dict[str, Any],
    value: object,
    *,
    label: str,
    format_checker: FormatChecker,
) -> None:
    errors = _schema_errors(schema, value, format_checker=format_checker)
    if errors:
        raise RecordValidationError(f"{label} failed JSON Schema validation: {errors}")


def _is_template_or_draft_path(path: Path) -> bool:
    return (
        "templates" in path.parts
        or path.name.endswith(".template.json")
        or path.name.endswith(".draft.json")
    )


def _record_identifier(record: dict[str, Any]) -> str | None:
    value = record.get("evidence_id")
    if value is None:
        value = record.get("record_id")
    return value if isinstance(value, str) else None


def _canonical_record_path_errors(
    path: Path,
    *,
    records_root: Path,
    record: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    try:
        relative = path.relative_to(records_root)
    except ValueError:
        return [f"governance record is outside the configured records root: {path}"]
    record_type = record.get("record_type")
    identifier = _record_identifier(record)
    if len(relative.parts) != 2:
        errors.append(
            "real governance records must use "
            "governance/records/<record_type>/<record_identifier>.json"
        )
    else:
        if relative.parts[0] != record_type:
            errors.append(
                f"record directory {relative.parts[0]!r} does not match record_type {record_type!r}"
            )
        expected_name = f"{identifier}.json" if identifier is not None else None
        if identifier is None or relative.name != expected_name:
            errors.append(
                f"record filename {relative.name!r} does not exactly match record/evidence "
                f"ID {identifier!r} plus .json"
            )
    return errors


def _planned_run() -> dict[str, Any]:
    return {
        "schema_version": "1.1.0",
        "run_id": "schema-fixture-planned",
        "created_at": "2026-08-26T12:00:00Z",
        "status": "planned",
        "purpose": "Schema validation fixture; not an experimental result.",
        "provenance": {
            "git": {
                "repository": "https://github.com/laxman-kc/compact-vio-uav.git",
                "commit_sha": "0" * 40,
                "dirty": False,
            },
            "environment": {
                "os": "fixture",
                "architecture": "fixture",
                "fingerprint": ZERO_HASH,
            },
            "hardware": {"platform_role": "simulation", "summary": "schema fixture"},
        },
        "experiment": {
            "candidate_family": "diagnostic",
            "candidate_name": "schema-fixture",
            "configuration": {
                "path": "configs/experiments/schema-fixture.json",
                "sha256": ZERO_HASH,
            },
            "seeds": [],
        },
        "data": {"datasets": []},
        "evaluation": {
            "configuration": {
                "path": "configs/experiments/schema-evaluation.json",
                "sha256": ZERO_HASH,
            },
            "metric_scale_claim": False,
            "primary_alignment": "none",
            "causal": True,
        },
        "artifacts": [],
    }


def _critical_artifact() -> dict[str, Any]:
    return {
        "artifact_id": "schema-report",
        "kind": "report",
        "retention_class": "reproducibility_critical",
        "rights_lane": "internal_only",
        "path": "reports/schema-fixture.json",
        "byte_size": 1,
        "sha256": ZERO_HASH,
    }


def _terminal_run() -> dict[str, Any]:
    terminal = copy.deepcopy(_planned_run())
    terminal.update(
        {
            "status": "succeeded",
            "started_at": "2026-08-26T12:00:00Z",
            "finished_at": "2026-08-26T12:30:00Z",
            "outcome": {"summary": "Schema fixture only.", "failure_category": "none"},
            "artifacts": [_critical_artifact()],
        }
    )
    return terminal


def _artifact_manifest_for_run(run_bytes: bytes) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "hash_algorithm": "sha256",
        "files": [
            {"path": "reports/schema-fixture.json", "bytes": 1, "sha256": ZERO_HASH},
            {
                "path": "run-manifest.json",
                "bytes": len(run_bytes),
                "sha256": hashlib.sha256(run_bytes).hexdigest(),
            },
        ],
    }


def _reviewed_rights_matrix() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "record_type": "rights_matrix",
        "record_status": "ready_for_owner_review",
        "authority": "evidence_input_only",
        "accepts_adr": False,
        "record_id": "rights-matrix-fixture",
        "prepared_at": "2026-08-26T11:10:00Z",
        "prepared_by": "schema fixture preparer",
        "scope_cutoff": "2026-08-26T11:00:00Z",
        "inventory_scope_statement": "Schema fixture inventory only; no project rights claim.",
        "inventory_complete_for_scope": True,
        "empty_inventory_rationale": None,
        "assets": [
            {
                "asset_id": "project-source-fixture",
                "asset_type": "project_source",
                "name": "Schema fixture project source",
                "immutable_identity": "fixture-identity",
                "source_ref": "https://example.invalid/source",
                "authoritative_terms_ref": "https://example.invalid/terms",
                "terms_observed_at": "2026-08-26T11:01:00Z",
                "terms_sha256": ZERO_HASH,
                "license_expression": "LicenseRef-Schema-Fixture",
                "intended_lane_ids": ["internal-only"],
                "determinations": {
                    "use": "review_required",
                    "modify": "review_required",
                    "redistribute_source": "review_required",
                    "redistribute_binary": "review_required",
                    "commercial_use": "review_required",
                    "derived_artifacts": "review_required",
                },
                "obligations": ["Schema fixture only; no actual obligation determined."],
                "separation_controls": ["Keep fixture assets internal."],
                "review_status": "reviewed",
                "reviewed_by": "schema fixture reviewer",
                "reviewed_at": "2026-08-26T11:05:00Z",
                "review_evidence_ref": "governance/records/evidence/rights-review.json",
            }
        ],
        "unresolved_items": [],
        "adr_ref": "docs/adr/0001-project-and-release-scope.md",
    }


def _reviewed_project_release_scope(rights_matrix_bytes: bytes) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "record_type": "project_release_scope",
        "record_status": "ready_for_owner_review",
        "authority": "decision_input_only",
        "accepts_adr": False,
        "record_id": "project-scope-fixture",
        "prepared_at": "2026-08-26T11:15:00Z",
        "prepared_by": "schema fixture preparer",
        "decision_owner": "schema fixture owner",
        "scope_cutoff": "2026-08-26T11:00:00Z",
        "purpose_statement": "Schema fixture only; no project purpose selected.",
        "intended_users": ["schema fixture reviewer"],
        "distribution_surfaces": ["private-test-vault"],
        "release_lanes": [
            {
                "lane_id": "internal-only",
                "description": "Schema fixture lane only.",
                "permitted_use_statement": "No actual permission is conferred.",
                "distribution_surfaces": ["private-test-vault"],
                "asset_separation_required": True,
            }
        ],
        "project_source_license": {
            "status": "proposed",
            "candidate_expression": "LicenseRef-Schema-Fixture",
            "terms_ref": "governance/records/evidence/source-terms.json",
            "rationale": "Schema fixture proposal only; it selects no project license.",
        },
        "artifact_release_intent": {
            "source_code": "do_not_release",
            "model_weights": "do_not_release",
            "calibration": "do_not_release",
            "containers": "do_not_release",
            "reports": "do_not_release",
        },
        "dependency_license_policy": {
            "status": "proposed",
            "policy_statement": "Schema fixture policy only.",
            "reciprocal_license_treatment": "Require review in this fixture.",
            "attribution_notice_requirements": "Require review in this fixture.",
            "separation_controls": ["Keep fixture assets separate."],
        },
        "rights_matrix_ref": {
            "record_ref": ("governance/records/rights_matrix/rights-matrix-fixture.json"),
            "record_sha256": hashlib.sha256(rights_matrix_bytes).hexdigest(),
            "record_id": "rights-matrix-fixture",
        },
        "legal_review": {
            "required": "no",
            "status": "not_required",
            "evidence_ref": None,
            "rationale": "Schema fixture exercises the no-review branch only.",
        },
        "open_questions": [],
        "adr_ref": "docs/adr/0001-project-and-release-scope.md",
    }


def _retention_rule(label: str) -> dict[str, str]:
    return {
        "retention_statement": f"Schema fixture retention for {label}; not project policy.",
        "review_at": "2026-08-26T13:00:00Z",
    }


def _storage_location(role: str, candidate_id: str, location_ref: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "role": role,
        "backend_kind": "filesystem",
        "provider_or_operator": "schema fixture operator",
        "location_ref": location_ref,
        "outside_worker_status": "verified",
        "outside_worker_evidence_ref": f"governance/records/evidence/{candidate_id}.json",
        "failure_domain_statement": "Schema fixture statement only.",
        "access_control_statement": "Schema fixture statement only.",
        "encryption_statement": "Schema fixture statement only.",
        "available_bytes": 1_000_000,
        "observed_at": "2026-08-26T12:10:00Z",
        "static_check_ref": f"governance/records/evidence/{candidate_id}-static.json",
    }


def _reviewed_storage_plan() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "record_type": "artifact_storage_plan",
        "record_status": "ready_for_owner_review",
        "authority": "decision_input_only",
        "accepts_adr": False,
        "record_id": "storage-plan-fixture",
        "prepared_at": "2026-08-26T12:20:00Z",
        "prepared_by": "schema fixture preparer",
        "decision_owner": "schema fixture owner",
        "phase_scope": "Schema validation only; no project phase selected.",
        "primary_vault": _storage_location("primary_vault", "primary-candidate", "vault-candidate"),
        "independent_backup": _storage_location(
            "independent_backup", "backup-candidate", "backup-candidate"
        ),
        "independence_review": {
            "status": "reviewed_independent",
            "reviewed_by": "schema fixture reviewer",
            "reviewed_at": "2026-08-26T12:15:00Z",
            "evidence_ref": "governance/records/evidence/independence-fixture.json",
            "limitations": ["Contract fixture only; it proves no external independence."],
        },
        "capacity_envelope": {
            "estimation_method": "schema fixture arithmetic",
            "worst_case_retained_bytes": 10_000,
            "reserve_bytes": 1_000,
            "total_required_bytes": 11_000,
            "valid_until": "2026-08-26T13:00:00Z",
            "reestimate_triggers": ["Any non-fixture scope."],
        },
        "retention_rules": {
            label: _retention_rule(label)
            for label in (
                "reproducibility_critical",
                "resume_only",
                "diagnostic",
                "disposable",
                "release",
            )
        },
        "recovery_point_objective": "Schema fixture statement only.",
        "transfer_plan": {
            "tool": "schema-fixture",
            "version": "1",
            "resumable": True,
            "integrity_method": "SHA-256 fixture",
            "measured_throughput_bytes_per_second": 1_000.0,
            "expected_teardown_transfer_seconds": 60.0,
            "measurement_ref": "governance/records/evidence/throughput-fixture.json",
        },
        "restore_test_cadence": "Schema fixture statement only.",
        "cost_envelope": {
            "currency": "USD",
            "storage_spend_ceiling": 1.0,
            "worker_spend_ceiling": 1.0,
            "period_statement": "Schema fixture period only.",
            "review_at": "2026-08-26T13:00:00Z",
            "rate_observation_ref": "governance/records/evidence/rate-fixture.json",
        },
        "owners": {
            "recovery_owner": "schema fixture owner",
            "teardown_authority": "schema fixture owner",
            "deletion_authority": "schema fixture owner",
        },
        "evidence_refs": {
            "static_check_ref": "governance/records/evidence/static-fixture.json",
            "copy_audit_ref": "governance/records/evidence/copy-audit-fixture.json",
            "storage_evidence_ref": (
                "governance/records/artifact_storage_evidence/storage-fixture-verified.json"
            ),
            "credential_access_audit_ref": (
                "governance/records/evidence/credential-audit-fixture.json"
            ),
        },
        "open_questions": [],
        "adr_ref": "docs/adr/0005-artifact-storage.md",
    }


def _owner_approved_worker_authorization(artifact_manifest_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "record_type": "worker_authorization",
        "record_status": "owner_approved",
        "authority": "bounded_action_authorization",
        "accepts_adr": False,
        "authorizes_work": True,
        "general_destructive_action_authorized": False,
        "record_id": "worker-auth-fixture",
        "prepared_at": "2026-08-26T12:00:00Z",
        "prepared_by": "schema fixture preparer",
        "authorization_kind": "m2_evidence_gathering",
        "purpose_statement": "Schema fixture drill only; no paid work was performed.",
        "run_owner": "schema fixture owner",
        "git_commit": "0" * 40,
        "worker_ref": "paid-worker-fixture",
        "requested_action_ids": [
            "create_disposable_restore_test_source_copy",
            "write_primary_restore_test_copy",
            "write_independent_backup_restore_test_copy",
            "two_copy_content_audit",
            "disposable_source_copy_delete",
            "representative_restore",
            "representative_load_open",
            "static_checks",
        ],
        "action_scopes": [
            {
                "action_id": "create_disposable_restore_test_source_copy",
                "location_accesses": [
                    {"location_ref": "disposable-source-copy", "access": "write"}
                ],
            },
            {
                "action_id": "write_primary_restore_test_copy",
                "location_accesses": [{"location_ref": "vault-candidate", "access": "write"}],
            },
            {
                "action_id": "write_independent_backup_restore_test_copy",
                "location_accesses": [{"location_ref": "backup-candidate", "access": "write"}],
            },
            {
                "action_id": "two_copy_content_audit",
                "location_accesses": [
                    {"location_ref": "vault-candidate", "access": "read"},
                    {"location_ref": "backup-candidate", "access": "read"},
                ],
            },
            {
                "action_id": "disposable_source_copy_delete",
                "location_accesses": [
                    {"location_ref": "disposable-source-copy", "access": "delete"}
                ],
            },
            {
                "action_id": "representative_restore",
                "location_accesses": [
                    {"location_ref": "backup-candidate", "access": "read"},
                    {"location_ref": "new-restore-destination", "access": "write"},
                ],
            },
            {
                "action_id": "representative_load_open",
                "location_accesses": [
                    {"location_ref": "new-restore-destination", "access": "read"}
                ],
            },
            {"action_id": "static_checks", "location_accesses": []},
        ],
        "intended_data": [],
        "named_test_locations": [
            "vault-candidate",
            "backup-candidate",
            "disposable-source-copy",
            "new-restore-destination",
        ],
        "disposable_restore_test_source_copy": {
            "copy_id": "disposable-source-fixture",
            "location_ref": "disposable-source-copy",
            "artifact_manifest_sha256": artifact_manifest_sha256,
            "retention_class": "disposable",
            "purpose_created_for_restore_test": True,
            "deletion_permitted": True,
        },
        "max_executions": 1,
        "expected_duration_minutes": 1,
        "spending_ceiling": {"amount": 1.0, "currency": "USD"},
        "review_at": "2026-08-26T12:35:00Z",
        "expires_at": "2026-08-26T13:00:00Z",
        "teardown_authority": "schema fixture owner",
        "recovery_owner": "schema fixture owner",
        "restore_gate_evidence_ref": None,
        "permissions": {
            "dataset_download": False,
            "training": False,
            "important_experiment": False,
            "disposable_source_copy_delete": True,
            "worker_lifecycle_change": False,
            "primary_vault_copy_delete": False,
            "independent_backup_copy_delete": False,
            "other_retained_copy_delete": False,
        },
        "hard_prohibited_action_ids": [
            "worker_lifecycle_change",
            "primary_vault_copy_delete",
            "independent_backup_copy_delete",
            "other_retained_copy_delete",
        ],
        "owner_approval_required": True,
        "approved_by": "schema fixture owner",
        "approved_at": "2026-08-26T12:05:00Z",
        "approval_statement": "Schema fixture approval only; not project authority.",
        "approval_evidence_ref": ("governance/records/evidence/worker-auth-approval-fixture.json"),
        "adr_ref": "docs/adr/0005-artifact-storage.md",
    }


def _verification(
    artifact_manifest_sha256: str,
    *,
    payload_file_count: int,
    payload_bytes: int,
    artifact_manifest_bytes: int,
    bundle_file_count: int,
    bundle_bytes: int,
    verified_at: str,
) -> dict[str, Any]:
    return {
        "method": "artifact_manifest_sha256_all_files",
        "artifact_manifest_sha256": artifact_manifest_sha256,
        "payload_files_verified": payload_file_count,
        "payload_bytes_verified": payload_bytes,
        "artifact_manifest_bytes_verified": artifact_manifest_bytes,
        "bundle_files_verified": bundle_file_count,
        "bundle_bytes_verified": bundle_bytes,
        "verified_at": verified_at,
        "result": "passed",
    }


def _copy_evidence(
    role: str,
    storage_candidate_id: str,
    location_ref: str,
    *,
    started_at: str,
    finished_at: str,
    verified_at: str,
    artifact_manifest_sha256: str,
    payload_file_count: int,
    payload_bytes: int,
    artifact_manifest_bytes: int,
    bundle_file_count: int,
    bundle_bytes: int,
) -> dict[str, Any]:
    duration = 10.0
    return {
        "role": role,
        "storage_candidate_id": storage_candidate_id,
        "location_ref": location_ref,
        "transfer_started_at": started_at,
        "transfer_finished_at": finished_at,
        "duration_seconds": duration,
        "bytes_transferred": bundle_bytes,
        "throughput_bytes_per_second": bundle_bytes / duration,
        "verification": _verification(
            artifact_manifest_sha256,
            payload_file_count=payload_file_count,
            payload_bytes=payload_bytes,
            artifact_manifest_bytes=artifact_manifest_bytes,
            bundle_file_count=bundle_file_count,
            bundle_bytes=bundle_bytes,
            verified_at=verified_at,
        ),
    }


def _verified_storage_evidence(
    run: dict[str, Any],
    run_bytes: bytes,
    artifact_manifest: dict[str, Any],
    artifact_manifest_bytes: bytes,
    storage_plan: dict[str, Any],
    storage_plan_bytes: bytes,
) -> dict[str, Any]:
    artifact_manifest_sha256 = hashlib.sha256(artifact_manifest_bytes).hexdigest()
    payload_file_count = len(artifact_manifest["files"])
    payload_bytes = sum(record["bytes"] for record in artifact_manifest["files"])
    artifact_manifest_byte_count = len(artifact_manifest_bytes)
    bundle_file_count = payload_file_count + 1
    bundle_bytes = payload_bytes + artifact_manifest_byte_count
    return {
        "schema_version": "1.0.0",
        "record_type": "artifact_storage_evidence",
        "evidence_id": "storage-fixture-verified",
        "status": "verified",
        "created_at": "2026-08-26T12:32:00Z",
        "execution_context": {
            "kind": "non_paid_environment",
            "execution_ref": "schema-validator-fixture",
            "started_at": "2026-08-26T12:30:00Z",
            "finished_at": "2026-08-26T12:30:39Z",
            "cost_evidence": None,
        },
        "bundle_identity": {
            "run_id": run["run_id"],
            "run_manifest_sha256": hashlib.sha256(run_bytes).hexdigest(),
            "artifact_manifest_sha256": artifact_manifest_sha256,
            "representative_for_phase": True,
            "representation_basis": (
                "Fixture exercises the complete schema-validation lifecycle contract."
            ),
            "payload_file_count": payload_file_count,
            "payload_bytes": payload_bytes,
            "artifact_manifest_bytes": artifact_manifest_byte_count,
            "bundle_file_count": bundle_file_count,
            "bundle_bytes": bundle_bytes,
        },
        "copies": [
            _copy_evidence(
                "primary_vault",
                "primary-candidate",
                "vault-candidate",
                started_at="2026-08-26T12:30:00Z",
                finished_at="2026-08-26T12:30:10Z",
                verified_at="2026-08-26T12:30:11Z",
                artifact_manifest_sha256=artifact_manifest_sha256,
                payload_file_count=payload_file_count,
                payload_bytes=payload_bytes,
                artifact_manifest_bytes=artifact_manifest_byte_count,
                bundle_file_count=bundle_file_count,
                bundle_bytes=bundle_bytes,
            ),
            _copy_evidence(
                "independent_backup",
                "backup-candidate",
                "backup-candidate",
                started_at="2026-08-26T12:30:12Z",
                finished_at="2026-08-26T12:30:22Z",
                verified_at="2026-08-26T12:30:23Z",
                artifact_manifest_sha256=artifact_manifest_sha256,
                payload_file_count=payload_file_count,
                payload_bytes=payload_bytes,
                artifact_manifest_bytes=artifact_manifest_byte_count,
                bundle_file_count=bundle_file_count,
                bundle_bytes=bundle_bytes,
            ),
        ],
        "source_test_copy_deletion": {
            "target": "disposable_source_test_copy",
            "source_copy_ref": "disposable-source-copy",
            "worker_termination": False,
            "deleted_at": "2026-08-26T12:30:24Z",
            "absence_verified_at": "2026-08-26T12:30:25Z",
            "method": "fixture absence check",
            "result": "passed",
        },
        "restore": {
            "source_role": "independent_backup",
            "destination_ref": "new-restore-destination",
            "destination_was_new": True,
            "restore_started_at": "2026-08-26T12:30:26Z",
            "restore_finished_at": "2026-08-26T12:30:36Z",
            "duration_seconds": 10.0,
            "bytes_restored": bundle_bytes,
            "throughput_bytes_per_second": bundle_bytes / 10.0,
            "verification": _verification(
                artifact_manifest_sha256,
                payload_file_count=payload_file_count,
                payload_bytes=payload_bytes,
                artifact_manifest_bytes=artifact_manifest_byte_count,
                bundle_file_count=bundle_file_count,
                bundle_bytes=bundle_bytes,
                verified_at="2026-08-26T12:30:37Z",
            ),
        },
        "load_open": {
            "artifact_path": "reports/schema-fixture.json",
            "method": "fixture JSON open",
            "tool": "schema-validator-fixture",
            "tool_version": "1",
            "started_at": "2026-08-26T12:30:38Z",
            "finished_at": "2026-08-26T12:30:39Z",
            "duration_seconds": 1.0,
            "result": "passed",
            "evidence_ref": "reports/evidence/load-open.json",
            "evidence_sha256": ZERO_HASH,
        },
        "storage_review": {
            "review_record_ref": (
                "governance/records/artifact_storage_plan/storage-plan-fixture.json"
            ),
            "review_record_sha256": hashlib.sha256(storage_plan_bytes).hexdigest(),
            "review_record_id": storage_plan["record_id"],
            "assessor": "schema fixture assessor",
            "assessed_at": "2026-08-26T12:30:40Z",
            "primary_outside_worker": True,
            "backup_outside_worker": True,
            "independent_failure_domains": True,
        },
        "worker_authorization": None,
        "assessment": {
            "assessor": "schema fixture assessor",
            "assessed_at": "2026-08-26T12:30:41Z",
            "result": "verified",
            "summary": "Contract fixture only; not project evidence.",
        },
        "supporting_evidence": [
            {
                "kind": "two_copy_content_audit",
                "path": "reports/evidence/two-copy-audit.json",
                "sha256": ZERO_HASH,
            }
        ],
        "blockers": [],
        "limitations": [
            "Schema fixtures establish contract behavior only and do not verify external storage."
        ],
        "artifact_restore_gate_passed": False,
    }


def _copy_audit_fixture(evidence: dict[str, Any]) -> dict[str, Any]:
    """Build a structurally realistic copy-audit fragment for validator tests."""

    identity = evidence["bundle_identity"]
    locations = {
        copy_record["role"]: copy_record["location_ref"] for copy_record in evidence["copies"]
    }

    def observation(copy_ref: str, device: int) -> dict[str, Any]:
        return {
            "copy_ref": copy_ref,
            "client_visible_filesystem_identifier": device,
            "artifact_manifest_sha256": identity["artifact_manifest_sha256"],
            "artifact_manifest_matches_expected": True,
            "payload_file_count": identity["payload_file_count"],
            "payload_bytes": identity["payload_bytes"],
            "artifact_manifest_bytes": identity["artifact_manifest_bytes"],
            "bundle_file_count": identity["bundle_file_count"],
            "bundle_bytes": identity["bundle_bytes"],
            "bundle_verification": {
                "ok": True,
                "missing": [],
                "unexpected": [],
                "size_mismatches": [],
                "hash_mismatches": [],
            },
        }

    return {
        "schema_version": "1.0.0",
        "tool": "compact-vio-copy-audit",
        "tool_version": "schema-fixture",
        "observed_at": "2026-08-26T12:30:23Z",
        "scope": "read_only_bundle_copy_content_audit",
        "assessment": "copy_content_verified",
        "content_identity_verified": True,
        "artifact_restore_gate_passed": False,
        "expected_artifact_manifest_sha256": identity["artifact_manifest_sha256"],
        "artifact_manifest_path": "artifact-manifest.json",
        "primary": observation(locations["primary_vault"], 1),
        "backup": observation(locations["independent_backup"], 2),
        "client_visible_filesystem_identifiers_distinct": True,
        "independent_failure_domains_verified": False,
        "outside_worker_locations_verified": False,
        "source_copy_deletion_verified": False,
        "restore_chronology_verified": False,
        "representative_load_verified": False,
        "blockers": [],
        "limitations": ["Schema fixture only; this is not project evidence."],
        "next_action": "Complete the independently reviewed restore drill.",
    }


def _failed_storage_evidence() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "record_type": "artifact_storage_evidence",
        "evidence_id": "storage-fixture-failed",
        "status": "failed",
        "created_at": "2026-08-26T12:10:00Z",
        "execution_context": None,
        "bundle_identity": {
            "run_id": None,
            "run_manifest_sha256": None,
            "artifact_manifest_sha256": None,
            "representative_for_phase": None,
            "representation_basis": None,
            "payload_file_count": None,
            "payload_bytes": None,
            "artifact_manifest_bytes": None,
            "bundle_file_count": None,
            "bundle_bytes": None,
        },
        "copies": [],
        "source_test_copy_deletion": None,
        "restore": None,
        "load_open": None,
        "storage_review": None,
        "worker_authorization": None,
        "assessment": {
            "assessor": "schema fixture assessor",
            "assessed_at": "2026-08-26T12:09:00Z",
            "result": "failed",
            "summary": "Fixture drill stopped before a durable copy was established.",
        },
        "supporting_evidence": [],
        "blockers": ["No reviewed primary-vault location is recorded."],
        "limitations": ["Fixture only; no external storage operation was attempted."],
        "artifact_restore_gate_passed": False,
    }


def _assert_invalid(validator: Draft202012Validator, value: object, label: str) -> None:
    if not list(validator.iter_errors(value)):
        raise AssertionError(f"schema accepted forbidden fixture: {label}")


def _date_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecordValidationError(f"date-time must include a UTC offset: {value!r}")
    return parsed


def _safe_timedelta(*, label: str, seconds: float = 0, minutes: float = 0) -> timedelta:
    try:
        return timedelta(seconds=seconds, minutes=minutes)
    except OverflowError as exc:
        raise RecordValidationError(f"{label} is outside the supported duration range") from exc


def _safe_datetime_add(moment: datetime, duration: timedelta, *, label: str) -> datetime:
    try:
        return moment + duration
    except OverflowError as exc:
        raise RecordValidationError(f"{label} is outside the supported date-time range") from exc


def _duplicate_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


REQUIRED_CALIBRATION_VALIDITY_CATEGORIES = {
    "sensor_hardware",
    "mount",
    "focus",
    "resolution",
    "exposure_mode",
    "sampling",
    "firmware",
    "driver_timestamp",
    "operating_environment",
}
CALIBRATION_CONFIGURATION_FIELDS = (
    "replay_clock_id",
    "camera_layout_id",
    "operating_mode_id",
    "cameras",
    "imu_streams",
    "spatial_calibrations",
    "temporal_calibrations",
    "gravity",
    "validity_conditions",
)


def calibration_configuration_fingerprint(profile: dict[str, Any]) -> str:
    """Hash the complete declared validity envelope using canonical project JSON."""

    configuration = {field: profile[field] for field in CALIBRATION_CONFIGURATION_FIELDS}
    return hashlib.sha256(_canonical_json_bytes(configuration)).hexdigest()


def _profile_parameter_sets(value: object, *, path: str = "profile") -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    if isinstance(value, dict):
        if {"model_id", "model_definition_ref", "parameters"}.issubset(value):
            found.append((path, value))
        for key, child in value.items():
            found.extend(_profile_parameter_sets(child, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_profile_parameter_sets(child, path=f"{path}[{index}]"))
    return found


def calibration_profile_semantic_errors(profile: dict[str, Any]) -> list[str]:
    """Validate profile relationships without selecting physical conventions."""

    errors: list[str] = []
    cameras = profile["cameras"]
    imus = profile["imu_streams"]
    camera_by_stream = {camera["stream_id"]: camera for camera in cameras}
    imu_by_stream = {imu["stream_id"]: imu for imu in imus}
    stream_ids = [camera["stream_id"] for camera in cameras] + [imu["stream_id"] for imu in imus]
    duplicate_streams = _duplicate_values(stream_ids)
    if duplicate_streams:
        errors.append(f"duplicate calibration stream_id values: {duplicate_streams}")

    condition_ids = [condition["condition_id"] for condition in profile["validity_conditions"]]
    duplicate_conditions = _duplicate_values(condition_ids)
    if duplicate_conditions:
        errors.append(f"duplicate validity condition IDs: {duplicate_conditions}")
    condition_id_set = set(condition_ids)
    categories = {condition["category"] for condition in profile["validity_conditions"]}
    missing_categories = sorted(REQUIRED_CALIBRATION_VALIDITY_CATEGORIES - categories)
    if missing_categories:
        errors.append(f"missing required validity categories: {missing_categories}")

    valid_condition_targets = set(stream_ids)
    valid_condition_targets.update(camera["sensor_id"] for camera in cameras)
    valid_condition_targets.update(imu["sensor_id"] for imu in imus)
    valid_condition_targets.update(
        {
            profile["record_id"],
            profile["sensor_profile_id"],
            profile["calibration_id"],
            profile["revision_id"],
            profile["camera_layout_id"],
            profile["operating_mode_id"],
        }
    )
    for condition in profile["validity_conditions"]:
        unknown_targets = sorted(set(condition["applies_to_ids"]) - valid_condition_targets)
        if unknown_targets:
            errors.append(
                f"validity condition {condition['condition_id']} has unknown applies_to_ids: "
                f"{unknown_targets}"
            )
    for sensor in [*cameras, *imus]:
        unresolved = sorted(set(sensor["validity_condition_ids"]) - condition_id_set)
        if unresolved:
            errors.append(
                f"stream {sensor['stream_id']} has unresolved validity conditions: {unresolved}"
            )

    spatial_ids = [item["spatial_calibration_id"] for item in profile["spatial_calibrations"]]
    duplicate_spatial_ids = _duplicate_values(spatial_ids)
    if duplicate_spatial_ids:
        errors.append(f"duplicate spatial calibration IDs: {duplicate_spatial_ids}")
    spatial_pairs: list[str] = []
    covered_cameras: set[str] = set()
    for spatial in profile["spatial_calibrations"]:
        camera = camera_by_stream.get(spatial["camera_stream_id"])
        imu = imu_by_stream.get(spatial["imu_stream_id"])
        if camera is None:
            errors.append(
                f"spatial calibration {spatial['spatial_calibration_id']} references an "
                "unknown camera stream"
            )
        if imu is None:
            errors.append(
                f"spatial calibration {spatial['spatial_calibration_id']} references an "
                "unknown IMU stream"
            )
        if camera is not None and imu is not None:
            endpoints = {spatial["from_frame_id"], spatial["to_frame_id"]}
            expected_endpoints = {camera["frame_id"], imu["frame_id"]}
            if endpoints != expected_endpoints:
                errors.append(
                    f"spatial calibration {spatial['spatial_calibration_id']} endpoints do "
                    "not match its camera and IMU frames"
                )
        if camera is not None and imu is not None:
            covered_cameras.add(camera["stream_id"])
            spatial_pairs.append(f"{camera['stream_id']}->{imu['stream_id']}")
        if len(spatial["rotation"]["component_order"]) != len(spatial["rotation"]["values"]):
            errors.append(
                f"spatial calibration {spatial['spatial_calibration_id']} rotation component "
                "order and values differ in length"
            )
    duplicate_spatial_pairs = _duplicate_values(spatial_pairs)
    if duplicate_spatial_pairs:
        errors.append(f"duplicate camera-to-IMU spatial calibrations: {duplicate_spatial_pairs}")
    missing_spatial = sorted(set(camera_by_stream) - covered_cameras)
    if missing_spatial:
        errors.append(f"camera streams lack direct camera-to-IMU calibration: {missing_spatial}")

    temporal_ids = [item["temporal_calibration_id"] for item in profile["temporal_calibrations"]]
    duplicate_temporal_ids = _duplicate_values(temporal_ids)
    if duplicate_temporal_ids:
        errors.append(f"duplicate temporal calibration IDs: {duplicate_temporal_ids}")
    temporal_streams = [item["stream_id"] for item in profile["temporal_calibrations"]]
    duplicate_temporal_streams = _duplicate_values(temporal_streams)
    if duplicate_temporal_streams:
        errors.append(
            f"streams have multiple direct temporal calibrations: {duplicate_temporal_streams}"
        )
    sensor_by_stream = {**camera_by_stream, **imu_by_stream}
    for temporal in profile["temporal_calibrations"]:
        sensor = sensor_by_stream.get(temporal["stream_id"])
        if sensor is None:
            errors.append(
                f"temporal calibration {temporal['temporal_calibration_id']} references an "
                "unknown stream"
            )
            continue
        if temporal["source_clock_id"] != sensor["source_clock_id"]:
            errors.append(
                f"temporal calibration {temporal['temporal_calibration_id']} source clock "
                "does not match its stream"
            )
        if temporal["target_replay_clock_id"] != profile["replay_clock_id"]:
            errors.append(
                f"temporal calibration {temporal['temporal_calibration_id']} does not target "
                "the declared replay clock"
            )
    expected_temporal_streams = set(sensor_by_stream)
    actual_temporal_streams = set(temporal_streams)
    missing_temporal = sorted(expected_temporal_streams - actual_temporal_streams)
    unexpected_temporal = sorted(actual_temporal_streams - expected_temporal_streams)
    if missing_temporal:
        errors.append(f"streams lack direct temporal calibration: {missing_temporal}")
    if unexpected_temporal:
        errors.append(f"unexpected temporal calibration streams: {unexpected_temporal}")

    imu_roles_by_sensor: dict[str, set[str]] = {}
    for imu in imus:
        roles = imu_roles_by_sensor.setdefault(imu["sensor_id"], set())
        if imu["gyroscope"] is not None:
            roles.add("gyroscope")
        if imu["accelerometer"] is not None:
            roles.add("accelerometer")
    for sensor_id, roles in imu_roles_by_sensor.items():
        missing_roles = sorted({"gyroscope", "accelerometer"} - roles)
        if missing_roles:
            errors.append(
                f"IMU sensor {sensor_id} lacks required characterizations: {missing_roles}"
            )

    for parameter_path, parameter_set in _profile_parameter_sets(profile):
        parameter_ids = [item["parameter_id"] for item in parameter_set["parameters"]]
        duplicates = _duplicate_values(parameter_ids)
        if duplicates:
            errors.append(f"{parameter_path} has duplicate parameter IDs: {duplicates}")
    for camera in cameras:
        if not camera["intrinsics"]["parameters"]:
            errors.append(f"camera stream {camera['stream_id']} has no intrinsic parameters")

    expected_fingerprint = calibration_configuration_fingerprint(profile)
    if profile["configuration_fingerprint_sha256"] != expected_fingerprint:
        errors.append("configuration fingerprint does not match validity conditions")
    supersedes = profile["supersedes"]
    if (
        supersedes is not None
        and supersedes["record_id"] == profile["record_id"]
        and supersedes["revision_id"] == profile["revision_id"]
    ):
        errors.append("profile cannot supersede itself")
    return errors


def calibration_assessment_semantic_errors(
    assessment: dict[str, Any],
    *,
    profile: dict[str, Any],
    profile_bytes: bytes,
) -> list[str]:
    """Validate one assessment against the exact immutable profile bytes."""

    errors: list[str] = []
    link = assessment["profile_link"]
    linked_fields = {
        "record_id": "record_id",
        "sensor_profile_id": "sensor_profile_id",
        "calibration_id": "calibration_id",
        "revision_id": "revision_id",
        "configuration_fingerprint_sha256": "configuration_fingerprint_sha256",
    }
    for link_field, profile_field in linked_fields.items():
        if link[link_field] != profile[profile_field]:
            errors.append(f"assessment profile link {link_field} does not match profile")
    if link["sha256"] != hashlib.sha256(profile_bytes).hexdigest():
        errors.append("assessment profile SHA-256 does not match raw profile bytes")
    if _date_time(assessment["assessed_at"]) < _date_time(profile["created_at"]):
        errors.append("calibration assessment predates profile creation")
    prior = assessment["prior_assessment"]
    if prior is not None and prior["assessment_id"] == assessment["assessment_id"]:
        errors.append("calibration assessment cannot reference itself as prior assessment")

    scope = assessment["threshold_scope"]
    scope_fields = {
        "profile_record_id": "record_id",
        "sensor_profile_id": "sensor_profile_id",
        "calibration_id": "calibration_id",
        "revision_id": "revision_id",
    }
    for scope_field, profile_field in scope_fields.items():
        if scope[scope_field] != profile[profile_field]:
            errors.append(f"threshold scope {scope_field} does not match profile")
    if scope["camera_layout_id"] != profile["camera_layout_id"]:
        errors.append("threshold scope camera_layout_id does not match profile")
    if scope["operating_mode_id"] != profile["operating_mode_id"]:
        errors.append("threshold scope operating_mode_id does not match profile")
    if scope["calibration_target_id"] != profile["calibration_procedure"]["calibration_target_id"]:
        errors.append("threshold scope calibration_target_id does not match profile")
    expected_camera_streams = {camera["stream_id"] for camera in profile["cameras"]}
    expected_imu_streams = {imu["stream_id"] for imu in profile["imu_streams"]}
    expected_conditions = {
        condition["condition_id"] for condition in profile["validity_conditions"]
    }
    if set(scope["camera_stream_ids"]) != expected_camera_streams:
        errors.append("threshold scope camera streams do not exactly match profile")
    if set(scope["imu_stream_ids"]) != expected_imu_streams:
        errors.append("threshold scope IMU streams do not exactly match profile")
    if set(scope["validity_condition_ids"]) != expected_conditions:
        errors.append("threshold scope validity conditions do not exactly match profile")

    criterion_ids = [criterion["criterion_id"] for criterion in assessment["criteria"]]
    duplicates = _duplicate_values(criterion_ids)
    if duplicates:
        errors.append(f"duplicate calibration criterion IDs: {duplicates}")
    valid_scope_ids = expected_camera_streams | expected_imu_streams | expected_conditions
    for criterion in assessment["criteria"]:
        unknown = sorted(set(criterion["applies_to_ids"]) - valid_scope_ids)
        if unknown:
            errors.append(
                f"criterion {criterion['criterion_id']} has unknown applies_to_ids: {unknown}"
            )
        threshold = criterion["threshold"]
        observed = criterion["observed_value"]
        if (
            threshold["unit_id"] != observed["unit_id"]
            or threshold["unit_definition_ref"] != observed["unit_definition_ref"]
        ):
            errors.append(f"criterion {criterion['criterion_id']} compares incompatible units")
            continue
        left = observed["value"]
        right = threshold["value"]
        operator = criterion["comparison_operator"]
        computed_pass = {
            "less_than": left < right,
            "less_than_or_equal": left <= right,
            "equal": left == right,
            "greater_than_or_equal": left >= right,
            "greater_than": left > right,
        }[operator]
        if criterion["passed"] is not computed_pass:
            errors.append(
                f"criterion {criterion['criterion_id']} passed flag does not match its "
                "declared comparison"
            )

    invalidation = assessment["invalidation"]
    if invalidation is not None:
        unknown_triggers = sorted(set(invalidation["trigger_condition_ids"]) - expected_conditions)
        if unknown_triggers:
            errors.append(f"invalidation has unknown trigger conditions: {unknown_triggers}")
    if assessment["decision"] == "approved":
        if any(not criterion["passed"] for criterion in assessment["criteria"]):
            errors.append("approved assessment contains a failed criterion")
        if any(not check["passed"] for check in assessment["required_checks"].values()):
            errors.append("approved assessment contains a failed required check")
        if any(value is None for value in profile["diagnostics"].values()):
            errors.append("approved assessment references a profile with unavailable diagnostics")
    return errors


def _assert_calibration_contracts(
    schemas: dict[str, dict[str, Any]],
    *,
    format_checker: FormatChecker,
) -> None:
    profile_path = CONFIG_TEMPLATE_DIRECTORY / "calibration-profile.template.json"
    assessment_path = CONFIG_TEMPLATE_DIRECTORY / "calibration-assessment.template.json"
    profile, profile_bytes = _load_with_bytes(profile_path)
    assessment = _load(assessment_path)
    profile_validator = Draft202012Validator(
        schemas["calibration-profile.schema.json"], format_checker=format_checker
    )
    assessment_validator = Draft202012Validator(
        schemas["calibration-assessment.schema.json"], format_checker=format_checker
    )
    profile_validator.validate(profile)
    assessment_validator.validate(assessment)
    profile_errors = calibration_profile_semantic_errors(profile)
    if profile_errors:
        raise AssertionError(f"valid calibration-profile fixture failed: {profile_errors}")
    assessment_errors = calibration_assessment_semantic_errors(
        assessment,
        profile=profile,
        profile_bytes=profile_bytes,
    )
    if assessment_errors:
        raise AssertionError(
            f"valid rejected calibration-assessment fixture failed: {assessment_errors}"
        )

    missing_intrinsics = copy.deepcopy(profile)
    del missing_intrinsics["cameras"][0]["intrinsics"]
    _assert_invalid(profile_validator, missing_intrinsics, "camera intrinsics omitted")

    missing_noise = copy.deepcopy(profile)
    del missing_noise["imu_streams"][0]["gyroscope"]["noise_density"]
    _assert_invalid(profile_validator, missing_noise, "IMU noise density omitted")

    empty_noise = copy.deepcopy(profile)
    empty_noise["imu_streams"][0]["gyroscope"]["noise_density"]["parameters"] = []
    _assert_invalid(profile_validator, empty_noise, "empty IMU noise characterization")

    missing_offset_sign = copy.deepcopy(profile)
    del missing_offset_sign["temporal_calibrations"][0]["positive_offset_definition_id"]
    _assert_invalid(profile_validator, missing_offset_sign, "temporal offset sign omitted")

    bad_vector = copy.deepcopy(profile)
    bad_vector["gravity"]["values"] = [1, 2]
    _assert_invalid(profile_validator, bad_vector, "gravity vector cardinality")

    zero_width = copy.deepcopy(profile)
    zero_width["cameras"][0]["width_px"] = 0
    _assert_invalid(profile_validator, zero_width, "nonpositive camera width")

    unknown_property = copy.deepcopy(profile)
    unknown_property["cameras"][0]["invented_default"] = True
    _assert_invalid(profile_validator, unknown_property, "unknown camera property")

    duplicate_stream = copy.deepcopy(profile)
    duplicate_stream["imu_streams"][0]["stream_id"] = duplicate_stream["cameras"][0]["stream_id"]
    _assert_error_contains(
        calibration_profile_semantic_errors(duplicate_stream),
        "duplicate calibration stream_id",
        label="duplicate calibration stream",
    )

    unresolved_condition = copy.deepcopy(profile)
    unresolved_condition["cameras"][0]["validity_condition_ids"][0] = "unknown-condition"
    _assert_error_contains(
        calibration_profile_semantic_errors(unresolved_condition),
        "unresolved validity conditions",
        label="unresolved calibration validity condition",
    )

    wrong_transform_frame = copy.deepcopy(profile)
    wrong_transform_frame["spatial_calibrations"][0]["from_frame_id"] = "wrong-frame"
    _assert_error_contains(
        calibration_profile_semantic_errors(wrong_transform_frame),
        "endpoints do not match its camera and IMU frames",
        label="wrong spatial transform endpoint",
    )

    reversed_transform = copy.deepcopy(profile)
    spatial = reversed_transform["spatial_calibrations"][0]
    spatial["from_frame_id"], spatial["to_frame_id"] = (
        spatial["to_frame_id"],
        spatial["from_frame_id"],
    )
    reversed_transform["configuration_fingerprint_sha256"] = calibration_configuration_fingerprint(
        reversed_transform
    )
    if calibration_profile_semantic_errors(reversed_transform):
        raise AssertionError("explicit reverse spatial-transform direction was rejected")

    wrong_temporal_clock = copy.deepcopy(profile)
    wrong_temporal_clock["temporal_calibrations"][0]["source_clock_id"] = "wrong-clock"
    _assert_error_contains(
        calibration_profile_semantic_errors(wrong_temporal_clock),
        "source clock does not match its stream",
        label="wrong temporal source clock",
    )

    missing_temporal = copy.deepcopy(profile)
    missing_temporal["temporal_calibrations"].pop()
    _assert_error_contains(
        calibration_profile_semantic_errors(missing_temporal),
        "streams lack direct temporal calibration",
        label="missing stream temporal coverage",
    )

    shared_clock_without_mapping = copy.deepcopy(profile)
    for sensor in [
        *shared_clock_without_mapping["cameras"],
        *shared_clock_without_mapping["imu_streams"],
    ]:
        sensor["source_clock_id"] = shared_clock_without_mapping["replay_clock_id"]
    shared_clock_without_mapping["temporal_calibrations"] = []
    _assert_error_contains(
        calibration_profile_semantic_errors(shared_clock_without_mapping),
        "streams lack direct temporal calibration",
        label="shared clock without explicit offset/sign mapping",
    )

    missing_category = copy.deepcopy(profile)
    missing_category["validity_conditions"] = [
        condition
        for condition in missing_category["validity_conditions"]
        if condition["category"] != "operating_environment"
    ]
    _assert_error_contains(
        calibration_profile_semantic_errors(missing_category),
        "missing required validity categories",
        label="missing calibration validity category",
    )

    duplicate_parameter = copy.deepcopy(profile)
    parameter = duplicate_parameter["cameras"][0]["intrinsics"]["parameters"][0]
    duplicate_parameter["cameras"][0]["intrinsics"]["parameters"].append(copy.deepcopy(parameter))
    _assert_error_contains(
        calibration_profile_semantic_errors(duplicate_parameter),
        "duplicate parameter IDs",
        label="duplicate calibration parameter ID",
    )

    bad_fingerprint = copy.deepcopy(profile)
    bad_fingerprint["configuration_fingerprint_sha256"] = ZERO_HASH
    _assert_error_contains(
        calibration_profile_semantic_errors(bad_fingerprint),
        "configuration fingerprint does not match",
        label="invalid calibration validity fingerprint",
    )

    bad_profile_hash = copy.deepcopy(assessment)
    bad_profile_hash["profile_link"]["sha256"] = ZERO_HASH
    _assert_error_contains(
        calibration_assessment_semantic_errors(
            bad_profile_hash,
            profile=profile,
            profile_bytes=profile_bytes,
        ),
        "SHA-256 does not match",
        label="assessment with wrong profile hash",
    )

    incomplete_scope = copy.deepcopy(assessment)
    incomplete_scope["threshold_scope"]["validity_condition_ids"].pop()
    _assert_error_contains(
        calibration_assessment_semantic_errors(
            incomplete_scope,
            profile=profile,
            profile_bytes=profile_bytes,
        ),
        "validity conditions do not exactly match",
        label="assessment with incomplete threshold scope",
    )

    false_approval = copy.deepcopy(assessment)
    false_approval["decision"] = "approved"
    false_approval["approved_for_replay"] = True
    _assert_invalid(
        assessment_validator,
        false_approval,
        "approved assessment containing failed checks",
    )

    dishonest_criterion = copy.deepcopy(assessment)
    dishonest_criterion["decision"] = "approved"
    dishonest_criterion["approved_for_replay"] = True
    dishonest_criterion["criteria"][0]["passed"] = True
    for check in dishonest_criterion["required_checks"].values():
        check["passed"] = True
    assessment_validator.validate(dishonest_criterion)
    _assert_error_contains(
        calibration_assessment_semantic_errors(
            dishonest_criterion,
            profile=profile,
            profile_bytes=profile_bytes,
        ),
        "passed flag does not match its declared comparison",
        label="approved assessment with dishonest criterion result",
    )

    alternate_conventions = copy.deepcopy(profile)
    alternate_conventions["cameras"][0]["axis_convention_id"] = "other-synthetic-axes"
    alternate_conventions["cameras"][0]["intrinsics"]["model_id"] = (
        "other-synthetic-intrinsics-model"
    )
    alternate_conventions["cameras"][0]["nominal_rate"]["unit_id"] = "other-synthetic-rate-unit"
    alternate_conventions["configuration_fingerprint_sha256"] = (
        calibration_configuration_fingerprint(alternate_conventions)
    )
    if calibration_profile_semantic_errors(alternate_conventions):
        raise AssertionError("arbitrary calibration conventions were treated as defaults")


def run_manifest_semantic_errors(run: dict[str, Any]) -> list[str]:
    """Return chronology and referential-integrity errors for one schema-valid run."""

    errors: list[str] = []
    created = _date_time(run["created_at"])
    started_value = run.get("started_at")
    finished_value = run.get("finished_at")
    started = _date_time(started_value) if isinstance(started_value, str) else None
    finished = _date_time(finished_value) if isinstance(finished_value, str) else None
    if started is not None and started < created:
        errors.append("run start predates run creation")
    if started is not None and finished is not None and finished < started:
        errors.append("run finish predates run start")

    artifacts = run["artifacts"]
    artifact_ids = [artifact["artifact_id"] for artifact in artifacts]
    artifact_paths = [artifact["path"] for artifact in artifacts]
    duplicate_ids = _duplicate_values(artifact_ids)
    if duplicate_ids:
        errors.append(f"duplicate run artifact_id values: {duplicate_ids}")
    duplicate_paths = _duplicate_values(artifact_paths)
    if duplicate_paths:
        errors.append(f"duplicate run artifact paths: {duplicate_paths}")

    artifacts_by_id = {artifact["artifact_id"]: artifact for artifact in artifacts}
    evaluation = run["evaluation"]
    for field in (
        "metrics_artifact_id",
        "coverage_artifact_id",
        "runtime_profile_artifact_id",
    ):
        reference = evaluation.get(field)
        if isinstance(reference, str) and reference not in artifacts_by_id:
            errors.append(f"evaluation.{field} references an absent artifact_id: {reference}")
    expected_kinds = {
        "metrics_artifact_id": "metrics",
        "runtime_profile_artifact_id": "profile",
    }
    for field, expected_kind in expected_kinds.items():
        reference = evaluation.get(field)
        artifact = artifacts_by_id.get(reference) if isinstance(reference, str) else None
        if artifact is not None and artifact["kind"] != expected_kind:
            errors.append(
                f"evaluation.{field} must reference kind {expected_kind}, got {artifact['kind']}"
            )
    return errors


def artifact_manifest_semantic_errors(artifact_manifest: dict[str, Any]) -> list[str]:
    """Return identity errors not expressible by the artifact JSON Schema."""

    paths = [record["path"] for record in artifact_manifest["files"]]
    errors: list[str] = []
    duplicates = _duplicate_values(paths)
    if duplicates:
        errors.append(f"duplicate artifact-manifest paths: {duplicates}")
    if "artifact-manifest.json" in paths:
        errors.append("artifact-manifest.json must be self-excluded from its file inventory")
    if paths != sorted(paths):
        errors.append("artifact-manifest file records are not sorted by path")
    return errors


def _reference_target(reference_root: Path, value: str) -> Path:
    if "\x00" in value or "\\" in value:
        raise RecordValidationError(f"reference is not a canonical POSIX path: {value!r}")
    pure = PurePosixPath(value)
    if (
        value != pure.as_posix()
        or pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise RecordValidationError(f"reference is not a canonical relative path: {value!r}")
    supplied_root = Path(reference_root)
    if supplied_root.is_symlink():
        raise RecordValidationError(
            f"configured reference root must not be a symbolic link: {supplied_root}"
        )
    root = supplied_root.resolve(strict=True)
    target = root.joinpath(*pure.parts)
    current = root
    for part in pure.parts:
        current = current / part
        try:
            status = os.lstat(current)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise RecordValidationError(
                f"cannot inspect reference path component {current}: {exc}"
            ) from exc
        if stat.S_ISLNK(status.st_mode):
            raise RecordValidationError(
                f"reference path must not contain a symbolic link: {current}"
            )
    resolved_target = target.resolve(strict=False)
    if not resolved_target.is_relative_to(root):
        raise RecordValidationError(f"reference escapes its configured root: {value!r}")
    return target


def _reference_matches_path(reference_root: Path, value: str, path: Path) -> bool:
    return _reference_target(reference_root, value) == path.resolve(strict=True)


def _assert_canonical_reference_contract() -> None:
    expected = ROOT / "governance/records/rights_matrix/example.json"
    actual = _reference_target(
        ROOT,
        "governance/records/rights_matrix/example.json",
    )
    if actual != expected:
        raise AssertionError("canonical reference fixture resolved to the wrong target")
    for value in (
        "./governance/records/rights_matrix/example.json",
        "governance//records/rights_matrix/example.json",
        "governance/./records/rights_matrix/example.json",
        "governance/records/rights_matrix/example.json/",
        "governance\\records\\rights_matrix\\example.json",
        "governance/records/rights_matrix/example.json\x00ignored",
    ):
        try:
            _reference_target(ROOT, value)
        except RecordValidationError:
            continue
        raise AssertionError(f"non-canonical reference fixture was accepted: {value!r}")

    with tempfile.TemporaryDirectory(prefix="compact-vio-reference-") as temporary:
        reference_root = Path(temporary)
        real = reference_root / "real.json"
        real.write_bytes(b"{}\n")
        alias = reference_root / "alias.json"
        alias.symlink_to(real)
        try:
            _reference_target(reference_root, "alias.json")
        except RecordValidationError as exc:
            if "symbolic link" not in str(exc):
                raise AssertionError(
                    f"symlink reference failed for the wrong reason: {exc}"
                ) from exc
        else:
            raise AssertionError("reference resolver accepted a symbolic-link target")


def artifact_storage_plan_semantic_errors(plan: dict[str, Any]) -> list[str]:
    """Return cross-field errors for a schema-valid storage-plan record."""

    if plan.get("record_status") != "ready_for_owner_review":
        return []
    errors: list[str] = []
    primary = plan["primary_vault"]
    backup = plan["independent_backup"]
    if primary["candidate_id"] == backup["candidate_id"]:
        errors.append("primary and backup candidate_id values must be distinct")
    if primary["location_ref"] == backup["location_ref"]:
        errors.append("primary and backup location_ref values must be distinct")

    capacity = plan["capacity_envelope"]
    expected_total = capacity["worst_case_retained_bytes"] + capacity["reserve_bytes"]
    if capacity["total_required_bytes"] != expected_total:
        errors.append(
            "capacity total_required_bytes must equal worst_case_retained_bytes plus reserve_bytes"
        )
    for label, location in (("primary", primary), ("backup", backup)):
        if location["available_bytes"] < capacity["total_required_bytes"]:
            errors.append(f"{label} available_bytes is below total_required_bytes")

    prepared = _date_time(plan["prepared_at"])
    storage_observations: list[datetime] = []
    for label, location in (("primary", primary), ("backup", backup)):
        observed = _date_time(location["observed_at"])
        storage_observations.append(observed)
        if observed > prepared:
            errors.append(f"{label} storage observation follows plan preparation")
    independence_reviewed = _date_time(plan["independence_review"]["reviewed_at"])
    if independence_reviewed > prepared:
        errors.append("independence review follows plan preparation")
    if storage_observations and independence_reviewed < max(storage_observations):
        errors.append("independence review predates a storage-candidate observation")
    valid_until = _date_time(capacity["valid_until"])
    if valid_until <= prepared:
        errors.append("capacity validity must end after plan preparation")
    for retention_class, rule in plan["retention_rules"].items():
        if _date_time(rule["review_at"]) <= prepared:
            errors.append(f"{retention_class} retention review must follow plan preparation")
    cost_review = _date_time(plan["cost_envelope"]["review_at"])
    if cost_review <= prepared:
        errors.append("cost review must follow plan preparation")
    teardown_duration = _safe_timedelta(
        label="expected teardown transfer duration",
        seconds=plan["transfer_plan"]["expected_teardown_transfer_seconds"],
    )
    teardown_finish = _safe_datetime_add(
        prepared,
        teardown_duration,
        label="expected teardown transfer finish",
    )
    if teardown_finish > cost_review:
        errors.append("teardown transfer allowance extends beyond the cost review time")
    minimum_transfer_seconds = (
        capacity["total_required_bytes"]
        / plan["transfer_plan"]["measured_throughput_bytes_per_second"]
    )
    if plan["transfer_plan"]["expected_teardown_transfer_seconds"] < minimum_transfer_seconds:
        errors.append("teardown transfer allowance is below bytes divided by measured throughput")
    return errors


def _worker_action_access_mode_errors(record: dict[str, Any]) -> list[str]:
    """Reject action/access combinations that could widen destructive scope."""

    errors: list[str] = []
    single_mode_actions = {
        "create_disposable_restore_test_source_copy": "write",
        "write_primary_restore_test_copy": "write",
        "write_independent_backup_restore_test_copy": "write",
        "two_copy_content_audit": "read",
        "disposable_source_copy_delete": "delete",
        "representative_load_open": "read",
    }
    for scope in record.get("action_scopes", []):
        action_id = scope["action_id"]
        accesses = scope["location_accesses"]
        locations = [access["location_ref"] for access in accesses]
        duplicate_locations = _duplicate_values(locations)
        if duplicate_locations:
            errors.append(
                f"action scope {action_id!r} repeats location references: {duplicate_locations}"
            )

        modes = [access["access"] for access in accesses]
        if "delete" in modes and action_id != "disposable_source_copy_delete":
            errors.append(
                f"delete access is forbidden for action {action_id!r}; only the exact "
                "disposable source-copy deletion action may use it"
            )
        expected_mode = single_mode_actions.get(action_id)
        if expected_mode is not None and any(mode != expected_mode for mode in modes):
            errors.append(f"action scope {action_id!r} permits only {expected_mode} access")
        if action_id == "representative_restore":
            if len(accesses) != 2 or sorted(modes) != ["read", "write"]:
                errors.append(
                    "representative_restore requires exactly one read source and one write "
                    "destination"
                )
    return errors


def worker_authorization_semantic_errors(
    record: dict[str, Any],
    *,
    at_time: datetime | None = None,
    require_active: bool = False,
) -> list[str]:
    """Validate durable chronology and, optionally, active-use authority."""

    status = record.get("record_status")
    if status not in {"ready_for_owner_review", "owner_approved"}:
        if require_active:
            return ["active-use validation requires an owner_approved record"]
        return []

    errors = _worker_action_access_mode_errors(record)
    prepared = _date_time(record["prepared_at"])
    review = _date_time(record["review_at"])
    expires = _date_time(record["expires_at"])
    if not prepared < review:
        errors.append("worker authorization review_at must follow prepared_at")
    if review > expires:
        errors.append("worker authorization review_at must not follow expires_at")

    duration = _safe_timedelta(
        label="worker expected duration",
        minutes=record["expected_duration_minutes"],
    )
    if _safe_datetime_add(prepared, duration, label="worker preparation plus duration") > review:
        errors.append("expected duration does not fit between preparation and review")

    actions = set(record["requested_action_ids"])
    action_scope_ids = [scope["action_id"] for scope in record["action_scopes"]]
    duplicate_scope_ids = _duplicate_values(action_scope_ids)
    if duplicate_scope_ids:
        errors.append(f"duplicate worker action-scope IDs: {duplicate_scope_ids}")
    if action_scope_ids != record["requested_action_ids"]:
        errors.append(
            "action_scopes must have exactly one entry per requested action in the same order"
        )
    named_locations = set(record["named_test_locations"])
    scoped_locations: set[str] = set()
    one_access_actions = {
        "create_disposable_restore_test_source_copy",
        "write_primary_restore_test_copy",
        "write_independent_backup_restore_test_copy",
        "disposable_source_copy_delete",
        "representative_load_open",
    }
    multi_access_actions = {"two_copy_content_audit", "representative_restore"}
    for scope in record["action_scopes"]:
        action_id = scope["action_id"]
        accesses = scope["location_accesses"]
        locations = [access["location_ref"] for access in accesses]
        scoped_locations.update(locations)
        access_pairs = [(access["location_ref"], access["access"]) for access in accesses]
        duplicate_access_pairs = sorted(
            pair for pair in set(access_pairs) if access_pairs.count(pair) > 1
        )
        if duplicate_access_pairs:
            errors.append(
                f"action scope {action_id!r} repeats location-access pairs: "
                f"{duplicate_access_pairs}"
            )
        unknown_locations = sorted(set(locations) - named_locations)
        if unknown_locations:
            errors.append(f"action scope {action_id!r} uses unnamed locations: {unknown_locations}")
        if action_id == "static_checks" and accesses:
            errors.append("static_checks action scope must not name a location access")
        elif action_id in one_access_actions and len(accesses) != 1:
            errors.append(f"action scope {action_id!r} requires exactly one location access")
        elif action_id in multi_access_actions and len(accesses) < 2:
            errors.append(f"action scope {action_id!r} requires at least two location accesses")
        elif action_id != "static_checks" and not accesses:
            errors.append(f"action scope {action_id!r} requires at least one location access")
    if scoped_locations != named_locations:
        errors.append("named_test_locations must exactly equal the action-scope location union")

    permission_action_pairs = {
        "dataset_download": "dataset_download",
        "training": "training",
        "important_experiment": "important_experiment",
        "disposable_source_copy_delete": "disposable_source_copy_delete",
    }
    for permission, action in permission_action_pairs.items():
        if bool(record["permissions"][permission]) != (action in actions):
            errors.append(f"permission {permission} must exactly match requested action {action}")

    source_copy_actions = {
        "create_disposable_restore_test_source_copy",
        "disposable_source_copy_delete",
    }
    if actions & source_copy_actions:
        source_copy = record["disposable_restore_test_source_copy"]
        if source_copy is None:
            errors.append("disposable source-copy actions require the exact source-copy object")
        elif source_copy["location_ref"] not in named_locations:
            errors.append("disposable source-copy location is absent from named_test_locations")
        else:
            scopes_by_action = {
                scope["action_id"]: {
                    (access["location_ref"], access["access"])
                    for access in scope["location_accesses"]
                }
                for scope in record["action_scopes"]
            }
            for action_id in sorted(actions & source_copy_actions):
                expected_access = (
                    "delete" if action_id == "disposable_source_copy_delete" else "write"
                )
                if scopes_by_action.get(action_id) != {
                    (source_copy["location_ref"], expected_access)
                }:
                    errors.append(
                        f"action scope {action_id!r} must identify only the disposable "
                        f"source-copy location with {expected_access} access"
                    )

    approved: datetime | None = None
    if status == "owner_approved":
        approved = _date_time(record["approved_at"])
        if approved < prepared:
            errors.append("worker authorization approval predates preparation")
        if not approved < review:
            errors.append("worker authorization approval must precede review_at")
        if _safe_datetime_add(approved, duration, label="worker approval plus duration") > review:
            errors.append("expected duration does not fit between approval and review")

    if require_active:
        if status != "owner_approved" or approved is None:
            errors.append("active-use validation requires an owner_approved record")
        elif at_time is None:
            errors.append("active-use validation requires --at-time")
        else:
            if at_time < approved or at_time >= review:
                errors.append("authorization is not active at the requested time")
            if (
                _safe_datetime_add(at_time, duration, label="active-use time plus duration")
                > review
            ):
                errors.append("expected duration does not fit before the active review deadline")
    return errors


def active_worker_scope_errors(
    record: dict[str, Any],
    *,
    worker_ref: str,
    git_commit: str,
    action_ids: list[str],
    location_accesses: list[tuple[str, str]],
) -> list[str]:
    """Check a requested live action scope is bounded by one active authorization."""

    errors = _worker_action_access_mode_errors(record)
    if record.get("authorization_kind") != "m2_evidence_gathering":
        errors.append(
            "post-M2 active-use validation is unavailable until a canonical owner-acceptance "
            "record and append-only execution ledger are implemented"
        )
    if record["worker_ref"] != worker_ref:
        errors.append("requested worker_ref is outside the authorization scope")
    if record["git_commit"] != git_commit:
        errors.append("requested Git revision is outside the authorization scope")
    if not action_ids:
        errors.append("active-use validation requires at least one --action-id")
    elif len(action_ids) != 1:
        errors.append("standalone active-use validation accepts exactly one action at a time")
    elif action_ids != ["static_checks"]:
        errors.append(
            "version 1 standalone active-use validation permits only static_checks; "
            "non-static M2 actions require reviewed storage-plan role linkage, required "
            "pre-action evidence, and an append-only consumption interface"
        )
    if len(action_ids) != len(set(action_ids)):
        errors.append("requested action IDs contain duplicates")
    if len(location_accesses) != len(set(location_accesses)):
        errors.append("requested location-access pairs contain duplicates")
    unauthorized_actions = sorted(set(action_ids) - set(record["requested_action_ids"]))
    if unauthorized_actions:
        errors.append(f"requested action IDs are not authorized: {unauthorized_actions}")
    requested_locations = {location_ref for location_ref, _ in location_accesses}
    unauthorized_locations = sorted(requested_locations - set(record["named_test_locations"]))
    if unauthorized_locations:
        errors.append(f"requested location references are not authorized: {unauthorized_locations}")
    location_actions = set(action_ids) - {"static_checks"}
    if location_actions and not location_accesses:
        errors.append("non-static active actions require at least one --location-access")
    if len(action_ids) == 1:
        requested_action = action_ids[0]
        scopes_by_action = {
            scope["action_id"]: {
                (access["location_ref"], access["access"]) for access in scope["location_accesses"]
            }
            for scope in record["action_scopes"]
        }
        expected_accesses = scopes_by_action.get(requested_action)
        if expected_accesses is not None and set(location_accesses) != expected_accesses:
            errors.append(
                "requested location accesses do not exactly match action scope "
                f"{requested_action!r}: {sorted(expected_accesses)}"
            )
    if "disposable_source_copy_delete" in action_ids:
        errors.append(
            "standalone deletion validation is unavailable without exact pre-delete "
            "two-copy verification evidence"
        )
        source_copy = record["disposable_restore_test_source_copy"]
        expected_location = source_copy["location_ref"] if source_copy is not None else None
        if action_ids != ["disposable_source_copy_delete"]:
            errors.append(
                "disposable source-copy deletion must be validated as one isolated active action"
            )
        if location_accesses != [(expected_location, "delete")]:
            errors.append(
                "disposable source-copy deletion requires exactly delete access to its "
                "authorized source location"
            )
    return errors


def project_release_scope_semantic_errors(record: dict[str, Any]) -> list[str]:
    """Return chronology and lane-scope errors for a schema-valid scope record."""

    lane_ids = [lane["lane_id"] for lane in record.get("release_lanes", [])]
    errors: list[str] = []
    duplicates = _duplicate_values(lane_ids)
    if duplicates:
        errors.append(f"duplicate release lane IDs: {duplicates}")
    if record.get("record_status") != "ready_for_owner_review":
        return errors

    prepared = _date_time(record["prepared_at"])
    if _date_time(record["scope_cutoff"]) > prepared:
        errors.append("project scope cutoff follows project-scope preparation")
    declared_surfaces = set(record["distribution_surfaces"])
    for lane in record["release_lanes"]:
        undeclared = sorted(set(lane["distribution_surfaces"]) - declared_surfaces)
        if undeclared:
            errors.append(
                f"release lane {lane['lane_id']!r} uses undeclared distribution surfaces: "
                f"{undeclared}"
            )
    return errors


def rights_matrix_semantic_errors(record: dict[str, Any]) -> list[str]:
    """Return chronology and identity errors for a schema-valid rights matrix."""

    asset_ids = [asset["asset_id"] for asset in record.get("assets", [])]
    errors: list[str] = []
    duplicates = _duplicate_values(asset_ids)
    if duplicates:
        errors.append(f"duplicate rights asset IDs: {duplicates}")
    if record.get("record_status") != "ready_for_owner_review":
        return errors

    prepared = _date_time(record["prepared_at"])
    if _date_time(record["scope_cutoff"]) > prepared:
        errors.append("rights-matrix scope cutoff follows rights-matrix preparation")
    for asset in record["assets"]:
        asset_id = asset["asset_id"]
        terms_observed = _date_time(asset["terms_observed_at"])
        if terms_observed > prepared:
            errors.append(f"rights asset {asset_id!r} terms were observed after preparation")
        reviewed_at = asset.get("reviewed_at")
        if isinstance(reviewed_at, str):
            reviewed = _date_time(reviewed_at)
            if reviewed < terms_observed:
                errors.append(
                    f"rights asset {asset_id!r} was reviewed before its terms were observed"
                )
            if reviewed > prepared:
                errors.append(f"rights asset {asset_id!r} was reviewed after preparation")
    return errors


def project_rights_cross_field_errors(
    project_scope: dict[str, Any],
    *,
    project_scope_bytes: bytes,
    rights_matrix: dict[str, Any],
    rights_matrix_bytes: bytes,
    project_scope_path: Path | None = None,
    rights_matrix_path: Path | None = None,
    reference_root: Path | None = None,
) -> list[str]:
    """Validate one exact review-ready project-scope/rights-matrix pair."""

    errors: list[str] = []
    try:
        if (
            _decode_json_object(project_scope_bytes, path=Path("<project-release-scope-bytes>"))
            != project_scope
        ):
            errors.append("project-scope raw bytes do not decode to the supplied record")
        if (
            _decode_json_object(rights_matrix_bytes, path=Path("<rights-matrix-bytes>"))
            != rights_matrix
        ):
            errors.append("rights-matrix raw bytes do not decode to the supplied record")
    except RecordValidationError as exc:
        errors.append(f"cross-record raw-byte linkage cannot be verified: {exc}")

    if project_scope.get("record_type") != "project_release_scope":
        errors.append("project-scope record has the wrong record_type")
    if rights_matrix.get("record_type") != "rights_matrix":
        errors.append("rights-matrix record has the wrong record_type")
    if project_scope.get("record_status") != "ready_for_owner_review":
        errors.append("project-scope record is not ready_for_owner_review")
    if rights_matrix.get("record_status") != "ready_for_owner_review":
        errors.append("rights-matrix record is not ready_for_owner_review")

    link = project_scope.get("rights_matrix_ref")
    if not isinstance(link, dict):
        errors.append("project-scope record omits its typed rights-matrix link")
    else:
        if link.get("record_id") != rights_matrix.get("record_id"):
            errors.append("project-scope rights-matrix record ID does not match")
        if link.get("record_sha256") != hashlib.sha256(rights_matrix_bytes).hexdigest():
            errors.append("project-scope rights-matrix SHA-256 does not match raw bytes")
        if reference_root is not None and rights_matrix_path is not None:
            try:
                if not _reference_matches_path(
                    reference_root,
                    link.get("record_ref", ""),
                    rights_matrix_path,
                ):
                    errors.append(
                        "project-scope rights-matrix reference does not identify the supplied "
                        "record"
                    )
            except RecordValidationError as exc:
                errors.append(f"project-scope rights-matrix reference is invalid: {exc}")

    if project_scope.get("scope_cutoff") != rights_matrix.get("scope_cutoff"):
        errors.append("project scope and rights matrix use different scope cutoffs")
    project_prepared = project_scope.get("prepared_at")
    rights_prepared = rights_matrix.get("prepared_at")
    if isinstance(project_prepared, str) and isinstance(rights_prepared, str):
        if _date_time(rights_prepared) > _date_time(project_prepared):
            errors.append("rights matrix was prepared after the linked project scope")

    lane_ids = {
        lane["lane_id"]
        for lane in project_scope.get("release_lanes", [])
        if isinstance(lane, dict) and isinstance(lane.get("lane_id"), str)
    }
    for asset in rights_matrix.get("assets", []):
        if not isinstance(asset, dict):
            continue
        absent = sorted(set(asset.get("intended_lane_ids", [])) - lane_ids)
        if absent:
            errors.append(
                f"rights asset {asset.get('asset_id')!r} references absent release lanes: {absent}"
            )

    if project_scope_path is not None and rights_matrix_path is not None:
        if project_scope_path.resolve(strict=True) == rights_matrix_path.resolve(strict=True):
            errors.append("project-scope and rights-matrix paths must identify different records")
    return errors


def governance_record_semantic_errors(record: dict[str, Any]) -> list[str]:
    record_type = record.get("record_type")
    if record_type == "artifact_storage_plan":
        return artifact_storage_plan_semantic_errors(record)
    if record_type == "worker_authorization":
        return worker_authorization_semantic_errors(record)
    if record_type == "project_release_scope":
        return project_release_scope_semantic_errors(record)
    if record_type == "rights_matrix":
        return rights_matrix_semantic_errors(record)
    return []


def _check_interval(
    errors: list[str],
    *,
    label: str,
    started_at: str,
    finished_at: str,
    duration_seconds: float,
) -> None:
    start = _date_time(started_at)
    finish = _date_time(finished_at)
    if finish <= start:
        errors.append(f"{label} finish must follow start")
        return
    observed = (finish - start).total_seconds()
    if not math.isclose(observed, duration_seconds, rel_tol=1e-9, abs_tol=1e-9):
        errors.append(f"{label} duration does not match timestamps")


def _verify_hashed_evidence_reference(
    errors: list[str],
    *,
    reference_root: Path,
    reference: str,
    expected_sha256: str,
    label: str,
) -> bytes | None:
    """Load and hash one credential-free, non-template evidence reference."""

    try:
        target = _reference_target(reference_root, reference)
        if _is_template_or_draft_path(target):
            raise RecordValidationError(
                f"{label} must not identify a template or draft example: {reference!r}"
            )
        raw = _read_exact_regular_file(target)
    except RecordValidationError as exc:
        errors.append(f"{label} cannot be verified: {exc}")
        return None
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        errors.append(f"{label} SHA-256 does not match the referenced raw bytes")
        return None
    return raw


def _copy_audit_payload_errors(
    raw: bytes,
    *,
    identity: dict[str, Any],
    copy_locations: dict[str, str],
    earliest_valid_observation: datetime,
    latest_valid_observation: datetime,
    label: str,
) -> list[str]:
    """Validate the safety-critical claims in one copy-audit JSON fragment."""

    try:
        audit = _decode_json_object(raw, path=Path(f"<{label}>"))
    except RecordValidationError as exc:
        return [f"{label} is not a valid copy-audit JSON object: {exc}"]

    errors: list[str] = []
    expected_top_level_keys = {
        "schema_version",
        "tool",
        "tool_version",
        "observed_at",
        "scope",
        "assessment",
        "content_identity_verified",
        "artifact_restore_gate_passed",
        "expected_artifact_manifest_sha256",
        "artifact_manifest_path",
        "primary",
        "backup",
        "client_visible_filesystem_identifiers_distinct",
        "independent_failure_domains_verified",
        "outside_worker_locations_verified",
        "source_copy_deletion_verified",
        "restore_chronology_verified",
        "representative_load_verified",
        "blockers",
        "limitations",
        "next_action",
    }
    unknown_top_level = sorted(set(audit) - expected_top_level_keys)
    missing_top_level = sorted(expected_top_level_keys - set(audit))
    if unknown_top_level:
        errors.append(f"{label} contains unknown top-level fields: {unknown_top_level}")
    if missing_top_level:
        errors.append(f"{label} omits required top-level fields: {missing_top_level}")
    expected_scalars = {
        "schema_version": "1.0.0",
        "tool": "compact-vio-copy-audit",
        "scope": "read_only_bundle_copy_content_audit",
        "assessment": "copy_content_verified",
        "content_identity_verified": True,
        "artifact_restore_gate_passed": False,
        "expected_artifact_manifest_sha256": identity["artifact_manifest_sha256"],
        "artifact_manifest_path": "artifact-manifest.json",
        "independent_failure_domains_verified": False,
        "outside_worker_locations_verified": False,
        "source_copy_deletion_verified": False,
        "restore_chronology_verified": False,
        "representative_load_verified": False,
    }
    for field, expected in expected_scalars.items():
        if audit.get(field) != expected:
            errors.append(f"{label}.{field} does not match the required copy-audit claim")
    if not isinstance(audit.get("tool_version"), str) or not audit["tool_version"]:
        errors.append(f"{label}.tool_version is absent")
    if audit.get("blockers") != []:
        errors.append(f"{label}.blockers is not empty")
    limitations = audit.get("limitations")
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not isinstance(item, str) or not item for item in limitations)
    ):
        errors.append(f"{label}.limitations is empty or absent")
    if not isinstance(audit.get("next_action"), str) or not audit["next_action"]:
        errors.append(f"{label}.next_action is empty or absent")
    if not isinstance(audit.get("client_visible_filesystem_identifiers_distinct"), bool):
        errors.append(f"{label}.client_visible_filesystem_identifiers_distinct is not boolean")

    observed_at = audit.get("observed_at")
    if not isinstance(observed_at, str):
        errors.append(f"{label}.observed_at is absent")
    else:
        try:
            observed = _date_time(observed_at)
        except (RecordValidationError, ValueError) as exc:
            errors.append(f"{label}.observed_at is invalid: {exc}")
        else:
            if observed < earliest_valid_observation:
                errors.append(f"{label} predates completion of both copy verifications")
            if observed >= latest_valid_observation:
                errors.append(
                    f"{label} does not strictly precede deletion of its disposable source copy"
                )

    expected_accounting = {
        "artifact_manifest_sha256": identity["artifact_manifest_sha256"],
        "artifact_manifest_matches_expected": True,
        "payload_file_count": identity["payload_file_count"],
        "payload_bytes": identity["payload_bytes"],
        "artifact_manifest_bytes": identity["artifact_manifest_bytes"],
        "bundle_file_count": identity["bundle_file_count"],
        "bundle_bytes": identity["bundle_bytes"],
    }
    expected_observation_keys = {
        "copy_ref",
        "client_visible_filesystem_identifier",
        *expected_accounting,
        "bundle_verification",
    }
    for role in ("primary", "backup"):
        observation = audit.get(role)
        if not isinstance(observation, dict):
            errors.append(f"{label}.{role} observation is absent")
            continue
        unknown_observation = sorted(set(observation) - expected_observation_keys)
        missing_observation = sorted(expected_observation_keys - set(observation))
        if unknown_observation:
            errors.append(
                f"{label}.{role} contains unknown observation fields: {unknown_observation}"
            )
        if missing_observation:
            errors.append(
                f"{label}.{role} omits required observation fields: {missing_observation}"
            )
        filesystem_identifier = observation.get("client_visible_filesystem_identifier")
        if not isinstance(filesystem_identifier, int) or isinstance(filesystem_identifier, bool):
            errors.append(f"{label}.{role}.client_visible_filesystem_identifier is not an integer")
        expected_role = "primary_vault" if role == "primary" else "independent_backup"
        if observation.get("copy_ref") != copy_locations[expected_role]:
            errors.append(f"{label}.{role}.copy_ref does not match the retained copy location")
        for field, expected in expected_accounting.items():
            if observation.get(field) != expected:
                errors.append(f"{label}.{role}.{field} does not match the frozen bundle")
        verification = observation.get("bundle_verification")
        if not isinstance(verification, dict):
            errors.append(f"{label}.{role}.bundle_verification is absent")
        else:
            expected_verification = {
                "ok": True,
                "missing": [],
                "unexpected": [],
                "size_mismatches": [],
                "hash_mismatches": [],
            }
            if set(verification) != set(expected_verification):
                errors.append(
                    f"{label}.{role}.bundle_verification fields do not match the contract"
                )
            if verification != expected_verification:
                errors.append(f"{label}.{role}.bundle_verification is not clean")
    return errors


def storage_evidence_cross_field_errors(
    evidence: dict[str, Any],
    *,
    run: dict[str, Any],
    run_bytes: bytes,
    artifact_manifest: dict[str, Any],
    artifact_manifest_bytes: bytes,
    storage_plan: dict[str, Any] | None = None,
    storage_plan_bytes: bytes | None = None,
    storage_plan_path: Path | None = None,
    storage_evidence_path: Path | None = None,
    worker_authorization: dict[str, Any] | None = None,
    worker_authorization_bytes: bytes | None = None,
    worker_authorization_path: Path | None = None,
    reference_root: Path | None = None,
) -> list[str]:
    """Return semantic linkage errors that Draft 2020-12 cannot express."""

    if evidence.get("status") != "verified":
        return []

    errors = run_manifest_semantic_errors(run)
    errors.extend(artifact_manifest_semantic_errors(artifact_manifest))
    if run.get("status") not in {"succeeded", "failed", "aborted"}:
        errors.append("verified storage evidence must identify a terminal run")
    run_finished_value = run.get("finished_at")
    run_finished = _date_time(run_finished_value) if isinstance(run_finished_value, str) else None
    identity = evidence["bundle_identity"]
    expected_run_sha = hashlib.sha256(run_bytes).hexdigest()
    expected_artifact_sha = hashlib.sha256(artifact_manifest_bytes).hexdigest()
    records = artifact_manifest["files"]
    expected_payload_file_count = len(records)
    expected_payload_bytes = sum(record["bytes"] for record in records)
    expected_artifact_manifest_bytes = len(artifact_manifest_bytes)
    expected_bundle_file_count = expected_payload_file_count + 1
    expected_bundle_bytes = expected_payload_bytes + expected_artifact_manifest_bytes

    try:
        decoded_run = _decode_json_object(run_bytes, path=Path("<raw-run-manifest>"))
    except RecordValidationError:
        errors.append("raw run-manifest bytes are not valid JSON")
    else:
        if decoded_run != run:
            errors.append("raw run-manifest bytes do not decode to the validated run object")

    try:
        decoded_artifact_manifest = _decode_json_object(
            artifact_manifest_bytes, path=Path("<raw-artifact-manifest>")
        )
    except RecordValidationError:
        errors.append("raw artifact-manifest bytes are not valid JSON")
    else:
        if decoded_artifact_manifest != artifact_manifest:
            errors.append(
                "raw artifact-manifest bytes do not decode to the validated artifact object"
            )

    expected_identity_fields = {
        "run_id": run["run_id"],
        "run_manifest_sha256": expected_run_sha,
        "artifact_manifest_sha256": expected_artifact_sha,
        "payload_file_count": expected_payload_file_count,
        "payload_bytes": expected_payload_bytes,
        "artifact_manifest_bytes": expected_artifact_manifest_bytes,
        "bundle_file_count": expected_bundle_file_count,
        "bundle_bytes": expected_bundle_bytes,
    }
    if any(identity.get(key) != value for key, value in expected_identity_fields.items()):
        errors.append("bundle identity does not match immutable manifest bytes")

    by_path = {record["path"]: record for record in records}
    run_record = by_path.get("run-manifest.json")
    if run_record != {
        "path": "run-manifest.json",
        "bytes": len(run_bytes),
        "sha256": expected_run_sha,
    }:
        errors.append("artifact manifest does not identify the exact run-manifest bytes")

    for artifact in run["artifacts"]:
        record = by_path.get(artifact["path"])
        if record is None:
            errors.append(f"run artifact is absent from artifact manifest: {artifact['path']}")
        elif (record["bytes"], record["sha256"]) != (
            artifact["byte_size"],
            artifact["sha256"],
        ):
            errors.append(f"run artifact identity mismatch: {artifact['path']}")

    roles = [copy_record["role"] for copy_record in evidence["copies"]]
    if sorted(roles) != ["independent_backup", "primary_vault"]:
        errors.append("copies must contain exactly one primary vault and independent backup")
    locations = [copy_record["location_ref"] for copy_record in evidence["copies"]]
    copy_locations_by_role = {
        copy_record["role"]: copy_record["location_ref"] for copy_record in evidence["copies"]
    }
    if len(locations) != len(set(locations)):
        errors.append("copy location references must be distinct")

    if storage_plan is None or storage_plan_bytes is None:
        errors.append("verified storage evidence requires its reviewed storage-plan bytes")
    else:
        if storage_plan.get("record_type") != "artifact_storage_plan":
            errors.append("review record is not an artifact_storage_plan")
        if storage_plan.get("record_status") != "ready_for_owner_review":
            errors.append("storage plan is not ready_for_owner_review")
        errors.extend(artifact_storage_plan_semantic_errors(storage_plan))
        review = evidence["storage_review"]
        if review["review_record_sha256"] != hashlib.sha256(storage_plan_bytes).hexdigest():
            errors.append("storage review hash does not match the reviewed storage-plan bytes")
        if review["review_record_id"] != storage_plan.get("record_id"):
            errors.append("storage review record ID does not match the storage plan")
        plan_locations = {
            "primary_vault": storage_plan["primary_vault"],
            "independent_backup": storage_plan["independent_backup"],
        }
        for copy_record in evidence["copies"]:
            planned = plan_locations[copy_record["role"]]
            if copy_record["storage_candidate_id"] != planned["candidate_id"]:
                errors.append(f"{copy_record['role']} candidate does not match the storage plan")
            if copy_record["location_ref"] != planned["location_ref"]:
                errors.append(f"{copy_record['role']} location does not match the storage plan")
        if reference_root is not None and storage_plan_path is not None:
            if not _reference_matches_path(
                reference_root, review["review_record_ref"], storage_plan_path
            ):
                errors.append(
                    "storage-review reference does not identify the supplied storage plan"
                )
        if reference_root is not None and storage_evidence_path is not None:
            plan_evidence_ref = storage_plan["evidence_refs"]["storage_evidence_ref"]
            if not _reference_matches_path(
                reference_root, plan_evidence_ref, storage_evidence_path
            ):
                errors.append(
                    "storage-plan evidence reference does not identify the supplied sidecar"
                )

    latest_copy_verification: datetime | None = None
    earliest_copy_start: datetime | None = None
    for copy_record in evidence["copies"]:
        label = f"{copy_record['role']} transfer"
        _check_interval(
            errors,
            label=label,
            started_at=copy_record["transfer_started_at"],
            finished_at=copy_record["transfer_finished_at"],
            duration_seconds=copy_record["duration_seconds"],
        )
        expected_throughput = copy_record["bytes_transferred"] / copy_record["duration_seconds"]
        if not math.isclose(
            copy_record["throughput_bytes_per_second"],
            expected_throughput,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ):
            errors.append(f"{label} throughput does not match bytes and duration")
        verification = copy_record["verification"]
        if (
            copy_record["bytes_transferred"] != expected_bundle_bytes
            or verification["artifact_manifest_sha256"] != expected_artifact_sha
            or verification["payload_files_verified"] != expected_payload_file_count
            or verification["payload_bytes_verified"] != expected_payload_bytes
            or verification["artifact_manifest_bytes_verified"] != expected_artifact_manifest_bytes
            or verification["bundle_files_verified"] != expected_bundle_file_count
            or verification["bundle_bytes_verified"] != expected_bundle_bytes
        ):
            errors.append(f"{label} does not cover the complete frozen bundle")
        finished = _date_time(copy_record["transfer_finished_at"])
        started = _date_time(copy_record["transfer_started_at"])
        earliest_copy_start = min(earliest_copy_start or started, started)
        verified = _date_time(verification["verified_at"])
        if verified < finished:
            errors.append(f"{label} verification predates transfer completion")
        latest_copy_verification = max(latest_copy_verification or verified, verified)

    if run_finished is not None and earliest_copy_start is not None:
        if earliest_copy_start < run_finished:
            errors.append("copy/export starts before the terminal run is frozen")
    execution_context = evidence["execution_context"]
    execution_start = _date_time(execution_context["started_at"])
    execution_finish = _date_time(execution_context["finished_at"])
    if execution_finish <= execution_start:
        errors.append("execution context finish must follow start")
    if run_finished is not None and execution_start < run_finished:
        errors.append("storage-drill execution starts before the terminal run is frozen")
    if earliest_copy_start is not None and execution_start > earliest_copy_start:
        errors.append("execution context starts after the first copy/export action")
    if storage_plan is not None and _date_time(storage_plan["prepared_at"]) > execution_start:
        errors.append("reviewed storage plan was prepared after storage-drill execution began")
    if storage_plan is not None:
        if _date_time(storage_plan["capacity_envelope"]["valid_until"]) < execution_finish:
            errors.append("storage-drill execution outlasts the storage-capacity validity window")
        if _date_time(storage_plan["cost_envelope"]["review_at"]) < execution_finish:
            errors.append("storage-drill execution outlasts the storage-cost review window")
        for retention_class, rule in storage_plan["retention_rules"].items():
            if _date_time(rule["review_at"]) < execution_finish:
                errors.append(
                    "storage-drill execution outlasts the "
                    f"{retention_class} retention review window"
                )

    deletion = evidence["source_test_copy_deletion"]
    deleted_at = _date_time(deletion["deleted_at"])
    absence_verified_at = _date_time(deletion["absence_verified_at"])
    if latest_copy_verification is not None and deleted_at <= latest_copy_verification:
        errors.append("disposable source test copy deletion must strictly follow copy verification")
    if absence_verified_at <= deleted_at:
        errors.append("source-copy absence verification must strictly follow deletion")
    if deletion["source_copy_ref"] in locations:
        errors.append("disposable source test copy must not be a retained copy location")

    restore = evidence["restore"]
    _check_interval(
        errors,
        label="restore",
        started_at=restore["restore_started_at"],
        finished_at=restore["restore_finished_at"],
        duration_seconds=restore["duration_seconds"],
    )
    if _date_time(restore["restore_started_at"]) <= absence_verified_at:
        errors.append(
            "restore must start strictly after disposable source-copy deletion is verified"
        )
    if restore["destination_ref"] in set(locations) | {deletion["source_copy_ref"]}:
        errors.append("restore destination must be a new location reference")
    expected_restore_throughput = restore["bytes_restored"] / restore["duration_seconds"]
    if not math.isclose(
        restore["throughput_bytes_per_second"],
        expected_restore_throughput,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        errors.append("restore throughput does not match bytes and duration")
    restore_verification = restore["verification"]
    if (
        restore["bytes_restored"] != expected_bundle_bytes
        or restore_verification["artifact_manifest_sha256"] != expected_artifact_sha
        or restore_verification["payload_files_verified"] != expected_payload_file_count
        or restore_verification["payload_bytes_verified"] != expected_payload_bytes
        or restore_verification["artifact_manifest_bytes_verified"]
        != expected_artifact_manifest_bytes
        or restore_verification["bundle_files_verified"] != expected_bundle_file_count
        or restore_verification["bundle_bytes_verified"] != expected_bundle_bytes
    ):
        errors.append("restore verification does not cover the complete frozen bundle")
    restore_finish = _date_time(restore["restore_finished_at"])
    restore_verified = _date_time(restore_verification["verified_at"])
    if restore_verified < restore_finish:
        errors.append("restore verification predates restore completion")

    load_open = evidence["load_open"]
    _check_interval(
        errors,
        label="load/open",
        started_at=load_open["started_at"],
        finished_at=load_open["finished_at"],
        duration_seconds=load_open["duration_seconds"],
    )
    if load_open["artifact_path"] not in by_path:
        errors.append("load/open artifact is absent from the frozen bundle")
    if _date_time(load_open["started_at"]) <= restore_verified:
        errors.append("load/open check must start strictly after restored-content verification")
    load_finish = _date_time(load_open["finished_at"])
    if execution_finish < load_finish:
        errors.append("execution context ends before representative load/open completion")

    review_time = _date_time(evidence["storage_review"]["assessed_at"])
    if review_time <= load_finish:
        errors.append("storage/failure-domain review must occur strictly after the load/open check")
    assessment_time = _date_time(evidence["assessment"]["assessed_at"])
    if assessment_time <= review_time:
        errors.append("final assessment must occur strictly after storage/failure-domain review")
    created_time = _date_time(evidence["created_at"])
    if created_time < assessment_time:
        errors.append("verified evidence creation predates its final assessment")

    supporting_paths = [item["path"] for item in evidence["supporting_evidence"]]
    duplicate_supporting_paths = _duplicate_values(supporting_paths)
    if duplicate_supporting_paths:
        errors.append(f"duplicate supporting-evidence paths: {duplicate_supporting_paths}")
    audit_indexes = [
        index
        for index, item in enumerate(evidence["supporting_evidence"])
        if item["kind"] == "two_copy_content_audit"
    ]
    if len(audit_indexes) != 1:
        errors.append("verified storage evidence requires exactly one two-copy content audit")
    if reference_root is not None:
        for index, item in enumerate(evidence["supporting_evidence"]):
            raw_evidence = _verify_hashed_evidence_reference(
                errors,
                reference_root=reference_root,
                reference=item["path"],
                expected_sha256=item["sha256"],
                label=f"supporting_evidence[{index}]",
            )
            if item["kind"] == "two_copy_content_audit" and raw_evidence is not None:
                assert latest_copy_verification is not None
                errors.extend(
                    _copy_audit_payload_errors(
                        raw_evidence,
                        identity=identity,
                        copy_locations=copy_locations_by_role,
                        earliest_valid_observation=latest_copy_verification,
                        latest_valid_observation=deleted_at,
                        label=f"supporting_evidence[{index}]",
                    )
                )
        _verify_hashed_evidence_reference(
            errors,
            reference_root=reference_root,
            reference=load_open["evidence_ref"],
            expected_sha256=load_open["evidence_sha256"],
            label="load_open evidence",
        )

    authorization_link = evidence["worker_authorization"]
    if execution_context["kind"] == "non_paid_environment":
        if execution_context["cost_evidence"] is not None:
            errors.append("non-paid execution context must not include paid cost evidence")
        if authorization_link is not None or worker_authorization is not None:
            errors.append("non-paid execution context must not claim paid-worker authorization")
    elif worker_authorization is None or worker_authorization_bytes is None:
        errors.append("paid-worker execution requires the exact worker-authorization record")
    else:
        errors.extend(
            worker_authorization_semantic_errors(
                worker_authorization,
                at_time=execution_start,
                require_active=True,
            )
        )
        if worker_authorization.get("record_status") != "owner_approved":
            errors.append("paid-worker drill authorization is not owner_approved")
        if worker_authorization.get("authorization_kind") != "m2_evidence_gathering":
            errors.append("paid-worker drill requires an m2_evidence_gathering authorization")
        if authorization_link is None:
            errors.append("paid-worker sidecar omits worker-authorization linkage")
        else:
            if (
                authorization_link["record_sha256"]
                != hashlib.sha256(worker_authorization_bytes).hexdigest()
            ):
                errors.append("worker-authorization hash does not match supplied record bytes")
            if authorization_link["record_id"] != worker_authorization.get("record_id"):
                errors.append("worker-authorization record ID does not match supplied record")
            if reference_root is not None and worker_authorization_path is not None:
                if not _reference_matches_path(
                    reference_root,
                    authorization_link["record_ref"],
                    worker_authorization_path,
                ):
                    errors.append(
                        "worker-authorization reference does not identify the supplied record"
                    )
        if worker_authorization.get("git_commit") != run["provenance"]["git"]["commit_sha"]:
            errors.append("worker authorization Git revision does not match the run")
        if worker_authorization.get("worker_ref") != execution_context["execution_ref"]:
            errors.append("worker authorization does not identify the execution worker")
        required_actions = {
            "create_disposable_restore_test_source_copy",
            "write_primary_restore_test_copy",
            "write_independent_backup_restore_test_copy",
            "two_copy_content_audit",
            "disposable_source_copy_delete",
            "representative_restore",
            "representative_load_open",
        }
        missing_actions = sorted(
            required_actions - set(worker_authorization["requested_action_ids"])
        )
        if missing_actions:
            errors.append(f"worker authorization omits drill actions: {missing_actions}")
        authorized_scopes = {
            scope["action_id"]: {
                (access["location_ref"], access["access"]) for access in scope["location_accesses"]
            }
            for scope in worker_authorization["action_scopes"]
        }
        source_copy = worker_authorization["disposable_restore_test_source_copy"]
        if source_copy is not None:
            if source_copy["artifact_manifest_sha256"] != expected_artifact_sha:
                errors.append("authorized disposable source copy identifies another bundle")
            if source_copy["location_ref"] != deletion["source_copy_ref"]:
                errors.append("deleted source copy differs from the authorized disposable copy")
        named_locations = set(worker_authorization["named_test_locations"])
        required_locations = set(locations) | {
            deletion["source_copy_ref"],
            restore["destination_ref"],
        }
        if not required_locations <= named_locations:
            errors.append("worker authorization omits one or more drill locations")
        expected_action_scopes = {
            "create_disposable_restore_test_source_copy": {(deletion["source_copy_ref"], "write")},
            "write_primary_restore_test_copy": {(copy_locations_by_role["primary_vault"], "write")},
            "write_independent_backup_restore_test_copy": {
                (copy_locations_by_role["independent_backup"], "write")
            },
            "two_copy_content_audit": {
                (copy_locations_by_role["primary_vault"], "read"),
                (copy_locations_by_role["independent_backup"], "read"),
            },
            "disposable_source_copy_delete": {(deletion["source_copy_ref"], "delete")},
            "representative_restore": {
                (copy_locations_by_role[restore["source_role"]], "read"),
                (restore["destination_ref"], "write"),
            },
            "representative_load_open": {(restore["destination_ref"], "read")},
        }
        for action_id, expected_accesses in expected_action_scopes.items():
            if authorized_scopes.get(action_id) != expected_accesses:
                errors.append(
                    f"worker action scope {action_id!r} does not match the performed drill "
                    f"location accesses: {sorted(expected_accesses)}"
                )
        if execution_finish > _date_time(worker_authorization["review_at"]):
            errors.append("paid-worker drill continued beyond its authorization review time")
        approved_duration = _safe_timedelta(
            label="paid-worker approved duration",
            minutes=worker_authorization["expected_duration_minutes"],
        )
        if execution_finish - execution_start > approved_duration:
            errors.append("paid-worker drill duration exceeds the approved duration")
        cost_evidence = execution_context["cost_evidence"]
        if cost_evidence is None:
            errors.append("paid-worker drill omits observed cost evidence")
        else:
            cost_observed = _date_time(cost_evidence["observed_at"])
            if cost_observed < execution_finish:
                errors.append("paid-worker cost was observed before execution finished")
            if cost_observed > assessment_time:
                errors.append("paid-worker final assessment predates its cost observation")
            spending_ceiling = worker_authorization["spending_ceiling"]
            if cost_evidence["currency"] != spending_ceiling["currency"]:
                errors.append("paid-worker observed-cost currency differs from the ceiling")
            if cost_evidence["observed_amount"] > spending_ceiling["amount"]:
                errors.append("paid-worker observed cost exceeds the approved spending ceiling")
            if storage_plan is not None:
                plan_cost = storage_plan["cost_envelope"]
                if spending_ceiling["currency"] != plan_cost["currency"]:
                    errors.append(
                        "worker authorization currency differs from the storage-plan currency"
                    )
                if spending_ceiling["amount"] > plan_cost["worker_spend_ceiling"]:
                    errors.append(
                        "worker authorization ceiling exceeds the storage-plan worker ceiling"
                    )
                if cost_evidence["observed_amount"] > plan_cost["worker_spend_ceiling"]:
                    errors.append("paid-worker observed cost exceeds the storage-plan ceiling")
            if reference_root is not None:
                _verify_hashed_evidence_reference(
                    errors,
                    reference_root=reference_root,
                    reference=cost_evidence["evidence_ref"],
                    expected_sha256=cost_evidence["evidence_sha256"],
                    label="paid-worker cost evidence",
                )
    return errors


def _assert_cross_invalid(
    evidence: dict[str, Any],
    *,
    label: str,
    run: dict[str, Any],
    run_bytes: bytes,
    artifact_manifest: dict[str, Any],
    artifact_manifest_bytes: bytes,
    storage_plan: dict[str, Any],
    storage_plan_bytes: bytes,
) -> None:
    if not storage_evidence_cross_field_errors(
        evidence,
        run=run,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    ):
        raise AssertionError(f"cross-record validation accepted forbidden fixture: {label}")


def _assert_error_contains(errors: list[str], expected: str, *, label: str) -> None:
    if not any(expected in error for error in errors):
        raise AssertionError(
            f"semantic validation did not report {expected!r} for {label}: {errors}"
        )


def _validate_templates(
    schemas: dict[str, dict[str, Any]],
    *,
    format_checker: FormatChecker,
) -> int:
    matched: set[Path] = set()
    for schema_path in _schema_paths():
        template_path = _matching_template(schema_path)
        if template_path is None:
            continue
        template = _load(template_path)
        _require_schema_valid(
            schemas[schema_path.name],
            template,
            label=str(template_path.relative_to(ROOT)),
            format_checker=format_checker,
        )
        expected_schema = RECORD_TYPE_SCHEMA_FILES.get(template.get("record_type"))
        if expected_schema is None:
            expected_schema = CONFIG_RECORD_TYPE_SCHEMA_FILES.get(template.get("record_type"))
        if expected_schema != schema_path.name:
            raise RecordValidationError(
                f"template {template_path} record_type maps to {expected_schema!r}, "
                f"not {schema_path.name!r}"
            )
        matched.add(template_path.resolve(strict=True))

    template_paths = {
        path.resolve(strict=True)
        for directory in (TEMPLATE_DIRECTORY, CONFIG_TEMPLATE_DIRECTORY)
        for path in directory.rglob("*.json")
    }
    orphaned = sorted(template_paths - matched)
    if orphaned:
        raise RecordValidationError(f"templates without one matching schema: {orphaned}")
    return len(matched)


def _discover_and_validate_governance_records(
    records_root: Path,
    *,
    reference_root: Path,
    schemas: dict[str, dict[str, Any]],
    format_checker: FormatChecker,
) -> int:
    root = records_root.resolve(strict=True)
    records: dict[tuple[str, str], tuple[dict[str, Any], bytes, Path]] = {}
    for path in sorted(root.rglob("*.json")):
        if _is_template_or_draft_path(path):
            continue
        record, raw = _load_with_bytes(path)
        record_type = record.get("record_type")
        if not isinstance(record_type, str):
            raise RecordValidationError(f"real governance record lacks record_type: {path}")
        schema_name = RECORD_TYPE_SCHEMA_FILES.get(record_type)
        if schema_name is None:
            raise RecordValidationError(f"unknown governance record_type {record_type!r}: {path}")
        schema = schemas.get(schema_name)
        if schema is None:
            raise RecordValidationError(
                f"orphan governance record has no loaded schema {schema_name!r}: {path}"
            )
        _require_schema_valid(
            schema,
            record,
            label=str(path),
            format_checker=format_checker,
        )
        path_errors = _canonical_record_path_errors(path, records_root=root, record=record)
        semantic_errors = governance_record_semantic_errors(record)
        if path_errors or semantic_errors:
            raise RecordValidationError(
                f"governance record semantic validation failed for {path}: "
                f"{path_errors + semantic_errors}"
            )
        identifier = _record_identifier(record)
        assert identifier is not None
        identity = (record_type, identifier)
        if identity in records:
            raise RecordValidationError(f"duplicate governance record identity {identity}")
        records[identity] = (record, raw, path.resolve(strict=True))

    for identity, (project_scope, project_bytes, project_path) in records.items():
        if identity[0] != "project_release_scope":
            continue
        if project_scope.get("record_status") != "ready_for_owner_review":
            continue
        link = project_scope.get("rights_matrix_ref")
        linked_id = link.get("record_id") if isinstance(link, dict) else None
        linked = records.get(("rights_matrix", linked_id))
        if linked is None:
            raise RecordValidationError(
                "ready project-scope record does not link an existing canonical rights "
                f"matrix: {project_path}"
            )
        rights_matrix, rights_bytes, rights_path = linked
        cross_errors = project_rights_cross_field_errors(
            project_scope,
            project_scope_bytes=project_bytes,
            rights_matrix=rights_matrix,
            rights_matrix_bytes=rights_bytes,
            project_scope_path=project_path,
            rights_matrix_path=rights_path,
            reference_root=reference_root,
        )
        if cross_errors:
            raise RecordValidationError(
                f"project-scope/rights-matrix cross-record validation failed for "
                f"{project_path}: {cross_errors}"
            )
    return len(records)


def _assert_project_rights_discovery_contract(
    *,
    schemas: dict[str, dict[str, Any]],
    format_checker: FormatChecker,
) -> None:
    """Exercise canonical discovery with a valid and a missing rights-matrix link."""

    with tempfile.TemporaryDirectory(prefix="compact-vio-schema-discovery-") as temporary:
        reference_root = Path(temporary)
        records_root = reference_root / "governance/records"
        rights_directory = records_root / "rights_matrix"
        project_directory = records_root / "project_release_scope"
        rights_directory.mkdir(parents=True)
        project_directory.mkdir(parents=True)

        rights_matrix = _reviewed_rights_matrix()
        rights_bytes = _canonical_json_bytes(rights_matrix)
        rights_path = rights_directory / "rights-matrix-fixture.json"
        rights_path.write_bytes(rights_bytes)
        project_scope = _reviewed_project_release_scope(rights_bytes)
        project_path = project_directory / "project-scope-fixture.json"
        project_path.write_bytes(_canonical_json_bytes(project_scope))

        count = _discover_and_validate_governance_records(
            records_root,
            reference_root=reference_root,
            schemas=schemas,
            format_checker=format_checker,
        )
        if count != 2:
            raise AssertionError(
                f"project/rights discovery fixture returned {count} records instead of 2"
            )

        missing_link = copy.deepcopy(project_scope)
        missing_link["rights_matrix_ref"] = {
            "record_ref": "governance/records/rights_matrix/does-not-exist.json",
            "record_sha256": ZERO_HASH,
            "record_id": "does-not-exist",
        }
        project_path.write_bytes(_canonical_json_bytes(missing_link))
        try:
            _discover_and_validate_governance_records(
                records_root,
                reference_root=reference_root,
                schemas=schemas,
                format_checker=format_checker,
            )
        except RecordValidationError as exc:
            if "does not link an existing canonical rights matrix" not in str(exc):
                raise AssertionError(
                    f"missing rights-matrix fixture failed for the wrong reason: {exc}"
                ) from exc
        else:
            raise AssertionError("discovery accepted a nonexistent rights-matrix link")


def _parse_at_time(value: str) -> datetime:
    try:
        return _date_time(value)
    except (RecordValidationError, ValueError) as exc:
        raise RecordValidationError(f"invalid --at-time value {value!r}: {exc}") from exc


def _require_real_record_path(path: Path, *, label: str) -> None:
    if _is_template_or_draft_path(path):
        raise RecordValidationError(f"{label} must not be a template or draft example: {path}")


def _load_schema_validated_file(
    path: Path,
    *,
    schema: dict[str, Any],
    label: str,
    format_checker: FormatChecker,
) -> tuple[dict[str, Any], bytes]:
    value, raw = _load_with_bytes(path)
    _require_schema_valid(
        schema,
        value,
        label=label,
        format_checker=format_checker,
    )
    return value, raw


def _validate_project_rights_records(
    project_scope_path: Path,
    rights_matrix_path: Path,
    *,
    reference_root: Path,
    records_root: Path,
    schemas: dict[str, dict[str, Any]],
    format_checker: FormatChecker,
) -> None:
    """Validate one exact canonical project-scope and rights-matrix record pair."""

    _require_real_record_path(project_scope_path, label="project/release scope")
    _require_real_record_path(rights_matrix_path, label="rights matrix")
    project_scope, project_bytes = _load_schema_validated_file(
        project_scope_path,
        schema=schemas["project-release-scope.schema.json"],
        label="project/release scope",
        format_checker=format_checker,
    )
    rights_matrix, rights_bytes = _load_schema_validated_file(
        rights_matrix_path,
        schema=schemas["rights-matrix.schema.json"],
        label="rights matrix",
        format_checker=format_checker,
    )
    errors = _canonical_record_path_errors(
        project_scope_path.resolve(strict=True),
        records_root=records_root.resolve(strict=True),
        record=project_scope,
    )
    errors.extend(
        _canonical_record_path_errors(
            rights_matrix_path.resolve(strict=True),
            records_root=records_root.resolve(strict=True),
            record=rights_matrix,
        )
    )
    errors.extend(project_release_scope_semantic_errors(project_scope))
    errors.extend(rights_matrix_semantic_errors(rights_matrix))
    errors.extend(
        project_rights_cross_field_errors(
            project_scope,
            project_scope_bytes=project_bytes,
            rights_matrix=rights_matrix,
            rights_matrix_bytes=rights_bytes,
            project_scope_path=project_scope_path,
            rights_matrix_path=rights_matrix_path,
            reference_root=reference_root,
        )
    )
    if errors:
        raise RecordValidationError(
            f"project-scope/rights-matrix record-set semantic errors: {errors}"
        )


def _validate_worker_authorization_file(
    path: Path,
    *,
    records_root: Path,
    schemas: dict[str, dict[str, Any]],
    format_checker: FormatChecker,
    at_time: datetime | None,
    require_active: bool,
) -> tuple[dict[str, Any], bytes]:
    _require_real_record_path(path, label="worker authorization")
    record, raw = _load_schema_validated_file(
        path,
        schema=schemas["worker-authorization.schema.json"],
        label="worker authorization",
        format_checker=format_checker,
    )
    errors = _canonical_record_path_errors(
        path.resolve(strict=True),
        records_root=records_root.resolve(strict=True),
        record=record,
    )
    errors.extend(
        worker_authorization_semantic_errors(
            record,
            at_time=at_time,
            require_active=require_active,
        )
    )
    if errors:
        raise RecordValidationError(f"worker authorization semantic errors: {errors}")
    return record, raw


def _validate_real_storage_evidence(
    *,
    run_path: Path,
    artifact_manifest_path: Path,
    storage_evidence_path: Path,
    storage_plan_path: Path,
    worker_authorization_path: Path | None,
    reference_root: Path,
    records_root: Path,
    schemas: dict[str, dict[str, Any]],
    format_checker: FormatChecker,
) -> None:
    for label, path in (
        ("run manifest", run_path),
        ("artifact manifest", artifact_manifest_path),
        ("storage evidence", storage_evidence_path),
        ("storage plan", storage_plan_path),
    ):
        _require_real_record_path(path, label=label)

    run, run_bytes = _load_schema_validated_file(
        run_path,
        schema=schemas["run-manifest.schema.json"],
        label="run manifest",
        format_checker=format_checker,
    )
    artifact_manifest, artifact_manifest_bytes = _load_schema_validated_file(
        artifact_manifest_path,
        schema=schemas["artifact-manifest.schema.json"],
        label="artifact manifest",
        format_checker=format_checker,
    )
    evidence, _ = _load_schema_validated_file(
        storage_evidence_path,
        schema=schemas["artifact-storage-evidence.schema.json"],
        label="artifact-storage evidence",
        format_checker=format_checker,
    )
    storage_plan, storage_plan_bytes = _load_schema_validated_file(
        storage_plan_path,
        schema=schemas["artifact-storage-plan.schema.json"],
        label="artifact-storage plan",
        format_checker=format_checker,
    )
    canonical_errors = _canonical_record_path_errors(
        storage_evidence_path.resolve(strict=True),
        records_root=records_root.resolve(strict=True),
        record=evidence,
    )
    canonical_errors.extend(
        _canonical_record_path_errors(
            storage_plan_path.resolve(strict=True),
            records_root=records_root.resolve(strict=True),
            record=storage_plan,
        )
    )
    if canonical_errors:
        raise RecordValidationError(f"non-canonical governed evidence paths: {canonical_errors}")
    if evidence.get("status") != "verified":
        raise RecordValidationError("real storage-evidence validation requires status verified")
    if storage_plan.get("record_status") != "ready_for_owner_review":
        raise RecordValidationError(
            "real storage-evidence validation requires a ready_for_owner_review storage plan"
        )

    worker_record: dict[str, Any] | None = None
    worker_bytes: bytes | None = None
    if worker_authorization_path is not None:
        worker_record, worker_bytes = _validate_worker_authorization_file(
            worker_authorization_path,
            records_root=records_root,
            schemas=schemas,
            format_checker=format_checker,
            at_time=None,
            require_active=False,
        )
    if evidence["execution_context"]["kind"] == "paid_worker":
        if worker_authorization_path is None:
            raise RecordValidationError("paid-worker evidence requires --worker-authorization")
    elif worker_authorization_path is not None:
        raise RecordValidationError("non-paid evidence must not supply --worker-authorization")

    errors = storage_evidence_cross_field_errors(
        evidence,
        run=run,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
        storage_plan_path=storage_plan_path,
        storage_evidence_path=storage_evidence_path,
        worker_authorization=worker_record,
        worker_authorization_bytes=worker_bytes,
        worker_authorization_path=worker_authorization_path,
        reference_root=reference_root,
    )
    if errors:
        raise RecordValidationError(f"real storage-evidence semantic errors: {errors}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate repository schemas/records, an exact project-scope/rights-matrix pair, "
            "or an exact run, artifact, storage-evidence, and reviewed storage-plan record set. "
            "Validation does not authenticate an approver or pass the project restore gate. "
            "Active-scope checking is stateless and does not prove record truth, consumption, "
            "cumulative spend/duration, or action execution."
        )
    )
    parser.add_argument("--run-manifest", type=Path)
    parser.add_argument("--artifact-manifest", type=Path)
    parser.add_argument("--storage-evidence", type=Path)
    parser.add_argument("--storage-plan", type=Path)
    parser.add_argument("--worker-authorization", type=Path)
    parser.add_argument(
        "--project-release-scope",
        type=Path,
        help="canonical review-ready project/release-scope record",
    )
    parser.add_argument(
        "--rights-matrix",
        type=Path,
        help="canonical review-ready rights-matrix record linked by the project scope",
    )
    parser.add_argument(
        "--at-time",
        help=(
            "RFC 3339 time for active-use worker-authorization evaluation; historical records "
            "remain valid after this window"
        ),
    )
    parser.add_argument("--worker-ref", help="actual worker reference for active-use validation")
    parser.add_argument("--git-commit", help="actual 40-character Git commit for active use")
    parser.add_argument(
        "--action-id",
        action="append",
        dest="action_ids",
        default=[],
        help="requested active action ID; repeat for multiple actions",
    )
    parser.add_argument(
        "--location-access",
        action="append",
        nargs=2,
        metavar=("ACCESS", "LOCATION_REF"),
        dest="location_accesses",
        default=[],
        help=(
            "requested active location access as READ|WRITE|DELETE plus its opaque location "
            "reference; repeat for every access in the action scope"
        ),
    )
    parser.add_argument("--reference-root", type=Path, default=ROOT)
    parser.add_argument("--records-root", type=Path, default=DEFAULT_RECORDS_ROOT)
    return parser


def _run_validation(arguments: argparse.Namespace) -> int:
    format_checker = FormatChecker()
    schemas = _load_schema_registry()
    template_count = _validate_templates(schemas, format_checker=format_checker)
    _assert_calibration_contracts(schemas, format_checker=format_checker)
    _assert_canonical_reference_contract()
    _assert_project_rights_discovery_contract(
        schemas=schemas,
        format_checker=format_checker,
    )
    record_count = _discover_and_validate_governance_records(
        arguments.records_root,
        reference_root=arguments.reference_root,
        schemas=schemas,
        format_checker=format_checker,
    )

    core_paths = (
        arguments.run_manifest,
        arguments.artifact_manifest,
        arguments.storage_evidence,
        arguments.storage_plan,
    )
    if any(path is not None for path in core_paths) and not all(
        path is not None for path in core_paths
    ):
        raise RecordValidationError(
            "--run-manifest, --artifact-manifest, --storage-evidence, and --storage-plan "
            "must be supplied together"
        )
    project_rights_paths = (
        arguments.project_release_scope,
        arguments.rights_matrix,
    )
    if any(path is not None for path in project_rights_paths) and not all(
        path is not None for path in project_rights_paths
    ):
        raise RecordValidationError(
            "--project-release-scope and --rights-matrix must be supplied together"
        )
    if arguments.at_time is not None and arguments.worker_authorization is None:
        raise RecordValidationError("--at-time requires --worker-authorization")
    scope_values_present = any(
        (
            arguments.worker_ref is not None,
            arguments.git_commit is not None,
            bool(arguments.action_ids),
            bool(arguments.location_accesses),
        )
    )
    if scope_values_present and arguments.at_time is None:
        raise RecordValidationError("active scope arguments require --at-time")
    if arguments.at_time is not None and (
        arguments.worker_ref is None or arguments.git_commit is None or not arguments.action_ids
    ):
        raise RecordValidationError(
            "--at-time requires --worker-ref, --git-commit, and at least one --action-id"
        )
    if arguments.git_commit is not None and (
        len(arguments.git_commit) != 40
        or any(character not in "0123456789abcdef" for character in arguments.git_commit)
    ):
        raise RecordValidationError("--git-commit must be 40 lowercase hexadecimal characters")
    normalized_location_accesses: list[tuple[str, str]] = []
    for access, location_ref in arguments.location_accesses:
        normalized_access = access.lower()
        if normalized_access not in {"read", "write", "delete"}:
            raise RecordValidationError("--location-access ACCESS must be READ, WRITE, or DELETE")
        normalized_location_accesses.append((location_ref, normalized_access))
    if (
        arguments.worker_authorization is not None
        and arguments.at_time is None
        and not all(path is not None for path in core_paths)
    ):
        raise RecordValidationError(
            "standalone --worker-authorization evaluation requires --at-time"
        )

    run_validator = Draft202012Validator(
        schemas["run-manifest.schema.json"], format_checker=format_checker
    )
    artifact_validator = Draft202012Validator(
        schemas["artifact-manifest.schema.json"], format_checker=format_checker
    )
    storage_validator = Draft202012Validator(
        schemas["artifact-storage-evidence.schema.json"], format_checker=format_checker
    )
    worker_validator = Draft202012Validator(
        schemas["worker-authorization.schema.json"], format_checker=format_checker
    )

    rights_matrix = _reviewed_rights_matrix()
    rights_matrix_bytes = _canonical_json_bytes(rights_matrix)
    project_scope = _reviewed_project_release_scope(rights_matrix_bytes)
    Draft202012Validator(
        schemas["rights-matrix.schema.json"], format_checker=format_checker
    ).validate(rights_matrix)
    Draft202012Validator(
        schemas["project-release-scope.schema.json"], format_checker=format_checker
    ).validate(project_scope)
    project_rights_errors = (
        project_release_scope_semantic_errors(project_scope)
        + rights_matrix_semantic_errors(rights_matrix)
        + project_rights_cross_field_errors(
            project_scope,
            project_scope_bytes=_canonical_json_bytes(project_scope),
            rights_matrix=rights_matrix,
            rights_matrix_bytes=rights_matrix_bytes,
        )
    )
    if project_rights_errors:
        raise AssertionError(
            f"valid project-scope/rights-matrix fixture failed: {project_rights_errors}"
        )

    changed_rights_bytes = rights_matrix_bytes + b"\n"
    _assert_error_contains(
        project_rights_cross_field_errors(
            project_scope,
            project_scope_bytes=_canonical_json_bytes(project_scope),
            rights_matrix=rights_matrix,
            rights_matrix_bytes=changed_rights_bytes,
        ),
        "SHA-256 does not match raw bytes",
        label="rights-matrix raw-byte mutation",
    )
    mismatched_cutoff = copy.deepcopy(rights_matrix)
    mismatched_cutoff["scope_cutoff"] = "2026-08-26T10:59:59Z"
    _assert_error_contains(
        project_rights_cross_field_errors(
            project_scope,
            project_scope_bytes=_canonical_json_bytes(project_scope),
            rights_matrix=mismatched_cutoff,
            rights_matrix_bytes=_canonical_json_bytes(mismatched_cutoff),
        ),
        "different scope cutoffs",
        label="project/rights scope-cutoff mismatch",
    )
    missing_lane = copy.deepcopy(rights_matrix)
    missing_lane["assets"][0]["intended_lane_ids"] = ["absent-lane"]
    _assert_error_contains(
        project_rights_cross_field_errors(
            project_scope,
            project_scope_bytes=_canonical_json_bytes(project_scope),
            rights_matrix=missing_lane,
            rights_matrix_bytes=_canonical_json_bytes(missing_lane),
        ),
        "references absent release lanes",
        label="rights asset with absent release lane",
    )
    premature_rights_review = copy.deepcopy(rights_matrix)
    premature_rights_review["assets"][0]["reviewed_at"] = "2026-08-26T11:00:30Z"
    _assert_error_contains(
        rights_matrix_semantic_errors(premature_rights_review),
        "reviewed before its terms were observed",
        label="rights review predating observed terms",
    )

    planned = _planned_run()
    run_validator.validate(planned)
    terminal = _terminal_run()
    run_validator.validate(terminal)
    run_bytes = _canonical_json_bytes(terminal)
    artifact_manifest = _artifact_manifest_for_run(run_bytes)
    artifact_validator.validate(artifact_manifest)
    artifact_manifest_bytes = _canonical_json_bytes(artifact_manifest)
    storage_plan = _reviewed_storage_plan()
    Draft202012Validator(
        schemas["artifact-storage-plan.schema.json"], format_checker=format_checker
    ).validate(storage_plan)
    storage_plan_bytes = _canonical_json_bytes(storage_plan)
    plan_errors = artifact_storage_plan_semantic_errors(storage_plan)
    if plan_errors:
        raise AssertionError(f"valid storage-plan fixture failed: {plan_errors}")

    verified_storage = _verified_storage_evidence(
        terminal,
        run_bytes,
        artifact_manifest,
        artifact_manifest_bytes,
        storage_plan,
        storage_plan_bytes,
    )
    storage_validator.validate(verified_storage)
    failed_storage = _failed_storage_evidence()
    storage_validator.validate(failed_storage)
    cross_errors = storage_evidence_cross_field_errors(
        verified_storage,
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )
    if cross_errors:
        raise AssertionError(f"valid storage evidence fixture failed: {cross_errors}")

    worker_authorization = _owner_approved_worker_authorization(
        hashlib.sha256(artifact_manifest_bytes).hexdigest()
    )
    worker_validator.validate(worker_authorization)
    worker_errors = worker_authorization_semantic_errors(worker_authorization)
    if worker_errors:
        raise AssertionError(f"valid worker-authorization fixture failed: {worker_errors}")
    for action_ids, location_accesses in ((["static_checks"], []),):
        scope_errors = active_worker_scope_errors(
            worker_authorization,
            worker_ref="paid-worker-fixture",
            git_commit="0" * 40,
            action_ids=action_ids,
            location_accesses=location_accesses,
        )
        if scope_errors:
            raise AssertionError(f"valid active worker scope fixture failed: {scope_errors}")

    worker_authorization_bytes = _canonical_json_bytes(worker_authorization)
    paid_storage = copy.deepcopy(verified_storage)
    paid_storage["execution_context"]["kind"] = "paid_worker"
    paid_storage["execution_context"]["execution_ref"] = "paid-worker-fixture"
    paid_storage["execution_context"]["cost_evidence"] = {
        "observed_amount": 0.5,
        "currency": "USD",
        "basis": "Schema fixture observation only; not an actual charge.",
        "observed_at": "2026-08-26T12:30:40Z",
        "evidence_ref": "reports/evidence/paid-cost.json",
        "evidence_sha256": ZERO_HASH,
    }
    paid_storage["worker_authorization"] = {
        "record_ref": ("governance/records/worker_authorization/worker-auth-fixture.json"),
        "record_sha256": hashlib.sha256(worker_authorization_bytes).hexdigest(),
        "record_id": worker_authorization["record_id"],
    }
    storage_validator.validate(paid_storage)
    paid_cross_errors = storage_evidence_cross_field_errors(
        paid_storage,
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
        worker_authorization=worker_authorization,
        worker_authorization_bytes=worker_authorization_bytes,
    )
    if paid_cross_errors:
        raise AssertionError(f"valid paid storage fixture failed: {paid_cross_errors}")

    invalid_terminal = copy.deepcopy(terminal)
    invalid_terminal["finished_at"] = None
    _assert_invalid(run_validator, invalid_terminal, "terminal null timestamp")

    post_export_location = copy.deepcopy(terminal)
    post_export_location["artifacts"][0]["locations"] = []
    _assert_invalid(run_validator, post_export_location, "post-export locations in frozen run")

    unsafe_path = copy.deepcopy(terminal)
    unsafe_path["artifacts"][0]["path"] = "../escape"
    _assert_invalid(run_validator, unsafe_path, "artifact traversal")

    dirty_without_diff = copy.deepcopy(planned)
    dirty_without_diff["provenance"]["git"]["dirty"] = True
    _assert_invalid(run_validator, dirty_without_diff, "dirty Git state without diff")

    credential_query = copy.deepcopy(planned)
    credential_query["provenance"]["git"]["repository"] = (
        "https://github.com/laxman-kc/compact-vio-uav.git?token=forbidden"
    )
    _assert_invalid(run_validator, credential_query, "query-bearing repository reference")

    credential_fragment = copy.deepcopy(planned)
    credential_fragment["provenance"]["git"]["repository"] = (
        "https://github.com/laxman-kc/compact-vio-uav.git#forbidden"
    )
    _assert_invalid(run_validator, credential_fragment, "fragment-bearing repository reference")

    credential_userinfo = copy.deepcopy(planned)
    credential_userinfo["provenance"]["git"]["repository"] = (
        "https://user:secret@github.com/laxman-kc/compact-vio-uav.git"
    )
    _assert_invalid(run_validator, credential_userinfo, "userinfo-bearing repository reference")

    for repository in (
        "//user:secret@github.com/laxman-kc/compact-vio-uav.git",
        "user:secret@github.com:laxman-kc/compact-vio-uav.git",
        "user%3Asecret%40github.com/laxman-kc/compact-vio-uav.git",
        "user%253Asecret%2540github.com/laxman-kc/compact-vio-uav.git",
        "https://github.com/repository%253Ftoken=forbidden",
    ):
        alternate_userinfo = copy.deepcopy(planned)
        alternate_userinfo["provenance"]["git"]["repository"] = repository
        _assert_invalid(
            run_validator,
            alternate_userinfo,
            "alternate or encoded userinfo-bearing repository reference",
        )

    sim3_metric_claim = copy.deepcopy(planned)
    sim3_metric_claim["evaluation"]["metric_scale_claim"] = True
    sim3_metric_claim["evaluation"]["primary_alignment"] = "sim3"
    _assert_invalid(run_validator, sim3_metric_claim, "Sim(3) metric-scale claim")

    reversed_run = copy.deepcopy(terminal)
    reversed_run["finished_at"] = "2026-08-26T11:59:59Z"
    _assert_error_contains(
        run_manifest_semantic_errors(reversed_run),
        "run finish predates run start",
        label="reversed run chronology",
    )

    duplicate_run_artifact = copy.deepcopy(terminal)
    second_artifact = copy.deepcopy(duplicate_run_artifact["artifacts"][0])
    second_artifact["sha256"] = "1" * 64
    duplicate_run_artifact["artifacts"].append(second_artifact)
    _assert_error_contains(
        run_manifest_semantic_errors(duplicate_run_artifact),
        "duplicate run artifact_id",
        label="duplicate run artifact identity",
    )
    _assert_error_contains(
        run_manifest_semantic_errors(duplicate_run_artifact),
        "duplicate run artifact paths",
        label="duplicate run artifact path",
    )

    missing_evaluation_artifact = copy.deepcopy(terminal)
    missing_evaluation_artifact["evaluation"]["metrics_artifact_id"] = "absent-metrics"
    _assert_error_contains(
        run_manifest_semantic_errors(missing_evaluation_artifact),
        "references an absent artifact_id",
        label="missing evaluation artifact",
    )

    _assert_invalid(
        artifact_validator,
        {
            "schema_version": 1,
            "hash_algorithm": "sha256",
            "files": [{"path": "directory/", "bytes": 0, "sha256": ZERO_HASH}],
        },
        "non-canonical bundle path",
    )

    duplicate_manifest_path = copy.deepcopy(artifact_manifest)
    duplicate_manifest_record = copy.deepcopy(duplicate_manifest_path["files"][0])
    duplicate_manifest_record["sha256"] = "1" * 64
    duplicate_manifest_path["files"].append(duplicate_manifest_record)
    _assert_error_contains(
        artifact_manifest_semantic_errors(duplicate_manifest_path),
        "duplicate artifact-manifest paths",
        label="duplicate artifact-manifest path",
    )

    self_including_manifest = copy.deepcopy(artifact_manifest)
    self_including_manifest["files"].append(
        {"path": "artifact-manifest.json", "bytes": 1, "sha256": ZERO_HASH}
    )
    self_including_manifest["files"].sort(key=lambda item: item["path"])
    _assert_invalid(
        artifact_validator,
        self_including_manifest,
        "artifact manifest includes itself",
    )
    _assert_error_contains(
        artifact_manifest_semantic_errors(self_including_manifest),
        "must be self-excluded",
        label="artifact manifest self-inventory",
    )

    try:
        _decode_json_object(b'{"overflow":1e9999}', path=Path("overflow.json"))
    except RecordValidationError:
        pass
    else:
        raise AssertionError("raw JSON decoder accepted a non-finite exponent result")

    bad_capacity = copy.deepcopy(storage_plan)
    bad_capacity["capacity_envelope"]["total_required_bytes"] += 1
    _assert_error_contains(
        artifact_storage_plan_semantic_errors(bad_capacity),
        "must equal worst_case_retained_bytes plus reserve_bytes",
        label="storage capacity arithmetic",
    )

    impossible_teardown = copy.deepcopy(storage_plan)
    impossible_teardown["transfer_plan"]["expected_teardown_transfer_seconds"] = 10.0
    _assert_error_contains(
        artifact_storage_plan_semantic_errors(impossible_teardown),
        "below bytes divided by measured throughput",
        label="storage teardown throughput lower bound",
    )

    future_storage_observation = copy.deepcopy(storage_plan)
    future_storage_observation["primary_vault"]["observed_at"] = "2026-08-26T12:21:00Z"
    _assert_error_contains(
        artifact_storage_plan_semantic_errors(future_storage_observation),
        "storage observation follows plan preparation",
        label="future-dated storage observation",
    )

    future_independence_review = copy.deepcopy(storage_plan)
    future_independence_review["independence_review"]["reviewed_at"] = "2026-08-26T12:21:00Z"
    _assert_error_contains(
        artifact_storage_plan_semantic_errors(future_independence_review),
        "independence review follows plan preparation",
        label="future-dated independence review",
    )
    premature_independence_review = copy.deepcopy(storage_plan)
    premature_independence_review["independence_review"]["reviewed_at"] = "2026-08-26T12:09:59Z"
    _assert_error_contains(
        artifact_storage_plan_semantic_errors(premature_independence_review),
        "independence review predates a storage-candidate observation",
        label="independence review predating candidate observations",
    )
    oversized_teardown = copy.deepcopy(storage_plan)
    oversized_teardown["transfer_plan"]["expected_teardown_transfer_seconds"] = 10**1000
    try:
        artifact_storage_plan_semantic_errors(oversized_teardown)
    except RecordValidationError as exc:
        if "outside the supported duration range" not in str(exc):
            raise AssertionError(
                f"oversized teardown duration failed for the wrong reason: {exc}"
            ) from exc
    else:
        raise AssertionError("oversized teardown duration did not fail deterministically")

    incoherent_worker_time = copy.deepcopy(worker_authorization)
    incoherent_worker_time["review_at"] = "2026-08-26T12:04:00Z"
    _assert_error_contains(
        worker_authorization_semantic_errors(incoherent_worker_time),
        "approval must precede review_at",
        label="worker authorization chronology",
    )
    _assert_error_contains(
        worker_authorization_semantic_errors(
            worker_authorization,
            at_time=_date_time("2026-08-26T12:35:00Z"),
            require_active=True,
        ),
        "authorization is not active",
        label="worker authorization review deadline",
    )
    oversized_worker_duration = copy.deepcopy(worker_authorization)
    oversized_worker_duration["expected_duration_minutes"] = 10**1000
    try:
        worker_authorization_semantic_errors(oversized_worker_duration)
    except RecordValidationError as exc:
        if "outside the supported duration range" not in str(exc):
            raise AssertionError(
                f"oversized worker duration failed for the wrong reason: {exc}"
            ) from exc
    else:
        raise AssertionError("oversized worker duration did not fail deterministically")

    out_of_scope_worker = active_worker_scope_errors(
        worker_authorization,
        worker_ref="different-worker",
        git_commit="0" * 40,
        action_ids=["training"],
        location_accesses=[("unlisted-location", "write")],
    )
    for expected in ("worker_ref", "action IDs", "location references"):
        _assert_error_contains(
            out_of_scope_worker,
            expected,
            label="out-of-scope active worker request",
        )

    cross_product_location = active_worker_scope_errors(
        worker_authorization,
        worker_ref="paid-worker-fixture",
        git_commit="0" * 40,
        action_ids=["write_primary_restore_test_copy"],
        location_accesses=[("backup-candidate", "write")],
    )
    _assert_error_contains(
        cross_product_location,
        "do not exactly match action scope",
        label="action/location Cartesian-product bypass",
    )

    retained_copy_delete_bypass = copy.deepcopy(worker_authorization)
    retained_copy_delete_bypass["action_scopes"][1]["location_accesses"] = [
        {"location_ref": "vault-candidate", "access": "delete"}
    ]
    worker_validator.validate(retained_copy_delete_bypass)
    _assert_error_contains(
        worker_authorization_semantic_errors(retained_copy_delete_bypass),
        "delete access is forbidden",
        label="retained-copy delete hidden under write action",
    )
    _assert_error_contains(
        active_worker_scope_errors(
            retained_copy_delete_bypass,
            worker_ref="paid-worker-fixture",
            git_commit="0" * 40,
            action_ids=["write_primary_restore_test_copy"],
            location_accesses=[("vault-candidate", "delete")],
        ),
        "delete access is forbidden",
        label="active retained-copy delete hidden under write action",
    )
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=retained_copy_delete_bypass,
            worker_authorization_bytes=_canonical_json_bytes(retained_copy_delete_bypass),
        ),
        "delete access is forbidden",
        label="historical retained-copy delete hidden under write action",
    )

    inverted_restore_request = active_worker_scope_errors(
        worker_authorization,
        worker_ref="paid-worker-fixture",
        git_commit="0" * 40,
        action_ids=["representative_restore"],
        location_accesses=[
            ("backup-candidate", "write"),
            ("new-restore-destination", "read"),
        ],
    )
    _assert_error_contains(
        inverted_restore_request,
        "do not exactly match action scope",
        label="restore source/destination access inversion",
    )
    inverted_historical_restore = copy.deepcopy(worker_authorization)
    inverted_historical_restore["action_scopes"][5]["location_accesses"] = [
        {"location_ref": "backup-candidate", "access": "write"},
        {"location_ref": "new-restore-destination", "access": "read"},
    ]
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=inverted_historical_restore,
            worker_authorization_bytes=_canonical_json_bytes(inverted_historical_restore),
        ),
        "does not match the performed drill location accesses",
        label="historical restore source/destination access inversion",
    )

    wrong_deletion_location = active_worker_scope_errors(
        worker_authorization,
        worker_ref="paid-worker-fixture",
        git_commit="0" * 40,
        action_ids=["disposable_source_copy_delete"],
        location_accesses=[("vault-candidate", "delete")],
    )
    _assert_error_contains(
        wrong_deletion_location,
        "standalone deletion validation is unavailable",
        label="deletion requested without pre-delete copy evidence",
    )
    _assert_error_contains(
        wrong_deletion_location,
        "delete access to its authorized source location",
        label="retained location requested for disposable deletion",
    )

    mismatched_historical_action_scope = copy.deepcopy(worker_authorization)
    mismatched_historical_action_scope["action_scopes"][1]["location_accesses"] = [
        {"location_ref": "backup-candidate", "access": "write"}
    ]
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=mismatched_historical_action_scope,
            worker_authorization_bytes=_canonical_json_bytes(mismatched_historical_action_scope),
        ),
        "does not match the performed drill location accesses",
        label="historical action/location scope mismatch",
    )

    missing_backup = copy.deepcopy(verified_storage)
    missing_backup["copies"] = missing_backup["copies"][:1]
    _assert_invalid(storage_validator, missing_backup, "verified drill without backup")

    worker_termination = copy.deepcopy(verified_storage)
    worker_termination["source_test_copy_deletion"]["worker_termination"] = True
    _assert_invalid(storage_validator, worker_termination, "worker termination as test deletion")

    gate_claim = copy.deepcopy(verified_storage)
    gate_claim["artifact_restore_gate_passed"] = True
    _assert_invalid(storage_validator, gate_claim, "sidecar passing project gate")

    no_review = copy.deepcopy(verified_storage)
    no_review["storage_review"] = None
    _assert_invalid(storage_validator, no_review, "verified drill without storage review")

    not_representative = copy.deepcopy(verified_storage)
    not_representative["bundle_identity"]["representative_for_phase"] = False
    _assert_invalid(
        storage_validator,
        not_representative,
        "verified drill without representative-bundle assertion",
    )

    inconsistent_failure = copy.deepcopy(failed_storage)
    inconsistent_failure["assessment"]["result"] = "verified"
    _assert_invalid(storage_validator, inconsistent_failure, "failed drill verified assessment")

    failed_paid_without_authorization = copy.deepcopy(failed_storage)
    failed_paid_without_authorization["execution_context"] = copy.deepcopy(
        paid_storage["execution_context"]
    )
    _assert_invalid(
        storage_validator,
        failed_paid_without_authorization,
        "failed paid drill without historical worker authorization",
    )

    template_review = copy.deepcopy(verified_storage)
    template_review["storage_review"]["review_record_ref"] = (
        "governance/records/templates/artifact-storage-plan.template.json"
    )
    _assert_invalid(storage_validator, template_review, "template storage-review reference")

    paid_without_authorization = copy.deepcopy(paid_storage)
    paid_without_authorization["worker_authorization"] = None
    _assert_invalid(
        storage_validator,
        paid_without_authorization,
        "paid drill without worker-authorization link",
    )

    paid_without_cost_evidence = copy.deepcopy(paid_storage)
    paid_without_cost_evidence["execution_context"]["cost_evidence"] = None
    _assert_invalid(
        storage_validator,
        paid_without_cost_evidence,
        "paid drill without cost evidence",
    )

    non_paid_with_authorization = copy.deepcopy(verified_storage)
    non_paid_with_authorization["worker_authorization"] = paid_storage["worker_authorization"]
    _assert_invalid(
        storage_validator,
        non_paid_with_authorization,
        "non-paid drill with worker-authorization link",
    )

    non_paid_with_cost_evidence = copy.deepcopy(verified_storage)
    non_paid_with_cost_evidence["execution_context"]["cost_evidence"] = paid_storage[
        "execution_context"
    ]["cost_evidence"]
    _assert_invalid(
        storage_validator,
        non_paid_with_cost_evidence,
        "non-paid drill with paid cost evidence",
    )

    for unsafe_execution_ref in (
        "//user:secret@host/path",
        "user:secret@host:path",
        "ssh:user:secret@host/path",
        "//user%3Asecret@host/path",
    ):
        unsafe_execution_context = copy.deepcopy(verified_storage)
        unsafe_execution_context["execution_context"]["execution_ref"] = unsafe_execution_ref
        _assert_invalid(
            storage_validator,
            unsafe_execution_context,
            f"credential-bearing execution reference {unsafe_execution_ref!r}",
        )

    wrong_identity = copy.deepcopy(verified_storage)
    wrong_identity["bundle_identity"]["run_manifest_sha256"] = ZERO_HASH
    _assert_cross_invalid(
        wrong_identity,
        label="wrong raw run-manifest identity",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    run_object_not_raw_bytes = copy.deepcopy(terminal)
    run_object_not_raw_bytes["purpose"] = "Different semantic object with unchanged raw bytes."
    _assert_cross_invalid(
        verified_storage,
        label="validated run object differs from hashed raw run bytes",
        run=run_object_not_raw_bytes,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    duplicate_location = copy.deepcopy(verified_storage)
    duplicate_location["copies"][1]["location_ref"] = duplicate_location["copies"][0][
        "location_ref"
    ]
    _assert_cross_invalid(
        duplicate_location,
        label="same primary and backup location reference",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    retained_copy_deleted = copy.deepcopy(verified_storage)
    retained_copy_deleted["source_test_copy_deletion"]["source_copy_ref"] = "vault-candidate"
    _assert_cross_invalid(
        retained_copy_deleted,
        label="retained primary location named as disposable source copy",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    early_deletion = copy.deepcopy(verified_storage)
    early_deletion["source_test_copy_deletion"]["deleted_at"] = "2026-08-26T12:30:00Z"
    _assert_cross_invalid(
        early_deletion,
        label="source test copy deleted before copy verification",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    deletion_at_verification = copy.deepcopy(verified_storage)
    deletion_at_verification["source_test_copy_deletion"]["deleted_at"] = "2026-08-26T12:30:23Z"
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            deletion_at_verification,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
        ),
        "deletion must strictly follow copy verification",
        label="deletion timestamp equal to final copy verification",
    )

    absence_at_deletion = copy.deepcopy(verified_storage)
    absence_at_deletion["source_test_copy_deletion"]["absence_verified_at"] = absence_at_deletion[
        "source_test_copy_deletion"
    ]["deleted_at"]
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            absence_at_deletion,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
        ),
        "absence verification must strictly follow deletion",
        label="absence verification timestamp equal to deletion",
    )

    restore_at_absence = copy.deepcopy(verified_storage)
    restore_at_absence["restore"]["restore_started_at"] = restore_at_absence[
        "source_test_copy_deletion"
    ]["absence_verified_at"]
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            restore_at_absence,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
        ),
        "restore must start strictly after",
        label="restore timestamp equal to absence verification",
    )

    load_at_restore_verification = copy.deepcopy(verified_storage)
    load_at_restore_verification["load_open"]["started_at"] = load_at_restore_verification[
        "restore"
    ]["verification"]["verified_at"]
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            load_at_restore_verification,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
        ),
        "load/open check must start strictly after",
        label="load/open timestamp equal to restore verification",
    )

    review_at_load_finish = copy.deepcopy(verified_storage)
    review_at_load_finish["storage_review"]["assessed_at"] = review_at_load_finish["load_open"][
        "finished_at"
    ]
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            review_at_load_finish,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
        ),
        "review must occur strictly after",
        label="storage review timestamp equal to load/open completion",
    )

    assessment_at_review = copy.deepcopy(verified_storage)
    assessment_at_review["assessment"]["assessed_at"] = assessment_at_review["storage_review"][
        "assessed_at"
    ]
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            assessment_at_review,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
        ),
        "assessment must occur strictly after",
        label="final assessment timestamp equal to storage review",
    )

    reused_restore_destination = copy.deepcopy(verified_storage)
    reused_restore_destination["restore"]["destination_ref"] = "vault-candidate"
    _assert_cross_invalid(
        reused_restore_destination,
        label="restore not placed in a new location",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    incomplete_restore = copy.deepcopy(verified_storage)
    incomplete_restore["restore"]["verification"]["payload_files_verified"] -= 1
    _assert_cross_invalid(
        incomplete_restore,
        label="restore does not verify every file",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    wrong_bundle_accounting = copy.deepcopy(verified_storage)
    wrong_bundle_accounting["bundle_identity"]["bundle_bytes"] -= 1
    _assert_cross_invalid(
        wrong_bundle_accounting,
        label="bundle bytes omit part of the physical bundle",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    bad_throughput = copy.deepcopy(verified_storage)
    bad_throughput["copies"][0]["throughput_bytes_per_second"] += 1
    _assert_cross_invalid(
        bad_throughput,
        label="copy throughput mismatch",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    missing_load_artifact = copy.deepcopy(verified_storage)
    missing_load_artifact["load_open"]["artifact_path"] = "reports/not-present.json"
    _assert_cross_invalid(
        missing_load_artifact,
        label="load/open target absent from bundle",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    wrong_plan_hash = copy.deepcopy(verified_storage)
    wrong_plan_hash["storage_review"]["review_record_sha256"] = ZERO_HASH
    _assert_cross_invalid(
        wrong_plan_hash,
        label="wrong reviewed storage-plan hash",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    wrong_storage_candidate = copy.deepcopy(verified_storage)
    wrong_storage_candidate["copies"][0]["storage_candidate_id"] = "wrong-candidate"
    _assert_cross_invalid(
        wrong_storage_candidate,
        label="copy candidate differs from reviewed plan",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    early_execution = copy.deepcopy(verified_storage)
    early_execution["execution_context"]["started_at"] = "2026-08-26T12:29:59Z"
    _assert_cross_invalid(
        early_execution,
        label="storage execution begins before terminal run",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    expired_capacity_plan = copy.deepcopy(storage_plan)
    expired_capacity_plan["capacity_envelope"]["valid_until"] = "2026-08-26T12:30:30Z"
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            verified_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=expired_capacity_plan,
            storage_plan_bytes=_canonical_json_bytes(expired_capacity_plan),
        ),
        "outlasts the storage-capacity validity window",
        label="drill outlasts capacity evidence",
    )

    expired_cost_plan = copy.deepcopy(storage_plan)
    expired_cost_plan["cost_envelope"]["review_at"] = "2026-08-26T12:30:30Z"
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            verified_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=expired_cost_plan,
            storage_plan_bytes=_canonical_json_bytes(expired_cost_plan),
        ),
        "outlasts the storage-cost review window",
        label="drill outlasts cost evidence",
    )

    expired_retention_plan = copy.deepcopy(storage_plan)
    expired_retention_plan["retention_rules"]["disposable"]["review_at"] = "2026-08-26T12:30:30Z"
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            verified_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=expired_retention_plan,
            storage_plan_bytes=_canonical_json_bytes(expired_retention_plan),
        ),
        "disposable retention review window",
        label="drill outlasts retention review evidence",
    )

    duplicate_supporting_path = copy.deepcopy(verified_storage)
    duplicate_supporting_path["supporting_evidence"].append(
        {
            "kind": "other",
            "path": duplicate_supporting_path["supporting_evidence"][0]["path"],
            "sha256": "1" * 64,
        }
    )
    _assert_cross_invalid(
        duplicate_supporting_path,
        label="duplicate supporting-evidence paths",
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=storage_plan,
        storage_plan_bytes=storage_plan_bytes,
    )

    readme_bytes = _read_exact_regular_file(ROOT / "README.md")
    reference_errors: list[str] = []
    referenced_bytes = _verify_hashed_evidence_reference(
        reference_errors,
        reference_root=ROOT,
        reference="README.md",
        expected_sha256=hashlib.sha256(readme_bytes).hexdigest(),
        label="hashed evidence fixture",
    )
    if reference_errors or referenced_bytes != readme_bytes:
        raise AssertionError(f"valid hashed-evidence fixture failed: {reference_errors}")
    wrong_reference_errors: list[str] = []
    _verify_hashed_evidence_reference(
        wrong_reference_errors,
        reference_root=ROOT,
        reference="README.md",
        expected_sha256=ZERO_HASH,
        label="hashed evidence fixture",
    )
    _assert_error_contains(
        wrong_reference_errors,
        "SHA-256 does not match",
        label="supporting-evidence raw-byte hash",
    )

    copy_audit_fixture = _copy_audit_fixture(verified_storage)
    copy_audit_bytes = _canonical_json_bytes(copy_audit_fixture)
    copy_audit_errors = _copy_audit_payload_errors(
        copy_audit_bytes,
        identity=verified_storage["bundle_identity"],
        copy_locations={
            copy_record["role"]: copy_record["location_ref"]
            for copy_record in verified_storage["copies"]
        },
        earliest_valid_observation=_date_time("2026-08-26T12:30:23Z"),
        latest_valid_observation=_date_time("2026-08-26T12:30:24Z"),
        label="copy-audit fixture",
    )
    if copy_audit_errors:
        raise AssertionError(f"valid copy-audit payload failed: {copy_audit_errors}")
    copy_audit_at_deletion = copy.deepcopy(copy_audit_fixture)
    copy_audit_at_deletion["observed_at"] = "2026-08-26T12:30:24Z"
    _assert_error_contains(
        _copy_audit_payload_errors(
            _canonical_json_bytes(copy_audit_at_deletion),
            identity=verified_storage["bundle_identity"],
            copy_locations={
                copy_record["role"]: copy_record["location_ref"]
                for copy_record in verified_storage["copies"]
            },
            earliest_valid_observation=_date_time("2026-08-26T12:30:23Z"),
            latest_valid_observation=_date_time("2026-08-26T12:30:24Z"),
            label="copy-audit fixture",
        ),
        "does not strictly precede deletion",
        label="copy-audit timestamp equal to source-copy deletion",
    )
    false_copy_audit = copy.deepcopy(copy_audit_fixture)
    false_copy_audit["content_identity_verified"] = False
    _assert_error_contains(
        _copy_audit_payload_errors(
            _canonical_json_bytes(false_copy_audit),
            identity=verified_storage["bundle_identity"],
            copy_locations={
                copy_record["role"]: copy_record["location_ref"]
                for copy_record in verified_storage["copies"]
            },
            earliest_valid_observation=_date_time("2026-08-26T12:30:23Z"),
            latest_valid_observation=_date_time("2026-08-26T12:30:24Z"),
            label="copy-audit fixture",
        ),
        "content_identity_verified",
        label="copy-audit content verification claim",
    )
    unrelated_copy_audit = copy.deepcopy(copy_audit_fixture)
    unrelated_copy_audit["primary"]["copy_ref"] = "unrelated-primary"
    _assert_error_contains(
        _copy_audit_payload_errors(
            _canonical_json_bytes(unrelated_copy_audit),
            identity=verified_storage["bundle_identity"],
            copy_locations={
                copy_record["role"]: copy_record["location_ref"]
                for copy_record in verified_storage["copies"]
            },
            earliest_valid_observation=_date_time("2026-08-26T12:30:23Z"),
            latest_valid_observation=_date_time("2026-08-26T12:30:24Z"),
            label="copy-audit fixture",
        ),
        "copy_ref does not match",
        label="copy-audit opaque reference linkage",
    )
    path_leaking_copy_audit = copy.deepcopy(copy_audit_fixture)
    path_leaking_copy_audit["private_path"] = "/Users/example/private-vault"
    _assert_error_contains(
        _copy_audit_payload_errors(
            _canonical_json_bytes(path_leaking_copy_audit),
            identity=verified_storage["bundle_identity"],
            copy_locations={
                copy_record["role"]: copy_record["location_ref"]
                for copy_record in verified_storage["copies"]
            },
            earliest_valid_observation=_date_time("2026-08-26T12:30:23Z"),
            latest_valid_observation=_date_time("2026-08-26T12:30:24Z"),
            label="copy-audit fixture",
        ),
        "unknown top-level fields",
        label="copy-audit private-path extension",
    )

    post_m2_authorization = copy.deepcopy(worker_authorization)
    post_m2_authorization["authorization_kind"] = "post_m2_paid_work"
    post_m2_authorization["restore_gate_evidence_ref"] = (
        "governance/records/evidence/m2-owner-acceptance.json"
    )
    _assert_invalid(
        worker_validator,
        post_m2_authorization,
        "owner-approved post-M2 authorization in v1",
    )
    _assert_error_contains(
        active_worker_scope_errors(
            post_m2_authorization,
            worker_ref="paid-worker-fixture",
            git_commit="0" * 40,
            action_ids=["representative_restore"],
            location_accesses=[("new-restore-destination", "write")],
        ),
        "post-M2 active-use validation is unavailable",
        label="post-M2 work without canonical gate acceptance and use ledger",
    )
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=post_m2_authorization,
            worker_authorization_bytes=_canonical_json_bytes(post_m2_authorization),
        ),
        "requires an m2_evidence_gathering authorization",
        label="post-M2 authority used for M2 drill",
    )

    overlong_paid_storage = copy.deepcopy(paid_storage)
    overlong_paid_storage["execution_context"]["finished_at"] = "2026-08-26T12:31:01Z"
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            overlong_paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=worker_authorization,
            worker_authorization_bytes=worker_authorization_bytes,
        ),
        "duration exceeds the approved duration",
        label="paid drill longer than approved duration",
    )

    over_budget_paid_storage = copy.deepcopy(paid_storage)
    over_budget_paid_storage["execution_context"]["cost_evidence"]["observed_amount"] = 1.01
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            over_budget_paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=worker_authorization,
            worker_authorization_bytes=worker_authorization_bytes,
        ),
        "exceeds the approved spending ceiling",
        label="paid drill exceeds approved spend",
    )

    wrong_currency_paid_storage = copy.deepcopy(paid_storage)
    wrong_currency_paid_storage["execution_context"]["cost_evidence"]["currency"] = "CAD"
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            wrong_currency_paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=worker_authorization,
            worker_authorization_bytes=worker_authorization_bytes,
        ),
        "currency differs from the ceiling",
        label="paid drill cost currency mismatch",
    )

    low_plan_ceiling = copy.deepcopy(storage_plan)
    low_plan_ceiling["cost_envelope"]["worker_spend_ceiling"] = 0.25
    low_plan_errors = storage_evidence_cross_field_errors(
        paid_storage,
        run=terminal,
        run_bytes=run_bytes,
        artifact_manifest=artifact_manifest,
        artifact_manifest_bytes=artifact_manifest_bytes,
        storage_plan=low_plan_ceiling,
        storage_plan_bytes=_canonical_json_bytes(low_plan_ceiling),
        worker_authorization=worker_authorization,
        worker_authorization_bytes=worker_authorization_bytes,
    )
    _assert_error_contains(
        low_plan_errors,
        "authorization ceiling exceeds the storage-plan worker ceiling",
        label="authorization exceeds storage-plan worker ceiling",
    )
    _assert_error_contains(
        low_plan_errors,
        "observed cost exceeds the storage-plan ceiling",
        label="observed spend exceeds storage-plan worker ceiling",
    )

    mismatched_plan_currency = copy.deepcopy(storage_plan)
    mismatched_plan_currency["cost_envelope"]["currency"] = "CAD"
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            paid_storage,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=mismatched_plan_currency,
            storage_plan_bytes=_canonical_json_bytes(mismatched_plan_currency),
            worker_authorization=worker_authorization,
            worker_authorization_bytes=worker_authorization_bytes,
        ),
        "authorization currency differs from the storage-plan currency",
        label="authorization and storage-plan currency mismatch",
    )

    premature_cost_observation = copy.deepcopy(paid_storage)
    premature_cost_observation["execution_context"]["cost_evidence"]["observed_at"] = (
        "2026-08-26T12:30:38Z"
    )
    _assert_error_contains(
        storage_evidence_cross_field_errors(
            premature_cost_observation,
            run=terminal,
            run_bytes=run_bytes,
            artifact_manifest=artifact_manifest,
            artifact_manifest_bytes=artifact_manifest_bytes,
            storage_plan=storage_plan,
            storage_plan_bytes=storage_plan_bytes,
            worker_authorization=worker_authorization,
            worker_authorization_bytes=worker_authorization_bytes,
        ),
        "cost was observed before execution finished",
        label="premature paid cost observation",
    )

    paid_cost_reference_errors: list[str] = []
    _verify_hashed_evidence_reference(
        paid_cost_reference_errors,
        reference_root=ROOT,
        reference="README.md",
        expected_sha256=ZERO_HASH,
        label="paid-worker cost evidence",
    )
    _assert_error_contains(
        paid_cost_reference_errors,
        "paid-worker cost evidence SHA-256 does not match",
        label="paid cost evidence raw-byte hash",
    )

    arbitrary_authority_path_errors = _canonical_record_path_errors(
        ROOT / "worker-auth-fixture.json",
        records_root=DEFAULT_RECORDS_ROOT,
        record=worker_authorization,
    )
    _assert_error_contains(
        arbitrary_authority_path_errors,
        "outside the configured records root",
        label="worker authority outside canonical records root",
    )
    wrong_suffix_authority_errors = _canonical_record_path_errors(
        DEFAULT_RECORDS_ROOT / "worker_authorization" / "worker-auth-fixture.txt",
        records_root=DEFAULT_RECORDS_ROOT,
        record=worker_authorization,
    )
    _assert_error_contains(
        wrong_suffix_authority_errors,
        "plus .json",
        label="worker authority with non-JSON filename suffix",
    )

    project_rights_record_set_valid = False
    if all(path is not None for path in project_rights_paths):
        assert arguments.project_release_scope is not None
        assert arguments.rights_matrix is not None
        _validate_project_rights_records(
            arguments.project_release_scope,
            arguments.rights_matrix,
            reference_root=arguments.reference_root,
            records_root=arguments.records_root,
            schemas=schemas,
            format_checker=format_checker,
        )
        project_rights_record_set_valid = True

    evidence_record_set_valid = False
    if all(path is not None for path in core_paths):
        assert arguments.run_manifest is not None
        assert arguments.artifact_manifest is not None
        assert arguments.storage_evidence is not None
        assert arguments.storage_plan is not None
        _validate_real_storage_evidence(
            run_path=arguments.run_manifest,
            artifact_manifest_path=arguments.artifact_manifest,
            storage_evidence_path=arguments.storage_evidence,
            storage_plan_path=arguments.storage_plan,
            worker_authorization_path=arguments.worker_authorization,
            reference_root=arguments.reference_root,
            records_root=arguments.records_root,
            schemas=schemas,
            format_checker=format_checker,
        )
        evidence_record_set_valid = True

    active_scope_record_valid = False
    if arguments.worker_authorization is not None and arguments.at_time is not None:
        worker_record, _ = _validate_worker_authorization_file(
            arguments.worker_authorization,
            records_root=arguments.records_root,
            schemas=schemas,
            format_checker=format_checker,
            at_time=_parse_at_time(arguments.at_time),
            require_active=True,
        )
        assert arguments.worker_ref is not None
        assert arguments.git_commit is not None
        scope_errors = active_worker_scope_errors(
            worker_record,
            worker_ref=arguments.worker_ref,
            git_commit=arguments.git_commit,
            action_ids=arguments.action_ids,
            location_accesses=normalized_location_accesses,
        )
        if scope_errors:
            raise RecordValidationError(f"active worker scope errors: {scope_errors}")
        active_scope_record_valid = True

    print(
        "Validation: PASS "
        f"({len(schemas)} schemas, {template_count} templates, "
        f"{record_count} real governance records, "
        f"project_rights_record_set_valid="
        f"{str(project_rights_record_set_valid).lower()}, "
        f"evidence_record_set_valid={str(evidence_record_set_valid).lower()}, "
        f"active_scope_record_valid={str(active_scope_record_valid).lower()}, "
        "record_truth_verified=false, approval_identity_authenticated=false, "
        "active_use_ledger_verified=false, cumulative_spend_duration_verified=false, "
        "action_execution_verified=false, artifact_restore_gate_passed=false)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        return _run_validation(arguments)
    except (RecordValidationError, OSError, OverflowError, ValueError) as exc:
        print(f"validation error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

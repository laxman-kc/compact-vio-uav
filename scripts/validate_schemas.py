"""Validate project JSON Schemas and their security-critical contract cases."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:  # pragma: no cover - exercised by CI with dependency installed.
    raise SystemExit(
        "jsonschema with format support is required; install jsonschema[format-nongpl]==4.26.0"
    ) from exc


ROOT = Path(__file__).resolve().parents[1]
RUN_SCHEMA_PATH = ROOT / "experiments/schemas/run-manifest.schema.json"
ARTIFACT_SCHEMA_PATH = ROOT / "experiments/schemas/artifact-manifest.schema.json"
ZERO_HASH = "0" * 64


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise AssertionError(f"schema root is not an object: {path}")
    return value


def _planned_run() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
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
            "hardware": {
                "platform_role": "simulation",
                "summary": "schema fixture",
            },
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
        "locations": [
            {
                "role": "primary_vault",
                "uri": "file:///vault/schema-fixture.json",
                "verification_status": "checksum_verified",
                "verified_at": "2026-08-26T12:10:00Z",
                "verified_sha256": ZERO_HASH,
            },
            {
                "role": "independent_backup",
                "uri": "file:///backup/schema-fixture.json",
                "verification_status": "restore_verified",
                "verified_at": "2026-08-26T12:20:00Z",
                "verified_sha256": ZERO_HASH,
            },
        ],
    }


def _assert_invalid(validator: Draft202012Validator, value: object, label: str) -> None:
    if not list(validator.iter_errors(value)):
        raise AssertionError(f"schema accepted forbidden fixture: {label}")


def main() -> int:
    run_schema = _load(RUN_SCHEMA_PATH)
    artifact_schema = _load(ARTIFACT_SCHEMA_PATH)
    Draft202012Validator.check_schema(run_schema)
    Draft202012Validator.check_schema(artifact_schema)
    format_checker = FormatChecker()
    run_validator = Draft202012Validator(run_schema, format_checker=format_checker)
    artifact_validator = Draft202012Validator(artifact_schema, format_checker=format_checker)

    planned = _planned_run()
    run_validator.validate(planned)
    terminal = copy.deepcopy(planned)
    terminal.update(
        {
            "status": "succeeded",
            "started_at": "2026-08-26T12:00:00Z",
            "finished_at": "2026-08-26T12:30:00Z",
            "outcome": {"summary": "Schema fixture only.", "failure_category": "none"},
            "artifacts": [_critical_artifact()],
        }
    )
    run_validator.validate(terminal)
    artifact_validator.validate(
        {
            "schema_version": 1,
            "hash_algorithm": "sha256",
            "files": [{"path": "run-manifest.json", "bytes": 1, "sha256": ZERO_HASH}],
        }
    )

    invalid_terminal = copy.deepcopy(terminal)
    invalid_terminal["finished_at"] = None
    _assert_invalid(run_validator, invalid_terminal, "terminal null timestamp")

    missing_backup = copy.deepcopy(terminal)
    missing_backup["artifacts"][0]["locations"] = []
    _assert_invalid(run_validator, missing_backup, "critical artifact without copies")

    missing_verification = copy.deepcopy(terminal)
    del missing_verification["artifacts"][0]["locations"][0]["verified_sha256"]
    _assert_invalid(run_validator, missing_verification, "verification without hash")

    unsafe_path = copy.deepcopy(terminal)
    unsafe_path["artifacts"][0]["path"] = "../escape"
    _assert_invalid(run_validator, unsafe_path, "artifact traversal")

    credential_uri = copy.deepcopy(terminal)
    credential_uri["artifacts"][0]["locations"][0]["uri"] = (
        "https://user:secret@example.com/artifact"
    )
    _assert_invalid(run_validator, credential_uri, "credential-bearing URI")

    dirty_without_diff = copy.deepcopy(planned)
    dirty_without_diff["provenance"]["git"]["dirty"] = True
    _assert_invalid(run_validator, dirty_without_diff, "dirty Git state without diff")

    sim3_metric_claim = copy.deepcopy(planned)
    sim3_metric_claim["evaluation"]["metric_scale_claim"] = True
    sim3_metric_claim["evaluation"]["primary_alignment"] = "sim3"
    _assert_invalid(run_validator, sim3_metric_claim, "Sim(3) metric-scale claim")

    _assert_invalid(
        artifact_validator,
        {
            "schema_version": 1,
            "hash_algorithm": "sha256",
            "files": [{"path": "directory/", "bytes": 0, "sha256": ZERO_HASH}],
        },
        "non-canonical bundle path",
    )
    print("JSON Schema validation: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())

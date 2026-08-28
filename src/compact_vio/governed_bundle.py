"""Read-only validation of one frozen governed training-run bundle.

The trainer's original output bundle remains nested and independently
verifiable.  A governed wrapper adds a schema-valid run manifest, an exact
resolved configuration, an execution-environment projection, and a new outer
artifact manifest.  This module validates those bindings without rewriting any
file and without making storage, restoration, or scientific-acceptance claims.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compact_vio.artifacts import (
    ArtifactError,
    ArtifactManifest,
    FileRecord,
    load_manifest,
    read_manifest_bytes,
    verify_bundle,
)
from compact_vio.learning.errors import LearningError

RUN_MANIFEST_PATH = "run-manifest.json"
ARTIFACT_MANIFEST_PATH = "artifact-manifest.json"
RESOLVED_CONFIG_PATH = "resolved-config.json"
ENVIRONMENT_PATH = "environment.json"
EVALUATION_CONFIG_PATH = "provenance/evaluation-config.json"
TRAINER_OUTPUT_DIRECTORY = "trainer-output"
TRAINER_SUMMARY_PATH = f"{TRAINER_OUTPUT_DIRECTORY}/run-summary.json"
TRAINER_MANIFEST_PATH = f"{TRAINER_OUTPUT_DIRECTORY}/artifact-manifest.json"
EXPECTED_TRAINER_PAYLOAD_PATHS = frozenset(
    {
        "checkpoint.pt",
        "run-summary.json",
        "test-metrics.json",
        "test-predictions.jsonl",
        "training-history.json",
    }
)

_RUN_SCHEMA_NAME = "run-manifest.schema.json"
_ARTIFACT_SCHEMA_NAME = "artifact-manifest.schema.json"
_MAX_JSON_BYTES = 64 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024


class GovernedBundleError(Exception):
    """Raised when a governed bundle is unsafe, incomplete, or inconsistent."""


@dataclass(frozen=True, slots=True)
class GovernedBundleReport:
    """Verified immutable identities for one governed wrapper."""

    bundle: Path
    run_id: str
    run_manifest_sha256: str
    artifact_manifest_sha256: str
    payload_file_count: int
    payload_bytes: int
    declared_artifact_count: int
    trainer_manifest_sha256: str
    trainer_payload_file_count: int
    resolved_config_sha256: str
    evaluation_config_sha256: str
    environment_sha256: str

    def to_dict(self) -> dict[str, object]:
        """Return the stable CLI projection of the successful validation."""

        return {
            "artifact_manifest_sha256": self.artifact_manifest_sha256,
            "bundle": str(self.bundle),
            "declared_artifact_count": self.declared_artifact_count,
            "environment_sha256": self.environment_sha256,
            "evaluation_config_sha256": self.evaluation_config_sha256,
            "event": "governed_bundle_validated",
            "ok": True,
            "payload_bytes": self.payload_bytes,
            "payload_file_count": self.payload_file_count,
            "resolved_config_sha256": self.resolved_config_sha256,
            "run_id": self.run_id,
            "run_manifest_sha256": self.run_manifest_sha256,
            "trainer_manifest_sha256": self.trainer_manifest_sha256,
            "trainer_payload_file_count": self.trainer_payload_file_count,
        }


def _default_schema_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "experiments" / "schemas"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve_directory(path: Path | str, *, field: str) -> Path:
    supplied = Path(path)
    if supplied.is_symlink():
        raise GovernedBundleError(f"{field} must not be a symbolic link: {supplied}")
    try:
        resolved = supplied.resolve(strict=True)
    except OSError as exc:
        raise GovernedBundleError(f"cannot resolve {field} {supplied}: {exc}") from exc
    if not resolved.is_dir():
        raise GovernedBundleError(f"{field} must be a directory: {resolved}")
    return resolved


def _read_stable_regular_file(path: Path, *, field: str) -> bytes:
    if path.is_symlink():
        raise GovernedBundleError(f"{field} must not be a symbolic link: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise GovernedBundleError(f"{field} must be a regular file: {path}")
        if before.st_size > _MAX_JSON_BYTES:
            raise GovernedBundleError(f"{field} exceeds {_MAX_JSON_BYTES} bytes: {path}")
        chunks: list[bytes] = []
        byte_count = 0
        while True:
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
            byte_count += len(chunk)
        after = os.fstat(descriptor)
        if (
            byte_count != before.st_size
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
            or before.st_dev != after.st_dev
        ):
            raise GovernedBundleError(f"{field} changed while being read: {path}")
        return b"".join(chunks)
    except GovernedBundleError:
        raise
    except OSError as exc:
        raise GovernedBundleError(f"cannot read {field} {path}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise GovernedBundleError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_non_finite_number(value: str) -> None:
    raise GovernedBundleError(f"non-finite JSON number is forbidden: {value}")


def _parse_finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise GovernedBundleError(f"non-finite JSON number is forbidden: {value}")
    return parsed


def _decode_json_object(raw: bytes, *, field: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_non_finite_number,
            parse_float=_parse_finite_float,
        )
    except UnicodeDecodeError as exc:
        raise GovernedBundleError(f"{field} is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise GovernedBundleError(
            f"{field} is invalid JSON at line {exc.lineno}, column {exc.colno}"
        ) from exc
    if type(value) is not dict:
        raise GovernedBundleError(f"{field} root must be a JSON object")
    return value


def _read_json(path: Path, *, field: str) -> tuple[dict[str, Any], bytes]:
    raw = _read_stable_regular_file(path, field=field)
    return _decode_json_object(raw, field=field), raw


def _load_schema(schema_directory: Path, name: str) -> dict[str, Any]:
    path = schema_directory / name
    value, _ = _read_json(path, field=f"JSON Schema {name}")
    return value


def _schema_error_path(error: Any) -> str:
    parts = [str(part) for part in error.absolute_path]
    return ".".join(parts) if parts else "<root>"


def _validate_schema(value: object, schema: dict[str, Any], *, field: str) -> None:
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from jsonschema.exceptions import SchemaError
    except ImportError as exc:  # pragma: no cover - exercised in dependency-light installs
        raise GovernedBundleError(
            "governed-bundle validation requires jsonschema[format-nongpl]==4.26.0; "
            "install the governance extra"
        ) from exc
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise GovernedBundleError(f"{field} schema is invalid: {exc.message}") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        rendered = "; ".join(f"{_schema_error_path(error)}: {error.message}" for error in errors)
        raise GovernedBundleError(f"{field} schema validation failed: {rendered}")


def _manifest_records(manifest: ArtifactManifest) -> dict[str, FileRecord]:
    return {record.path: record for record in manifest.files}


def _require_record(records: dict[str, FileRecord], path: str) -> FileRecord:
    record = records.get(path)
    if record is None:
        raise GovernedBundleError(f"outer artifact manifest is missing required path: {path}")
    return record


def _require_record_bytes(record: FileRecord, raw: bytes, *, field: str) -> str:
    digest = _sha256(raw)
    if record.bytes != len(raw) or record.sha256 != digest:
        raise GovernedBundleError(f"{field} bytes do not match the outer artifact manifest")
    return digest


def _verify_inventory(root: Path, *, field: str) -> ArtifactManifest:
    try:
        report = verify_bundle(root)
        manifest = load_manifest(root)
    except ArtifactError as exc:
        raise GovernedBundleError(f"{field} is invalid: {exc}") from exc
    if not report.ok:
        raise GovernedBundleError(
            f"{field} inventory mismatch: {json.dumps(report.to_dict(), sort_keys=True)}"
        )
    return manifest


def _validate_declared_artifacts(
    run_manifest: dict[str, Any],
    outer_records: dict[str, FileRecord],
) -> dict[str, dict[str, Any]]:
    artifacts: list[dict[str, Any]] = run_manifest["artifacts"]
    by_id: dict[str, dict[str, Any]] = {}
    by_path: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        artifact_id = artifact["artifact_id"]
        path = artifact["path"]
        if artifact_id in by_id:
            raise GovernedBundleError(f"duplicate run artifact_id: {artifact_id}")
        if path in by_path:
            raise GovernedBundleError(f"duplicate run artifact path: {path}")
        if path == RUN_MANIFEST_PATH:
            raise GovernedBundleError("run-manifest.json must not declare itself as an artifact")
        record = outer_records.get(path)
        if record is None:
            raise GovernedBundleError(f"run artifact is absent from outer manifest: {path}")
        if (artifact["byte_size"], artifact["sha256"]) != (record.bytes, record.sha256):
            raise GovernedBundleError(f"run artifact identity differs from outer manifest: {path}")
        by_id[artifact_id] = artifact
        by_path[path] = artifact

    expected_paths = set(outer_records) - {RUN_MANIFEST_PATH}
    declared_paths = set(by_path)
    if declared_paths != expected_paths:
        missing = sorted(expected_paths - declared_paths)
        unexpected = sorted(declared_paths - expected_paths)
        raise GovernedBundleError(
            "run artifact paths must classify every outer payload except run-manifest.json: "
            f"missing={missing!r}, unexpected={unexpected!r}"
        )

    evaluation = run_manifest["evaluation"]
    for field in (
        "metrics_artifact_id",
        "coverage_artifact_id",
        "runtime_profile_artifact_id",
    ):
        reference = evaluation.get(field)
        if reference is not None and reference not in by_id:
            raise GovernedBundleError(f"evaluation.{field} references an absent artifact_id")
    metrics_id = evaluation.get("metrics_artifact_id")
    if metrics_id is not None and by_id[metrics_id]["kind"] != "metrics":
        raise GovernedBundleError("evaluation.metrics_artifact_id must identify kind metrics")
    profile_id = evaluation.get("runtime_profile_artifact_id")
    if profile_id is not None and by_id[profile_id]["kind"] != "profile":
        raise GovernedBundleError(
            "evaluation.runtime_profile_artifact_id must identify kind profile"
        )
    return by_path


def _validate_resolved_config_binding(
    *,
    run_manifest: dict[str, Any],
    resolved_config: dict[str, Any],
    resolved_config_sha256: str,
    trainer_summary: dict[str, Any],
) -> None:
    reference = run_manifest["experiment"]["configuration"]
    expected_reference = {
        "path": RESOLVED_CONFIG_PATH,
        "sha256": resolved_config_sha256,
    }
    if reference != expected_reference:
        raise GovernedBundleError(
            "run experiment.configuration must bind the exact resolved-config.json bytes"
        )
    preprocessing = run_manifest["data"].get("preprocessing")
    if preprocessing != expected_reference:
        raise GovernedBundleError(
            "run data.preprocessing must bind the exact resolved-config.json bytes"
        )
    try:
        from compact_vio.learning.config import TrainingConfig

        canonical = TrainingConfig.from_dict(resolved_config).to_dict()
    except (LearningError, TypeError, ValueError) as exc:
        raise GovernedBundleError(f"resolved configuration is invalid: {exc}") from exc
    if resolved_config != canonical:
        raise GovernedBundleError(
            "resolved-config.json must use the canonical TrainingConfig projection"
        )
    if trainer_summary.get("runtime_config") != canonical:
        raise GovernedBundleError(
            "resolved configuration does not reproduce trainer run-summary.runtime_config"
        )
    experiment = run_manifest["experiment"]
    if trainer_summary.get("experiment_id") != experiment["candidate_name"]:
        raise GovernedBundleError("trainer and governed experiment identities differ")
    if experiment["seeds"] != [canonical["seed"]]:
        raise GovernedBundleError("run experiment seeds must equal the resolved training seed")
    git_revision = run_manifest["provenance"]["git"]["commit_sha"]
    if trainer_summary.get("git_revision") != git_revision:
        raise GovernedBundleError("trainer and governed Git revisions differ")
    if trainer_summary.get("started_at") != run_manifest.get("started_at"):
        raise GovernedBundleError("trainer and governed run start times differ")
    if trainer_summary.get("completed_at") != run_manifest.get("finished_at"):
        raise GovernedBundleError("trainer and governed run finish times differ")
    if trainer_summary.get("status") != "completed" or run_manifest["status"] != "succeeded":
        raise GovernedBundleError(
            "a completed trainer output must be represented as a succeeded governed run"
        )


def _validate_configuration_reference(
    reference: dict[str, Any],
    *,
    field: str,
    outer_records: dict[str, FileRecord],
    declared_by_path: dict[str, dict[str, Any]],
) -> FileRecord:
    path = reference["path"]
    record = outer_records.get(path)
    if record is None:
        raise GovernedBundleError(
            f"run {field} must reference an outer-inventoried artifact: {path}"
        )
    artifact = declared_by_path.get(path)
    if artifact is None:  # Defensive: full classification is checked before this helper.
        raise GovernedBundleError(f"run {field} references an unclassified artifact: {path}")
    if artifact["kind"] != "configuration":
        raise GovernedBundleError(
            f"run {field} must reference an artifact declared as kind configuration: {path}"
        )
    if reference["sha256"] != record.sha256:
        raise GovernedBundleError(
            f"run {field} SHA-256 does not match the outer artifact identity: {path}"
        )
    return record


def _validate_configuration_references(
    *,
    run_manifest: dict[str, Any],
    outer_records: dict[str, FileRecord],
    declared_by_path: dict[str, dict[str, Any]],
) -> None:
    _validate_configuration_reference(
        run_manifest["experiment"]["configuration"],
        field="experiment.configuration",
        outer_records=outer_records,
        declared_by_path=declared_by_path,
    )
    preprocessing = run_manifest["data"].get("preprocessing")
    if preprocessing is not None:
        _validate_configuration_reference(
            preprocessing,
            field="data.preprocessing",
            outer_records=outer_records,
            declared_by_path=declared_by_path,
        )
    for dataset_index, dataset in enumerate(run_manifest["data"]["datasets"]):
        _validate_configuration_reference(
            dataset["acquisition_manifest"],
            field=f"data.datasets[{dataset_index}].acquisition_manifest",
            outer_records=outer_records,
            declared_by_path=declared_by_path,
        )
        for split_index, split in enumerate(dataset["splits"]):
            _validate_configuration_reference(
                {
                    "path": split["manifest_path"],
                    "sha256": split["manifest_sha256"],
                },
                field=f"data.datasets[{dataset_index}].splits[{split_index}]",
                outer_records=outer_records,
                declared_by_path=declared_by_path,
            )
    _validate_configuration_reference(
        run_manifest["evaluation"]["configuration"],
        field="evaluation.configuration",
        outer_records=outer_records,
        declared_by_path=declared_by_path,
    )


def _validate_evaluation_config_binding(
    *,
    run_manifest: dict[str, Any],
    evaluation_config: dict[str, Any],
    evaluation_config_sha256: str,
) -> None:
    expected_reference = {
        "path": EVALUATION_CONFIG_PATH,
        "sha256": evaluation_config_sha256,
    }
    if run_manifest["evaluation"]["configuration"] != expected_reference:
        raise GovernedBundleError(
            f"run evaluation.configuration must bind the exact {EVALUATION_CONFIG_PATH} bytes"
        )
    if evaluation_config.get("record_type") != "resolved_evaluation_configuration":
        raise GovernedBundleError(
            f"{EVALUATION_CONFIG_PATH} record_type must be resolved_evaluation_configuration"
        )
    if evaluation_config.get("schema_version") != "1.0.0":
        raise GovernedBundleError(f"{EVALUATION_CONFIG_PATH} schema_version must be 1.0.0")
    evaluation = run_manifest["evaluation"]
    for field in ("metric_scale_claim", "primary_alignment", "causal"):
        if evaluation_config.get(field) != evaluation[field]:
            raise GovernedBundleError(
                f"{EVALUATION_CONFIG_PATH} {field} differs from run-manifest evaluation"
            )


def validate_governed_bundle(
    bundle: Path | str,
    *,
    schema_directory: Path | str | None = None,
) -> GovernedBundleReport:
    """Validate one frozen governed wrapper without changing it.

    The caller must separately retain and publish the returned raw manifest
    hashes as trust roots.  A successful result establishes structural and
    copy-integrity consistency only; it does not establish storage durability,
    restoration, rights clearance, or scientific acceptance.
    """

    root = _resolve_directory(bundle, field="governed bundle")
    schemas = _resolve_directory(
        schema_directory if schema_directory is not None else _default_schema_directory(),
        field="schema directory",
    )
    outer_manifest = _verify_inventory(root, field="outer governed bundle")
    outer_records = _manifest_records(outer_manifest)

    run_record = _require_record(outer_records, RUN_MANIFEST_PATH)
    resolved_record = _require_record(outer_records, RESOLVED_CONFIG_PATH)
    environment_record = _require_record(outer_records, ENVIRONMENT_PATH)
    evaluation_config_record = _require_record(outer_records, EVALUATION_CONFIG_PATH)
    trainer_summary_record = _require_record(outer_records, TRAINER_SUMMARY_PATH)
    trainer_manifest_record = _require_record(outer_records, TRAINER_MANIFEST_PATH)

    run_manifest, run_bytes = _read_json(root / RUN_MANIFEST_PATH, field=RUN_MANIFEST_PATH)
    resolved_config, resolved_bytes = _read_json(
        root / RESOLVED_CONFIG_PATH,
        field=RESOLVED_CONFIG_PATH,
    )
    environment, environment_bytes = _read_json(
        root / ENVIRONMENT_PATH,
        field=ENVIRONMENT_PATH,
    )
    evaluation_config, evaluation_config_bytes = _read_json(
        root / EVALUATION_CONFIG_PATH,
        field=EVALUATION_CONFIG_PATH,
    )
    trainer_summary, trainer_summary_bytes = _read_json(
        root / TRAINER_SUMMARY_PATH,
        field=TRAINER_SUMMARY_PATH,
    )
    run_sha256 = _require_record_bytes(run_record, run_bytes, field=RUN_MANIFEST_PATH)
    resolved_sha256 = _require_record_bytes(
        resolved_record,
        resolved_bytes,
        field=RESOLVED_CONFIG_PATH,
    )
    environment_sha256 = _require_record_bytes(
        environment_record,
        environment_bytes,
        field=ENVIRONMENT_PATH,
    )
    evaluation_config_sha256 = _require_record_bytes(
        evaluation_config_record,
        evaluation_config_bytes,
        field=EVALUATION_CONFIG_PATH,
    )
    _require_record_bytes(
        trainer_summary_record,
        trainer_summary_bytes,
        field=TRAINER_SUMMARY_PATH,
    )

    try:
        outer_manifest_bytes = read_manifest_bytes(root)
    except ArtifactError as exc:
        raise GovernedBundleError(f"cannot read outer artifact manifest: {exc}") from exc
    outer_document = _decode_json_object(
        outer_manifest_bytes,
        field=ARTIFACT_MANIFEST_PATH,
    )
    if outer_manifest_bytes != outer_manifest.to_json_bytes():
        raise GovernedBundleError("outer artifact-manifest.json is not canonical JSON")
    run_schema = _load_schema(schemas, _RUN_SCHEMA_NAME)
    artifact_schema = _load_schema(schemas, _ARTIFACT_SCHEMA_NAME)
    _validate_schema(
        run_manifest,
        run_schema,
        field=RUN_MANIFEST_PATH,
    )
    _validate_schema(
        outer_document,
        artifact_schema,
        field=ARTIFACT_MANIFEST_PATH,
    )
    declared_by_path = _validate_declared_artifacts(run_manifest, outer_records)
    if declared_by_path[RESOLVED_CONFIG_PATH]["kind"] != "configuration":
        raise GovernedBundleError("resolved-config.json must be declared as kind configuration")
    if declared_by_path[ENVIRONMENT_PATH]["kind"] != "environment":
        raise GovernedBundleError("environment.json must be declared as kind environment")
    _validate_configuration_references(
        run_manifest=run_manifest,
        outer_records=outer_records,
        declared_by_path=declared_by_path,
    )
    if environment != run_manifest["provenance"]:
        raise GovernedBundleError(
            "environment.json must exactly equal the run-manifest provenance projection"
        )
    _validate_resolved_config_binding(
        run_manifest=run_manifest,
        resolved_config=resolved_config,
        resolved_config_sha256=resolved_sha256,
        trainer_summary=trainer_summary,
    )
    _validate_evaluation_config_binding(
        run_manifest=run_manifest,
        evaluation_config=evaluation_config,
        evaluation_config_sha256=evaluation_config_sha256,
    )

    trainer_root = root / TRAINER_OUTPUT_DIRECTORY
    trainer_manifest = _verify_inventory(trainer_root, field="nested trainer-output bundle")
    trainer_paths = {record.path for record in trainer_manifest.files}
    if trainer_paths != EXPECTED_TRAINER_PAYLOAD_PATHS:
        raise GovernedBundleError(
            "nested trainer-output manifest must preserve the exact five-file trainer bundle: "
            f"expected={sorted(EXPECTED_TRAINER_PAYLOAD_PATHS)!r}, "
            f"actual={sorted(trainer_paths)!r}"
        )
    try:
        trainer_manifest_bytes = read_manifest_bytes(trainer_root)
    except ArtifactError as exc:
        raise GovernedBundleError(f"cannot read nested trainer manifest: {exc}") from exc
    trainer_manifest_document = _decode_json_object(
        trainer_manifest_bytes,
        field=TRAINER_MANIFEST_PATH,
    )
    if trainer_manifest_bytes != trainer_manifest.to_json_bytes():
        raise GovernedBundleError("nested trainer artifact-manifest.json is not canonical JSON")
    _validate_schema(
        trainer_manifest_document,
        artifact_schema,
        field=TRAINER_MANIFEST_PATH,
    )
    trainer_manifest_sha256 = _require_record_bytes(
        trainer_manifest_record,
        trainer_manifest_bytes,
        field=TRAINER_MANIFEST_PATH,
    )

    # Re-inventory at the end so a concurrent mutation cannot pass by changing
    # a file after its binding check but before this call returns.
    final_manifest = _verify_inventory(root, field="outer governed bundle")
    if final_manifest != outer_manifest:
        raise GovernedBundleError("outer governed bundle changed during validation")
    try:
        final_manifest_bytes = read_manifest_bytes(root)
    except ArtifactError as exc:
        raise GovernedBundleError(f"cannot re-read outer artifact manifest: {exc}") from exc
    if final_manifest_bytes != outer_manifest_bytes:
        raise GovernedBundleError("outer artifact manifest changed during validation")

    return GovernedBundleReport(
        bundle=root,
        run_id=run_manifest["run_id"],
        run_manifest_sha256=run_sha256,
        artifact_manifest_sha256=_sha256(outer_manifest_bytes),
        payload_file_count=len(outer_manifest.files),
        payload_bytes=sum(record.bytes for record in outer_manifest.files),
        declared_artifact_count=len(run_manifest["artifacts"]),
        trainer_manifest_sha256=trainer_manifest_sha256,
        trainer_payload_file_count=len(trainer_manifest.files),
        resolved_config_sha256=resolved_sha256,
        evaluation_config_sha256=evaluation_config_sha256,
        environment_sha256=environment_sha256,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-validate-governed-bundle",
        description=(
            "Read-only validation of a frozen governed training bundle and its nested "
            "original trainer output."
        ),
    )
    parser.add_argument("bundle", type=Path, help="governed bundle root")
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=_default_schema_directory(),
        help="directory containing run/artifact JSON Schemas",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        report = validate_governed_bundle(
            arguments.bundle,
            schema_directory=arguments.schema_dir,
        )
    except (GovernedBundleError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "event": "governed_bundle_validation_failed",
                    "ok": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report.to_dict(), sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_MANIFEST_PATH",
    "ENVIRONMENT_PATH",
    "EVALUATION_CONFIG_PATH",
    "EXPECTED_TRAINER_PAYLOAD_PATHS",
    "GovernedBundleError",
    "GovernedBundleReport",
    "RESOLVED_CONFIG_PATH",
    "RUN_MANIFEST_PATH",
    "TRAINER_MANIFEST_PATH",
    "TRAINER_OUTPUT_DIRECTORY",
    "TRAINER_SUMMARY_PATH",
    "build_parser",
    "main",
    "validate_governed_bundle",
]

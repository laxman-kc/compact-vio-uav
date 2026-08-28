"""Evaluate frozen learned-VIO checkpoints against EuRoC position-only reference data.

This command is deliberately evaluation-only: it does not construct an optimizer,
update weights, or expose reference positions to the model.  The checked-in protocol
binds the exact archive, sequence, source bytes, checkpoints, inference-state policy,
metric, and decision rule before predictions are inspected.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compact_vio.evaluation.position_magnitude import DISPLACEMENT_MAGNITUDE_METRIC_ID
from compact_vio.learning.errors import LearningError

_HEX_32 = re.compile(r"[0-9a-f]{32}")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_GIT_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_RECORD_TYPE = "euroc_position_only_checkpoint_evaluation"
_SCHEMA_VERSION = "2.0.0"
_METRIC_POLICY_ID = DISPLACEMENT_MAGNITUDE_METRIC_ID
_DECISION_RULE_ID = (
    "full-sensor-and-reference-coverage/beat-zero-pair-rmse/"
    "minimum-pair-displacement-magnitude-rmse/no-tie-break/v1"
)
_CONTROLLED_MAGNITUDE_DECISION_RULE_ID = (
    "full-sensor-and-reference-coverage/beat-zero-pair-rmse/"
    "v5-beats-v2-on-pair-cumulative-and-distance-ratio/no-tie-no-retry/v1"
)
_DECISION_RULE_IDS = frozenset({_DECISION_RULE_ID, _CONTROLLED_MAGNITUDE_DECISION_RULE_ID})
_INDEPENDENT_POLICY = "independent-zero-state-per-pair/v1"
_STATEFUL_POLICY = "stateful-contiguous-native-pairs/v1"
_INFERENCE_POLICIES = frozenset({_INDEPENDENT_POLICY, _STATEFUL_POLICY})
_VALIDATION_TRANSLATION_METRIC = "validation/translation_rmse_m"
_VALIDATION_ROTATION_METRIC = "validation/rotation_rmse_rad"
_FROZEN_V2_VALIDATION_TRANSLATION_RMSE_M = 0.058765891780989885
_FROZEN_V2_VALIDATION_ROTATION_RMSE_RAD = 0.0061899144990098035


def _text(value: object, *, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise LearningError(f"{field} must be a non-empty string")
    return value


def _identifier(value: object, *, field: str) -> str:
    result = _text(value, field=field)
    if _SAFE_ID.fullmatch(result) is None or result in (".", ".."):
        raise LearningError(f"{field} must be one safe identifier without path separators")
    return result


def _digest(value: object, *, field: str, pattern: re.Pattern[str]) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise LearningError(f"{field} must be a lowercase hexadecimal digest")
    return value


def _exact_mapping(
    value: object,
    expected: set[str],
    *,
    field: str,
) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise LearningError(f"{field} must be a JSON object with string keys")
    if set(value) != expected:
        raise LearningError(f"{field} fields must equal {sorted(expected)!r}")
    return value


def _identifier_array(value: object, *, field: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise LearningError(f"{field} must be a non-empty JSON array")
    result = tuple(_identifier(item, field=f"{field}[{index}]") for index, item in enumerate(value))
    if len(result) != len(set(result)):
        raise LearningError(f"{field} must not contain duplicates")
    return result


def _sha256_mapping(value: object, *, field: str) -> tuple[tuple[str, str], ...]:
    if type(value) is not dict or not value:
        raise LearningError(f"{field} must be a non-empty JSON object")
    result: list[tuple[str, str]] = []
    for key, digest in value.items():
        sequence_id = _identifier(key, field=f"{field} key")
        result.append(
            (
                sequence_id,
                _digest(digest, field=f"{field}[{sequence_id!r}]", pattern=_HEX_64),
            )
        )
    return tuple(sorted(result))


def _json_without_duplicate_keys(path: Path) -> tuple[object, bytes]:
    def collect(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise LearningError(f"duplicate JSON key in {path}: {key!r}")
            result[key] = value
        return result

    try:
        source_bytes = path.read_bytes()
        value = json.loads(source_bytes.decode("utf-8"), object_pairs_hook=collect)
        return value, source_bytes
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LearningError(f"cannot read evaluation protocol {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise LearningError(f"source must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise LearningError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _archive_hashes(path: Path) -> tuple[int, str, str]:
    if path.is_symlink() or not path.is_file():
        raise LearningError(f"archive must be a regular non-symlink file: {path}")
    md5 = hashlib.md5(usedforsecurity=False)  # noqa: S324 - published integrity identity
    sha256 = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                size += len(chunk)
                md5.update(chunk)
                sha256.update(chunk)
    except OSError as exc:
        raise LearningError(f"cannot hash archive {path}: {exc}") from exc
    return size, md5.hexdigest(), sha256.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_revision(anchor: Path, *, expected_source_sha256: str) -> str:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=anchor.parent,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if status.stdout:
            raise LearningError("evaluation requires a completely clean worktree")
        root_result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=anchor.parent,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        repository_root = Path(root_result.stdout.strip()).resolve(strict=True)
        try:
            relative_source = anchor.resolve(strict=True).relative_to(repository_root)
        except ValueError as exc:
            raise LearningError("evaluation protocol must be inside the repository") from exc
        subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative_source.as_posix()],
            cwd=repository_root,
            check=True,
            capture_output=True,
            timeout=30,
        )
        committed_source = subprocess.run(
            ["git", "show", f"HEAD:{relative_source.as_posix()}"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            timeout=30,
        ).stdout
        if hashlib.sha256(committed_source).hexdigest() != expected_source_sha256:
            raise LearningError("evaluation protocol bytes do not equal the committed HEAD blob")
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=anchor.parent,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LearningError(f"cannot resolve git revision: {exc}") from exc
    revision = result.stdout.strip()
    if _HEX_64.fullmatch(revision) is None and re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise LearningError("git revision is not a lowercase commit digest")
    return revision


def _write_json(path: Path, value: object) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, TypeError, ValueError) as exc:
        raise LearningError(f"cannot write JSON artifact {path}: {exc}") from exc


def _percentile(values: tuple[float, ...], quantile: float) -> float:
    if not values or any(type(value) is not float or not math.isfinite(value) for value in values):
        raise LearningError("latency values must be non-empty finite floats")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


@dataclass(frozen=True, slots=True)
class PositionDatasetIdentity:
    """Exact official archive and extracted source identity for one sequence."""

    doi: str
    rights_statement: str
    sequence_id: str
    archive_filename: str
    archive_size_bytes: int
    archive_md5: str
    archive_sha256: str
    sensor_sources_sha256: str
    sensor_calibration_sha256: str
    position_reference_sha256: str

    def __post_init__(self) -> None:
        _text(self.doi, field="dataset.doi")
        _text(self.rights_statement, field="dataset.rights_statement")
        _identifier(self.sequence_id, field="dataset.sequence_id")
        if (
            type(self.archive_filename) is not str
            or "/" in self.archive_filename
            or "\\" in self.archive_filename
            or Path(self.archive_filename).name != self.archive_filename
            or not self.archive_filename.endswith(".zip")
        ):
            raise LearningError("dataset.archive_filename must be one .zip basename")
        if type(self.archive_size_bytes) is not int or self.archive_size_bytes <= 0:
            raise LearningError("dataset.archive_size_bytes must be a positive integer")
        _digest(self.archive_md5, field="dataset.archive_md5", pattern=_HEX_32)
        for field in (
            "archive_sha256",
            "sensor_sources_sha256",
            "sensor_calibration_sha256",
            "position_reference_sha256",
        ):
            _digest(getattr(self, field), field=f"dataset.{field}", pattern=_HEX_64)


@dataclass(frozen=True, slots=True)
class PositionEvaluationSampling:
    """Frozen causal and position-reference association behavior."""

    frame_stride: int
    evaluation_unroll_pairs: int
    max_reference_bracket_interval_ns: int
    prediction_origin_id: str
    reference_origin_id: str
    sensor_origin_projection_policy_id: str
    reference_association_policy_id: str

    def __post_init__(self) -> None:
        if self.frame_stride != 1:
            raise LearningError("sampling.frame_stride must equal one for native evaluation")
        if type(self.evaluation_unroll_pairs) is not int or self.evaluation_unroll_pairs <= 0:
            raise LearningError("sampling.evaluation_unroll_pairs must be positive")
        if (
            type(self.max_reference_bracket_interval_ns) is not int
            or self.max_reference_bracket_interval_ns != 100_000_000
        ):
            raise LearningError(
                "sampling.max_reference_bracket_interval_ns must equal frozen 100000000"
            )
        if self.prediction_origin_id != "imu0" or self.reference_origin_id != "leica0":
            raise LearningError("sampling origins must equal imu0 prediction and leica0 reference")
        if (
            self.sensor_origin_projection_policy_id != "imu-to-leica-origin/from-native-t-bs/"
            "r-il-equals-r-bi-transpose-times-p-bl-minus-p-bi/"
            "delta-l-equals-t-i-plus-r-rel-r-il-minus-r-il/v1"
        ):
            raise LearningError("unsupported sensor-origin projection policy")
        if (
            self.reference_association_policy_id
            != "linear-within-leica-coverage/max-bracket-100ms/"
            "all-native-pairs-both-endpoints-valid/no-extrapolation/v1"
        ):
            raise LearningError("unsupported position-reference association policy")


@dataclass(frozen=True, slots=True)
class PositionCheckpointProvenance:
    """Exact training-run provenance required for one frozen candidate."""

    code_revision: str
    split_id: str
    train_sequence_ids: tuple[str, ...]
    validation_sequence_ids: tuple[str, ...]
    source_sha256: tuple[tuple[str, str], ...]
    calibration_sha256: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        _digest(
            self.code_revision,
            field="checkpoint_provenance.code_revision",
            pattern=_GIT_REVISION,
        )
        _text(self.split_id, field="checkpoint_provenance.split_id")
        for field in ("train_sequence_ids", "validation_sequence_ids"):
            values = getattr(self, field)
            if type(values) is not tuple or not values:
                raise LearningError(f"checkpoint_provenance.{field} must be a non-empty tuple")
            checked = tuple(
                _identifier(value, field=f"checkpoint_provenance.{field}[{index}]")
                for index, value in enumerate(values)
            )
            if checked != values or len(checked) != len(set(checked)):
                raise LearningError(
                    f"checkpoint_provenance.{field} must contain unique exact identifiers"
                )
        overlap = set(self.train_sequence_ids) & set(self.validation_sequence_ids)
        if overlap:
            raise LearningError(
                f"checkpoint_provenance train/validation membership overlaps: {sorted(overlap)!r}"
            )
        for field in ("source_sha256", "calibration_sha256"):
            pairs = getattr(self, field)
            if type(pairs) is not tuple or not pairs:
                raise LearningError(f"checkpoint_provenance.{field} must be a non-empty tuple")
            if any(
                type(item) is not tuple
                or len(item) != 2
                or type(item[0]) is not str
                or type(item[1]) is not str
                for item in pairs
            ):
                raise LearningError(
                    f"checkpoint_provenance.{field} must contain exact identifier/hash pairs"
                )
            checked = tuple(
                sorted(
                    (
                        _identifier(key, field=f"checkpoint_provenance.{field} key"),
                        _digest(
                            digest,
                            field=f"checkpoint_provenance.{field}[{key!r}]",
                            pattern=_HEX_64,
                        ),
                    )
                    for key, digest in pairs
                )
            )
            if checked != pairs or len({key for key, _ in pairs}) != len(pairs):
                raise LearningError(
                    f"checkpoint_provenance.{field} must be sorted with unique identifiers"
                )
        source_ids = {key for key, _ in self.source_sha256}
        calibration_ids = {key for key, _ in self.calibration_sha256}
        if source_ids != calibration_ids:
            raise LearningError(
                "checkpoint_provenance source/calibration sequence membership differs"
            )
        required_ids = set(self.train_sequence_ids) | set(self.validation_sequence_ids)
        if not required_ids <= source_ids:
            raise LearningError(
                "checkpoint_provenance source/calibration hashes do not cover split membership"
            )


@dataclass(frozen=True, slots=True)
class PositionEvaluationCandidate:
    """One frozen checkpoint and its declared fusion-state inference behavior."""

    candidate_id: str
    checkpoint_sha256: str
    inference_policy_id: str
    checkpoint_provenance: PositionCheckpointProvenance

    def __post_init__(self) -> None:
        _identifier(self.candidate_id, field="candidate_id")
        _digest(self.checkpoint_sha256, field="checkpoint_sha256", pattern=_HEX_64)
        if (
            type(self.inference_policy_id) is not str
            or self.inference_policy_id not in _INFERENCE_POLICIES
        ):
            raise LearningError("unsupported candidate inference_policy_id")
        if type(self.checkpoint_provenance) is not PositionCheckpointProvenance:
            raise LearningError(
                "candidate checkpoint_provenance must be a PositionCheckpointProvenance"
            )


@dataclass(frozen=True, slots=True)
class PositionValidationGuardrail:
    """Pre-inference validation limits for one selected training checkpoint."""

    candidate_id: str
    max_selected_validation_translation_rmse_m: float
    max_selected_validation_rotation_rmse_rad: float

    def __post_init__(self) -> None:
        _identifier(self.candidate_id, field="validation_guardrail.candidate_id")
        for field in (
            "max_selected_validation_translation_rmse_m",
            "max_selected_validation_rotation_rmse_rad",
        ):
            value = getattr(self, field)
            if type(value) is not float or not math.isfinite(value) or value < 0.0:
                raise LearningError(f"validation_guardrail.{field} must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class PositionEvaluationProtocol:
    """Strict, immutable fresh-evaluation protocol loaded from committed JSON."""

    evaluation_id: str
    dataset: PositionDatasetIdentity
    sampling: PositionEvaluationSampling
    metric_policy_id: str
    decision_rule_id: str
    candidates: tuple[PositionEvaluationCandidate, ...]
    validation_guardrail: PositionValidationGuardrail | None
    source_path: Path
    source_sha256: str

    def __post_init__(self) -> None:
        _identifier(self.evaluation_id, field="evaluation_id")
        if type(self.dataset) is not PositionDatasetIdentity:
            raise LearningError("dataset must be a PositionDatasetIdentity")
        if type(self.sampling) is not PositionEvaluationSampling:
            raise LearningError("sampling must be a PositionEvaluationSampling")
        if self.metric_policy_id != _METRIC_POLICY_ID:
            raise LearningError("unsupported metric_policy_id")
        if self.decision_rule_id not in _DECISION_RULE_IDS:
            raise LearningError("unsupported decision_rule_id")
        if (
            type(self.candidates) is not tuple
            or not self.candidates
            or any(type(item) is not PositionEvaluationCandidate for item in self.candidates)
        ):
            raise LearningError("candidates must be a non-empty exact tuple")
        identifiers = tuple(item.candidate_id for item in self.candidates)
        if len(identifiers) != len(set(identifiers)):
            raise LearningError("candidate identifiers must be unique")
        hashes = tuple(item.checkpoint_sha256 for item in self.candidates)
        if len(hashes) != len(set(hashes)):
            raise LearningError("candidate checkpoint hashes must be unique")
        for candidate in self.candidates:
            if self.dataset.sequence_id in (
                *candidate.checkpoint_provenance.train_sequence_ids,
                *candidate.checkpoint_provenance.validation_sequence_ids,
            ):
                raise LearningError(
                    f"evaluation sequence {self.dataset.sequence_id!r} appears in checkpoint "
                    f"{candidate.candidate_id!r} frozen split provenance"
                )
        if self.decision_rule_id == _CONTROLLED_MAGNITUDE_DECISION_RULE_ID:
            if type(self.validation_guardrail) is not PositionValidationGuardrail:
                raise LearningError(
                    "controlled magnitude-loss protocol requires a validation_guardrail"
                )
            if identifiers != ("v2", "v5"):
                raise LearningError(
                    "controlled magnitude-loss protocol requires candidates in exact v2, v5 order"
                )
            if any(
                candidate.inference_policy_id != _INDEPENDENT_POLICY
                for candidate in self.candidates
            ):
                raise LearningError(
                    "controlled magnitude-loss protocol requires independent-pair inference"
                )
            if self.validation_guardrail.candidate_id != "v5":
                raise LearningError("validation_guardrail must apply to candidate_id 'v5'")
            if (
                self.validation_guardrail.max_selected_validation_translation_rmse_m
                != _FROZEN_V2_VALIDATION_TRANSLATION_RMSE_M
                or self.validation_guardrail.max_selected_validation_rotation_rmse_rad
                != _FROZEN_V2_VALIDATION_ROTATION_RMSE_RAD
            ):
                raise LearningError(
                    "validation_guardrail must equal the exact frozen selected-v2 limits"
                )
        elif self.validation_guardrail is not None:
            raise LearningError(
                "validation_guardrail is supported only by the controlled magnitude-loss rule"
            )
        if not isinstance(self.source_path, Path) or not self.source_path.is_absolute():
            raise LearningError("source_path must be an absolute pathlib.Path")
        _digest(self.source_sha256, field="source_sha256", pattern=_HEX_64)


def load_position_evaluation_protocol(path: Path | str) -> PositionEvaluationProtocol:
    """Load an exact protocol and bind its SHA-256 before any model execution."""

    supplied = Path(path)
    if supplied.is_symlink():
        raise LearningError("evaluation protocol must be a regular non-symlink file")
    try:
        source = supplied.resolve(strict=True)
    except OSError as exc:
        raise LearningError(f"evaluation protocol does not exist: {supplied}") from exc
    if not source.is_file():
        raise LearningError("evaluation protocol must be a regular non-symlink file")
    source_value, source_bytes = _json_without_duplicate_keys(source)
    root_fields = {
        "record_type",
        "schema_version",
        "evaluation_id",
        "dataset",
        "sampling",
        "metric_policy_id",
        "decision_rule_id",
        "candidates",
    }
    if type(source_value) is dict and "validation_guardrail" in source_value:
        root_fields.add("validation_guardrail")
    root = _exact_mapping(source_value, root_fields, field="evaluation protocol")
    if root["record_type"] != _RECORD_TYPE or root["schema_version"] != _SCHEMA_VERSION:
        raise LearningError("unsupported evaluation protocol record_type or schema_version")
    dataset = _exact_mapping(
        root["dataset"],
        {
            "doi",
            "rights_statement",
            "sequence_id",
            "archive_filename",
            "archive_size_bytes",
            "archive_md5",
            "archive_sha256",
            "sensor_sources_sha256",
            "sensor_calibration_sha256",
            "position_reference_sha256",
        },
        field="dataset",
    )
    sampling = _exact_mapping(
        root["sampling"],
        {
            "frame_stride",
            "evaluation_unroll_pairs",
            "max_reference_bracket_interval_ns",
            "prediction_origin_id",
            "reference_origin_id",
            "sensor_origin_projection_policy_id",
            "reference_association_policy_id",
        },
        field="sampling",
    )
    candidate_values = root["candidates"]
    if type(candidate_values) is not list or not candidate_values:
        raise LearningError("candidates must be a non-empty JSON array")
    candidates: list[PositionEvaluationCandidate] = []
    for index, raw_candidate in enumerate(candidate_values):
        candidate = _exact_mapping(
            raw_candidate,
            {
                "candidate_id",
                "checkpoint_sha256",
                "inference_policy_id",
                "checkpoint_provenance",
            },
            field=f"candidates[{index}]",
        )
        checkpoint_provenance = _exact_mapping(
            candidate["checkpoint_provenance"],
            {
                "code_revision",
                "split_id",
                "train_sequence_ids",
                "validation_sequence_ids",
                "source_sha256",
                "calibration_sha256",
            },
            field=f"candidates[{index}].checkpoint_provenance",
        )
        candidates.append(
            PositionEvaluationCandidate(
                candidate_id=candidate["candidate_id"],  # type: ignore[arg-type]
                checkpoint_sha256=candidate["checkpoint_sha256"],  # type: ignore[arg-type]
                inference_policy_id=candidate["inference_policy_id"],  # type: ignore[arg-type]
                checkpoint_provenance=PositionCheckpointProvenance(
                    code_revision=checkpoint_provenance["code_revision"],  # type: ignore[arg-type]
                    split_id=checkpoint_provenance["split_id"],  # type: ignore[arg-type]
                    train_sequence_ids=_identifier_array(
                        checkpoint_provenance["train_sequence_ids"],
                        field=(f"candidates[{index}].checkpoint_provenance.train_sequence_ids"),
                    ),
                    validation_sequence_ids=_identifier_array(
                        checkpoint_provenance["validation_sequence_ids"],
                        field=(
                            f"candidates[{index}].checkpoint_provenance.validation_sequence_ids"
                        ),
                    ),
                    source_sha256=_sha256_mapping(
                        checkpoint_provenance["source_sha256"],
                        field=f"candidates[{index}].checkpoint_provenance.source_sha256",
                    ),
                    calibration_sha256=_sha256_mapping(
                        checkpoint_provenance["calibration_sha256"],
                        field=f"candidates[{index}].checkpoint_provenance.calibration_sha256",
                    ),
                ),
            )
        )
    guardrail: PositionValidationGuardrail | None = None
    if "validation_guardrail" in root:
        guardrail_value = _exact_mapping(
            root["validation_guardrail"],
            {
                "candidate_id",
                "max_selected_validation_translation_rmse_m",
                "max_selected_validation_rotation_rmse_rad",
            },
            field="validation_guardrail",
        )
        guardrail = PositionValidationGuardrail(**guardrail_value)  # type: ignore[arg-type]
    try:
        return PositionEvaluationProtocol(
            evaluation_id=root["evaluation_id"],  # type: ignore[arg-type]
            dataset=PositionDatasetIdentity(**dataset),  # type: ignore[arg-type]
            sampling=PositionEvaluationSampling(**sampling),  # type: ignore[arg-type]
            metric_policy_id=root["metric_policy_id"],  # type: ignore[arg-type]
            decision_rule_id=root["decision_rule_id"],  # type: ignore[arg-type]
            candidates=tuple(candidates),
            validation_guardrail=guardrail,
            source_path=source,
            source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )
    except TypeError as exc:
        raise LearningError(f"invalid evaluation protocol: {exc}") from exc


@dataclass(frozen=True, slots=True)
class CandidateDecisionInput:
    """Exact outcome fields consumed by the predeclared selection rule."""

    candidate_id: str
    sensor_pair_count: int
    produced_pair_count: int
    reference_pair_count: int
    scored_pair_count: int
    pair_displacement_magnitude_rmse_m: float
    cumulative_scored_distance_rmse_m: float | None = None
    scored_distance_ratio: float | None = None

    def __post_init__(self) -> None:
        _identifier(self.candidate_id, field="candidate_id")
        for field in (
            "sensor_pair_count",
            "produced_pair_count",
            "reference_pair_count",
            "scored_pair_count",
        ):
            if type(getattr(self, field)) is not int or getattr(self, field) <= 0:
                raise LearningError(f"{field} must be a positive integer")
        if (
            type(self.pair_displacement_magnitude_rmse_m) is not float
            or not math.isfinite(self.pair_displacement_magnitude_rmse_m)
            or self.pair_displacement_magnitude_rmse_m < 0.0
        ):
            raise LearningError("pair displacement-magnitude RMSE must be finite and non-negative")
        for field in ("cumulative_scored_distance_rmse_m", "scored_distance_ratio"):
            value = getattr(self, field)
            if value is not None and (
                type(value) is not float or not math.isfinite(value) or value < 0.0
            ):
                raise LearningError(f"{field} must be None or a finite non-negative float")


def apply_position_decision_rule(
    protocol: PositionEvaluationProtocol,
    outcomes: tuple[CandidateDecisionInput, ...],
    *,
    zero_motion_pair_rmse_m: float,
) -> dict[str, object]:
    """Apply one supported frozen position-only decision rule exactly."""

    if type(protocol) is not PositionEvaluationProtocol:
        raise LearningError("protocol must be an exact PositionEvaluationProtocol")
    if type(outcomes) is not tuple or any(
        type(item) is not CandidateDecisionInput for item in outcomes
    ):
        raise LearningError("outcomes must be an exact tuple of CandidateDecisionInput")
    expected = tuple(item.candidate_id for item in protocol.candidates)
    actual = tuple(item.candidate_id for item in outcomes)
    if actual != expected:
        raise LearningError("candidate outcomes must match protocol order exactly")
    if (
        type(zero_motion_pair_rmse_m) is not float
        or not math.isfinite(zero_motion_pair_rmse_m)
        or zero_motion_pair_rmse_m < 0.0
    ):
        raise LearningError("zero_motion_pair_rmse_m must be finite and non-negative")

    if protocol.decision_rule_id == _CONTROLLED_MAGNITUDE_DECISION_RULE_ID:
        if expected != ("v2", "v5"):
            raise LearningError(
                "controlled magnitude-loss rule requires candidates in exact v2, v5 order"
            )
        if any(
            item.cumulative_scored_distance_rmse_m is None or item.scored_distance_ratio is None
            for item in outcomes
        ):
            raise LearningError(
                "controlled magnitude-loss rule requires cumulative RMSE and distance ratio"
            )
        baseline, experimental = outcomes
        baseline_counts = (
            baseline.sensor_pair_count,
            baseline.produced_pair_count,
            baseline.reference_pair_count,
            baseline.scored_pair_count,
        )
        experimental_counts = (
            experimental.sensor_pair_count,
            experimental.produced_pair_count,
            experimental.reference_pair_count,
            experimental.scored_pair_count,
        )
        if experimental_counts != baseline_counts:
            raise LearningError(
                "controlled magnitude-loss rule requires identical candidate coverage counts"
            )
        coverage = {
            item.candidate_id: {
                "full_sensor_coverage": item.produced_pair_count == item.sensor_pair_count,
                "full_reference_coverage": item.scored_pair_count == item.reference_pair_count,
                "beats_zero_motion_pair_rmse": (
                    item.pair_displacement_magnitude_rmse_m < zero_motion_pair_rmse_m
                ),
            }
            for item in outcomes
        }
        both_have_full_coverage = all(
            values["full_sensor_coverage"] and values["full_reference_coverage"]
            for values in coverage.values()
        )
        assert baseline.cumulative_scored_distance_rmse_m is not None
        assert experimental.cumulative_scored_distance_rmse_m is not None
        assert baseline.scored_distance_ratio is not None
        assert experimental.scored_distance_ratio is not None
        gates = {
            "pair_displacement_magnitude_rmse_lower_than_zero_motion": (
                experimental.pair_displacement_magnitude_rmse_m < zero_motion_pair_rmse_m
            ),
            "pair_displacement_magnitude_rmse_lower_than_v2": (
                experimental.pair_displacement_magnitude_rmse_m
                < baseline.pair_displacement_magnitude_rmse_m
            ),
            "cumulative_scored_distance_rmse_lower_than_v2": (
                experimental.cumulative_scored_distance_rmse_m
                < baseline.cumulative_scored_distance_rmse_m
            ),
            "distance_ratio_error_lower_than_v2": (
                abs(1.0 - experimental.scored_distance_ratio)
                < abs(1.0 - baseline.scored_distance_ratio)
            ),
        }
        accepted = both_have_full_coverage and all(gates.values())
        return {
            "decision_rule_id": protocol.decision_rule_id,
            "zero_motion_pair_rmse_m": zero_motion_pair_rmse_m,
            "candidate_eligibility": [
                {"candidate_id": item.candidate_id, **coverage[item.candidate_id]}
                for item in outcomes
            ],
            "comparison_gates": gates,
            "decision": "accept_v5" if accepted else "retain_v2",
            "selected_candidate_id": "v5" if accepted else "v2",
            "scope": (
                "controlled position-only v2-versus-v5 displacement-magnitude endpoint; "
                "not a full-pose, rotation, ATE, deployment, or publication-grade approval"
            ),
        }

    eligibility: list[dict[str, object]] = []
    eligible: list[CandidateDecisionInput] = []
    for outcome in outcomes:
        full_sensor_coverage = outcome.produced_pair_count == outcome.sensor_pair_count
        full_reference_coverage = outcome.scored_pair_count == outcome.reference_pair_count
        beats_zero = outcome.pair_displacement_magnitude_rmse_m < zero_motion_pair_rmse_m
        is_eligible = full_sensor_coverage and full_reference_coverage and beats_zero
        eligibility.append(
            {
                "candidate_id": outcome.candidate_id,
                "full_sensor_coverage": full_sensor_coverage,
                "full_reference_coverage": full_reference_coverage,
                "beats_zero_motion_pair_rmse": beats_zero,
                "eligible": is_eligible,
            }
        )
        if is_eligible:
            eligible.append(outcome)

    selected: str | None = None
    decision = "no_eligible_candidate"
    if eligible:
        minimum = min(item.pair_displacement_magnitude_rmse_m for item in eligible)
        best = tuple(
            item for item in eligible if item.pair_displacement_magnitude_rmse_m == minimum
        )
        if len(best) == 1:
            selected = best[0].candidate_id
            decision = "selected_position_endpoint_candidate"
        else:
            decision = "no_selection_exact_metric_tie"
    return {
        "decision_rule_id": protocol.decision_rule_id,
        "zero_motion_pair_rmse_m": zero_motion_pair_rmse_m,
        "candidate_eligibility": eligibility,
        "decision": decision,
        "selected_candidate_id": selected,
        "scope": (
            "position-only displacement-magnitude endpoint; not a full-pose, rotation, "
            "ATE, deployment, or publication-grade approval"
        ),
    }


def _checkpoint_arguments(values: Sequence[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        if type(value) is not str or "=" not in value:
            raise LearningError("--checkpoint values must use candidate_id=path")
        candidate_id, path_text = value.split("=", 1)
        _text(candidate_id, field="checkpoint candidate_id")
        _text(path_text, field="checkpoint path")
        if candidate_id in result:
            raise LearningError(f"duplicate checkpoint mapping for {candidate_id!r}")
        result[candidate_id] = Path(path_text)
    return result


def _prepare_output_directory(path: Path) -> Path:
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise LearningError("output directory must be a non-symlink directory")
        try:
            if any(path.iterdir()):
                raise LearningError("output directory must be empty")
        except OSError as exc:
            raise LearningError(f"cannot inspect output directory {path}: {exc}") from exc
    else:
        try:
            path.mkdir(parents=True)
        except OSError as exc:
            raise LearningError(f"cannot create output directory {path}: {exc}") from exc
    return path.resolve(strict=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-evaluate-position",
        description="Evaluate frozen checkpoints on a position-only EuRoC protocol.",
    )
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--checkpoint", action="append", default=[], metavar="ID=PATH")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    return parser


def _select_device(torch_module: Any, requested: str) -> Any:
    if requested == "auto":
        requested = "cuda" if torch_module.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch_module.cuda.is_available():
        raise LearningError("CUDA was requested but is not available")
    return torch_module.device(requested)


def _configure_deterministic_inference(torch_module: Any, seed: int) -> None:
    if type(seed) is not int or seed < 0:
        raise LearningError("checkpoint seed must be a non-negative integer")
    workspace = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
    if workspace not in (None, ":4096:8", ":16:8"):
        raise LearningError("CUBLAS_WORKSPACE_CONFIG must be unset, ':4096:8', or ':16:8'")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch_module.manual_seed(seed)
    if torch_module.cuda.is_available():
        torch_module.cuda.manual_seed_all(seed)
    torch_module.backends.cudnn.benchmark = False
    torch_module.backends.cudnn.deterministic = True
    torch_module.use_deterministic_algorithms(True, warn_only=False)


def _regular_file(path: Path, *, field: str) -> Path:
    if path.is_symlink():
        raise LearningError(f"{field} must be a regular non-symlink file")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise LearningError(f"{field} does not exist: {path}") from exc
    if not resolved.is_file():
        raise LearningError(f"{field} must be a regular file")
    return resolved


def _resolve_checkpoints(
    protocol: PositionEvaluationProtocol,
    supplied_values: Sequence[str],
) -> dict[str, Path]:
    supplied = _checkpoint_arguments(supplied_values)
    expected = tuple(candidate.candidate_id for candidate in protocol.candidates)
    if set(supplied) != set(expected):
        raise LearningError(
            "checkpoint mappings must match protocol candidates exactly: "
            f"expected={list(expected)!r}, supplied={sorted(supplied)!r}"
        )
    resolved: dict[str, Path] = {}
    for candidate in protocol.candidates:
        path = _regular_file(
            supplied[candidate.candidate_id],
            field=f"checkpoint {candidate.candidate_id!r}",
        )
        actual = _sha256(path)
        if actual != candidate.checkpoint_sha256:
            raise LearningError(
                f"checkpoint SHA-256 mismatch for {candidate.candidate_id!r}: "
                f"expected {candidate.checkpoint_sha256}, got {actual}"
            )
        resolved[candidate.candidate_id] = path
    return resolved


def _validate_candidate_checkpoint_metadata(
    *,
    candidate: PositionEvaluationCandidate,
    metadata: Any,
    evaluation_sequence_id: str,
    expected_dataset_id: str,
) -> None:
    provenance = metadata.provenance
    expected = candidate.checkpoint_provenance
    checks = (
        ("dataset_id", provenance.dataset_id, expected_dataset_id),
        ("code_revision", provenance.code_revision, expected.code_revision),
        ("split_id", provenance.split_id, expected.split_id),
        ("train_sequence_ids", provenance.train_sequence_ids, expected.train_sequence_ids),
        (
            "validation_sequence_ids",
            provenance.validation_sequence_ids,
            expected.validation_sequence_ids,
        ),
        ("source_sha256", provenance.source_sha256, expected.source_sha256),
        ("calibration_sha256", provenance.calibration_sha256, expected.calibration_sha256),
    )
    for field, actual, required in checks:
        if type(actual) is not type(required) or actual != required:
            raise LearningError(
                f"checkpoint {candidate.candidate_id!r} provenance {field} differs from protocol"
            )
    if evaluation_sequence_id in (
        *provenance.train_sequence_ids,
        *provenance.validation_sequence_ids,
    ):
        raise LearningError(
            f"evaluation sequence {evaluation_sequence_id!r} appears in checkpoint "
            f"{candidate.candidate_id!r} training/validation provenance"
        )


def _enforce_validation_guardrail(
    protocol: PositionEvaluationProtocol,
    metrics_by_candidate: Mapping[str, Mapping[str, float]],
) -> None:
    guardrail = protocol.validation_guardrail
    if guardrail is None:
        return
    metrics = metrics_by_candidate.get(guardrail.candidate_id)
    if metrics is None:
        raise LearningError("validation guardrail candidate metrics are missing")
    checks = (
        (
            _VALIDATION_TRANSLATION_METRIC,
            guardrail.max_selected_validation_translation_rmse_m,
        ),
        (
            _VALIDATION_ROTATION_METRIC,
            guardrail.max_selected_validation_rotation_rmse_rad,
        ),
    )
    for metric_name, maximum in checks:
        value = metrics.get(metric_name)
        if type(value) is not float or not math.isfinite(value) or value < 0.0:
            raise LearningError(
                f"validation guardrail metric {metric_name!r} is missing, negative, or non-finite"
            )
        if value > maximum:
            raise LearningError(
                f"validation guardrail failed: {metric_name}={value!r} exceeds {maximum!r}"
            )


def _preflight_candidate_checkpoints(
    protocol: PositionEvaluationProtocol,
    checkpoints: Mapping[str, Path],
    *,
    expected_dataset_id: str,
) -> None:
    """Validate every checkpoint and the selected validation gate before inference."""

    from compact_vio.learning.inference import load_inference_model

    metrics_by_candidate: dict[str, Mapping[str, float]] = {}
    for candidate in protocol.candidates:
        model, metadata = load_inference_model(
            checkpoints[candidate.candidate_id],
            device="cpu",
            expected_inference_policy_id=candidate.inference_policy_id,
            expected_checkpoint_sha256=candidate.checkpoint_sha256,
        )
        _validate_candidate_checkpoint_metadata(
            candidate=candidate,
            metadata=metadata,
            evaluation_sequence_id=protocol.dataset.sequence_id,
            expected_dataset_id=expected_dataset_id,
        )
        metrics_by_candidate[candidate.candidate_id] = metadata.metrics
        del model
    _enforce_validation_guardrail(protocol, metrics_by_candidate)


def _candidate_predictions(
    *,
    candidate: PositionEvaluationCandidate,
    checkpoint_path: Path,
    sequence: Any,
    device: Any,
    evaluation_unroll_pairs: int,
    torch_module: Any,
    expected_dataset_id: str,
) -> tuple[tuple[Any, ...], dict[str, object], Any]:
    from torch.utils.data import DataLoader

    from compact_vio.evaluation.se3 import RelativePoseIncrement
    from compact_vio.learning.dataset import (
        EuRoCInferencePairDataset,
        EuRoCInferenceSequenceDataset,
        collate_vio_batch,
        collate_vio_sequence_batch,
    )
    from compact_vio.learning.inference import (
        load_inference_model,
        predict_batch,
        predict_sequence_batch,
    )

    model, metadata = load_inference_model(
        checkpoint_path,
        device=device,
        expected_inference_policy_id=candidate.inference_policy_id,
        expected_checkpoint_sha256=candidate.checkpoint_sha256,
    )
    _validate_candidate_checkpoint_metadata(
        candidate=candidate,
        metadata=metadata,
        evaluation_sequence_id=sequence.sequence_id,
        expected_dataset_id=expected_dataset_id,
    )
    model.zero_grad(set_to_none=True)
    if device.type == "cuda":
        torch_module.cuda.empty_cache()
        torch_module.cuda.reset_peak_memory_stats(device)

    increments: list[Any] = []
    latencies: list[float] = []
    state_initialization_count = 0
    _configure_deterministic_inference(torch_module, metadata.config.seed)
    if candidate.inference_policy_id == _INDEPENDENT_POLICY:
        dataset = EuRoCInferencePairDataset(
            (sequence,),
            model_config=metadata.config.model,
            data_config=metadata.config.data,
        )
        loader = DataLoader(
            dataset,
            batch_size=metadata.config.batch_size,
            shuffle=False,
            num_workers=metadata.config.num_workers,
            collate_fn=collate_vio_batch,
            pin_memory=device.type == "cuda",
            persistent_workers=metadata.config.num_workers > 0,
        )
        for batch in loader:
            if device.type == "cuda":
                torch_module.cuda.synchronize(device)
            started = time.perf_counter()
            prediction = predict_batch(model, batch, device=device).motion_vectors
            if device.type == "cuda":
                torch_module.cuda.synchronize(device)
            latencies.append(time.perf_counter() - started)
            for index, identity in enumerate(batch.identities):
                values = tuple(float(item) for item in prediction[index].tolist())
                increments.append(
                    RelativePoseIncrement(
                        sequence_id=identity.sequence_id,
                        sample_id=(
                            f"{identity.previous_timestamp_ns}:{identity.current_timestamp_ns}"
                        ),
                        start_timestamp_ns=identity.previous_timestamp_ns,
                        end_timestamp_ns=identity.current_timestamp_ns,
                        translation_previous_body_m=values[:3],  # type: ignore[arg-type]
                        rotation_vector_previous_to_current_rad=values[3:],  # type: ignore[arg-type]
                    )
                )
        state_initialization_count = len(increments)
        expected_pair_count = len(dataset)
        inference_scope = (
            "independent-pair-batches/model-placement-eval/host-to-device/"
            "forward/device-to-host/no-dedicated-warmup/v1"
        )
    else:
        dataset = EuRoCInferenceSequenceDataset(
            (sequence,),
            unroll_pairs=evaluation_unroll_pairs,
            model_config=metadata.config.model,
            data_config=metadata.config.data,
        )
        loader = DataLoader(
            dataset,
            batch_size=1,
            shuffle=False,
            num_workers=metadata.config.num_workers,
            collate_fn=collate_vio_sequence_batch,
            pin_memory=device.type == "cuda",
            persistent_workers=metadata.config.num_workers > 0,
        )
        fusion_state = None
        previous_chain: str | None = None
        previous_chunk: int | None = None
        for batch in loader:
            if len(batch.chain_ids) != 1:
                raise LearningError("stateful evaluation requires batch size one")
            chain = batch.chain_ids[0]
            chunk = batch.chunk_indices[0]
            contiguous = (
                previous_chain == chain
                and previous_chunk is not None
                and chunk == previous_chunk + 1
            )
            if batch.chain_starts[0] or not contiguous:
                fusion_state = None
                state_initialization_count += 1
            if device.type == "cuda":
                torch_module.cuda.synchronize(device)
            started = time.perf_counter()
            prediction = predict_sequence_batch(
                model,
                batch,
                device=device,
                initial_fusion_state=fusion_state,
            )
            if device.type == "cuda":
                torch_module.cuda.synchronize(device)
            latencies.append(time.perf_counter() - started)
            fusion_state = prediction.final_fusion_state
            if not torch_module.equal(prediction.step_mask, batch.step_mask.cpu()):
                raise LearningError("stateful prediction mask differs from source batch")
            for step_index, active in enumerate(batch.step_mask[0].tolist()):
                if not active:
                    continue
                identity = batch.identities[0][step_index]
                if identity is None:
                    raise LearningError("active stateful step lacks source identity")
                values = tuple(
                    float(item) for item in prediction.motion_vectors[0, step_index].tolist()
                )
                increments.append(
                    RelativePoseIncrement(
                        sequence_id=identity.sequence_id,
                        sample_id=(
                            f"{identity.previous_timestamp_ns}:{identity.current_timestamp_ns}"
                        ),
                        start_timestamp_ns=identity.previous_timestamp_ns,
                        end_timestamp_ns=identity.current_timestamp_ns,
                        translation_previous_body_m=values[:3],  # type: ignore[arg-type]
                        rotation_vector_previous_to_current_rad=values[3:],  # type: ignore[arg-type]
                    )
                )
            previous_chain = chain
            previous_chunk = chunk
            if batch.chain_ends[0]:
                fusion_state = None
        expected_pair_count = dataset.pair_count
        inference_scope = (
            "stateful-contiguous-native-pairs/model-placement-eval/host-to-device/"
            "forward/device-to-host/no-dedicated-warmup/v1"
        )

    if len(increments) != expected_pair_count or not latencies:
        raise LearningError(
            f"candidate {candidate.candidate_id!r} produced incomplete inference output"
        )
    total_seconds = math.fsum(latencies)
    inference = {
        "policy_id": candidate.inference_policy_id,
        "scope": inference_scope,
        "evaluation_unroll_pairs": (
            evaluation_unroll_pairs if candidate.inference_policy_id == _STATEFUL_POLICY else 1
        ),
        "state_initialization_count": state_initialization_count,
        "batch_count": len(latencies),
        "total_seconds": total_seconds,
        "pairs_per_second": len(increments) / total_seconds,
        "batch_latency_p50_ms": 1000.0 * _percentile(tuple(latencies), 0.5),
        "batch_latency_p95_ms": 1000.0 * _percentile(tuple(latencies), 0.95),
        "cuda_peak_allocated_bytes": (
            torch_module.cuda.max_memory_allocated(device) if device.type == "cuda" else None
        ),
        "cuda_peak_reserved_bytes": (
            torch_module.cuda.max_memory_reserved(device) if device.type == "cuda" else None
        ),
    }
    return tuple(increments), inference, metadata


def _position_reference_at_camera_frames(
    sequence: Any,
    reference: Any,
    *,
    max_bracket_interval_ns: int,
) -> tuple[tuple[Any, ...], dict[str, object]]:
    from compact_vio.data.euroc import EuRoCDataError
    from compact_vio.data.euroc_position import interpolate_euroc_position
    from compact_vio.evaluation.position_magnitude import TimedPosition, TimedPositionPair

    first = reference.positions[0].timestamp_ns
    last = reference.positions[-1].timestamp_ns
    reference_timestamps = tuple(position.timestamp_ns for position in reference.positions)
    associated: dict[int, Any] = {}
    exact_count = 0
    interpolated_count = 0
    rejected_outside_count = 0
    rejected_gap_count = 0
    maximum_selected_bracket_ns = 0
    maximum_observed_bracket_ns = 0
    for frame in sequence.camera_frames:
        timestamp_ns = frame.timestamp_ns
        if timestamp_ns < first or timestamp_ns > last:
            rejected_outside_count += 1
            continue
        right_index = bisect.bisect_left(reference_timestamps, timestamp_ns)
        is_exact = (
            right_index < len(reference_timestamps)
            and reference_timestamps[right_index] == timestamp_ns
        )
        bracket_ns = 0
        if not is_exact:
            bracket_ns = reference_timestamps[right_index] - reference_timestamps[right_index - 1]
            maximum_observed_bracket_ns = max(maximum_observed_bracket_ns, bracket_ns)
            if bracket_ns > max_bracket_interval_ns:
                rejected_gap_count += 1
                continue
        try:
            interpolated = interpolate_euroc_position(
                reference,
                timestamp_ns,
                max_bracket_interval_ns=max_bracket_interval_ns,
            )
        except EuRoCDataError as exc:
            raise LearningError(f"cannot associate Leica position: {exc}") from exc
        if is_exact:
            exact_count += 1
        else:
            interpolated_count += 1
            maximum_selected_bracket_ns = max(maximum_selected_bracket_ns, bracket_ns)
        associated[timestamp_ns] = TimedPosition(
            sequence_id=sequence.sequence_id,
            timestamp_ns=timestamp_ns,
            position_world_m=interpolated.position_rs_r_m,
        )

    pairs = []
    retained_segment_count = 0
    previous_retained_end: int | None = None
    for previous_frame, current_frame in zip(
        sequence.camera_frames,
        sequence.camera_frames[1:],
        strict=False,
    ):
        previous = associated.get(previous_frame.timestamp_ns)
        current = associated.get(current_frame.timestamp_ns)
        if previous is not None and current is not None:
            if previous_retained_end != previous.timestamp_ns:
                retained_segment_count += 1
            pairs.append(TimedPositionPair(previous, current))
            previous_retained_end = current.timestamp_ns
    if not pairs:
        raise LearningError("no native camera pair has two accepted Leica associations")
    evidence = {
        "policy_max_bracket_interval_ns": max_bracket_interval_ns,
        "camera_frame_count": len(sequence.camera_frames),
        "associated_camera_frame_count": len(associated),
        "native_exact_camera_frame_count": exact_count,
        "linearly_interpolated_camera_frame_count": interpolated_count,
        "rejected_outside_coverage_camera_frame_count": rejected_outside_count,
        "rejected_over_gap_camera_frame_count": rejected_gap_count,
        "maximum_selected_interpolation_bracket_ns": maximum_selected_bracket_ns,
        "maximum_observed_interpolation_bracket_ns": maximum_observed_bracket_ns,
        "eligible_native_pair_count": len(pairs),
        "rejected_native_pair_count": (len(sequence.camera_frames) - 1 - len(pairs)),
        "retained_contiguous_segment_count": retained_segment_count,
    }
    return tuple(pairs), evidence


def _scored_predictions(
    reference_pairs: tuple[Any, ...],
    increments: tuple[Any, ...],
) -> tuple[Any, ...]:
    by_identity = {
        (increment.start_timestamp_ns, increment.end_timestamp_ns): increment
        for increment in increments
    }
    if len(by_identity) != len(increments):
        raise LearningError("candidate predictions contain duplicate timestamp pairs")
    result = []
    for pair in reference_pairs:
        key = (pair.previous.timestamp_ns, pair.current.timestamp_ns)
        try:
            result.append(by_identity[key])
        except KeyError as exc:
            raise LearningError(f"candidate is missing reference-covered pair {key!r}") from exc
    return tuple(result)


def _prediction_rows(
    increments: tuple[Any, ...],
    reference_by_pair: Mapping[tuple[int, int], tuple[Any, Any]],
    *,
    sensor_origin_offset_prediction_frame_m: tuple[float, float, float],
) -> list[dict[str, object]]:
    from compact_vio.evaluation.position_magnitude import project_sensor_point_increment

    rows: list[dict[str, object]] = []
    for increment in increments:
        key = (increment.start_timestamp_ns, increment.end_timestamp_ns)
        position_pair = reference_by_pair.get(key)
        reference_payload: dict[str, object] | None = None
        if position_pair is not None:
            previous, current = position_pair
            displacement = math.dist(previous.position_world_m, current.position_world_m)
            reference_payload = {
                "previous_position_world_m": list(previous.position_world_m),
                "current_position_world_m": list(current.position_world_m),
                "displacement_magnitude_m": displacement,
            }
        projected = project_sensor_point_increment(
            increment,
            sensor_origin_offset_prediction_frame_m=(sensor_origin_offset_prediction_frame_m),
        )
        rows.append(
            {
                "sequence_id": increment.sequence_id,
                "previous_timestamp_ns": increment.start_timestamp_ns,
                "current_timestamp_ns": increment.end_timestamp_ns,
                "prediction": {
                    "translation_previous_body_m": list(increment.translation_previous_body_m),
                    "rotation_vector_previous_to_current_rad": list(
                        increment.rotation_vector_previous_to_current_rad
                    ),
                    "leica_origin_translation_previous_imu_m": list(
                        projected.translation_previous_body_m
                    ),
                    "leica_origin_displacement_magnitude_m": math.hypot(
                        *projected.translation_previous_body_m
                    ),
                },
                "position_reference": reference_payload,
                "reference_rotation_available": False,
                "predicted_rotation_used_for_sensor_point_projection": True,
            }
        )
    return rows


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    try:
        with path.open("x", encoding="utf-8") as handle:
            for row in rows:
                json.dump(row, handle, sort_keys=True, allow_nan=False)
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except (OSError, TypeError, ValueError) as exc:
        raise LearningError(f"cannot write predictions artifact {path}: {exc}") from exc


def _run(args: argparse.Namespace) -> int:
    try:
        import torch

        from compact_vio.data.euroc import (
            load_euroc_sensor_sequence,
            sensor_calibration_sources_sha256,
            sensor_sequence_sources_sha256,
        )
        from compact_vio.data.euroc_position import (
            leica_origin_in_imu_frame,
            load_euroc_position_reference,
            position_reference_sources_sha256,
        )
        from compact_vio.evaluation.position_magnitude import (
            evaluate_displacement_magnitude_pairs,
            zero_motion_displacement_magnitude_pairs,
        )
    except ImportError as exc:
        raise LearningError(
            "position evaluation requires the project train extra (PyTorch, Pillow, and PyYAML)"
        ) from exc

    started_at = _utc_now()
    started_monotonic = time.monotonic()
    protocol = load_position_evaluation_protocol(args.protocol)
    execution_git_revision = _git_revision(
        protocol.source_path,
        expected_source_sha256=protocol.source_sha256,
    )
    checkpoints = _resolve_checkpoints(protocol, args.checkpoint)
    _preflight_candidate_checkpoints(
        protocol,
        checkpoints,
        expected_dataset_id=f"EuRoC DOI {protocol.dataset.doi}",
    )
    archive = _regular_file(args.archive, field="archive")
    size, md5, archive_sha256 = _archive_hashes(archive)
    if (
        size != protocol.dataset.archive_size_bytes
        or md5 != protocol.dataset.archive_md5
        or archive_sha256 != protocol.dataset.archive_sha256
    ):
        raise LearningError("archive identity does not match the frozen evaluation protocol")
    output = _prepare_output_directory(args.output_dir)
    data_root = Path(args.data_root).resolve(strict=True)
    sequence_root = data_root / protocol.dataset.sequence_id
    sequence = load_euroc_sensor_sequence(sequence_root)
    reference = load_euroc_position_reference(sequence_root)
    if sequence.sequence_id != reference.sequence_id:
        raise LearningError("sensor and position-reference sequence identifiers differ")
    sensor_origin_offset = leica_origin_in_imu_frame(
        sequence.imu_calibration,
        reference.calibration,
    )

    observed_sensor_sha256 = sensor_sequence_sources_sha256(sequence_root)
    observed_calibration_sha256 = sensor_calibration_sources_sha256(sequence_root)
    observed_reference_sha256 = position_reference_sources_sha256(sequence_root)
    if observed_sensor_sha256 != protocol.dataset.sensor_sources_sha256:
        raise LearningError("sensor source SHA-256 does not match the protocol")
    if observed_calibration_sha256 != protocol.dataset.sensor_calibration_sha256:
        raise LearningError("sensor calibration SHA-256 does not match the protocol")
    if observed_reference_sha256 != protocol.dataset.position_reference_sha256:
        raise LearningError("position-reference SHA-256 does not match the protocol")

    scored_reference_pairs, association_evidence = _position_reference_at_camera_frames(
        sequence,
        reference,
        max_bracket_interval_ns=(protocol.sampling.max_reference_bracket_interval_ns),
    )
    sensor_pair_count = len(sequence.camera_frames) - protocol.sampling.frame_stride
    if sensor_pair_count <= 0:
        raise LearningError("sensor sequence contains no native camera pair")
    reference_by_pair = {
        (pair.previous.timestamp_ns, pair.current.timestamp_ns): (
            pair.previous,
            pair.current,
        )
        for pair in scored_reference_pairs
    }
    baseline = zero_motion_displacement_magnitude_pairs(
        scored_reference_pairs,
        sensor_origin_offset_prediction_frame_m=sensor_origin_offset,
    )
    device = _select_device(torch, args.device)
    candidate_results: list[dict[str, object]] = []
    pending_prediction_rows: list[tuple[str, list[dict[str, object]]]] = []
    decision_inputs: list[CandidateDecisionInput] = []
    expected_prediction_identities: tuple[tuple[int, int], ...] | None = None

    for candidate in protocol.candidates:
        increments, inference, metadata = _candidate_predictions(
            candidate=candidate,
            checkpoint_path=checkpoints[candidate.candidate_id],
            sequence=sequence,
            device=device,
            evaluation_unroll_pairs=protocol.sampling.evaluation_unroll_pairs,
            torch_module=torch,
            expected_dataset_id=f"EuRoC DOI {protocol.dataset.doi}",
        )
        identities = tuple(
            (increment.start_timestamp_ns, increment.end_timestamp_ns) for increment in increments
        )
        if expected_prediction_identities is None:
            expected_prediction_identities = identities
        elif identities != expected_prediction_identities:
            raise LearningError("candidate output identities/order differ")
        scored = _scored_predictions(scored_reference_pairs, increments)
        metrics = evaluate_displacement_magnitude_pairs(
            scored_reference_pairs,
            scored,
            sensor_origin_offset_prediction_frame_m=sensor_origin_offset,
        )
        prediction_rows = _prediction_rows(
            increments,
            reference_by_pair,
            sensor_origin_offset_prediction_frame_m=sensor_origin_offset,
        )
        checkpoint_provenance = asdict(metadata.provenance)
        result = {
            "candidate_id": candidate.candidate_id,
            "checkpoint": {
                "path": str(checkpoints[candidate.candidate_id]),
                "sha256": candidate.checkpoint_sha256,
                "epoch": metadata.epoch,
                "training_config": metadata.config.to_dict(),
                "training_metrics": metadata.metrics,
                "provenance": checkpoint_provenance,
            },
            "inference": inference,
            "coverage": {
                "sensor_pair_count": sensor_pair_count,
                "produced_pair_count": len(increments),
                "reference_pair_count": len(scored_reference_pairs),
                "scored_pair_count": len(scored),
                "reference_excluded_sensor_pair_count": (
                    sensor_pair_count - len(scored_reference_pairs)
                ),
            },
            "position_only_metrics": asdict(metrics),
        }
        pending_prediction_rows.append((candidate.candidate_id, prediction_rows))
        candidate_results.append(result)
        decision_inputs.append(
            CandidateDecisionInput(
                candidate_id=candidate.candidate_id,
                sensor_pair_count=sensor_pair_count,
                produced_pair_count=len(increments),
                reference_pair_count=len(scored_reference_pairs),
                scored_pair_count=len(scored),
                pair_displacement_magnitude_rmse_m=(metrics.pair_displacement_magnitude_rmse_m),
                cumulative_scored_distance_rmse_m=(metrics.cumulative_scored_distance_rmse_m),
                scored_distance_ratio=metrics.scored_distance_ratio,
            )
        )

    decision = apply_position_decision_rule(
        protocol,
        tuple(decision_inputs),
        zero_motion_pair_rmse_m=baseline.pair_displacement_magnitude_rmse_m,
    )

    if _sha256(protocol.source_path) != protocol.source_sha256:
        raise LearningError("evaluation protocol changed during execution")
    if (
        _git_revision(
            protocol.source_path,
            expected_source_sha256=protocol.source_sha256,
        )
        != execution_git_revision
    ):
        raise LearningError("git revision changed during execution")
    if _archive_hashes(archive) != (
        protocol.dataset.archive_size_bytes,
        protocol.dataset.archive_md5,
        protocol.dataset.archive_sha256,
    ):
        raise LearningError("archive changed during execution")
    for candidate in protocol.candidates:
        if _sha256(checkpoints[candidate.candidate_id]) != candidate.checkpoint_sha256:
            raise LearningError(f"checkpoint {candidate.candidate_id!r} changed during execution")
    if (
        sensor_sequence_sources_sha256(sequence_root) != protocol.dataset.sensor_sources_sha256
        or sensor_calibration_sources_sha256(sequence_root)
        != protocol.dataset.sensor_calibration_sha256
        or position_reference_sources_sha256(sequence_root)
        != protocol.dataset.position_reference_sha256
    ):
        raise LearningError("extracted source bytes changed during execution")

    # Publish only after every candidate, metric, identity, and decision validates.
    for (candidate_id, rows), result in zip(
        pending_prediction_rows,
        candidate_results,
        strict=True,
    ):
        predictions_path = output / f"{candidate_id}-predictions.jsonl"
        _write_jsonl(predictions_path, rows)
        result["predictions_artifact"] = {
            "filename": predictions_path.name,
            "sha256": _sha256(predictions_path),
        }
        metrics_path = output / f"{candidate_id}-metrics.json"
        _write_json(metrics_path, result)
        result["metrics_artifact"] = {
            "filename": metrics_path.name,
            "sha256": _sha256(metrics_path),
        }
    summary = {
        "record_type": "euroc_position_only_checkpoint_evaluation_result",
        "schema_version": "1.0.0",
        "status": "completed",
        "evaluation_id": protocol.evaluation_id,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "duration_seconds": time.monotonic() - started_monotonic,
        "git_revision": execution_git_revision,
        "device": str(device),
        "torch_version": torch.__version__,
        "cuda_device_name": (torch.cuda.get_device_name(device) if device.type == "cuda" else None),
        "protocol": {
            "path": str(protocol.source_path),
            "sha256": protocol.source_sha256,
            "metric_policy_id": protocol.metric_policy_id,
            "reference_association_policy_id": (protocol.sampling.reference_association_policy_id),
            "sensor_origin_projection_policy_id": (
                protocol.sampling.sensor_origin_projection_policy_id
            ),
            "validation_guardrail": (
                asdict(protocol.validation_guardrail)
                if protocol.validation_guardrail is not None
                else None
            ),
        },
        "dataset": {
            **asdict(protocol.dataset),
            "archive_verified_path": str(archive),
            "sensor_root": str(sequence_root.resolve(strict=True)),
            "camera_frame_count": len(sequence.camera_frames),
            "imu_measurement_count": len(sequence.imu_measurements),
            "position_reference_count": len(reference.positions),
            "reference_association": association_evidence,
            "imu0_t_bs": sequence.imu_calibration.t_bs,
            "leica0_t_bs": reference.calibration.t_bs,
            "leica_origin_in_imu_frame_m": sensor_origin_offset,
        },
        "zero_motion_position_only_metrics": asdict(baseline),
        "candidates": candidate_results,
        "decision": decision,
        "limitations": [
            "Machine Hall Leica reference supplies position only; no independent rotation "
            "endpoint is scored.",
            "Predicted rotation affects the Leica-point displacement through the declared "
            "IMU-to-Leica lever arm.",
            "Displacement magnitudes do not measure direction, heading, ATE, or final pose.",
            "This fresh endpoint does not erase the prior V2_03-informed exploratory history.",
            "A selected position-endpoint candidate is not flight/deployment/publication approval.",
        ],
    }
    summary_path = output / "evaluation-summary.json"
    _write_json(summary_path, summary)
    print(
        json.dumps(
            {
                "event": "evaluation_complete",
                "summary": str(summary_path),
                "summary_sha256": _sha256(summary_path),
                "decision": decision["decision"],
                "selected_candidate_id": decision["selected_candidate_id"],
            },
            sort_keys=True,
            allow_nan=False,
        ),
        flush=True,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {"event": "evaluation_failed", "error_type": type(exc).__name__, "error": str(exc)},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CandidateDecisionInput",
    "PositionCheckpointProvenance",
    "PositionDatasetIdentity",
    "PositionEvaluationCandidate",
    "PositionEvaluationProtocol",
    "PositionEvaluationSampling",
    "PositionValidationGuardrail",
    "apply_position_decision_rule",
    "build_parser",
    "load_position_evaluation_protocol",
    "main",
]

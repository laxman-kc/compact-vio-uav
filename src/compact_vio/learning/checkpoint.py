"""Validated, portable checkpoints for compact learned VIO."""

from __future__ import annotations

import math
import os
import pickle
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from compact_vio.learning.config import TrainingConfig
from compact_vio.learning.errors import LearningDependencyError, LearningError

try:
    import torch
    from torch import nn
    from torch.optim import Optimizer
except ImportError as exc:  # pragma: no cover - dependency-light installation
    raise LearningDependencyError(
        "PyTorch is required for checkpoint operations; install the training extra"
    ) from exc

_SCHEMA_VERSION = 1


def _non_empty_text(value: object, *, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise LearningError(f"{field} must be a non-empty string")


def _sequence_ids(values: Sequence[str], *, field: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise LearningError(f"{field} must be a sequence of identifiers, not a string")
    result = tuple(values)
    if not result or any(type(value) is not str or not value.strip() for value in result):
        raise LearningError(f"{field} must contain non-empty sequence identifiers")
    if len(result) != len(set(result)):
        raise LearningError(f"{field} must not contain duplicates")
    return result


def _hashes(values: Mapping[str, str], *, field: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, Mapping) or not values:
        raise LearningError(f"{field} must be a non-empty mapping")
    result: list[tuple[str, str]] = []
    for key, digest in values.items():
        _non_empty_text(key, field=f"{field} key")
        if type(digest) is not str or len(digest) != 64:
            raise LearningError(f"{field}[{key!r}] must be a lowercase SHA-256 digest")
        try:
            int(digest, 16)
        except ValueError as exc:
            raise LearningError(f"{field}[{key!r}] must be a lowercase SHA-256 digest") from exc
        if digest != digest.lower():
            raise LearningError(f"{field}[{key!r}] must be a lowercase SHA-256 digest")
        result.append((key, digest))
    return tuple(sorted(result))


def _hash_pairs(values: object, *, field: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(values, (list, tuple)) or not values:
        raise LearningError(f"{field} must contain key/digest pairs")
    pairs: list[tuple[str, str]] = []
    for item in values:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise LearningError(f"{field} must contain key/digest pairs")
        key, digest = item
        if type(key) is not str or type(digest) is not str:
            raise LearningError(f"{field} must contain string key/digest pairs")
        pairs.append((key, digest))
    if len({key for key, _ in pairs}) != len(pairs):
        raise LearningError(f"{field} must not repeat a key")
    return _hashes(dict(pairs), field=field)


@dataclass(frozen=True, slots=True)
class CheckpointProvenance:
    """Data, split, calibration, and code identity bound to a checkpoint."""

    dataset_id: str
    split_id: str
    train_sequence_ids: tuple[str, ...]
    validation_sequence_ids: tuple[str, ...]
    source_sha256: tuple[tuple[str, str], ...]
    calibration_sha256: tuple[tuple[str, str], ...]
    code_revision: str

    def __post_init__(self) -> None:
        _non_empty_text(self.dataset_id, field="dataset_id")
        _non_empty_text(self.split_id, field="split_id")
        _non_empty_text(self.code_revision, field="code_revision")
        object.__setattr__(
            self,
            "train_sequence_ids",
            _sequence_ids(self.train_sequence_ids, field="train_sequence_ids"),
        )
        object.__setattr__(
            self,
            "validation_sequence_ids",
            _sequence_ids(self.validation_sequence_ids, field="validation_sequence_ids"),
        )
        overlap = set(self.train_sequence_ids) & set(self.validation_sequence_ids)
        if overlap:
            raise LearningError(
                f"checkpoint train/validation sequences overlap: {sorted(overlap)!r}"
            )
        object.__setattr__(
            self,
            "source_sha256",
            _hash_pairs(self.source_sha256, field="source_sha256"),
        )
        object.__setattr__(
            self,
            "calibration_sha256",
            _hash_pairs(self.calibration_sha256, field="calibration_sha256"),
        )
        expected_sequences = set(self.train_sequence_ids) | set(self.validation_sequence_ids)
        missing_source = expected_sequences - {key for key, _ in self.source_sha256}
        missing_calibration = expected_sequences - {key for key, _ in self.calibration_sha256}
        if missing_source or missing_calibration:
            raise LearningError(
                "checkpoint provenance is missing sequence hashes: "
                f"source={sorted(missing_source)!r}, calibration={sorted(missing_calibration)!r}"
            )

    @classmethod
    def create(
        cls,
        *,
        dataset_id: str,
        split_id: str,
        train_sequence_ids: Sequence[str],
        validation_sequence_ids: Sequence[str],
        source_sha256: Mapping[str, str],
        calibration_sha256: Mapping[str, str],
        code_revision: str,
    ) -> CheckpointProvenance:
        return cls(
            dataset_id=dataset_id,
            split_id=split_id,
            train_sequence_ids=tuple(train_sequence_ids),
            validation_sequence_ids=tuple(validation_sequence_ids),
            source_sha256=_hashes(source_sha256, field="source_sha256"),
            calibration_sha256=_hashes(calibration_sha256, field="calibration_sha256"),
            code_revision=code_revision,
        )


@dataclass(frozen=True, slots=True)
class LoadedCheckpoint:
    """Validated checkpoint metadata returned after restoring model state."""

    config: TrainingConfig
    epoch: int
    metrics: dict[str, float]
    provenance: CheckpointProvenance


def _metrics(values: Mapping[str, int | float]) -> dict[str, float]:
    if not isinstance(values, Mapping) or not values:
        raise LearningError("metrics must be a non-empty mapping")
    result: dict[str, float] = {}
    for name, value in values.items():
        _non_empty_text(name, field="metric name")
        if type(value) not in (int, float) or not math.isfinite(float(value)):
            raise LearningError(f"metric {name!r} must be finite")
        result[name] = float(value)
    return result


def save_checkpoint(
    path: os.PathLike[str] | str,
    *,
    model: nn.Module,
    config: TrainingConfig,
    epoch: int,
    metrics: Mapping[str, int | float],
    provenance: CheckpointProvenance,
    optimizer: Optimizer | None = None,
) -> Path:
    """Atomically save a CPU-portable checkpoint with full run identity."""

    if not isinstance(model, nn.Module):
        raise LearningError("model must be a torch.nn.Module")
    if not isinstance(config, TrainingConfig):
        raise LearningError("config must be a TrainingConfig")
    declared_model_config = getattr(model, "config", None)
    if declared_model_config is not None and declared_model_config != config.model:
        raise LearningError("TrainingConfig.model does not match the supplied model")
    if type(epoch) is not int or epoch < 0:
        raise LearningError("epoch must be a non-negative integer")
    if not isinstance(provenance, CheckpointProvenance):
        raise LearningError("provenance must be CheckpointProvenance")
    metric_values = _metrics(metrics)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise LearningError(f"checkpoint destination is not a regular file: {destination}")
    payload: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "config": config.to_dict(),
        "epoch": epoch,
        "metrics": metric_values,
        "provenance": asdict(provenance),
        "model_state_dict": {
            name: tensor.detach().to(device="cpu") for name, tensor in model.state_dict().items()
        },
        "optimizer_state_dict": optimizer.state_dict() if optimizer is not None else None,
    }
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(destination)
    except (OSError, RuntimeError) as exc:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise LearningError(f"cannot save checkpoint {destination}: {exc}") from exc
    return destination.resolve()


def _parse_provenance(value: object) -> CheckpointProvenance:
    if not isinstance(value, Mapping):
        raise LearningError("checkpoint provenance must be a mapping")
    required = {
        "dataset_id",
        "split_id",
        "train_sequence_ids",
        "validation_sequence_ids",
        "source_sha256",
        "calibration_sha256",
        "code_revision",
    }
    if set(value) != required:
        raise LearningError("checkpoint provenance has unexpected fields")
    try:
        return CheckpointProvenance(
            dataset_id=value["dataset_id"],  # type: ignore[arg-type]
            split_id=value["split_id"],  # type: ignore[arg-type]
            train_sequence_ids=tuple(value["train_sequence_ids"]),  # type: ignore[arg-type]
            validation_sequence_ids=tuple(value["validation_sequence_ids"]),  # type: ignore[arg-type]
            source_sha256=tuple(tuple(item) for item in value["source_sha256"]),  # type: ignore[arg-type]
            calibration_sha256=tuple(
                tuple(item)
                for item in value["calibration_sha256"]  # type: ignore[arg-type]
            ),
            code_revision=value["code_revision"],  # type: ignore[arg-type]
        )
    except (TypeError, KeyError) as exc:
        raise LearningError(f"invalid checkpoint provenance: {exc}") from exc


def load_checkpoint(
    path: os.PathLike[str] | str,
    *,
    model: nn.Module,
    optimizer: Optimizer | None = None,
    map_location: torch.device | str = "cpu",
    expected_config: TrainingConfig | None = None,
    expected_provenance: CheckpointProvenance | None = None,
) -> LoadedCheckpoint:
    """Load a weights-only-safe checkpoint and strictly restore model state.

    Callers resuming or evaluating a just-completed run can bind the complete
    expected configuration and provenance. Those checks occur before any model
    or optimizer state is restored.
    """

    source = Path(path)
    if not source.is_file() or source.is_symlink():
        raise LearningError(f"checkpoint must be a regular non-symlink file: {source}")
    if not isinstance(model, nn.Module):
        raise LearningError("model must be a torch.nn.Module")
    if expected_config is not None and type(expected_config) is not TrainingConfig:
        raise LearningError("expected_config must be a TrainingConfig or None")
    if expected_provenance is not None and type(expected_provenance) is not CheckpointProvenance:
        raise LearningError("expected_provenance must be CheckpointProvenance or None")
    try:
        payload = torch.load(source, map_location=map_location, weights_only=True)
    except (OSError, RuntimeError, ValueError, EOFError, pickle.UnpicklingError) as exc:
        raise LearningError(f"cannot load checkpoint {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LearningError("checkpoint payload must be a mapping")
    required = {
        "schema_version",
        "config",
        "epoch",
        "metrics",
        "provenance",
        "model_state_dict",
        "optimizer_state_dict",
    }
    if set(payload) != required or payload["schema_version"] != _SCHEMA_VERSION:
        raise LearningError("checkpoint schema is unsupported or incomplete")
    config = TrainingConfig.from_dict(payload["config"])
    if expected_config is not None and config != expected_config:
        raise LearningError("checkpoint training configuration differs from the expected run")
    declared_model_config = getattr(model, "config", None)
    if declared_model_config is not None and declared_model_config != config.model:
        raise LearningError("checkpoint config does not match the supplied model architecture")
    epoch = payload["epoch"]
    if type(epoch) is not int or epoch < 0:
        raise LearningError("checkpoint epoch must be a non-negative integer")
    metrics = _metrics(payload["metrics"])
    provenance = _parse_provenance(payload["provenance"])
    if expected_provenance is not None and provenance != expected_provenance:
        raise LearningError("checkpoint provenance differs from the expected run")
    try:
        model.load_state_dict(payload["model_state_dict"], strict=True)
        if optimizer is not None:
            optimizer_state = payload["optimizer_state_dict"]
            if optimizer_state is None:
                raise LearningError("checkpoint does not contain optimizer state")
            optimizer.load_state_dict(optimizer_state)
    except LearningError:
        raise
    except (RuntimeError, TypeError, ValueError) as exc:
        raise LearningError(f"checkpoint state is incompatible: {exc}") from exc
    return LoadedCheckpoint(config=config, epoch=epoch, metrics=metrics, provenance=provenance)


__all__ = [
    "CheckpointProvenance",
    "LoadedCheckpoint",
    "load_checkpoint",
    "save_checkpoint",
]

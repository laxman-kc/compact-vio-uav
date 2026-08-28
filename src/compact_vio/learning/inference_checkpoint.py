"""Strict, optimizer-free checkpoints for production learned-VIO inference.

Training checkpoints intentionally contain optimizer and experiment-selection
state.  This module projects one validated training checkpoint into a smaller
inference contract containing only weights and the identities needed to
reproduce their interpretation.  The source is loaded through the existing
``load_inference_model`` path, and exported models continue to execute through
``predict_batch`` or ``predict_sequence_batch``.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import pickle
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compact_vio.learning.checkpoint import CheckpointProvenance
from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
from compact_vio.learning.errors import LearningDependencyError, LearningError
from compact_vio.learning.model import CompactVIO

try:
    import torch
    from torch import Tensor
except ImportError as exc:  # pragma: no cover - dependency-light installation
    raise LearningDependencyError(
        "PyTorch is required for inference checkpoint operations; install the training extra"
    ) from exc


INDEPENDENT_INFERENCE_POLICY_ID = "independent-zero-state-per-pair/v1"
STATEFUL_INFERENCE_POLICY_ID = "stateful-contiguous-native-pairs/v1"
INFERENCE_POLICY_IDS = frozenset({INDEPENDENT_INFERENCE_POLICY_ID, STATEFUL_INFERENCE_POLICY_ID})

INFERENCE_CHECKPOINT_RECORD_TYPE = "compact_vio_inference_checkpoint"
INFERENCE_CHECKPOINT_SCHEMA_VERSION = "1.0.0"
_METADATA_RECORD_TYPE = "compact_vio_inference_checkpoint_metadata"
_METADATA_SCHEMA_VERSION = "1.0.0"
_MOTION_VECTOR_LAYOUT_ID = "translation-meters-xyz/rotation-vector-radians-xyz/v1"
_PAIR_EXECUTION_API_ID = "compact_vio.learning.inference.predict_batch/v1"
_SEQUENCE_EXECUTION_API_ID = "compact_vio.learning.inference.predict_sequence_batch/v1"
_STATE_DIGEST_DOMAIN = b"compact-vio-model-state/v1\0"
_SHA256_HEX_LENGTH = 64
_READ_CHUNK_BYTES = 8 * 1024 * 1024
_TRAINING_CHECKPOINT_FIELDS = {
    "config",
    "epoch",
    "metrics",
    "model_state_dict",
    "optimizer_state_dict",
    "provenance",
    "schema_version",
}


def _exact_mapping(value: object, expected: set[str], *, field: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise LearningError(f"{field} must be an object with string keys")
    if set(value) != expected:
        raise LearningError(f"{field} fields must equal {sorted(expected)!r}")
    return value


def _sha256_digest(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LearningError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _inference_policy(value: object, *, field: str = "inference_policy_id") -> str:
    if type(value) is not str or value not in INFERENCE_POLICY_IDS:
        raise LearningError(f"{field} must identify one of {sorted(INFERENCE_POLICY_IDS)!r}")
    return value


def _selected_metrics(values: object) -> tuple[tuple[str, float], ...]:
    if not isinstance(values, Mapping) or not values:
        raise LearningError("selected source metrics must be a non-empty mapping")
    result: list[tuple[str, float]] = []
    for name, value in values.items():
        if type(name) is not str or not name.strip():
            raise LearningError("selected source metric names must be non-empty strings")
        if type(value) not in (int, float) or not math.isfinite(float(value)):
            raise LearningError(f"selected source metric {name!r} must be finite")
        result.append((name, float(value)))
    if len({name for name, _ in result}) != len(result):
        raise LearningError("selected source metrics must not repeat a name")
    return tuple(sorted(result))


def _execution_api_for_policy(inference_policy_id: str) -> str:
    if inference_policy_id == INDEPENDENT_INFERENCE_POLICY_ID:
        return _PAIR_EXECUTION_API_ID
    return _SEQUENCE_EXECUTION_API_ID


def _canonical_metadata_bytes(metadata: Mapping[str, object]) -> bytes:
    """Return the one canonical UTF-8 representation used for metadata hashes."""

    try:
        return json.dumps(
            metadata,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise LearningError(f"inference metadata is not canonical JSON data: {exc}") from exc


def _sha256_file(path: Path, *, field: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise LearningError(f"{field} must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise LearningError(f"cannot hash {field} {path}: {exc}") from exc
    return digest.hexdigest()


def _require_training_checkpoint_record(path: Path) -> None:
    """Reject re-export chains and records outside the legacy training schema."""

    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError, EOFError, pickle.UnpicklingError) as exc:
        raise LearningError(f"cannot inspect source training checkpoint {path}: {exc}") from exc
    if (
        type(payload) is not dict
        or set(payload) != _TRAINING_CHECKPOINT_FIELDS
        or payload.get("schema_version") != 1
    ):
        raise LearningError("source must use the supported training checkpoint schema")


def _tensor_bytes(value: Tensor, *, name: str) -> bytes:
    if value.layout != torch.strided:
        raise LearningError(f"model state tensor {name!r} must use strided layout")
    # ``clone`` guarantees an exact-size, offset-zero storage even when the
    # source is a contiguous view into a larger allocation.  Copying exactly
    # the resulting Torch allocation through the standard library avoids an
    # undeclared NumPy runtime dependency and per-byte Python iteration.
    tensor = (
        value.detach().to(device="cpu").contiguous().clone(memory_format=torch.contiguous_format)
    )
    if tensor.is_floating_point() or tensor.is_complex():
        if not torch.isfinite(tensor).all():
            raise LearningError(f"model state tensor {name!r} contains non-finite values")
    expected_byte_count = tensor.numel() * tensor.element_size()
    try:
        data = ctypes.string_at(tensor.data_ptr(), expected_byte_count)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise LearningError(f"cannot encode model state tensor {name!r}: {exc}") from exc
    if len(data) != expected_byte_count:
        raise LearningError(f"model state tensor {name!r} storage byte count is not exact")
    return data


def model_state_sha256(state_dict: Mapping[str, Tensor]) -> str:
    """Hash names, shapes, dtypes, and exact CPU bytes in canonical key order."""

    if not isinstance(state_dict, Mapping) or not state_dict:
        raise LearningError("model_state_dict must be a non-empty mapping")
    if any(type(name) is not str or not name for name in state_dict):
        raise LearningError("model_state_dict keys must be non-empty strings")
    digest = hashlib.sha256(_STATE_DIGEST_DOMAIN)
    for name in sorted(state_dict):
        tensor = state_dict[name]
        if not isinstance(tensor, Tensor):
            raise LearningError(f"model state value {name!r} must be a torch tensor")
        data = _tensor_bytes(tensor, name=name)
        header = _canonical_metadata_bytes(
            {
                "byte_count": len(data),
                "dtype": str(tensor.dtype),
                "name": name,
                "shape": list(tensor.shape),
            }
        )
        digest.update(len(header).to_bytes(8, byteorder="big", signed=False))
        digest.update(header)
        digest.update(len(data).to_bytes(8, byteorder="big", signed=False))
        digest.update(data)
    return digest.hexdigest()


def _provenance_metadata(provenance: CheckpointProvenance) -> dict[str, object]:
    return {
        "calibration_sha256": [list(item) for item in provenance.calibration_sha256],
        "code_revision": provenance.code_revision,
        "dataset_id": provenance.dataset_id,
        "source_sha256": [list(item) for item in provenance.source_sha256],
        "split_id": provenance.split_id,
        "train_sequence_ids": list(provenance.train_sequence_ids),
        "validation_sequence_ids": list(provenance.validation_sequence_ids),
    }


def _parse_string_list(value: object, *, field: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise LearningError(f"{field} must be an array")
    if any(type(item) is not str for item in value):
        raise LearningError(f"{field} must contain strings")
    return tuple(value)


def _parse_hash_pairs(value: object, *, field: str) -> tuple[tuple[str, str], ...]:
    if type(value) is not list:
        raise LearningError(f"{field} must be an array of key/digest pairs")
    pairs: list[tuple[str, str]] = []
    for index, item in enumerate(value):
        if type(item) is not list or len(item) != 2:
            raise LearningError(f"{field}[{index}] must be a key/digest pair")
        key, digest = item
        if type(key) is not str:
            raise LearningError(f"{field}[{index}] key must be a string")
        pairs.append((key, _sha256_digest(digest, field=f"{field}[{index}] digest")))
    return tuple(pairs)


def _parse_provenance(value: object) -> CheckpointProvenance:
    fields = {
        "calibration_sha256",
        "code_revision",
        "dataset_id",
        "source_sha256",
        "split_id",
        "train_sequence_ids",
        "validation_sequence_ids",
    }
    item = _exact_mapping(value, fields, field="metadata.provenance")
    try:
        return CheckpointProvenance(
            dataset_id=item["dataset_id"],
            split_id=item["split_id"],
            train_sequence_ids=_parse_string_list(
                item["train_sequence_ids"], field="metadata.provenance.train_sequence_ids"
            ),
            validation_sequence_ids=_parse_string_list(
                item["validation_sequence_ids"],
                field="metadata.provenance.validation_sequence_ids",
            ),
            source_sha256=_parse_hash_pairs(
                item["source_sha256"], field="metadata.provenance.source_sha256"
            ),
            calibration_sha256=_parse_hash_pairs(
                item["calibration_sha256"],
                field="metadata.provenance.calibration_sha256",
            ),
            code_revision=item["code_revision"],
        )
    except TypeError as exc:
        raise LearningError(f"invalid inference checkpoint provenance: {exc}") from exc


def _parse_training_config(value: object) -> TrainingConfig:
    if not isinstance(value, Mapping):
        raise LearningError("metadata.training_config must be a mapping")
    return TrainingConfig.from_dict(value)


@dataclass(frozen=True, slots=True)
class InferenceCheckpointIdentity:
    """Exact model, preprocessing, state-policy, source, and data identity."""

    training_config: TrainingConfig
    inference_policy_id: str
    provenance: CheckpointProvenance
    source_checkpoint_sha256: str
    model_state_sha256: str
    selected_source_epoch: int
    selected_source_metrics: tuple[tuple[str, float], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.training_config, TrainingConfig):
            raise LearningError("training_config must be a TrainingConfig")
        object.__setattr__(
            self,
            "inference_policy_id",
            _inference_policy(self.inference_policy_id),
        )
        if not isinstance(self.provenance, CheckpointProvenance):
            raise LearningError("provenance must be CheckpointProvenance")
        _sha256_digest(self.source_checkpoint_sha256, field="source_checkpoint_sha256")
        _sha256_digest(self.model_state_sha256, field="model_state_sha256")
        if type(self.selected_source_epoch) is not int or self.selected_source_epoch < 0:
            raise LearningError("selected_source_epoch must be a non-negative integer")
        if type(self.selected_source_metrics) is not tuple or any(
            type(item) is not tuple or len(item) != 2 for item in self.selected_source_metrics
        ):
            raise LearningError("selected_source_metrics must contain name/value pairs")
        names = tuple(item[0] for item in self.selected_source_metrics)
        if any(type(name) is not str or not name.strip() for name in names):
            raise LearningError("selected source metric names must be non-empty strings")
        if len(set(names)) != len(names):
            raise LearningError("selected source metrics must not repeat a name")
        object.__setattr__(
            self,
            "selected_source_metrics",
            _selected_metrics(dict(self.selected_source_metrics)),
        )

    @property
    def model_config(self) -> ModelConfig:
        """Return the exact architecture identity from the selected checkpoint."""

        return self.training_config.model

    @property
    def data_config(self) -> DataConfig:
        """Return the exact preprocessing identity from the selected checkpoint."""

        return self.training_config.data

    @property
    def metrics(self) -> dict[str, float]:
        """Return the selected checkpoint metrics without any epoch history."""

        return dict(self.selected_source_metrics)

    @property
    def execution_api_id(self) -> str:
        """Return the only prediction API compatible with the bound state policy."""

        return _execution_api_for_policy(self.inference_policy_id)

    def to_metadata(self) -> dict[str, object]:
        """Return the canonical JSON-compatible metadata object."""

        return {
            "model_state_sha256": self.model_state_sha256,
            "provenance": _provenance_metadata(self.provenance),
            "record_type": _METADATA_RECORD_TYPE,
            "runtime": {
                "execution_api_id": self.execution_api_id,
                "inference_policy_id": self.inference_policy_id,
                "motion_vector_layout_id": _MOTION_VECTOR_LAYOUT_ID,
            },
            "schema_version": _METADATA_SCHEMA_VERSION,
            "source_lineage": {
                "checkpoint_sha256": self.source_checkpoint_sha256,
                "selected_epoch": self.selected_source_epoch,
                "selected_metrics": self.metrics,
            },
            "training_config": self.training_config.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ExportedInferenceCheckpoint:
    """Integrity identities returned after a successful exclusive export."""

    path: Path
    artifact_sha256: str
    metadata_sha256: str
    identity: InferenceCheckpointIdentity


@dataclass(frozen=True, slots=True)
class LoadedInferenceCheckpoint:
    """Strictly restored production model and its verified identities."""

    model: CompactVIO
    identity: InferenceCheckpointIdentity
    artifact_sha256: str
    metadata_sha256: str


def _parse_identity(metadata: object) -> InferenceCheckpointIdentity:
    fields = {
        "model_state_sha256",
        "provenance",
        "record_type",
        "runtime",
        "schema_version",
        "source_lineage",
        "training_config",
    }
    item = _exact_mapping(metadata, fields, field="metadata")
    if (
        item["record_type"] != _METADATA_RECORD_TYPE
        or item["schema_version"] != _METADATA_SCHEMA_VERSION
    ):
        raise LearningError("inference metadata schema is unsupported")
    runtime = _exact_mapping(
        item["runtime"],
        {
            "execution_api_id",
            "inference_policy_id",
            "motion_vector_layout_id",
        },
        field="metadata.runtime",
    )
    policy = _inference_policy(runtime["inference_policy_id"])
    if runtime["execution_api_id"] != _execution_api_for_policy(policy):
        raise LearningError("execution_api_id does not match inference_policy_id")
    if runtime["motion_vector_layout_id"] != _MOTION_VECTOR_LAYOUT_ID:
        raise LearningError("motion_vector_layout_id is unsupported")
    lineage = _exact_mapping(
        item["source_lineage"],
        {"checkpoint_sha256", "selected_epoch", "selected_metrics"},
        field="metadata.source_lineage",
    )
    selected_epoch = lineage["selected_epoch"]
    if type(selected_epoch) is not int or selected_epoch < 0:
        raise LearningError("metadata.source_lineage.selected_epoch must be non-negative")
    return InferenceCheckpointIdentity(
        training_config=_parse_training_config(item["training_config"]),
        inference_policy_id=policy,
        provenance=_parse_provenance(item["provenance"]),
        source_checkpoint_sha256=_sha256_digest(
            lineage["checkpoint_sha256"], field="source_checkpoint_sha256"
        ),
        model_state_sha256=_sha256_digest(item["model_state_sha256"], field="model_state_sha256"),
        selected_source_epoch=selected_epoch,
        selected_source_metrics=_selected_metrics(lineage["selected_metrics"]),
    )


def _cpu_state_dict(model: CompactVIO) -> dict[str, Tensor]:
    return {
        name: tensor.detach().to(device="cpu").contiguous()
        for name, tensor in sorted(model.state_dict().items())
    }


def _write_exclusive_checkpoint(path: Path, payload: Mapping[str, object]) -> Path:
    if path.is_symlink() or path.exists():
        raise LearningError(f"refusing to overwrite inference checkpoint destination: {path}")
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise LearningError(f"inference checkpoint parent must be a regular directory: {parent}")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=parent,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            torch.save(dict(payload), handle)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise LearningError(
                f"refusing to overwrite inference checkpoint destination: {path}"
            ) from exc
    except LearningError:
        raise
    except (OSError, RuntimeError) as exc:
        raise LearningError(f"cannot export inference checkpoint {path}: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path.resolve(strict=True)


def export_inference_checkpoint(
    source_checkpoint: os.PathLike[str] | str,
    destination: os.PathLike[str] | str,
    *,
    expected_source_sha256: str,
    inference_policy_id: str,
) -> ExportedInferenceCheckpoint:
    """Export one training checkpoint as an exclusive, inference-only artifact.

    The expected source hash and inference-state policy are mandatory so an
    operator cannot silently export the wrong selected checkpoint or later
    reinterpret its recurrent state behavior.
    """

    source = Path(source_checkpoint)
    target = Path(destination)
    expected_digest = _sha256_digest(expected_source_sha256, field="expected_source_sha256")
    policy = _inference_policy(inference_policy_id)
    if target.is_symlink() or target.exists():
        raise LearningError(f"refusing to overwrite inference checkpoint destination: {target}")

    source_digest = _sha256_file(source, field="source checkpoint")
    if source_digest != expected_digest:
        raise LearningError(
            f"source checkpoint SHA-256 mismatch: expected {expected_digest}, got {source_digest}"
        )
    _require_training_checkpoint_record(source)
    from compact_vio.learning.inference import load_inference_model

    model, source_metadata = load_inference_model(source, device="cpu")
    if _sha256_file(source, field="source checkpoint") != source_digest:
        raise LearningError("source checkpoint changed while it was being exported")

    state_dict = _cpu_state_dict(model)
    identity = InferenceCheckpointIdentity(
        training_config=source_metadata.config,
        inference_policy_id=policy,
        provenance=source_metadata.provenance,
        source_checkpoint_sha256=source_digest,
        model_state_sha256=model_state_sha256(state_dict),
        selected_source_epoch=source_metadata.epoch,
        selected_source_metrics=_selected_metrics(source_metadata.metrics),
    )
    metadata = identity.to_metadata()
    metadata_sha256 = hashlib.sha256(_canonical_metadata_bytes(metadata)).hexdigest()
    payload: dict[str, object] = {
        "metadata": metadata,
        "metadata_sha256": metadata_sha256,
        "model_state_dict": state_dict,
        "record_type": INFERENCE_CHECKPOINT_RECORD_TYPE,
        "schema_version": INFERENCE_CHECKPOINT_SCHEMA_VERSION,
    }
    output = _write_exclusive_checkpoint(target, payload)
    return ExportedInferenceCheckpoint(
        path=output,
        artifact_sha256=_sha256_file(output, field="inference checkpoint"),
        metadata_sha256=metadata_sha256,
        identity=identity,
    )


def load_inference_checkpoint(
    path: os.PathLike[str] | str,
    *,
    expected_artifact_sha256: str,
    expected_inference_policy_id: str | None = None,
    device: torch.device | str = "cpu",
) -> LoadedInferenceCheckpoint:
    """Verify and strictly restore an inference-only checkpoint.

    ``expected_artifact_sha256`` is a mandatory caller trust root and is checked
    against the exact file bytes used for restoration.  When supplied,
    ``expected_inference_policy_id`` also turns accidental pair-reset versus
    recurrent-carry mismatches into a hard error before predictions.
    """

    source = Path(path)
    expected_policy = (
        _inference_policy(expected_inference_policy_id, field="expected_inference_policy_id")
        if expected_inference_policy_id is not None
        else None
    )
    expected_artifact_digest = _sha256_digest(
        expected_artifact_sha256,
        field="expected_artifact_sha256",
    )
    artifact_sha256 = _sha256_file(source, field="inference checkpoint")
    if artifact_sha256 != expected_artifact_digest:
        raise LearningError(
            "inference artifact SHA-256 mismatch: "
            f"expected {expected_artifact_digest}, got {artifact_sha256}"
        )
    try:
        payload = torch.load(source, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError, EOFError, pickle.UnpicklingError) as exc:
        raise LearningError(f"cannot load inference checkpoint {source}: {exc}") from exc
    if _sha256_file(source, field="inference checkpoint") != artifact_sha256:
        raise LearningError("inference checkpoint changed while it was being loaded")
    item = _exact_mapping(
        payload,
        {
            "metadata",
            "metadata_sha256",
            "model_state_dict",
            "record_type",
            "schema_version",
        },
        field="inference checkpoint",
    )
    if (
        item["record_type"] != INFERENCE_CHECKPOINT_RECORD_TYPE
        or item["schema_version"] != INFERENCE_CHECKPOINT_SCHEMA_VERSION
    ):
        raise LearningError("inference checkpoint schema is unsupported")
    declared_metadata_sha256 = _sha256_digest(item["metadata_sha256"], field="metadata_sha256")
    actual_metadata_sha256 = hashlib.sha256(_canonical_metadata_bytes(item["metadata"])).hexdigest()
    if actual_metadata_sha256 != declared_metadata_sha256:
        raise LearningError("inference checkpoint metadata SHA-256 mismatch")
    identity = _parse_identity(item["metadata"])
    if expected_policy is not None and identity.inference_policy_id != expected_policy:
        raise LearningError(
            "inference policy mismatch: "
            f"artifact declares {identity.inference_policy_id!r}, "
            f"caller expected {expected_policy!r}"
        )
    state_dict = item["model_state_dict"]
    if not isinstance(state_dict, Mapping):
        raise LearningError("model_state_dict must be a mapping")
    actual_state_sha256 = model_state_sha256(state_dict)
    if actual_state_sha256 != identity.model_state_sha256:
        raise LearningError("inference checkpoint model-state SHA-256 mismatch")

    model = CompactVIO(identity.model_config)
    try:
        model.load_state_dict(state_dict, strict=True)
        model.to(device)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise LearningError(f"inference checkpoint state is incompatible: {exc}") from exc
    model.eval()
    return LoadedInferenceCheckpoint(
        model=model,
        identity=identity,
        artifact_sha256=artifact_sha256,
        metadata_sha256=declared_metadata_sha256,
    )


__all__ = [
    "ExportedInferenceCheckpoint",
    "INFERENCE_CHECKPOINT_RECORD_TYPE",
    "INFERENCE_CHECKPOINT_SCHEMA_VERSION",
    "INDEPENDENT_INFERENCE_POLICY_ID",
    "INFERENCE_POLICY_IDS",
    "InferenceCheckpointIdentity",
    "LoadedInferenceCheckpoint",
    "STATEFUL_INFERENCE_POLICY_ID",
    "export_inference_checkpoint",
    "load_inference_checkpoint",
    "model_state_sha256",
]

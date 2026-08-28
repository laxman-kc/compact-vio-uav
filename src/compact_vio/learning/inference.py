"""Deterministic checkpoint loading and batched relative-motion inference."""

from __future__ import annotations

import hashlib
import pickle
from dataclasses import dataclass
from pathlib import Path

from compact_vio.learning.checkpoint import LoadedCheckpoint, load_checkpoint
from compact_vio.learning.dataset import VIOBatch, VIOSequenceBatch
from compact_vio.learning.errors import LearningDependencyError, LearningError
from compact_vio.learning.model import CompactVIO

try:
    import torch
    from torch import Tensor
except ImportError as exc:  # pragma: no cover - dependency-light installation
    raise LearningDependencyError(
        "PyTorch is required for learned VIO inference; install the training extra"
    ) from exc


_READ_CHUNK_BYTES = 8 * 1024 * 1024


def _expected_sha256(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LearningError("expected_checkpoint_sha256 must be a lowercase SHA-256 digest")
    return value


def _sha256_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise LearningError(f"checkpoint must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise LearningError(f"cannot hash checkpoint {path}: {exc}") from exc
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class MotionPrediction:
    """CPU motion vectors produced independently for a source batch."""

    motion_vectors: Tensor


@dataclass(frozen=True, slots=True)
class MotionSequencePrediction:
    """Masked CPU motion vectors plus detached device-resident carry state."""

    motion_vectors: Tensor
    step_mask: Tensor
    final_fusion_state: Tensor


@torch.inference_mode()
def predict_batch(
    model: CompactVIO,
    batch: VIOBatch,
    *,
    device: torch.device | str = "cpu",
) -> MotionPrediction:
    """Predict one batch with dropout disabled and return detached CPU tensors."""

    if not isinstance(model, CompactVIO) or not isinstance(batch, VIOBatch):
        raise LearningError("model and batch have invalid types")
    actual_device = torch.device(device)
    model.to(actual_device)
    model.eval()
    moved = batch.to(actual_device)
    output = model(
        moved.frame_pairs,
        moved.imu,
        moved.imu_lengths,
        moved.delta_time_s,
    )
    return MotionPrediction(
        motion_vectors=output.motion_vector.detach().to(device="cpu"),
    )


@torch.inference_mode()
def predict_sequence_batch(
    model: CompactVIO,
    batch: VIOSequenceBatch,
    *,
    device: torch.device | str = "cpu",
    initial_fusion_state: Tensor | None = None,
) -> MotionSequencePrediction:
    """Predict one causal chunk and return its detached state for checked carry.

    Motion vectors and the mask are returned on CPU for artifact generation.
    ``final_fusion_state`` remains on the requested execution device so the
    caller can pass it to the next contiguous chunk without a device roundtrip.
    """

    if not isinstance(model, CompactVIO) or not isinstance(batch, VIOSequenceBatch):
        raise LearningError("model and sequence batch have invalid types")
    actual_device = torch.device(device)
    model.to(actual_device)
    model.eval()
    moved = batch.to(actual_device)
    if initial_fusion_state is not None:
        if not isinstance(initial_fusion_state, Tensor):
            raise LearningError("initial_fusion_state must be a torch tensor or None")
        initial_fusion_state = initial_fusion_state.to(actual_device)
    output = model.forward_sequence(
        moved.frame_pairs,
        moved.imu,
        moved.imu_lengths,
        moved.delta_time_s,
        moved.step_mask,
        initial_fusion_state,
    )
    return MotionSequencePrediction(
        motion_vectors=output.motion_vector.detach().to(device="cpu"),
        step_mask=output.step_mask.detach().to(device="cpu"),
        final_fusion_state=model.detach_fusion_state(output.final_fusion_state),
    )


def load_inference_model(
    checkpoint_path: Path | str,
    *,
    device: torch.device | str = "cpu",
    expected_inference_policy_id: str | None = None,
    expected_checkpoint_sha256: str | None = None,
) -> tuple[CompactVIO, LoadedCheckpoint]:
    """Construct and restore either supported checkpoint record for inference.

    Legacy/training checkpoint behavior remains unchanged.  Production
    inference-only artifacts are dispatched only by their exact record type
    and schema version, then adapted to ``LoadedCheckpoint`` so existing
    evaluation consumers retain one truthful metadata interface.  An
    inference-only record requires ``expected_checkpoint_sha256`` as an
    external trust root.  ``expected_inference_policy_id`` is verified when the
    artifact embeds that identity; legacy training records do not embed it, so
    their protocol-declared execution policy remains a caller-side contract.
    """

    # Read metadata into a temporary default model only after knowing that this
    # project's schema carries the full config. A shape mismatch fails safely;
    # a second load constructs the exact declared architecture.
    source = Path(checkpoint_path)
    if source.is_symlink() or not source.is_file():
        raise LearningError(f"checkpoint must be a regular non-symlink file: {source}")
    expected_digest = (
        _expected_sha256(expected_checkpoint_sha256)
        if expected_checkpoint_sha256 is not None
        else None
    )
    observed_digest = _sha256_file(source) if expected_digest is not None else None
    if observed_digest is not None and observed_digest != expected_digest:
        raise LearningError(
            f"checkpoint SHA-256 mismatch: expected {expected_digest}, got {observed_digest}"
        )
    try:
        payload = torch.load(source, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError, EOFError, pickle.UnpicklingError) as exc:
        raise LearningError(f"cannot inspect checkpoint {source}: {exc}") from exc
    if observed_digest is not None and _sha256_file(source) != observed_digest:
        raise LearningError("checkpoint changed while it was being inspected")
    if not isinstance(payload, dict):
        raise LearningError("checkpoint payload must be a mapping")

    training_fields = {
        "schema_version",
        "config",
        "epoch",
        "metrics",
        "provenance",
        "model_state_dict",
        "optimizer_state_dict",
    }
    if payload.get("schema_version") == 1 and set(payload) == training_fields:
        if not isinstance(payload.get("config"), dict):
            raise LearningError("checkpoint does not contain a training configuration")
        from compact_vio.learning.config import TrainingConfig

        config = TrainingConfig.from_dict(payload["config"])
        model = CompactVIO(config.model)
        metadata = load_checkpoint(source, model=model, map_location=device)
        if observed_digest is not None and _sha256_file(source) != observed_digest:
            raise LearningError("checkpoint changed while it was being loaded")
        model.to(device)
        model.eval()
        return model, metadata

    from compact_vio.learning.inference_checkpoint import (
        INFERENCE_CHECKPOINT_RECORD_TYPE,
        INFERENCE_CHECKPOINT_SCHEMA_VERSION,
        load_inference_checkpoint,
    )

    inference_fields = {
        "metadata",
        "metadata_sha256",
        "model_state_dict",
        "record_type",
        "schema_version",
    }
    if (
        payload.get("record_type") == INFERENCE_CHECKPOINT_RECORD_TYPE
        and payload.get("schema_version") == INFERENCE_CHECKPOINT_SCHEMA_VERSION
        and set(payload) == inference_fields
    ):
        if expected_digest is None:
            raise LearningError(
                "inference-only checkpoint loading requires expected_checkpoint_sha256"
            )
        loaded = load_inference_checkpoint(
            source,
            expected_artifact_sha256=expected_digest,
            expected_inference_policy_id=expected_inference_policy_id,
            device=device,
        )
        identity = loaded.identity
        return loaded.model, LoadedCheckpoint(
            config=identity.training_config,
            epoch=identity.selected_source_epoch,
            metrics=identity.metrics,
            provenance=identity.provenance,
        )

    raise LearningError("checkpoint record type or schema is unsupported or incomplete")


__all__ = [
    "MotionPrediction",
    "MotionSequencePrediction",
    "load_inference_model",
    "predict_batch",
    "predict_sequence_batch",
]

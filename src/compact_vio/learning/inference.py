"""Deterministic checkpoint loading and batched relative-motion inference."""

from __future__ import annotations

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
) -> tuple[CompactVIO, LoadedCheckpoint]:
    """Construct the checkpoint-declared architecture and strictly load weights."""

    # Read metadata into a temporary default model only after knowing that this
    # project's schema carries the full config. A shape mismatch fails safely;
    # a second load constructs the exact declared architecture.
    source = Path(checkpoint_path)
    try:
        payload = torch.load(source, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError, EOFError, pickle.UnpicklingError) as exc:
        raise LearningError(f"cannot inspect checkpoint {source}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("config"), dict):
        raise LearningError("checkpoint does not contain a training configuration")
    from compact_vio.learning.config import TrainingConfig

    config = TrainingConfig.from_dict(payload["config"])
    model = CompactVIO(config.model)
    metadata = load_checkpoint(source, model=model, map_location=device)
    model.to(device)
    model.eval()
    return model, metadata


__all__ = [
    "MotionPrediction",
    "MotionSequencePrediction",
    "load_inference_model",
    "predict_batch",
    "predict_sequence_batch",
]

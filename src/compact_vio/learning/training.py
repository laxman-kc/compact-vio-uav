"""Deterministic AMP-capable training and held-out evaluation loops."""

from __future__ import annotations

import math
import os
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from compact_vio.learning.checkpoint import CheckpointProvenance, save_checkpoint
from compact_vio.learning.config import TrainingConfig
from compact_vio.learning.dataset import VIOBatch
from compact_vio.learning.errors import LearningDependencyError, LearningError
from compact_vio.learning.model import CompactVIO

try:
    import torch
    from torch import Tensor
    from torch.optim import AdamW, Optimizer
except ImportError as exc:  # pragma: no cover - dependency-light installation
    raise LearningDependencyError(
        "PyTorch is required for training; install the training extra"
    ) from exc


@dataclass(frozen=True, slots=True)
class EpochMetrics:
    """Sample-weighted motion losses and geometric RMSE for one epoch."""

    total_loss: float
    translation_loss: float
    rotation_loss: float
    translation_rmse_m: float
    rotation_rmse_rad: float
    samples: int

    def to_dict(self, *, prefix: str = "") -> dict[str, float]:
        return {
            f"{prefix}total_loss": self.total_loss,
            f"{prefix}translation_loss": self.translation_loss,
            f"{prefix}rotation_loss": self.rotation_loss,
            f"{prefix}translation_rmse_m": self.translation_rmse_m,
            f"{prefix}rotation_rmse_rad": self.rotation_rmse_rad,
            f"{prefix}samples": float(self.samples),
        }


@dataclass(frozen=True, slots=True)
class FitResult:
    """Training history and location of the best validation checkpoint."""

    train_history: tuple[EpochMetrics, ...]
    validation_history: tuple[EpochMetrics, ...]
    best_epoch: int
    best_checkpoint: Path


@dataclass(slots=True)
class _Accumulator:
    weighted_total: float = 0.0
    weighted_translation: float = 0.0
    weighted_rotation: float = 0.0
    translation_squared_error: float = 0.0
    rotation_squared_error: float = 0.0
    samples: int = 0

    def add(
        self,
        *,
        total: Tensor,
        translation: Tensor,
        rotation: Tensor,
        prediction: Tensor,
        target: Tensor,
    ) -> None:
        batch_size = target.shape[0]
        self.weighted_total += float(total.detach()) * batch_size
        self.weighted_translation += float(translation.detach()) * batch_size
        self.weighted_rotation += float(rotation.detach()) * batch_size
        error = prediction.detach() - target
        self.translation_squared_error += float(error[:, :3].square().sum())
        self.rotation_squared_error += float(error[:, 3:].square().sum())
        self.samples += batch_size

    def finish(self) -> EpochMetrics:
        if self.samples <= 0:
            raise LearningError("data loader yielded no samples")
        values = EpochMetrics(
            total_loss=self.weighted_total / self.samples,
            translation_loss=self.weighted_translation / self.samples,
            rotation_loss=self.weighted_rotation / self.samples,
            translation_rmse_m=math.sqrt(self.translation_squared_error / self.samples),
            rotation_rmse_rad=math.sqrt(self.rotation_squared_error / self.samples),
            samples=self.samples,
        )
        if not all(
            math.isfinite(value)
            for value in (
                values.total_loss,
                values.translation_loss,
                values.rotation_loss,
                values.translation_rmse_m,
                values.rotation_rmse_rad,
            )
        ):
            raise LearningError("epoch produced non-finite metrics")
        return values


def seed_everything(seed: int, *, deterministic: bool = True) -> None:
    """Seed Python and PyTorch and select deterministic kernels when requested."""

    if type(seed) is not int or seed < 0 or type(deterministic) is not bool:
        raise LearningError("seed must be non-negative and deterministic must be boolean")
    if deterministic:
        workspace = os.environ.get("CUBLAS_WORKSPACE_CONFIG")
        if workspace not in (None, ":4096:8", ":16:8"):
            raise LearningError(
                "CUBLAS_WORKSPACE_CONFIG must be unset, ':4096:8', or ':16:8' "
                "for deterministic CUDA execution"
            )
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = not deterministic
    torch.backends.cudnn.deterministic = deterministic
    torch.use_deterministic_algorithms(deterministic, warn_only=False)


def motion_loss(
    prediction: Tensor,
    target: Tensor,
    *,
    translation_weight: float,
    rotation_weight: float,
) -> tuple[Tensor, Tensor, Tensor]:
    """Return weighted total, translation, and rotation Smooth-L1 losses."""

    if prediction.shape != target.shape or prediction.ndim != 2 or prediction.shape[1] != 6:
        raise LearningError("prediction and target must both have shape [batch, 6]")
    if not torch.isfinite(prediction).all() or not torch.isfinite(target).all():
        raise LearningError("prediction and target must contain only finite values")
    for value, field in (
        (translation_weight, "translation_weight"),
        (rotation_weight, "rotation_weight"),
    ):
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            raise LearningError(f"{field} must be a finite positive number")
    translation = torch.nn.functional.smooth_l1_loss(prediction[:, :3], target[:, :3])
    rotation = torch.nn.functional.smooth_l1_loss(prediction[:, 3:], target[:, 3:])
    return translation_weight * translation + rotation_weight * rotation, translation, rotation


def _forward_loss(
    model: CompactVIO,
    batch: VIOBatch,
    config: TrainingConfig,
) -> tuple[Tensor, Tensor, Tensor, Tensor]:
    output = model(
        batch.frame_pairs,
        batch.imu,
        batch.imu_lengths,
        batch.delta_time_s,
    )
    prediction = output.motion_vector
    total, translation, rotation = motion_loss(
        prediction,
        batch.target_motion,
        translation_weight=config.translation_loss_weight,
        rotation_weight=config.rotation_loss_weight,
    )
    return total, translation, rotation, prediction


def train_one_epoch(
    model: CompactVIO,
    batches: Iterable[VIOBatch],
    *,
    optimizer: Optimizer,
    device: torch.device | str,
    config: TrainingConfig,
    scaler: torch.amp.GradScaler | None = None,
) -> EpochMetrics:
    """Train for one complete loader pass with independent frame-pair samples."""

    model.train()
    actual_device = torch.device(device)
    amp_enabled = config.use_amp and actual_device.type == "cuda"
    accumulator = _Accumulator()
    for host_batch in batches:
        if not isinstance(host_batch, VIOBatch):
            raise LearningError("data loader must yield VIOBatch records")
        batch = host_batch.to(actual_device, non_blocking=actual_device.type == "cuda")
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=actual_device.type, enabled=amp_enabled):
            total, translation, rotation, prediction = _forward_loss(model, batch, config)
        if scaler is not None and amp_enabled:
            scaler.scale(total).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip_norm)
            scaler.step(optimizer)
            scaler.update()
        else:
            total.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip_norm)
            optimizer.step()
        accumulator.add(
            total=total,
            translation=translation,
            rotation=rotation,
            prediction=prediction,
            target=batch.target_motion,
        )
    return accumulator.finish()


@torch.inference_mode()
def evaluate(
    model: CompactVIO,
    batches: Iterable[VIOBatch],
    *,
    device: torch.device | str,
    config: TrainingConfig,
) -> EpochMetrics:
    """Evaluate a held-out loader without gradients or stochastic dropout."""

    model.eval()
    actual_device = torch.device(device)
    amp_enabled = config.use_amp and actual_device.type == "cuda"
    accumulator = _Accumulator()
    for host_batch in batches:
        if not isinstance(host_batch, VIOBatch):
            raise LearningError("data loader must yield VIOBatch records")
        batch = host_batch.to(actual_device, non_blocking=actual_device.type == "cuda")
        with torch.autocast(device_type=actual_device.type, enabled=amp_enabled):
            total, translation, rotation, prediction = _forward_loss(model, batch, config)
        accumulator.add(
            total=total,
            translation=translation,
            rotation=rotation,
            prediction=prediction,
            target=batch.target_motion,
        )
    return accumulator.finish()


def fit(
    model: CompactVIO,
    train_batches: Iterable[VIOBatch],
    validation_batches: Iterable[VIOBatch],
    *,
    device: torch.device | str,
    config: TrainingConfig,
    checkpoint_path: Path | str,
    provenance: CheckpointProvenance,
    progress_callback: Callable[[int, EpochMetrics, EpochMetrics], None] | None = None,
) -> FitResult:
    """Optimize and atomically retain the lowest validation-loss checkpoint.

    V1 treats each causal frame pair as an independent optimization sample and
    supplies a fresh zero state to its frame-pair fusion gate. Cross-frame
    sequence-state training is not claimed. ``progress_callback`` runs
    once after each completed train/validation epoch and any best-checkpoint
    write, making long GPU runs observable without coupling this module to a
    particular logger.
    """

    if not isinstance(model, CompactVIO):
        raise LearningError("model must be CompactVIO")
    if model.config != config.model:
        raise LearningError("model architecture does not match TrainingConfig.model")
    if progress_callback is not None and not callable(progress_callback):
        raise LearningError("progress_callback must be callable or None")
    actual_device = torch.device(device)
    model.to(actual_device)
    optimizer = AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    scaler = torch.amp.GradScaler("cuda", enabled=config.use_amp and actual_device.type == "cuda")
    train_history: list[EpochMetrics] = []
    validation_history: list[EpochMetrics] = []
    best_loss = math.inf
    best_epoch = 0
    destination = Path(checkpoint_path)
    for epoch in range(1, config.epochs + 1):
        train_metrics = train_one_epoch(
            model,
            train_batches,
            optimizer=optimizer,
            device=actual_device,
            config=config,
            scaler=scaler,
        )
        validation_metrics = evaluate(
            model,
            validation_batches,
            device=actual_device,
            config=config,
        )
        train_history.append(train_metrics)
        validation_history.append(validation_metrics)
        if validation_metrics.total_loss < best_loss:
            best_loss = validation_metrics.total_loss
            best_epoch = epoch
            save_checkpoint(
                destination,
                model=model,
                optimizer=optimizer,
                config=config,
                epoch=epoch,
                metrics={
                    **train_metrics.to_dict(prefix="train/"),
                    **validation_metrics.to_dict(prefix="validation/"),
                },
                provenance=provenance,
            )
        if progress_callback is not None:
            progress_callback(epoch, train_metrics, validation_metrics)
    if best_epoch == 0:
        raise LearningError("training did not produce a checkpoint")
    return FitResult(
        train_history=tuple(train_history),
        validation_history=tuple(validation_history),
        best_epoch=best_epoch,
        best_checkpoint=destination.resolve(),
    )


__all__ = [
    "EpochMetrics",
    "FitResult",
    "evaluate",
    "fit",
    "motion_loss",
    "seed_everything",
    "train_one_epoch",
]

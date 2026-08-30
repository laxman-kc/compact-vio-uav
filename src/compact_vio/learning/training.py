"""Deterministic AMP-capable training and held-out evaluation loops."""

from __future__ import annotations

import math
import os
import random
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from compact_vio.learning.checkpoint import CheckpointProvenance, save_checkpoint
from compact_vio.learning.config import TrainingConfig
from compact_vio.learning.dataset import VIOBatch, VIOSequenceBatch
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
    translation_magnitude_loss: float | None = None
    trajectory_consistency_loss: float | None = None

    def to_dict(self, *, prefix: str = "") -> dict[str, float]:
        values = {
            f"{prefix}total_loss": self.total_loss,
            f"{prefix}translation_loss": self.translation_loss,
            f"{prefix}rotation_loss": self.rotation_loss,
            f"{prefix}translation_rmse_m": self.translation_rmse_m,
            f"{prefix}rotation_rmse_rad": self.rotation_rmse_rad,
            f"{prefix}samples": float(self.samples),
        }
        if self.translation_magnitude_loss is not None:
            values[f"{prefix}translation_magnitude_loss"] = self.translation_magnitude_loss
        if self.trajectory_consistency_loss is not None:
            values[f"{prefix}trajectory_consistency_loss"] = self.trajectory_consistency_loss
        return values


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
    weighted_translation_magnitude: float = 0.0
    weighted_trajectory_consistency: float = 0.0
    weighted_rotation: float = 0.0
    translation_squared_error: float = 0.0
    rotation_squared_error: float = 0.0
    samples: int = 0
    has_translation_magnitude: bool = False
    has_trajectory_consistency: bool = False

    def add(
        self,
        *,
        total: Tensor,
        translation: Tensor,
        translation_magnitude: Tensor | None,
        trajectory_consistency: Tensor | None,
        rotation: Tensor,
        prediction: Tensor,
        target: Tensor,
    ) -> None:
        batch_size = target.shape[0]
        self.weighted_total += float(total.detach()) * batch_size
        self.weighted_translation += float(translation.detach()) * batch_size
        if translation_magnitude is not None:
            self.weighted_translation_magnitude += (
                float(translation_magnitude.detach()) * batch_size
            )
            self.has_translation_magnitude = True
        if trajectory_consistency is not None:
            self.weighted_trajectory_consistency += (
                float(trajectory_consistency.detach()) * batch_size
            )
            self.has_trajectory_consistency = True
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
            translation_magnitude_loss=(
                self.weighted_translation_magnitude / self.samples
                if self.has_translation_magnitude
                else None
            ),
            trajectory_consistency_loss=(
                self.weighted_trajectory_consistency / self.samples
                if self.has_trajectory_consistency
                else None
            ),
        )
        if not all(
            math.isfinite(value)
            for value in (
                values.total_loss,
                values.translation_loss,
                values.rotation_loss,
                values.translation_rmse_m,
                values.rotation_rmse_rad,
                *(
                    (values.translation_magnitude_loss,)
                    if values.translation_magnitude_loss is not None
                    else ()
                ),
                *(
                    (values.trajectory_consistency_loss,)
                    if values.trajectory_consistency_loss is not None
                    else ()
                ),
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
    translation_magnitude_weight: float = 0.0,
) -> tuple[Tensor, Tensor, Tensor]:
    """Return weighted total, translation-vector, and rotation Smooth-L1 losses.

    A nonzero ``translation_magnitude_weight`` adds Smooth-L1 loss between the
    predicted and target translation L2 norms. Its zero default preserves the
    legacy v1-v4 objective and checkpoint behavior exactly.
    """

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
    if (
        type(translation_magnitude_weight) not in (int, float)
        or not math.isfinite(translation_magnitude_weight)
        or translation_magnitude_weight < 0
    ):
        raise LearningError("translation_magnitude_weight must be a finite non-negative number")
    translation = torch.nn.functional.smooth_l1_loss(prediction[:, :3], target[:, :3])
    rotation = torch.nn.functional.smooth_l1_loss(prediction[:, 3:], target[:, 3:])
    legacy_total = translation_weight * translation + rotation_weight * rotation
    if translation_magnitude_weight == 0.0:
        return legacy_total, translation, rotation
    translation_magnitude = torch.nn.functional.smooth_l1_loss(
        torch.linalg.vector_norm(prediction[:, :3], dim=1),
        torch.linalg.vector_norm(target[:, :3], dim=1),
    )
    return (
        legacy_total + translation_magnitude_weight * translation_magnitude,
        translation,
        rotation,
    )


def _rotation_vector_matrices(rotation_vectors: Tensor) -> Tensor:
    """Differentiably map batched axis-angle vectors to rotation matrices."""

    x, y, z = rotation_vectors.unbind(dim=-1)
    zeros = torch.zeros_like(x)
    skew = torch.stack(
        (
            zeros,
            -z,
            y,
            z,
            zeros,
            -x,
            -y,
            x,
            zeros,
        ),
        dim=-1,
    ).reshape(*rotation_vectors.shape[:-1], 3, 3)
    angle = torch.linalg.vector_norm(rotation_vectors, dim=-1)
    sine_coefficient = torch.sinc(angle / math.pi)
    cosine_coefficient = 0.5 * torch.sinc(angle / (2.0 * math.pi)).square()
    identity = torch.eye(
        3,
        dtype=rotation_vectors.dtype,
        device=rotation_vectors.device,
    ).expand(*rotation_vectors.shape[:-1], 3, 3)
    return (
        identity
        + sine_coefficient[..., None, None] * skew
        + cosine_coefficient[..., None, None] * torch.matmul(skew, skew)
    )


def _integrate_relative_motion(motion: Tensor, step_mask: Tensor) -> tuple[Tensor, Tensor]:
    """Compose previous-body relative motion without alignment or scale fitting."""

    batch_size, steps, _ = motion.shape
    position = torch.zeros(batch_size, 3, dtype=motion.dtype, device=motion.device)
    rotation = torch.eye(3, dtype=motion.dtype, device=motion.device).expand(batch_size, 3, 3)
    positions: list[Tensor] = []
    rotations: list[Tensor] = []
    for step in range(steps):
        active = step_mask[:, step]
        translation = motion[:, step, :3]
        delta_rotation = _rotation_vector_matrices(motion[:, step, 3:])
        next_position = position + torch.matmul(rotation, translation.unsqueeze(-1)).squeeze(-1)
        next_rotation = torch.matmul(rotation, delta_rotation)
        position = torch.where(active[:, None], next_position, position)
        rotation = torch.where(active[:, None, None], next_rotation, rotation)
        positions.append(position)
        rotations.append(rotation)
    return torch.stack(positions, dim=1), torch.stack(rotations, dim=1)


def trajectory_consistency_loss(
    prediction: Tensor,
    target: Tensor,
    step_mask: Tensor,
    *,
    rotation_weight: float = 1.0,
) -> tuple[Tensor, Tensor, Tensor]:
    """Compare every composed pose endpoint across a causal sequence chunk.

    Relative translations are rotated from the previous body frame before they
    are accumulated. Relative rotations are composed on SO(3). Smooth-L1
    position and rotation-matrix losses keep the objective differentiable at an
    exact match, including zero rotation.
    """

    if prediction.shape != target.shape or prediction.ndim != 3 or prediction.shape[2] != 6:
        raise LearningError("prediction and target must both have shape [batch, steps, 6]")
    if step_mask.shape != prediction.shape[:2] or step_mask.dtype != torch.bool:
        raise LearningError("step_mask must be boolean with shape [batch, steps]")
    if not torch.isfinite(prediction).all() or not torch.isfinite(target).all():
        raise LearningError("prediction and target must contain only finite values")
    if torch.any(step_mask.sum(dim=1) == 0):
        raise LearningError("every trajectory row must contain at least one valid step")
    if prediction.shape[1] > 1 and torch.any(step_mask[:, 1:] & ~step_mask[:, :-1]):
        raise LearningError("valid trajectory steps must form a contiguous prefix")
    if (
        type(rotation_weight) not in (int, float)
        or not math.isfinite(rotation_weight)
        or rotation_weight <= 0
    ):
        raise LearningError("rotation_weight must be a finite positive number")

    predicted_position, predicted_rotation = _integrate_relative_motion(prediction, step_mask)
    target_position, target_rotation = _integrate_relative_motion(target, step_mask)
    translation = torch.nn.functional.smooth_l1_loss(
        predicted_position[step_mask], target_position[step_mask]
    )
    rotation = torch.nn.functional.smooth_l1_loss(
        predicted_rotation[step_mask], target_rotation[step_mask]
    )
    return translation + rotation_weight * rotation, translation, rotation


def _configured_translation_magnitude_loss(
    prediction: Tensor,
    target: Tensor,
    config: TrainingConfig,
) -> Tensor | None:
    if config.translation_magnitude_loss_weight == 0.0:
        return None
    predicted_translation = prediction.detach()[:, :3]
    target_translation = target.detach()[:, :3]
    return torch.nn.functional.smooth_l1_loss(
        torch.linalg.vector_norm(predicted_translation, dim=1),
        torch.linalg.vector_norm(target_translation, dim=1),
    )


def _forward_loss(
    model: CompactVIO,
    batch: VIOBatch,
    config: TrainingConfig,
) -> tuple[Tensor, Tensor, Tensor | None, Tensor, Tensor]:
    if config.trajectory_loss_weight > 0.0:
        raise LearningError(
            "trajectory_loss_weight requires VIOSequenceBatch training with multiple steps"
        )
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
        translation_magnitude_weight=config.translation_magnitude_loss_weight,
    )
    translation_magnitude = _configured_translation_magnitude_loss(
        prediction,
        batch.target_motion,
        config,
    )
    return total, translation, translation_magnitude, rotation, prediction


def _forward_sequence_loss(
    model: CompactVIO,
    batch: VIOSequenceBatch,
    config: TrainingConfig,
    *,
    fusion_state: Tensor | None = None,
) -> tuple[Tensor, Tensor, Tensor | None, Tensor | None, Tensor, Tensor, Tensor, Tensor]:
    """Return masked sequence losses, valid predictions/targets, and final state."""

    output = model.forward_sequence(
        batch.frame_pairs,
        batch.imu,
        batch.imu_lengths,
        batch.delta_time_s,
        batch.step_mask,
        fusion_state,
    )
    prediction = output.motion_vector[batch.step_mask]
    target = batch.target_motion[batch.step_mask]
    total, translation, rotation = motion_loss(
        prediction,
        target,
        translation_weight=config.translation_loss_weight,
        rotation_weight=config.rotation_loss_weight,
        translation_magnitude_weight=config.translation_magnitude_loss_weight,
    )
    translation_magnitude = _configured_translation_magnitude_loss(prediction, target, config)
    trajectory_consistency: Tensor | None = None
    if config.trajectory_loss_weight > 0.0:
        trajectory_consistency, _, _ = trajectory_consistency_loss(
            output.motion_vector,
            batch.target_motion,
            batch.step_mask,
            rotation_weight=config.rotation_loss_weight,
        )
        total = total + config.trajectory_loss_weight * trajectory_consistency
    return (
        total,
        translation,
        translation_magnitude,
        trajectory_consistency,
        rotation,
        prediction,
        target,
        output.final_fusion_state,
    )


def train_one_epoch(
    model: CompactVIO,
    batches: Iterable[VIOBatch | VIOSequenceBatch],
    *,
    optimizer: Optimizer,
    device: torch.device | str,
    config: TrainingConfig,
    scaler: torch.amp.GradScaler | None = None,
) -> EpochMetrics:
    """Train one loader pass with legacy pairs or reset-per-chunk sequences.

    Every :class:`VIOSequenceBatch` row starts from a zero fusion state. The
    graph spans all unmasked steps in that chunk and ends at the optimizer
    update, which is bounded truncated BPTT without cross-chunk leakage.
    """

    model.train()
    actual_device = torch.device(device)
    amp_enabled = config.use_amp and actual_device.type == "cuda"
    accumulator = _Accumulator()
    for host_batch in batches:
        if not isinstance(host_batch, (VIOBatch, VIOSequenceBatch)):
            raise LearningError("data loader must yield VIOBatch or VIOSequenceBatch records")
        batch = host_batch.to(actual_device, non_blocking=actual_device.type == "cuda")
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=actual_device.type, enabled=amp_enabled):
            if isinstance(batch, VIOSequenceBatch):
                (
                    total,
                    translation,
                    translation_magnitude,
                    trajectory_consistency,
                    rotation,
                    prediction,
                    target,
                    _,
                ) = _forward_sequence_loss(model, batch, config)
            else:
                (
                    total,
                    translation,
                    translation_magnitude,
                    rotation,
                    prediction,
                ) = _forward_loss(model, batch, config)
                target = batch.target_motion
                trajectory_consistency = None
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
            translation_magnitude=translation_magnitude,
            trajectory_consistency=trajectory_consistency,
            rotation=rotation,
            prediction=prediction,
            target=target,
        )
    return accumulator.finish()


@torch.inference_mode()
def evaluate(
    model: CompactVIO,
    batches: Iterable[VIOBatch | VIOSequenceBatch],
    *,
    device: torch.device | str,
    config: TrainingConfig,
) -> EpochMetrics:
    """Evaluate legacy pairs or causally ordered stateful sequence chunks.

    Sequence evaluation requires batch size one. State is carried only when
    ``chain_id`` matches and ``chunk_index`` is exactly consecutive, and is
    detached at every chunk boundary. ``chain_start`` always resets state;
    ``chain_end`` removes it. These checks prevent state leakage across EuRoC
    sequence, stride, phase, or continuity-segment chains.
    """

    model.eval()
    actual_device = torch.device(device)
    amp_enabled = config.use_amp and actual_device.type == "cuda"
    accumulator = _Accumulator()
    sequence_states: dict[str, Tensor] = {}
    next_chunk_indices: dict[str, int] = {}
    completed_chains: set[str] = set()
    batch_kind: type[VIOBatch] | type[VIOSequenceBatch] | None = None
    for host_batch in batches:
        if not isinstance(host_batch, (VIOBatch, VIOSequenceBatch)):
            raise LearningError("data loader must yield VIOBatch or VIOSequenceBatch records")
        current_kind = VIOSequenceBatch if isinstance(host_batch, VIOSequenceBatch) else VIOBatch
        if batch_kind is None:
            batch_kind = current_kind
        elif batch_kind is not current_kind:
            raise LearningError("evaluation loader must not mix pair and sequence batch types")
        batch = host_batch.to(actual_device, non_blocking=actual_device.type == "cuda")
        if isinstance(batch, VIOSequenceBatch):
            if batch.frame_pairs.shape[0] != 1:
                raise LearningError("stateful evaluation requires sequence batch size one")
            chain_id = batch.chain_ids[0]
            chunk_index = batch.chunk_indices[0]
            if batch.chain_starts[0]:
                if chunk_index != 0:
                    raise LearningError("a chain_start sequence chunk must have chunk_index zero")
                if chain_id in sequence_states or chain_id in completed_chains:
                    raise LearningError("stateful evaluation encountered a repeated chain start")
                fusion_state = None
            else:
                if chain_id not in sequence_states:
                    raise LearningError("stateful evaluation chunk has no preceding chain state")
                if next_chunk_indices[chain_id] != chunk_index:
                    raise LearningError("stateful evaluation chunks must be exactly contiguous")
                fusion_state = sequence_states[chain_id]
            with torch.autocast(device_type=actual_device.type, enabled=amp_enabled):
                (
                    total,
                    translation,
                    translation_magnitude,
                    trajectory_consistency,
                    rotation,
                    prediction,
                    target,
                    final_state,
                ) = _forward_sequence_loss(
                    model,
                    batch,
                    config,
                    fusion_state=fusion_state,
                )
            if batch.chain_ends[0]:
                sequence_states.pop(chain_id, None)
                next_chunk_indices.pop(chain_id, None)
                completed_chains.add(chain_id)
            else:
                sequence_states[chain_id] = model.detach_fusion_state(final_state)
                next_chunk_indices[chain_id] = chunk_index + 1
        else:
            with torch.autocast(device_type=actual_device.type, enabled=amp_enabled):
                (
                    total,
                    translation,
                    translation_magnitude,
                    rotation,
                    prediction,
                ) = _forward_loss(model, batch, config)
            target = batch.target_motion
            trajectory_consistency = None
        accumulator.add(
            total=total,
            translation=translation,
            translation_magnitude=translation_magnitude,
            trajectory_consistency=trajectory_consistency,
            rotation=rotation,
            prediction=prediction,
            target=target,
        )
    return accumulator.finish()


def fit(
    model: CompactVIO,
    train_batches: Iterable[VIOBatch | VIOSequenceBatch],
    validation_batches: Iterable[VIOBatch | VIOSequenceBatch],
    *,
    device: torch.device | str,
    config: TrainingConfig,
    checkpoint_path: Path | str,
    provenance: CheckpointProvenance,
    progress_callback: Callable[[int, EpochMetrics, EpochMetrics], None] | None = None,
) -> FitResult:
    """Optimize and atomically retain the lowest validation-loss checkpoint.

    Legacy loaders retain independent-pair behavior. Sequence loaders perform
    bounded reset-per-chunk BPTT for training and checked causal state carry for
    validation. ``progress_callback`` runs once after each completed
    train/validation epoch and any best-checkpoint write, making long GPU runs
    observable without coupling this module to a particular logger.
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


def fit_sequence(
    model: CompactVIO,
    train_batches: Iterable[VIOSequenceBatch],
    validation_batches: Iterable[VIOSequenceBatch],
    *,
    device: torch.device | str,
    config: TrainingConfig,
    checkpoint_path: Path | str,
    provenance: CheckpointProvenance,
    progress_callback: Callable[[int, EpochMetrics, EpochMetrics], None] | None = None,
) -> FitResult:
    """Fit bounded recurrent chunks using reset-train/carry-validation policy.

    This named entry point makes the v3 temporal policy explicit while sharing
    the optimizer, checkpoint schema, and deterministic AMP implementation with
    :func:`fit`. The sequence batch type is checked inside every epoch.
    """

    class _SequenceBatchView:
        def __init__(self, source: Iterable[VIOSequenceBatch]) -> None:
            self.source = source

        def __iter__(self) -> Iterator[VIOSequenceBatch]:
            for batch in self.source:
                if not isinstance(batch, VIOSequenceBatch):
                    raise LearningError("fit_sequence loaders must yield VIOSequenceBatch records")
                yield batch

    return fit(
        model,
        _SequenceBatchView(train_batches),
        _SequenceBatchView(validation_batches),
        device=device,
        config=config,
        checkpoint_path=checkpoint_path,
        provenance=provenance,
        progress_callback=progress_callback,
    )


__all__ = [
    "EpochMetrics",
    "FitResult",
    "evaluate",
    "fit",
    "fit_sequence",
    "motion_loss",
    "seed_everything",
    "train_one_epoch",
    "trajectory_consistency_loss",
]

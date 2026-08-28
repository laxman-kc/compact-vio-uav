"""Compact causal frame-pair and IMU relative-motion network."""

from __future__ import annotations

from dataclasses import dataclass

from compact_vio.learning.config import ModelConfig
from compact_vio.learning.errors import LearningDependencyError, LearningError

try:
    import torch
    from torch import Tensor, nn
    from torch.nn.utils.rnn import pack_padded_sequence
except ImportError as exc:  # pragma: no cover - exercised in dependency-light installs
    raise LearningDependencyError(
        "PyTorch is required for compact_vio.learning.model; install the training extra"
    ) from exc


@dataclass(frozen=True, slots=True)
class VIOOutput:
    """One batched relative-motion prediction."""

    relative_translation_m: Tensor
    relative_rotation_vector_rad: Tensor

    @property
    def motion_vector(self) -> Tensor:
        return torch.cat((self.relative_translation_m, self.relative_rotation_vector_rad), dim=-1)


@dataclass(frozen=True, slots=True)
class VIOSequenceOutput:
    """Masked relative-motion predictions and the final recurrent state.

    Motion tensors have shape ``[B, S, 3]``, ``step_mask`` has shape
    ``[B, S]``, and ``final_fusion_state`` has shape ``[B, F]``. Masked
    motion rows are exactly zero and do not update the recurrent state.
    """

    relative_translation_m: Tensor
    relative_rotation_vector_rad: Tensor
    step_mask: Tensor
    final_fusion_state: Tensor

    @property
    def motion_vector(self) -> Tensor:
        """Return translation and rotation concatenated as ``[B, S, 6]``."""

        return torch.cat((self.relative_translation_m, self.relative_rotation_vector_rad), dim=-1)


class ConvNormActivation(nn.Sequential):
    """Bias-free convolution followed by group normalization and SiLU."""

    def __init__(self, in_channels: int, out_channels: int, kernel: int, stride: int) -> None:
        padding = kernel // 2
        groups = min(8, out_channels)
        while out_channels % groups:
            groups -= 1
        super().__init__(
            nn.Conv2d(
                in_channels,
                out_channels,
                kernel_size=kernel,
                stride=stride,
                padding=padding,
                bias=False,
            ),
            nn.GroupNorm(groups, out_channels),
            nn.SiLU(inplace=True),
        )


class CompactVIO(nn.Module):
    """Predict pairwise 6-DoF motion from two images and causal IMU samples.

    The visual encoder sees only the previous/current grayscale frame pair. The
    GRU sees exactly the supplied ``(previous, current]`` IMU sequence. Legacy
    ``forward`` retains independent-pair behavior by default, while ``step`` and
    ``forward_sequence`` make the fusion-GRU state explicit for bounded causal
    unrolling.
    """

    def __init__(self, config: ModelConfig | None = None) -> None:
        super().__init__()
        if config is None:
            config = ModelConfig()
        if not isinstance(config, ModelConfig):
            raise LearningError("config must be a ModelConfig")
        self.config = config
        encoded_height = (config.image_height_px + 31) // 32
        encoded_width = (config.image_width_px + 31) // 32
        self.visual_encoder = nn.Sequential(
            ConvNormActivation(2, 32, 7, 2),
            ConvNormActivation(32, 64, 5, 2),
            ConvNormActivation(64, 96, 3, 2),
            ConvNormActivation(96, 128, 3, 2),
            ConvNormActivation(128, 192, 3, 2),
            nn.Flatten(),
            nn.Linear(192 * encoded_height * encoded_width, config.visual_feature_dim),
            nn.LayerNorm(config.visual_feature_dim),
            nn.SiLU(inplace=True),
        )
        self.imu_encoder = nn.GRU(
            input_size=6,
            hidden_size=config.imu_hidden_dim,
            num_layers=1,
            batch_first=True,
        )
        fusion_input_dim = config.visual_feature_dim + config.imu_hidden_dim + 1
        self.fusion_projection = nn.Sequential(
            nn.Linear(fusion_input_dim, config.fusion_hidden_dim),
            nn.LayerNorm(config.fusion_hidden_dim),
            nn.SiLU(inplace=True),
        )
        self.fusion_recurrence = nn.GRUCell(
            input_size=config.fusion_hidden_dim,
            hidden_size=config.fusion_hidden_dim,
        )
        head_hidden = max(64, config.fusion_hidden_dim // 2)
        self.motion_head = nn.Sequential(
            nn.LayerNorm(config.fusion_hidden_dim),
            nn.Dropout(config.dropout_probability),
            nn.Linear(config.fusion_hidden_dim, head_hidden),
            nn.SiLU(inplace=True),
            nn.Linear(head_hidden, 6),
        )

    @property
    def parameter_count(self) -> int:
        """Return the number of trainable scalar parameters."""

        return sum(parameter.numel() for parameter in self.parameters() if parameter.requires_grad)

    def initial_fusion_state(
        self, batch_size: int, *, device: torch.device | None = None
    ) -> Tensor:
        """Create a zero fusion state with exact shape ``[B, F]``."""

        if type(batch_size) is not int or batch_size <= 0:
            raise LearningError("batch_size must be a positive integer")
        reference = next(self.parameters())
        return reference.new_zeros(
            (batch_size, self.config.fusion_hidden_dim),
            device=device or reference.device,
        )

    def _initial_fusion_state(
        self, batch_size: int, *, device: torch.device | None = None
    ) -> Tensor:
        """Backward-compatible alias for :meth:`initial_fusion_state`."""

        return self.initial_fusion_state(batch_size, device=device)

    def detach_fusion_state(self, fusion_state: Tensor) -> Tensor:
        """Detach a valid ``[B, F]`` state at a truncation boundary."""

        if not isinstance(fusion_state, Tensor):
            raise LearningError("fusion_state must be a torch tensor")
        if fusion_state.ndim != 2 or fusion_state.shape[1] != self.config.fusion_hidden_dim:
            raise LearningError("fusion_state must have shape [batch, fusion_hidden_dim]")
        if not fusion_state.is_floating_point() or not torch.isfinite(fusion_state).all():
            raise LearningError("fusion_state must contain finite floating-point values")
        return fusion_state.detach()

    def _validated_fusion_state(
        self,
        fusion_state: Tensor | None,
        *,
        batch_size: int,
        device: torch.device,
    ) -> Tensor:
        if fusion_state is None:
            return self.initial_fusion_state(batch_size, device=device)
        if not isinstance(fusion_state, Tensor):
            raise LearningError("fusion_state must be a torch tensor or None")
        if fusion_state.shape != (batch_size, self.config.fusion_hidden_dim):
            raise LearningError("fusion_state must have shape [batch, fusion_hidden_dim]")
        if not fusion_state.is_floating_point() or not torch.isfinite(fusion_state).all():
            raise LearningError("fusion_state must contain finite floating-point values")
        if fusion_state.device != device:
            raise LearningError("fusion_state and model inputs must share a device")
        return fusion_state

    def _encode_pair_batch(
        self,
        frame_pairs: Tensor,
        imu: Tensor,
        imu_lengths: Tensor,
        delta_time_s: Tensor,
    ) -> Tensor:
        """Validate and encode one flattened batch of causal frame pairs."""

        if frame_pairs.ndim != 4 or frame_pairs.shape[1] != 2:
            raise LearningError("frame_pairs must have shape [batch, 2, height, width]")
        batch_size = frame_pairs.shape[0]
        if (
            frame_pairs.shape[2] != self.config.image_height_px
            or frame_pairs.shape[3] != self.config.image_width_px
        ):
            raise LearningError(
                "frame pair size does not match ModelConfig image_height_px/image_width_px"
            )
        if imu.ndim != 3 or imu.shape[0] != batch_size or imu.shape[2] != 6:
            raise LearningError("imu must have shape [batch, samples, 6]")
        if imu_lengths.ndim != 1 or imu_lengths.shape[0] != batch_size:
            raise LearningError("imu_lengths must have shape [batch]")
        if imu_lengths.dtype not in (
            torch.int8,
            torch.int16,
            torch.int32,
            torch.int64,
            torch.uint8,
        ):
            raise LearningError("imu_lengths must have an integer dtype")
        if delta_time_s.shape != (batch_size, 1):
            raise LearningError("delta_time_s must have shape [batch, 1]")
        if batch_size <= 0:
            raise LearningError("batch must not be empty")
        if not frame_pairs.is_floating_point() or not imu.is_floating_point():
            raise LearningError("frame_pairs and imu must be floating-point tensors")
        if not delta_time_s.is_floating_point():
            raise LearningError("delta_time_s must be a floating-point tensor")
        if imu.device != frame_pairs.device or delta_time_s.device != frame_pairs.device:
            raise LearningError("frame_pairs, imu, and delta_time_s must share a device")
        if torch.any(imu_lengths <= 0) or torch.any(imu_lengths > imu.shape[1]):
            raise LearningError("each imu length must be in [1, padded_samples]")
        if not torch.isfinite(frame_pairs).all() or not torch.isfinite(imu).all():
            raise LearningError("frame_pairs and imu must contain only finite values")
        if not torch.isfinite(delta_time_s).all() or torch.any(delta_time_s <= 0):
            raise LearningError("delta_time_s must contain finite positive values")
        visual_features = self.visual_encoder(frame_pairs)
        packed = pack_padded_sequence(
            imu,
            imu_lengths.detach().to(device="cpu", dtype=torch.int64),
            batch_first=True,
            enforce_sorted=False,
        )
        _, imu_hidden = self.imu_encoder(packed)
        return self.fusion_projection(
            torch.cat((visual_features, imu_hidden[-1], delta_time_s), dim=-1)
        )

    def _predict_motion(self, fused: Tensor, recurrent_state: Tensor) -> Tensor:
        """Apply the configured rotation-state policy without changing parameters."""

        recurrent_motion = self.motion_head(recurrent_state)
        if self.config.rotation_state_source == "shared-recurrent-fusion-state/v1":
            return recurrent_motion
        zero_initialized_state = self.fusion_recurrence(
            fused,
            torch.zeros_like(recurrent_state),
        )
        current_pair_motion = self.motion_head(zero_initialized_state)
        return torch.cat(
            (recurrent_motion[:, :3], current_pair_motion[:, 3:]),
            dim=-1,
        )

    def step(
        self,
        frame_pairs: Tensor,
        imu: Tensor,
        imu_lengths: Tensor,
        delta_time_s: Tensor,
        fusion_state: Tensor | None = None,
    ) -> tuple[VIOOutput, Tensor]:
        """Run one causal step and return its output plus next ``[B, F]`` state."""

        fused = self._encode_pair_batch(frame_pairs, imu, imu_lengths, delta_time_s)
        previous_state = self._validated_fusion_state(
            fusion_state,
            batch_size=frame_pairs.shape[0],
            device=frame_pairs.device,
        )
        next_state = self.fusion_recurrence(fused, previous_state)
        motion = self._predict_motion(fused, next_state)
        return (
            VIOOutput(
                relative_translation_m=motion[:, :3],
                relative_rotation_vector_rad=motion[:, 3:],
            ),
            next_state,
        )

    def forward(
        self,
        frame_pairs: Tensor,
        imu: Tensor,
        imu_lengths: Tensor,
        delta_time_s: Tensor,
        fusion_state: Tensor | None = None,
    ) -> VIOOutput:
        """Run a causal batch.

        Expected shapes are ``[B,2,H,W]``, ``[B,T,6]``, ``[B]``, and
        ``[B,1]``. Padding after each declared IMU length is ignored by the
        packed GRU, which makes variable-rate windows deterministic.
        """

        output, _ = self.step(
            frame_pairs,
            imu,
            imu_lengths,
            delta_time_s,
            fusion_state,
        )
        return output

    def forward_sequence(
        self,
        frame_pairs: Tensor,
        imu: Tensor,
        imu_lengths: Tensor,
        delta_time_s: Tensor,
        step_mask: Tensor,
        fusion_state: Tensor | None = None,
    ) -> VIOSequenceOutput:
        """Run a padded causal sequence with a masked recurrent unroll.

        Input shapes are ``[B,S,2,H,W]``, ``[B,S,T,6]``, ``[B,S]``,
        ``[B,S,1]``, and boolean ``[B,S]``. Each mask row must be a nonempty
        true prefix. Encoders are evaluated once over the flattened ``B*S``
        axis; the fusion GRUCell is then unrolled in timestamp order.
        """

        if frame_pairs.ndim != 5 or frame_pairs.shape[2] != 2:
            raise LearningError("frame_pairs must have shape [batch, steps, 2, height, width]")
        batch_size, steps = frame_pairs.shape[:2]
        if batch_size <= 0 or steps <= 0:
            raise LearningError("sequence batch and step dimensions must be positive")
        if (
            frame_pairs.shape[3] != self.config.image_height_px
            or frame_pairs.shape[4] != self.config.image_width_px
        ):
            raise LearningError(
                "frame pair size does not match ModelConfig image_height_px/image_width_px"
            )
        if imu.ndim != 4 or imu.shape[:2] != (batch_size, steps) or imu.shape[3] != 6:
            raise LearningError("imu must have shape [batch, steps, samples, 6]")
        if imu_lengths.shape != (batch_size, steps):
            raise LearningError("imu_lengths must have shape [batch, steps]")
        if delta_time_s.shape != (batch_size, steps, 1):
            raise LearningError("delta_time_s must have shape [batch, steps, 1]")
        if step_mask.shape != (batch_size, steps) or step_mask.dtype != torch.bool:
            raise LearningError("step_mask must be a boolean tensor with shape [batch, steps]")
        if step_mask.device != frame_pairs.device:
            raise LearningError("step_mask and model inputs must share a device")
        if imu_lengths.device != frame_pairs.device:
            raise LearningError("imu_lengths and model inputs must share a device")
        if not torch.all(step_mask.any(dim=1)):
            raise LearningError("each sequence row must contain at least one unmasked step")
        if steps > 1 and torch.any((~step_mask[:, :-1]) & step_mask[:, 1:]):
            raise LearningError("each step_mask row must be a true prefix followed by padding")
        if imu_lengths.dtype not in (
            torch.int8,
            torch.int16,
            torch.int32,
            torch.int64,
            torch.uint8,
        ):
            raise LearningError("imu_lengths must have an integer dtype")
        if torch.any(imu_lengths < 0) or torch.any(imu_lengths > imu.shape[2]):
            raise LearningError("each sequence IMU length must be in [0, padded_samples]")
        if torch.any(imu_lengths[step_mask] <= 0):
            raise LearningError("each unmasked sequence step must contain causal IMU samples")
        if not frame_pairs.is_floating_point() or not imu.is_floating_point():
            raise LearningError("frame_pairs and imu must be floating-point tensors")
        if not delta_time_s.is_floating_point():
            raise LearningError("delta_time_s must be a floating-point tensor")
        if imu.device != frame_pairs.device or delta_time_s.device != frame_pairs.device:
            raise LearningError("frame_pairs, imu, and delta_time_s must share a device")
        if not torch.isfinite(frame_pairs).all() or not torch.isfinite(imu).all():
            raise LearningError("frame_pairs and imu must contain only finite values")
        if not torch.isfinite(delta_time_s).all():
            raise LearningError("delta_time_s must contain only finite values")
        if torch.any(delta_time_s[step_mask] <= 0):
            raise LearningError("each unmasked delta_time_s must be positive")

        safe_lengths = torch.where(step_mask, imu_lengths, torch.ones_like(imu_lengths))
        safe_delta_time = torch.where(
            step_mask.unsqueeze(-1), delta_time_s, torch.ones_like(delta_time_s)
        )
        fused = self._encode_pair_batch(
            frame_pairs.reshape(
                batch_size * steps,
                2,
                self.config.image_height_px,
                self.config.image_width_px,
            ),
            imu.reshape(batch_size * steps, imu.shape[2], 6),
            safe_lengths.reshape(batch_size * steps),
            safe_delta_time.reshape(batch_size * steps, 1),
        ).reshape(batch_size, steps, self.config.fusion_hidden_dim)
        state = self._validated_fusion_state(
            fusion_state,
            batch_size=batch_size,
            device=frame_pairs.device,
        )
        motions: list[Tensor] = []
        for step_index in range(steps):
            candidate = self.fusion_recurrence(fused[:, step_index], state)
            active = step_mask[:, step_index].unsqueeze(-1)
            state = torch.where(active, candidate, state)
            motion = self._predict_motion(fused[:, step_index], state)
            motions.append(torch.where(active, motion, torch.zeros_like(motion)))
        motion_sequence = torch.stack(motions, dim=1)
        return VIOSequenceOutput(
            relative_translation_m=motion_sequence[:, :, :3],
            relative_rotation_vector_rad=motion_sequence[:, :, 3:],
            step_mask=step_mask,
            final_fusion_state=state,
        )


__all__ = ["CompactVIO", "VIOOutput", "VIOSequenceOutput"]

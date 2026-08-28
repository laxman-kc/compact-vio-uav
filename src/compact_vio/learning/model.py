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
    GRU sees exactly the supplied ``(previous, current]`` IMU sequence. A GRUCell
    gates the fused frame-pair features from a fresh zero state. V1 intentionally
    accepts and emits no cross-frame state because it is not trained statefully.
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

    def _initial_fusion_state(
        self, batch_size: int, *, device: torch.device | None = None
    ) -> Tensor:
        """Create V1's mandatory per-frame-pair zero fusion state."""

        if type(batch_size) is not int or batch_size <= 0:
            raise LearningError("batch_size must be a positive integer")
        reference = next(self.parameters())
        return reference.new_zeros(
            (batch_size, self.config.fusion_hidden_dim),
            device=device or reference.device,
        )

    def forward(
        self,
        frame_pairs: Tensor,
        imu: Tensor,
        imu_lengths: Tensor,
        delta_time_s: Tensor,
    ) -> VIOOutput:
        """Run a causal batch.

        Expected shapes are ``[B,2,H,W]``, ``[B,T,6]``, ``[B]``, and
        ``[B,1]``. Padding after each declared IMU length is ignored by the
        packed GRU, which makes variable-rate windows deterministic.
        """

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
        fused = self.fusion_projection(
            torch.cat((visual_features, imu_hidden[-1], delta_time_s), dim=-1)
        )
        fusion_state = self.fusion_recurrence(
            fused, self._initial_fusion_state(batch_size, device=frame_pairs.device)
        )
        motion = self.motion_head(fusion_state)
        return VIOOutput(
            relative_translation_m=motion[:, :3],
            relative_rotation_vector_rad=motion[:, 3:],
        )


__all__ = ["CompactVIO", "VIOOutput"]

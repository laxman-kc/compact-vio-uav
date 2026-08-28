"""PyTorch dataset for calibrated EuRoC causal frame pairs."""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compact_vio.data.euroc import (
    CausalFramePair,
    EuRoCSequence,
    GroundTruthState,
    interpolate_ground_truth,
    iter_causal_frame_pairs,
)
from compact_vio.learning.config import DataConfig, ModelConfig
from compact_vio.learning.errors import LearningDependencyError, LearningError
from compact_vio.learning.geometry import relative_motion_target

try:
    import torch
    from torch import Tensor
except ImportError as exc:  # pragma: no cover - dependency-light installation
    raise LearningDependencyError(
        "PyTorch is required for compact_vio.learning.dataset; install the training extra"
    ) from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover - dependency-light installation
    raise LearningDependencyError(
        "Pillow is required for EuRoC image loading; install the training extra"
    ) from exc


@dataclass(frozen=True, slots=True)
class SampleIdentity:
    """Stable source identity for one supervised frame pair."""

    sequence_id: str
    previous_timestamp_ns: int
    current_timestamp_ns: int

    def __post_init__(self) -> None:
        if type(self.sequence_id) is not str or not self.sequence_id.strip():
            raise LearningError("sequence_id must be a non-empty string")
        if (
            type(self.previous_timestamp_ns) is not int
            or type(self.current_timestamp_ns) is not int
            or self.previous_timestamp_ns < 0
            or self.current_timestamp_ns <= self.previous_timestamp_ns
        ):
            raise LearningError("sample timestamps must be non-negative and strictly increasing")


@dataclass(frozen=True, slots=True)
class VIOBatch:
    """Padded causal batch consumed by :class:`CompactVIO`."""

    frame_pairs: Tensor
    imu: Tensor
    imu_lengths: Tensor
    delta_time_s: Tensor
    target_motion: Tensor
    identities: tuple[SampleIdentity, ...]

    def __post_init__(self) -> None:
        tensors = (
            self.frame_pairs,
            self.imu,
            self.imu_lengths,
            self.delta_time_s,
            self.target_motion,
        )
        if not all(isinstance(value, Tensor) for value in tensors):
            raise LearningError("VIOBatch numeric fields must be torch tensors")
        if self.frame_pairs.ndim != 4 or self.frame_pairs.shape[1] != 2:
            raise LearningError("frame_pairs must have shape [batch, 2, height, width]")
        batch_size = self.frame_pairs.shape[0]
        if self.imu.ndim != 3 or self.imu.shape[0] != batch_size or self.imu.shape[2] != 6:
            raise LearningError("imu must have shape [batch, samples, 6]")
        if self.imu_lengths.shape != (batch_size,):
            raise LearningError("imu_lengths must have shape [batch]")
        if self.delta_time_s.shape != (batch_size, 1):
            raise LearningError("delta_time_s must have shape [batch, 1]")
        if self.target_motion.shape != (batch_size, 6):
            raise LearningError("target_motion must have shape [batch, 6]")
        if not all(
            tensor.is_floating_point()
            for tensor in (
                self.frame_pairs,
                self.imu,
                self.delta_time_s,
                self.target_motion,
            )
        ):
            raise LearningError("frame, IMU, time, and target tensors must be floating point")
        if self.imu_lengths.dtype not in (
            torch.int8,
            torch.int16,
            torch.int32,
            torch.int64,
            torch.uint8,
        ):
            raise LearningError("imu_lengths must have an integer dtype")
        if len(self.identities) != batch_size or not all(
            isinstance(identity, SampleIdentity) for identity in self.identities
        ):
            raise LearningError("identities must contain one SampleIdentity per batch item")

    def to(self, device: torch.device | str, *, non_blocking: bool = False) -> VIOBatch:
        """Move tensor fields to a device while preserving source identities."""

        return VIOBatch(
            frame_pairs=self.frame_pairs.to(device, non_blocking=non_blocking),
            imu=self.imu.to(device, non_blocking=non_blocking),
            imu_lengths=self.imu_lengths.to(device, non_blocking=non_blocking),
            delta_time_s=self.delta_time_s.to(device, non_blocking=non_blocking),
            target_motion=self.target_motion.to(device, non_blocking=non_blocking),
            identities=self.identities,
        )

    def pin_memory(self) -> VIOBatch:
        """Pin tensor storage for asynchronous host-to-CUDA transfer."""

        return VIOBatch(
            frame_pairs=self.frame_pairs.pin_memory(),
            imu=self.imu.pin_memory(),
            imu_lengths=self.imu_lengths.pin_memory(),
            delta_time_s=self.delta_time_s.pin_memory(),
            target_motion=self.target_motion.pin_memory(),
            identities=self.identities,
        )


@dataclass(frozen=True, slots=True)
class _PairRecord:
    sequence_id: str
    pair: CausalFramePair


def _supervised_pairs(
    sequence: EuRoCSequence,
    *,
    frame_strides: tuple[int, ...],
) -> tuple[_PairRecord, ...]:
    imu_t_bs = sequence.imu_calibration.t_bs
    ground_truth_t_bs = sequence.ground_truth_calibration.t_bs
    if any(
        not math.isclose(imu_t_bs[row][column], ground_truth_t_bs[row][column], abs_tol=1e-9)
        for row in range(4)
        for column in range(4)
    ):
        raise LearningError(
            f"sequence {sequence.sequence_id!r} has different IMU and ground-truth T_BS; "
            "V1 relative-motion labels require the same sensor/body transform"
        )
    if not sequence.ground_truth_states:
        raise LearningError(f"sequence {sequence.sequence_id!r} has no ground truth")
    first_gt = sequence.ground_truth_states[0].timestamp_ns
    last_gt = sequence.ground_truth_states[-1].timestamp_ns
    ground_truth_timestamps = tuple(state.timestamp_ns for state in sequence.ground_truth_states)

    def state_at(timestamp_ns: int) -> GroundTruthState:
        index = bisect.bisect_left(ground_truth_timestamps, timestamp_ns)
        if index < len(ground_truth_timestamps) and ground_truth_timestamps[index] == timestamp_ns:
            return sequence.ground_truth_states[index]
        return interpolate_ground_truth(
            sequence.ground_truth_states[index - 1 : index + 1], timestamp_ns
        )

    records: list[_PairRecord] = []
    for frame_stride in frame_strides:
        for pair in iter_causal_frame_pairs(
            sequence,
            frame_stride=frame_stride,
            include_ground_truth=False,
            require_imu=True,
        ):
            if (
                pair.previous_frame.timestamp_ns < first_gt
                or pair.current_frame.timestamp_ns > last_gt
            ):
                continue
            previous_gt = state_at(pair.previous_frame.timestamp_ns)
            current_gt = state_at(pair.current_frame.timestamp_ns)
            records.append(
                _PairRecord(
                    sequence_id=sequence.sequence_id,
                    pair=CausalFramePair(
                        previous_frame=pair.previous_frame,
                        current_frame=pair.current_frame,
                        imu_measurements=pair.imu_measurements,
                        previous_ground_truth=previous_gt,
                        current_ground_truth=current_gt,
                    ),
                ),
            )
    if not records:
        raise LearningError(
            f"sequence {sequence.sequence_id!r} has no causal frame pair "
            "inside ground-truth coverage"
        )
    return tuple(records)


class EuRoCPairDataset:
    """Lazy EuRoC image dataset with eager timestamp/target validation."""

    def __init__(
        self,
        sequences: Sequence[EuRoCSequence],
        *,
        model_config: ModelConfig | None = None,
        data_config: DataConfig | None = None,
        frame_strides: tuple[int, ...] = (1,),
    ) -> None:
        if model_config is None:
            model_config = ModelConfig()
        if data_config is None:
            data_config = DataConfig()
        sequence_tuple = tuple(sequences)
        if not sequence_tuple or not all(type(item) is EuRoCSequence for item in sequence_tuple):
            raise LearningError("sequences must contain at least one EuRoCSequence")
        sequence_ids = tuple(item.sequence_id for item in sequence_tuple)
        if len(sequence_ids) != len(set(sequence_ids)):
            raise LearningError("sequences must not repeat a sequence_id")
        if not isinstance(model_config, ModelConfig) or not isinstance(data_config, DataConfig):
            raise LearningError("model_config and data_config have invalid types")
        if (
            type(frame_strides) is not tuple
            or not frame_strides
            or any(type(value) is not int or value <= 0 for value in frame_strides)
            or len(frame_strides) != len(set(frame_strides))
        ):
            raise LearningError(
                "frame_strides must be a non-empty tuple of unique positive integers"
            )
        records: list[_PairRecord] = []
        for sequence in sequence_tuple:
            records.extend(_supervised_pairs(sequence, frame_strides=frame_strides))
        self._records = tuple(records)
        self.model_config = model_config
        self.data_config = data_config
        self.frame_strides = frame_strides
        self.sequence_ids = sequence_ids

    def __len__(self) -> int:
        return len(self._records)

    def _image_tensor(self, path: Path) -> Tensor:
        try:
            with Image.open(path) as image:
                grayscale = image.convert("L")
                resized = grayscale.resize(
                    (self.model_config.image_width_px, self.model_config.image_height_px),
                    resample=Image.Resampling.BILINEAR,
                )
                pixels = bytearray(resized.tobytes())
        except (OSError, ValueError) as exc:
            raise LearningError(f"cannot decode EuRoC image {path}: {exc}") from exc
        tensor = torch.frombuffer(pixels, dtype=torch.uint8).reshape(
            self.model_config.image_height_px,
            self.model_config.image_width_px,
        )
        tensor = tensor.to(dtype=torch.float32).div_(255.0)
        return tensor.sub_(self.data_config.image_mean).div_(self.data_config.image_std)

    def __getitem__(self, index: int) -> dict[str, Any]:
        if type(index) is not int:
            raise TypeError("dataset index must be an integer")
        record = self._records[index]
        pair = record.pair
        if pair.previous_ground_truth is None or pair.current_ground_truth is None:
            raise LearningError("internal supervised pair is missing ground truth")
        target = relative_motion_target(pair.previous_ground_truth, pair.current_ground_truth)
        imu_rows = [
            (
                measurement.angular_velocity_rs_s_rad_s[0] / self.data_config.gyroscope_scale_rad_s,
                measurement.angular_velocity_rs_s_rad_s[1] / self.data_config.gyroscope_scale_rad_s,
                measurement.angular_velocity_rs_s_rad_s[2] / self.data_config.gyroscope_scale_rad_s,
                measurement.linear_acceleration_rs_s_m_s2[0]
                / self.data_config.accelerometer_scale_m_s2,
                measurement.linear_acceleration_rs_s_m_s2[1]
                / self.data_config.accelerometer_scale_m_s2,
                measurement.linear_acceleration_rs_s_m_s2[2]
                / self.data_config.accelerometer_scale_m_s2,
            )
            for measurement in pair.imu_measurements
        ]
        if not imu_rows:
            raise LearningError("supervised frame pair contains no causal IMU samples")
        return {
            "frame_pair": torch.stack(
                (
                    self._image_tensor(pair.previous_frame.image_path),
                    self._image_tensor(pair.current_frame.image_path),
                )
            ),
            "imu": torch.tensor(imu_rows, dtype=torch.float32),
            "delta_time_s": torch.tensor(
                [(pair.current_frame.timestamp_ns - pair.previous_frame.timestamp_ns) * 1e-9],
                dtype=torch.float32,
            ),
            "target_motion": torch.tensor(
                (*target.translation_previous_m, *target.rotation_vector_rad),
                dtype=torch.float32,
            ),
            "identity": SampleIdentity(
                sequence_id=record.sequence_id,
                previous_timestamp_ns=pair.previous_frame.timestamp_ns,
                current_timestamp_ns=pair.current_frame.timestamp_ns,
            ),
        }


def collate_vio_batch(samples: Sequence[dict[str, Any]]) -> VIOBatch:
    """Pad only the tail of variable-length IMU windows and preserve lengths."""

    sample_tuple = tuple(samples)
    if not sample_tuple:
        raise LearningError("cannot collate an empty batch")
    required = {"frame_pair", "imu", "delta_time_s", "target_motion", "identity"}
    for sample in sample_tuple:
        if not isinstance(sample, dict) or set(sample) != required:
            raise LearningError("each sample must contain the exact VIO dataset fields")
    lengths = torch.tensor([sample["imu"].shape[0] for sample in sample_tuple], dtype=torch.int64)
    if torch.any(lengths <= 0):
        raise LearningError("every sample must contain at least one IMU measurement")
    max_length = int(lengths.max().item())
    first_imu = sample_tuple[0]["imu"]
    padded = first_imu.new_zeros((len(sample_tuple), max_length, 6))
    for index, sample in enumerate(sample_tuple):
        imu = sample["imu"]
        if not isinstance(imu, Tensor) or imu.ndim != 2 or imu.shape[1] != 6:
            raise LearningError("sample imu must have shape [samples, 6]")
        padded[index, : imu.shape[0]] = imu
    identities = tuple(sample["identity"] for sample in sample_tuple)
    if not all(isinstance(identity, SampleIdentity) for identity in identities):
        raise LearningError("sample identity has an invalid type")
    return VIOBatch(
        frame_pairs=torch.stack(tuple(sample["frame_pair"] for sample in sample_tuple)),
        imu=padded,
        imu_lengths=lengths,
        delta_time_s=torch.stack(tuple(sample["delta_time_s"] for sample in sample_tuple)),
        target_motion=torch.stack(tuple(sample["target_motion"] for sample in sample_tuple)),
        identities=identities,  # type: ignore[arg-type]
    )


__all__ = ["EuRoCPairDataset", "SampleIdentity", "VIOBatch", "collate_vio_batch"]

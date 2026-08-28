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
class VIOSequenceBatch:
    """Padded recurrent chunks with explicit valid-step and chain metadata."""

    frame_pairs: Tensor
    imu: Tensor
    imu_lengths: Tensor
    delta_time_s: Tensor
    target_motion: Tensor
    step_mask: Tensor
    identities: tuple[tuple[SampleIdentity | None, ...], ...]
    chain_ids: tuple[str, ...]
    chunk_indices: tuple[int, ...]
    chain_starts: tuple[bool, ...]
    chain_ends: tuple[bool, ...]

    def __post_init__(self) -> None:
        tensors = (
            self.frame_pairs,
            self.imu,
            self.imu_lengths,
            self.delta_time_s,
            self.target_motion,
            self.step_mask,
        )
        if not all(isinstance(value, Tensor) for value in tensors):
            raise LearningError("VIOSequenceBatch numeric fields must be torch tensors")
        if self.frame_pairs.ndim != 5 or self.frame_pairs.shape[2] != 2:
            raise LearningError("frame_pairs must have shape [batch, steps, 2, height, width]")
        batch_size, steps = self.frame_pairs.shape[:2]
        if batch_size <= 0 or steps <= 0:
            raise LearningError("sequence batches must contain at least one item and one step")
        if (
            self.imu.ndim != 4
            or self.imu.shape[0] != batch_size
            or self.imu.shape[1] != steps
            or self.imu.shape[2] <= 0
            or self.imu.shape[3] != 6
        ):
            raise LearningError("imu must have shape [batch, steps, samples, 6]")
        if self.imu_lengths.shape != (batch_size, steps):
            raise LearningError("imu_lengths must have shape [batch, steps]")
        if self.delta_time_s.shape != (batch_size, steps, 1):
            raise LearningError("delta_time_s must have shape [batch, steps, 1]")
        if self.target_motion.shape != (batch_size, steps, 6):
            raise LearningError("target_motion must have shape [batch, steps, 6]")
        if self.step_mask.shape != (batch_size, steps) or self.step_mask.dtype != torch.bool:
            raise LearningError("step_mask must be a boolean tensor with shape [batch, steps]")
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
        if torch.any(self.imu_lengths <= 0) or torch.any(self.imu_lengths > self.imu.shape[2]):
            raise LearningError("imu_lengths must be within the padded IMU dimension")
        if not torch.all(torch.isfinite(self.delta_time_s)) or torch.any(self.delta_time_s <= 0):
            raise LearningError("delta_time_s must contain finite positive values")

        if type(self.identities) is not tuple or len(self.identities) != batch_size:
            raise LearningError("identities must have shape [batch, steps]")
        for batch_index, identity_row in enumerate(self.identities):
            if type(identity_row) is not tuple or len(identity_row) != steps:
                raise LearningError("identities must have shape [batch, steps]")
            for step_index, identity in enumerate(identity_row):
                if bool(self.step_mask[batch_index, step_index].item()):
                    if not isinstance(identity, SampleIdentity):
                        raise LearningError("valid steps must have a SampleIdentity")
                elif identity is not None:
                    raise LearningError("padded steps must have a None identity")

        metadata = (
            (self.chain_ids, str, "chain_ids"),
            (self.chunk_indices, int, "chunk_indices"),
            (self.chain_starts, bool, "chain_starts"),
            (self.chain_ends, bool, "chain_ends"),
        )
        for values, expected_type, field in metadata:
            if type(values) is not tuple or len(values) != batch_size:
                raise LearningError(f"{field} must contain one value per batch item")
            if any(type(value) is not expected_type for value in values):
                raise LearningError(f"{field} contains an invalid value type")
        if any(not value.strip() for value in self.chain_ids):
            raise LearningError("chain_ids must be non-empty strings")
        if any(value < 0 for value in self.chunk_indices):
            raise LearningError("chunk_indices must be non-negative")

        padded = ~self.step_mask
        if torch.any(self.imu_lengths[padded] != 1):
            raise LearningError("padded steps must use the safe dummy IMU length one")
        if torch.any(self.delta_time_s.squeeze(-1)[padded] != 1):
            raise LearningError("padded steps must use the safe dummy delta time one")
        if torch.any(self.target_motion[padded] != 0):
            raise LearningError("padded target motion must be zero")

    def to(
        self,
        device: torch.device | str,
        *,
        non_blocking: bool = False,
    ) -> VIOSequenceBatch:
        """Move tensor fields only, preserving identities and chain metadata."""

        return VIOSequenceBatch(
            frame_pairs=self.frame_pairs.to(device, non_blocking=non_blocking),
            imu=self.imu.to(device, non_blocking=non_blocking),
            imu_lengths=self.imu_lengths.to(device, non_blocking=non_blocking),
            delta_time_s=self.delta_time_s.to(device, non_blocking=non_blocking),
            target_motion=self.target_motion.to(device, non_blocking=non_blocking),
            step_mask=self.step_mask.to(device, non_blocking=non_blocking),
            identities=self.identities,
            chain_ids=self.chain_ids,
            chunk_indices=self.chunk_indices,
            chain_starts=self.chain_starts,
            chain_ends=self.chain_ends,
        )

    def pin_memory(self) -> VIOSequenceBatch:
        """Pin tensor storage while preserving identities and chain metadata."""

        return VIOSequenceBatch(
            frame_pairs=self.frame_pairs.pin_memory(),
            imu=self.imu.pin_memory(),
            imu_lengths=self.imu_lengths.pin_memory(),
            delta_time_s=self.delta_time_s.pin_memory(),
            target_motion=self.target_motion.pin_memory(),
            step_mask=self.step_mask.pin_memory(),
            identities=self.identities,
            chain_ids=self.chain_ids,
            chunk_indices=self.chunk_indices,
            chain_starts=self.chain_starts,
            chain_ends=self.chain_ends,
        )


@dataclass(frozen=True, slots=True)
class _PairRecord:
    sequence_id: str
    frame_stride: int
    previous_frame_index: int
    current_frame_index: int
    pair: CausalFramePair


@dataclass(frozen=True, slots=True)
class _SequenceChunk:
    records: tuple[_PairRecord, ...]
    chain_id: str
    chunk_index: int
    chain_start: bool
    chain_end: bool


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
        for previous_frame_index, pair in enumerate(
            iter_causal_frame_pairs(
                sequence,
                frame_stride=frame_stride,
                include_ground_truth=False,
                require_imu=True,
            )
        ):
            current_frame_index = previous_frame_index + frame_stride
            if (
                pair.previous_frame != sequence.camera_frames[previous_frame_index]
                or pair.current_frame != sequence.camera_frames[current_frame_index]
            ):
                raise LearningError(
                    "internal causal-pair order does not match exact camera-frame indices"
                )
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
                    frame_stride=frame_stride,
                    previous_frame_index=previous_frame_index,
                    current_frame_index=current_frame_index,
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
        return self._sample_from_record(self._records[index])

    def _sample_from_record(self, record: _PairRecord) -> dict[str, Any]:
        """Materialize one validated pair record without changing source order."""

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


class EuRoCSequenceDataset(EuRoCPairDataset):
    """Deterministic, non-overlapping recurrent chunks of supervised EuRoC pairs.

    Chunks are ordered by input sequence, declared stride, stride phase,
    continuity segment, then chunk index.  A stride-``k`` chain contains only
    edges whose camera indices advance by exactly ``k``; this keeps, for
    example, the stride-two phases ``0 -> 2 -> 4`` and ``1 -> 3 -> 5`` separate.
    """

    def __init__(
        self,
        sequences: Sequence[EuRoCSequence],
        *,
        unroll_pairs: int,
        model_config: ModelConfig | None = None,
        data_config: DataConfig | None = None,
        frame_strides: tuple[int, ...] = (1,),
    ) -> None:
        if type(unroll_pairs) is not int or unroll_pairs <= 0:
            raise LearningError("unroll_pairs must be a positive integer")
        super().__init__(
            sequences,
            model_config=model_config,
            data_config=data_config,
            frame_strides=frame_strides,
        )
        self.unroll_pairs = unroll_pairs

        chunks: list[_SequenceChunk] = []
        for sequence_id in self.sequence_ids:
            for frame_stride in self.frame_strides:
                stride_records = tuple(
                    record
                    for record in self._records
                    if record.sequence_id == sequence_id and record.frame_stride == frame_stride
                )
                for phase in range(frame_stride):
                    phase_records = tuple(
                        record
                        for record in stride_records
                        if record.previous_frame_index % frame_stride == phase
                    )
                    segments: list[tuple[_PairRecord, ...]] = []
                    current_segment: list[_PairRecord] = []
                    for record in phase_records:
                        if record.current_frame_index != (
                            record.previous_frame_index + frame_stride
                        ):
                            raise LearningError(
                                "internal pair camera indices do not match the declared stride"
                            )
                        if current_segment and (
                            record.previous_frame_index != current_segment[-1].current_frame_index
                        ):
                            segments.append(tuple(current_segment))
                            current_segment = []
                        current_segment.append(record)
                    if current_segment:
                        segments.append(tuple(current_segment))

                    for segment_index, segment in enumerate(segments):
                        chain_id = (
                            f"{sequence_id}|stride={frame_stride}|phase={phase}|"
                            f"segment={segment_index}"
                        )
                        chunk_count = math.ceil(len(segment) / unroll_pairs)
                        for chunk_index in range(chunk_count):
                            start = chunk_index * unroll_pairs
                            records = segment[start : start + unroll_pairs]
                            chunks.append(
                                _SequenceChunk(
                                    records=records,
                                    chain_id=chain_id,
                                    chunk_index=chunk_index,
                                    chain_start=chunk_index == 0,
                                    chain_end=chunk_index == chunk_count - 1,
                                )
                            )
        if not chunks:
            raise LearningError("sequence dataset contains no recurrent chunk")
        self._chunks = tuple(chunks)

    def __len__(self) -> int:
        return len(self._chunks)

    @property
    def pair_count(self) -> int:
        """Return the exact number of valid supervised pairs across all chunks."""

        return len(self._records)

    def __getitem__(self, index: int) -> dict[str, Any]:
        if type(index) is not int:
            raise TypeError("dataset index must be an integer")
        chunk = self._chunks[index]
        samples = tuple(self._sample_from_record(record) for record in chunk.records)
        return {
            "frame_pairs": torch.stack(tuple(sample["frame_pair"] for sample in samples)),
            "imu": tuple(sample["imu"] for sample in samples),
            "delta_time_s": torch.stack(tuple(sample["delta_time_s"] for sample in samples)),
            "target_motion": torch.stack(tuple(sample["target_motion"] for sample in samples)),
            "identities": tuple(sample["identity"] for sample in samples),
            "chain_id": chunk.chain_id,
            "chunk_index": chunk.chunk_index,
            "chain_start": chunk.chain_start,
            "chain_end": chunk.chain_end,
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


def collate_vio_sequence_batch(samples: Sequence[dict[str, Any]]) -> VIOSequenceBatch:
    """Pad recurrent steps and per-step IMU windows without duplicating data."""

    sample_tuple = tuple(samples)
    if not sample_tuple:
        raise LearningError("cannot collate an empty sequence batch")
    required = {
        "frame_pairs",
        "imu",
        "delta_time_s",
        "target_motion",
        "identities",
        "chain_id",
        "chunk_index",
        "chain_start",
        "chain_end",
    }
    max_steps = 0
    max_imu_samples = 0
    frame_shape: tuple[int, ...] | None = None
    for sample in sample_tuple:
        if not isinstance(sample, dict) or set(sample) != required:
            raise LearningError("each sample must contain the exact VIO sequence fields")
        frame_pairs = sample["frame_pairs"]
        if (
            not isinstance(frame_pairs, Tensor)
            or frame_pairs.ndim != 4
            or frame_pairs.shape[0] <= 0
            or frame_pairs.shape[1] != 2
            or not frame_pairs.is_floating_point()
        ):
            raise LearningError("sample frame_pairs must have shape [steps, 2, height, width]")
        if frame_shape is None:
            frame_shape = tuple(frame_pairs.shape[1:])
        elif tuple(frame_pairs.shape[1:]) != frame_shape:
            raise LearningError("all sequence samples must use the same frame shape")
        steps = frame_pairs.shape[0]
        imu_steps = sample["imu"]
        if type(imu_steps) is not tuple or len(imu_steps) != steps:
            raise LearningError("sample imu must contain one tensor per recurrent step")
        for imu in imu_steps:
            if (
                not isinstance(imu, Tensor)
                or imu.ndim != 2
                or imu.shape[0] <= 0
                or imu.shape[1] != 6
                or not imu.is_floating_point()
            ):
                raise LearningError("each sample IMU window must have shape [samples, 6]")
            max_imu_samples = max(max_imu_samples, imu.shape[0])
        delta_time_s = sample["delta_time_s"]
        target_motion = sample["target_motion"]
        if (
            not isinstance(delta_time_s, Tensor)
            or delta_time_s.shape != (steps, 1)
            or not delta_time_s.is_floating_point()
        ):
            raise LearningError("sample delta_time_s must have shape [steps, 1]")
        if (
            not isinstance(target_motion, Tensor)
            or target_motion.shape != (steps, 6)
            or not target_motion.is_floating_point()
        ):
            raise LearningError("sample target_motion must have shape [steps, 6]")
        identities = sample["identities"]
        if (
            type(identities) is not tuple
            or len(identities) != steps
            or not all(isinstance(identity, SampleIdentity) for identity in identities)
        ):
            raise LearningError("sample identities must contain one identity per step")
        if type(sample["chain_id"]) is not str or not sample["chain_id"].strip():
            raise LearningError("sample chain_id must be a non-empty string")
        if type(sample["chunk_index"]) is not int or sample["chunk_index"] < 0:
            raise LearningError("sample chunk_index must be a non-negative integer")
        if type(sample["chain_start"]) is not bool or type(sample["chain_end"]) is not bool:
            raise LearningError("sample chain_start and chain_end must be boolean")
        max_steps = max(max_steps, steps)

    first_frames = sample_tuple[0]["frame_pairs"]
    first_imu = sample_tuple[0]["imu"][0]
    batch_size = len(sample_tuple)
    assert frame_shape is not None
    frame_pairs = first_frames.new_zeros((batch_size, max_steps, *frame_shape))
    imu = first_imu.new_zeros((batch_size, max_steps, max_imu_samples, 6))
    imu_lengths = torch.ones(
        (batch_size, max_steps),
        dtype=torch.int64,
        device=first_imu.device,
    )
    delta_time_s = first_frames.new_ones((batch_size, max_steps, 1))
    target_motion = first_frames.new_zeros((batch_size, max_steps, 6))
    step_mask = torch.zeros(
        (batch_size, max_steps),
        dtype=torch.bool,
        device=first_frames.device,
    )
    identity_rows: list[list[SampleIdentity | None]] = [
        [None] * max_steps for _ in range(batch_size)
    ]

    for batch_index, sample in enumerate(sample_tuple):
        steps = sample["frame_pairs"].shape[0]
        frame_pairs[batch_index, :steps] = sample["frame_pairs"]
        delta_time_s[batch_index, :steps] = sample["delta_time_s"]
        target_motion[batch_index, :steps] = sample["target_motion"]
        step_mask[batch_index, :steps] = True
        for step_index, imu_window in enumerate(sample["imu"]):
            length = imu_window.shape[0]
            imu[batch_index, step_index, :length] = imu_window
            imu_lengths[batch_index, step_index] = length
        identity_rows[batch_index][:steps] = sample["identities"]

    return VIOSequenceBatch(
        frame_pairs=frame_pairs,
        imu=imu,
        imu_lengths=imu_lengths,
        delta_time_s=delta_time_s,
        target_motion=target_motion,
        step_mask=step_mask,
        identities=tuple(tuple(row) for row in identity_rows),
        chain_ids=tuple(sample["chain_id"] for sample in sample_tuple),
        chunk_indices=tuple(sample["chunk_index"] for sample in sample_tuple),
        chain_starts=tuple(sample["chain_start"] for sample in sample_tuple),
        chain_ends=tuple(sample["chain_end"] for sample in sample_tuple),
    )


__all__ = [
    "EuRoCPairDataset",
    "EuRoCSequenceDataset",
    "SampleIdentity",
    "VIOBatch",
    "VIOSequenceBatch",
    "collate_vio_batch",
    "collate_vio_sequence_batch",
]

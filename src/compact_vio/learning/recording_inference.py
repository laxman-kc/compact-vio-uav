"""Run a packaged RAFT hybrid or legacy CompactVIO checkpoint on a recording.

This module is intentionally the small, user-facing bridge between a recording
and useful trajectory artifacts. It accepts timestamp-named images, an image
ZIP, or MP4 plus explicit camera timestamps. The current RAFT hybrid performs
calibrated image rectification and causal gyro integration; the legacy path
applies checkpoint preprocessing and optional recurrent-state carry. Both
paths integrate relative motion and write CSV/SVG/HTML/JSON outputs.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import html
import json
import math
import os
import shutil
import stat
import sys
import tempfile
import time
import zipfile
import zlib
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from compact_vio.evaluation.se3 import rotation_vector_to_matrix
from compact_vio.learning.config import DataConfig, ModelConfig
from compact_vio.learning.errors import LearningError

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]

_IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"})
_VIDEO_SUFFIXES = frozenset({".mp4"})
_ARCHIVE_SUFFIXES = frozenset({".zip"})
_CAMERA_TIMESTAMP_FIELDS = ("timestamp_ns", "#timestamp [ns]", "#timestamp")
_CAMERA_FILENAME_FIELDS = ("filename", "image", "path")
_IMU_COLUMN_SETS = (
    (
        ("gyro_x_rad_s", "gyro_y_rad_s", "gyro_z_rad_s"),
        ("accel_x_m_s2", "accel_y_m_s2", "accel_z_m_s2"),
    ),
    (("gyro_x", "gyro_y", "gyro_z"), ("accel_x", "accel_y", "accel_z")),
    (("gx", "gy", "gz"), ("ax", "ay", "az")),
    (
        (
            "w_RS_S_x [rad s^-1]",
            "w_RS_S_y [rad s^-1]",
            "w_RS_S_z [rad s^-1]",
        ),
        (
            "a_RS_S_x [m s^-2]",
            "a_RS_S_y [m s^-2]",
            "a_RS_S_z [m s^-2]",
        ),
    ),
)
_IDENTITY: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
_MAX_ARCHIVE_MEMBERS = 20_000
_MAX_ARCHIVE_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_ARCHIVE_MEMBER_BYTES = 256 * 1024 * 1024
_MAX_ARCHIVE_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_ARCHIVE_COMPRESSION_RATIO = 100
_MAX_CSV_BYTES = 128 * 1024 * 1024
_MAX_CAMERA_ROWS = 250_000
_MAX_IMU_ROWS = 2_000_000
_MAX_VIDEO_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_VIDEO_FRAMES = 100_000
_MAX_VIDEO_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
_MAX_CALIBRATION_BYTES = 4 * 1024 * 1024
_MAX_TIMESTAMP_NS = (1 << 63) - 1
_MAX_GYROSCOPE_ABS_RAD_S = 100.0
_MAX_ACCELERATION_ABS_M_S2 = 1000.0


class _DuplicateMappingKeyError(ValueError):
    """Raised when strict JSON/YAML parsing encounters a repeated key."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateMappingKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


class RecordingInferenceError(LearningError):
    """Raised when an input recording or inference output is invalid."""


@dataclass(frozen=True, slots=True)
class CameraSample:
    """One decoded camera frame with its sensor-clock timestamp."""

    timestamp_ns: int
    image_path: Path

    def __post_init__(self) -> None:
        if (
            type(self.timestamp_ns) is not int
            or self.timestamp_ns < 0
            or self.timestamp_ns > _MAX_TIMESTAMP_NS
        ):
            raise RecordingInferenceError("camera timestamp_ns must be in signed 64-bit range")
        if not isinstance(self.image_path, Path):
            raise RecordingInferenceError("camera image_path must be a pathlib.Path")


@dataclass(frozen=True, slots=True)
class ImuSample:
    """One six-axis IMU sample in the model's expected sensor convention."""

    timestamp_ns: int
    angular_velocity_rad_s: Vector3
    linear_acceleration_m_s2: Vector3

    def __post_init__(self) -> None:
        if (
            type(self.timestamp_ns) is not int
            or self.timestamp_ns < 0
            or self.timestamp_ns > _MAX_TIMESTAMP_NS
        ):
            raise RecordingInferenceError("IMU timestamp_ns must be in signed 64-bit range")
        _finite_vector(self.angular_velocity_rad_s, field="angular_velocity_rad_s")
        _finite_vector(self.linear_acceleration_m_s2, field="linear_acceleration_m_s2")
        if any(abs(value) > _MAX_GYROSCOPE_ABS_RAD_S for value in self.angular_velocity_rad_s):
            raise RecordingInferenceError("IMU gyroscope value exceeds the supported range")
        if any(abs(value) > _MAX_ACCELERATION_ABS_M_S2 for value in self.linear_acceleration_m_s2):
            raise RecordingInferenceError("IMU acceleration value exceeds the supported range")


@dataclass(frozen=True, slots=True)
class MotionEstimate:
    """One model prediction in the backend-declared previous sensor/body frame."""

    translation_previous_m: Vector3
    rotation_vector_rad: Vector3

    def __post_init__(self) -> None:
        _finite_vector(self.translation_previous_m, field="translation_previous_m")
        _finite_vector(self.rotation_vector_rad, field="rotation_vector_rad")


@dataclass(frozen=True, slots=True)
class PoseSample:
    """One integrated local pose, initialized at identity on the first frame."""

    timestamp_ns: int
    position_m: Vector3
    quaternion_wxyz: tuple[float, float, float, float]
    increment: MotionEstimate


@dataclass(frozen=True, slots=True)
class InferenceArtifacts:
    """Files and basic run facts returned by :func:`run_recording`."""

    trajectory_csv: Path
    trajectory_svg: Path
    summary_html: Path
    summary_json: Path
    frame_count: int
    pair_count: int
    path_length_m: float
    final_displacement_m: float
    elapsed_s: float


@dataclass(frozen=True, slots=True)
class ModelQualityAssessment:
    """Plain-language model evidence shown beside a successful inference run."""

    status: str
    headline: str
    explanation: str
    recommended_use: str
    current_recording_accuracy: str
    development_passed: int
    development_total: int
    final_test_sequence: str | None
    final_test_passed: bool | None
    predicted_path_m: float | None
    reference_path_m: float | None
    path_ratio: float | None
    path_error_percent: float | None
    endpoint_drift_m: float | None
    endpoint_drift_percent: float | None
    endpoint_drift_limit_percent: float | None
    failed_gates: tuple[str, ...]


def _quality_number(record: dict[str, object], field: str) -> float | None:
    value = record.get(field)
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        return None
    return float(value)


def _generic_quality_assessment(status: object) -> ModelQualityAssessment:
    if status == "experimental_rejected":
        return ModelQualityAssessment(
            status="rejected",
            headline="Model accuracy is not reliable yet",
            explanation=(
                "The software can generate a trajectory, but this model is marked as having "
                "failed its accuracy checks."
            ),
            recommended_use=(
                "Use the output to test the workflow and inspect rough motion only—not to "
                "measure distance or position."
            ),
            current_recording_accuracy="unverified_without_ground_truth",
            development_passed=0,
            development_total=0,
            final_test_sequence=None,
            final_test_passed=None,
            predicted_path_m=None,
            reference_path_m=None,
            path_ratio=None,
            path_error_percent=None,
            endpoint_drift_m=None,
            endpoint_drift_percent=None,
            endpoint_drift_limit_percent=None,
            failed_gates=(),
        )
    if status == "accepted":
        return ModelQualityAssessment(
            status="accepted",
            headline="The packaged model passed its recorded accuracy checks",
            explanation=(
                "This recording was processed successfully, but its individual accuracy "
                "cannot be measured here without a reference trajectory."
            ),
            recommended_use="Verify important measurements against an external reference.",
            current_recording_accuracy="unverified_without_ground_truth",
            development_passed=0,
            development_total=0,
            final_test_sequence=None,
            final_test_passed=None,
            predicted_path_m=None,
            reference_path_m=None,
            path_ratio=None,
            path_error_percent=None,
            endpoint_drift_m=None,
            endpoint_drift_percent=None,
            endpoint_drift_limit_percent=None,
            failed_gates=(),
        )
    return ModelQualityAssessment(
        status="not_assessed",
        headline="Accuracy has not been verified for this model",
        explanation=(
            "The software produced a trajectory, but this checkpoint does not include a "
            "benchmark verdict."
        ),
        recommended_use="Treat the trajectory as an unverified estimate.",
        current_recording_accuracy="unverified_without_ground_truth",
        development_passed=0,
        development_total=0,
        final_test_sequence=None,
        final_test_passed=None,
        predicted_path_m=None,
        reference_path_m=None,
        path_ratio=None,
        path_error_percent=None,
        endpoint_drift_m=None,
        endpoint_drift_percent=None,
        endpoint_drift_limit_percent=None,
        failed_gates=(),
    )


def _failed_quality_gates(
    row: dict[str, object],
    gate_values: dict[str, object],
) -> tuple[str, ...]:
    """Return plain-language failures for one validated evaluation row."""

    failed: list[str] = []
    coverage = _quality_number(row, "coverage_ratio")
    coverage_min = _quality_number(gate_values, "coverage_ratio_min")
    if coverage is not None and coverage_min is not None and coverage < coverage_min:
        failed.append("complete recording coverage")

    path_ratio = _quality_number(row, "path_length_ratio")
    path_min = _quality_number(gate_values, "path_length_ratio_min")
    path_max = _quality_number(gate_values, "path_length_ratio_max")
    if (
        path_ratio is not None
        and path_min is not None
        and path_max is not None
        and not path_min <= path_ratio <= path_max
    ):
        failed.append("distance travelled")

    normalized_drift = _quality_number(row, "normalized_final_translation_drift")
    drift_limit = _quality_number(gate_values, "normalized_final_translation_drift_max")
    if normalized_drift is not None and drift_limit is not None and normalized_drift > drift_limit:
        failed.append("end-position drift")

    comparisons = (
        (
            "overall position error",
            "translation_ate_m",
            "zero_translation_ate_m",
            "require_translation_ate_below_zero_motion",
        ),
        (
            "frame-to-frame translation",
            "pair_translation_rmse_m",
            "zero_pair_translation_rmse_m",
            "require_pair_translation_rmse_below_zero_motion",
        ),
        (
            "frame-to-frame rotation",
            "pair_rotation_rmse_rad",
            "zero_pair_rotation_rmse_rad",
            "require_pair_rotation_rmse_below_zero_motion",
        ),
    )
    for label, observed_field, baseline_field, required_field in comparisons:
        observed = _quality_number(row, observed_field)
        baseline = _quality_number(row, baseline_field)
        if (
            gate_values.get(required_field) is True
            and observed is not None
            and baseline is not None
            and observed >= baseline
        ):
            failed.append(label)
    return tuple(failed)


def assess_model_quality(backend: object) -> ModelQualityAssessment:
    """Translate a validated backend package into an honest user-facing verdict."""

    declared_status = getattr(backend, "quality_status", "not_declared")
    package = getattr(backend, "package", None)
    manifest = getattr(package, "manifest", None)
    evaluation = manifest.get("evaluation") if type(manifest) is dict else None
    if type(evaluation) is not dict:
        return _generic_quality_assessment(declared_status)

    sequences = evaluation.get("sequences")
    sequence_rows = (
        tuple(item for item in sequences if type(item) is dict) if type(sequences) is list else ()
    )
    development = tuple(row for row in sequence_rows if row.get("role") == "development_validation")
    development_passed = sum(row.get("all_pass") is True for row in development)
    final = next((row for row in sequence_rows if row.get("role") == "final_test"), None)
    gates = evaluation.get("gates")
    gate_values = gates if type(gates) is dict else {}
    status = "accepted" if evaluation.get("outcome") == "accepted" else "rejected"

    final_sequence = final.get("sequence_id") if final is not None else None
    final_sequence = final_sequence if type(final_sequence) is str else None
    final_passed = final.get("all_pass") if final is not None else None
    final_passed = final_passed if type(final_passed) is bool else None
    predicted_path = _quality_number(final, "predicted_path_length_m") if final else None
    reference_path = _quality_number(final, "reference_path_length_m") if final else None
    path_ratio = _quality_number(final, "path_length_ratio") if final else None
    drift_m = _quality_number(final, "final_translation_drift_m") if final else None
    normalized_drift = (
        _quality_number(final, "normalized_final_translation_drift") if final else None
    )
    drift_limit = _quality_number(gate_values, "normalized_final_translation_drift_max")
    failed: list[str] = []
    for row in sequence_rows:
        row_failures = _failed_quality_gates(row, gate_values)
        if row is final:
            failed.extend(row_failures)
            if row.get("all_pass") is False and not row_failures:
                failed.append("held-out benchmark")
            continue
        if row.get("all_pass") is False:
            sequence = row.get("sequence_id")
            prefix = sequence.replace("_", " ") if type(sequence) is str else "development test"
            if row_failures:
                failed.extend(f"{prefix}: {label}" for label in row_failures)
            else:
                failed.append(f"{prefix}: recorded accuracy gate")

    path_error_percent = abs(1.0 - path_ratio) * 100.0 if path_ratio is not None else None
    drift_percent = normalized_drift * 100.0 if normalized_drift is not None else None
    drift_limit_percent = drift_limit * 100.0 if drift_limit is not None else None

    if status == "accepted":
        headline = "The packaged model passed its recorded accuracy checks"
        explanation = (
            f"All {len(sequence_rows)} packaged benchmark recordings passed. This uploaded "
            "recording still has no ground-truth path, so its individual accuracy is unverified."
        )
        recommended_use = "Inspect the result and verify important measurements independently."
    elif final_passed is False and (
        final_sequence is not None
        and predicted_path is not None
        and reference_path is not None
        and path_ratio is not None
        and drift_m is not None
        and drift_percent is not None
        and drift_limit_percent is not None
        and path_error_percent is not None
    ):
        direction = "short" if path_ratio < 1.0 else "long"
        headline = "Model accuracy is not reliable yet"
        explanation = (
            f"On the held-out {final_sequence.replace('_', ' ')} test, it estimated "
            f"{predicted_path:.1f} m for a {reference_path:.1f} m path "
            f"({path_error_percent:.1f}% {direction}) and ended {drift_m:.2f} m away "
            f"({drift_percent:.2f}% drift; limit {drift_limit_percent:.2f}%)."
        )
        recommended_use = (
            "Use the output to test the workflow and inspect rough motion only—not to measure "
            "distance or position."
        )
    elif development and development_passed < len(development):
        headline = "Model accuracy is not reliable yet"
        explanation = (
            f"{len(development) - development_passed} of {len(development)} development "
            "benchmark recordings failed the packaged accuracy checks. A successful held-out "
            "row does not override that failure."
        )
        recommended_use = (
            "Use the output to test the workflow and inspect rough motion only—not to measure "
            "distance or position."
        )
    else:
        headline = "Model accuracy is not reliable yet"
        explanation = "The packaged model failed at least one recorded accuracy check."
        recommended_use = "Treat this trajectory as an unverified estimate."

    return ModelQualityAssessment(
        status=status,
        headline=headline,
        explanation=explanation,
        recommended_use=recommended_use,
        current_recording_accuracy="unverified_without_ground_truth",
        development_passed=development_passed,
        development_total=len(development),
        final_test_sequence=final_sequence,
        final_test_passed=final_passed,
        predicted_path_m=predicted_path,
        reference_path_m=reference_path,
        path_ratio=path_ratio,
        path_error_percent=path_error_percent,
        endpoint_drift_m=drift_m,
        endpoint_drift_percent=drift_percent,
        endpoint_drift_limit_percent=drift_limit_percent,
        failed_gates=tuple(failed),
    )


class MotionBackend(Protocol):
    """Minimal backend contract used by the recording runner.

    Tensor values are deliberately typed as ``Any`` so the orchestration core
    remains usable by PyTorch, ONNX Runtime, and small deterministic test
    backends without forcing any one runtime at module import time.
    """

    model_config: ModelConfig
    data_config: DataConfig

    def predict_step(
        self,
        frame_pair: Any,
        imu_window: Any,
        delta_time_s: float,
        state: object | None,
    ) -> tuple[MotionEstimate, object | None]:
        """Return one relative motion and the state for the next causal pair."""


class RecordingBackend(Protocol):
    """Whole-recording backend contract for calibration-aware VIO frontends.

    Unlike :class:`MotionBackend`, this contract preserves source image paths,
    camera timestamps, native IMU timestamps, and the parsed calibration.  It
    is used by the RAFT/gyro hybrid, whose exact preprocessing cannot be
    reconstructed from the legacy resized tensors.
    """

    backend_id: str
    calibration_usage: str

    def predict_recording(
        self,
        frames: Sequence[CameraSample],
        imu_samples: Sequence[ImuSample],
        calibration: dict[str, object] | None,
    ) -> Sequence[MotionEstimate]:
        """Return one motion for every consecutive source-frame pair."""


class TorchCheckpointBackend:
    """Stateful or independent inference over a validated PyTorch checkpoint."""

    def __init__(
        self,
        checkpoint_path: Path | str,
        *,
        device: str = "cpu",
        expected_checkpoint_sha256: str | None = None,
        state_policy: str = "stateful",
    ) -> None:
        if state_policy not in {"stateful", "independent"}:
            raise RecordingInferenceError("state_policy must be 'stateful' or 'independent'")
        from compact_vio.learning.inference import load_inference_model
        from compact_vio.learning.inference_checkpoint import (
            INDEPENDENT_INFERENCE_POLICY_ID,
            STATEFUL_INFERENCE_POLICY_ID,
        )

        expected_policy = (
            STATEFUL_INFERENCE_POLICY_ID
            if state_policy == "stateful"
            else INDEPENDENT_INFERENCE_POLICY_ID
        )
        model, metadata = load_inference_model(
            checkpoint_path,
            device=device,
            expected_inference_policy_id=expected_policy,
            expected_checkpoint_sha256=expected_checkpoint_sha256,
        )
        self.model = model
        self.model_config = metadata.config.model
        self.data_config = metadata.config.data
        self.device = device
        self.state_policy = state_policy
        self.selected_epoch = metadata.epoch

    def predict_step(
        self,
        frame_pair: Any,
        imu_window: Any,
        delta_time_s: float,
        state: object | None,
    ) -> tuple[MotionEstimate, object | None]:
        import torch

        carried_state = state if self.state_policy == "stateful" else None
        with torch.inference_mode():
            output, next_state = self.model.step(
                frame_pair.unsqueeze(0).to(self.device),
                imu_window.unsqueeze(0).to(self.device),
                torch.tensor([imu_window.shape[0]], dtype=torch.int64, device=self.device),
                torch.tensor([[delta_time_s]], dtype=torch.float32, device=self.device),
                carried_state,
            )
        values = output.motion_vector[0].detach().to(device="cpu", dtype=torch.float64).tolist()
        estimate = MotionEstimate(
            translation_previous_m=tuple(values[:3]),  # type: ignore[arg-type]
            rotation_vector_rad=tuple(values[3:]),  # type: ignore[arg-type]
        )
        return estimate, next_state.detach() if self.state_policy == "stateful" else None


def _finite_vector(value: object, *, field: str) -> Vector3:
    if type(value) is not tuple or len(value) != 3:
        raise RecordingInferenceError(f"{field} must be an exact three-tuple")
    if any(type(item) not in (int, float) or not math.isfinite(float(item)) for item in value):
        raise RecordingInferenceError(f"{field} must contain finite real values")
    return tuple(float(item) for item in value)  # type: ignore[return-value]


def _field(fieldnames: Sequence[str], candidates: Sequence[str], *, kind: str) -> str:
    matches = tuple(candidate for candidate in candidates if candidate in fieldnames)
    if len(matches) != 1:
        raise RecordingInferenceError(
            f"{kind} CSV must contain exactly one of these columns: {list(candidates)!r}"
        )
    return matches[0]


def _dict_reader(path: Path, *, kind: str) -> tuple[csv.DictReader[str], Any]:
    if path.is_symlink() or not path.is_file():
        raise RecordingInferenceError(f"{kind} CSV must be a regular file: {path}")
    try:
        source_bytes = path.stat().st_size
    except OSError as exc:
        raise RecordingInferenceError(f"cannot inspect {kind} CSV {path}: {exc}") from exc
    if source_bytes > _MAX_CSV_BYTES:
        raise RecordingInferenceError(f"{kind} CSV exceeds the size limit")
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise RecordingInferenceError(f"cannot read {kind} CSV {path}: {exc}") from exc
    try:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
    except (csv.Error, UnicodeError) as exc:
        handle.close()
        raise RecordingInferenceError(f"{kind} CSV is malformed: {exc}") from exc
    if not fieldnames or len(fieldnames) != len(set(fieldnames)):
        handle.close()
        raise RecordingInferenceError(f"{kind} CSV header is missing or repeats a column")
    return reader, handle


def load_camera_timestamps(path: Path | str) -> tuple[tuple[int, str | None], ...]:
    """Load strictly increasing camera timestamps and optional filenames."""

    source = Path(path)
    reader, handle = _dict_reader(source, kind="camera timestamp")
    try:
        assert reader.fieldnames is not None
        timestamp_field = _field(
            reader.fieldnames, _CAMERA_TIMESTAMP_FIELDS, kind="camera timestamp"
        )
        filename_matches = tuple(
            field for field in _CAMERA_FILENAME_FIELDS if field in reader.fieldnames
        )
        if len(filename_matches) > 1:
            raise RecordingInferenceError("camera timestamp CSV repeats filename semantics")
        filename_field = filename_matches[0] if filename_matches else None
        result: list[tuple[int, str | None]] = []
        for line, row in enumerate(reader, start=2):
            if line > _MAX_CAMERA_ROWS + 1:
                raise RecordingInferenceError("camera timestamp CSV contains too many rows")
            try:
                timestamp_ns = int(row[timestamp_field])
            except (KeyError, TypeError, ValueError) as exc:
                raise RecordingInferenceError(
                    f"{source}:{line}: camera timestamp_ns must be an integer"
                ) from exc
            if not 0 <= timestamp_ns <= _MAX_TIMESTAMP_NS:
                raise RecordingInferenceError(
                    f"{source}:{line}: camera timestamp_ns must be in signed 64-bit range"
                )
            filename = row.get(filename_field, "").strip() if filename_field else None
            if filename_field and not filename:
                raise RecordingInferenceError(f"{source}:{line}: filename must not be empty")
            result.append((timestamp_ns, filename))
    except (csv.Error, UnicodeError) as exc:
        raise RecordingInferenceError(f"camera timestamp CSV is malformed: {exc}") from exc
    finally:
        handle.close()
    if len(result) < 2:
        raise RecordingInferenceError("camera timestamp CSV must contain at least two frames")
    timestamps = tuple(timestamp for timestamp, _ in result)
    if timestamps[0] < 0 or any(
        current <= previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise RecordingInferenceError("camera timestamps must be non-negative and increasing")
    return tuple(result)


def load_imu_csv(path: Path | str) -> tuple[ImuSample, ...]:
    """Load canonical, short-name, or native EuRoC six-axis IMU CSV columns."""

    source = Path(path)
    reader, handle = _dict_reader(source, kind="IMU")
    try:
        assert reader.fieldnames is not None
        timestamp_field = _field(reader.fieldnames, _CAMERA_TIMESTAMP_FIELDS, kind="IMU")
        column_match = tuple(
            columns
            for columns in _IMU_COLUMN_SETS
            if all(field in reader.fieldnames for field in (*columns[0], *columns[1]))
        )
        if len(column_match) != 1:
            raise RecordingInferenceError(
                "IMU CSV must contain one supported gx/gy/gz and ax/ay/az column set"
            )
        gyro_fields, acceleration_fields = column_match[0]
        result: list[ImuSample] = []
        for line, row in enumerate(reader, start=2):
            if line > _MAX_IMU_ROWS + 1:
                raise RecordingInferenceError("IMU CSV contains too many rows")
            try:
                timestamp_ns = int(row[timestamp_field])
                gyro = tuple(float(row[field]) for field in gyro_fields)
                acceleration = tuple(float(row[field]) for field in acceleration_fields)
            except (KeyError, TypeError, ValueError) as exc:
                raise RecordingInferenceError(
                    f"{source}:{line}: invalid timestamp or six-axis IMU value"
                ) from exc
            try:
                result.append(
                    ImuSample(
                        timestamp_ns=timestamp_ns,
                        angular_velocity_rad_s=gyro,  # type: ignore[arg-type]
                        linear_acceleration_m_s2=acceleration,  # type: ignore[arg-type]
                    )
                )
            except RecordingInferenceError as exc:
                raise RecordingInferenceError(f"{source}:{line}: {exc}") from exc
    except (csv.Error, UnicodeError) as exc:
        raise RecordingInferenceError(f"IMU CSV is malformed: {exc}") from exc
    finally:
        handle.close()
    if not result:
        raise RecordingInferenceError("IMU CSV must contain at least one measurement")
    timestamps = tuple(sample.timestamp_ns for sample in result)
    if any(
        current <= previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise RecordingInferenceError("IMU timestamps must be strictly increasing")
    return tuple(result)


def load_calibration(path: Path | str) -> tuple[dict[str, object], str]:
    """Validate a JSON/YAML calibration mapping and return it with its SHA-256.

    The current RAFT hybrid validates and uses camera/IMU calibration for image
    rectification and gyro-frame handling. The legacy checkpoint path only
    fingerprints calibration and keeps its grayscale/resize normalization.
    """

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise RecordingInferenceError(f"calibration must be a regular file: {source}")
    try:
        source_bytes = source.stat().st_size
    except OSError as exc:
        raise RecordingInferenceError(f"cannot inspect calibration {source}: {exc}") from exc
    if source_bytes > _MAX_CALIBRATION_BYTES:
        raise RecordingInferenceError("calibration exceeds the size limit")
    try:
        encoded = source.read_bytes()
        document = encoded.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise RecordingInferenceError(f"cannot read calibration {source}: {exc}") from exc
    try:
        value = json.loads(document, object_pairs_hook=_unique_json_object)
    except _DuplicateMappingKeyError as exc:
        raise RecordingInferenceError(f"cannot parse calibration {source}: {exc}") from exc
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RecordingInferenceError(
                "non-JSON calibration requires PyYAML from the data extra"
            ) from exc

        class _UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc, name-defined]
            pass

        def _construct_unique_mapping(loader: object, node: object, deep: bool = False) -> object:
            loader.flatten_mapping(node)  # type: ignore[attr-defined]
            mapping: dict[object, object] = {}
            for key_node, value_node in node.value:  # type: ignore[attr-defined]
                key = loader.construct_object(key_node, deep=deep)  # type: ignore[attr-defined]
                try:
                    repeated = key in mapping
                except TypeError as exc:
                    raise _DuplicateMappingKeyError(
                        "calibration mapping keys must be scalar values"
                    ) from exc
                if repeated:
                    raise _DuplicateMappingKeyError(f"duplicate YAML key: {key!r}")
                mapping[key] = loader.construct_object(  # type: ignore[attr-defined]
                    value_node, deep=deep
                )
            return mapping

        _UniqueKeyLoader.add_constructor(  # type: ignore[attr-defined]
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            _construct_unique_mapping,
        )
        try:
            value = yaml.load(document, Loader=_UniqueKeyLoader)
        except (yaml.YAMLError, _DuplicateMappingKeyError) as exc:
            raise RecordingInferenceError(f"cannot parse calibration {source}: {exc}") from exc
    if type(value) is not dict or not value or any(type(key) is not str for key in value):
        raise RecordingInferenceError("calibration document must be a non-empty mapping")
    return value, hashlib.sha256(encoded).hexdigest()


def _directory_images(recording: Path) -> tuple[Path, ...]:
    images = tuple(
        path
        for path in recording.iterdir()
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in _IMAGE_SUFFIXES
    )
    if len(images) < 2:
        raise RecordingInferenceError(
            f"image recording must contain at least two supported images: {recording}"
        )
    return images


def _resolve_manifest_frames(
    recording: Path,
    timestamp_rows: tuple[tuple[int, str | None], ...] | None,
) -> tuple[CameraSample, ...]:
    if timestamp_rows is None:
        images = _directory_images(recording)
        timestamped: list[tuple[int, Path]] = []
        for image_path in images:
            try:
                timestamped.append((int(image_path.stem), image_path))
            except ValueError as exc:
                raise RecordingInferenceError(
                    "without --camera-timestamps every image filename stem must be timestamp_ns"
                ) from exc
        timestamped.sort(key=lambda item: item[0])
        rows = tuple(CameraSample(timestamp, path) for timestamp, path in timestamped)
    elif timestamp_rows[0][1] is not None:
        root = recording.resolve()
        rows_list: list[CameraSample] = []
        for timestamp, filename in timestamp_rows:
            assert filename is not None
            relative = PurePosixPath(filename)
            if (
                relative.is_absolute()
                or not relative.parts
                or any(part in {"", ".", ".."} for part in relative.parts)
                or "\\" in filename
                or "\x00" in filename
            ):
                raise RecordingInferenceError(f"camera filename is unsafe: {filename}")
            if len(relative.parts) > 1 and relative.parts[0] == recording.name:
                relative = PurePosixPath(*relative.parts[1:])
            unresolved = recording.joinpath(*relative.parts)
            current = recording
            for part in relative.parts:
                current /= part
                if current.is_symlink():
                    raise RecordingInferenceError(
                        f"camera image path must not contain symbolic links: {filename}"
                    )
            candidate = unresolved.resolve()
            if not candidate.is_relative_to(root):
                raise RecordingInferenceError(
                    f"camera filename escapes recording directory: {filename}"
                )
            if not candidate.is_file():
                raise RecordingInferenceError(f"camera image is not a regular file: {candidate}")
            rows_list.append(CameraSample(timestamp, candidate))
        rows = tuple(rows_list)
    else:
        images = _directory_images(recording)
        ordered_images = tuple(sorted(images, key=lambda path: path.name))
        if len(ordered_images) != len(timestamp_rows):
            raise RecordingInferenceError(
                "camera timestamp count does not match the image count in the recording"
            )
        rows = tuple(
            CameraSample(timestamp, image_path)
            for (timestamp, _), image_path in zip(timestamp_rows, ordered_images, strict=True)
        )
    timestamps = tuple(row.timestamp_ns for row in rows)
    if timestamps[0] < 0 or any(
        current <= previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise RecordingInferenceError("camera timestamps must be non-negative and increasing")
    if len({row.image_path for row in rows}) != len(rows):
        raise RecordingInferenceError("camera manifest must not repeat an image")
    return rows


def _safe_extract_image_archive(source: Path, destination: Path) -> None:
    try:
        source_bytes = source.stat().st_size
    except OSError as exc:
        raise RecordingInferenceError(f"cannot inspect image ZIP {source}: {exc}") from exc
    if source_bytes > _MAX_ARCHIVE_SOURCE_BYTES:
        raise RecordingInferenceError("image ZIP exceeds the compressed size limit")
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RecordingInferenceError(f"cannot open image ZIP {source}: {exc}") from exc
    with archive:
        members = archive.infolist()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise RecordingInferenceError("image ZIP contains too many members")
        total_bytes = 0
        seen: set[str] = set()
        seen_casefold: set[str] = set()
        for member in members:
            pure = PurePosixPath(member.filename)
            if (
                pure.is_absolute()
                or not pure.parts
                or any(part in {"", ".", ".."} for part in pure.parts)
                or "\\" in member.filename
                or "\x00" in member.filename
            ):
                raise RecordingInferenceError(
                    f"image ZIP contains an unsafe member path: {member.filename!r}"
                )
            canonical = pure.as_posix()
            folded = canonical.casefold()
            if canonical in seen or folded in seen_casefold:
                raise RecordingInferenceError(
                    f"image ZIP repeats a member path: {member.filename!r}"
                )
            seen.add(canonical)
            seen_casefold.add(folded)
            unix_mode = member.external_attr >> 16
            file_type = stat.S_IFMT(unix_mode)
            if file_type == stat.S_IFLNK:
                raise RecordingInferenceError("image ZIP must not contain symbolic links")
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise RecordingInferenceError("image ZIP must contain only files/directories")
            if member.flag_bits & 0x1:
                raise RecordingInferenceError("encrypted image ZIPs are not supported")
            if member.is_dir():
                continue
            if member.file_size > _MAX_ARCHIVE_MEMBER_BYTES:
                raise RecordingInferenceError("image ZIP member exceeds the size limit")
            if member.file_size and member.compress_size == 0:
                raise RecordingInferenceError("image ZIP has an invalid compression size")
            if (
                member.file_size
                and member.compress_size
                and member.file_size > member.compress_size * _MAX_ARCHIVE_COMPRESSION_RATIO
            ):
                raise RecordingInferenceError("image ZIP compression ratio is unsafe")
            total_bytes += member.file_size
            if total_bytes > _MAX_ARCHIVE_TOTAL_BYTES:
                raise RecordingInferenceError("image ZIP exceeds the total expansion limit")
            if pure.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            target = destination.joinpath(*pure.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with archive.open(member, "r") as input_handle, target.open("xb") as output_handle:
                    while chunk := input_handle.read(1024 * 1024):
                        written += len(chunk)
                        if written > member.file_size or written > _MAX_ARCHIVE_MEMBER_BYTES:
                            raise RecordingInferenceError(
                                "image ZIP member expanded beyond its declared size"
                            )
                        output_handle.write(chunk)
            except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
                raise RecordingInferenceError(
                    f"cannot extract image ZIP member {member.filename!r}: {exc}"
                ) from exc
            if written != member.file_size:
                raise RecordingInferenceError("image ZIP member size changed during extraction")


def _decode_mp4_opencv(source: Path, destination: Path) -> None:
    try:
        source_bytes = source.stat().st_size
    except OSError as exc:
        raise RecordingInferenceError(f"cannot inspect MP4 recording {source}: {exc}") from exc
    if source_bytes > _MAX_VIDEO_SOURCE_BYTES:
        raise RecordingInferenceError("MP4 exceeds the compressed size limit")
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RecordingInferenceError(
            "MP4 decoding requires OpenCV; install the demo/video extra"
        ) from exc
    capture = cv2.VideoCapture(os.fspath(source))
    if not capture.isOpened():
        capture.release()
        raise RecordingInferenceError(f"OpenCV cannot open MP4 recording: {source}")
    count = 0
    output_bytes = 0
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            count += 1
            if count > _MAX_VIDEO_FRAMES:
                raise RecordingInferenceError("MP4 decodes to too many frames")
            output = destination / f"{count:09d}.png"
            if not cv2.imwrite(os.fspath(output), frame):
                raise RecordingInferenceError(f"OpenCV cannot write decoded frame {count}")
            try:
                output_bytes += output.stat().st_size
            except OSError as exc:
                raise RecordingInferenceError(
                    f"cannot inspect decoded frame {count}: {exc}"
                ) from exc
            if output_bytes > _MAX_VIDEO_OUTPUT_BYTES:
                raise RecordingInferenceError("MP4 decoded frames exceed the size limit")
    finally:
        capture.release()
    if count < 2:
        raise RecordingInferenceError("MP4 must decode to at least two frames")


@contextmanager
def camera_samples(
    recording_path: Path | str,
    camera_timestamps_path: Path | str | None = None,
) -> Any:
    """Yield camera samples for a timestamped directory or decoded MP4."""

    recording = Path(recording_path)
    timestamp_rows = (
        load_camera_timestamps(camera_timestamps_path)
        if camera_timestamps_path is not None
        else None
    )
    if recording.is_dir() and not recording.is_symlink():
        yield _resolve_manifest_frames(recording, timestamp_rows)
        return
    if recording.is_symlink() or not recording.is_file():
        raise RecordingInferenceError(
            f"recording must be a regular MP4 or image directory: {recording}"
        )
    suffix = recording.suffix.lower()
    if suffix not in _VIDEO_SUFFIXES | _ARCHIVE_SUFFIXES:
        raise RecordingInferenceError("recording file must use the .mp4 or .zip suffix")
    with tempfile.TemporaryDirectory(prefix="compact-vio-frames-") as directory:
        frame_root = Path(directory)
        if suffix in _VIDEO_SUFFIXES:
            if timestamp_rows is None:
                raise RecordingInferenceError("MP4 inference requires --camera-timestamps")
            _decode_mp4_opencv(recording, frame_root)
        else:
            _safe_extract_image_archive(recording, frame_root)
            if timestamp_rows is None or timestamp_rows[0][1] is None:
                candidates = tuple(frame_root.rglob("*"))
                parent_directories = {
                    path.parent
                    for path in candidates
                    if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
                }
                if len(parent_directories) != 1:
                    raise RecordingInferenceError(
                        "timestamp-named images in a ZIP must share one directory, "
                        "or supply a camera CSV"
                    )
                frame_root = next(iter(parent_directories))
        yield _resolve_manifest_frames(
            frame_root,
            tuple((timestamp, None) for timestamp, _ in timestamp_rows)
            if suffix in _VIDEO_SUFFIXES and timestamp_rows is not None
            else timestamp_rows,
        )


def _normalized_imu(samples: Sequence[ImuSample], data_config: DataConfig) -> Any:
    import torch

    return torch.tensor(
        [
            (
                *(
                    component / data_config.gyroscope_scale_rad_s
                    for component in sample.angular_velocity_rad_s
                ),
                *(
                    component / data_config.accelerometer_scale_m_s2
                    for component in sample.linear_acceleration_m_s2
                ),
            )
            for sample in samples
        ],
        dtype=torch.float32,
    )


def _matmul(left: Matrix3, right: Matrix3) -> Matrix3:
    return tuple(
        tuple(
            math.fsum(left[row][index] * right[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _matvec(matrix: Matrix3, vector: Vector3) -> Vector3:
    return tuple(
        math.fsum(matrix[row][column] * vector[column] for column in range(3)) for row in range(3)
    )  # type: ignore[return-value]


def _matrix_to_quaternion(matrix: Matrix3) -> tuple[float, float, float, float]:
    """Convert a proper rotation matrix to a normalized ``(w,x,y,z)`` quaternion."""

    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0.0:
        scale = 2.0 * math.sqrt(trace + 1.0)
        quaternion = (
            0.25 * scale,
            (matrix[2][1] - matrix[1][2]) / scale,
            (matrix[0][2] - matrix[2][0]) / scale,
            (matrix[1][0] - matrix[0][1]) / scale,
        )
    else:
        diagonal = (matrix[0][0], matrix[1][1], matrix[2][2])
        index = max(range(3), key=diagonal.__getitem__)
        if index == 0:
            scale = 2.0 * math.sqrt(max(0.0, 1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2]))
            quaternion = (
                (matrix[2][1] - matrix[1][2]) / scale,
                0.25 * scale,
                (matrix[0][1] + matrix[1][0]) / scale,
                (matrix[0][2] + matrix[2][0]) / scale,
            )
        elif index == 1:
            scale = 2.0 * math.sqrt(max(0.0, 1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2]))
            quaternion = (
                (matrix[0][2] - matrix[2][0]) / scale,
                (matrix[0][1] + matrix[1][0]) / scale,
                0.25 * scale,
                (matrix[1][2] + matrix[2][1]) / scale,
            )
        else:
            scale = 2.0 * math.sqrt(max(0.0, 1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1]))
            quaternion = (
                (matrix[1][0] - matrix[0][1]) / scale,
                (matrix[0][2] + matrix[2][0]) / scale,
                (matrix[1][2] + matrix[2][1]) / scale,
                0.25 * scale,
            )
    norm = math.sqrt(math.fsum(component * component for component in quaternion))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise RecordingInferenceError("integrated orientation is not a finite rotation")
    normalized = tuple(component / norm for component in quaternion)
    if normalized[0] < 0.0:
        normalized = tuple(-component for component in normalized)
    return normalized  # type: ignore[return-value]


def _integrate(
    frames: Sequence[CameraSample],
    motions: Sequence[MotionEstimate],
) -> tuple[PoseSample, ...]:
    if len(motions) != len(frames) - 1:
        raise RecordingInferenceError("motion count must equal frame count minus one")
    zero = MotionEstimate((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    position: Vector3 = (0.0, 0.0, 0.0)
    rotation = _IDENTITY
    poses = [PoseSample(frames[0].timestamp_ns, position, (1.0, 0.0, 0.0, 0.0), zero)]
    for frame, motion in zip(frames[1:], motions, strict=True):
        world_increment = _matvec(rotation, motion.translation_previous_m)
        position = tuple(
            left + right for left, right in zip(position, world_increment, strict=True)
        )  # type: ignore[assignment]
        rotation = _matmul(rotation, rotation_vector_to_matrix(motion.rotation_vector_rad))
        poses.append(
            PoseSample(
                timestamp_ns=frame.timestamp_ns,
                position_m=position,
                quaternion_wxyz=_matrix_to_quaternion(rotation),
                increment=motion,
            )
        )
    return tuple(poses)


def _atomic_text(path: Path, content: str) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise RecordingInferenceError(f"cannot write artifact {path}: {exc}") from exc


def _trajectory_csv(poses: Sequence[PoseSample]) -> str:
    import io

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "timestamp_ns",
            "x_m",
            "y_m",
            "z_m",
            "qw",
            "qx",
            "qy",
            "qz",
            "delta_x_previous_m",
            "delta_y_previous_m",
            "delta_z_previous_m",
            "delta_rx_rad",
            "delta_ry_rad",
            "delta_rz_rad",
        )
    )
    for pose in poses:
        writer.writerow(
            (
                pose.timestamp_ns,
                *pose.position_m,
                *pose.quaternion_wxyz,
                *pose.increment.translation_previous_m,
                *pose.increment.rotation_vector_rad,
            )
        )
    return output.getvalue()


def _plot_geometry(
    values: Sequence[tuple[float, float]], box: tuple[int, int, int, int]
) -> tuple[tuple[tuple[float, float], ...], tuple[float, float, float, float]]:
    left, top, width, height = box
    xs = tuple(point[0] for point in values)
    ys = tuple(point[1] for point in values)
    minimum_x, maximum_x = min(xs), max(xs)
    minimum_y, maximum_y = min(ys), max(ys)
    padding_x = max((maximum_x - minimum_x) * 0.08, 1e-6)
    padding_y = max((maximum_y - minimum_y) * 0.08, 1e-6)
    minimum_x -= padding_x
    maximum_x += padding_x
    minimum_y -= padding_y
    maximum_y += padding_y
    mapped = tuple(
        (
            left + (x - minimum_x) / (maximum_x - minimum_x) * width,
            top + height - (y - minimum_y) / (maximum_y - minimum_y) * height,
        )
        for x, y in values
    )
    return mapped, (minimum_x, maximum_x, minimum_y, maximum_y)


def _plot_points(values: Sequence[tuple[float, float]], box: tuple[int, int, int, int]) -> str:
    mapped, _ = _plot_geometry(values, box)
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in mapped)


def _trajectory_svg(poses: Sequence[PoseSample], *, title: str) -> str:
    xy = tuple((pose.position_m[0], pose.position_m[1]) for pose in poses)
    xz = tuple((pose.position_m[0], pose.position_m[2]) for pose in poses)
    xy_mapped, xy_bounds = _plot_geometry(xy, (55, 120, 400, 270))
    xz_mapped, xz_bounds = _plot_geometry(xz, (545, 120, 400, 270))
    path_length = math.fsum(
        math.dist(previous.position_m, current.position_m)
        for previous, current in zip(poses, poses[1:], strict=False)
    )
    final = poses[-1].position_m
    safe_title = html.escape(title)
    description = html.escape(
        f"Estimated local path with {len(poses)} poses and {path_length:.3f} metres of motion. "
        f"It ends at x {final[0]:.3f}, y {final[1]:.3f}, z {final[2]:.3f} metres. "
        "Both views are autoscaled and contain no ground-truth reference."
    )
    xy_start, xy_end = xy_mapped[0], xy_mapped[-1]
    xz_start, xz_end = xz_mapped[0], xz_mapped[-1]

    def axis_labels(
        *, left: int, right: int, top: int, bottom: int, bounds: tuple[float, float, float, float]
    ) -> str:
        minimum_x, maximum_x, minimum_y, maximum_y = bounds
        return (
            '<g fill="#94a3b8" font-family="sans-serif" font-size="11">'
            f'<text x="{left}" y="{bottom}" text-anchor="start">x {minimum_x:.3f}</text>'
            f'<text x="{right}" y="{bottom}" text-anchor="end">{maximum_x:.3f}</text>'
            f'<text x="{left - 5}" y="{top}" text-anchor="end">{maximum_y:.3f}</text>'
            f'<text x="{left - 5}" y="{bottom - 22}" text-anchor="end">{minimum_y:.3f}</text>'
            "</g>"
        )

    def marker(point: tuple[float, float], *, color: str, label: str) -> str:
        x, y = point
        return (
            f'<g fill="{color}"><circle cx="{x:.2f}" cy="{y:.2f}" r="5"/>'
            f'<text x="{x + 8:.2f}" y="{y - 8:.2f}" fill="#e2e8f0" '
            f'font-family="sans-serif" font-size="12">{label}</text></g>'
        )

    return "\n".join(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="540" '
            'viewBox="0 0 1000 540" role="img" aria-labelledby="title desc">',
            f'<title id="title">{safe_title}</title>',
            f'<desc id="desc">{description}</desc>',
            '<rect width="1000" height="540" fill="#0b1020"/>',
            '<text x="40" y="44" fill="#f8fafc" font-family="sans-serif" '
            f'font-size="24" font-weight="700">{safe_title}</text>',
            '<g fill="none" stroke="#334155" stroke-width="1">'
            '<rect x="40" y="80" width="430" height="350"/>'
            '<rect x="530" y="80" width="430" height="350"/></g>',
            '<g fill="#cbd5e1" font-family="sans-serif" font-size="16">'
            '<text x="50" y="105">XY top view (metres)</text>'
            '<text x="540" y="105">XZ side view (metres)</text></g>',
            f'<polyline points="{_plot_points(xy, (55, 120, 400, 270))}" fill="none" '
            'stroke="#38bdf8" stroke-width="3" stroke-linejoin="round"/>',
            f'<polyline points="{_plot_points(xz, (545, 120, 400, 270))}" fill="none" '
            'stroke="#a78bfa" stroke-width="3" stroke-linejoin="round"/>',
            axis_labels(left=55, right=455, top=124, bottom=422, bounds=xy_bounds),
            axis_labels(left=545, right=945, top=124, bottom=422, bounds=xz_bounds),
            marker(xy_start, color="#22c55e", label="start"),
            marker(xy_end, color="#f59e0b", label="end"),
            marker(xz_start, color="#22c55e", label="start"),
            marker(xz_end, color="#f59e0b", label="end"),
            '<text x="40" y="474" fill="#cbd5e1" font-family="sans-serif" '
            f'font-size="14">Estimated path: {path_length:.3f} m across {len(poses)} poses.</text>',
            '<text x="40" y="500" fill="#94a3b8" font-family="sans-serif" '
            'font-size="13">Views are autoscaled to this recording. Raw local estimate; no '
            "alignment, smoothing, or ground truth.</text>",
            "</svg>",
        )
    )


def _summary_html(summary: dict[str, object], svg: str) -> str:
    quality = summary.get("model_quality")
    quality_record = quality if type(quality) is dict else {}
    quality_status = quality_record.get("status", "not_assessed")
    quality_headline = html.escape(
        str(quality_record.get("headline", "Accuracy has not been verified for this model"))
    )
    quality_explanation = html.escape(
        str(
            quality_record.get(
                "explanation",
                "This recording has no ground-truth trajectory, so its accuracy is unknown.",
            )
        )
    )
    recommended_use = html.escape(
        str(quality_record.get("recommended_use", "Treat this as an unverified estimate."))
    )
    current_recording_accuracy = html.escape(
        str(
            quality_record.get(
                "current_recording_accuracy",
                "unverified_without_ground_truth",
            )
        )
    )
    current_recording_html = (
        "<p><strong>Accuracy for this recording:</strong> Unverified. "
        "No reference path was supplied, so this report cannot measure whether the uploaded "
        "trajectory is correct.</p>"
        if current_recording_accuracy == "unverified_without_ground_truth"
        else ""
    )
    quality_label = {
        "accepted": "Benchmark passed",
        "rejected": "Benchmark not passed",
    }.get(str(quality_status), "Benchmark not available")
    quality_class = {
        "accepted": "verdict accepted",
        "rejected": "verdict limited",
    }.get(str(quality_status), "verdict unknown")
    development_passed = quality_record.get("development_passed")
    development_total = quality_record.get("development_total")
    development_html = ""
    if type(development_passed) is int and type(development_total) is int and development_total:
        development_html = (
            '<p class="supporting">Development checks: '
            f"{development_passed}/{development_total} passed. "
            "The held-out test determines the overall verdict.</p>"
        )
    failed_gates = quality_record.get("failed_gates")
    failed_html = ""
    if type(failed_gates) in (list, tuple) and failed_gates:
        safe_failures = ", ".join(html.escape(str(item)) for item in failed_gates)
        failed_html = f'<p class="supporting"><strong>Failed checks:</strong> {safe_failures}.</p>'

    rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in summary.items()
        if key not in {"model_quality", "quality_warning"}
    )
    metrics = (
        ("Frames processed", summary.get("frames", "—")),
        ("Motion estimates", summary.get("predicted_pairs", "—")),
        ("Estimated path", f"{float(summary.get('predicted_path_length_m', 0.0)):.3f} m"),
        ("Start-to-end", f"{float(summary.get('final_displacement_m', 0.0)):.3f} m"),
        ("Processing time", f"{float(summary.get('runtime_s', 0.0)):.3f} s"),
    )
    metric_cards = "".join(
        '<div class="metric"><span>'
        f"{html.escape(label)}</span><strong>{html.escape(str(value))}</strong></div>"
        for label, value in metrics
    )
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>CompactVIO trajectory result</title><style>",
            ":root{color-scheme:dark}*{box-sizing:border-box}",
            "body{margin:0;background:#070b16;color:#e2e8f0;font-family:Inter,system-ui,sans-serif}",
            "main{max-width:1080px;margin:auto;padding:40px 24px 64px}",
            "h1{font-size:2.25rem;margin:0 0 8px}h2{margin:0 0 10px;font-size:1.35rem}",
            "p{color:#cbd5e1;line-height:1.6}.eyebrow{text-transform:uppercase;letter-spacing:.12em;"
            "font-size:.75rem;font-weight:800;color:#86efac}",
            ".run{padding:20px 22px;border:1px solid #166534;background:#052e16;border-radius:14px;"
            "margin:24px 0}",
            ".metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;"
            "margin:20px 0}.metric{padding:16px;background:#0f172a;border:1px solid #334155;"
            "border-radius:12px}.metric span{display:block;color:#94a3b8;font-size:.82rem;"
            "margin-bottom:6px}.metric strong{font-size:1.2rem}",
            ".verdict{padding:22px;border-radius:14px;border:1px solid #475569;margin:24px 0}",
            ".verdict.limited{background:#451a03;border-color:#f59e0b}.verdict.accepted{"
            "background:#052e16;border-color:#22c55e}.verdict.unknown{background:#172033}",
            ".verdict .label{font-weight:800;margin:0 0 8px}.supporting{font-size:.92rem}",
            "section.chart{margin-top:30px}svg{max-width:100%;height:auto;border-radius:14px;"
            "border:1px solid #334155}",
            "details{margin-top:28px;border:1px solid #334155;border-radius:12px;padding:14px 18px;"
            "background:#0f172a}summary{cursor:pointer;font-weight:700}",
            "table{border-collapse:collapse;width:100%;margin-top:16px}th,td{padding:9px 12px;"
            "border-top:1px solid #334155;text-align:left;vertical-align:top;word-break:break-word}"
            "th{width:42%;color:#7dd3fc}@media(max-width:640px){main{padding:24px 14px 40px}"
            "h1{font-size:1.75rem}}</style></head>",
            "<body><main><h1>Your estimated trajectory</h1>",
            "<p>This report separates a successful software run from model accuracy.</p>",
            '<section class="run" role="status"><div class="eyebrow">Run completed</div>',
            "<h2>The recording was processed and result files were created</h2>",
            "<p>This confirms that the camera, IMU, calibration, model, and export pipeline "
            "worked. "
            "It does not prove the estimated path is accurate.</p></section>",
            f'<section class="metrics" aria-label="Run summary">{metric_cards}</section>',
            f'<section class="{quality_class}"><p class="label">Model quality: '
            f"{quality_label}</p><h2>{quality_headline}</h2>",
            f"<p>{quality_explanation}</p>{current_recording_html}"
            "<p><strong>What you can use it for:</strong> "
            f"{recommended_use}</p>{development_html}{failed_html}</section>",
            f'<section class="chart"><h2>Estimated local path</h2>{svg}</section>',
            f"<details><summary>Technical run details</summary><table>{rows}</table></details>",
            "</main></body></html>",
        )
    )


def run_recording(
    *,
    recording_path: Path | str,
    imu_csv_path: Path | str,
    output_directory: Path | str,
    backend: MotionBackend,
    camera_timestamps_path: Path | str | None = None,
    calibration_path: Path | str | None = None,
    sequence_id: str = "recording",
) -> InferenceArtifacts:
    """Run every causal pair and write trajectory CSV, SVG, HTML, and JSON."""

    if type(sequence_id) is not str or not sequence_id.strip():
        raise RecordingInferenceError("sequence_id must be a non-empty string")
    if not callable(getattr(backend, "predict_recording", None)) and not (
        isinstance(getattr(backend, "model_config", None), ModelConfig)
        and isinstance(getattr(backend, "data_config", None), DataConfig)
    ):
        raise RecordingInferenceError(
            "backend must implement predict_recording or declare model_config and data_config"
        )
    output = Path(output_directory)
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise RecordingInferenceError(f"output must be a regular directory: {output}")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists() and any(output.iterdir()):
            raise RecordingInferenceError(
                f"output directory must be empty to avoid mixing run artifacts: {output}"
            )
    except OSError as exc:
        raise RecordingInferenceError(f"cannot prepare output directory {output}: {exc}") from exc

    started = time.perf_counter()
    calibration_sha256: str | None = None
    calibration: dict[str, object] | None = None
    if calibration_path is not None:
        calibration, calibration_sha256 = load_calibration(calibration_path)
    imu = load_imu_csv(imu_csv_path)
    imu_timestamps = tuple(sample.timestamp_ns for sample in imu)
    motions: list[MotionEstimate] = []
    state: object | None = None
    with camera_samples(recording_path, camera_timestamps_path) as frames:
        recording_predictor = getattr(backend, "predict_recording", None)
        if callable(recording_predictor):
            predicted = tuple(recording_predictor(frames, imu, calibration))
            if len(predicted) != len(frames) - 1:
                raise RecordingInferenceError(
                    "recording backend must return exactly one motion per frame pair"
                )
            if not all(isinstance(estimate, MotionEstimate) for estimate in predicted):
                raise RecordingInferenceError("recording backend returned an invalid motion")
            motions.extend(predicted)
        else:
            if not isinstance(
                getattr(backend, "model_config", None), ModelConfig
            ) or not isinstance(getattr(backend, "data_config", None), DataConfig):
                raise RecordingInferenceError(
                    "step backend must declare valid model_config and data_config"
                )
            from compact_vio.learning.dataset import _normalized_image_tensor

            previous_tensor = _normalized_image_tensor(
                frames[0].image_path,
                model_config=backend.model_config,
                data_config=backend.data_config,
            )
            for previous, current in zip(frames, frames[1:], strict=False):
                current_tensor = _normalized_image_tensor(
                    current.image_path,
                    model_config=backend.model_config,
                    data_config=backend.data_config,
                )
                start = bisect.bisect_right(imu_timestamps, previous.timestamp_ns)
                end = bisect.bisect_right(imu_timestamps, current.timestamp_ns)
                window = imu[start:end]
                if not window:
                    raise RecordingInferenceError(
                        "no causal IMU sample in camera interval "
                        f"({previous.timestamp_ns}, {current.timestamp_ns}]"
                    )
                import torch

                frame_pair = torch.stack((previous_tensor, current_tensor))
                estimate, state = backend.predict_step(
                    frame_pair,
                    _normalized_imu(window, backend.data_config),
                    (current.timestamp_ns - previous.timestamp_ns) * 1e-9,
                    state,
                )
                if not isinstance(estimate, MotionEstimate):
                    raise RecordingInferenceError("backend must return a MotionEstimate")
                motions.append(estimate)
                previous_tensor = current_tensor
        poses = _integrate(frames, motions)

    elapsed_s = time.perf_counter() - started
    path_length = math.fsum(
        math.hypot(*pose.increment.translation_previous_m) for pose in poses[1:]
    )
    final_displacement = math.hypot(*poses[-1].position_m)
    duration_s = (poses[-1].timestamp_ns - poses[0].timestamp_ns) * 1e-9
    model_quality = assess_model_quality(backend)
    summary: dict[str, object] = {
        "run_status": "completed",
        "sequence_id": sequence_id,
        "frames": len(poses),
        "predicted_pairs": len(motions),
        "recording_duration_s": round(duration_s, 6),
        "predicted_path_length_m": round(path_length, 6),
        "final_displacement_m": round(final_displacement, 6),
        "runtime_s": round(elapsed_s, 6),
        "mean_runtime_ms_per_pair": round(elapsed_s * 1000.0 / len(motions), 3),
        "trajectory_convention": "local-frame/raw-no-alignment/v1",
        "backend_id": getattr(backend, "backend_id", type(backend).__name__),
        "model_identity": getattr(backend, "model_identity", "not-declared"),
        "motion_frame": getattr(backend, "motion_frame", "previous camera/body frame"),
        "quality_status": getattr(backend, "quality_status", "not_declared"),
        "quality_warning": getattr(backend, "quality_warning", None),
        "accuracy_for_this_recording": model_quality.current_recording_accuracy,
        "model_quality": asdict(model_quality),
        "calibration_sha256": calibration_sha256 or "not-supplied",
        "calibration_usage": getattr(
            backend,
            "calibration_usage",
            "recorded-only; current model uses grayscale-resize-normalize",
        ),
    }
    svg = _trajectory_svg(poses, title=f"CompactVIO — {sequence_id}")
    try:
        staging = Path(
            tempfile.mkdtemp(prefix=f".{output.name or 'result'}.staging-", dir=output.parent)
        )
    except OSError as exc:
        raise RecordingInferenceError(f"cannot stage output directory {output}: {exc}") from exc
    try:
        _atomic_text(staging / "trajectory.csv", _trajectory_csv(poses))
        _atomic_text(staging / "trajectory.svg", svg)
        _atomic_text(staging / "summary.html", _summary_html(summary, svg))
        _atomic_text(
            staging / "summary.json",
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        )
        if output.is_symlink() or (output.exists() and not output.is_dir()):
            raise RecordingInferenceError(f"output changed before publication: {output}")
        if output.exists():
            try:
                if any(output.iterdir()):
                    raise RecordingInferenceError(
                        f"output directory changed before publication: {output}"
                    )
                output.rmdir()
            except OSError as exc:
                raise RecordingInferenceError(
                    f"cannot publish result to output directory {output}: {exc}"
                ) from exc
        try:
            staging.replace(output)
        except OSError as exc:
            raise RecordingInferenceError(
                f"cannot publish complete result directory {output}: {exc}"
            ) from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    csv_path = output / "trajectory.csv"
    svg_path = output / "trajectory.svg"
    html_path = output / "summary.html"
    json_path = output / "summary.json"
    return InferenceArtifacts(
        trajectory_csv=csv_path.resolve(),
        trajectory_svg=svg_path.resolve(),
        summary_html=html_path.resolve(),
        summary_json=json_path.resolve(),
        frame_count=len(poses),
        pair_count=len(motions),
        path_length_m=float(path_length),
        final_displacement_m=float(final_displacement),
        elapsed_s=float(elapsed_s),
    )


_RAFT_CALIBRATION_EXAMPLE = """RAFT hybrid calibration JSON/YAML shape (T_BS maps each sensor into
the IMU sensor frame; imu.T_BS must be identity):
{
  "camera": {
    "T_BS": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
    "camera_model": "pinhole",
    "distortion_coefficients": [0.0,0.0,0.0,0.0],
    "distortion_model": "radtan",
    "intrinsics": [200.0,200.0,188.0,120.0],
    "resolution": [376,240]
  },
  "imu": {"T_BS": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}
}
Every source frame must exactly match resolution. The IMU CSV must include at least two
samples strictly before the first camera timestamp. Keep the rig stationary during the
recommended 1.0-1.84 s pre-roll so mean angular velocity represents gyro bias, not motion.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-run",
        description=(
            "Run a RAFT hybrid model package or legacy CompactVIO checkpoint on a recorded "
            "camera and IMU stream."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_RAFT_CALIBRATION_EXAMPLE,
    )
    parser.add_argument(
        "--recording", required=True, help="MP4, image ZIP, or timestamped image directory"
    )
    parser.add_argument("--camera-timestamps", help="camera timestamp CSV; required for MP4")
    parser.add_argument(
        "--imu",
        required=True,
        help=(
            "timestamped six-axis IMU CSV; hybrid requires >=2 samples strictly before the "
            "first camera frame; keep the rig stationary during the recommended 1.0-1.84 s "
            "gyro-bias pre-roll"
        ),
    )
    parser.add_argument(
        "--calibration",
        help="combined camera/IMU JSON/YAML; required with --model-package (shape below)",
    )
    model = parser.add_mutually_exclusive_group(required=True)
    model.add_argument("--checkpoint", help="legacy training or inference checkpoint")
    model.add_argument(
        "--model-package",
        help="RAFT-small hybrid package manifest.json",
    )
    parser.add_argument(
        "--checkpoint-sha256",
        help="required external SHA-256 when --checkpoint is an inference-only artifact",
    )
    parser.add_argument(
        "--model-package-sha256",
        help="optional expected SHA-256 of the hybrid package manifest",
    )
    parser.add_argument(
        "--raft-batch-size",
        type=int,
        default=8,
        help="frame pairs per RAFT batch for --model-package (default: 8)",
    )
    parser.add_argument("--output", required=True, help="directory for trajectory artifacts")
    parser.add_argument("--sequence-id", default="recording")
    parser.add_argument("--device", default="cpu", help="PyTorch device, for example cpu or cuda")
    parser.add_argument(
        "--state-policy",
        choices=("stateful", "independent"),
        default="stateful",
        help="legacy checkpoint only; ignored by stateless RAFT packages",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.model_package is not None:
            if args.calibration is None:
                raise RecordingInferenceError("--calibration is required with --model-package")
            if args.checkpoint_sha256 is not None:
                raise RecordingInferenceError(
                    "--checkpoint-sha256 cannot be used with --model-package"
                )
            from compact_vio.learning.raft_hybrid import RaftHybridBackend

            backend: object = RaftHybridBackend(
                args.model_package,
                device=args.device,
                batch_size=args.raft_batch_size,
                expected_manifest_sha256=args.model_package_sha256,
            )
            if getattr(backend, "quality_status", None) == "experimental_rejected":
                print(
                    json.dumps(
                        {
                            "event": "model_quality_warning",
                            "quality_status": backend.quality_status,
                            "warning": backend.quality_warning,
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                    flush=True,
                )
        else:
            if args.model_package_sha256 is not None:
                raise RecordingInferenceError("--model-package-sha256 requires --model-package")
            backend = TorchCheckpointBackend(
                args.checkpoint,
                device=args.device,
                expected_checkpoint_sha256=args.checkpoint_sha256,
                state_policy=args.state_policy,
            )
        result = run_recording(
            recording_path=args.recording,
            camera_timestamps_path=args.camera_timestamps,
            calibration_path=args.calibration,
            imu_csv_path=args.imu,
            output_directory=args.output,
            backend=backend,  # type: ignore[arg-type]
            sequence_id=args.sequence_id,
        )
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "event": "recording_inference_failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "recording_inference_complete",
                "frame_count": result.frame_count,
                "pair_count": result.pair_count,
                "trajectory_csv": str(result.trajectory_csv),
                "trajectory_svg": str(result.trajectory_svg),
                "summary_html": str(result.summary_html),
                "summary_json": str(result.summary_json),
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CameraSample",
    "ImuSample",
    "InferenceArtifacts",
    "ModelQualityAssessment",
    "MotionBackend",
    "RecordingBackend",
    "MotionEstimate",
    "PoseSample",
    "RecordingInferenceError",
    "TorchCheckpointBackend",
    "build_parser",
    "assess_model_quality",
    "camera_samples",
    "load_camera_timestamps",
    "load_calibration",
    "load_imu_csv",
    "main",
    "run_recording",
]

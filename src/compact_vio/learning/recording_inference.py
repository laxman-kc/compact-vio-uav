"""Run a trained CompactVIO checkpoint on a recorded camera and IMU stream.

This module is intentionally the small, user-facing bridge between a recording
and useful trajectory artifacts.  It accepts either timestamp-named images or
an MP4 plus an explicit camera timestamp CSV, applies the checkpoint's own
training preprocessing, carries the causal fusion state, integrates relative
motions, and writes CSV/SVG/HTML outputs.
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
import sys
import tempfile
import time
import zipfile
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
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
_MAX_ARCHIVE_MEMBERS = 100_000
_MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024
_MAX_ARCHIVE_TOTAL_BYTES = 32 * 1024 * 1024 * 1024


class RecordingInferenceError(LearningError):
    """Raised when an input recording or inference output is invalid."""


@dataclass(frozen=True, slots=True)
class CameraSample:
    """One decoded camera frame with its sensor-clock timestamp."""

    timestamp_ns: int
    image_path: Path

    def __post_init__(self) -> None:
        if type(self.timestamp_ns) is not int or self.timestamp_ns < 0:
            raise RecordingInferenceError("camera timestamp_ns must be non-negative")
        if not isinstance(self.image_path, Path):
            raise RecordingInferenceError("camera image_path must be a pathlib.Path")


@dataclass(frozen=True, slots=True)
class ImuSample:
    """One six-axis IMU sample in the model's expected sensor convention."""

    timestamp_ns: int
    angular_velocity_rad_s: Vector3
    linear_acceleration_m_s2: Vector3

    def __post_init__(self) -> None:
        if type(self.timestamp_ns) is not int or self.timestamp_ns < 0:
            raise RecordingInferenceError("IMU timestamp_ns must be non-negative")
        _finite_vector(self.angular_velocity_rad_s, field="angular_velocity_rad_s")
        _finite_vector(self.linear_acceleration_m_s2, field="linear_acceleration_m_s2")


@dataclass(frozen=True, slots=True)
class MotionEstimate:
    """One model prediction expressed in the previous camera/body frame."""

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
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise RecordingInferenceError(f"cannot read {kind} CSV {path}: {exc}") from exc
    reader = csv.DictReader(handle)
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
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
            try:
                timestamp_ns = int(row[timestamp_field])
            except (KeyError, TypeError, ValueError) as exc:
                raise RecordingInferenceError(
                    f"{source}:{line}: camera timestamp_ns must be an integer"
                ) from exc
            filename = row.get(filename_field, "").strip() if filename_field else None
            if filename_field and not filename:
                raise RecordingInferenceError(f"{source}:{line}: filename must not be empty")
            result.append((timestamp_ns, filename))
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

    The current trained model does not undistort or rectify frames; its exact
    preprocessing is grayscale, resize, and normalization.  Calibration is
    nevertheless accepted and fingerprinted so a recording result remains
    bound to the sensor description supplied by the user.
    """

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise RecordingInferenceError(f"calibration must be a regular file: {source}")
    try:
        encoded = source.read_bytes()
        document = encoded.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise RecordingInferenceError(f"cannot read calibration {source}: {exc}") from exc
    try:
        value = json.loads(document)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RecordingInferenceError(
                "non-JSON calibration requires PyYAML from the data extra"
            ) from exc
        try:
            value = yaml.safe_load(document)
        except yaml.YAMLError as exc:
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
            candidate = (recording / filename).resolve()
            if not candidate.is_relative_to(root):
                raise RecordingInferenceError(
                    f"camera filename escapes recording directory: {filename}"
                )
            if candidate.is_symlink() or not candidate.is_file():
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
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RecordingInferenceError(f"cannot open image ZIP {source}: {exc}") from exc
    with archive:
        members = archive.infolist()
        if len(members) > _MAX_ARCHIVE_MEMBERS:
            raise RecordingInferenceError("image ZIP contains too many members")
        total_bytes = 0
        for member in members:
            pure = PurePosixPath(member.filename)
            if (
                pure.is_absolute()
                or not pure.parts
                or any(part in {"", ".", ".."} for part in pure.parts)
                or "\\" in member.filename
            ):
                raise RecordingInferenceError(
                    f"image ZIP contains an unsafe member path: {member.filename!r}"
                )
            unix_mode = member.external_attr >> 16
            if unix_mode and (unix_mode & 0o170000) == 0o120000:
                raise RecordingInferenceError("image ZIP must not contain symbolic links")
            if member.is_dir():
                continue
            if member.file_size > _MAX_ARCHIVE_MEMBER_BYTES:
                raise RecordingInferenceError("image ZIP member exceeds the size limit")
            total_bytes += member.file_size
            if total_bytes > _MAX_ARCHIVE_TOTAL_BYTES:
                raise RecordingInferenceError("image ZIP exceeds the total expansion limit")
            if pure.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            target = destination.joinpath(*pure.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                with archive.open(member, "r") as input_handle, target.open("xb") as output_handle:
                    while chunk := input_handle.read(1024 * 1024):
                        output_handle.write(chunk)
            except OSError as exc:
                raise RecordingInferenceError(
                    f"cannot extract image ZIP member {member.filename!r}: {exc}"
                ) from exc


def _decode_mp4_opencv(source: Path, destination: Path) -> None:
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
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            count += 1
            output = destination / f"{count:09d}.png"
            if not cv2.imwrite(os.fspath(output), frame):
                raise RecordingInferenceError(f"OpenCV cannot write decoded frame {count}")
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


def _plot_points(values: Sequence[tuple[float, float]], box: tuple[int, int, int, int]) -> str:
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
    return " ".join(
        f"{left + (x - minimum_x) / (maximum_x - minimum_x) * width:.2f},"
        f"{top + height - (y - minimum_y) / (maximum_y - minimum_y) * height:.2f}"
        for x, y in values
    )


def _trajectory_svg(poses: Sequence[PoseSample], *, title: str) -> str:
    xy = tuple((pose.position_m[0], pose.position_m[1]) for pose in poses)
    xz = tuple((pose.position_m[0], pose.position_m[2]) for pose in poses)
    safe_title = html.escape(title)
    return "\n".join(
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="500" '
            'viewBox="0 0 1000 500" role="img" aria-labelledby="title desc">',
            f'<title id="title">{safe_title}</title>',
            '<desc id="desc">Integrated CompactVIO trajectory in XY and XZ views.</desc>',
            '<rect width="1000" height="500" fill="#0b1020"/>',
            '<text x="40" y="44" fill="#f8fafc" font-family="sans-serif" '
            f'font-size="24" font-weight="700">{safe_title}</text>',
            '<g fill="none" stroke="#334155" stroke-width="1">'
            '<rect x="40" y="80" width="430" height="350"/>'
            '<rect x="530" y="80" width="430" height="350"/></g>',
            '<g fill="#cbd5e1" font-family="sans-serif" font-size="16">'
            '<text x="50" y="105">XY top view (metres)</text>'
            '<text x="540" y="105">XZ side view (metres)</text></g>',
            f'<polyline points="{_plot_points(xy, (55, 120, 400, 290))}" fill="none" '
            'stroke="#38bdf8" stroke-width="3" stroke-linejoin="round"/>',
            f'<polyline points="{_plot_points(xz, (545, 120, 400, 290))}" fill="none" '
            'stroke="#a78bfa" stroke-width="3" stroke-linejoin="round"/>',
            '<g fill="#22c55e"><circle cx="55" cy="410" r="5"/>'
            '<text x="68" y="416" fill="#cbd5e1" font-family="sans-serif" '
            'font-size="13">start</text></g>',
            '<text x="40" y="470" fill="#94a3b8" font-family="sans-serif" '
            'font-size="13">Raw integrated model output; no alignment, smoothing, '
            "or ground truth.</text>",
            "</svg>",
        )
    )


def _summary_html(summary: dict[str, object], svg: str) -> str:
    rows = "".join(
        f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(str(value))}</td></tr>"
        for key, value in summary.items()
    )
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en"><head><meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            "<title>CompactVIO recording result</title><style>",
            "body{margin:0;background:#070b16;color:#e2e8f0;font-family:system-ui,sans-serif}",
            "main{max-width:1040px;margin:auto;padding:28px}h1{margin-bottom:6px}",
            "p{color:#94a3b8}table{border-collapse:collapse;width:100%;"
            "margin:20px 0;background:#0f172a}",
            "th,td{padding:10px 14px;border:1px solid #334155;text-align:left}"
            "th{width:45%;color:#7dd3fc}",
            "svg{max-width:100%;height:auto;border-radius:12px}</style></head>",
            "<body><main><h1>CompactVIO recording result</h1>",
            "<p>Raw causal model inference and integrated local trajectory.</p>",
            f"<table>{rows}</table>{svg}</main></body></html>",
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
    if not isinstance(getattr(backend, "model_config", None), ModelConfig) or not isinstance(
        getattr(backend, "data_config", None), DataConfig
    ):
        raise RecordingInferenceError("backend must declare valid model_config and data_config")
    output = Path(output_directory)
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        raise RecordingInferenceError(f"output must be a regular directory: {output}")
    try:
        output.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RecordingInferenceError(f"cannot create output directory {output}: {exc}") from exc

    started = time.perf_counter()
    calibration_sha256: str | None = None
    if calibration_path is not None:
        _, calibration_sha256 = load_calibration(calibration_path)
    imu = load_imu_csv(imu_csv_path)
    imu_timestamps = tuple(sample.timestamp_ns for sample in imu)
    motions: list[MotionEstimate] = []
    state: object | None = None
    with camera_samples(recording_path, camera_timestamps_path) as frames:
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
    summary: dict[str, object] = {
        "sequence_id": sequence_id,
        "frames": len(poses),
        "predicted_pairs": len(motions),
        "recording_duration_s": round(duration_s, 6),
        "predicted_path_length_m": round(path_length, 6),
        "final_displacement_m": round(final_displacement, 6),
        "runtime_s": round(elapsed_s, 6),
        "mean_runtime_ms_per_pair": round(elapsed_s * 1000.0 / len(motions), 3),
        "trajectory_convention": "local-frame/raw-no-alignment/v1",
        "calibration_sha256": calibration_sha256 or "not-supplied",
        "calibration_usage": "recorded-only; current model uses grayscale-resize-normalize",
    }
    csv_path = output / "trajectory.csv"
    svg_path = output / "trajectory.svg"
    html_path = output / "summary.html"
    json_path = output / "summary.json"
    svg = _trajectory_svg(poses, title=f"CompactVIO — {sequence_id}")
    _atomic_text(csv_path, _trajectory_csv(poses))
    _atomic_text(svg_path, svg)
    _atomic_text(html_path, _summary_html(summary, svg))
    _atomic_text(json_path, json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n")
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-run",
        description="Run a CompactVIO checkpoint on MP4, image ZIP, or timestamped images.",
    )
    parser.add_argument(
        "--recording", required=True, help="MP4, image ZIP, or timestamped image directory"
    )
    parser.add_argument("--camera-timestamps", help="camera timestamp CSV; required for MP4")
    parser.add_argument("--imu", required=True, help="timestamped six-axis IMU CSV")
    parser.add_argument("--calibration", help="JSON/YAML camera-IMU calibration to fingerprint")
    parser.add_argument("--checkpoint", required=True, help="training or inference checkpoint")
    parser.add_argument(
        "--checkpoint-sha256",
        help="required external SHA-256 when --checkpoint is an inference-only artifact",
    )
    parser.add_argument("--output", required=True, help="directory for trajectory artifacts")
    parser.add_argument("--sequence-id", default="recording")
    parser.add_argument("--device", default="cpu", help="PyTorch device, for example cpu or cuda")
    parser.add_argument(
        "--state-policy",
        choices=("stateful", "independent"),
        default="stateful",
        help="carry fusion state across contiguous pairs (default: stateful)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
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
            backend=backend,
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
    "MotionBackend",
    "MotionEstimate",
    "PoseSample",
    "RecordingInferenceError",
    "TorchCheckpointBackend",
    "build_parser",
    "camera_samples",
    "load_camera_timestamps",
    "load_calibration",
    "load_imu_csv",
    "main",
    "run_recording",
]

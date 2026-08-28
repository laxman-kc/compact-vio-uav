"""Strict reader for the EuRoC MAV Dataset's ASL directory format.

The reader preserves source units, timestamp scale, axis labels, transform
direction, and quaternion order.  It never guesses a missing path, changes a
frame convention, converts nanoseconds to seconds, or substitutes calibration.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_CAMERA_CSV = PurePosixPath("mav0/cam0/data.csv")
_CAMERA_DATA = PurePosixPath("mav0/cam0/data")
_CAMERA_YAML = PurePosixPath("mav0/cam0/sensor.yaml")
_IMU_CSV = PurePosixPath("mav0/imu0/data.csv")
_IMU_YAML = PurePosixPath("mav0/imu0/sensor.yaml")
_GROUND_TRUTH_CSV = PurePosixPath("mav0/state_groundtruth_estimate0/data.csv")
_GROUND_TRUTH_YAML = PurePosixPath("mav0/state_groundtruth_estimate0/sensor.yaml")
_TIMESTAMP_PATTERN = re.compile(r"[0-9]+")

_CAMERA_HEADER = ("#timestamp [ns]", "filename")
_IMU_HEADER = (
    "#timestamp [ns]",
    "w_RS_S_x [rad s^-1]",
    "w_RS_S_y [rad s^-1]",
    "w_RS_S_z [rad s^-1]",
    "a_RS_S_x [m s^-2]",
    "a_RS_S_y [m s^-2]",
    "a_RS_S_z [m s^-2]",
)
_GROUND_TRUTH_HEADERS = (
    (
        "#timestamp",
        "p_RS_R_x [m]",
        "p_RS_R_y [m]",
        "p_RS_R_z [m]",
        "q_RS_w []",
        "q_RS_x []",
        "q_RS_y []",
        "q_RS_z []",
        "v_RS_R_x [m s^-1]",
        "v_RS_R_y [m s^-1]",
        "v_RS_R_z [m s^-1]",
        "b_w_RS_S_x [rad s^-1]",
        "b_w_RS_S_y [rad s^-1]",
        "b_w_RS_S_z [rad s^-1]",
        "b_a_RS_S_x [m s^-2]",
        "b_a_RS_S_y [m s^-2]",
        "b_a_RS_S_z [m s^-2]",
    ),
    (
        "#timestamp [ns]",
        "p_RS_R_x [m]",
        "p_RS_R_y [m]",
        "p_RS_R_z [m]",
        "q_RS_w []",
        "q_RS_x []",
        "q_RS_y []",
        "q_RS_z []",
        "v_RS_R_x [m s^-1]",
        "v_RS_R_y [m s^-1]",
        "v_RS_R_z [m s^-1]",
        "b_w_RS_S_x [rad s^-1]",
        "b_w_RS_S_y [rad s^-1]",
        "b_w_RS_S_z [rad s^-1]",
        "b_a_RS_S_x [m s^-2]",
        "b_a_RS_S_y [m s^-2]",
        "b_a_RS_S_z [m s^-2]",
    ),
)


class EuRoCDataError(ValueError):
    """Raised when a EuRoC source violates the declared ASL contract."""


class EuRoCDependencyError(EuRoCDataError):
    """Raised when an optional parser dependency is needed but unavailable."""


Vector3 = tuple[float, float, float]
QuaternionWxyz = tuple[float, float, float, float]
Matrix4x4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


@dataclass(frozen=True, slots=True)
class CameraCalibration:
    """Native ``cam0/sensor.yaml`` values; ``T_BS`` direction is unchanged."""

    sensor_type: str
    comment: str | None
    t_bs: Matrix4x4
    rate_hz: float
    resolution_width_px: int
    resolution_height_px: int
    camera_model: str
    intrinsics: tuple[float, float, float, float]
    distortion_model: str
    distortion_coefficients: tuple[float, float, float, float]
    source_path: Path


@dataclass(frozen=True, slots=True)
class ImuCalibration:
    """Native ``imu0/sensor.yaml`` values with source units preserved."""

    sensor_type: str
    comment: str | None
    t_bs: Matrix4x4
    rate_hz: float
    gyroscope_noise_density: float
    gyroscope_random_walk: float
    accelerometer_noise_density: float
    accelerometer_random_walk: float
    source_path: Path


@dataclass(frozen=True, slots=True)
class GroundTruthCalibration:
    """Native ground-truth sensor pose declaration."""

    sensor_type: str
    comment: str | None
    t_bs: Matrix4x4
    rate_hz: float | None
    source_path: Path


@dataclass(frozen=True, slots=True)
class CameraFrame:
    """One ``cam0`` image indexed by its native integer nanosecond timestamp."""

    timestamp_ns: int
    filename: str
    image_path: Path


@dataclass(frozen=True, slots=True)
class ImuMeasurement:
    """One native IMU row in ASL's sensor-frame column convention."""

    timestamp_ns: int
    angular_velocity_rs_s_rad_s: Vector3
    linear_acceleration_rs_s_m_s2: Vector3


@dataclass(frozen=True, slots=True)
class GroundTruthState:
    """One native or interpolated ASL ground-truth state.

    Quaternion components remain in source order ``(w, x, y, z)``.  The field
    names mirror the official CSV header rather than claiming another frame.
    """

    timestamp_ns: int
    position_rs_r_m: Vector3
    quaternion_rs_wxyz: QuaternionWxyz
    velocity_rs_r_m_s: Vector3
    gyroscope_bias_rs_s_rad_s: Vector3
    accelerometer_bias_rs_s_m_s2: Vector3


@dataclass(frozen=True, slots=True)
class EuRoCSequence:
    """Fully validated EuRoC sequence loaded from one exact source root."""

    sequence_id: str
    root: Path
    camera_calibration: CameraCalibration
    imu_calibration: ImuCalibration
    ground_truth_calibration: GroundTruthCalibration
    camera_frames: tuple[CameraFrame, ...]
    imu_measurements: tuple[ImuMeasurement, ...]
    ground_truth_states: tuple[GroundTruthState, ...]


@dataclass(frozen=True, slots=True)
class CausalFramePair:
    """Consecutive frames plus exactly the IMU samples in ``(previous, current]``."""

    previous_frame: CameraFrame
    current_frame: CameraFrame
    imu_measurements: tuple[ImuMeasurement, ...]
    previous_ground_truth: GroundTruthState | None
    current_ground_truth: GroundTruthState | None


@dataclass(frozen=True, slots=True)
class SequenceSplits:
    """Sequence identifiers assigned to disjoint train/validation/test sets."""

    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]


def _is_real(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _require_mapping(value: object, *, path: Path) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EuRoCDataError(f"{path}: YAML document must be a mapping")
    if not all(type(key) is str for key in value):
        raise EuRoCDataError(f"{path}: YAML mapping keys must be strings")
    return value


def _reject_json_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EuRoCDataError(f"duplicate YAML/JSON key: {key!r}")
        result[key] = value
    return result


def _load_yaml(path: Path) -> Mapping[str, object]:
    try:
        source = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise EuRoCDataError(f"cannot read calibration {path}: {exc}") from exc

    # JSON is a strict YAML subset and keeps synthetic tests dependency-free.
    try:
        value = json.loads(source, object_pairs_hook=_reject_json_duplicates)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise EuRoCDependencyError(
                f"{path}: PyYAML is required to parse this sensor.yaml file"
            ) from exc

        class UniqueKeyLoader(yaml.SafeLoader):  # type: ignore[misc, name-defined]
            pass

        def construct_mapping(
            loader: UniqueKeyLoader,
            node: object,
            deep: bool = False,
        ) -> dict[object, object]:
            loader.flatten_mapping(node)  # type: ignore[arg-type]
            result: dict[object, object] = {}
            for key_node, value_node in node.value:  # type: ignore[attr-defined]
                key = loader.construct_object(key_node, deep=deep)
                if key in result:
                    raise EuRoCDataError(f"{path}: duplicate YAML key: {key!r}")
                result[key] = loader.construct_object(value_node, deep=deep)
            return result

        UniqueKeyLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            construct_mapping,
        )
        try:
            value = yaml.load(source, Loader=UniqueKeyLoader)
        except EuRoCDataError:
            raise
        except yaml.YAMLError as exc:
            raise EuRoCDataError(f"{path}: invalid YAML: {exc}") from exc
    return _require_mapping(value, path=path)


def _mapping_field(mapping: Mapping[str, object], field: str, *, path: Path) -> object:
    if field not in mapping:
        raise EuRoCDataError(f"{path}: missing required field {field!r}")
    return mapping[field]


def _text_field(
    mapping: Mapping[str, object],
    field: str,
    *,
    path: Path,
    optional: bool = False,
) -> str | None:
    if optional and field not in mapping:
        return None
    value = _mapping_field(mapping, field, path=path)
    if type(value) is not str or not value.strip():
        raise EuRoCDataError(f"{path}: {field} must be a non-empty string")
    return value


def _positive_float(mapping: Mapping[str, object], field: str, *, path: Path) -> float:
    value = _mapping_field(mapping, field, path=path)
    if not _is_real(value) or float(value) <= 0.0:
        raise EuRoCDataError(f"{path}: {field} must be a finite positive number")
    return float(value)


def _optional_positive_float(
    mapping: Mapping[str, object], field: str, *, path: Path
) -> float | None:
    if field not in mapping:
        return None
    return _positive_float(mapping, field, path=path)


def _float_tuple(
    mapping: Mapping[str, object],
    field: str,
    *,
    length: int,
    path: Path,
) -> tuple[float, ...]:
    value = _mapping_field(mapping, field, path=path)
    if not isinstance(value, list) or len(value) != length or not all(_is_real(x) for x in value):
        raise EuRoCDataError(f"{path}: {field} must contain exactly {length} finite numeric values")
    return tuple(float(item) for item in value)


def _t_bs(mapping: Mapping[str, object], *, path: Path) -> Matrix4x4:
    value = _mapping_field(mapping, "T_BS", path=path)
    transform = _require_mapping(value, path=path)
    rows = _mapping_field(transform, "rows", path=path)
    cols = _mapping_field(transform, "cols", path=path)
    if type(rows) is not int or type(cols) is not int or rows != 4 or cols != 4:
        raise EuRoCDataError(f"{path}: T_BS rows and cols must both equal 4")
    flat = _float_tuple(transform, "data", length=16, path=path)
    matrix = tuple(tuple(flat[row * 4 : row * 4 + 4]) for row in range(4))
    if matrix[3] != (0.0, 0.0, 0.0, 1.0):
        raise EuRoCDataError(f"{path}: T_BS bottom row must be exactly [0, 0, 0, 1]")

    rotation = tuple(tuple(matrix[row][col] for col in range(3)) for row in range(3))
    for row in range(3):
        for other in range(3):
            dot = sum(rotation[row][index] * rotation[other][index] for index in range(3))
            expected = 1.0 if row == other else 0.0
            if not math.isclose(dot, expected, rel_tol=0.0, abs_tol=1e-6):
                raise EuRoCDataError(f"{path}: T_BS rotation must be orthonormal")
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if not math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise EuRoCDataError(f"{path}: T_BS rotation determinant must equal +1")
    return matrix  # type: ignore[return-value]


def _load_camera_calibration(path: Path) -> CameraCalibration:
    document = _load_yaml(path)
    sensor_type = _text_field(document, "sensor_type", path=path)
    if sensor_type != "camera":
        raise EuRoCDataError(f"{path}: sensor_type must equal 'camera'")
    resolution = _mapping_field(document, "resolution", path=path)
    if (
        not isinstance(resolution, list)
        or len(resolution) != 2
        or any(type(value) is not int or value <= 0 for value in resolution)
    ):
        raise EuRoCDataError(f"{path}: resolution must be [positive_width, positive_height]")
    intrinsics = _float_tuple(document, "intrinsics", length=4, path=path)
    if intrinsics[0] <= 0.0 or intrinsics[1] <= 0.0:
        raise EuRoCDataError(f"{path}: focal lengths in intrinsics must be positive")
    distortion = _float_tuple(document, "distortion_coefficients", length=4, path=path)
    return CameraCalibration(
        sensor_type=sensor_type,
        comment=_text_field(document, "comment", path=path, optional=True),
        t_bs=_t_bs(document, path=path),
        rate_hz=_positive_float(document, "rate_hz", path=path),
        resolution_width_px=resolution[0],
        resolution_height_px=resolution[1],
        camera_model=_text_field(document, "camera_model", path=path),  # type: ignore[arg-type]
        intrinsics=intrinsics,  # type: ignore[arg-type]
        distortion_model=_text_field(document, "distortion_model", path=path),  # type: ignore[arg-type]
        distortion_coefficients=distortion,  # type: ignore[arg-type]
        source_path=path,
    )


def _load_imu_calibration(path: Path) -> ImuCalibration:
    document = _load_yaml(path)
    sensor_type = _text_field(document, "sensor_type", path=path)
    if sensor_type != "imu":
        raise EuRoCDataError(f"{path}: sensor_type must equal 'imu'")
    return ImuCalibration(
        sensor_type=sensor_type,
        comment=_text_field(document, "comment", path=path, optional=True),
        t_bs=_t_bs(document, path=path),
        rate_hz=_positive_float(document, "rate_hz", path=path),
        gyroscope_noise_density=_positive_float(document, "gyroscope_noise_density", path=path),
        gyroscope_random_walk=_positive_float(document, "gyroscope_random_walk", path=path),
        accelerometer_noise_density=_positive_float(
            document, "accelerometer_noise_density", path=path
        ),
        accelerometer_random_walk=_positive_float(document, "accelerometer_random_walk", path=path),
        source_path=path,
    )


def _load_ground_truth_calibration(path: Path) -> GroundTruthCalibration:
    document = _load_yaml(path)
    sensor_type = _text_field(document, "sensor_type", path=path)
    # The official Vicon-room ASL archives label this estimated state stream
    # ``visual-inertial``. Preserve that source value rather than inventing a
    # synthetic ``ground_truth`` sensor type.
    if sensor_type != "visual-inertial":
        raise EuRoCDataError(f"{path}: sensor_type must equal 'visual-inertial'")
    return GroundTruthCalibration(
        sensor_type=sensor_type,
        comment=_text_field(document, "comment", path=path, optional=True),
        t_bs=_t_bs(document, path=path),
        rate_hz=_optional_positive_float(document, "rate_hz", path=path),
        source_path=path,
    )


def _open_csv(path: Path) -> tuple[tuple[str, ...], list[tuple[int, list[str]]]]:
    try:
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except (OSError, UnicodeError) as exc:
        raise EuRoCDataError(f"cannot open {path}: {exc}") from exc
    with handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise EuRoCDataError(f"{path}: CSV is empty") from exc
        except csv.Error as exc:
            raise EuRoCDataError(f"{path}: invalid CSV header: {exc}") from exc
        rows: list[tuple[int, list[str]]] = []
        try:
            for line_number, row in enumerate(reader, start=2):
                if not row or all(not value.strip() for value in row):
                    raise EuRoCDataError(f"{path}:{line_number}: blank CSV row")
                rows.append((line_number, row))
        except csv.Error as exc:
            raise EuRoCDataError(f"{path}:{reader.line_num}: invalid CSV: {exc}") from exc
    if not rows:
        raise EuRoCDataError(f"{path}: CSV contains no data rows")
    return tuple(value.strip() for value in header), rows


def _require_header(path: Path, actual: tuple[str, ...], expected: tuple[str, ...]) -> None:
    if actual != expected:
        raise EuRoCDataError(f"{path}: unexpected CSV header; expected {expected!r}")


def _timestamp(value: str, *, path: Path, line: int) -> int:
    stripped = value.strip()
    if not _TIMESTAMP_PATTERN.fullmatch(stripped):
        raise EuRoCDataError(f"{path}:{line}: timestamp must be an unsigned decimal integer")
    return int(stripped)


def _float(value: str, *, path: Path, line: int, column: str) -> float:
    try:
        parsed = float(value.strip())
    except ValueError as exc:
        raise EuRoCDataError(f"{path}:{line}: {column} must be numeric") from exc
    if not math.isfinite(parsed):
        raise EuRoCDataError(f"{path}:{line}: {column} must be finite")
    return parsed


def _increasing(timestamp_ns: int, previous_ns: int | None, *, path: Path, line: int) -> None:
    if previous_ns is not None and timestamp_ns <= previous_ns:
        relation = "duplicate" if timestamp_ns == previous_ns else "out-of-order"
        raise EuRoCDataError(
            f"{path}:{line}: timestamps must be strictly increasing ({relation} timestamp)"
        )


def _load_camera_frames(path: Path, data_directory: Path) -> tuple[CameraFrame, ...]:
    header, rows = _open_csv(path)
    _require_header(path, header, _CAMERA_HEADER)
    frames: list[CameraFrame] = []
    previous: int | None = None
    filenames: set[str] = set()
    data_root = data_directory.resolve(strict=True)
    for line, row in rows:
        if len(row) != 2:
            raise EuRoCDataError(f"{path}:{line}: camera row must contain exactly 2 columns")
        timestamp_ns = _timestamp(row[0], path=path, line=line)
        _increasing(timestamp_ns, previous, path=path, line=line)
        filename = row[1].strip()
        filename_path = PurePosixPath(filename)
        if (
            not filename
            or filename_path.is_absolute()
            or len(filename_path.parts) != 1
            or filename_path.parts[0] in (".", "..")
        ):
            raise EuRoCDataError(f"{path}:{line}: filename must be one safe basename")
        if filename in filenames:
            raise EuRoCDataError(f"{path}:{line}: duplicate camera filename {filename!r}")
        image_path = data_directory / filename
        try:
            resolved_image = image_path.resolve(strict=True)
        except OSError as exc:
            raise EuRoCDataError(f"{path}:{line}: image does not exist: {image_path}") from exc
        if resolved_image.parent != data_root or not resolved_image.is_file():
            raise EuRoCDataError(f"{path}:{line}: image is not a regular file in cam0/data")
        frames.append(CameraFrame(timestamp_ns, filename, resolved_image))
        previous = timestamp_ns
        filenames.add(filename)
    return tuple(frames)


def _load_imu(path: Path) -> tuple[ImuMeasurement, ...]:
    header, rows = _open_csv(path)
    _require_header(path, header, _IMU_HEADER)
    measurements: list[ImuMeasurement] = []
    previous: int | None = None
    for line, row in rows:
        if len(row) != len(_IMU_HEADER):
            raise EuRoCDataError(f"{path}:{line}: IMU row must contain exactly 7 columns")
        timestamp_ns = _timestamp(row[0], path=path, line=line)
        _increasing(timestamp_ns, previous, path=path, line=line)
        values = tuple(
            _float(row[index], path=path, line=line, column=_IMU_HEADER[index])
            for index in range(1, 7)
        )
        measurements.append(
            ImuMeasurement(
                timestamp_ns,
                values[0:3],  # type: ignore[arg-type]
                values[3:6],  # type: ignore[arg-type]
            )
        )
        previous = timestamp_ns
    return tuple(measurements)


def _quaternion_norm(quaternion: QuaternionWxyz) -> float:
    return math.sqrt(sum(component * component for component in quaternion))


def _normalized_quaternion(quaternion: QuaternionWxyz) -> QuaternionWxyz:
    norm = _quaternion_norm(quaternion)
    if not math.isfinite(norm) or norm <= 1e-12:
        raise EuRoCDataError("cannot normalize a zero or non-finite quaternion")
    return tuple(component / norm for component in quaternion)  # type: ignore[return-value]


def _load_ground_truth(path: Path) -> tuple[GroundTruthState, ...]:
    header, rows = _open_csv(path)
    if header not in _GROUND_TRUTH_HEADERS:
        raise EuRoCDataError(
            f"{path}: unexpected ground-truth CSV header; expected official EuRoC columns"
        )
    states: list[GroundTruthState] = []
    previous: int | None = None
    for line, row in rows:
        if len(row) != len(header):
            raise EuRoCDataError(
                f"{path}:{line}: ground-truth row must contain exactly {len(header)} columns"
            )
        timestamp_ns = _timestamp(row[0], path=path, line=line)
        _increasing(timestamp_ns, previous, path=path, line=line)
        values = tuple(
            _float(row[index], path=path, line=line, column=header[index])
            for index in range(1, len(header))
        )
        quaternion = values[3:7]
        norm = _quaternion_norm(quaternion)  # type: ignore[arg-type]
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-3):
            raise EuRoCDataError(f"{path}:{line}: q_RS quaternion norm must be within 0.001 of one")
        states.append(
            GroundTruthState(
                timestamp_ns=timestamp_ns,
                position_rs_r_m=values[0:3],  # type: ignore[arg-type]
                quaternion_rs_wxyz=quaternion,  # type: ignore[arg-type]
                velocity_rs_r_m_s=values[7:10],  # type: ignore[arg-type]
                gyroscope_bias_rs_s_rad_s=values[10:13],  # type: ignore[arg-type]
                accelerometer_bias_rs_s_m_s2=values[13:16],  # type: ignore[arg-type]
            )
        )
        previous = timestamp_ns
    return tuple(states)


def _required_file(root: Path, relative: PurePosixPath) -> Path:
    path = root.joinpath(*relative.parts)
    if not path.is_file():
        raise EuRoCDataError(f"missing required EuRoC file: {path}")
    return path.resolve(strict=True)


def _required_directory(root: Path, relative: PurePosixPath) -> Path:
    path = root.joinpath(*relative.parts)
    if not path.is_dir():
        raise EuRoCDataError(f"missing required EuRoC directory: {path}")
    return path.resolve(strict=True)


def load_euroc_sequence(sequence_root: os.PathLike[str] | str) -> EuRoCSequence:
    """Load and fully validate one exact EuRoC ASL-format sequence root."""

    supplied_root = Path(sequence_root)
    try:
        root = supplied_root.resolve(strict=True)
    except OSError as exc:
        raise EuRoCDataError(f"EuRoC sequence root does not exist: {supplied_root}") from exc
    if not root.is_dir():
        raise EuRoCDataError(f"EuRoC sequence root is not a directory: {root}")
    if not root.name.strip():
        raise EuRoCDataError("EuRoC sequence root must have a non-empty directory name")

    camera_csv = _required_file(root, _CAMERA_CSV)
    camera_data = _required_directory(root, _CAMERA_DATA)
    camera_yaml = _required_file(root, _CAMERA_YAML)
    imu_csv = _required_file(root, _IMU_CSV)
    imu_yaml = _required_file(root, _IMU_YAML)
    ground_truth_csv = _required_file(root, _GROUND_TRUTH_CSV)
    ground_truth_yaml = _required_file(root, _GROUND_TRUTH_YAML)

    return EuRoCSequence(
        sequence_id=root.name,
        root=root,
        camera_calibration=_load_camera_calibration(camera_yaml),
        imu_calibration=_load_imu_calibration(imu_yaml),
        ground_truth_calibration=_load_ground_truth_calibration(ground_truth_yaml),
        camera_frames=_load_camera_frames(camera_csv, camera_data),
        imu_measurements=_load_imu(imu_csv),
        ground_truth_states=_load_ground_truth(ground_truth_csv),
    )


def _lerp(first: Sequence[float], second: Sequence[float], fraction: float) -> Vector3:
    return tuple(
        left + fraction * (right - left) for left, right in zip(first, second, strict=True)
    )  # type: ignore[return-value]


def _slerp_shortest_arc(
    first: QuaternionWxyz,
    second: QuaternionWxyz,
    fraction: float,
) -> QuaternionWxyz:
    left = _normalized_quaternion(first)
    right = _normalized_quaternion(second)
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    if dot < 0.0:
        right = tuple(-component for component in right)  # type: ignore[assignment]
        dot = -dot
    dot = min(1.0, max(-1.0, dot))
    if dot > 0.9995:
        blended = tuple(a + fraction * (b - a) for a, b in zip(left, right, strict=True))
        return _normalized_quaternion(blended)  # type: ignore[arg-type]
    angle = math.acos(dot)
    sine = math.sin(angle)
    left_weight = math.sin((1.0 - fraction) * angle) / sine
    right_weight = math.sin(fraction * angle) / sine
    return _normalized_quaternion(
        tuple(left_weight * a + right_weight * b for a, b in zip(left, right, strict=True))  # type: ignore[arg-type]
    )


def interpolate_ground_truth(
    states: Sequence[GroundTruthState], timestamp_ns: int
) -> GroundTruthState:
    """Interpolate native state fields at an integer nanosecond timestamp.

    Position, velocity, and both biases use linear interpolation. Orientation
    uses normalized quaternion SLERP on the shortest arc. Extrapolation is
    rejected.
    """

    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise EuRoCDataError("timestamp_ns must be a non-negative integer")
    state_tuple = tuple(states)
    if not state_tuple:
        raise EuRoCDataError("ground-truth states must not be empty")
    if not all(type(state) is GroundTruthState for state in state_tuple):
        raise EuRoCDataError("states must contain only GroundTruthState records")
    timestamps = tuple(state.timestamp_ns for state in state_tuple)
    if any(
        current <= previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise EuRoCDataError("ground-truth timestamps must be strictly increasing")
    if timestamp_ns < timestamps[0] or timestamp_ns > timestamps[-1]:
        raise EuRoCDataError(
            f"timestamp {timestamp_ns} is outside ground-truth coverage "
            f"[{timestamps[0]}, {timestamps[-1]}]"
        )
    right_index = bisect.bisect_left(timestamps, timestamp_ns)
    if right_index < len(timestamps) and timestamps[right_index] == timestamp_ns:
        state = state_tuple[right_index]
        return GroundTruthState(
            timestamp_ns=timestamp_ns,
            position_rs_r_m=state.position_rs_r_m,
            quaternion_rs_wxyz=_normalized_quaternion(state.quaternion_rs_wxyz),
            velocity_rs_r_m_s=state.velocity_rs_r_m_s,
            gyroscope_bias_rs_s_rad_s=state.gyroscope_bias_rs_s_rad_s,
            accelerometer_bias_rs_s_m_s2=state.accelerometer_bias_rs_s_m_s2,
        )
    left = state_tuple[right_index - 1]
    right = state_tuple[right_index]
    fraction = (timestamp_ns - left.timestamp_ns) / (right.timestamp_ns - left.timestamp_ns)
    return GroundTruthState(
        timestamp_ns=timestamp_ns,
        position_rs_r_m=_lerp(left.position_rs_r_m, right.position_rs_r_m, fraction),
        quaternion_rs_wxyz=_slerp_shortest_arc(
            left.quaternion_rs_wxyz, right.quaternion_rs_wxyz, fraction
        ),
        velocity_rs_r_m_s=_lerp(left.velocity_rs_r_m_s, right.velocity_rs_r_m_s, fraction),
        gyroscope_bias_rs_s_rad_s=_lerp(
            left.gyroscope_bias_rs_s_rad_s,
            right.gyroscope_bias_rs_s_rad_s,
            fraction,
        ),
        accelerometer_bias_rs_s_m_s2=_lerp(
            left.accelerometer_bias_rs_s_m_s2,
            right.accelerometer_bias_rs_s_m_s2,
            fraction,
        ),
    )


def iter_causal_frame_pairs(
    sequence: EuRoCSequence,
    *,
    include_ground_truth: bool = True,
    require_imu: bool = True,
) -> Iterable[CausalFramePair]:
    """Yield consecutive camera pairs with IMU in ``(previous, current]``.

    The function performs no resampling and no timestamp conversion. Ground
    truth, when requested, is interpolated independently at both frame times.
    """

    if type(sequence) is not EuRoCSequence:
        raise EuRoCDataError("sequence must be an EuRoCSequence")
    if type(include_ground_truth) is not bool or type(require_imu) is not bool:
        raise EuRoCDataError("include_ground_truth and require_imu must be boolean")
    imu_timestamps = tuple(item.timestamp_ns for item in sequence.imu_measurements)
    for previous, current in zip(sequence.camera_frames, sequence.camera_frames[1:], strict=False):
        start = bisect.bisect_right(imu_timestamps, previous.timestamp_ns)
        end = bisect.bisect_right(imu_timestamps, current.timestamp_ns)
        window = sequence.imu_measurements[start:end]
        if require_imu and not window:
            raise EuRoCDataError(
                "no IMU measurement in causal interval "
                f"({previous.timestamp_ns}, {current.timestamp_ns}]"
            )
        if include_ground_truth:
            previous_ground_truth = interpolate_ground_truth(
                sequence.ground_truth_states, previous.timestamp_ns
            )
            current_ground_truth = interpolate_ground_truth(
                sequence.ground_truth_states, current.timestamp_ns
            )
        else:
            previous_ground_truth = None
            current_ground_truth = None
        yield CausalFramePair(
            previous_frame=previous,
            current_frame=current,
            imu_measurements=window,
            previous_ground_truth=previous_ground_truth,
            current_ground_truth=current_ground_truth,
        )


def _sequence_ids(values: Iterable[str], *, split: str) -> tuple[str, ...]:
    if isinstance(values, str):
        raise EuRoCDataError(f"{split} split must be an iterable of sequence identifiers")
    result = tuple(values)
    if not result:
        raise EuRoCDataError(f"{split} split must contain at least one sequence")
    for value in result:
        if type(value) is not str or not value.strip():
            raise EuRoCDataError(f"{split} split identifiers must be non-empty strings")
    if len(result) != len(set(result)):
        raise EuRoCDataError(f"{split} split contains a duplicate sequence identifier")
    return result


def validate_sequence_splits(
    *,
    train: Iterable[str],
    validation: Iterable[str],
    test: Iterable[str],
) -> SequenceSplits:
    """Validate and return immutable, sequence-disjoint dataset splits."""

    splits = SequenceSplits(
        train=_sequence_ids(train, split="train"),
        validation=_sequence_ids(validation, split="validation"),
        test=_sequence_ids(test, split="test"),
    )
    owners: dict[str, str] = {}
    for split_name, sequence_ids in (
        ("train", splits.train),
        ("validation", splits.validation),
        ("test", splits.test),
    ):
        for sequence_id in sequence_ids:
            previous_split = owners.get(sequence_id)
            if previous_split is not None:
                raise EuRoCDataError(
                    f"sequence {sequence_id!r} appears in both {previous_split} and {split_name}"
                )
            owners[sequence_id] = split_name
    return splits


def sha256_file(path: os.PathLike[str] | str, *, chunk_bytes: int = 1024 * 1024) -> str:
    """Return the lowercase SHA-256 of one regular, non-symlink source file."""

    if type(chunk_bytes) is not int or chunk_bytes <= 0:
        raise EuRoCDataError("chunk_bytes must be a positive integer")
    source = Path(path)
    try:
        status = source.lstat()
    except OSError as exc:
        raise EuRoCDataError(f"cannot inspect source file {source}: {exc}") from exc
    if source.is_symlink() or not source.is_file():
        raise EuRoCDataError(f"source must be a regular non-symlink file: {source}")
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            while chunk := handle.read(chunk_bytes):
                digest.update(chunk)
    except OSError as exc:
        raise EuRoCDataError(f"cannot hash source file {source}: {exc}") from exc
    if source.stat().st_size != status.st_size or source.stat().st_mtime_ns != status.st_mtime_ns:
        raise EuRoCDataError(f"source file changed while hashing: {source}")
    return digest.hexdigest()


def source_files_sha256(
    root: os.PathLike[str] | str,
    relative_paths: Iterable[os.PathLike[str] | str],
) -> str:
    """Hash an exact ordered source inventory, binding paths and file bytes.

    Paths are canonicalized and sorted, so caller iteration order cannot change
    the result. Duplicate, absolute, traversal, missing, and symlink paths fail.
    """

    source_root = Path(root).resolve(strict=True)
    if not source_root.is_dir():
        raise EuRoCDataError(f"source root is not a directory: {source_root}")
    canonical: list[PurePosixPath] = []
    for supplied in relative_paths:
        text = os.fspath(supplied)
        path = PurePosixPath(text)
        if (
            path.is_absolute()
            or not path.parts
            or any(part in ("", ".", "..") for part in path.parts)
        ):
            raise EuRoCDataError(f"source path must be canonical and root-relative: {text!r}")
        canonical.append(path)
    if not canonical:
        raise EuRoCDataError("relative_paths must not be empty")
    if len(canonical) != len(set(canonical)):
        raise EuRoCDataError("relative_paths must not contain duplicates")

    digest = hashlib.sha256(b"compact-vio-source-inventory-v1\0")
    for relative in sorted(canonical, key=lambda item: item.as_posix()):
        source = source_root.joinpath(*relative.parts)
        try:
            resolved = source.resolve(strict=True)
        except OSError as exc:
            raise EuRoCDataError(f"missing source file: {source}") from exc
        if source.is_symlink() or not resolved.is_file() or source_root not in resolved.parents:
            raise EuRoCDataError(f"source must be a contained regular non-symlink file: {source}")
        encoded_path = relative.as_posix().encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        size = resolved.stat().st_size
        digest.update(size.to_bytes(8, "big"))
        try:
            with resolved.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        except OSError as exc:
            raise EuRoCDataError(f"cannot hash source file {source}: {exc}") from exc
    return digest.hexdigest()


def calibration_sources_sha256(sequence_root: os.PathLike[str] | str) -> str:
    """Hash the exact camera, IMU, and ground-truth calibration source files."""

    return source_files_sha256(
        sequence_root,
        (_CAMERA_YAML, _IMU_YAML, _GROUND_TRUTH_YAML),
    )


def sequence_sources_sha256(sequence_root: os.PathLike[str] | str) -> str:
    """Hash every source byte consumed by the V1 cam0/IMU/GT adapter.

    The inventory includes calibration, sensor CSV files, and every cam0 image.
    It intentionally excludes unused cam1 and ROS-bag data.
    """

    root = Path(sequence_root).resolve(strict=True)
    camera_data = root.joinpath(*_CAMERA_DATA.parts)
    if not camera_data.is_dir() or camera_data.is_symlink():
        raise EuRoCDataError(f"camera data must be a non-symlink directory: {camera_data}")
    try:
        image_names = sorted(item.name for item in camera_data.iterdir())
    except OSError as exc:
        raise EuRoCDataError(f"cannot enumerate camera data {camera_data}: {exc}") from exc
    if not image_names:
        raise EuRoCDataError("camera data directory must not be empty")
    relative_paths: list[PurePosixPath] = [
        _CAMERA_CSV,
        _CAMERA_YAML,
        _IMU_CSV,
        _IMU_YAML,
        _GROUND_TRUTH_CSV,
        _GROUND_TRUTH_YAML,
    ]
    for name in image_names:
        if PurePosixPath(name).name != name:
            raise EuRoCDataError(f"camera data contains a non-canonical basename: {name!r}")
        relative_paths.append(_CAMERA_DATA / name)
    return source_files_sha256(root, relative_paths)


__all__ = [
    "CameraCalibration",
    "CameraFrame",
    "CausalFramePair",
    "EuRoCDataError",
    "EuRoCDependencyError",
    "EuRoCSequence",
    "GroundTruthCalibration",
    "GroundTruthState",
    "ImuCalibration",
    "ImuMeasurement",
    "SequenceSplits",
    "calibration_sources_sha256",
    "interpolate_ground_truth",
    "iter_causal_frame_pairs",
    "load_euroc_sequence",
    "sha256_file",
    "sequence_sources_sha256",
    "source_files_sha256",
    "validate_sequence_splits",
]

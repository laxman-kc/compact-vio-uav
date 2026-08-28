"""Strict position-only adapter for EuRoC Machine Hall Leica references.

The official Machine Hall archives expose Leica measurements as positions,
not full poses.  This module preserves the source field names and transform
direction and deliberately makes no orientation claim.
"""

from __future__ import annotations

import bisect
import csv
import json
import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from compact_vio.data.euroc import (
    EuRoCDataError,
    EuRoCDependencyError,
    ImuCalibration,
    source_files_sha256,
)

_LEICA_CSV = PurePosixPath("mav0/leica0/data.csv")
_LEICA_YAML = PurePosixPath("mav0/leica0/sensor.yaml")
_LEICA_HEADER = (
    "#timestamp [ns]",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
)
_TIMESTAMP_PATTERN = re.compile(r"[0-9]+")

Vector3 = tuple[float, float, float]
Matrix4x4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]


@dataclass(frozen=True, slots=True)
class LeicaCalibration:
    """Native ``leica0/sensor.yaml`` declaration; ``T_BS`` is unchanged."""

    sensor_type: str
    comment: str | None
    t_bs: Matrix4x4
    source_path: Path


@dataclass(frozen=True, slots=True)
class LeicaPosition:
    """One native or linearly interpolated Leica position measurement."""

    timestamp_ns: int
    position_rs_r_m: Vector3


@dataclass(frozen=True, slots=True)
class EuRoCPositionReference:
    """Validated EuRoC Leica position stream from one exact sequence root."""

    sequence_id: str
    root: Path
    calibration: LeicaCalibration
    positions: tuple[LeicaPosition, ...]


def _validated_rigid_transform(value: object, *, field: str) -> Matrix4x4:
    if (
        type(value) is not tuple
        or len(value) != 4
        or any(type(row) is not tuple or len(row) != 4 for row in value)
    ):
        raise EuRoCDataError(f"{field} must be an exact 4x4 tuple")
    if any(
        type(component) not in (int, float) or not math.isfinite(float(component))
        for row in value
        for component in row
    ):
        raise EuRoCDataError(f"{field} must contain finite built-in real values")
    matrix = tuple(tuple(float(component) for component in row) for row in value)
    if matrix[3] != (0.0, 0.0, 0.0, 1.0):
        raise EuRoCDataError(f"{field} bottom row must equal [0, 0, 0, 1]")
    rotation = tuple(tuple(matrix[row][column] for column in range(3)) for row in range(3))
    for row in range(3):
        for other in range(3):
            dot = math.fsum(rotation[row][index] * rotation[other][index] for index in range(3))
            expected = 1.0 if row == other else 0.0
            if not math.isclose(dot, expected, rel_tol=0.0, abs_tol=1e-6):
                raise EuRoCDataError(f"{field} rotation must be orthonormal")
    determinant = (
        rotation[0][0] * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
        - rotation[0][1] * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
        + rotation[0][2] * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
    )
    if not math.isclose(determinant, 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise EuRoCDataError(f"{field} rotation determinant must equal +1")
    return matrix  # type: ignore[return-value]


def leica_origin_in_imu_frame(
    imu_calibration: ImuCalibration,
    leica_calibration: LeicaCalibration,
) -> Vector3:
    """Return the Leica origin expressed in the learned model's IMU frame.

    EuRoC declares both transforms as ``T_BS`` (sensor to body). If ``I`` is
    ``imu0`` and ``L`` is ``leica0``, this computes
    ``R_BI^T * (t_BL - t_BI)`` without changing either source declaration.
    """

    if type(imu_calibration) is not ImuCalibration:
        raise EuRoCDataError("imu_calibration must be an exact ImuCalibration")
    if type(leica_calibration) is not LeicaCalibration:
        raise EuRoCDataError("leica_calibration must be an exact LeicaCalibration")
    imu_t_bs = _validated_rigid_transform(imu_calibration.t_bs, field="imu0 T_BS")
    leica_t_bs = _validated_rigid_transform(leica_calibration.t_bs, field="leica0 T_BS")
    displacement_body = tuple(leica_t_bs[index][3] - imu_t_bs[index][3] for index in range(3))
    offset = tuple(
        math.fsum(imu_t_bs[row][column] * displacement_body[row] for row in range(3))
        for column in range(3)
    )
    if any(not math.isfinite(component) for component in offset):
        raise EuRoCDataError("Leica-to-IMU lever arm is outside the finite runtime domain")
    return offset  # type: ignore[return-value]


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
    transform = _require_mapping(_mapping_field(mapping, "T_BS", path=path), path=path)
    rows = _mapping_field(transform, "rows", path=path)
    cols = _mapping_field(transform, "cols", path=path)
    if type(rows) is not int or type(cols) is not int or rows != 4 or cols != 4:
        raise EuRoCDataError(f"{path}: T_BS rows and cols must both equal 4")
    flat = _float_tuple(transform, "data", length=16, path=path)
    matrix = tuple(tuple(flat[row * 4 : row * 4 + 4]) for row in range(4))
    if matrix[3] != (0.0, 0.0, 0.0, 1.0):
        raise EuRoCDataError(f"{path}: T_BS bottom row must be exactly [0, 0, 0, 1]")

    rotation = tuple(tuple(matrix[row][column] for column in range(3)) for row in range(3))
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


def _load_calibration(path: Path) -> LeicaCalibration:
    document = _load_yaml(path)
    sensor_type = _text_field(document, "sensor_type", path=path)
    if sensor_type != "position":
        raise EuRoCDataError(f"{path}: sensor_type must equal 'position'")
    return LeicaCalibration(
        sensor_type=sensor_type,
        comment=_text_field(document, "comment", path=path, optional=True),
        t_bs=_t_bs(document, path=path),
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
    return tuple(header), rows


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


def _load_positions(path: Path) -> tuple[LeicaPosition, ...]:
    header, rows = _open_csv(path)
    if header != _LEICA_HEADER:
        raise EuRoCDataError(f"{path}: unexpected CSV header; expected {_LEICA_HEADER!r}")
    positions: list[LeicaPosition] = []
    previous: int | None = None
    for line, row in rows:
        if len(row) != len(_LEICA_HEADER):
            raise EuRoCDataError(f"{path}:{line}: Leica row must contain exactly 4 columns")
        timestamp_ns = _timestamp(row[0], path=path, line=line)
        if previous is not None and timestamp_ns <= previous:
            relation = "duplicate" if timestamp_ns == previous else "out-of-order"
            raise EuRoCDataError(
                f"{path}:{line}: timestamps must be strictly increasing ({relation} timestamp)"
            )
        values = tuple(
            _float(row[index], path=path, line=line, column=_LEICA_HEADER[index])
            for index in range(1, 4)
        )
        positions.append(
            LeicaPosition(timestamp_ns=timestamp_ns, position_rs_r_m=values)  # type: ignore[arg-type]
        )
        previous = timestamp_ns
    return tuple(positions)


def _validated_root(sequence_root: os.PathLike[str] | str) -> Path:
    supplied = Path(sequence_root)
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise EuRoCDataError(f"EuRoC sequence root does not exist: {supplied}") from exc
    if not root.is_dir():
        raise EuRoCDataError(f"EuRoC sequence root is not a directory: {root}")
    if not root.name.strip():
        raise EuRoCDataError("EuRoC sequence root must have a non-empty directory name")
    return root


def _required_file(root: Path, relative: PurePosixPath) -> Path:
    source = root.joinpath(*relative.parts)
    try:
        status = source.lstat()
        resolved = source.resolve(strict=True)
    except OSError as exc:
        raise EuRoCDataError(f"missing required EuRoC file: {source}") from exc
    if source.is_symlink() or not source.is_file() or root not in resolved.parents:
        raise EuRoCDataError(f"required EuRoC source must be a contained regular file: {source}")
    if status.st_size != resolved.stat().st_size:
        raise EuRoCDataError(f"EuRoC source changed while inspecting: {source}")
    return resolved


def load_euroc_position_reference(
    sequence_root: os.PathLike[str] | str,
) -> EuRoCPositionReference:
    """Load the exact Leica position reference from one EuRoC sequence root."""

    root = _validated_root(sequence_root)
    csv_path = _required_file(root, _LEICA_CSV)
    yaml_path = _required_file(root, _LEICA_YAML)
    return EuRoCPositionReference(
        sequence_id=root.name,
        root=root,
        calibration=_load_calibration(yaml_path),
        positions=_load_positions(csv_path),
    )


def interpolate_euroc_position(
    reference_or_positions: EuRoCPositionReference | Sequence[LeicaPosition],
    timestamp_ns: int,
    *,
    max_bracket_interval_ns: int | None = None,
) -> LeicaPosition:
    """Linearly interpolate without extrapolation or an over-wide declared bracket."""

    if type(timestamp_ns) is not int or timestamp_ns < 0:
        raise EuRoCDataError("timestamp_ns must be a non-negative integer")
    if max_bracket_interval_ns is not None and (
        type(max_bracket_interval_ns) is not int or max_bracket_interval_ns <= 0
    ):
        raise EuRoCDataError("max_bracket_interval_ns must be None or a positive integer")
    if type(reference_or_positions) is EuRoCPositionReference:
        positions = reference_or_positions.positions
    else:
        positions = tuple(reference_or_positions)
    if not positions:
        raise EuRoCDataError("Leica positions must not be empty")
    if not all(type(position) is LeicaPosition for position in positions):
        raise EuRoCDataError("positions must contain only LeicaPosition records")
    timestamps = tuple(position.timestamp_ns for position in positions)
    if any(type(value) is not int or value < 0 for value in timestamps):
        raise EuRoCDataError("Leica timestamps must be non-negative integers")
    if any(
        current <= previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise EuRoCDataError("Leica timestamps must be strictly increasing")
    if not all(
        len(position.position_rs_r_m) == 3
        and all(_is_real(value) for value in position.position_rs_r_m)
        for position in positions
    ):
        raise EuRoCDataError("Leica positions must contain exactly three finite numeric values")
    if timestamp_ns < timestamps[0] or timestamp_ns > timestamps[-1]:
        raise EuRoCDataError(
            f"timestamp {timestamp_ns} is outside Leica position coverage "
            f"[{timestamps[0]}, {timestamps[-1]}]"
        )

    right_index = bisect.bisect_left(timestamps, timestamp_ns)
    if right_index < len(positions) and timestamps[right_index] == timestamp_ns:
        position = positions[right_index]
        return LeicaPosition(timestamp_ns, position.position_rs_r_m)
    left = positions[right_index - 1]
    right = positions[right_index]
    bracket_interval_ns = right.timestamp_ns - left.timestamp_ns
    if max_bracket_interval_ns is not None and bracket_interval_ns > max_bracket_interval_ns:
        raise EuRoCDataError(
            f"timestamp {timestamp_ns} requires Leica interpolation across "
            f"{bracket_interval_ns} ns, exceeding {max_bracket_interval_ns} ns"
        )
    fraction = (timestamp_ns - left.timestamp_ns) / (right.timestamp_ns - left.timestamp_ns)
    interpolated = tuple(
        first + fraction * (second - first)
        for first, second in zip(left.position_rs_r_m, right.position_rs_r_m, strict=True)
    )
    return LeicaPosition(timestamp_ns, interpolated)  # type: ignore[arg-type]


def position_reference_sources_sha256(sequence_root: os.PathLike[str] | str) -> str:
    """Hash the exact Leica CSV and calibration source bytes with their paths."""

    return source_files_sha256(sequence_root, (_LEICA_CSV, _LEICA_YAML))


__all__ = [
    "EuRoCPositionReference",
    "LeicaCalibration",
    "LeicaPosition",
    "interpolate_euroc_position",
    "leica_origin_in_imu_frame",
    "load_euroc_position_reference",
    "position_reference_sources_sha256",
]

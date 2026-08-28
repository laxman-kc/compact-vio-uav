"""Ground-truth relative-motion targets in the EuRoC sensor convention."""

from __future__ import annotations

import math
from dataclasses import dataclass

from compact_vio.data.euroc import GroundTruthState
from compact_vio.learning.errors import LearningError

Vector3 = tuple[float, float, float]
QuaternionWxyz = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class RelativeMotionTarget:
    """Motion from the previous sensor frame to the current sensor frame.

    Translation is expressed in the previous sensor frame. Rotation is the
    logarithm of ``R_previous^T R_current`` as a three-component rotation vector.
    """

    translation_previous_m: Vector3
    rotation_vector_rad: Vector3


def _normalize(quaternion: QuaternionWxyz) -> QuaternionWxyz:
    norm = math.sqrt(sum(component * component for component in quaternion))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise LearningError("ground-truth quaternion must have non-zero finite norm")
    return tuple(component / norm for component in quaternion)  # type: ignore[return-value]


def _conjugate(quaternion: QuaternionWxyz) -> QuaternionWxyz:
    return (quaternion[0], -quaternion[1], -quaternion[2], -quaternion[3])


def _multiply(left: QuaternionWxyz, right: QuaternionWxyz) -> QuaternionWxyz:
    lw, lx, ly, lz = left
    rw, rx, ry, rz = right
    return (
        lw * rw - lx * rx - ly * ry - lz * rz,
        lw * rx + lx * rw + ly * rz - lz * ry,
        lw * ry - lx * rz + ly * rw + lz * rx,
        lw * rz + lx * ry - ly * rx + lz * rw,
    )


def _rotate(quaternion: QuaternionWxyz, vector: Vector3) -> Vector3:
    rotated = _multiply(
        _multiply(quaternion, (0.0, vector[0], vector[1], vector[2])),
        _conjugate(quaternion),
    )
    return rotated[1], rotated[2], rotated[3]


def _rotation_vector(quaternion: QuaternionWxyz) -> Vector3:
    w, x, y, z = _normalize(quaternion)
    # q and -q encode the same rotation; w >= 0 chooses the shortest log map.
    if w < 0.0:
        w, x, y, z = -w, -x, -y, -z
    vector_norm = math.sqrt(x * x + y * y + z * z)
    if vector_norm <= 1e-10:
        return 2.0 * x, 2.0 * y, 2.0 * z
    angle = 2.0 * math.atan2(vector_norm, max(0.0, w))
    scale = angle / vector_norm
    return scale * x, scale * y, scale * z


def relative_motion_target(
    previous: GroundTruthState,
    current: GroundTruthState,
) -> RelativeMotionTarget:
    """Compute ``R_prev^T(p_current-p_prev)`` and ``log(R_prev^T R_current)``.

    EuRoC's ``q_RS`` rotates a vector from sensor ``S`` into reference frame
    ``R``. Therefore the inverse previous quaternion maps the reference-frame
    position difference back into the previous sensor frame.
    """

    if type(previous) is not GroundTruthState or type(current) is not GroundTruthState:
        raise LearningError("previous and current must be GroundTruthState records")
    if current.timestamp_ns <= previous.timestamp_ns:
        raise LearningError("current ground truth must follow previous ground truth")
    q_previous = _normalize(previous.quaternion_rs_wxyz)
    q_current = _normalize(current.quaternion_rs_wxyz)
    delta_reference = tuple(
        right - left
        for left, right in zip(previous.position_rs_r_m, current.position_rs_r_m, strict=True)
    )
    inverse_previous = _conjugate(q_previous)
    return RelativeMotionTarget(
        translation_previous_m=_rotate(inverse_previous, delta_reference),  # type: ignore[arg-type]
        rotation_vector_rad=_rotation_vector(_multiply(inverse_previous, q_current)),
    )


__all__ = ["RelativeMotionTarget", "relative_motion_target"]

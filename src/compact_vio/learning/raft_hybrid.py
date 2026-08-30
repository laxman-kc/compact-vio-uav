"""Frozen RAFT-small, gyroscope, and range-guarded translation runtime.

The model package intentionally keeps three independently hash-bound assets:
official RAFT-small C_T_V2 weights, a compatible 831-feature translation-head
checkpoint, and the train-only standardized-feature clamp bound to that head.
The runtime consumes raw timestamped images and IMU measurements so the exact
rectification and causal gyro integration are not lost in a generic tensor
adapter.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compact_vio.evaluation.se3 import rotation_vector_to_matrix
from compact_vio.learning.errors import LearningDependencyError, LearningError
from compact_vio.learning.recording_inference import (
    CameraSample,
    ImuSample,
    MotionEstimate,
)

PACKAGE_RECORD_TYPE = "compact_vio_raft_hybrid_package"
PACKAGE_SCHEMA_VERSION = "1.1.0"
EVALUATION_RECORD_TYPE = "compact_vio_raft_hybrid_evaluation_summary"
EVALUATION_SCHEMA_VERSION = "1.0.0"
HEAD_RECORD_TYPE = "development_raft_small_translation_head_result"
CLAMP_RECORD_TYPE = "train_only_standardized_feature_clamp"
RAFT_WEIGHTS_ID = "Raft_Small_Weights.C_T_V2"
RAFT_WEIGHTS_SHA256 = "01064c6dba73b0fc9fc8edf772248560a00a3acfd62ac6677e9eeebad9680e27"
RAFT_UPDATES = 12
EXPERIMENTAL_QUALITY_WARNING = (
    "EXPERIMENTAL MODEL: the packaged candidate failed at least one frozen trajectory-quality "
    "gate; outputs are available for research inspection only."
)
INPUT_HEIGHT = 240
INPUT_WIDTH = 376
GRID_HEIGHT = 10
GRID_WIDTH = 16
FLOW_FEATURE_DIM = 809
IMU_FEATURE_DIM = 22
FEATURE_DIM = FLOW_FEATURE_DIM + IMU_FEATURE_DIM
HEAD_HIDDEN_DIM = 128
HEAD_PARAMETER_COUNT = 123_395
_READ_CHUNK_BYTES = 8 * 1024 * 1024
_SHA256_LENGTH = 64
_REQUIRED_PACKAGE_FILENAMES = {
    "raft_weights": "raft-small-c-t-v2.pth",
    "translation_head": "translation-head.pt",
    "feature_clamp": "feature-clamp.pt",
    "evaluation_summary": "evaluation-summary.json",
}
_PORTABLE_HEAD_FILENAMES = {
    "translation_head_onnx": "translation-head.onnx",
    "translation_head_onnx_manifest": "translation-head.onnx.json",
}

Vector3 = tuple[float, float, float]
Matrix3 = tuple[Vector3, Vector3, Vector3]
Matrix4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]
_IDENTITY_3: Matrix3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


class RaftHybridError(LearningError):
    """Raised when a hybrid package or recording violates its frozen contract."""


@dataclass(frozen=True, slots=True)
class RaftHybridPackage:
    """Validated package paths and integrity identities."""

    manifest_path: Path
    manifest_sha256: str
    raft_weights_path: Path
    raft_weights_sha256: str
    head_checkpoint_path: Path
    head_checkpoint_sha256: str
    clamp_path: Path
    clamp_sha256: str
    evaluation_summary_path: Path
    evaluation_summary_sha256: str
    head_onnx_path: Path
    head_onnx_sha256: str
    head_onnx_manifest_path: Path
    head_onnx_manifest_sha256: str
    manifest: dict[str, object]


@dataclass(frozen=True, slots=True)
class HybridCalibration:
    """Pinhole/radtan camera and body-sensor rotations used by the extractor."""

    camera_t_bs: Matrix4
    imu_t_bs: Matrix4
    resolution_width_px: int
    resolution_height_px: int
    intrinsics: tuple[float, float, float, float]
    distortion_coefficients: tuple[float, float, float, float]


def _sha256_file(path: Path, *, field: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise RaftHybridError(f"{field} must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise RaftHybridError(f"cannot hash {field} {path}: {exc}") from exc
    return digest.hexdigest()


def _digest(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RaftHybridError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _exact_mapping(value: object, keys: set[str], *, field: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise RaftHybridError(f"{field} must contain exactly {sorted(keys)!r}")
    return value


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RaftHybridError(f"package manifest is not canonical JSON data: {exc}") from exc


def _artifact_manifest(filename: str, digest: str, byte_size: int) -> dict[str, object]:
    return {"byte_size": byte_size, "filename": filename, "sha256": digest}


_EVALUATION_SEQUENCE_FIELDS = {
    "all_pass",
    "coverage_ratio",
    "data_identity_sha256",
    "expected_pairs",
    "final_rotation_drift_rad",
    "final_translation_drift_m",
    "normalized_final_translation_drift",
    "pair_rotation_rmse_rad",
    "pair_translation_rmse_m",
    "path_length_ratio",
    "predicted_pairs",
    "predicted_path_length_m",
    "reference_path_length_m",
    "role",
    "sequence_id",
    "translation_ate_m",
    "zero_pair_rotation_rmse_rad",
    "zero_pair_translation_rmse_m",
    "zero_translation_ate_m",
}
_EVALUATION_GATE_FIELDS = {
    "coverage_ratio_min",
    "normalized_final_translation_drift_max",
    "path_length_ratio_max",
    "path_length_ratio_min",
    "require_pair_rotation_rmse_below_zero_motion",
    "require_pair_translation_rmse_below_zero_motion",
    "require_translation_ate_below_zero_motion",
}
_FROZEN_EVALUATION_GATES: dict[str, object] = {
    "coverage_ratio_min": 1.0,
    "normalized_final_translation_drift_max": 0.02,
    "path_length_ratio_max": 1.2,
    "path_length_ratio_min": 0.8,
    "require_pair_rotation_rmse_below_zero_motion": True,
    "require_pair_translation_rmse_below_zero_motion": True,
    "require_translation_ate_below_zero_motion": True,
}


def _finite_nonnegative(value: object, *, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise RaftHybridError(f"{field} must be a finite non-negative number")
    return float(value)


def _close_ratio(observed: float, expected: float) -> bool:
    return math.isclose(observed, expected, rel_tol=1e-9, abs_tol=1e-12)


def _validate_evaluation_document(value: object) -> dict[str, object]:
    root = _exact_mapping(
        value,
        {"candidate_id", "gates", "outcome", "record_type", "schema_version", "sequences"},
        field="evaluation summary",
    )
    if (
        root["record_type"] != EVALUATION_RECORD_TYPE
        or root["schema_version"] != EVALUATION_SCHEMA_VERSION
    ):
        raise RaftHybridError("evaluation summary record type or schema is unsupported")
    candidate_id = root["candidate_id"]
    if (
        type(candidate_id) is not str
        or not candidate_id.startswith("raft-hybrid-sha256:")
        or len(candidate_id) != len("raft-hybrid-sha256:") + _SHA256_LENGTH
        or any(character not in "0123456789abcdef" for character in candidate_id.rsplit(":", 1)[1])
    ):
        raise RaftHybridError("evaluation summary candidate_id must be a bound hybrid digest")
    if root["outcome"] not in {"accepted", "rejected"}:
        raise RaftHybridError("evaluation summary outcome must be accepted or rejected")

    gates = _exact_mapping(root["gates"], _EVALUATION_GATE_FIELDS, field="evaluation gates")
    if gates != _FROZEN_EVALUATION_GATES:
        raise RaftHybridError("evaluation summary gates do not match the frozen definition")
    numeric_gates = {
        name: _finite_nonnegative(gates[name], field=f"evaluation gates.{name}")
        for name in (
            "coverage_ratio_min",
            "normalized_final_translation_drift_max",
            "path_length_ratio_max",
            "path_length_ratio_min",
        )
    }
    if numeric_gates["coverage_ratio_min"] > 1.0:
        raise RaftHybridError("evaluation coverage_ratio_min must not exceed 1")
    if numeric_gates["path_length_ratio_min"] > numeric_gates["path_length_ratio_max"]:
        raise RaftHybridError("evaluation path-length gate bounds are inverted")
    for name in (
        "require_pair_rotation_rmse_below_zero_motion",
        "require_pair_translation_rmse_below_zero_motion",
        "require_translation_ate_below_zero_motion",
    ):
        if type(gates[name]) is not bool:
            raise RaftHybridError(f"evaluation gates.{name} must be boolean")

    sequences = root["sequences"]
    if type(sequences) is not list or not sequences:
        raise RaftHybridError("evaluation summary sequences must be a non-empty array")
    seen: set[str] = set()
    roles: list[str] = []
    all_pass_values: list[bool] = []
    for index, item in enumerate(sequences):
        metrics = _exact_mapping(
            item,
            _EVALUATION_SEQUENCE_FIELDS,
            field=f"evaluation sequences[{index}]",
        )
        sequence_id = metrics["sequence_id"]
        if type(sequence_id) is not str or not sequence_id or sequence_id in seen:
            raise RaftHybridError("evaluation sequence IDs must be unique non-empty strings")
        seen.add(sequence_id)
        role = metrics["role"]
        if role not in {"development_validation", "final_test"}:
            raise RaftHybridError("evaluation sequence role is unsupported")
        roles.append(role)
        _digest(
            metrics["data_identity_sha256"],
            field=f"evaluation sequences[{index}].data_identity_sha256",
        )
        expected_pairs = metrics["expected_pairs"]
        predicted_pairs = metrics["predicted_pairs"]
        if (
            type(expected_pairs) is not int
            or expected_pairs <= 0
            or type(predicted_pairs) is not int
            or not 0 <= predicted_pairs <= expected_pairs
        ):
            raise RaftHybridError("evaluation pair counts are invalid")
        numbers = {
            name: _finite_nonnegative(metrics[name], field=f"evaluation sequences[{index}].{name}")
            for name in _EVALUATION_SEQUENCE_FIELDS
            if name
            not in {
                "all_pass",
                "data_identity_sha256",
                "expected_pairs",
                "predicted_pairs",
                "role",
                "sequence_id",
            }
        }
        if numbers["reference_path_length_m"] <= 0:
            raise RaftHybridError("evaluation reference path length must be positive")
        expected_coverage = predicted_pairs / expected_pairs
        expected_ratio = numbers["predicted_path_length_m"] / numbers["reference_path_length_m"]
        expected_drift = numbers["final_translation_drift_m"] / numbers["reference_path_length_m"]
        if not _close_ratio(numbers["coverage_ratio"], expected_coverage):
            raise RaftHybridError("evaluation coverage ratio is inconsistent with pair counts")
        if not _close_ratio(numbers["path_length_ratio"], expected_ratio):
            raise RaftHybridError("evaluation path ratio is inconsistent with path lengths")
        if not _close_ratio(numbers["normalized_final_translation_drift"], expected_drift):
            raise RaftHybridError("evaluation normalized drift is inconsistent")

        computed_pass = (
            numbers["coverage_ratio"] >= numeric_gates["coverage_ratio_min"]
            and numbers["normalized_final_translation_drift"]
            <= numeric_gates["normalized_final_translation_drift_max"]
            and numeric_gates["path_length_ratio_min"]
            <= numbers["path_length_ratio"]
            <= numeric_gates["path_length_ratio_max"]
            and (
                not gates["require_translation_ate_below_zero_motion"]
                or numbers["translation_ate_m"] < numbers["zero_translation_ate_m"]
            )
            and (
                not gates["require_pair_translation_rmse_below_zero_motion"]
                or numbers["pair_translation_rmse_m"] < numbers["zero_pair_translation_rmse_m"]
            )
            and (
                not gates["require_pair_rotation_rmse_below_zero_motion"]
                or numbers["pair_rotation_rmse_rad"] < numbers["zero_pair_rotation_rmse_rad"]
            )
        )
        if type(metrics["all_pass"]) is not bool or metrics["all_pass"] is not computed_pass:
            raise RaftHybridError("evaluation all_pass is inconsistent with frozen gates")
        all_pass_values.append(computed_pass)
    expected_outcome = "accepted" if all(all_pass_values) else "rejected"
    if root["outcome"] != expected_outcome:
        raise RaftHybridError("evaluation outcome is inconsistent with per-sequence gates")
    if len(sequences) < 2 or roles.count("final_test") != 1:
        raise RaftHybridError(
            "evaluation summary must contain development evidence and exactly one final test"
        )
    return root


def load_raft_hybrid_evaluation_summary(path: Path | str) -> dict[str, object]:
    """Load one canonical, internally consistent evaluation-summary record."""

    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise RaftHybridError(f"evaluation summary must be a regular non-symlink file: {source}")
    try:
        raw = source.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RaftHybridError(f"cannot parse evaluation summary {source}: {exc}") from exc
    document = _validate_evaluation_document(value)
    if raw != _canonical_json_bytes(document):
        raise RaftHybridError("evaluation summary must use canonical JSON encoding")
    return document


def _translation_post_matrix(value: object | None) -> Matrix3:
    if value is None:
        return _IDENTITY_3
    if (
        type(value) in (list, tuple)
        and len(value) == 9
        and all(type(item) in (int, float) for item in value)
    ):
        flat = _real_tuple(value, 9, field="translation post-head matrix")
        rows = tuple(tuple(flat[row * 3 : (row + 1) * 3]) for row in range(3))
    elif type(value) in (list, tuple) and len(value) == 3:
        rows = tuple(
            _real_tuple(row, 3, field=f"translation post-head matrix[{index}]")
            for index, row in enumerate(value)
        )
    else:
        raise RaftHybridError("translation post-head matrix must contain exactly 3x3 values")
    if max(abs(item) for row in rows for item in row) > 10.0:
        raise RaftHybridError("translation post-head matrix coefficients must be bounded by 10")
    return rows  # type: ignore[return-value]


def raft_hybrid_candidate_id(
    *,
    raft_weights_sha256: str,
    head_checkpoint_sha256: str,
    clamp_sha256: str,
    translation_post_matrix: object | None = None,
) -> str:
    """Return the deterministic identity bound by final evaluation evidence."""

    identity = {
        "clamp_sha256": _digest(clamp_sha256, field="candidate clamp SHA-256"),
        "head_checkpoint_sha256": _digest(head_checkpoint_sha256, field="candidate head SHA-256"),
        "raft_weights_sha256": _digest(raft_weights_sha256, field="candidate RAFT weights SHA-256"),
        "translation_post_matrix": [
            list(row) for row in _translation_post_matrix(translation_post_matrix)
        ],
    }
    digest = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
    return f"raft-hybrid-sha256:{digest}"


def _load_torch_payload(path: Path, *, field: str) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "RAFT hybrid artifacts require PyTorch; install the runtime extra"
        ) from exc
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise RaftHybridError(f"cannot load {field} {path}: {exc}") from exc
    if type(payload) is not dict:
        raise RaftHybridError(f"{field} payload must be an object")
    return payload


def _sha256_float_tensor(value: object, *, field: str) -> str:
    try:
        import torch
        from torch import Tensor
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("tensor verification requires PyTorch") from exc
    if not isinstance(value, Tensor):
        raise RaftHybridError(f"{field} must be a torch tensor")
    contiguous = value.detach().cpu().to(torch.float32).contiguous()
    return hashlib.sha256(contiguous.numpy().tobytes(order="C")).hexdigest()


def _sha256_bool_tensor(value: object, *, field: str) -> str:
    try:
        import torch
        from torch import Tensor
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("tensor verification requires PyTorch") from exc
    if not isinstance(value, Tensor) or value.dtype != torch.bool:
        raise RaftHybridError(f"{field} must be a boolean torch tensor")
    return hashlib.sha256(value.detach().cpu().contiguous().numpy().tobytes(order="C")).hexdigest()


def _validate_head_payload(payload: dict[str, Any]) -> None:
    try:
        import torch
        from torch import Tensor
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("head validation requires PyTorch") from exc
    expected = {
        "model_state_dict",
        "feature_mean",
        "feature_std",
        "target_mean",
        "target_std",
        "architecture",
        "selected",
    }
    _exact_mapping(payload, expected, field="translation head")
    architecture = _exact_mapping(
        payload["architecture"],
        {"type", "feature_dim", "hidden_dim", "layers", "activation"},
        field="translation-head architecture",
    )
    if architecture != {
        "type": "MLP",
        "feature_dim": FEATURE_DIM,
        "hidden_dim": HEAD_HIDDEN_DIM,
        "layers": [FEATURE_DIM, HEAD_HIDDEN_DIM, HEAD_HIDDEN_DIM, 3],
        "activation": "GELU",
    }:
        raise RaftHybridError("translation-head architecture is incompatible")
    state = payload["model_state_dict"]
    expected_shapes = {
        "network.0.weight": (HEAD_HIDDEN_DIM, FEATURE_DIM),
        "network.0.bias": (HEAD_HIDDEN_DIM,),
        "network.2.weight": (HEAD_HIDDEN_DIM, HEAD_HIDDEN_DIM),
        "network.2.bias": (HEAD_HIDDEN_DIM,),
        "network.4.weight": (3, HEAD_HIDDEN_DIM),
        "network.4.bias": (3,),
    }
    if not isinstance(state, Mapping) or set(state) != set(expected_shapes):
        raise RaftHybridError("translation-head state_dict keys are incompatible")
    for name, shape in expected_shapes.items():
        tensor = state[name]
        if not isinstance(tensor, Tensor) or tuple(tensor.shape) != shape:
            raise RaftHybridError(f"translation-head tensor {name!r} has an incompatible shape")
        if not tensor.is_floating_point() or not bool(torch.isfinite(tensor).all()):
            raise RaftHybridError(f"translation-head tensor {name!r} must be finite floating point")
    for name, shape in {
        "feature_mean": (FEATURE_DIM,),
        "feature_std": (FEATURE_DIM,),
        "target_mean": (3,),
        "target_std": (3,),
    }.items():
        tensor = payload[name]
        if not isinstance(tensor, Tensor) or tuple(tensor.shape) != shape:
            raise RaftHybridError(f"translation-head {name} has an incompatible shape")
        if not tensor.is_floating_point() or not bool(torch.isfinite(tensor).all()):
            raise RaftHybridError(f"translation-head {name} must be finite floating point")
    if bool((payload["feature_std"] <= 0).any()) or bool((payload["target_std"] <= 0).any()):
        raise RaftHybridError("translation-head normalization scales must be positive")
    if type(payload["selected"]) is not dict:
        raise RaftHybridError("translation-head selected metadata must be an object")


def _validate_clamp_payload(payload: dict[str, Any], *, head_sha256: str) -> None:
    try:
        import torch
        from torch import Tensor
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("clamp validation requires PyTorch") from exc
    expected = {
        "record_type",
        "schema_version",
        "train_sequence_ids",
        "source_cache_path",
        "source_cache_sha256",
        "head_checkpoint_path",
        "head_checkpoint_sha256",
        "feature_dim",
        "rule",
        "clamp_min",
        "clamp_max",
        "constant_feature_mask",
        "clamp_min_tensor_sha256",
        "clamp_max_tensor_sha256",
        "constant_mask_tensor_sha256",
        "constant_feature_count",
    }
    _exact_mapping(payload, expected, field="feature clamp")
    if payload["record_type"] != CLAMP_RECORD_TYPE or payload["schema_version"] != 1:
        raise RaftHybridError("feature clamp record type or schema is unsupported")
    if payload["feature_dim"] != FEATURE_DIM:
        raise RaftHybridError("feature clamp dimension is incompatible")
    if payload["head_checkpoint_sha256"] != head_sha256:
        raise RaftHybridError("feature clamp does not bind the packaged translation head")
    if payload["rule"] != (
        "per-feature exact train standardized min/max; exact raw train constants forced to [0,0]"
    ):
        raise RaftHybridError("feature clamp rule is unsupported")
    train_ids = payload["train_sequence_ids"]
    if (
        type(train_ids) is not list
        or not train_ids
        or any(type(item) is not str or not item for item in train_ids)
        or len(train_ids) != len(set(train_ids))
    ):
        raise RaftHybridError("feature clamp train_sequence_ids are invalid")
    _digest(payload["source_cache_sha256"], field="feature clamp source cache SHA-256")
    minimum = payload["clamp_min"]
    maximum = payload["clamp_max"]
    mask = payload["constant_feature_mask"]
    if not all(
        isinstance(item, Tensor) and tuple(item.shape) == (FEATURE_DIM,)
        for item in (minimum, maximum, mask)
    ):
        raise RaftHybridError("feature clamp tensors must have shape [831]")
    if (
        not minimum.is_floating_point()
        or not maximum.is_floating_point()
        or mask.dtype != torch.bool
    ):
        raise RaftHybridError("feature clamp tensor dtypes are incompatible")
    if not bool(torch.isfinite(minimum).all()) or not bool(torch.isfinite(maximum).all()):
        raise RaftHybridError("feature clamp bounds must be finite")
    if bool((minimum > maximum).any()):
        raise RaftHybridError("feature clamp minimum exceeds maximum")
    if bool((minimum[mask] != 0).any()) or bool((maximum[mask] != 0).any()):
        raise RaftHybridError("constant feature clamp bounds must be exact zero")
    if payload["constant_feature_count"] != int(mask.sum()):
        raise RaftHybridError("feature clamp constant count is inconsistent")
    checks = (
        (
            _sha256_float_tensor(minimum, field="clamp_min"),
            payload["clamp_min_tensor_sha256"],
            "clamp_min",
        ),
        (
            _sha256_float_tensor(maximum, field="clamp_max"),
            payload["clamp_max_tensor_sha256"],
            "clamp_max",
        ),
        (
            _sha256_bool_tensor(mask, field="constant_feature_mask"),
            payload["constant_mask_tensor_sha256"],
            "constant_feature_mask",
        ),
    )
    for observed, expected_digest, field in checks:
        if observed != _digest(expected_digest, field=f"{field} SHA-256"):
            raise RaftHybridError(f"{field} tensor SHA-256 mismatch")


def _manifest_document(
    *,
    raft_path: Path,
    raft_sha256: str,
    head_path: Path,
    head_sha256: str,
    clamp_path: Path,
    clamp_sha256: str,
    evaluation_path: Path,
    evaluation_sha256: str,
    head_onnx_path: Path | None,
    head_onnx_sha256: str | None,
    head_onnx_manifest_path: Path | None,
    head_onnx_manifest_sha256: str | None,
    head_payload: dict[str, Any],
    clamp_payload: dict[str, Any],
    evaluation_payload: dict[str, object],
    translation_post_matrix: Matrix3,
) -> dict[str, object]:
    artifacts = {
        "raft_weights": _artifact_manifest(raft_path.name, raft_sha256, raft_path.stat().st_size),
        "translation_head": _artifact_manifest(
            head_path.name, head_sha256, head_path.stat().st_size
        ),
        "feature_clamp": _artifact_manifest(
            clamp_path.name, clamp_sha256, clamp_path.stat().st_size
        ),
        "evaluation_summary": _artifact_manifest(
            evaluation_path.name, evaluation_sha256, evaluation_path.stat().st_size
        ),
    }
    if (
        head_onnx_path is not None
        and head_onnx_sha256 is not None
        and head_onnx_manifest_path is not None
        and head_onnx_manifest_sha256 is not None
    ):
        artifacts.update(
            {
                "translation_head_onnx": _artifact_manifest(
                    head_onnx_path.name,
                    head_onnx_sha256,
                    head_onnx_path.stat().st_size,
                ),
                "translation_head_onnx_manifest": _artifact_manifest(
                    head_onnx_manifest_path.name,
                    head_onnx_manifest_sha256,
                    head_onnx_manifest_path.stat().st_size,
                ),
            }
        )
    quality_status = (
        "accepted" if evaluation_payload["outcome"] == "accepted" else "experimental_rejected"
    )
    return {
        "record_type": PACKAGE_RECORD_TYPE,
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "quality_status": quality_status,
        "artifacts": artifacts,
        "architecture": {
            "feature_dim": FEATURE_DIM,
            "flow_feature_dim": FLOW_FEATURE_DIM,
            "head": head_payload["architecture"],
            "head_parameter_count": HEAD_PARAMETER_COUNT,
            "imu_feature_dim": IMU_FEATURE_DIM,
            "raft_updates": RAFT_UPDATES,
            "raft_weights_id": RAFT_WEIGHTS_ID,
            "translation_post_matrix": [list(row) for row in translation_post_matrix],
        },
        "preprocessing": {
            "endpoint_derotation": "K * R_Cprev_Ccur * K^-1 * (u + flow) - u",
            "feature_clamp_rule": clamp_payload["rule"],
            "grid_height": GRID_HEIGHT,
            "grid_width": GRID_WIDTH,
            "image": "grayscale-repeat-rgb-resize-radtan-rectify",
            "input_height": INPUT_HEIGHT,
            "input_width": INPUT_WIDTH,
            "rectification": "grid_sample-bilinear-zeros-align_corners_true",
        },
        "evaluation": {
            "candidate_id": evaluation_payload["candidate_id"],
            "gates": evaluation_payload["gates"],
            "outcome": evaluation_payload["outcome"],
            "sequences": evaluation_payload["sequences"],
        },
        "runtime": {
            "calibration_contract": "combined-pinhole-radtan/body-equals-imu-sensor/v2",
            "gyro_bias": "mean-native-samples-strictly-before-first-camera-frame/min-2/v1",
            "gyro_integration": "causal-trapezoid-latest-at-or-before-start-held-tail/v1",
            "motion_layout": (
                "translation-previous-imu-sensor-m/rotation-vector-previous-imu-sensor-rad/v2"
            ),
            "translation_postprocess": "matrix-3x3-no-bias-before-se3-integration/v1",
        },
        "selection": head_payload["selected"],
        "training": {
            "clamp_source_cache_sha256": clamp_payload["source_cache_sha256"],
            "train_sequence_ids": clamp_payload["train_sequence_ids"],
        },
    }


def build_raft_hybrid_package(
    destination: Path | str,
    *,
    raft_weights_path: Path | str,
    head_checkpoint_path: Path | str,
    clamp_path: Path | str,
    evaluation_summary_path: Path | str,
    head_onnx_path: Path | str,
    head_onnx_manifest_path: Path | str,
    translation_post_matrix: object | None = None,
) -> RaftHybridPackage:
    """Create a new self-contained directory from compatible frozen assets."""

    target = Path(destination)
    if target.is_symlink() or target.exists():
        raise RaftHybridError(f"refusing to overwrite model package: {target}")
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir():
        raise RaftHybridError(f"model package parent must be a regular directory: {parent}")
    sources = {
        "raft_weights": Path(raft_weights_path),
        "translation_head": Path(head_checkpoint_path),
        "feature_clamp": Path(clamp_path),
        "evaluation_summary": Path(evaluation_summary_path),
    }
    sources["translation_head_onnx"] = Path(head_onnx_path)
    sources["translation_head_onnx_manifest"] = Path(head_onnx_manifest_path)
    source_hashes = {
        name: _sha256_file(path, field=name.replace("_", " ")) for name, path in sources.items()
    }
    if source_hashes["raft_weights"] != RAFT_WEIGHTS_SHA256:
        raise RaftHybridError("RAFT weights are not the official C_T_V2 artifact")
    head_payload = _load_torch_payload(sources["translation_head"], field="translation head")
    _validate_head_payload(head_payload)
    clamp_payload = _load_torch_payload(sources["feature_clamp"], field="feature clamp")
    _validate_clamp_payload(
        clamp_payload,
        head_sha256=source_hashes["translation_head"],
    )
    evaluation_payload = load_raft_hybrid_evaluation_summary(sources["evaluation_summary"])
    post_matrix = _translation_post_matrix(translation_post_matrix)
    expected_candidate_id = raft_hybrid_candidate_id(
        raft_weights_sha256=source_hashes["raft_weights"],
        head_checkpoint_sha256=source_hashes["translation_head"],
        clamp_sha256=source_hashes["feature_clamp"],
        translation_post_matrix=post_matrix,
    )
    if evaluation_payload["candidate_id"] != expected_candidate_id:
        raise RaftHybridError("evaluation summary does not bind the packaged candidate")
    if Path(head_onnx_path).name != _PORTABLE_HEAD_FILENAMES["translation_head_onnx"]:
        raise RaftHybridError(
            f"portable ONNX must be named {_PORTABLE_HEAD_FILENAMES['translation_head_onnx']!r}"
        )
    from compact_vio.learning.raft_head_onnx import verify_raft_head_onnx_manifest

    portable_manifest = verify_raft_head_onnx_manifest(
        head_onnx_manifest_path,
        model_path=head_onnx_path,
        head_checkpoint_path=head_checkpoint_path,
        clamp_artifact_path=clamp_path,
        require_passed_parity=True,
        rerun_parity=True,
    )
    portable_export = portable_manifest["export"]
    assert isinstance(portable_export, dict)
    if _translation_post_matrix(portable_export["translation_post_matrix"]) != post_matrix:
        raise RaftHybridError(
            "portable ONNX translation_post_matrix does not match the model package"
        )

    created = False
    try:
        target.mkdir()
        created = True
        copied: dict[str, Path] = {}
        for name, source in sources.items():
            filenames = {**_REQUIRED_PACKAGE_FILENAMES, **_PORTABLE_HEAD_FILENAMES}
            output = target / filenames[name]
            try:
                with source.open("rb") as input_handle, output.open("xb") as output_handle:
                    shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            except OSError as exc:
                raise RaftHybridError(f"cannot copy {name} into model package: {exc}") from exc
            copied[name] = output
            if _sha256_file(output, field=f"packaged {name}") != source_hashes[name]:
                raise RaftHybridError(f"packaged {name} changed while it was copied")
        manifest = _manifest_document(
            raft_path=copied["raft_weights"],
            raft_sha256=source_hashes["raft_weights"],
            head_path=copied["translation_head"],
            head_sha256=source_hashes["translation_head"],
            clamp_path=copied["feature_clamp"],
            clamp_sha256=source_hashes["feature_clamp"],
            evaluation_path=copied["evaluation_summary"],
            evaluation_sha256=source_hashes["evaluation_summary"],
            head_onnx_path=copied.get("translation_head_onnx"),
            head_onnx_sha256=source_hashes.get("translation_head_onnx"),
            head_onnx_manifest_path=copied.get("translation_head_onnx_manifest"),
            head_onnx_manifest_sha256=source_hashes.get("translation_head_onnx_manifest"),
            head_payload=head_payload,
            clamp_payload=clamp_payload,
            evaluation_payload=evaluation_payload,
            translation_post_matrix=post_matrix,
        )
        manifest_path = target / "manifest.json"
        try:
            with manifest_path.open("xb") as handle:
                handle.write(_canonical_json_bytes(manifest))
        except OSError as exc:
            raise RaftHybridError(f"cannot write model package manifest: {exc}") from exc
        return load_raft_hybrid_package(manifest_path)
    except Exception:
        if created:
            for child in target.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink(missing_ok=True)
            target.rmdir()
        raise


def load_raft_hybrid_package(
    manifest_path: Path | str,
    *,
    expected_manifest_sha256: str | None = None,
) -> RaftHybridPackage:
    """Validate a package manifest plus every bound sibling asset."""

    source = Path(manifest_path)
    observed_manifest_sha = _sha256_file(source, field="model package manifest")
    if expected_manifest_sha256 is not None and observed_manifest_sha != _digest(
        expected_manifest_sha256, field="expected_manifest_sha256"
    ):
        raise RaftHybridError(
            "model package manifest SHA-256 mismatch: expected "
            f"{expected_manifest_sha256}, got {observed_manifest_sha}"
        )
    try:
        raw_manifest = source.read_bytes()
        document = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RaftHybridError(f"cannot parse model package manifest {source}: {exc}") from exc
    root = _exact_mapping(
        document,
        {
            "record_type",
            "schema_version",
            "artifacts",
            "architecture",
            "evaluation",
            "preprocessing",
            "quality_status",
            "runtime",
            "selection",
            "training",
        },
        field="model package manifest",
    )
    if raw_manifest != _canonical_json_bytes(root):
        raise RaftHybridError("model package manifest must use canonical JSON encoding")
    if (
        root["record_type"] != PACKAGE_RECORD_TYPE
        or root["schema_version"] != PACKAGE_SCHEMA_VERSION
    ):
        raise RaftHybridError("model package record type or schema is unsupported")
    architecture = _exact_mapping(
        root["architecture"],
        {
            "feature_dim",
            "flow_feature_dim",
            "head",
            "head_parameter_count",
            "imu_feature_dim",
            "raft_updates",
            "raft_weights_id",
            "translation_post_matrix",
        },
        field="model package architecture",
    )
    post_matrix = _translation_post_matrix(architecture["translation_post_matrix"])
    if type(root["artifacts"]) is not dict:
        raise RaftHybridError("model package artifacts must be an object")
    artifact_fields = set(root["artifacts"])
    required_fields = set(_REQUIRED_PACKAGE_FILENAMES) | set(_PORTABLE_HEAD_FILENAMES)
    if artifact_fields != required_fields:
        raise RaftHybridError("model package artifacts are incomplete or unsupported")
    artifacts = root["artifacts"]
    filenames = {**_REQUIRED_PACKAGE_FILENAMES, **_PORTABLE_HEAD_FILENAMES}
    resolved: dict[str, Path] = {}
    hashes: dict[str, str] = {}
    package_root = source.parent.resolve()
    for name, expected_filename in filenames.items():
        record = _exact_mapping(
            artifacts[name], {"byte_size", "filename", "sha256"}, field=f"{name} artifact"
        )
        if record["filename"] != expected_filename:
            raise RaftHybridError(f"{name} artifact filename is not canonical")
        if type(record["byte_size"]) is not int or record["byte_size"] <= 0:
            raise RaftHybridError(f"{name} artifact byte_size must be positive")
        candidate = source.parent / expected_filename
        if candidate.is_symlink():
            raise RaftHybridError(f"packaged {name} must not be a symbolic link")
        path = candidate.resolve()
        if not path.is_relative_to(package_root):
            raise RaftHybridError(f"{name} artifact escapes the model package")
        digest = _sha256_file(path, field=f"packaged {name}")
        if path.stat().st_size != record["byte_size"] or digest != _digest(
            record["sha256"], field=f"{name} SHA-256"
        ):
            raise RaftHybridError(f"packaged {name} size or SHA-256 mismatch")
        resolved[name] = path
        hashes[name] = digest
    if hashes["raft_weights"] != RAFT_WEIGHTS_SHA256:
        raise RaftHybridError("packaged RAFT weights are not official C_T_V2 weights")
    head_payload = _load_torch_payload(resolved["translation_head"], field="translation head")
    _validate_head_payload(head_payload)
    clamp_payload = _load_torch_payload(resolved["feature_clamp"], field="feature clamp")
    _validate_clamp_payload(clamp_payload, head_sha256=hashes["translation_head"])
    evaluation_payload = load_raft_hybrid_evaluation_summary(resolved["evaluation_summary"])
    expected_quality_status = (
        "accepted" if evaluation_payload["outcome"] == "accepted" else "experimental_rejected"
    )
    if root["quality_status"] != expected_quality_status:
        raise RaftHybridError("model package quality_status is inconsistent with evaluation")
    expected_candidate_id = raft_hybrid_candidate_id(
        raft_weights_sha256=hashes["raft_weights"],
        head_checkpoint_sha256=hashes["translation_head"],
        clamp_sha256=hashes["feature_clamp"],
        translation_post_matrix=post_matrix,
    )
    if evaluation_payload["candidate_id"] != expected_candidate_id:
        raise RaftHybridError("evaluation summary does not bind the packaged candidate")
    expected_evaluation = {
        "candidate_id": evaluation_payload["candidate_id"],
        "gates": evaluation_payload["gates"],
        "outcome": evaluation_payload["outcome"],
        "sequences": evaluation_payload["sequences"],
    }
    if root["evaluation"] != expected_evaluation:
        raise RaftHybridError("model package evaluation core does not match its summary")
    from compact_vio.learning.raft_head_onnx import verify_raft_head_onnx_manifest

    portable_manifest = verify_raft_head_onnx_manifest(
        resolved["translation_head_onnx_manifest"],
        model_path=resolved["translation_head_onnx"],
        head_checkpoint_path=resolved["translation_head"],
        clamp_artifact_path=resolved["feature_clamp"],
        require_passed_parity=True,
    )
    portable_export = portable_manifest["export"]
    assert isinstance(portable_export, dict)
    if _translation_post_matrix(portable_export["translation_post_matrix"]) != post_matrix:
        raise RaftHybridError(
            "portable ONNX translation_post_matrix does not match the model package"
        )
    expected_manifest = _manifest_document(
        raft_path=resolved["raft_weights"],
        raft_sha256=hashes["raft_weights"],
        head_path=resolved["translation_head"],
        head_sha256=hashes["translation_head"],
        clamp_path=resolved["feature_clamp"],
        clamp_sha256=hashes["feature_clamp"],
        evaluation_path=resolved["evaluation_summary"],
        evaluation_sha256=hashes["evaluation_summary"],
        head_onnx_path=resolved["translation_head_onnx"],
        head_onnx_sha256=hashes["translation_head_onnx"],
        head_onnx_manifest_path=resolved["translation_head_onnx_manifest"],
        head_onnx_manifest_sha256=hashes["translation_head_onnx_manifest"],
        head_payload=head_payload,
        clamp_payload=clamp_payload,
        evaluation_payload=evaluation_payload,
        translation_post_matrix=post_matrix,
    )
    if root != expected_manifest:
        raise RaftHybridError("model package manifest does not match the packaged artifacts")
    return RaftHybridPackage(
        manifest_path=source.resolve(),
        manifest_sha256=observed_manifest_sha,
        raft_weights_path=resolved["raft_weights"],
        raft_weights_sha256=hashes["raft_weights"],
        head_checkpoint_path=resolved["translation_head"],
        head_checkpoint_sha256=hashes["translation_head"],
        clamp_path=resolved["feature_clamp"],
        clamp_sha256=hashes["feature_clamp"],
        evaluation_summary_path=resolved["evaluation_summary"],
        evaluation_summary_sha256=hashes["evaluation_summary"],
        head_onnx_path=resolved["translation_head_onnx"],
        head_onnx_sha256=hashes["translation_head_onnx"],
        head_onnx_manifest_path=resolved["translation_head_onnx_manifest"],
        head_onnx_manifest_sha256=hashes["translation_head_onnx_manifest"],
        manifest=root,
    )


def _real_tuple(value: object, length: int, *, field: str) -> tuple[float, ...]:
    if (
        type(value) not in (list, tuple)
        or len(value) != length
        or any(type(item) not in (int, float) or not math.isfinite(float(item)) for item in value)
    ):
        raise RaftHybridError(f"{field} must contain {length} finite real values")
    return tuple(float(item) for item in value)


def _matrix4(value: object, *, field: str) -> Matrix4:
    if type(value) is dict:
        mapping = _exact_mapping(value, {"rows", "cols", "data"}, field=field)
        if mapping["rows"] != 4 or mapping["cols"] != 4:
            raise RaftHybridError(f"{field} must declare a 4x4 matrix")
        flat = _real_tuple(mapping["data"], 16, field=f"{field}.data")
        rows = tuple(tuple(flat[row * 4 : (row + 1) * 4]) for row in range(4))
    elif type(value) in (list, tuple) and len(value) == 4:
        rows = tuple(
            _real_tuple(row, 4, field=f"{field}[{index}]") for index, row in enumerate(value)
        )
    else:
        raise RaftHybridError(f"{field} must be a 4x4 nested matrix or EuRoC matrix mapping")
    if any(abs(rows[3][column] - expected) > 1e-9 for column, expected in enumerate((0, 0, 0, 1))):
        raise RaftHybridError(f"{field} must be a homogeneous rigid transform")
    rotation = tuple(tuple(rows[row][column] for column in range(3)) for row in range(3))
    for row in range(3):
        for column in range(3):
            dot = math.fsum(rotation[index][row] * rotation[index][column] for index in range(3))
            expected = 1.0 if row == column else 0.0
            if abs(dot - expected) > 1e-5:
                raise RaftHybridError(f"{field} rotation must be orthonormal")
    return rows  # type: ignore[return-value]


def parse_hybrid_calibration(value: Mapping[str, object]) -> HybridCalibration:
    """Parse the combined camera/IMU calibration accepted by the upload runner."""

    root = _exact_mapping(value, {"camera", "imu"}, field="hybrid calibration")
    camera = _exact_mapping(
        root["camera"],
        {
            "T_BS",
            "camera_model",
            "distortion_coefficients",
            "distortion_model",
            "intrinsics",
            "resolution",
        },
        field="camera calibration",
    )
    imu = _exact_mapping(root["imu"], {"T_BS"}, field="IMU calibration")
    if camera["camera_model"] != "pinhole" or camera["distortion_model"] != "radtan":
        raise RaftHybridError("hybrid runtime requires pinhole camera and radtan distortion")
    resolution = camera["resolution"]
    if (
        type(resolution) not in (list, tuple)
        or len(resolution) != 2
        or any(type(item) is not int or item <= 1 for item in resolution)
    ):
        raise RaftHybridError("camera resolution must be [width, height] positive integers")
    intrinsics = _real_tuple(camera["intrinsics"], 4, field="camera intrinsics")
    if intrinsics[0] <= 0 or intrinsics[1] <= 0:
        raise RaftHybridError("camera focal lengths must be positive")
    camera_t_bs = _matrix4(camera["T_BS"], field="camera.T_BS")
    imu_t_bs = _matrix4(imu["T_BS"], field="imu.T_BS")
    if any(
        abs(imu_t_bs[row][column] - (1.0 if row == column else 0.0)) > 1e-9
        for row in range(4)
        for column in range(4)
    ):
        raise RaftHybridError(
            "imu.T_BS must be identity: the hybrid output frame is the native IMU sensor frame"
        )
    return HybridCalibration(
        camera_t_bs=camera_t_bs,
        imu_t_bs=imu_t_bs,
        resolution_width_px=resolution[0],
        resolution_height_px=resolution[1],
        intrinsics=intrinsics,  # type: ignore[arg-type]
        distortion_coefficients=_real_tuple(
            camera["distortion_coefficients"], 4, field="camera distortion coefficients"
        ),  # type: ignore[arg-type]
    )


def euroc_calibration_document(sequence: object) -> dict[str, object]:
    """Create runtime calibration with the EuRoC body normalized to the IMU."""

    camera = getattr(sequence, "camera_calibration", None)
    imu = getattr(sequence, "imu_calibration", None)
    if camera is None or imu is None:
        raise RaftHybridError("sequence does not expose EuRoC camera and IMU calibration")
    camera_t_body = _matrix4(camera.t_bs, field="EuRoC camera T_BS")
    imu_t_body = _matrix4(imu.t_bs, field="EuRoC IMU T_BS")
    imu_rotation = tuple(tuple(imu_t_body[row][column] for column in range(3)) for row in range(3))
    imu_rotation_t = tuple(
        tuple(imu_rotation[column][row] for column in range(3)) for row in range(3)
    )
    imu_translation = tuple(imu_t_body[row][3] for row in range(3))
    camera_rotation = tuple(
        tuple(camera_t_body[row][column] for column in range(3)) for row in range(3)
    )
    camera_translation = tuple(camera_t_body[row][3] for row in range(3))
    normalized_rotation = _mm(imu_rotation_t, camera_rotation)  # type: ignore[arg-type]
    normalized_translation = tuple(
        math.fsum(
            imu_rotation_t[row][index] * (camera_translation[index] - imu_translation[index])
            for index in range(3)
        )
        for row in range(3)
    )
    normalized_camera_t_bs = [
        [*normalized_rotation[row], normalized_translation[row]] for row in range(3)
    ] + [[0.0, 0.0, 0.0, 1.0]]
    return {
        "camera": {
            "T_BS": normalized_camera_t_bs,
            "camera_model": camera.camera_model,
            "distortion_coefficients": list(camera.distortion_coefficients),
            "distortion_model": camera.distortion_model,
            "intrinsics": list(camera.intrinsics),
            "resolution": [camera.resolution_width_px, camera.resolution_height_px],
        },
        "imu": {
            "T_BS": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        },
    }


def _mm(left: Matrix3, right: Matrix3) -> Matrix3:
    return tuple(
        tuple(
            math.fsum(left[row][index] * right[index][column] for index in range(3))
            for column in range(3)
        )
        for row in range(3)
    )  # type: ignore[return-value]


def _transpose(matrix: Matrix3) -> Matrix3:
    return tuple(tuple(matrix[column][row] for column in range(3)) for row in range(3))  # type: ignore[return-value]


def _matrix_to_rotation_vector(matrix: Matrix3) -> Vector3:
    cosine = min(1.0, max(-1.0, (matrix[0][0] + matrix[1][1] + matrix[2][2] - 1.0) / 2.0))
    angle = math.acos(cosine)
    anti = (
        matrix[2][1] - matrix[1][2],
        matrix[0][2] - matrix[2][0],
        matrix[1][0] - matrix[0][1],
    )
    if angle < 1e-8:
        return tuple(0.5 * value for value in anti)  # type: ignore[return-value]
    sine = math.sin(angle)
    if abs(sine) < 1e-10:
        raise RaftHybridError("gyro integration produced an ambiguous pi rotation")
    scale = angle / (2.0 * sine)
    return tuple(scale * value for value in anti)  # type: ignore[return-value]


def _causal_prefix_bias(imu_samples: Sequence[ImuSample], first_frame_timestamp_ns: int) -> Vector3:
    prefix = tuple(
        sample for sample in imu_samples if sample.timestamp_ns < first_frame_timestamp_ns
    )
    if len(prefix) < 2:
        raise RaftHybridError(
            "hybrid runtime requires at least two causal IMU samples before the first camera frame"
        )
    return tuple(
        math.fsum(sample.angular_velocity_rad_s[axis] for sample in prefix) / len(prefix)
        for axis in range(3)
    )  # type: ignore[return-value]


def _integrate_gyro(
    *,
    start_ns: int,
    end_ns: int,
    imu_samples: Sequence[ImuSample],
    imu_timestamps: Sequence[int],
    bias: Vector3,
) -> tuple[Matrix3, Vector3, Any]:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("hybrid gyro features require PyTorch") from exc
    result = _IDENTITY_3
    start_index = bisect.bisect_right(imu_timestamps, start_ns) - 1
    if start_index < 0:
        raise RaftHybridError("camera pair starts before native IMU coverage")
    previous_ns = start_ns
    previous_gyro = tuple(
        value - offset
        for value, offset in zip(imu_samples[start_index].angular_velocity_rad_s, bias, strict=True)
    )
    end_index = bisect.bisect_right(imu_timestamps, end_ns)
    for measurement in imu_samples[start_index + 1 : end_index]:
        dt = (measurement.timestamp_ns - previous_ns) * 1e-9
        corrected = tuple(
            value - offset
            for value, offset in zip(measurement.angular_velocity_rad_s, bias, strict=True)
        )
        average = tuple(
            0.5 * (left + right) for left, right in zip(previous_gyro, corrected, strict=True)
        )
        result = _mm(
            result,
            rotation_vector_to_matrix(tuple(value * dt for value in average)),
        )
        previous_ns = measurement.timestamp_ns
        previous_gyro = corrected
    if previous_ns < end_ns:
        dt = (end_ns - previous_ns) * 1e-9
        result = _mm(
            result,
            rotation_vector_to_matrix(tuple(value * dt for value in previous_gyro)),
        )

    start_window = bisect.bisect_right(imu_timestamps, start_ns)
    window = imu_samples[start_window:end_index]
    if not window:
        raise RaftHybridError(f"no causal IMU samples in camera interval ({start_ns}, {end_ns}]")
    corrected_rows = [
        tuple(
            value - offset
            for value, offset in zip(sample.angular_velocity_rad_s, bias, strict=True)
        )
        for sample in window
    ]
    accel_rows = [sample.linear_acceleration_m_s2 for sample in window]
    gyro = torch.tensor(corrected_rows, dtype=torch.float32)
    accel = torch.tensor(accel_rows, dtype=torch.float32)
    rotation_vector = _matrix_to_rotation_vector(result)
    summary = torch.cat(
        (
            torch.tensor(rotation_vector, dtype=torch.float32),
            gyro.mean(0),
            gyro.std(0, unbiased=False),
            accel.mean(0),
            accel.std(0, unbiased=False),
            accel[0],
            accel[-1],
            torch.tensor([(end_ns - start_ns) * 1e-9], dtype=torch.float32),
        )
    )
    if tuple(summary.shape) != (IMU_FEATURE_DIM,):
        raise RaftHybridError("internal IMU summary dimension changed")
    return result, rotation_vector, summary


def _camera_delta_rotation(calibration: HybridCalibration, imu_delta: Matrix3) -> Matrix3:
    r_bi = tuple(
        tuple(calibration.imu_t_bs[row][column] for column in range(3)) for row in range(3)
    )
    r_bc = tuple(
        tuple(calibration.camera_t_bs[row][column] for column in range(3)) for row in range(3)
    )
    r_ic = _mm(_transpose(r_bi), r_bc)  # type: ignore[arg-type]
    return _mm(_mm(_transpose(r_ic), imu_delta), r_ic)


def _scaled_intrinsics(calibration: HybridCalibration) -> tuple[float, float, float, float]:
    fx, fy, cx, cy = calibration.intrinsics
    scale_x = INPUT_WIDTH / calibration.resolution_width_px
    scale_y = INPUT_HEIGHT / calibration.resolution_height_px
    return (
        fx * scale_x,
        fy * scale_y,
        (cx + 0.5) * scale_x - 0.5,
        (cy + 0.5) * scale_y - 0.5,
    )


def _read_image(
    path: Path,
    *,
    expected_width_px: int,
    expected_height_px: int,
) -> Any:
    try:
        import torch
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError(
            "hybrid image preprocessing requires PyTorch and Pillow"
        ) from exc
    try:
        with Image.open(path) as image:
            if image.size != (expected_width_px, expected_height_px):
                raise RaftHybridError(
                    f"input image dimensions {image.size[0]}x{image.size[1]} do not match "
                    f"calibration resolution {expected_width_px}x{expected_height_px}: {path}"
                )
            grayscale = image.convert("L").resize(
                (INPUT_WIDTH, INPUT_HEIGHT), Image.Resampling.BILINEAR
            )
            pixels = bytearray(grayscale.tobytes())
    except RaftHybridError:
        raise
    except (OSError, ValueError) as exc:
        raise RaftHybridError(f"cannot decode hybrid input image {path}: {exc}") from exc
    tensor = torch.frombuffer(pixels, dtype=torch.uint8).reshape(INPUT_HEIGHT, INPUT_WIDTH)
    return tensor.unsqueeze(0).repeat(3, 1, 1).to(torch.float32).div_(255.0)


def _rectification_grid(
    calibration: HybridCalibration,
    intrinsics: tuple[float, float, float, float],
    device: Any,
) -> tuple[Any, Any]:
    import torch

    fx, fy, cx, cy = intrinsics
    k1, k2, p1, p2 = calibration.distortion_coefficients
    ys, xs = torch.meshgrid(
        torch.arange(INPUT_HEIGHT, device=device, dtype=torch.float32),
        torch.arange(INPUT_WIDTH, device=device, dtype=torch.float32),
        indexing="ij",
    )
    x = (xs - cx) / fx
    y = (ys - cy) / fy
    radius2 = x.square() + y.square()
    radial = 1.0 + k1 * radius2 + k2 * radius2.square()
    distorted_x = x * radial + 2.0 * p1 * x * y + p2 * (radius2 + 2.0 * x.square())
    distorted_y = y * radial + p1 * (radius2 + 2.0 * y.square()) + 2.0 * p2 * x * y
    source_x = fx * distorted_x + cx
    source_y = fy * distorted_y + cy
    grid = torch.stack(
        (
            2.0 * source_x / (INPUT_WIDTH - 1) - 1.0,
            2.0 * source_y / (INPUT_HEIGHT - 1) - 1.0,
        ),
        -1,
    )
    valid = ((grid[..., 0].abs() <= 1.0) & (grid[..., 1].abs() <= 1.0)).unsqueeze(0).unsqueeze(0)
    return grid.unsqueeze(0), valid


def _endpoint_derotated_flow(
    flow: Any,
    rotations: Any,
    intrinsics: tuple[float, float, float, float],
    rectified_valid: Any,
    device: Any,
) -> tuple[Any, Any]:
    import torch

    fx, fy, cx, cy = intrinsics
    ys, xs = torch.meshgrid(
        torch.arange(INPUT_HEIGHT, device=device, dtype=torch.float32),
        torch.arange(INPUT_WIDTH, device=device, dtype=torch.float32),
        indexing="ij",
    )
    endpoint_x = xs.unsqueeze(0) + flow[:, 0]
    endpoint_y = ys.unsqueeze(0) + flow[:, 1]
    current_rays = torch.stack(
        (
            (endpoint_x - cx) / fx,
            (endpoint_y - cy) / fy,
            torch.ones_like(endpoint_x),
        ),
        1,
    ).reshape(-1, 3, INPUT_HEIGHT * INPUT_WIDTH)
    previous = torch.bmm(rotations, current_rays)
    z = previous[:, 2].clamp_min(1e-8)
    corrected_x = (fx * previous[:, 0] / z + cx).reshape(-1, INPUT_HEIGHT, INPUT_WIDTH)
    corrected_y = (fy * previous[:, 1] / z + cy).reshape(-1, INPUT_HEIGHT, INPUT_WIDTH)
    residual = torch.stack((corrected_x - xs, corrected_y - ys), 1)
    valid = (
        (previous[:, 2] > 1e-8).reshape(-1, INPUT_HEIGHT, INPUT_WIDTH)
        & (endpoint_x >= 0)
        & (endpoint_x <= INPUT_WIDTH - 1)
        & (endpoint_y >= 0)
        & (endpoint_y <= INPUT_HEIGHT - 1)
        & (corrected_x >= 0)
        & (corrected_x <= INPUT_WIDTH - 1)
        & (corrected_y >= 0)
        & (corrected_y <= INPUT_HEIGHT - 1)
    ).unsqueeze(1) & rectified_valid
    valid = valid & torch.isfinite(residual).all(dim=1, keepdim=True)
    return torch.nan_to_num(residual), valid


def _compact_flow_features(
    flow: Any,
    valid: Any,
    intrinsics: tuple[float, float, float, float],
) -> Any:
    import torch
    from torch.nn import functional as functional

    fx, fy, _, _ = intrinsics
    scale = torch.tensor((fx, fy), dtype=flow.dtype, device=flow.device).view(1, 2, 1, 1)
    normalized = (flow / scale).clamp(-1.0, 1.0)
    mask = valid.to(flow.dtype)
    fraction = functional.adaptive_avg_pool2d(mask, (GRID_HEIGHT, GRID_WIDTH))
    denominator = fraction.clamp_min(1e-4)
    mean = (
        functional.adaptive_avg_pool2d(normalized * mask, (GRID_HEIGHT, GRID_WIDTH)) / denominator
    )
    second = (
        functional.adaptive_avg_pool2d(normalized.square() * mask, (GRID_HEIGHT, GRID_WIDTH))
        / denominator
    )
    std = (second - mean.square()).clamp_min(0).sqrt()

    flat_mask = mask.flatten(2)
    flat = normalized.flatten(2)
    count = flat_mask.sum(2).clamp_min(1.0)
    global_mean = (flat * flat_mask).sum(2) / count
    global_second = (flat.square() * flat_mask).sum(2) / count
    global_std = (global_second - global_mean.square()).clamp_min(0).sqrt()
    magnitude = torch.linalg.vector_norm(normalized, dim=1, keepdim=True)
    magnitude_mean = (magnitude.flatten(2) * flat_mask).sum(2) / count
    magnitude_second = (magnitude.square().flatten(2) * flat_mask).sum(2) / count
    magnitude_std = (magnitude_second - magnitude_mean.square()).clamp_min(0).sqrt()
    abs_max = (flat.abs() * flat_mask).amax(2)
    stats = torch.cat(
        (
            global_mean,
            global_std,
            magnitude_mean,
            magnitude_std,
            abs_max,
            fraction.mean((2, 3)),
        ),
        dim=1,
    )
    features = torch.cat((mean.flatten(1), std.flatten(1), fraction.flatten(1), stats), dim=1)
    if features.shape[1] != FLOW_FEATURE_DIM:
        raise RaftHybridError("internal compact-flow feature dimension changed")
    return features


def _create_translation_head() -> Any:
    try:
        from torch import nn
    except ImportError as exc:  # pragma: no cover
        raise LearningDependencyError("translation head requires PyTorch") from exc

    class TranslationHead(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(FEATURE_DIM, HEAD_HIDDEN_DIM),
                nn.GELU(),
                nn.Linear(HEAD_HIDDEN_DIM, HEAD_HIDDEN_DIM),
                nn.GELU(),
                nn.Linear(HEAD_HIDDEN_DIM, 3),
            )

        def forward(self, features: Any) -> Any:
            return self.network(features)

    return TranslationHead()


class RaftHybridBackend:
    """Batched raw-recording inference for one validated hybrid package."""

    backend_id = "raft-small-c-t-v2/gyro/train-clamped-translation-head/v1"
    calibration_usage = "pinhole/radtan rectification plus camera/IMU extrinsic gyro derotation"
    motion_frame = "previous IMU sensor frame"

    def __init__(
        self,
        package_manifest: Path | str,
        *,
        device: str = "cpu",
        batch_size: int = 8,
        expected_manifest_sha256: str | None = None,
    ) -> None:
        if type(batch_size) is not int or batch_size <= 0:
            raise RaftHybridError("batch_size must be a positive integer")
        try:
            import torch
            from torchvision.models.optical_flow import Raft_Small_Weights, raft_small
        except ImportError as exc:
            raise LearningDependencyError(
                "RAFT hybrid inference requires torch, torchvision, and Pillow"
            ) from exc
        actual_device = torch.device(device)
        if actual_device.type == "cuda" and not torch.cuda.is_available():
            raise RaftHybridError("CUDA was requested but torch.cuda.is_available() is false")
        package = load_raft_hybrid_package(
            package_manifest,
            expected_manifest_sha256=expected_manifest_sha256,
        )
        try:
            raft_state = torch.load(
                package.raft_weights_path, map_location="cpu", weights_only=True
            )
        except Exception as exc:
            raise RaftHybridError(f"cannot load packaged RAFT weights: {exc}") from exc
        raft = raft_small(weights=None, progress=False)
        try:
            raft.load_state_dict(raft_state, strict=True)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise RaftHybridError(f"packaged RAFT state_dict is incompatible: {exc}") from exc
        raft.to(actual_device).eval()

        head_payload = _load_torch_payload(package.head_checkpoint_path, field="translation head")
        clamp_payload = _load_torch_payload(package.clamp_path, field="feature clamp")
        head = _create_translation_head()
        try:
            head.load_state_dict(head_payload["model_state_dict"], strict=True)
        except (RuntimeError, TypeError, ValueError) as exc:
            raise RaftHybridError(f"translation-head state_dict is incompatible: {exc}") from exc
        head.to(actual_device).eval()

        self.package = package
        self.model_identity = package.manifest_sha256
        self.quality_status = package.manifest["quality_status"]
        self.quality_warning = (
            EXPERIMENTAL_QUALITY_WARNING if self.quality_status == "experimental_rejected" else None
        )
        self.device = actual_device
        self.batch_size = batch_size
        self.raft = raft
        self.raft_transforms = Raft_Small_Weights.C_T_V2.transforms()
        self.head = head
        self.feature_mean = head_payload["feature_mean"].to(actual_device, dtype=torch.float32)
        self.feature_std = head_payload["feature_std"].to(actual_device, dtype=torch.float32)
        self.target_mean = head_payload["target_mean"].to(actual_device, dtype=torch.float32)
        self.target_std = head_payload["target_std"].to(actual_device, dtype=torch.float32)
        self.clamp_min = clamp_payload["clamp_min"].to(actual_device, dtype=torch.float32)
        self.clamp_max = clamp_payload["clamp_max"].to(actual_device, dtype=torch.float32)
        package_architecture = package.manifest["architecture"]
        assert isinstance(package_architecture, dict)
        self.translation_post_matrix = torch.tensor(
            _translation_post_matrix(package_architecture["translation_post_matrix"]),
            dtype=torch.float32,
            device=actual_device,
        )

    def predict_recording(
        self,
        frames: Sequence[CameraSample],
        imu_samples: Sequence[ImuSample],
        calibration: dict[str, object] | None,
    ) -> tuple[MotionEstimate, ...]:
        """Predict every native pair with exact frozen preprocessing and clamp."""

        try:
            import torch
            from torch.nn import functional as functional
        except ImportError as exc:  # pragma: no cover
            raise LearningDependencyError("RAFT hybrid inference requires PyTorch") from exc
        frame_tuple = tuple(frames)
        imu_tuple = tuple(imu_samples)
        if len(frame_tuple) < 2 or not all(isinstance(item, CameraSample) for item in frame_tuple):
            raise RaftHybridError("hybrid recording must contain at least two camera samples")
        if not imu_tuple or not all(isinstance(item, ImuSample) for item in imu_tuple):
            raise RaftHybridError("hybrid recording must contain native timestamped IMU samples")
        if calibration is None:
            raise RaftHybridError("RAFT hybrid inference requires --calibration")
        parsed_calibration = parse_hybrid_calibration(calibration)
        imu_timestamps = tuple(item.timestamp_ns for item in imu_tuple)
        if any(
            current <= previous
            for previous, current in zip(imu_timestamps, imu_timestamps[1:], strict=False)
        ):
            raise RaftHybridError("hybrid IMU timestamps must be strictly increasing")
        bias = _causal_prefix_bias(imu_tuple, frame_tuple[0].timestamp_ns)
        camera_rotations: list[Matrix3] = []
        rotation_vectors: list[Vector3] = []
        imu_summaries: list[Any] = []
        for previous, current in zip(frame_tuple, frame_tuple[1:], strict=False):
            imu_delta, rotation_vector, summary = _integrate_gyro(
                start_ns=previous.timestamp_ns,
                end_ns=current.timestamp_ns,
                imu_samples=imu_tuple,
                imu_timestamps=imu_timestamps,
                bias=bias,
            )
            camera_rotations.append(_camera_delta_rotation(parsed_calibration, imu_delta))
            rotation_vectors.append(rotation_vector)
            imu_summaries.append(summary)

        intrinsics = _scaled_intrinsics(parsed_calibration)
        rectify_grid, rectify_valid = _rectification_grid(
            parsed_calibration, intrinsics, self.device
        )
        translations: list[Vector3] = []
        with torch.inference_mode():
            for start in range(0, len(camera_rotations), self.batch_size):
                end = min(start + self.batch_size, len(camera_rotations))
                image1 = torch.stack(
                    tuple(
                        _read_image(
                            frame_tuple[index].image_path,
                            expected_width_px=parsed_calibration.resolution_width_px,
                            expected_height_px=parsed_calibration.resolution_height_px,
                        )
                        for index in range(start, end)
                    )
                ).to(self.device, non_blocking=True)
                image2 = torch.stack(
                    tuple(
                        _read_image(
                            frame_tuple[index + 1].image_path,
                            expected_width_px=parsed_calibration.resolution_width_px,
                            expected_height_px=parsed_calibration.resolution_height_px,
                        )
                        for index in range(start, end)
                    )
                ).to(self.device, non_blocking=True)
                grid = rectify_grid.expand(image1.shape[0], -1, -1, -1)
                image1 = functional.grid_sample(
                    image1,
                    grid,
                    mode="bilinear",
                    padding_mode="zeros",
                    align_corners=True,
                )
                image2 = functional.grid_sample(
                    image2,
                    grid,
                    mode="bilinear",
                    padding_mode="zeros",
                    align_corners=True,
                )
                image1, image2 = self.raft_transforms(image1, image2)
                with torch.autocast(
                    device_type=self.device.type,
                    dtype=torch.float16,
                    enabled=self.device.type == "cuda",
                ):
                    flow = self.raft(
                        image1,
                        image2,
                        num_flow_updates=RAFT_UPDATES,
                    )[-1]
                flow = flow.to(torch.float32)
                rotations = torch.tensor(
                    camera_rotations[start:end], dtype=torch.float32, device=self.device
                )
                residual, valid = _endpoint_derotated_flow(
                    flow,
                    rotations,
                    intrinsics,
                    rectify_valid,
                    self.device,
                )
                flow_features = _compact_flow_features(residual, valid, intrinsics)
                imu_features = torch.stack(imu_summaries[start:end]).to(self.device)
                features = torch.cat((flow_features, imu_features), dim=1)
                if tuple(features.shape) != (end - start, FEATURE_DIM):
                    raise RaftHybridError("hybrid feature tensor has an incompatible shape")
                standardized = (features - self.feature_mean) / self.feature_std
                clamped = torch.maximum(torch.minimum(standardized, self.clamp_max), self.clamp_min)
                decoded = self.target_mean + self.target_std * self.head(clamped)
                decoded = decoded @ self.translation_post_matrix.transpose(0, 1)
                if not bool(torch.isfinite(decoded).all()):
                    raise RaftHybridError("translation head produced non-finite output")
                translations.extend(
                    tuple(float(value) for value in row)
                    for row in decoded.detach().to(device="cpu", dtype=torch.float64).tolist()
                )
        return tuple(
            MotionEstimate(
                translation_previous_m=translation,
                rotation_vector_rad=rotation_vector,
            )
            for translation, rotation_vector in zip(translations, rotation_vectors, strict=True)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-package-raft-hybrid",
        description="Build a self-contained RAFT-small/gyro/translation-head model package.",
    )
    parser.add_argument("--raft-weights", required=True, type=Path)
    parser.add_argument("--head-checkpoint", required=True, type=Path)
    parser.add_argument("--feature-clamp", required=True, type=Path)
    parser.add_argument(
        "--evaluation-summary",
        required=True,
        type=Path,
        help=(
            "canonical compact_vio_raft_hybrid_evaluation_summary JSON; rejected outcomes "
            "remain runnable but are marked experimental"
        ),
    )
    parser.add_argument(
        "--head-onnx",
        required=True,
        type=Path,
        help="checked translation-head.onnx embedded in the package",
    )
    parser.add_argument(
        "--head-onnx-manifest",
        required=True,
        type=Path,
        help="strict ONNX export/parity sidecar embedded in the package",
    )
    parser.add_argument(
        "--translation-post-matrix",
        type=float,
        nargs=9,
        metavar=("M00", "M01", "M02", "M10", "M11", "M12", "M20", "M21", "M22"),
        help="optional row-major 3x3 no-bias matrix; default is identity",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_raft_hybrid_package(
            args.output,
            raft_weights_path=args.raft_weights,
            head_checkpoint_path=args.head_checkpoint,
            clamp_path=args.feature_clamp,
            evaluation_summary_path=args.evaluation_summary,
            translation_post_matrix=args.translation_post_matrix,
            head_onnx_path=args.head_onnx,
            head_onnx_manifest_path=args.head_onnx_manifest,
        )
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "event": "raft_hybrid_package_failed",
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
                "event": "raft_hybrid_package_complete",
                "manifest": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "head_checkpoint_sha256": result.head_checkpoint_sha256,
                "feature_clamp_sha256": result.clamp_sha256,
                "evaluation_summary_sha256": result.evaluation_summary_sha256,
                "head_onnx_sha256": result.head_onnx_sha256,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "FEATURE_DIM",
    "FLOW_FEATURE_DIM",
    "GRID_HEIGHT",
    "GRID_WIDTH",
    "HEAD_HIDDEN_DIM",
    "HybridCalibration",
    "IMU_FEATURE_DIM",
    "INPUT_HEIGHT",
    "INPUT_WIDTH",
    "PACKAGE_RECORD_TYPE",
    "PACKAGE_SCHEMA_VERSION",
    "RAFT_WEIGHTS_SHA256",
    "RaftHybridBackend",
    "RaftHybridError",
    "RaftHybridPackage",
    "build_parser",
    "build_raft_hybrid_package",
    "euroc_calibration_document",
    "load_raft_hybrid_package",
    "main",
    "parse_hybrid_calibration",
]

"""Checked ONNX export for the frozen clamped RAFT translation head.

The exported graph intentionally starts after RAFT feature extraction.  It has
one raw feature input and performs the frozen standardization, train-only
feature clamp, MLP, and target de-standardization inside the graph.  PyTorch,
ONNX, and ONNX Runtime imports stay lazy so command help remains usable in a
dependency-light installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from compact_vio.learning.errors import LearningDependencyError, LearningError

if TYPE_CHECKING:  # pragma: no cover - type checking only
    from torch import Tensor


RAFT_HEAD_ONNX_RECORD_TYPE = "compact_vio_raft_translation_head_onnx_export"
RAFT_HEAD_ONNX_SCHEMA_VERSION = "1.1.0"
RAFT_HEAD_INPUT_NAMES = ("features",)
RAFT_HEAD_OUTPUT_NAMES = ("translation_previous_imu_m",)
RAFT_HEAD_FEATURE_DIM = 831
RAFT_HEAD_OUTPUT_DIM = 3
RAFT_HEAD_HIDDEN_DIM = 128
RAFT_HEAD_ONNX_OPSET = 17
RAFT_HEAD_PARITY_TOLERANCE = 1e-5
RAFT_HEAD_FORMULA = (
    "z=(features-feature_mean)/feature_std; "
    "z=max(min(z,clamp_max),clamp_min); "
    "decoded=target_mean+target_std*MLP(z); "
    "translation_previous_imu_m=decoded@translation_post_matrix^T"
)
RAFT_HEAD_CLAMP_RECORD_TYPE = "train_only_standardized_feature_clamp"
RAFT_HEAD_CLAMP_SCHEMA_VERSION = 1
RAFT_HEAD_CLAMP_RULE = (
    "per-feature exact train standardized min/max; exact raw train constants forced to [0,0]"
)

_HEAD_FIELDS = {
    "architecture",
    "feature_mean",
    "feature_std",
    "model_state_dict",
    "selected",
    "target_mean",
    "target_std",
}
_ARCHITECTURE = {
    "activation": "GELU",
    "feature_dim": RAFT_HEAD_FEATURE_DIM,
    "hidden_dim": RAFT_HEAD_HIDDEN_DIM,
    "layers": [
        RAFT_HEAD_FEATURE_DIM,
        RAFT_HEAD_HIDDEN_DIM,
        RAFT_HEAD_HIDDEN_DIM,
        RAFT_HEAD_OUTPUT_DIM,
    ],
    "type": "MLP",
}
_STATE_SHAPES = {
    "network.0.bias": (RAFT_HEAD_HIDDEN_DIM,),
    "network.0.weight": (RAFT_HEAD_HIDDEN_DIM, RAFT_HEAD_FEATURE_DIM),
    "network.2.bias": (RAFT_HEAD_HIDDEN_DIM,),
    "network.2.weight": (RAFT_HEAD_HIDDEN_DIM, RAFT_HEAD_HIDDEN_DIM),
    "network.4.bias": (RAFT_HEAD_OUTPUT_DIM,),
    "network.4.weight": (RAFT_HEAD_OUTPUT_DIM, RAFT_HEAD_HIDDEN_DIM),
}
_CLAMP_FIELDS = {
    "clamp_max",
    "clamp_max_tensor_sha256",
    "clamp_min",
    "clamp_min_tensor_sha256",
    "constant_feature_count",
    "constant_feature_mask",
    "constant_mask_tensor_sha256",
    "feature_dim",
    "head_checkpoint_path",
    "head_checkpoint_sha256",
    "record_type",
    "rule",
    "schema_version",
    "source_cache_path",
    "source_cache_sha256",
    "train_sequence_ids",
}
_SHA256_HEX_LENGTH = 64
_READ_CHUNK_BYTES = 8 * 1024 * 1024
_IDENTITY_3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


@dataclass(frozen=True, slots=True)
class RaftHeadParityRun:
    """One dynamic-batch PyTorch-versus-ONNX Runtime comparison."""

    run_index: int
    batch_size: int
    translation_max_abs_error: float


@dataclass(frozen=True, slots=True)
class RaftHeadParityResult:
    """Numerical parity evidence for the complete clamped head formula."""

    provider: str
    absolute_tolerance: float
    relative_tolerance: float
    runs: tuple[RaftHeadParityRun, ...]

    @property
    def max_translation_abs_error(self) -> float:
        return max(run.translation_max_abs_error for run in self.runs)

    def to_dict(self) -> dict[str, object]:
        return {
            "absolute_tolerance": self.absolute_tolerance,
            "max_translation_abs_error": self.max_translation_abs_error,
            "provider": self.provider,
            "relative_tolerance": self.relative_tolerance,
            "runs": [asdict(run) for run in self.runs],
            "status": "passed",
        }


@dataclass(frozen=True, slots=True)
class ExportedRaftHeadOnnx:
    """Paths, hashes, and parity evidence for one completed export."""

    model_path: Path
    manifest_path: Path
    model_sha256: str
    manifest_sha256: str
    parity: RaftHeadParityResult | None


@dataclass(frozen=True, slots=True)
class _LoadedRaftHeadSources:
    model: object
    head_sha256: str
    clamp_sha256: str
    architecture: dict[str, object]
    selected: dict[str, object]
    train_sequence_ids: tuple[str, ...]
    source_cache_sha256: str
    clamp_rule: str
    clamp_min_tensor_sha256: str
    clamp_max_tensor_sha256: str
    constant_mask_tensor_sha256: str
    constant_feature_count: int
    normalization_tensor_sha256: dict[str, str]
    translation_post_matrix: tuple[tuple[float, float, float], ...]


def _sha256_value(value: object, *, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_HEX_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LearningError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _sha256_file(path: Path, *, field: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise LearningError(f"{field} must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_READ_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as exc:
        raise LearningError(f"cannot hash {field} {path}: {exc}") from exc
    return digest.hexdigest()


def _sha256_float32_tensor(tensor: Tensor) -> str:
    contiguous = tensor.detach().cpu().to(dtype=_torch().float32).contiguous()
    return hashlib.sha256(contiguous.numpy().tobytes(order="C")).hexdigest()


def _sha256_bool_tensor(tensor: Tensor) -> str:
    contiguous = tensor.detach().cpu().to(dtype=_torch().bool).contiguous()
    return hashlib.sha256(contiguous.numpy().tobytes(order="C")).hexdigest()


def _torch() -> object:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for RAFT head ONNX export; install the ONNX extra"
        ) from exc
    return torch


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
        raise LearningError(f"RAFT head ONNX manifest is not canonical JSON data: {exc}") from exc


def _json_mapping(value: object, *, field: str) -> dict[str, object]:
    if type(value) is not dict:
        raise LearningError(f"{field} must be an object")
    try:
        encoded = json.dumps(value, sort_keys=True, allow_nan=False)
        decoded = json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise LearningError(f"{field} must contain only finite JSON data: {exc}") from exc
    if type(decoded) is not dict:  # pragma: no cover - guarded above
        raise LearningError(f"{field} must be an object")
    return decoded


def _translation_post_matrix(
    value: object | None,
) -> tuple[tuple[float, float, float], ...]:
    if value is None:
        return _IDENTITY_3
    if (
        type(value) in (list, tuple)
        and len(value) == 9
        and all(type(item) in (int, float) for item in value)
    ):
        flat = tuple(float(item) for item in value)
        rows = tuple(tuple(flat[row * 3 : (row + 1) * 3]) for row in range(3))
    elif type(value) in (list, tuple) and len(value) == 3:
        if any(
            type(row) not in (list, tuple)
            or len(row) != 3
            or any(type(item) not in (int, float) for item in row)
            for row in value
        ):
            raise LearningError("translation_post_matrix must contain exactly 3x3 real values")
        rows = tuple(tuple(float(item) for item in row) for row in value)
    else:
        raise LearningError("translation_post_matrix must contain exactly 3x3 real values")
    if any(not math.isfinite(item) for row in rows for item in row):
        raise LearningError("translation_post_matrix must contain only finite values")
    if max(abs(item) for row in rows for item in row) > 10.0:
        raise LearningError("translation_post_matrix coefficients must be bounded by 10")
    return rows


def _require_new_path(path: Path, *, field: str) -> None:
    if path.is_symlink() or path.exists():
        raise LearningError(f"refusing to overwrite {field}: {path}")
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise LearningError(f"{field} parent must be a regular directory: {path.parent}")


def _link_exclusive(source: Path, destination: Path, *, field: str) -> Path:
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise LearningError(f"refusing to overwrite {field}: {destination}") from exc
    except OSError as exc:
        raise LearningError(f"cannot commit {field} {destination}: {exc}") from exc
    return destination.resolve(strict=True)


def _require_tensor(
    value: object,
    *,
    field: str,
    shape: tuple[int, ...],
    dtype: object,
) -> Tensor:
    torch = _torch()
    if not isinstance(value, torch.Tensor):
        raise LearningError(f"{field} must be a PyTorch tensor")
    if tuple(value.shape) != shape:
        raise LearningError(f"{field} must have shape {shape}, got {tuple(value.shape)}")
    if value.dtype != dtype:
        raise LearningError(f"{field} must use {dtype}, got {value.dtype}")
    result = value.detach().cpu().contiguous()
    if dtype != torch.bool and not torch.isfinite(result).all():
        raise LearningError(f"{field} must contain only finite values")
    return result


def _load_payload(path: Path, *, field: str) -> dict[str, object]:
    torch = _torch()
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise LearningError(f"cannot load {field} {path}: {exc}") from exc
    if type(payload) is not dict:
        raise LearningError(f"{field} payload must be an object")
    return payload


def _create_model(
    *,
    state_dict: Mapping[str, Tensor],
    feature_mean: Tensor,
    feature_std: Tensor,
    target_mean: Tensor,
    target_std: Tensor,
    clamp_min: Tensor,
    clamp_max: Tensor,
    translation_post_matrix: tuple[tuple[float, float, float], ...],
) -> object:
    torch = _torch()
    nn = torch.nn

    class _TranslationHead(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.network = nn.Sequential(
                nn.Linear(RAFT_HEAD_FEATURE_DIM, RAFT_HEAD_HIDDEN_DIM),
                nn.GELU(),
                nn.Linear(RAFT_HEAD_HIDDEN_DIM, RAFT_HEAD_HIDDEN_DIM),
                nn.GELU(),
                nn.Linear(RAFT_HEAD_HIDDEN_DIM, RAFT_HEAD_OUTPUT_DIM),
            )

        def forward(self, features: object) -> object:
            return self.network(features)

    class _ClampedTranslationHead(nn.Module):
        def __init__(self, head: object) -> None:
            super().__init__()
            self.head = head
            self.register_buffer("feature_mean", feature_mean.clone())
            self.register_buffer("feature_std", feature_std.clone())
            self.register_buffer("target_mean", target_mean.clone())
            self.register_buffer("target_std", target_std.clone())
            self.register_buffer("clamp_min", clamp_min.clone())
            self.register_buffer("clamp_max", clamp_max.clone())
            self.register_buffer(
                "translation_post_matrix",
                torch.tensor(translation_post_matrix, dtype=torch.float32),
            )

        def forward(self, features: object) -> object:
            standardized = (features - self.feature_mean) / self.feature_std
            clamped = torch.maximum(
                torch.minimum(standardized, self.clamp_max),
                self.clamp_min,
            )
            decoded = self.target_mean + self.target_std * self.head(clamped)
            return decoded @ self.translation_post_matrix.transpose(0, 1)

    head = _TranslationHead()
    try:
        head.load_state_dict(state_dict, strict=True)
    except Exception as exc:
        raise LearningError(f"RAFT head model_state_dict is incompatible: {exc}") from exc
    return _ClampedTranslationHead(head).cpu().eval()


def _load_frozen_sources(
    head_checkpoint: os.PathLike[str] | str,
    clamp_artifact: os.PathLike[str] | str,
    *,
    expected_head_sha256: str,
    expected_clamp_sha256: str,
    translation_post_matrix: object | None = None,
) -> _LoadedRaftHeadSources:
    """Load and strictly validate the two source artifacts."""

    torch = _torch()
    post_matrix = _translation_post_matrix(translation_post_matrix)
    head_path = Path(head_checkpoint)
    clamp_path = Path(clamp_artifact)
    expected_head = _sha256_value(expected_head_sha256, field="expected_head_sha256")
    expected_clamp = _sha256_value(expected_clamp_sha256, field="expected_clamp_sha256")
    head_sha256 = _sha256_file(head_path, field="RAFT head checkpoint")
    clamp_sha256 = _sha256_file(clamp_path, field="RAFT clamp artifact")
    if head_sha256 != expected_head:
        raise LearningError(
            f"RAFT head checkpoint SHA-256 mismatch: expected {expected_head}, got {head_sha256}"
        )
    if clamp_sha256 != expected_clamp:
        raise LearningError(
            f"RAFT clamp artifact SHA-256 mismatch: expected {expected_clamp}, got {clamp_sha256}"
        )

    head = _load_payload(head_path, field="RAFT head checkpoint")
    if set(head) != _HEAD_FIELDS:
        raise LearningError("RAFT head checkpoint fields do not match the frozen schema")
    architecture = _json_mapping(head["architecture"], field="architecture")
    if architecture != _ARCHITECTURE:
        raise LearningError("RAFT head architecture does not match 831->128->128->3 GELU")
    selected = _json_mapping(head["selected"], field="selected")

    feature_mean = _require_tensor(
        head["feature_mean"],
        field="feature_mean",
        shape=(RAFT_HEAD_FEATURE_DIM,),
        dtype=torch.float32,
    )
    feature_std = _require_tensor(
        head["feature_std"],
        field="feature_std",
        shape=(RAFT_HEAD_FEATURE_DIM,),
        dtype=torch.float32,
    )
    target_mean = _require_tensor(
        head["target_mean"],
        field="target_mean",
        shape=(RAFT_HEAD_OUTPUT_DIM,),
        dtype=torch.float32,
    )
    target_std = _require_tensor(
        head["target_std"],
        field="target_std",
        shape=(RAFT_HEAD_OUTPUT_DIM,),
        dtype=torch.float32,
    )
    if torch.any(feature_std <= 0):
        raise LearningError("feature_std must be strictly positive")
    if torch.any(target_std <= 0):
        raise LearningError("target_std must be strictly positive")

    raw_state = head["model_state_dict"]
    if not isinstance(raw_state, Mapping) or set(raw_state) != set(_STATE_SHAPES):
        raise LearningError("model_state_dict fields do not match the frozen RAFT head")
    state_dict = {
        name: _require_tensor(
            raw_state[name],
            field=f"model_state_dict.{name}",
            shape=shape,
            dtype=torch.float32,
        )
        for name, shape in _STATE_SHAPES.items()
    }

    clamp = _load_payload(clamp_path, field="RAFT clamp artifact")
    if set(clamp) != _CLAMP_FIELDS:
        raise LearningError("RAFT clamp artifact fields do not match the frozen schema")
    if (
        clamp["record_type"] != RAFT_HEAD_CLAMP_RECORD_TYPE
        or clamp["schema_version"] != RAFT_HEAD_CLAMP_SCHEMA_VERSION
        or clamp["feature_dim"] != RAFT_HEAD_FEATURE_DIM
        or clamp["rule"] != RAFT_HEAD_CLAMP_RULE
    ):
        raise LearningError("RAFT clamp artifact identity or rule is unsupported")
    bound_head_sha256 = _sha256_value(
        clamp["head_checkpoint_sha256"], field="clamp.head_checkpoint_sha256"
    )
    if bound_head_sha256 != head_sha256:
        raise LearningError("RAFT clamp artifact does not bind the selected head checkpoint")
    source_cache_sha256 = _sha256_value(
        clamp["source_cache_sha256"], field="clamp.source_cache_sha256"
    )
    for path_field in ("source_cache_path", "head_checkpoint_path"):
        if type(clamp[path_field]) is not str or not clamp[path_field]:
            raise LearningError(f"clamp.{path_field} must be a non-empty string")
    train_ids = clamp["train_sequence_ids"]
    if (
        type(train_ids) is not list
        or not train_ids
        or any(type(item) is not str or not item for item in train_ids)
        or len(set(train_ids)) != len(train_ids)
    ):
        raise LearningError("clamp.train_sequence_ids must be unique non-empty strings")

    clamp_min = _require_tensor(
        clamp["clamp_min"],
        field="clamp_min",
        shape=(RAFT_HEAD_FEATURE_DIM,),
        dtype=torch.float32,
    )
    clamp_max = _require_tensor(
        clamp["clamp_max"],
        field="clamp_max",
        shape=(RAFT_HEAD_FEATURE_DIM,),
        dtype=torch.float32,
    )
    constant_mask = _require_tensor(
        clamp["constant_feature_mask"],
        field="constant_feature_mask",
        shape=(RAFT_HEAD_FEATURE_DIM,),
        dtype=torch.bool,
    )
    if torch.any(clamp_min > clamp_max):
        raise LearningError("clamp_min must be less than or equal to clamp_max")
    if torch.any(clamp_min[constant_mask] != 0) or torch.any(clamp_max[constant_mask] != 0):
        raise LearningError("constant feature clamp bounds must both be exactly zero")

    clamp_min_sha256 = _sha256_value(
        clamp["clamp_min_tensor_sha256"], field="clamp.clamp_min_tensor_sha256"
    )
    clamp_max_sha256 = _sha256_value(
        clamp["clamp_max_tensor_sha256"], field="clamp.clamp_max_tensor_sha256"
    )
    constant_mask_sha256 = _sha256_value(
        clamp["constant_mask_tensor_sha256"], field="clamp.constant_mask_tensor_sha256"
    )
    if _sha256_float32_tensor(clamp_min) != clamp_min_sha256:
        raise LearningError("clamp_min tensor SHA-256 mismatch")
    if _sha256_float32_tensor(clamp_max) != clamp_max_sha256:
        raise LearningError("clamp_max tensor SHA-256 mismatch")
    if _sha256_bool_tensor(constant_mask) != constant_mask_sha256:
        raise LearningError("constant_feature_mask tensor SHA-256 mismatch")
    constant_count = clamp["constant_feature_count"]
    if type(constant_count) is not int or constant_count != int(constant_mask.sum().item()):
        raise LearningError("constant_feature_count does not match constant_feature_mask")

    if _sha256_file(head_path, field="RAFT head checkpoint") != head_sha256:
        raise LearningError("RAFT head checkpoint changed while it was being loaded")
    if _sha256_file(clamp_path, field="RAFT clamp artifact") != clamp_sha256:
        raise LearningError("RAFT clamp artifact changed while it was being loaded")

    model = _create_model(
        state_dict=state_dict,
        feature_mean=feature_mean,
        feature_std=feature_std,
        target_mean=target_mean,
        target_std=target_std,
        clamp_min=clamp_min,
        clamp_max=clamp_max,
        translation_post_matrix=post_matrix,
    )
    normalization_hashes = {
        "feature_mean": _sha256_float32_tensor(feature_mean),
        "feature_std": _sha256_float32_tensor(feature_std),
        "target_mean": _sha256_float32_tensor(target_mean),
        "target_std": _sha256_float32_tensor(target_std),
    }
    return _LoadedRaftHeadSources(
        model=model,
        head_sha256=head_sha256,
        clamp_sha256=clamp_sha256,
        architecture=architecture,
        selected=selected,
        train_sequence_ids=tuple(train_ids),
        source_cache_sha256=source_cache_sha256,
        clamp_rule=str(clamp["rule"]),
        clamp_min_tensor_sha256=clamp_min_sha256,
        clamp_max_tensor_sha256=clamp_max_sha256,
        constant_mask_tensor_sha256=constant_mask_sha256,
        constant_feature_count=constant_count,
        normalization_tensor_sha256=normalization_hashes,
        translation_post_matrix=post_matrix,
    )


def _validate_tolerance(value: object, *, field: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)) or float(value) < 0:
        raise LearningError(f"{field} must be finite and non-negative")
    return float(value)


def _synthetic_features(model: object, *, batch_size: int, seed: int) -> object:
    torch = _torch()
    if type(batch_size) is not int or batch_size <= 0:
        raise LearningError("batch_size must be a positive integer")
    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    standardized = (
        torch.randn(
            batch_size,
            RAFT_HEAD_FEATURE_DIM,
            generator=generator,
            dtype=torch.float32,
        )
        * 3.0
    )
    if batch_size >= 1:
        standardized[0, ::2] = model.clamp_min[::2] - 1.0
        standardized[0, 1::2] = model.clamp_max[1::2] + 1.0
    return model.feature_mean + model.feature_std * standardized


def _export_graph(model: object, destination: Path) -> None:
    torch = _torch()
    try:
        import onnx  # noqa: F401 - exporter dependency preflight
    except ImportError as exc:
        raise LearningDependencyError(
            "ONNX is required for RAFT head export; install the ONNX extra"
        ) from exc
    sample = _synthetic_features(model, batch_size=1, seed=31_831)
    try:
        torch.onnx.export(
            model,
            (sample,),
            str(destination),
            export_params=True,
            opset_version=RAFT_HEAD_ONNX_OPSET,
            do_constant_folding=True,
            input_names=list(RAFT_HEAD_INPUT_NAMES),
            output_names=list(RAFT_HEAD_OUTPUT_NAMES),
            dynamic_axes={
                RAFT_HEAD_INPUT_NAMES[0]: {0: "batch"},
                RAFT_HEAD_OUTPUT_NAMES[0]: {0: "batch"},
            },
            dynamo=False,
        )
    except Exception as exc:
        raise LearningError(f"cannot export RAFT translation head ONNX graph: {exc}") from exc


def _annotate_and_check_onnx(path: Path, sources: _LoadedRaftHeadSources) -> None:
    try:
        import onnx
    except ImportError as exc:
        raise LearningDependencyError(
            "ONNX is required for RAFT head validation; install the ONNX extra"
        ) from exc
    metadata = {
        "compact_vio.formula": RAFT_HEAD_FORMULA,
        "compact_vio.raft_head_clamp_artifact_sha256": sources.clamp_sha256,
        "compact_vio.raft_head_clamp_max_tensor_sha256": (sources.clamp_max_tensor_sha256),
        "compact_vio.raft_head_clamp_min_tensor_sha256": (sources.clamp_min_tensor_sha256),
        "compact_vio.raft_head_constant_mask_tensor_sha256": (sources.constant_mask_tensor_sha256),
        "compact_vio.raft_head_export_schema_version": RAFT_HEAD_ONNX_SCHEMA_VERSION,
        "compact_vio.raft_head_source_checkpoint_sha256": sources.head_sha256,
        "compact_vio.raft_head_translation_post_matrix": json.dumps(
            [list(row) for row in sources.translation_post_matrix],
            separators=(",", ":"),
        ),
        "compact_vio.raft_head_units": "meters in previous IMU sensor frame",
    }
    try:
        graph = onnx.load_model(path)
        onnx.helper.set_model_props(graph, metadata)
        onnx.checker.check_model(graph, full_check=True)
        onnx.save_model(graph, path)
        onnx.checker.check_model(onnx.load_model(path), full_check=True)
    except Exception as exc:
        raise LearningError(f"exported RAFT head ONNX graph validation failed: {exc}") from exc


def _check_onnx_structure(
    path: Path,
    *,
    source_head: Mapping[str, object],
    source_clamp: Mapping[str, object],
    translation_post_matrix: tuple[tuple[float, float, float], ...],
) -> None:
    """Parse and strictly check the portable graph rather than trusting its sidecar."""

    try:
        import onnx
    except ImportError as exc:
        raise LearningDependencyError(
            "ONNX is required to verify a RAFT head package; install the ONNX extra"
        ) from exc
    expected_metadata = {
        "compact_vio.formula": RAFT_HEAD_FORMULA,
        "compact_vio.raft_head_clamp_artifact_sha256": source_clamp["artifact_sha256"],
        "compact_vio.raft_head_clamp_max_tensor_sha256": source_clamp["clamp_max_tensor_sha256"],
        "compact_vio.raft_head_clamp_min_tensor_sha256": source_clamp["clamp_min_tensor_sha256"],
        "compact_vio.raft_head_constant_mask_tensor_sha256": source_clamp[
            "constant_mask_tensor_sha256"
        ],
        "compact_vio.raft_head_export_schema_version": RAFT_HEAD_ONNX_SCHEMA_VERSION,
        "compact_vio.raft_head_source_checkpoint_sha256": source_head["checkpoint_sha256"],
        "compact_vio.raft_head_translation_post_matrix": json.dumps(
            [list(row) for row in translation_post_matrix],
            separators=(",", ":"),
        ),
        "compact_vio.raft_head_units": "meters in previous IMU sensor frame",
    }
    try:
        graph = onnx.load_model(path)
        onnx.checker.check_model(graph, full_check=True)
    except Exception as exc:
        raise LearningError(f"RAFT head ONNX graph is invalid: {exc}") from exc
    default_opsets = [item.version for item in graph.opset_import if item.domain in {"", "ai.onnx"}]
    if default_opsets != [RAFT_HEAD_ONNX_OPSET]:
        raise LearningError("RAFT head ONNX graph opset does not match the export contract")
    if len(graph.graph.input) != 1 or len(graph.graph.output) != 1:
        raise LearningError("RAFT head ONNX graph must have exactly one input and one output")
    input_value = graph.graph.input[0]
    output_value = graph.graph.output[0]
    if (
        input_value.name != RAFT_HEAD_INPUT_NAMES[0]
        or output_value.name != RAFT_HEAD_OUTPUT_NAMES[0]
    ):
        raise LearningError("RAFT head ONNX graph I/O names do not match the export contract")
    input_type = input_value.type.tensor_type
    output_type = output_value.type.tensor_type
    if (
        input_type.elem_type != onnx.TensorProto.FLOAT
        or output_type.elem_type != onnx.TensorProto.FLOAT
    ):
        raise LearningError("RAFT head ONNX graph I/O must use float32")
    input_shape = input_type.shape.dim
    output_shape = output_type.shape.dim
    if (
        len(input_shape) != 2
        or input_shape[0].dim_param != "batch"
        or input_shape[1].dim_value != RAFT_HEAD_FEATURE_DIM
        or len(output_shape) != 2
        or output_shape[0].dim_param != "batch"
        or output_shape[1].dim_value != RAFT_HEAD_OUTPUT_DIM
    ):
        raise LearningError("RAFT head ONNX graph I/O shapes do not match the export contract")
    metadata = {item.key: item.value for item in graph.metadata_props}
    if metadata != expected_metadata:
        raise LearningError("RAFT head ONNX graph metadata does not match its bound sources")


def check_raft_head_onnx_parity(
    onnx_path: os.PathLike[str] | str,
    model: object,
    *,
    expected_onnx_sha256: str | None = None,
    relative_tolerance: float = 1e-5,
    absolute_tolerance: float = 1e-5,
) -> RaftHeadParityResult:
    """Require CPU ONNX Runtime parity at two different batch sizes."""

    relative = _validate_tolerance(relative_tolerance, field="relative_tolerance")
    absolute = _validate_tolerance(absolute_tolerance, field="absolute_tolerance")
    os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
    try:
        import numpy as np
        import onnxruntime as ort
    except ImportError as exc:
        raise LearningDependencyError(
            "ONNX Runtime and NumPy are required for RAFT head parity checking"
        ) from exc
    torch = _torch()
    source = Path(onnx_path)
    observed_sha256 = _sha256_file(source, field="RAFT head ONNX model")
    if expected_onnx_sha256 is not None:
        expected = _sha256_value(expected_onnx_sha256, field="expected_onnx_sha256")
        if observed_sha256 != expected:
            raise LearningError(
                f"ONNX SHA-256 mismatch: expected {expected}, got {observed_sha256}"
            )
    try:
        session = ort.InferenceSession(str(source), providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise LearningError(f"cannot load RAFT head model in ONNX Runtime: {exc}") from exc
    if tuple(item.name for item in session.get_inputs()) != RAFT_HEAD_INPUT_NAMES:
        raise LearningError("ONNX Runtime input names do not match the RAFT head contract")
    if tuple(item.name for item in session.get_outputs()) != RAFT_HEAD_OUTPUT_NAMES:
        raise LearningError("ONNX Runtime output names do not match the RAFT head contract")

    model.cpu().eval()
    runs: list[RaftHeadParityRun] = []
    for run_index, batch_size in enumerate((1, 4), start=1):
        features = _synthetic_features(model, batch_size=batch_size, seed=41_831 + run_index)
        with torch.inference_mode():
            expected_output = model(features).detach().numpy()
        try:
            (actual_output,) = session.run(
                list(RAFT_HEAD_OUTPUT_NAMES),
                {RAFT_HEAD_INPUT_NAMES[0]: features.numpy()},
            )
        except Exception as exc:
            raise LearningError(f"RAFT head ONNX parity run {run_index} failed: {exc}") from exc
        if (
            actual_output.shape != expected_output.shape
            or actual_output.dtype != expected_output.dtype
        ):
            raise LearningError(
                f"RAFT head ONNX parity run {run_index} output shape or dtype mismatch"
            )
        if not np.isfinite(actual_output).all():
            raise LearningError(f"RAFT head ONNX parity run {run_index} output is non-finite")
        difference = np.abs(actual_output - expected_output)
        maximum = float(difference.max(initial=0.0))
        if not np.allclose(
            actual_output,
            expected_output,
            rtol=relative,
            atol=absolute,
            equal_nan=False,
        ):
            raise LearningError(
                f"RAFT head ONNX parity run {run_index} failed: max absolute error "
                f"{maximum:.9g}, rtol {relative:.9g}, atol {absolute:.9g}"
            )
        runs.append(
            RaftHeadParityRun(
                run_index=run_index,
                batch_size=batch_size,
                translation_max_abs_error=maximum,
            )
        )
    if _sha256_file(source, field="RAFT head ONNX model") != observed_sha256:
        raise LearningError("RAFT head ONNX model changed while parity was being checked")
    return RaftHeadParityResult(
        provider="CPUExecutionProvider",
        absolute_tolerance=absolute,
        relative_tolerance=relative,
        runs=tuple(runs),
    )


def _io_contract() -> dict[str, object]:
    return {
        "inputs": [
            {
                "dtype": "float32",
                "name": RAFT_HEAD_INPUT_NAMES[0],
                "semantic": "raw frozen-RAFT/IMU feature vector before standardization",
                "shape": ["batch", RAFT_HEAD_FEATURE_DIM],
            }
        ],
        "outputs": [
            {
                "dtype": "float32",
                "frame": "previous IMU sensor frame",
                "name": RAFT_HEAD_OUTPUT_NAMES[0],
                "shape": ["batch", RAFT_HEAD_OUTPUT_DIM],
                "units": "m",
            }
        ],
    }


def export_raft_head_onnx(
    head_checkpoint: os.PathLike[str] | str,
    clamp_artifact: os.PathLike[str] | str,
    destination: os.PathLike[str] | str,
    manifest_destination: os.PathLike[str] | str,
    *,
    expected_head_sha256: str,
    expected_clamp_sha256: str,
    verify_parity: bool = True,
    parity_relative_tolerance: float = 1e-5,
    parity_absolute_tolerance: float = 1e-5,
    translation_post_matrix: object | None = None,
) -> ExportedRaftHeadOnnx:
    """Export the exact frozen clamped head without overwriting any path."""

    if type(verify_parity) is not bool:
        raise LearningError("verify_parity must be boolean")
    if (
        _validate_tolerance(parity_relative_tolerance, field="parity_relative_tolerance")
        > RAFT_HEAD_PARITY_TOLERANCE
        or _validate_tolerance(parity_absolute_tolerance, field="parity_absolute_tolerance")
        > RAFT_HEAD_PARITY_TOLERANCE
    ):
        raise LearningError("RAFT head ONNX export tolerances must not exceed 1e-5")
    target = Path(destination)
    manifest_target = Path(manifest_destination)
    if target == manifest_target:
        raise LearningError("ONNX model and manifest destinations must be different")
    _require_new_path(target, field="RAFT head ONNX model destination")
    _require_new_path(manifest_target, field="RAFT head ONNX manifest destination")
    sources = _load_frozen_sources(
        head_checkpoint,
        clamp_artifact,
        expected_head_sha256=expected_head_sha256,
        expected_clamp_sha256=expected_clamp_sha256,
        translation_post_matrix=translation_post_matrix,
    )

    model_temporary: Path | None = None
    manifest_temporary: Path | None = None
    committed_model: Path | None = None
    committed_manifest: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".onnx", dir=target.parent, delete=False
        ) as handle:
            model_temporary = Path(handle.name)
        _export_graph(sources.model, model_temporary)
        _annotate_and_check_onnx(model_temporary, sources)
        onnx_sha256 = _sha256_file(model_temporary, field="temporary RAFT head ONNX model")
        parity = (
            check_raft_head_onnx_parity(
                model_temporary,
                sources.model,
                expected_onnx_sha256=onnx_sha256,
                relative_tolerance=parity_relative_tolerance,
                absolute_tolerance=parity_absolute_tolerance,
            )
            if verify_parity
            else None
        )
        manifest: dict[str, object] = {
            "artifact": {
                "byte_size": model_temporary.stat().st_size,
                "filename": target.name,
                "onnx_sha256": onnx_sha256,
            },
            "export": {
                "dynamic_axes": ["batch"],
                "formula": RAFT_HEAD_FORMULA,
                "opset_version": RAFT_HEAD_ONNX_OPSET,
                "translation_post_matrix": [list(row) for row in sources.translation_post_matrix],
            },
            "io_contract": _io_contract(),
            "parity": parity.to_dict() if parity is not None else {"status": "not_run"},
            "record_type": RAFT_HEAD_ONNX_RECORD_TYPE,
            "schema_version": RAFT_HEAD_ONNX_SCHEMA_VERSION,
            "source_clamp": {
                "artifact_sha256": sources.clamp_sha256,
                "clamp_max_tensor_sha256": sources.clamp_max_tensor_sha256,
                "clamp_min_tensor_sha256": sources.clamp_min_tensor_sha256,
                "constant_feature_count": sources.constant_feature_count,
                "constant_mask_tensor_sha256": sources.constant_mask_tensor_sha256,
                "record_type": RAFT_HEAD_CLAMP_RECORD_TYPE,
                "rule": sources.clamp_rule,
                "schema_version": RAFT_HEAD_CLAMP_SCHEMA_VERSION,
                "source_cache_sha256": sources.source_cache_sha256,
                "train_sequence_ids": list(sources.train_sequence_ids),
            },
            "source_head": {
                "architecture": sources.architecture,
                "checkpoint_sha256": sources.head_sha256,
                "normalization_tensor_sha256": sources.normalization_tensor_sha256,
                "selected": sources.selected,
            },
        }
        manifest_bytes = _canonical_json_bytes(manifest)
        with tempfile.NamedTemporaryFile(
            prefix=f".{manifest_target.name}.",
            suffix=".tmp",
            dir=manifest_target.parent,
            delete=False,
        ) as handle:
            manifest_temporary = Path(handle.name)
            handle.write(manifest_bytes)
            handle.flush()
            os.fsync(handle.fileno())

        _require_new_path(target, field="RAFT head ONNX model destination")
        _require_new_path(manifest_target, field="RAFT head ONNX manifest destination")
        committed_model = _link_exclusive(
            model_temporary, target, field="RAFT head ONNX model destination"
        )
        committed_manifest = _link_exclusive(
            manifest_temporary,
            manifest_target,
            field="RAFT head ONNX manifest destination",
        )
        return ExportedRaftHeadOnnx(
            model_path=committed_model,
            manifest_path=committed_manifest,
            model_sha256=onnx_sha256,
            manifest_sha256=_sha256_file(committed_manifest, field="RAFT head ONNX manifest"),
            parity=parity,
        )
    except Exception:
        if committed_manifest is not None:
            committed_manifest.unlink(missing_ok=True)
        if committed_model is not None:
            committed_model.unlink(missing_ok=True)
        raise
    finally:
        if manifest_temporary is not None:
            manifest_temporary.unlink(missing_ok=True)
        if model_temporary is not None:
            model_temporary.unlink(missing_ok=True)


def _exact_manifest_mapping(
    value: object,
    fields: set[str],
    *,
    field: str,
) -> dict[str, object]:
    if type(value) is not dict or set(value) != fields:
        raise LearningError(f"{field} fields do not match the schema")
    return value


def _validate_parity_record(value: object) -> None:
    parity = _exact_manifest_mapping(
        value,
        {"status"}
        if type(value) is dict and value.get("status") == "not_run"
        else {
            "absolute_tolerance",
            "max_translation_abs_error",
            "provider",
            "relative_tolerance",
            "runs",
            "status",
        },
        field="RAFT head ONNX parity",
    )
    if parity["status"] == "not_run":
        return
    if parity["status"] != "passed" or parity["provider"] != "CPUExecutionProvider":
        raise LearningError("RAFT head ONNX parity status or provider is unsupported")
    absolute = _validate_tolerance(parity["absolute_tolerance"], field="parity.absolute_tolerance")
    relative = _validate_tolerance(parity["relative_tolerance"], field="parity.relative_tolerance")
    if absolute > RAFT_HEAD_PARITY_TOLERANCE or relative > RAFT_HEAD_PARITY_TOLERANCE:
        raise LearningError("RAFT head ONNX parity tolerances exceed the frozen 1e-5 gate")
    maximum = _validate_tolerance(
        parity["max_translation_abs_error"], field="parity.max_translation_abs_error"
    )
    runs = parity["runs"]
    if type(runs) is not list or len(runs) != 2:
        raise LearningError("RAFT head ONNX parity must contain batch-1 and batch-4 runs")
    observed_errors: list[float] = []
    for expected_index, expected_batch, value in zip((1, 2), (1, 4), runs, strict=True):
        run = _exact_manifest_mapping(
            value,
            {"batch_size", "run_index", "translation_max_abs_error"},
            field="RAFT head ONNX parity run",
        )
        if run["run_index"] != expected_index or run["batch_size"] != expected_batch:
            raise LearningError("RAFT head ONNX parity run ordering is unsupported")
        observed_errors.append(
            _validate_tolerance(
                run["translation_max_abs_error"],
                field=f"parity.runs[{expected_index - 1}].translation_max_abs_error",
            )
        )
    if maximum != max(observed_errors):
        raise LearningError("RAFT head ONNX parity maximum is inconsistent with its runs")
    if maximum > RAFT_HEAD_PARITY_TOLERANCE:
        raise LearningError("RAFT head ONNX parity error exceeds the frozen 1e-5 gate")


def verify_raft_head_onnx_manifest(
    manifest_path: os.PathLike[str] | str,
    *,
    model_path: os.PathLike[str] | str | None = None,
    head_checkpoint_path: os.PathLike[str] | str | None = None,
    clamp_artifact_path: os.PathLike[str] | str | None = None,
    require_passed_parity: bool = False,
    rerun_parity: bool = False,
) -> dict[str, object]:
    """Strictly verify the sidecar, ONNX bytes, and optional source bytes."""

    if type(require_passed_parity) is not bool or type(rerun_parity) is not bool:
        raise LearningError("require_passed_parity and rerun_parity must be boolean")
    if rerun_parity and not require_passed_parity:
        raise LearningError("rerun_parity requires require_passed_parity")
    source = Path(manifest_path)
    if source.is_symlink() or not source.is_file():
        raise LearningError(f"RAFT head ONNX manifest must be a regular file: {source}")
    try:
        raw_manifest = source.read_bytes()
        payload = json.loads(raw_manifest.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LearningError(f"cannot load RAFT head ONNX manifest {source}: {exc}") from exc
    expected_fields = {
        "artifact",
        "export",
        "io_contract",
        "parity",
        "record_type",
        "schema_version",
        "source_clamp",
        "source_head",
    }
    root = _exact_manifest_mapping(payload, expected_fields, field="RAFT head ONNX manifest")
    if raw_manifest != _canonical_json_bytes(root):
        raise LearningError("RAFT head ONNX manifest is not canonical JSON")
    if (
        root["record_type"] != RAFT_HEAD_ONNX_RECORD_TYPE
        or root["schema_version"] != RAFT_HEAD_ONNX_SCHEMA_VERSION
    ):
        raise LearningError("RAFT head ONNX manifest identity is unsupported")

    export = _exact_manifest_mapping(
        root["export"],
        {"dynamic_axes", "formula", "opset_version", "translation_post_matrix"},
        field="RAFT head ONNX export",
    )
    matrix = _translation_post_matrix(export["translation_post_matrix"])
    if export != {
        "dynamic_axes": ["batch"],
        "formula": RAFT_HEAD_FORMULA,
        "opset_version": RAFT_HEAD_ONNX_OPSET,
        "translation_post_matrix": [list(row) for row in matrix],
    }:
        raise LearningError("RAFT head ONNX export contract is unsupported")
    if root["io_contract"] != _io_contract():
        raise LearningError("RAFT head ONNX I/O contract is unsupported")
    _validate_parity_record(root["parity"])
    if require_passed_parity and root["parity"].get("status") != "passed":  # type: ignore[union-attr]
        raise LearningError("RAFT head ONNX package binding requires passed parity")

    artifact = _exact_manifest_mapping(
        root["artifact"],
        {"byte_size", "filename", "onnx_sha256"},
        field="RAFT head ONNX artifact",
    )
    filename = artifact["filename"]
    if type(filename) is not str or not filename or Path(filename).name != filename:
        raise LearningError("RAFT head ONNX artifact filename must be one plain filename")
    if type(artifact["byte_size"]) is not int or artifact["byte_size"] <= 0:
        raise LearningError("RAFT head ONNX artifact byte_size must be positive")
    expected_model_sha256 = _sha256_value(artifact["onnx_sha256"], field="artifact.onnx_sha256")
    model = Path(model_path) if model_path is not None else source.parent / filename
    observed_model_sha256 = _sha256_file(model, field="RAFT head ONNX artifact")
    if model.stat().st_size != artifact["byte_size"]:
        raise LearningError("RAFT head ONNX byte size does not match its manifest")
    if observed_model_sha256 != expected_model_sha256:
        raise LearningError("RAFT head ONNX SHA-256 does not match its manifest")

    source_head = _exact_manifest_mapping(
        root["source_head"],
        {"architecture", "checkpoint_sha256", "normalization_tensor_sha256", "selected"},
        field="RAFT head ONNX source_head",
    )
    if source_head["architecture"] != _ARCHITECTURE:
        raise LearningError("RAFT head ONNX source architecture is unsupported")
    selected = _json_mapping(source_head["selected"], field="source_head.selected")
    if not selected:
        raise LearningError("RAFT head ONNX source selected metadata must not be empty")
    normalization = _exact_manifest_mapping(
        source_head["normalization_tensor_sha256"],
        {"feature_mean", "feature_std", "target_mean", "target_std"},
        field="RAFT head ONNX normalization hashes",
    )
    for name, digest in normalization.items():
        _sha256_value(digest, field=f"source_head.normalization_tensor_sha256.{name}")
    expected_head_sha256 = _sha256_value(
        source_head["checkpoint_sha256"], field="source_head.checkpoint_sha256"
    )

    source_clamp = _exact_manifest_mapping(
        root["source_clamp"],
        {
            "artifact_sha256",
            "clamp_max_tensor_sha256",
            "clamp_min_tensor_sha256",
            "constant_feature_count",
            "constant_mask_tensor_sha256",
            "record_type",
            "rule",
            "schema_version",
            "source_cache_sha256",
            "train_sequence_ids",
        },
        field="RAFT head ONNX source_clamp",
    )
    if (
        source_clamp["record_type"] != RAFT_HEAD_CLAMP_RECORD_TYPE
        or source_clamp["schema_version"] != RAFT_HEAD_CLAMP_SCHEMA_VERSION
        or source_clamp["rule"] != RAFT_HEAD_CLAMP_RULE
    ):
        raise LearningError("RAFT head ONNX source clamp contract is unsupported")
    expected_clamp_sha256 = _sha256_value(
        source_clamp["artifact_sha256"], field="source_clamp.artifact_sha256"
    )
    for field in (
        "clamp_min_tensor_sha256",
        "clamp_max_tensor_sha256",
        "constant_mask_tensor_sha256",
        "source_cache_sha256",
    ):
        _sha256_value(source_clamp[field], field=f"source_clamp.{field}")
    count = source_clamp["constant_feature_count"]
    if type(count) is not int or not 0 <= count <= RAFT_HEAD_FEATURE_DIM:
        raise LearningError("RAFT head ONNX constant_feature_count is invalid")
    train_ids = source_clamp["train_sequence_ids"]
    if (
        type(train_ids) is not list
        or not train_ids
        or any(type(item) is not str or not item for item in train_ids)
        or len(train_ids) != len(set(train_ids))
    ):
        raise LearningError("RAFT head ONNX train_sequence_ids are invalid")

    if (head_checkpoint_path is None) != (clamp_artifact_path is None):
        raise LearningError(
            "head_checkpoint_path and clamp_artifact_path must be supplied together"
        )
    loaded: _LoadedRaftHeadSources | None = None
    if head_checkpoint_path is not None and clamp_artifact_path is not None:
        loaded = _load_frozen_sources(
            head_checkpoint_path,
            clamp_artifact_path,
            expected_head_sha256=expected_head_sha256,
            expected_clamp_sha256=expected_clamp_sha256,
            translation_post_matrix=matrix,
        )
        expected_source_head = {
            "architecture": loaded.architecture,
            "checkpoint_sha256": loaded.head_sha256,
            "normalization_tensor_sha256": loaded.normalization_tensor_sha256,
            "selected": loaded.selected,
        }
        expected_source_clamp = {
            "artifact_sha256": loaded.clamp_sha256,
            "clamp_max_tensor_sha256": loaded.clamp_max_tensor_sha256,
            "clamp_min_tensor_sha256": loaded.clamp_min_tensor_sha256,
            "constant_feature_count": loaded.constant_feature_count,
            "constant_mask_tensor_sha256": loaded.constant_mask_tensor_sha256,
            "record_type": RAFT_HEAD_CLAMP_RECORD_TYPE,
            "rule": loaded.clamp_rule,
            "schema_version": RAFT_HEAD_CLAMP_SCHEMA_VERSION,
            "source_cache_sha256": loaded.source_cache_sha256,
            "train_sequence_ids": list(loaded.train_sequence_ids),
        }
        if source_head != expected_source_head or source_clamp != expected_source_clamp:
            raise LearningError("RAFT head ONNX source records do not match source artifacts")
    _check_onnx_structure(
        model,
        source_head=source_head,
        source_clamp=source_clamp,
        translation_post_matrix=matrix,
    )
    if rerun_parity:
        if loaded is None:
            raise LearningError("rerun_parity requires both source artifacts")
        parity_record = root["parity"]
        assert isinstance(parity_record, dict)
        observed_parity = check_raft_head_onnx_parity(
            model,
            loaded.model,
            expected_onnx_sha256=expected_model_sha256,
            relative_tolerance=float(parity_record["relative_tolerance"]),
            absolute_tolerance=float(parity_record["absolute_tolerance"]),
        )
        if observed_parity.max_translation_abs_error > RAFT_HEAD_PARITY_TOLERANCE:
            raise LearningError("fresh RAFT head ONNX parity exceeds the frozen 1e-5 gate")
    return root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-export-raft-head-onnx",
        description="Export the frozen clamped 831-feature RAFT translation head to ONNX.",
    )
    parser.add_argument("--head-checkpoint", required=True)
    parser.add_argument("--expected-head-sha256", required=True)
    parser.add_argument("--clamp-artifact", required=True)
    parser.add_argument("--expected-clamp-sha256", required=True)
    parser.add_argument("--output", required=True, help="new .onnx destination")
    parser.add_argument("--manifest", required=True, help="new JSON sidecar destination")
    parser.add_argument(
        "--translation-post-matrix",
        type=float,
        nargs=9,
        metavar=("M00", "M01", "M02", "M10", "M11", "M12", "M20", "M21", "M22"),
        help="row-major 3x3 matrix embedded after head decoding; default is identity",
    )
    parser.add_argument("--parity-rtol", type=float, default=1e-5)
    parser.add_argument("--parity-atol", type=float, default=1e-5)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = export_raft_head_onnx(
            args.head_checkpoint,
            args.clamp_artifact,
            args.output,
            args.manifest,
            expected_head_sha256=args.expected_head_sha256,
            expected_clamp_sha256=args.expected_clamp_sha256,
            parity_relative_tolerance=args.parity_rtol,
            parity_absolute_tolerance=args.parity_atol,
            translation_post_matrix=args.translation_post_matrix,
        )
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "event": "raft_head_onnx_export_failed",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "raft_head_onnx_export_complete",
                "manifest": str(result.manifest_path),
                "manifest_sha256": result.manifest_sha256,
                "model": str(result.model_path),
                "model_sha256": result.model_sha256,
                "parity": result.parity.to_dict() if result.parity is not None else None,
            },
            sort_keys=True,
            allow_nan=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "RAFT_HEAD_FEATURE_DIM",
    "RAFT_HEAD_FORMULA",
    "RAFT_HEAD_INPUT_NAMES",
    "RAFT_HEAD_ONNX_OPSET",
    "RAFT_HEAD_ONNX_RECORD_TYPE",
    "RAFT_HEAD_ONNX_SCHEMA_VERSION",
    "RAFT_HEAD_OUTPUT_NAMES",
    "ExportedRaftHeadOnnx",
    "RaftHeadParityResult",
    "RaftHeadParityRun",
    "build_parser",
    "check_raft_head_onnx_parity",
    "export_raft_head_onnx",
    "main",
    "verify_raft_head_onnx_manifest",
]

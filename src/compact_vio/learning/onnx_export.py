"""ONNX export and recurrent-state parity for :class:`CompactVIO`.

The module deliberately imports PyTorch, ONNX, and ONNX Runtime only inside
the operations that need them.  This keeps the base package and ``--help``
usable when the optional model/export stack is not installed.

The exported graph represents exactly one causal frame-pair step.  It accepts
an explicit fusion state and returns the next state, so a caller can either
carry state across contiguous pairs or reset it to zero for independent-pair
inference.  Padded IMU windows are supported through ``imu_lengths``; padded
samples after the declared length do not influence either output.
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
    from compact_vio.learning.model import CompactVIO


ONNX_EXPORT_RECORD_TYPE = "compact_vio_onnx_export"
ONNX_EXPORT_SCHEMA_VERSION = "1.0.0"
ONNX_RUNTIME_POLICY_ID = "caller-managed-explicit-fusion-state/v1"
ONNX_MOTION_LAYOUT_ID = "translation-meters-xyz/rotation-vector-radians-xyz/v1"
DEFAULT_ONNX_OPSET = 17
ONNX_INPUT_NAMES = (
    "frame_pairs",
    "imu",
    "imu_lengths",
    "delta_time_s",
    "fusion_state_in",
)
ONNX_OUTPUT_NAMES = ("motion_vector", "fusion_state_out")
_READ_CHUNK_BYTES = 8 * 1024 * 1024
_SHA256_HEX_LENGTH = 64


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
        raise LearningError(f"ONNX manifest is not canonical JSON data: {exc}") from exc


def _require_regular_parent(path: Path, *, field: str) -> None:
    parent = path.parent
    if parent.is_symlink() or not parent.is_dir():
        raise LearningError(f"{field} parent must be a regular directory: {parent}")


def _require_new_path(path: Path, *, field: str) -> None:
    if path.is_symlink() or path.exists():
        raise LearningError(f"refusing to overwrite {field}: {path}")
    _require_regular_parent(path, field=field)


def _link_exclusive(source: Path, destination: Path, *, field: str) -> Path:
    """Commit a temporary regular file without replacing an existing path."""

    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise LearningError(f"refusing to overwrite {field}: {destination}") from exc
    except OSError as exc:
        raise LearningError(f"cannot commit {field} {destination}: {exc}") from exc
    return destination.resolve(strict=True)


@dataclass(frozen=True, slots=True)
class OnnxParityRun:
    """Maximum absolute errors from one recurrent ONNX Runtime invocation."""

    run_index: int
    motion_max_abs_error: float
    fusion_state_max_abs_error: float


@dataclass(frozen=True, slots=True)
class OnnxParityResult:
    """Two-step PyTorch-versus-ONNX Runtime numerical comparison."""

    provider: str
    absolute_tolerance: float
    relative_tolerance: float
    runs: tuple[OnnxParityRun, ...]

    @property
    def max_motion_abs_error(self) -> float:
        return max(run.motion_max_abs_error for run in self.runs)

    @property
    def max_fusion_state_abs_error(self) -> float:
        return max(run.fusion_state_max_abs_error for run in self.runs)

    def to_dict(self) -> dict[str, object]:
        return {
            "absolute_tolerance": self.absolute_tolerance,
            "max_fusion_state_abs_error": self.max_fusion_state_abs_error,
            "max_motion_abs_error": self.max_motion_abs_error,
            "provider": self.provider,
            "relative_tolerance": self.relative_tolerance,
            "runs": [asdict(run) for run in self.runs],
            "status": "passed",
        }


@dataclass(frozen=True, slots=True)
class ExportedOnnxModel:
    """Paths, hashes, and parity evidence for one completed ONNX export."""

    model_path: Path
    manifest_path: Path
    model_sha256: str
    manifest_sha256: str
    parity: OnnxParityResult | None


def _create_export_adapter(model: CompactVIO) -> object:
    """Create a validation-free graph adapter with explicit recurrent state.

    ``CompactVIO`` uses ``pack_padded_sequence`` in its eager path.  ONNX does
    not need that Python-side packing: running the GRU over the padded tensor
    and gathering the output at ``imu_lengths - 1`` is mathematically
    identical, because only later padded samples are ignored.  The gathered
    implementation is dynamic in both batch size and padded IMU length.
    """

    try:
        import torch
        from torch import nn
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for ONNX export; install the training extra"
        ) from exc

    class _CompactVIOOnnxStep(nn.Module):
        def __init__(self, source: CompactVIO) -> None:
            super().__init__()
            self.visual_encoder = source.visual_encoder
            self.imu_encoder = source.imu_encoder
            self.fusion_projection = source.fusion_projection
            self.fusion_recurrence = source.fusion_recurrence
            self.motion_head = source.motion_head
            self.imu_hidden_dim = source.config.imu_hidden_dim
            self.fusion_hidden_dim = source.config.fusion_hidden_dim
            self.rotation_state_source = source.config.rotation_state_source

        def _fusion_step(self, fused: object, previous_state: object) -> object:
            """Apply GRUCell with fixed slices that the legacy exporter supports.

            Calling ``nn.GRUCell`` directly lowers through ``unsafe_chunk``;
            that operator cannot retain a dynamic batch dimension in the
            Torch 2.7 legacy exporter.  These equations are PyTorch's exact
            reset/update/new gate equations with the same parameters and gate
            order, expressed as statically bounded slices.
            """

            input_gates = torch.nn.functional.linear(
                fused,
                self.fusion_recurrence.weight_ih,
                self.fusion_recurrence.bias_ih,
            )
            hidden_gates = torch.nn.functional.linear(
                previous_state,
                self.fusion_recurrence.weight_hh,
                self.fusion_recurrence.bias_hh,
            )
            hidden = self.fusion_hidden_dim
            reset = torch.sigmoid(input_gates[:, :hidden] + hidden_gates[:, :hidden])
            update = torch.sigmoid(
                input_gates[:, hidden : 2 * hidden] + hidden_gates[:, hidden : 2 * hidden]
            )
            candidate = torch.tanh(
                input_gates[:, 2 * hidden :] + reset * hidden_gates[:, 2 * hidden :]
            )
            return candidate + update * (previous_state - candidate)

        def forward(
            self,
            frame_pairs: object,
            imu: object,
            imu_lengths: object,
            delta_time_s: object,
            fusion_state_in: object,
        ) -> tuple[object, object]:
            visual_features = self.visual_encoder(frame_pairs)
            imu_outputs, _ = self.imu_encoder(imu)
            gather_index = (imu_lengths.to(dtype=torch.int64) - 1).reshape(-1, 1, 1)
            gather_index = gather_index.expand(-1, 1, self.imu_hidden_dim)
            imu_hidden = torch.gather(imu_outputs, dim=1, index=gather_index).squeeze(1)
            fused = self.fusion_projection(
                torch.cat((visual_features, imu_hidden, delta_time_s), dim=-1)
            )
            fusion_state_out = self._fusion_step(fused, fusion_state_in)
            recurrent_motion = self.motion_head(fusion_state_out)
            if self.rotation_state_source == "shared-recurrent-fusion-state/v1":
                motion = recurrent_motion
            else:
                current_pair_state = self._fusion_step(fused, torch.zeros_like(fusion_state_out))
                current_pair_motion = self.motion_head(current_pair_state)
                motion = torch.cat(
                    (recurrent_motion[:, :3], current_pair_motion[:, 3:]),
                    dim=-1,
                )
            return motion, fusion_state_out

    return _CompactVIOOnnxStep(model).eval()


def _validate_torch_inputs(
    model: CompactVIO,
    frame_pairs: object,
    imu: object,
    imu_lengths: object,
    delta_time_s: object,
    fusion_state: object,
) -> None:
    try:
        import torch
        from torch import Tensor
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for ONNX parity; install the training extra"
        ) from exc

    tensors = (frame_pairs, imu, imu_lengths, delta_time_s, fusion_state)
    if not all(isinstance(value, Tensor) for value in tensors):
        raise LearningError("ONNX inputs must be PyTorch tensors")
    if any(value.device.type != "cpu" for value in tensors):
        raise LearningError("ONNX export/parity inputs must be CPU tensors")
    batch_size = frame_pairs.shape[0] if frame_pairs.ndim else 0
    config = model.config
    if (
        frame_pairs.shape
        != (
            batch_size,
            2,
            config.image_height_px,
            config.image_width_px,
        )
        or batch_size <= 0
    ):
        raise LearningError("frame_pairs do not match [batch, 2, configured height, width]")
    if imu.ndim != 3 or imu.shape[0] != batch_size or imu.shape[1] <= 0 or imu.shape[2] != 6:
        raise LearningError("imu must have shape [batch, positive padded samples, 6]")
    if imu_lengths.shape != (batch_size,) or imu_lengths.dtype != torch.int64:
        raise LearningError("imu_lengths must be int64 with shape [batch]")
    if delta_time_s.shape != (batch_size, 1):
        raise LearningError("delta_time_s must have shape [batch, 1]")
    if fusion_state.shape != (batch_size, config.fusion_hidden_dim):
        raise LearningError("fusion_state must have shape [batch, fusion_hidden_dim]")
    for name, tensor in (
        ("frame_pairs", frame_pairs),
        ("imu", imu),
        ("delta_time_s", delta_time_s),
        ("fusion_state", fusion_state),
    ):
        if tensor.dtype != torch.float32:
            raise LearningError(f"{name} must use float32")
        if not torch.isfinite(tensor).all():
            raise LearningError(f"{name} must contain only finite values")
    if torch.any(imu_lengths <= 0) or torch.any(imu_lengths > imu.shape[1]):
        raise LearningError("each imu length must be in [1, padded samples]")
    if torch.any(delta_time_s <= 0):
        raise LearningError("delta_time_s must contain positive values")


def _synthetic_inputs(
    model: CompactVIO,
    *,
    batch_size: int,
    padded_imu_samples: int,
    seed: int,
) -> tuple[object, object, object, object, object]:
    if type(batch_size) is not int or batch_size <= 0:
        raise LearningError("batch_size must be a positive integer")
    if type(padded_imu_samples) is not int or padded_imu_samples <= 0:
        raise LearningError("padded_imu_samples must be a positive integer")
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for ONNX export; install the training extra"
        ) from exc

    generator = torch.Generator(device="cpu")
    generator.manual_seed(seed)
    config = model.config
    frame_pairs = torch.randn(
        batch_size,
        2,
        config.image_height_px,
        config.image_width_px,
        generator=generator,
        dtype=torch.float32,
    )
    imu = torch.randn(
        batch_size,
        padded_imu_samples,
        6,
        generator=generator,
        dtype=torch.float32,
    )
    lengths = [max(1, padded_imu_samples - index) for index in range(batch_size)]
    imu_lengths = torch.tensor(lengths, dtype=torch.int64)
    delta_time_s = torch.full((batch_size, 1), 0.05, dtype=torch.float32)
    fusion_state = torch.randn(
        batch_size,
        config.fusion_hidden_dim,
        generator=generator,
        dtype=torch.float32,
    )
    return frame_pairs, imu, imu_lengths, delta_time_s, fusion_state


def _assert_numpy_close(
    expected: object,
    actual: object,
    *,
    field: str,
    run_index: int,
    relative_tolerance: float,
    absolute_tolerance: float,
) -> float:
    try:
        import numpy as np
    except ImportError as exc:  # pragma: no cover - ONNX Runtime depends on NumPy
        raise LearningDependencyError("NumPy is required for ONNX parity checking") from exc

    expected_array = np.asarray(expected)
    actual_array = np.asarray(actual)
    if actual_array.shape != expected_array.shape:
        raise LearningError(
            f"ONNX parity run {run_index} {field} shape mismatch: "
            f"expected {expected_array.shape}, got {actual_array.shape}"
        )
    if actual_array.dtype != expected_array.dtype:
        raise LearningError(
            f"ONNX parity run {run_index} {field} dtype mismatch: "
            f"expected {expected_array.dtype}, got {actual_array.dtype}"
        )
    if not np.isfinite(actual_array).all():
        raise LearningError(f"ONNX parity run {run_index} {field} contains non-finite values")
    difference = np.abs(actual_array - expected_array)
    maximum = float(difference.max(initial=0.0))
    if not np.allclose(
        actual_array,
        expected_array,
        rtol=relative_tolerance,
        atol=absolute_tolerance,
        equal_nan=False,
    ):
        raise LearningError(
            f"ONNX parity run {run_index} {field} failed: max absolute error {maximum:.9g}, "
            f"rtol {relative_tolerance:.9g}, atol {absolute_tolerance:.9g}"
        )
    return maximum


def check_onnx_parity(
    onnx_path: os.PathLike[str] | str,
    model: CompactVIO,
    *,
    expected_onnx_sha256: str | None = None,
    batch_size: int = 2,
    padded_imu_samples: int = 7,
    relative_tolerance: float = 1e-5,
    absolute_tolerance: float = 1e-5,
) -> OnnxParityResult:
    """Require two-step CPU ONNX Runtime parity for motion and carried state."""

    if (
        type(relative_tolerance) not in (int, float)
        or not math.isfinite(float(relative_tolerance))
        or relative_tolerance < 0
        or type(absolute_tolerance) not in (int, float)
        or not math.isfinite(float(absolute_tolerance))
        or absolute_tolerance < 0
    ):
        raise LearningError("ONNX parity tolerances must be finite and non-negative")
    # Disable optional runtime telemetry before importing ONNX Runtime.  Apart
    # from avoiding network-side behavior, this prevents the macOS runtime
    # from creating an unrelated session-identity file in the working tree.
    os.environ.setdefault("ORT_DISABLE_TELEMETRY", "1")
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise LearningDependencyError(
            "ONNX Runtime is required for parity checking; install the ONNX export extra"
        ) from exc
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for ONNX parity; install the training extra"
        ) from exc

    source = Path(onnx_path)
    observed_sha256 = _sha256_file(source, field="ONNX model")
    if expected_onnx_sha256 is not None:
        expected_sha256 = _sha256_value(expected_onnx_sha256, field="expected_onnx_sha256")
        if observed_sha256 != expected_sha256:
            raise LearningError(
                f"ONNX SHA-256 mismatch: expected {expected_sha256}, got {observed_sha256}"
            )
    try:
        session = ort.InferenceSession(str(source), providers=["CPUExecutionProvider"])
    except Exception as exc:  # ORT exposes runtime-specific exception types
        raise LearningError(f"cannot load ONNX model in ONNX Runtime: {exc}") from exc
    if tuple(item.name for item in session.get_inputs()) != ONNX_INPUT_NAMES:
        raise LearningError("ONNX Runtime input names do not match the CompactVIO contract")
    if tuple(item.name for item in session.get_outputs()) != ONNX_OUTPUT_NAMES:
        raise LearningError("ONNX Runtime output names do not match the CompactVIO contract")

    adapter = _create_export_adapter(model)
    model.to(device="cpu")
    model.eval()
    adapter.eval()
    pytorch_state = None
    runtime_state = None
    runs: list[OnnxParityRun] = []
    for run_index in (1, 2):
        inputs = _synthetic_inputs(
            model,
            batch_size=batch_size,
            padded_imu_samples=padded_imu_samples + run_index - 1,
            seed=41_000 + run_index,
        )
        frame_pairs, imu, imu_lengths, delta_time_s, generated_state = inputs
        if pytorch_state is None:
            pytorch_state = generated_state
            runtime_state = generated_state.detach().numpy()
        _validate_torch_inputs(
            model,
            frame_pairs,
            imu,
            imu_lengths,
            delta_time_s,
            pytorch_state,
        )
        with torch.inference_mode():
            expected_motion, expected_state = adapter(
                frame_pairs,
                imu,
                imu_lengths,
                delta_time_s,
                pytorch_state,
            )
        feed = {
            "frame_pairs": frame_pairs.detach().numpy(),
            "imu": imu.detach().numpy(),
            "imu_lengths": imu_lengths.detach().numpy(),
            "delta_time_s": delta_time_s.detach().numpy(),
            "fusion_state_in": runtime_state,
        }
        try:
            actual_motion, actual_state = session.run(list(ONNX_OUTPUT_NAMES), feed)
        except Exception as exc:  # ORT exposes runtime-specific exception types
            raise LearningError(f"ONNX Runtime parity run {run_index} failed: {exc}") from exc
        motion_error = _assert_numpy_close(
            expected_motion.detach().numpy(),
            actual_motion,
            field="motion_vector",
            run_index=run_index,
            relative_tolerance=float(relative_tolerance),
            absolute_tolerance=float(absolute_tolerance),
        )
        state_error = _assert_numpy_close(
            expected_state.detach().numpy(),
            actual_state,
            field="fusion_state_out",
            run_index=run_index,
            relative_tolerance=float(relative_tolerance),
            absolute_tolerance=float(absolute_tolerance),
        )
        runs.append(
            OnnxParityRun(
                run_index=run_index,
                motion_max_abs_error=motion_error,
                fusion_state_max_abs_error=state_error,
            )
        )
        pytorch_state = expected_state.detach()
        runtime_state = actual_state

    if _sha256_file(source, field="ONNX model") != observed_sha256:
        raise LearningError("ONNX model changed while parity was being checked")
    return OnnxParityResult(
        provider="CPUExecutionProvider",
        absolute_tolerance=float(absolute_tolerance),
        relative_tolerance=float(relative_tolerance),
        runs=tuple(runs),
    )


def _export_graph(
    model: CompactVIO,
    destination: Path,
    *,
    opset_version: int,
    sample_imu_samples: int,
) -> None:
    try:
        import torch
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for ONNX export; install the training extra"
        ) from exc
    try:
        import onnx  # noqa: F401 - exporter dependency preflight
    except ImportError as exc:
        raise LearningDependencyError(
            "ONNX is required for export; install the ONNX export extra"
        ) from exc

    model.to(device="cpu")
    model.eval()
    adapter = _create_export_adapter(model)
    sample = _synthetic_inputs(
        model,
        batch_size=1,
        padded_imu_samples=sample_imu_samples,
        seed=31_337,
    )
    _validate_torch_inputs(model, *sample)
    dynamic_axes = {
        "frame_pairs": {0: "batch"},
        "imu": {0: "batch", 1: "imu_samples"},
        "imu_lengths": {0: "batch"},
        "delta_time_s": {0: "batch"},
        "fusion_state_in": {0: "batch"},
        "motion_vector": {0: "batch"},
        "fusion_state_out": {0: "batch"},
    }
    try:
        torch.onnx.export(
            adapter,
            sample,
            str(destination),
            export_params=True,
            opset_version=opset_version,
            do_constant_folding=True,
            input_names=list(ONNX_INPUT_NAMES),
            output_names=list(ONNX_OUTPUT_NAMES),
            dynamic_axes=dynamic_axes,
            dynamo=False,
        )
    except Exception as exc:
        raise LearningError(f"cannot export CompactVIO ONNX graph: {exc}") from exc


def _annotate_and_check_onnx(
    path: Path,
    *,
    source_checkpoint_sha256: str,
    model: CompactVIO,
    training_config: object,
    opset_version: int,
) -> None:
    try:
        import onnx
    except ImportError as exc:
        raise LearningDependencyError(
            "ONNX is required for export validation; install the ONNX export extra"
        ) from exc
    metadata = {
        "compact_vio.export_schema_version": ONNX_EXPORT_SCHEMA_VERSION,
        "compact_vio.input_data_config_json": json.dumps(
            asdict(training_config.data), sort_keys=True, separators=(",", ":")
        ),
        "compact_vio.model_config_json": json.dumps(
            asdict(model.config), sort_keys=True, separators=(",", ":")
        ),
        "compact_vio.motion_layout_id": ONNX_MOTION_LAYOUT_ID,
        "compact_vio.opset_version": str(opset_version),
        "compact_vio.runtime_policy_id": ONNX_RUNTIME_POLICY_ID,
        "compact_vio.source_checkpoint_sha256": source_checkpoint_sha256,
    }
    try:
        graph = onnx.load_model(path)
        onnx.helper.set_model_props(graph, metadata)
        onnx.checker.check_model(graph, full_check=True)
        onnx.save_model(graph, path)
        onnx.checker.check_model(onnx.load_model(path), full_check=True)
    except Exception as exc:
        raise LearningError(f"exported ONNX graph validation failed: {exc}") from exc


def _source_record_details(path: Path) -> dict[str, object]:
    """Return bounded source-format details without trusting arbitrary pickle."""

    try:
        import torch
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for ONNX export; install the training extra"
        ) from exc
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise LearningError(f"cannot inspect ONNX source checkpoint: {exc}") from exc
    if type(payload) is not dict:
        raise LearningError("ONNX source checkpoint payload must be an object")
    if payload.get("record_type") == "compact_vio_inference_checkpoint":
        metadata = payload.get("metadata")
        runtime = metadata.get("runtime") if type(metadata) is dict else None
        policy = runtime.get("inference_policy_id") if type(runtime) is dict else None
        return {
            "record_type": "compact_vio_inference_checkpoint",
            "schema_version": str(payload.get("schema_version")),
            "source_inference_policy_id": policy,
        }
    if payload.get("schema_version") == 1 and "optimizer_state_dict" in payload:
        return {
            "record_type": "compact_vio_training_checkpoint",
            "schema_version": "1",
            "source_inference_policy_id": None,
        }
    raise LearningError("ONNX source checkpoint record type is unsupported")


def _io_contract(model: CompactVIO) -> dict[str, object]:
    config = model.config
    return {
        "inputs": [
            {
                "dtype": "float32",
                "name": "frame_pairs",
                "shape": ["batch", 2, config.image_height_px, config.image_width_px],
            },
            {
                "dtype": "float32",
                "name": "imu",
                "padding": "right padding ignored after imu_lengths",
                "shape": ["batch", "imu_samples", 6],
            },
            {"dtype": "int64", "name": "imu_lengths", "shape": ["batch"]},
            {"dtype": "float32", "name": "delta_time_s", "shape": ["batch", 1]},
            {
                "dtype": "float32",
                "name": "fusion_state_in",
                "shape": ["batch", config.fusion_hidden_dim],
            },
        ],
        "outputs": [
            {
                "dtype": "float32",
                "layout_id": ONNX_MOTION_LAYOUT_ID,
                "name": "motion_vector",
                "shape": ["batch", 6],
            },
            {
                "dtype": "float32",
                "name": "fusion_state_out",
                "shape": ["batch", config.fusion_hidden_dim],
            },
        ],
    }


def export_onnx_checkpoint(
    source_checkpoint: os.PathLike[str] | str,
    destination: os.PathLike[str] | str,
    manifest_destination: os.PathLike[str] | str,
    *,
    expected_source_sha256: str,
    expected_inference_policy_id: str | None = None,
    opset_version: int = DEFAULT_ONNX_OPSET,
    sample_imu_samples: int = 10,
    verify_parity: bool = True,
    parity_relative_tolerance: float = 1e-5,
    parity_absolute_tolerance: float = 1e-5,
) -> ExportedOnnxModel:
    """Export a selected checkpoint, validate it, and commit model + manifest.

    Both destinations must be new paths.  The source SHA-256 is mandatory and
    checked before and after load.  When ``verify_parity`` is true (the release
    default), no artifact is committed unless ONNX Runtime passes two
    recurrent invocations for both the six-value motion output and carried
    fusion state.
    """

    source = Path(source_checkpoint)
    target = Path(destination)
    manifest_target = Path(manifest_destination)
    expected_digest = _sha256_value(expected_source_sha256, field="expected_source_sha256")
    if type(opset_version) is not int or opset_version < 17:
        raise LearningError("opset_version must be an integer greater than or equal to 17")
    if type(sample_imu_samples) is not int or sample_imu_samples <= 0:
        raise LearningError("sample_imu_samples must be a positive integer")
    if type(verify_parity) is not bool:
        raise LearningError("verify_parity must be boolean")
    if target == manifest_target:
        raise LearningError("ONNX model and manifest destinations must be different")
    _require_new_path(target, field="ONNX model destination")
    _require_new_path(manifest_target, field="ONNX manifest destination")
    source_digest = _sha256_file(source, field="source checkpoint")
    if source_digest != expected_digest:
        raise LearningError(
            f"source checkpoint SHA-256 mismatch: expected {expected_digest}, got {source_digest}"
        )

    try:
        from compact_vio.learning.inference import load_inference_model
    except ImportError as exc:  # pragma: no cover - dependency-light install
        raise LearningDependencyError(
            "PyTorch is required for ONNX export; install the training extra"
        ) from exc
    model, loaded = load_inference_model(
        source,
        device="cpu",
        expected_inference_policy_id=expected_inference_policy_id,
        expected_checkpoint_sha256=expected_digest,
    )
    if _sha256_file(source, field="source checkpoint") != source_digest:
        raise LearningError("source checkpoint changed while it was being loaded")
    source_details = _source_record_details(source)

    model_temporary: Path | None = None
    manifest_temporary: Path | None = None
    committed_model: Path | None = None
    committed_manifest: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.name}.",
            suffix=".onnx",
            dir=target.parent,
            delete=False,
        ) as handle:
            model_temporary = Path(handle.name)
        _export_graph(
            model,
            model_temporary,
            opset_version=opset_version,
            sample_imu_samples=sample_imu_samples,
        )
        _annotate_and_check_onnx(
            model_temporary,
            source_checkpoint_sha256=source_digest,
            model=model,
            training_config=loaded.config,
            opset_version=opset_version,
        )
        onnx_sha256 = _sha256_file(model_temporary, field="temporary ONNX model")
        parity = (
            check_onnx_parity(
                model_temporary,
                model,
                expected_onnx_sha256=onnx_sha256,
                padded_imu_samples=max(sample_imu_samples + 2, 3),
                relative_tolerance=parity_relative_tolerance,
                absolute_tolerance=parity_absolute_tolerance,
            )
            if verify_parity
            else None
        )
        provenance = loaded.provenance
        manifest: dict[str, object] = {
            "artifact": {
                "byte_size": model_temporary.stat().st_size,
                "filename": target.name,
                "onnx_sha256": onnx_sha256,
            },
            "export": {
                "dynamic_axes": ["batch", "imu_samples"],
                "opset_version": opset_version,
                "runtime_policy_id": ONNX_RUNTIME_POLICY_ID,
            },
            "io_contract": _io_contract(model),
            "model_config": asdict(model.config),
            "parity": parity.to_dict() if parity is not None else {"status": "not_run"},
            "preprocessing": asdict(loaded.config.data),
            "provenance": {
                "dataset_id": provenance.dataset_id,
                "split_id": provenance.split_id,
                "train_sequence_ids": list(provenance.train_sequence_ids),
                "validation_sequence_ids": list(provenance.validation_sequence_ids),
            },
            "record_type": ONNX_EXPORT_RECORD_TYPE,
            "schema_version": ONNX_EXPORT_SCHEMA_VERSION,
            "source_checkpoint": {
                **source_details,
                "selected_epoch": loaded.epoch,
                "selected_metrics": dict(sorted(loaded.metrics.items())),
                "sha256": source_digest,
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

        # Repeat both destination checks immediately before commit.  Hard-link
        # creation remains the authoritative no-overwrite operation under race.
        _require_new_path(target, field="ONNX model destination")
        _require_new_path(manifest_target, field="ONNX manifest destination")
        committed_model = _link_exclusive(
            model_temporary,
            target,
            field="ONNX model destination",
        )
        committed_manifest = _link_exclusive(
            manifest_temporary,
            manifest_target,
            field="ONNX manifest destination",
        )
        return ExportedOnnxModel(
            model_path=committed_model,
            manifest_path=committed_manifest,
            model_sha256=onnx_sha256,
            manifest_sha256=_sha256_file(committed_manifest, field="ONNX manifest"),
            parity=parity,
        )
    except Exception:
        # These paths were created only by this invocation.  Removing them on
        # a partial two-file commit cannot delete a pre-existing user artifact.
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


def verify_onnx_manifest(
    manifest_path: os.PathLike[str] | str,
    *,
    model_path: os.PathLike[str] | str | None = None,
) -> dict[str, object]:
    """Load the sidecar and verify its exact artifact hash and byte count."""

    source = Path(manifest_path)
    if source.is_symlink() or not source.is_file():
        raise LearningError(f"ONNX manifest must be a regular non-symlink file: {source}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LearningError(f"cannot load ONNX manifest {source}: {exc}") from exc
    if type(payload) is not dict:
        raise LearningError("ONNX manifest must contain one JSON object")
    expected_fields = {
        "artifact",
        "export",
        "io_contract",
        "model_config",
        "parity",
        "preprocessing",
        "provenance",
        "record_type",
        "schema_version",
        "source_checkpoint",
    }
    if set(payload) != expected_fields:
        raise LearningError("ONNX manifest fields do not match the supported schema")
    if (
        payload["record_type"] != ONNX_EXPORT_RECORD_TYPE
        or payload["schema_version"] != ONNX_EXPORT_SCHEMA_VERSION
    ):
        raise LearningError("ONNX manifest record type or schema is unsupported")
    artifact = payload["artifact"]
    if type(artifact) is not dict or set(artifact) != {"byte_size", "filename", "onnx_sha256"}:
        raise LearningError("ONNX manifest artifact record is invalid")
    filename = artifact["filename"]
    if type(filename) is not str or not filename or Path(filename).name != filename:
        raise LearningError("ONNX manifest artifact filename must be one plain filename")
    expected_size = artifact["byte_size"]
    if type(expected_size) is not int or expected_size <= 0:
        raise LearningError("ONNX manifest artifact byte_size must be positive")
    expected_sha256 = _sha256_value(artifact["onnx_sha256"], field="artifact.onnx_sha256")
    model = Path(model_path) if model_path is not None else source.parent / filename
    if model.stat().st_size != expected_size:
        raise LearningError("ONNX artifact byte size does not match its manifest")
    observed_sha256 = _sha256_file(model, field="ONNX artifact")
    if observed_sha256 != expected_sha256:
        raise LearningError(
            f"ONNX artifact SHA-256 mismatch: expected {expected_sha256}, got {observed_sha256}"
        )
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-export-onnx",
        description="Export one selected CompactVIO checkpoint to checked, stateful ONNX.",
    )
    parser.add_argument("--source-checkpoint", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--output", required=True, help="new .onnx destination")
    parser.add_argument("--manifest", required=True, help="new JSON sidecar destination")
    parser.add_argument("--expected-inference-policy")
    parser.add_argument("--opset", type=int, default=DEFAULT_ONNX_OPSET)
    parser.add_argument("--sample-imu-samples", type=int, default=10)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = export_onnx_checkpoint(
            args.source_checkpoint,
            args.output,
            args.manifest,
            expected_source_sha256=args.expected_source_sha256,
            expected_inference_policy_id=args.expected_inference_policy,
            opset_version=args.opset,
            sample_imu_samples=args.sample_imu_samples,
        )
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "event": "onnx_export_failed",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "event": "onnx_export_complete",
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
    "DEFAULT_ONNX_OPSET",
    "ONNX_EXPORT_RECORD_TYPE",
    "ONNX_EXPORT_SCHEMA_VERSION",
    "ONNX_INPUT_NAMES",
    "ONNX_MOTION_LAYOUT_ID",
    "ONNX_OUTPUT_NAMES",
    "ONNX_RUNTIME_POLICY_ID",
    "ExportedOnnxModel",
    "OnnxParityResult",
    "OnnxParityRun",
    "build_parser",
    "check_onnx_parity",
    "export_onnx_checkpoint",
    "main",
    "verify_onnx_manifest",
]

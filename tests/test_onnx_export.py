from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from compact_vio.learning.errors import LearningError

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

ONNX_STACK_AVAILABLE = bool(
    importlib.util.find_spec("onnx") and importlib.util.find_spec("onnxruntime")
)

if TORCH_AVAILABLE:
    from compact_vio.learning.checkpoint import CheckpointProvenance, save_checkpoint
    from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
    from compact_vio.learning.inference_checkpoint import STATEFUL_INFERENCE_POLICY_ID
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.onnx_export import (
        ONNX_INPUT_NAMES,
        ONNX_OUTPUT_NAMES,
        OnnxParityResult,
        OnnxParityRun,
        _create_export_adapter,
        _synthetic_inputs,
        export_onnx_checkpoint,
        verify_onnx_manifest,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OnnxExportDependencyLightTests(unittest.TestCase):
    def test_help_does_not_import_optional_model_or_onnx_stacks(self) -> None:
        original_import = builtins.__import__

        def reject_optional(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            if name.split(".", 1)[0] in {"torch", "onnx", "onnxruntime"}:
                raise AssertionError("--help must not import optional model/export dependencies")
            return original_import(name, globals, locals, fromlist, level)

        module_name = "compact_vio.learning.onnx_export"
        original_module = sys.modules.pop(module_name, None)
        builtins.__import__ = reject_optional
        try:
            from compact_vio.learning.onnx_export import main

            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                main(["--help"])
        finally:
            builtins.__import__ = original_import
            sys.modules.pop(module_name, None)
            if original_module is not None:
                sys.modules[module_name] = original_module
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--expected-source-sha256", output.getvalue())


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class OnnxExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model_config = ModelConfig(
            image_height_px=32,
            image_width_px=48,
            visual_feature_dim=24,
            imu_hidden_dim=12,
            fusion_hidden_dim=24,
            dropout_probability=0.0,
        )
        self.training_config = TrainingConfig(
            model=self.model_config,
            data=DataConfig(
                image_mean=0.45,
                image_std=0.2,
                gyroscope_scale_rad_s=4.0,
                accelerometer_scale_m_s2=18.0,
            ),
            batch_size=2,
            epochs=1,
            num_workers=0,
            use_amp=False,
        )
        self.provenance = CheckpointProvenance.create(
            dataset_id="synthetic-onnx",
            split_id="synthetic-onnx-split",
            train_sequence_ids=("train",),
            validation_sequence_ids=("validation",),
            source_sha256={"train": "a" * 64, "validation": "b" * 64},
            calibration_sha256={"train": "c" * 64, "validation": "d" * 64},
            code_revision="onnx-test-revision",
        )

    def _save_training_checkpoint(self, path: Path) -> CompactVIO:
        torch.manual_seed(701)
        model = CompactVIO(self.model_config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        save_checkpoint(
            path,
            model=model,
            config=self.training_config,
            epoch=0,
            metrics={"validation/weighted_motion_loss": 0.25},
            provenance=self.provenance,
            optimizer=optimizer,
        )
        return model

    def test_export_adapter_matches_native_step_and_ignores_right_padding(self) -> None:
        for rotation_policy in (
            "shared-recurrent-fusion-state/v1",
            "current-pair-zero-initialized-fusion-state/v1",
        ):
            config = ModelConfig(
                image_height_px=32,
                image_width_px=48,
                visual_feature_dim=24,
                imu_hidden_dim=12,
                fusion_hidden_dim=24,
                dropout_probability=0.0,
                rotation_state_source=rotation_policy,
            )
            torch.manual_seed(703)
            model = CompactVIO(config).eval()
            frame_pairs, imu, imu_lengths, delta_time_s, state = _synthetic_inputs(
                model,
                batch_size=3,
                padded_imu_samples=5,
                seed=709,
            )
            adapter = _create_export_adapter(model)
            with torch.inference_mode():
                native, native_state = model.step(
                    frame_pairs,
                    imu,
                    imu_lengths,
                    delta_time_s,
                    state,
                )
                actual_motion, actual_state = adapter(
                    frame_pairs,
                    imu,
                    imu_lengths,
                    delta_time_s,
                    state,
                )
                changed_padding = imu.clone()
                for row, length in enumerate(imu_lengths.tolist()):
                    changed_padding[row, length:] = 10_000.0
                padded_motion, padded_state = adapter(
                    frame_pairs,
                    changed_padding,
                    imu_lengths,
                    delta_time_s,
                    state,
                )

            torch.testing.assert_close(actual_motion, native.motion_vector, rtol=1e-6, atol=1e-7)
            torch.testing.assert_close(actual_state, native_state, rtol=1e-6, atol=1e-7)
            torch.testing.assert_close(padded_motion, actual_motion, rtol=0, atol=0)
            torch.testing.assert_close(padded_state, actual_state, rtol=0, atol=0)

    def test_mocked_export_is_exclusive_and_manifest_binds_model(self) -> None:
        parity = OnnxParityResult(
            provider="CPUExecutionProvider",
            absolute_tolerance=1e-5,
            relative_tolerance=1e-5,
            runs=(
                OnnxParityRun(1, 1e-7, 2e-7),
                OnnxParityRun(2, 2e-7, 3e-7),
            ),
        )

        def fake_export(
            model: object,
            destination: Path,
            *,
            opset_version: int,
            sample_imu_samples: int,
        ) -> None:
            self.assertEqual(opset_version, 17)
            self.assertEqual(sample_imu_samples, 5)
            destination.write_bytes(b"synthetic-onnx-graph")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            model_path = root / "compact-vio.onnx"
            manifest_path = root / "compact-vio.onnx.json"
            self._save_training_checkpoint(source)
            with (
                patch("compact_vio.learning.onnx_export._export_graph", side_effect=fake_export),
                patch("compact_vio.learning.onnx_export._annotate_and_check_onnx"),
                patch("compact_vio.learning.onnx_export.check_onnx_parity", return_value=parity),
            ):
                result = export_onnx_checkpoint(
                    source,
                    model_path,
                    manifest_path,
                    expected_source_sha256=_sha256(source),
                    expected_inference_policy_id=STATEFUL_INFERENCE_POLICY_ID,
                    sample_imu_samples=5,
                )

            manifest = verify_onnx_manifest(manifest_path)
            self.assertEqual(result.model_sha256, _sha256(model_path))
            self.assertEqual(result.manifest_sha256, _sha256(manifest_path))
            self.assertEqual(manifest["artifact"]["onnx_sha256"], _sha256(model_path))
            self.assertEqual(manifest["export"]["dynamic_axes"], ["batch", "imu_samples"])
            self.assertEqual(
                tuple(item["name"] for item in manifest["io_contract"]["inputs"]),
                ONNX_INPUT_NAMES,
            )
            self.assertEqual(
                tuple(item["name"] for item in manifest["io_contract"]["outputs"]),
                ONNX_OUTPUT_NAMES,
            )
            self.assertEqual(manifest["parity"]["status"], "passed")
            self.assertEqual(
                manifest["source_checkpoint"]["record_type"],
                "compact_vio_training_checkpoint",
            )
            with self.assertRaisesRegex(LearningError, "refusing to overwrite"):
                export_onnx_checkpoint(
                    source,
                    model_path,
                    manifest_path,
                    expected_source_sha256=_sha256(source),
                )

            model_path.write_bytes(b"tampered")
            with self.assertRaisesRegex(LearningError, "byte size|SHA-256 mismatch"):
                verify_onnx_manifest(manifest_path)

    def test_source_hash_is_mandatory_and_checked_before_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            self._save_training_checkpoint(source)
            with self.assertRaisesRegex(LearningError, "source checkpoint SHA-256 mismatch"):
                export_onnx_checkpoint(
                    source,
                    root / "model.onnx",
                    root / "model.onnx.json",
                    expected_source_sha256="0" * 64,
                )

    @unittest.skipUnless(ONNX_STACK_AVAILABLE, "ONNX and ONNX Runtime are not installed")
    def test_real_export_has_dynamic_shapes_and_recurrent_parity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            model_path = root / "compact-vio.onnx"
            manifest_path = root / "compact-vio.onnx.json"
            self._save_training_checkpoint(source)
            result = export_onnx_checkpoint(
                source,
                model_path,
                manifest_path,
                expected_source_sha256=_sha256(source),
                expected_inference_policy_id=STATEFUL_INFERENCE_POLICY_ID,
                sample_imu_samples=4,
            )

            manifest = verify_onnx_manifest(manifest_path)
            self.assertIsNotNone(result.parity)
            self.assertEqual(len(result.parity.runs), 2)
            self.assertEqual(manifest["parity"]["status"], "passed")


if __name__ == "__main__":
    unittest.main()

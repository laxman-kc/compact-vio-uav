from __future__ import annotations

import builtins
import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

if TORCH_AVAILABLE:
    from compact_vio.learning import inference as inference_module
    from compact_vio.learning.checkpoint import CheckpointProvenance, save_checkpoint
    from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
    from compact_vio.learning.errors import LearningError
    from compact_vio.learning.full_pose_evaluate_cli import (
        evaluate_checkpoint_on_euroc_sequence,
    )
    from compact_vio.learning.inference_checkpoint import (
        INDEPENDENT_INFERENCE_POLICY_ID,
        export_inference_checkpoint,
    )
    from compact_vio.learning.model import CompactVIO
    from tests.test_learning_torch import _write_asl_fixture


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FullPoseEvaluateDependencyLightTests(unittest.TestCase):
    def test_help_does_not_import_torch_and_requires_explicit_state_policy(self) -> None:
        original_import = builtins.__import__

        def reject_torch(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            if name == "torch" or name.startswith("torch."):
                raise AssertionError("--help must not import Torch")
            return original_import(name, globals, locals, fromlist, level)

        sys.modules.pop("compact_vio.learning.full_pose_evaluate_cli", None)
        builtins.__import__ = reject_torch
        try:
            from compact_vio.learning.full_pose_evaluate_cli import main

            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                main(["--help"])
        finally:
            builtins.__import__ = original_import
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--state-policy {independent,stateful}", output.getvalue())


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class FullPoseEvaluatePolicyTests(unittest.TestCase):
    def _write_checkpoint_and_sequence(self, directory: str) -> tuple[Path, Path]:
        sequence = _write_asl_fixture(directory)
        model_config = ModelConfig(
            image_height_px=32,
            image_width_px=48,
            visual_feature_dim=16,
            imu_hidden_dim=8,
            fusion_hidden_dim=16,
            dropout_probability=0.0,
        )
        config = TrainingConfig(
            model=model_config,
            data=DataConfig(),
            batch_size=2,
            epochs=1,
            num_workers=0,
            use_amp=False,
        )
        provenance = CheckpointProvenance.create(
            dataset_id="synthetic-policy-evaluation",
            split_id="synthetic-disjoint-split",
            train_sequence_ids=("train",),
            validation_sequence_ids=("validation",),
            source_sha256={"train": "a" * 64, "validation": "b" * 64},
            calibration_sha256={"train": "c" * 64, "validation": "d" * 64},
            code_revision="policy-evaluation-test",
        )
        checkpoint = Path(directory) / "training.pt"
        save_checkpoint(
            checkpoint,
            model=CompactVIO(model_config),
            config=config,
            epoch=1,
            metrics={"validation/total_loss": 1.0},
            provenance=provenance,
        )
        return checkpoint, sequence

    def test_independent_resets_each_pair_while_stateful_carries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint, sequence = self._write_checkpoint_and_sequence(directory)
            original_predict = inference_module.predict_sequence_batch
            independent_states: list[torch.Tensor | None] = []

            def track_independent(*args: object, **kwargs: object) -> object:
                independent_states.append(kwargs.get("initial_fusion_state"))  # type: ignore[arg-type]
                return original_predict(*args, **kwargs)  # type: ignore[arg-type]

            with patch.object(
                inference_module,
                "predict_sequence_batch",
                new=track_independent,
            ):
                independent = evaluate_checkpoint_on_euroc_sequence(
                    checkpoint,
                    sequence,
                    state_policy="independent",
                    unroll_pairs=128,
                )

            stateful_states: list[torch.Tensor | None] = []

            def track_stateful(*args: object, **kwargs: object) -> object:
                stateful_states.append(kwargs.get("initial_fusion_state"))  # type: ignore[arg-type]
                return original_predict(*args, **kwargs)  # type: ignore[arg-type]

            with patch.object(
                inference_module,
                "predict_sequence_batch",
                new=track_stateful,
            ):
                stateful = evaluate_checkpoint_on_euroc_sequence(
                    checkpoint,
                    sequence,
                    state_policy="stateful",
                    unroll_pairs=1,
                )

        self.assertEqual(len(independent_states), 2)
        self.assertTrue(all(state is None for state in independent_states))
        self.assertEqual(independent["inference"]["effective_unroll_pairs"], 1)  # type: ignore[index]
        self.assertEqual(independent["inference"]["state_policy"], "independent")  # type: ignore[index]
        self.assertEqual(len(stateful_states), 2)
        self.assertIsNone(stateful_states[0])
        self.assertIsInstance(stateful_states[1], torch.Tensor)
        self.assertEqual(stateful["inference"]["state_policy"], "stateful")  # type: ignore[index]

    def test_inference_artifact_policy_mismatch_fails_before_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint, sequence = self._write_checkpoint_and_sequence(directory)
            artifact = Path(directory) / "independent-inference.pt"
            export_inference_checkpoint(
                checkpoint,
                artifact,
                expected_source_sha256=_sha256(checkpoint),
                inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )

            with self.assertRaisesRegex(LearningError, "inference policy mismatch"):
                evaluate_checkpoint_on_euroc_sequence(
                    artifact,
                    sequence,
                    state_policy="stateful",
                    expected_checkpoint_sha256=_sha256(artifact),
                )


if __name__ == "__main__":
    unittest.main()

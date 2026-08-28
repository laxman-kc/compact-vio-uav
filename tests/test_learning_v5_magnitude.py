from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from compact_vio.learning.cli import _checkpoint_split_id, _epoch_metrics_json, load_run_spec
from compact_vio.learning.config import ModelConfig, TrainingConfig
from compact_vio.learning.errors import LearningError

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

if TORCH_AVAILABLE:
    from compact_vio.learning.checkpoint import (
        CheckpointProvenance,
        load_checkpoint,
        save_checkpoint,
    )
    from compact_vio.learning.dataset import SampleIdentity, VIOBatch
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.training import motion_loss, train_one_epoch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V2_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v2_stride_augmented.json"
V5_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v5_magnitude.json"


class V5MagnitudeConfigTests(unittest.TestCase):
    def test_v5_changes_only_experiment_identity_and_magnitude_loss_weight(self) -> None:
        v2_document = json.loads(V2_CONFIG_PATH.read_text(encoding="utf-8"))
        v5_document = json.loads(V5_CONFIG_PATH.read_text(encoding="utf-8"))
        normalized_v5 = copy.deepcopy(v5_document)
        normalized_v5["experiment_id"] = v2_document["experiment_id"]
        normalized_v5["optimization"].pop("translation_magnitude_loss_weight")

        self.assertEqual(normalized_v5, v2_document)

        v2 = load_run_spec(V2_CONFIG_PATH)
        v5 = load_run_spec(V5_CONFIG_PATH)
        self.assertEqual(
            replace(v5.training, translation_magnitude_loss_weight=0.0),
            v2.training,
        )
        self.assertEqual(v5.training.translation_magnitude_loss_weight, 1.0)
        self.assertEqual(v5.training_frame_strides, (1, 2))
        self.assertEqual(v5.training_unroll_pairs, 1)
        self.assertEqual(v5.training.epochs, 30)
        self.assertEqual(v5.training.seed, 20260828)
        self.assertEqual(v5.experiment_id, "euroc-compact-vio-v5-magnitude")

    def test_legacy_canonical_config_defaults_magnitude_weight_to_zero(self) -> None:
        declared = TrainingConfig()
        legacy_mapping = declared.to_dict()

        parsed = TrainingConfig.from_dict(legacy_mapping)

        self.assertNotIn("translation_magnitude_loss_weight", legacy_mapping)
        self.assertEqual(parsed, declared)
        self.assertEqual(parsed.translation_magnitude_loss_weight, 0.0)

    def test_magnitude_weight_must_be_finite_and_non_negative(self) -> None:
        for value in (-1.0, math.nan, math.inf, True):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(LearningError, "translation_magnitude_loss_weight"),
            ):
                TrainingConfig(translation_magnitude_loss_weight=value)  # type: ignore[arg-type]

    def test_provenance_explicitly_binds_v5_loss_without_changing_v2_identity(self) -> None:
        v2 = load_run_spec(V2_CONFIG_PATH)
        v5 = load_run_spec(V5_CONFIG_PATH)

        v2_identity = _checkpoint_split_id(v2, v2.training, smoke=False)
        v5_identity = _checkpoint_split_id(v5, v5.training, smoke=False)

        self.assertEqual(
            v2_identity,
            f"{v2.experiment_id}:config={v2.config_sha256}:"
            f"split={v2.split_sha256}:strides=1,2:unroll=1:"
            "rotation-state-source=shared-recurrent-fusion-state/v1:mode=full",
        )
        self.assertNotIn("translation-magnitude", v2_identity)
        self.assertIn("translation-magnitude-loss=smooth-l1-l2-norm-v1", v5_identity)
        self.assertIn("translation-magnitude-weight=1", v5_identity)
        self.assertIn(f"config={v5.config_sha256}", v5_identity)


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class V5MagnitudeTorchTests(unittest.TestCase):
    def test_motion_loss_is_zero_for_exact_motion_and_finite_for_zero_prediction(self) -> None:
        target = torch.tensor([[0.3, -0.4, 0.0, 0.01, -0.02, 0.03]])

        exact_total, exact_translation, exact_rotation = motion_loss(
            target.clone(),
            target,
            translation_weight=1.0,
            rotation_weight=1.0,
            translation_magnitude_weight=1.0,
        )
        self.assertEqual(float(exact_total), 0.0)
        self.assertEqual(float(exact_translation), 0.0)
        self.assertEqual(float(exact_rotation), 0.0)

        zero_total, zero_translation, zero_rotation = motion_loss(
            torch.zeros_like(target),
            target,
            translation_weight=1.0,
            rotation_weight=1.0,
            translation_magnitude_weight=1.0,
        )
        expected_magnitude = torch.nn.functional.smooth_l1_loss(
            torch.zeros(1),
            torch.tensor([0.5]),
        )
        torch.testing.assert_close(
            zero_total,
            zero_translation + zero_rotation + expected_magnitude,
            rtol=0,
            atol=0,
        )
        self.assertTrue(torch.isfinite(zero_total))

    def test_motion_loss_adds_exact_smooth_l1_norm_term(self) -> None:
        prediction = torch.tensor([[3.0, 4.0, 0.0, 0.0, 0.0, 0.0]])
        target = torch.zeros_like(prediction)

        legacy_total, translation, rotation = motion_loss(
            prediction,
            target,
            translation_weight=1.0,
            rotation_weight=1.0,
        )
        v5_total, v5_translation, v5_rotation = motion_loss(
            prediction,
            target,
            translation_weight=1.0,
            rotation_weight=1.0,
            translation_magnitude_weight=1.0,
        )

        self.assertEqual(float(translation), 2.0)
        self.assertEqual(float(rotation), 0.0)
        self.assertEqual(float(legacy_total), 2.0)
        self.assertEqual(float(v5_total), 6.5)
        torch.testing.assert_close(v5_translation, translation, rtol=0, atol=0)
        torch.testing.assert_close(v5_rotation, rotation, rtol=0, atol=0)

    def test_magnitude_objective_backpropagates_finite_translation_gradients(self) -> None:
        prediction = torch.tensor(
            [[0.3, 0.4, 0.0, 0.0, 0.0, 0.0]],
            requires_grad=True,
        )
        target = torch.zeros_like(prediction)

        total, _, _ = motion_loss(
            prediction,
            target,
            translation_weight=1.0,
            rotation_weight=1.0,
            translation_magnitude_weight=1.0,
        )
        total.backward()

        self.assertIsNotNone(prediction.grad)
        assert prediction.grad is not None
        self.assertTrue(torch.isfinite(prediction.grad).all())
        self.assertGreater(float(torch.linalg.vector_norm(prediction.grad[:, :3])), 0.0)

    def test_training_metrics_report_magnitude_loss_only_when_enabled(self) -> None:
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
            batch_size=2,
            epochs=1,
            translation_magnitude_loss_weight=1.0,
            num_workers=0,
            use_amp=False,
        )
        batch = VIOBatch(
            frame_pairs=torch.randn(2, 2, 32, 48),
            imu=torch.randn(2, 3, 6),
            imu_lengths=torch.tensor([3, 2]),
            delta_time_s=torch.tensor([[0.05], [0.05]]),
            target_motion=torch.randn(2, 6),
            identities=(
                SampleIdentity("synthetic", 100, 200),
                SampleIdentity("synthetic", 200, 300),
            ),
        )
        model = CompactVIO(model_config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate)

        metrics = train_one_epoch(
            model,
            (batch,),
            optimizer=optimizer,
            device="cpu",
            config=config,
        )

        self.assertIsNotNone(metrics.translation_magnitude_loss)
        assert metrics.translation_magnitude_loss is not None
        self.assertTrue(math.isfinite(metrics.translation_magnitude_loss))
        self.assertIn("translation_magnitude_loss", metrics.to_dict())
        self.assertIn("translation_magnitude_loss", _epoch_metrics_json(metrics))
        legacy_metrics = replace(metrics, translation_magnitude_loss=None)
        self.assertNotIn("translation_magnitude_loss", legacy_metrics.to_dict())
        self.assertNotIn("translation_magnitude_loss", _epoch_metrics_json(legacy_metrics))

    def test_legacy_checkpoint_without_magnitude_field_loads_as_zero(self) -> None:
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
            batch_size=2,
            epochs=1,
            num_workers=0,
            use_amp=False,
        )
        provenance = CheckpointProvenance.create(
            dataset_id="synthetic-v1",
            split_id="legacy-objective-v1",
            train_sequence_ids=("train",),
            validation_sequence_ids=("validation",),
            source_sha256={"train": "a" * 64, "validation": "b" * 64},
            calibration_sha256={"train": "c" * 64, "validation": "d" * 64},
            code_revision="test-revision",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.pt"
            save_checkpoint(
                path,
                model=CompactVIO(model_config),
                config=config,
                epoch=1,
                metrics={"validation/total_loss": 1.0},
                provenance=provenance,
            )
            payload = torch.load(path, map_location="cpu", weights_only=True)
            self.assertNotIn("translation_magnitude_loss_weight", payload["config"])
            torch.save(payload, path)

            metadata = load_checkpoint(path, model=CompactVIO(model_config))

        self.assertEqual(metadata.config.translation_magnitude_loss_weight, 0.0)
        self.assertEqual(metadata.provenance, provenance)

    def test_v5_checkpoint_roundtrip_binds_the_expected_objective(self) -> None:
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
            batch_size=2,
            epochs=1,
            translation_magnitude_loss_weight=1.0,
            num_workers=0,
            use_amp=False,
        )
        provenance = CheckpointProvenance.create(
            dataset_id="synthetic-v5",
            split_id="magnitude-objective-v1",
            train_sequence_ids=("train",),
            validation_sequence_ids=("validation",),
            source_sha256={"train": "a" * 64, "validation": "b" * 64},
            calibration_sha256={"train": "c" * 64, "validation": "d" * 64},
            code_revision="test-revision",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v5.pt"
            save_checkpoint(
                path,
                model=CompactVIO(model_config),
                config=config,
                epoch=1,
                metrics={"validation/translation_magnitude_loss": 0.25},
                provenance=provenance,
            )
            metadata = load_checkpoint(
                path,
                model=CompactVIO(model_config),
                expected_config=config,
                expected_provenance=provenance,
            )
            incompatible = replace(config, translation_magnitude_loss_weight=0.0)
            with self.assertRaisesRegex(LearningError, "configuration differs"):
                load_checkpoint(
                    path,
                    model=CompactVIO(model_config),
                    expected_config=incompatible,
                    expected_provenance=provenance,
                )

        self.assertEqual(metadata.config, config)
        self.assertEqual(metadata.provenance, provenance)
        self.assertEqual(metadata.metrics["validation/translation_magnitude_loss"], 0.25)


if __name__ == "__main__":
    unittest.main()

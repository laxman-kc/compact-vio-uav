from __future__ import annotations

import copy
import json
import math
import unittest
from dataclasses import replace
from pathlib import Path

from compact_vio.learning.cli import _checkpoint_split_id, _epoch_metrics_json, load_run_spec
from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
from compact_vio.learning.errors import LearningError

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

if TORCH_AVAILABLE:
    from compact_vio.learning.dataset import SampleIdentity, VIOSequenceBatch
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.training import (
        seed_everything,
        train_one_epoch,
        trajectory_consistency_loss,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V4_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v4_translation_state.json"
V6_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v6_trajectory.json"


class V6TrajectoryConfigTests(unittest.TestCase):
    def test_v6_changes_only_identity_and_trajectory_loss_weight_from_v4(self) -> None:
        v4_document = json.loads(V4_CONFIG_PATH.read_text(encoding="utf-8"))
        v6_document = json.loads(V6_CONFIG_PATH.read_text(encoding="utf-8"))
        normalized_v6 = copy.deepcopy(v6_document)
        normalized_v6["experiment_id"] = v4_document["experiment_id"]
        normalized_v6["optimization"].pop("trajectory_loss_weight")

        self.assertEqual(normalized_v6, v4_document)

        v4 = load_run_spec(V4_CONFIG_PATH)
        v6 = load_run_spec(V6_CONFIG_PATH)
        self.assertEqual(replace(v6.training, trajectory_loss_weight=0.0), v4.training)
        self.assertEqual(v6.training.trajectory_loss_weight, 1.0)
        self.assertEqual(v6.training_unroll_pairs, 8)
        self.assertEqual(v6.training_frame_strides, (1, 2))

    def test_legacy_configuration_defaults_trajectory_weight_to_zero(self) -> None:
        legacy = TrainingConfig()
        mapping = legacy.to_dict()

        self.assertNotIn("trajectory_loss_weight", mapping)
        self.assertEqual(TrainingConfig.from_dict(mapping), legacy)
        self.assertEqual(legacy.trajectory_loss_weight, 0.0)

    def test_trajectory_weight_must_be_finite_and_non_negative(self) -> None:
        for value in (-1.0, math.nan, math.inf, True):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(LearningError, "trajectory_loss_weight"),
            ):
                TrainingConfig(trajectory_loss_weight=value)  # type: ignore[arg-type]

    def test_checkpoint_identity_binds_the_trajectory_objective(self) -> None:
        v4 = load_run_spec(V4_CONFIG_PATH)
        v6 = load_run_spec(V6_CONFIG_PATH)

        v4_identity = _checkpoint_split_id(v4, v4.training, smoke=False)
        v6_identity = _checkpoint_split_id(v6, v6.training, smoke=False)

        self.assertNotIn("trajectory-loss", v4_identity)
        self.assertIn("trajectory-loss=body-frame-se3-endpoint-smooth-l1-v1", v6_identity)
        self.assertIn("trajectory-weight=1", v6_identity)


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class V6TrajectoryTorchTests(unittest.TestCase):
    def test_loss_is_zero_for_perfect_pose_sequence_and_positive_for_zero_motion(self) -> None:
        target = torch.tensor(
            [
                [
                    [1.0, 0.0, 0.0, 0.0, 0.0, math.pi / 2.0],
                    [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                    [0.0, 0.5, 0.0, 0.0, math.pi / 8.0, 0.0],
                ]
            ]
        )
        mask = torch.ones(1, 3, dtype=torch.bool)

        perfect, perfect_translation, perfect_rotation = trajectory_consistency_loss(
            target.clone(), target, mask
        )
        zero, zero_translation, zero_rotation = trajectory_consistency_loss(
            torch.zeros_like(target), target, mask
        )

        self.assertEqual(float(perfect), 0.0)
        self.assertEqual(float(perfect_translation), 0.0)
        self.assertEqual(float(perfect_rotation), 0.0)
        self.assertGreater(float(zero), 0.0)
        self.assertGreater(float(zero_translation), 0.0)
        self.assertGreater(float(zero_rotation), 0.0)

    def test_loss_backpropagates_finite_gradients_to_early_motion(self) -> None:
        prediction = torch.tensor(
            [
                [
                    [0.2, 0.0, 0.0, 0.0, 0.0, 0.05],
                    [0.2, 0.0, 0.0, 0.0, 0.0, 0.05],
                    [0.2, 0.0, 0.0, 0.0, 0.0, 0.05],
                ]
            ],
            requires_grad=True,
        )
        target = torch.tensor(
            [
                [
                    [0.5, 0.0, 0.0, 0.0, 0.0, 0.2],
                    [0.5, 0.0, 0.0, 0.0, 0.0, 0.2],
                    [0.5, 0.0, 0.0, 0.0, 0.0, 0.2],
                ]
            ]
        )
        mask = torch.ones(1, 3, dtype=torch.bool)

        total, _, _ = trajectory_consistency_loss(prediction, target, mask)
        total.backward()

        self.assertIsNotNone(prediction.grad)
        assert prediction.grad is not None
        self.assertTrue(torch.isfinite(prediction.grad).all())
        self.assertGreater(float(prediction.grad[:, 0].abs().sum()), 0.0)

    def test_masked_padding_is_ignored_and_mask_gaps_are_rejected(self) -> None:
        target = torch.randn(1, 3, 6)
        prediction = target.clone()
        mask = torch.tensor([[True, True, False]])
        changed_padding = prediction.clone()
        changed_padding[:, 2] = 10_000.0

        loss, _, _ = trajectory_consistency_loss(changed_padding, target, mask)

        self.assertEqual(float(loss), 0.0)
        with self.assertRaisesRegex(LearningError, "contiguous prefix"):
            trajectory_consistency_loss(
                prediction,
                target,
                torch.tensor([[True, False, True]]),
            )

    def test_sequence_training_reports_trajectory_loss_and_updates_model(self) -> None:
        seed_everything(607)
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
            batch_size=3,
            epochs=1,
            trajectory_loss_weight=1.0,
            num_workers=0,
            use_amp=False,
        )
        batch = VIOSequenceBatch(
            frame_pairs=torch.randn(1, 3, 2, 32, 48),
            imu=torch.randn(1, 3, 2, 6),
            imu_lengths=torch.full((1, 3), 2, dtype=torch.int64),
            delta_time_s=torch.full((1, 3, 1), 0.05),
            target_motion=torch.randn(1, 3, 6),
            step_mask=torch.ones(1, 3, dtype=torch.bool),
            identities=(
                (
                    SampleIdentity("synthetic", 100, 200),
                    SampleIdentity("synthetic", 200, 300),
                    SampleIdentity("synthetic", 300, 400),
                ),
            ),
            chain_ids=("synthetic:stride=1:phase=0",),
            chunk_indices=(0,),
            chain_starts=(True,),
            chain_ends=(True,),
        )
        model = CompactVIO(model_config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)

        metrics = train_one_epoch(
            model,
            (batch,),
            optimizer=optimizer,
            device="cpu",
            config=config,
        )

        self.assertIsNotNone(metrics.trajectory_consistency_loss)
        assert metrics.trajectory_consistency_loss is not None
        self.assertTrue(math.isfinite(metrics.trajectory_consistency_loss))
        self.assertIn("trajectory_consistency_loss", metrics.to_dict())
        self.assertIn("trajectory_consistency_loss", _epoch_metrics_json(metrics))


if __name__ == "__main__":
    unittest.main()

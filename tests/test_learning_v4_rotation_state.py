from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

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
    from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
    from compact_vio.learning.errors import LearningError
    from compact_vio.learning.inference import load_inference_model
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.training import seed_everything


LEGACY_POLICY = "shared-recurrent-fusion-state/v1"
V4_POLICY = "current-pair-zero-initialized-fusion-state/v1"


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class V4RotationStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.legacy_config = ModelConfig(
            image_height_px=32,
            image_width_px=48,
            visual_feature_dim=24,
            imu_hidden_dim=12,
            fusion_hidden_dim=24,
            dropout_probability=0.0,
            rotation_state_source=LEGACY_POLICY,
        )
        self.v4_config = replace(self.legacy_config, rotation_state_source=V4_POLICY)

    def _sequence_inputs(
        self, *, steps: int = 5
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        return (
            torch.randn(1, steps, 2, 32, 48),
            torch.randn(1, steps, 4, 6),
            torch.full((1, steps), 4, dtype=torch.int64),
            torch.full((1, steps, 1), 0.05),
            torch.ones(1, steps, dtype=torch.bool),
        )

    @staticmethod
    def _step_arguments(
        inputs: tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor],
        step: int,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        frame_pairs, imu, imu_lengths, delta_time_s, _ = inputs
        return (
            frame_pairs[:, step],
            imu[:, step],
            imu_lengths[:, step],
            delta_time_s[:, step],
        )

    @staticmethod
    def _provenance() -> CheckpointProvenance:
        return CheckpointProvenance.create(
            dataset_id="synthetic-v4-contract",
            split_id="synthetic-disjoint-split",
            train_sequence_ids=("train",),
            validation_sequence_ids=("validation",),
            source_sha256={"train": "a" * 64, "validation": "b" * 64},
            calibration_sha256={"train": "c" * 64, "validation": "d" * 64},
            code_revision="v4-contract-test",
        )

    def test_policy_default_and_invalid_value_are_strict(self) -> None:
        self.assertEqual(ModelConfig().rotation_state_source, LEGACY_POLICY)
        for invalid in ("not-a-supported-policy", []):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(LearningError, "rotation_state_source"):
                    ModelConfig(rotation_state_source=invalid)  # type: ignore[arg-type]

    def test_v4_changes_only_rotation_state_routing_for_identical_weights(self) -> None:
        seed_everything(401)
        legacy = CompactVIO(self.legacy_config).eval()
        v4 = CompactVIO(self.v4_config).eval()
        v4.load_state_dict(legacy.state_dict(), strict=True)
        inputs = self._sequence_inputs(steps=1)
        arguments = self._step_arguments(inputs, 0)

        self.assertEqual(legacy.parameter_count, v4.parameter_count)
        self.assertEqual(tuple(legacy.state_dict()), tuple(v4.state_dict()))
        for name, tensor in legacy.state_dict().items():
            self.assertEqual(tensor.shape, v4.state_dict()[name].shape)

        legacy_reset, legacy_reset_state = legacy.step(*arguments)
        v4_reset, v4_reset_state = v4.step(*arguments)
        torch.testing.assert_close(
            legacy_reset.motion_vector, v4_reset.motion_vector, rtol=0, atol=0
        )
        torch.testing.assert_close(legacy_reset_state, v4_reset_state, rtol=0, atol=0)

        prior = torch.randn(1, self.v4_config.fusion_hidden_dim)
        legacy_carried, legacy_next = legacy.step(*arguments, prior)
        v4_carried, v4_next = v4.step(*arguments, prior)
        torch.testing.assert_close(
            legacy_carried.relative_translation_m,
            v4_carried.relative_translation_m,
            rtol=0,
            atol=0,
        )
        torch.testing.assert_close(legacy_next, v4_next, rtol=0, atol=0)
        torch.testing.assert_close(
            v4_carried.relative_rotation_vector_rad,
            v4_reset.relative_rotation_vector_rad,
            rtol=0,
            atol=0,
        )
        self.assertFalse(
            torch.equal(
                legacy_carried.relative_rotation_vector_rad,
                v4_carried.relative_rotation_vector_rad,
            )
        )

    def test_rotation_is_prior_state_invariant_while_translation_is_sensitive(self) -> None:
        seed_everything(409)
        model = CompactVIO(self.v4_config).eval()
        inputs = self._sequence_inputs(steps=1)
        arguments = self._step_arguments(inputs, 0)
        first_state = torch.zeros(1, self.v4_config.fusion_hidden_dim)
        second_state = torch.full_like(first_state, 0.75)

        first, _ = model.step(*arguments, first_state)
        second, _ = model.step(*arguments, second_state)
        torch.testing.assert_close(
            first.relative_rotation_vector_rad,
            second.relative_rotation_vector_rad,
            rtol=0,
            atol=0,
        )
        self.assertFalse(torch.equal(first.relative_translation_m, second.relative_translation_m))

        differentiable_state = torch.randn_like(first_state, requires_grad=True)
        output, _ = model.step(*arguments, differentiable_state)
        rotation_gradient = torch.autograd.grad(
            output.relative_rotation_vector_rad.square().sum(),
            differentiable_state,
            retain_graph=True,
            allow_unused=True,
        )[0]
        translation_gradient = torch.autograd.grad(
            output.relative_translation_m.square().sum(),
            differentiable_state,
            allow_unused=True,
        )[0]
        if rotation_gradient is not None:
            torch.testing.assert_close(
                rotation_gradient, torch.zeros_like(rotation_gradient), rtol=0, atol=0
            )
        self.assertIsNotNone(translation_gradient)
        assert translation_gradient is not None
        self.assertTrue(torch.isfinite(translation_gradient).all())
        self.assertGreater(float(translation_gradient.abs().sum()), 0.0)

    def test_different_histories_cannot_change_common_pair_rotation(self) -> None:
        seed_everything(419)
        model = CompactVIO(self.v4_config).eval()
        common = self._sequence_inputs(steps=2)
        history_a = self._step_arguments(common, 0)
        history_b = (
            torch.randn_like(history_a[0]),
            torch.randn_like(history_a[1]),
            history_a[2],
            history_a[3],
        )
        _, state_a = model.step(*history_a)
        _, state_b = model.step(*history_b)
        self.assertFalse(torch.equal(state_a, state_b))

        current = self._step_arguments(common, 1)
        after_a, _ = model.step(*current, state_a)
        after_b, _ = model.step(*current, state_b)
        torch.testing.assert_close(
            after_a.relative_rotation_vector_rad,
            after_b.relative_rotation_vector_rad,
            rtol=0,
            atol=0,
        )
        self.assertFalse(
            torch.equal(after_a.relative_translation_m, after_b.relative_translation_m)
        )

    def test_final_rotation_gradient_is_current_pair_only(self) -> None:
        seed_everything(421)
        model = CompactVIO(self.v4_config).eval()
        frame_pairs, imu, imu_lengths, delta_time_s, step_mask = self._sequence_inputs(steps=4)
        frame_pairs = frame_pairs.requires_grad_(True)

        output = model.forward_sequence(
            frame_pairs,
            imu,
            imu_lengths,
            delta_time_s,
            step_mask,
        )
        rotation_gradient = torch.autograd.grad(
            output.relative_rotation_vector_rad[:, -1].square().sum(),
            frame_pairs,
            retain_graph=True,
        )[0]
        translation_gradient = torch.autograd.grad(
            output.relative_translation_m[:, -1].square().sum(),
            frame_pairs,
        )[0]

        torch.testing.assert_close(
            rotation_gradient[:, :-1],
            torch.zeros_like(rotation_gradient[:, :-1]),
            rtol=0,
            atol=0,
        )
        self.assertGreater(float(rotation_gradient[:, -1].abs().sum()), 0.0)
        self.assertGreater(float(translation_gradient[:, :-1].abs().sum()), 0.0)

    def test_rotation_is_invariant_to_chunk_boundaries_and_state_resets(self) -> None:
        seed_everything(431)
        model = CompactVIO(self.v4_config).eval()
        frame_pairs, imu, imu_lengths, delta_time_s, step_mask = self._sequence_inputs(steps=5)
        full = model.forward_sequence(
            frame_pairs,
            imu,
            imu_lengths,
            delta_time_s,
            step_mask,
        )

        first = model.forward_sequence(
            frame_pairs[:, :2],
            imu[:, :2],
            imu_lengths[:, :2],
            delta_time_s[:, :2],
            step_mask[:, :2],
        )
        carried = model.forward_sequence(
            frame_pairs[:, 2:],
            imu[:, 2:],
            imu_lengths[:, 2:],
            delta_time_s[:, 2:],
            step_mask[:, 2:],
            first.final_fusion_state,
        )
        carried_motion = torch.cat((first.motion_vector, carried.motion_vector), dim=1)
        torch.testing.assert_close(carried_motion, full.motion_vector, rtol=1e-5, atol=1e-6)
        torch.testing.assert_close(
            carried.final_fusion_state,
            full.final_fusion_state,
            rtol=1e-5,
            atol=1e-6,
        )

        reset = model.forward_sequence(
            frame_pairs[:, 2:],
            imu[:, 2:],
            imu_lengths[:, 2:],
            delta_time_s[:, 2:],
            step_mask[:, 2:],
        )
        torch.testing.assert_close(
            reset.relative_rotation_vector_rad,
            full.relative_rotation_vector_rad[:, 2:],
            rtol=1e-5,
            atol=1e-6,
        )
        self.assertFalse(
            torch.equal(
                reset.relative_translation_m,
                full.relative_translation_m[:, 2:],
            )
        )

    def test_masked_padding_cannot_change_valid_outputs_or_final_state(self) -> None:
        seed_everything(433)
        model = CompactVIO(self.v4_config).eval()
        frame_pairs, imu, imu_lengths, delta_time_s, _ = self._sequence_inputs(steps=4)
        step_mask = torch.tensor([[True, True, False, False]])

        baseline = model.forward_sequence(
            frame_pairs,
            imu,
            imu_lengths,
            delta_time_s,
            step_mask,
        )
        changed_frames = frame_pairs.clone()
        changed_imu = imu.clone()
        changed_lengths = imu_lengths.clone()
        changed_delta_time = delta_time_s.clone()
        changed_frames[:, 2:] = 10_000.0
        changed_imu[:, 2:] = -10_000.0
        changed_lengths[:, 2:] = 0
        changed_delta_time[:, 2:] = -10_000.0
        changed = model.forward_sequence(
            changed_frames,
            changed_imu,
            changed_lengths,
            changed_delta_time,
            step_mask,
        )
        truncated = model.forward_sequence(
            frame_pairs[:, :2],
            imu[:, :2],
            imu_lengths[:, :2],
            delta_time_s[:, :2],
            torch.ones(1, 2, dtype=torch.bool),
        )

        torch.testing.assert_close(
            baseline.motion_vector[:, :2], changed.motion_vector[:, :2], rtol=0, atol=0
        )
        torch.testing.assert_close(
            baseline.final_fusion_state, changed.final_fusion_state, rtol=0, atol=0
        )
        torch.testing.assert_close(
            baseline.motion_vector[:, 2:],
            torch.zeros_like(baseline.motion_vector[:, 2:]),
            rtol=0,
            atol=0,
        )
        torch.testing.assert_close(
            changed.motion_vector[:, 2:],
            torch.zeros_like(changed.motion_vector[:, 2:]),
            rtol=0,
            atol=0,
        )
        torch.testing.assert_close(
            baseline.motion_vector[:, :2], truncated.motion_vector, rtol=1e-5, atol=1e-6
        )
        torch.testing.assert_close(
            baseline.final_fusion_state,
            truncated.final_fusion_state,
            rtol=1e-5,
            atol=1e-6,
        )

    def test_checkpoint_policy_identity_prevents_same_shape_misrouting(self) -> None:
        seed_everything(439)
        v4_model = CompactVIO(self.v4_config).eval()
        v4_training = TrainingConfig(
            model=self.v4_config,
            data=DataConfig(),
            batch_size=2,
            epochs=1,
            num_workers=0,
            use_amp=False,
        )
        inputs = self._sequence_inputs(steps=1)
        arguments = self._step_arguments(inputs, 0)
        expected, _ = v4_model.step(*arguments)

        with tempfile.TemporaryDirectory() as directory:
            v4_path = Path(directory) / "v4.pt"
            save_checkpoint(
                v4_path,
                model=v4_model,
                config=v4_training,
                epoch=1,
                metrics={"validation/total_loss": 0.1},
                provenance=self._provenance(),
            )
            with self.assertRaisesRegex(LearningError, "config does not match"):
                load_checkpoint(v4_path, model=CompactVIO(self.legacy_config))

            restored, metadata = load_inference_model(v4_path)
            actual, _ = restored.step(*arguments)
            self.assertEqual(metadata.config.model.rotation_state_source, V4_POLICY)
            self.assertEqual(restored.config.rotation_state_source, V4_POLICY)
            torch.testing.assert_close(expected.motion_vector, actual.motion_vector, rtol=0, atol=0)

            old_style_path = Path(directory) / "legacy-without-policy.pt"
            legacy_model = CompactVIO(self.legacy_config).eval()
            legacy_training = replace(v4_training, model=self.legacy_config)
            save_checkpoint(
                old_style_path,
                model=legacy_model,
                config=legacy_training,
                epoch=1,
                metrics={"validation/total_loss": 0.2},
                provenance=self._provenance(),
            )
            payload = torch.load(old_style_path, map_location="cpu", weights_only=True)
            payload["config"]["model"].pop("rotation_state_source")
            torch.save(payload, old_style_path)
            restored_legacy, legacy_metadata = load_inference_model(old_style_path)
            self.assertEqual(legacy_metadata.config.model.rotation_state_source, LEGACY_POLICY)
            self.assertEqual(restored_legacy.config.rotation_state_source, LEGACY_POLICY)


if __name__ == "__main__":
    unittest.main()

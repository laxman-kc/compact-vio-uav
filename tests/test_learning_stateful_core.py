from __future__ import annotations

import unittest

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

if TORCH_AVAILABLE:
    from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
    from compact_vio.learning.dataset import SampleIdentity, VIOSequenceBatch
    from compact_vio.learning.inference import predict_sequence_batch
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.training import evaluate, seed_everything, train_one_epoch


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class StatefulCoreTests(unittest.TestCase):
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
            data=DataConfig(),
            batch_size=8,
            epochs=1,
            num_workers=0,
            use_amp=False,
        )

    def _sequence_batch(
        self,
        *,
        valid_steps: tuple[int, ...] = (3,),
        steps: int = 3,
        chain_ids: tuple[str, ...] | None = None,
        chunk_indices: tuple[int, ...] | None = None,
        chain_starts: tuple[bool, ...] | None = None,
        chain_ends: tuple[bool, ...] | None = None,
    ) -> VIOSequenceBatch:
        batch_size = len(valid_steps)
        frame_pairs = torch.randn(batch_size, steps, 2, 32, 48)
        imu = torch.randn(batch_size, steps, 3, 6)
        imu_lengths = torch.full((batch_size, steps), 3, dtype=torch.int64)
        delta_time_s = torch.full((batch_size, steps, 1), 0.05)
        target_motion = torch.randn(batch_size, steps, 6)
        step_mask = torch.zeros(batch_size, steps, dtype=torch.bool)
        identity_rows: list[tuple[SampleIdentity | None, ...]] = []
        for batch_index, length in enumerate(valid_steps):
            if length <= 0 or length > steps:
                raise AssertionError("test valid_steps must be in [1, steps]")
            step_mask[batch_index, :length] = True
            identities: list[SampleIdentity | None] = []
            for step_index in range(steps):
                if step_index < length:
                    previous = 1_000_000 * (batch_index + 1) + step_index * 100
                    identities.append(
                        SampleIdentity(
                            f"sequence-{batch_index}",
                            previous,
                            previous + 100,
                        )
                    )
                else:
                    identities.append(None)
            identity_rows.append(tuple(identities))
            if length < steps:
                imu_lengths[batch_index, length:] = 1
                delta_time_s[batch_index, length:] = 1.0
                target_motion[batch_index, length:] = 0.0
        if chain_ids is None:
            chain_ids = tuple(f"chain-{index}" for index in range(batch_size))
        if chunk_indices is None:
            chunk_indices = (0,) * batch_size
        if chain_starts is None:
            chain_starts = (True,) * batch_size
        if chain_ends is None:
            chain_ends = (True,) * batch_size
        return VIOSequenceBatch(
            frame_pairs=frame_pairs,
            imu=imu,
            imu_lengths=imu_lengths,
            delta_time_s=delta_time_s,
            target_motion=target_motion,
            step_mask=step_mask,
            identities=tuple(identity_rows),
            chain_ids=chain_ids,
            chunk_indices=chunk_indices,
            chain_starts=chain_starts,
            chain_ends=chain_ends,
        )

    def test_legacy_forward_is_identical_to_explicit_zero_state_step(self) -> None:
        seed_everything(101)
        model = CompactVIO(self.model_config).eval()
        batch = self._sequence_batch(steps=1, valid_steps=(1,))

        legacy = model(
            batch.frame_pairs[:, 0],
            batch.imu[:, 0],
            batch.imu_lengths[:, 0],
            batch.delta_time_s[:, 0],
        )
        explicit, _ = model.step(
            batch.frame_pairs[:, 0],
            batch.imu[:, 0],
            batch.imu_lengths[:, 0],
            batch.delta_time_s[:, 0],
            model.initial_fusion_state(1),
        )

        torch.testing.assert_close(legacy.motion_vector, explicit.motion_vector, rtol=0, atol=0)

    def test_state_changes_output_and_reset_is_reproducible(self) -> None:
        seed_everything(103)
        model = CompactVIO(self.model_config).eval()
        batch = self._sequence_batch(steps=1, valid_steps=(1,))
        arguments = (
            batch.frame_pairs[:, 0],
            batch.imu[:, 0],
            batch.imu_lengths[:, 0],
            batch.delta_time_s[:, 0],
        )

        first, first_state = model.step(*arguments)
        continued, continued_state = model.step(*arguments, first_state)
        reset, reset_state = model.step(*arguments)

        torch.testing.assert_close(first.motion_vector, reset.motion_vector, rtol=0, atol=0)
        torch.testing.assert_close(first_state, reset_state, rtol=0, atol=0)
        self.assertFalse(torch.equal(first.motion_vector, continued.motion_vector))
        self.assertFalse(torch.equal(first_state, continued_state))
        detached = model.detach_fusion_state(continued_state)
        self.assertFalse(detached.requires_grad)
        torch.testing.assert_close(detached, continued_state)

    def test_masked_sequence_matches_manual_steps_and_preserves_tail_state(self) -> None:
        seed_everything(107)
        model = CompactVIO(self.model_config).eval()
        batch = self._sequence_batch(steps=4, valid_steps=(2,))

        sequence = model.forward_sequence(
            batch.frame_pairs,
            batch.imu,
            batch.imu_lengths,
            batch.delta_time_s,
            batch.step_mask,
        )
        first, state = model.step(
            batch.frame_pairs[:, 0],
            batch.imu[:, 0],
            batch.imu_lengths[:, 0],
            batch.delta_time_s[:, 0],
        )
        second, state = model.step(
            batch.frame_pairs[:, 1],
            batch.imu[:, 1],
            batch.imu_lengths[:, 1],
            batch.delta_time_s[:, 1],
            state,
        )

        torch.testing.assert_close(
            sequence.motion_vector[:, 0], first.motion_vector, atol=1e-6, rtol=1e-5
        )
        torch.testing.assert_close(
            sequence.motion_vector[:, 1], second.motion_vector, atol=1e-6, rtol=1e-5
        )
        torch.testing.assert_close(
            sequence.motion_vector[:, 2:], torch.zeros(1, 2, 6), rtol=0, atol=0
        )
        torch.testing.assert_close(sequence.final_fusion_state, state, atol=1e-6, rtol=1e-5)

    def test_sequence_backward_reaches_first_step(self) -> None:
        seed_everything(109)
        model = CompactVIO(self.model_config).train()
        batch = self._sequence_batch(steps=4, valid_steps=(4,))
        frame_pairs = batch.frame_pairs.clone().requires_grad_(True)

        output = model.forward_sequence(
            frame_pairs,
            batch.imu,
            batch.imu_lengths,
            batch.delta_time_s,
            batch.step_mask,
        )
        output.motion_vector[:, -1].square().sum().backward()

        self.assertIsNotNone(frame_pairs.grad)
        self.assertGreater(float(frame_pairs.grad[:, 0].abs().sum()), 0.0)
        self.assertTrue(any(parameter.grad is not None for parameter in model.parameters()))

    def test_sequence_training_counts_only_unmasked_pairs(self) -> None:
        seed_everything(113)
        model = CompactVIO(self.model_config)
        batch = self._sequence_batch(steps=4, valid_steps=(4, 2))
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)

        metrics = train_one_epoch(
            model,
            (batch,),
            optimizer=optimizer,
            device="cpu",
            config=self.training_config,
        )

        self.assertEqual(metrics.samples, 6)
        self.assertTrue(torch.isfinite(torch.tensor(metrics.total_loss)))

    def test_stateful_evaluation_rejects_noncontiguous_chunk(self) -> None:
        seed_everything(127)
        model = CompactVIO(self.model_config)
        first = self._sequence_batch(
            steps=2,
            valid_steps=(2,),
            chain_ids=("one-chain",),
            chunk_indices=(0,),
            chain_starts=(True,),
            chain_ends=(False,),
        )
        skipped = self._sequence_batch(
            steps=2,
            valid_steps=(1,),
            chain_ids=("one-chain",),
            chunk_indices=(2,),
            chain_starts=(False,),
            chain_ends=(True,),
        )

        with self.assertRaisesRegex(ValueError, "exactly contiguous"):
            evaluate(model, (first, skipped), device="cpu", config=self.training_config)

    def test_sequence_inference_returns_cpu_motion_and_reusable_detached_state(self) -> None:
        seed_everything(131)
        model = CompactVIO(self.model_config)
        first = self._sequence_batch(steps=2, valid_steps=(2,))
        second = self._sequence_batch(steps=2, valid_steps=(2,))

        prediction = predict_sequence_batch(model, first, device="cpu")
        continued = predict_sequence_batch(
            model,
            second,
            device="cpu",
            initial_fusion_state=prediction.final_fusion_state,
        )
        reset = predict_sequence_batch(model, second, device="cpu")

        self.assertEqual(prediction.motion_vectors.shape, (1, 2, 6))
        self.assertEqual(prediction.motion_vectors.device.type, "cpu")
        self.assertEqual(prediction.final_fusion_state.shape, (1, 24))
        self.assertFalse(prediction.final_fusion_state.requires_grad)
        self.assertFalse(torch.equal(continued.motion_vectors, reset.motion_vectors))


if __name__ == "__main__":
    unittest.main()

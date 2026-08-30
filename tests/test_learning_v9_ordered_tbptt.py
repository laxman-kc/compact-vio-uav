from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from compact_vio.learning.cli import (
    InitialCheckpointIdentity,
    _checkpoint_split_id,
    _training_loader_policy,
    load_run_spec,
)
from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
from compact_vio.learning.errors import LearningError

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

if TORCH_AVAILABLE:
    import compact_vio.learning.training as training_module
    from compact_vio.learning.dataset import (
        EuRoCSequenceDataset,
        SampleIdentity,
        VIOSequenceBatch,
    )
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.training import (
        _trajectory_consistency_loss_with_state,
        evaluate,
        seed_everything,
        train_one_epoch,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V6_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v6_trajectory.json"
V8_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v8_long_finetune.json"
V9_CONFIG_PATH = (
    REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v9_ordered_tbptt_finetune.json"
)


class V9PolicyConfigTests(unittest.TestCase):
    def test_v9_is_v6_finetune_with_ordered_single_chunk_policy(self) -> None:
        v6 = json.loads(V6_CONFIG_PATH.read_text(encoding="utf-8"))
        v9 = json.loads(V9_CONFIG_PATH.read_text(encoding="utf-8"))
        normalized = copy.deepcopy(v9)
        normalized.pop("initialization")
        normalized.pop("training_sequence_state_policy")
        normalized["experiment_id"] = v6["experiment_id"]
        for field in ("epochs", "batch_size", "learning_rate", "trajectory_loss_weight"):
            normalized["optimization"][field] = v6["optimization"][field]

        self.assertEqual(normalized, v6)
        spec = load_run_spec(V9_CONFIG_PATH)
        self.assertEqual(spec.training.epochs, 5)
        self.assertEqual(spec.training.learning_rate, 3e-6)
        self.assertEqual(spec.training.trajectory_loss_weight, 0.01)
        self.assertEqual(spec.training.batch_size, 8)
        self.assertEqual(spec.training_unroll_pairs, 8)
        self.assertTrue(spec.initial_checkpoint_required)
        self.assertEqual(
            spec.training_sequence_state_policy,
            "carry-detached-fusion-and-pose-contiguous-chunks/v1",
        )
        self.assertEqual(_training_loader_policy(spec, spec.training), (1, False, True))

    def test_v8_loader_and_checkpoint_identity_remain_legacy(self) -> None:
        v8 = load_run_spec(V8_CONFIG_PATH)
        self.assertEqual(v8.training_sequence_state_policy, "reset-per-chunk/v1")
        self.assertEqual(_training_loader_policy(v8, v8.training), (1, True, False))
        legacy_identity = _checkpoint_split_id(v8, v8.training, smoke=False)
        self.assertNotIn("training-sequence-state-policy", legacy_identity)

        v9 = load_run_spec(V9_CONFIG_PATH)
        parent = InitialCheckpointIdentity(Path("/v6/checkpoint.pt"), "a" * 64, 23)
        identity = _checkpoint_split_id(
            v9,
            v9.training,
            smoke=False,
            initial_checkpoint=parent,
        )
        self.assertIn(
            "training-sequence-state-policy=carry-detached-fusion-and-pose-contiguous-chunks/v1",
            identity,
        )
        self.assertIn("training-loader=ordered-single-chunk/v1", identity)
        self.assertIn(f"initial-checkpoint-sha256={'a' * 64}", identity)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
    def test_smoke_prefix_ends_at_a_real_complete_chain(self) -> None:
        dataset = object.__new__(EuRoCSequenceDataset)
        dataset._chunks = (
            SimpleNamespace(chain_end=False),
            SimpleNamespace(chain_end=True),
            SimpleNamespace(chain_end=False),
            SimpleNamespace(chain_end=True),
        )
        self.assertEqual(dataset.complete_chain_prefix_indices(1), (0, 1))
        self.assertEqual(dataset.complete_chain_prefix_indices(3), (0, 1))
        self.assertEqual(dataset.complete_chain_prefix_indices(4), (0, 1, 2, 3))


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class V9OrderedTBPTTTests(unittest.TestCase):
    def setUp(self) -> None:
        seed_everything(909)
        self.model_config = ModelConfig(
            image_height_px=32,
            image_width_px=48,
            visual_feature_dim=16,
            imu_hidden_dim=8,
            fusion_hidden_dim=16,
            dropout_probability=0.0,
        )
        self.config = TrainingConfig(
            model=self.model_config,
            data=DataConfig(),
            batch_size=2,
            epochs=1,
            learning_rate=3e-5,
            trajectory_loss_weight=1.0,
            num_workers=0,
            use_amp=False,
        )

    def _chunk(
        self,
        *,
        chain_id: str,
        chunk_index: int,
        start: bool,
        end: bool,
        first_timestamp: int,
        sequence_id: str = "sequence",
    ) -> VIOSequenceBatch:
        identities = (
            SampleIdentity(sequence_id, first_timestamp, first_timestamp + 100),
            SampleIdentity(sequence_id, first_timestamp + 100, first_timestamp + 200),
        )
        return VIOSequenceBatch(
            frame_pairs=torch.randn(1, 2, 2, 32, 48),
            imu=torch.randn(1, 2, 3, 6),
            imu_lengths=torch.full((1, 2), 3, dtype=torch.int64),
            delta_time_s=torch.full((1, 2, 1), 0.05),
            target_motion=torch.randn(1, 2, 6) * 0.01,
            step_mask=torch.ones(1, 2, dtype=torch.bool),
            identities=(identities,),
            chain_ids=(chain_id,),
            chunk_indices=(chunk_index,),
            chain_starts=(start,),
            chain_ends=(end,),
        )

    def _optimizer(self, model: CompactVIO) -> torch.optim.Optimizer:
        return torch.optim.AdamW(model.parameters(), lr=self.config.learning_rate)

    def test_split_and_unsplit_cumulative_pose_endpoints_and_loss_match(self) -> None:
        prediction = torch.tensor(
            [
                [
                    [0.10, 0.01, 0.00, 0.00, 0.00, 0.05],
                    [0.08, 0.00, 0.01, 0.01, 0.00, 0.03],
                    [0.09, -0.01, 0.00, 0.00, 0.02, -0.02],
                    [0.07, 0.02, 0.00, -0.01, 0.00, 0.04],
                ]
            ]
        )
        target = prediction + torch.tensor([0.01, -0.005, 0.002, 0.001, -0.002, 0.003])
        mask = torch.ones(1, 4, dtype=torch.bool)

        full = _trajectory_consistency_loss_with_state(prediction, target, mask)
        first = _trajectory_consistency_loss_with_state(
            prediction[:, :2], target[:, :2], mask[:, :2]
        )
        second = _trajectory_consistency_loss_with_state(
            prediction[:, 2:],
            target[:, 2:],
            mask[:, 2:],
            predicted_initial_pose=first[3],
            reference_initial_pose=first[4],
        )

        torch.testing.assert_close((first[0] + second[0]) / 2.0, full[0])
        torch.testing.assert_close(second[3].position, full[3].position)
        torch.testing.assert_close(second[3].rotation, full[3].rotation)
        torch.testing.assert_close(second[4].position, full[4].position)
        torch.testing.assert_close(second[4].rotation, full[4].rotation)

    def test_training_carries_detached_fusion_and_pose_then_resets(self) -> None:
        class RecordingModel(CompactVIO):
            def __init__(inner_self, config: ModelConfig) -> None:
                super().__init__(config)
                inner_self.received_fusion_states: list[torch.Tensor | None] = []
                inner_self.produced_fusion_states: list[torch.Tensor] = []

            def forward_sequence(inner_self, *args: object, **kwargs: object):
                fusion_state = args[5] if len(args) > 5 else kwargs.get("fusion_state")
                inner_self.received_fusion_states.append(fusion_state)  # type: ignore[arg-type]
                output = super().forward_sequence(*args, **kwargs)  # type: ignore[arg-type]
                inner_self.produced_fusion_states.append(output.final_fusion_state)
                return output

        model = RecordingModel(self.model_config)
        chunks = (
            self._chunk(
                chain_id="chain-a",
                chunk_index=0,
                start=True,
                end=False,
                first_timestamp=100,
            ),
            self._chunk(
                chain_id="chain-a",
                chunk_index=1,
                start=False,
                end=True,
                first_timestamp=300,
            ),
            self._chunk(
                chain_id="chain-b",
                chunk_index=0,
                start=True,
                end=True,
                first_timestamp=1_000,
            ),
        )
        pose_inputs: list[tuple[object, object]] = []
        pose_outputs: list[tuple[object, object]] = []
        original = training_module._trajectory_consistency_loss_with_state

        def record_pose(*args: object, **kwargs: object):
            pose_inputs.append(
                (kwargs.get("predicted_initial_pose"), kwargs.get("reference_initial_pose"))
            )
            result = original(*args, **kwargs)  # type: ignore[arg-type]
            pose_outputs.append((result[3], result[4]))
            return result

        with mock.patch.object(
            training_module,
            "_trajectory_consistency_loss_with_state",
            side_effect=record_pose,
        ):
            metrics = train_one_epoch(
                model,
                chunks,
                optimizer=self._optimizer(model),
                device="cpu",
                config=self.config,
                carry_sequence_state=True,
            )

        self.assertEqual(metrics.samples, 6)
        self.assertIsNone(model.received_fusion_states[0])
        self.assertIsNone(model.received_fusion_states[2])
        carried_fusion = model.received_fusion_states[1]
        assert carried_fusion is not None
        self.assertFalse(carried_fusion.requires_grad)
        self.assertIsNone(carried_fusion.grad_fn)
        torch.testing.assert_close(carried_fusion, model.produced_fusion_states[0].detach())
        self.assertEqual(pose_inputs[0], (None, None))
        self.assertEqual(pose_inputs[2], (None, None))
        for carried, produced in zip(pose_inputs[1], pose_outputs[0], strict=True):
            assert carried is not None
            self.assertFalse(carried.position.requires_grad)
            self.assertFalse(carried.rotation.requires_grad)
            self.assertIsNone(carried.position.grad_fn)
            self.assertIsNone(carried.rotation.grad_fn)
            torch.testing.assert_close(carried.position, produced.position.detach())
            torch.testing.assert_close(carried.rotation, produced.rotation.detach())

    def test_carry_rejects_gaps_repeats_interleaving_and_unfinished_chains(self) -> None:
        cases = {
            "no preceding": (
                (
                    self._chunk(
                        chain_id="a",
                        chunk_index=1,
                        start=False,
                        end=True,
                        first_timestamp=300,
                    ),
                ),
                "no preceding",
            ),
            "chunk gap": (
                (
                    self._chunk(
                        chain_id="a",
                        chunk_index=0,
                        start=True,
                        end=False,
                        first_timestamp=100,
                    ),
                    self._chunk(
                        chain_id="a",
                        chunk_index=2,
                        start=False,
                        end=True,
                        first_timestamp=300,
                    ),
                ),
                "exactly contiguous",
            ),
            "timestamp gap": (
                (
                    self._chunk(
                        chain_id="a",
                        chunk_index=0,
                        start=True,
                        end=False,
                        first_timestamp=100,
                    ),
                    self._chunk(
                        chain_id="a",
                        chunk_index=1,
                        start=False,
                        end=True,
                        first_timestamp=400,
                    ),
                ),
                "boundary",
            ),
            "interleave": (
                (
                    self._chunk(
                        chain_id="a",
                        chunk_index=0,
                        start=True,
                        end=False,
                        first_timestamp=100,
                    ),
                    self._chunk(
                        chain_id="b",
                        chunk_index=0,
                        start=True,
                        end=True,
                        first_timestamp=1_000,
                    ),
                ),
                "interleave",
            ),
            "repeat": (
                (
                    self._chunk(
                        chain_id="a",
                        chunk_index=0,
                        start=True,
                        end=True,
                        first_timestamp=100,
                    ),
                    self._chunk(
                        chain_id="a",
                        chunk_index=0,
                        start=True,
                        end=True,
                        first_timestamp=500,
                    ),
                ),
                "repeated",
            ),
            "unfinished": (
                (
                    self._chunk(
                        chain_id="a",
                        chunk_index=0,
                        start=True,
                        end=False,
                        first_timestamp=100,
                    ),
                ),
                "before chain_end",
            ),
        }
        for name, (chunks, message) in cases.items():
            with self.subTest(name=name):
                model = CompactVIO(self.model_config)
                with self.assertRaisesRegex(LearningError, message):
                    train_one_epoch(
                        model,
                        chunks,
                        optimizer=self._optimizer(model),
                        device="cpu",
                        config=self.config,
                        carry_sequence_state=True,
                    )

    def test_validation_carries_cumulative_pose_under_the_same_chain_policy(self) -> None:
        model = CompactVIO(self.model_config)
        chunks = (
            self._chunk(
                chain_id="validation",
                chunk_index=0,
                start=True,
                end=False,
                first_timestamp=100,
            ),
            self._chunk(
                chain_id="validation",
                chunk_index=1,
                start=False,
                end=True,
                first_timestamp=300,
            ),
        )
        pose_inputs: list[tuple[object, object]] = []
        original = training_module._trajectory_consistency_loss_with_state

        def record_pose(*args: object, **kwargs: object):
            pose_inputs.append(
                (kwargs.get("predicted_initial_pose"), kwargs.get("reference_initial_pose"))
            )
            return original(*args, **kwargs)  # type: ignore[arg-type]

        with mock.patch.object(
            training_module,
            "_trajectory_consistency_loss_with_state",
            side_effect=record_pose,
        ):
            metrics = evaluate(
                model,
                chunks,
                device="cpu",
                config=self.config,
                carry_trajectory_pose_state=True,
            )

        self.assertEqual(metrics.samples, 4)
        self.assertEqual(pose_inputs[0], (None, None))
        for pose in pose_inputs[1]:
            assert pose is not None
            self.assertFalse(pose.position.requires_grad)
            self.assertFalse(pose.rotation.requires_grad)

    def test_legacy_sequence_training_still_resets_every_chunk(self) -> None:
        class RecordingModel(CompactVIO):
            def __init__(inner_self, config: ModelConfig) -> None:
                super().__init__(config)
                inner_self.states: list[torch.Tensor | None] = []

            def forward_sequence(inner_self, *args: object, **kwargs: object):
                state = args[5] if len(args) > 5 else kwargs.get("fusion_state")
                inner_self.states.append(state)  # type: ignore[arg-type]
                return super().forward_sequence(*args, **kwargs)  # type: ignore[arg-type]

        model = RecordingModel(self.model_config)
        chunks = (
            self._chunk(
                chain_id="legacy",
                chunk_index=8,
                start=False,
                end=False,
                first_timestamp=100,
            ),
            self._chunk(
                chain_id="other",
                chunk_index=3,
                start=False,
                end=False,
                first_timestamp=1_000,
            ),
        )
        train_one_epoch(
            model,
            chunks,
            optimizer=self._optimizer(model),
            device="cpu",
            config=self.config,
        )
        self.assertEqual(model.states, [None, None])


if __name__ == "__main__":
    unittest.main()

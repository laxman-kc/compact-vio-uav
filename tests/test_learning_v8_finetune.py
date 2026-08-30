from __future__ import annotations

import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from compact_vio.data.euroc import sha256_file
from compact_vio.learning.cli import (
    InitialCheckpointIdentity,
    _checkpoint_split_id,
    _initial_checkpoint_request,
    _load_initial_checkpoint,
    _save_epoch_checkpoint,
    build_parser,
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
    from compact_vio.learning.checkpoint import CheckpointProvenance, save_checkpoint
    from compact_vio.learning.model import CompactVIO


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
V6_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v6_trajectory.json"
V8_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v8_long_finetune.json"


class V8FineTuneConfigTests(unittest.TestCase):
    def test_v8_changes_only_allowed_experiment_optimization_and_sampling_fields(self) -> None:
        v6 = json.loads(V6_CONFIG_PATH.read_text(encoding="utf-8"))
        v8 = json.loads(V8_CONFIG_PATH.read_text(encoding="utf-8"))
        normalized = copy.deepcopy(v8)
        normalized.pop("initialization")
        normalized["experiment_id"] = v6["experiment_id"]
        normalized["optimization"]["epochs"] = v6["optimization"]["epochs"]
        normalized["optimization"]["learning_rate"] = v6["optimization"]["learning_rate"]
        normalized["sampling"]["unroll_pairs"] = v6["sampling"]["unroll_pairs"]

        self.assertEqual(normalized, v6)
        spec = load_run_spec(V8_CONFIG_PATH)
        self.assertEqual(spec.experiment_id, "euroc-compact-vio-v8-long-finetune")
        self.assertEqual(spec.training.epochs, 10)
        self.assertEqual(spec.training.learning_rate, 3e-5)
        self.assertEqual(spec.training.trajectory_loss_weight, 1.0)
        self.assertEqual(spec.training_unroll_pairs, 64)
        self.assertTrue(spec.initial_checkpoint_required)

    def test_initial_checkpoint_path_and_digest_are_required_together(self) -> None:
        self.assertIsNone(_initial_checkpoint_request(None, None))
        with self.assertRaisesRegex(LearningError, "this experiment requires"):
            _initial_checkpoint_request(None, None, required=True)
        for checkpoint, digest in (("parent.pt", None), (None, "a" * 64)):
            with (
                self.subTest(checkpoint=checkpoint, digest=digest),
                self.assertRaisesRegex(LearningError, "supplied together"),
            ):
                _initial_checkpoint_request(checkpoint, digest)
        with self.assertRaisesRegex(LearningError, "lowercase SHA-256"):
            _initial_checkpoint_request("parent.pt", "A" * 64)

    def test_parser_and_checkpoint_split_identity_bind_parent(self) -> None:
        args = build_parser().parse_args(
            [
                "--config",
                str(V8_CONFIG_PATH),
                "--data-root",
                "data",
                "--output-dir",
                "outputs/v8",
                "--initial-checkpoint",
                "outputs/v6/checkpoint.pt",
                "--initial-checkpoint-sha256",
                "a" * 64,
            ]
        )
        self.assertEqual(args.initial_checkpoint, "outputs/v6/checkpoint.pt")
        self.assertEqual(args.initial_checkpoint_sha256, "a" * 64)

        spec = load_run_spec(V8_CONFIG_PATH)
        parent = InitialCheckpointIdentity(Path("/parent/checkpoint.pt"), "a" * 64, 19)
        identity = _checkpoint_split_id(
            spec,
            spec.training,
            smoke=False,
            initial_checkpoint=parent,
        )
        self.assertIn(f"initial-checkpoint-sha256={'a' * 64}", identity)
        self.assertIn("initial-checkpoint-epoch=19", identity)
        self.assertEqual(
            parent.to_dict(),
            {"path": "/parent/checkpoint.pt", "sha256": "a" * 64, "epoch": 19},
        )


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class V8FineTuneCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.split_sha256 = "f" * 64
        self.source_sha256 = {"train": "a" * 64, "validation": "b" * 64}
        self.calibration_sha256 = {"train": "c" * 64, "validation": "d" * 64}
        self.model_config = ModelConfig(
            image_height_px=32,
            image_width_px=48,
            visual_feature_dim=16,
            imu_hidden_dim=8,
            fusion_hidden_dim=16,
            dropout_probability=0.0,
        )
        self.parent_config = TrainingConfig(
            model=self.model_config,
            data=DataConfig(image_mean=0.45),
            batch_size=8,
            epochs=30,
            learning_rate=3e-4,
            trajectory_loss_weight=1.0,
            num_workers=0,
            use_amp=False,
        )
        self.runtime_config = replace(
            self.parent_config,
            batch_size=64,
            epochs=10,
            learning_rate=3e-5,
        )
        self.provenance = CheckpointProvenance.create(
            dataset_id="synthetic-vio",
            split_id=f"parent:split={self.split_sha256}:unroll=8:mode=full",
            train_sequence_ids=("train",),
            validation_sequence_ids=("validation",),
            source_sha256=self.source_sha256,
            calibration_sha256=self.calibration_sha256,
            code_revision="parent-revision",
        )

    def _save_parent(self, path: Path) -> CompactVIO:
        torch.manual_seed(811)
        model = CompactVIO(self.model_config)
        optimizer = torch.optim.AdamW(model.parameters(), lr=0.9)
        optimizer.zero_grad(set_to_none=True)
        sum(parameter.square().sum() for parameter in model.parameters()).backward()
        optimizer.step()
        self.assertTrue(optimizer.state)
        save_checkpoint(
            path,
            model=model,
            optimizer=optimizer,
            config=self.parent_config,
            epoch=23,
            metrics={"validation/total_loss": 0.25},
            provenance=self.provenance,
        )
        return model

    def test_loads_parent_weights_but_starts_with_fresh_optimizer_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parent.pt"
            parent_model = self._save_parent(path)
            digest = sha256_file(path)
            torch.manual_seed(812)
            model = CompactVIO(self.model_config)

            identity = _load_initial_checkpoint(
                path,
                expected_sha256=digest,
                model=model,
                runtime_config=self.runtime_config,
                dataset_id="synthetic-vio",
                split_sha256=self.split_sha256,
                train_sequence_ids=("train",),
                validation_sequence_ids=("validation",),
                source_sha256=self.source_sha256,
                calibration_sha256=self.calibration_sha256,
            )

            for expected, actual in zip(parent_model.parameters(), model.parameters(), strict=True):
                torch.testing.assert_close(expected, actual, rtol=0, atol=0)
            fresh_optimizer = torch.optim.AdamW(
                model.parameters(),
                lr=self.runtime_config.learning_rate,
                weight_decay=self.runtime_config.weight_decay,
            )
            self.assertFalse(fresh_optimizer.state)
            self.assertEqual(fresh_optimizer.param_groups[0]["lr"], 3e-5)
            self.assertEqual(identity.epoch, 23)
            self.assertEqual(identity.sha256, digest)
            self.assertEqual(identity.path, path.resolve())

    def test_retained_epoch_checkpoint_is_weights_only_and_exactly_identified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            model = CompactVIO(self.model_config)

            identity = _save_epoch_checkpoint(
                output,
                model=model,
                config=self.runtime_config,
                epoch=7,
                metrics={"validation/total_loss": 0.125},
                provenance=self.provenance,
            )
            payload = torch.load(identity.path, map_location="cpu", weights_only=True)

            self.assertEqual(identity.path, (output / "epoch-checkpoints/epoch-0007.pt").resolve())
            self.assertEqual(identity.sha256, sha256_file(identity.path))
            self.assertEqual(identity.epoch, 7)
            self.assertEqual(payload["epoch"], 7)
            self.assertIsNone(payload["optimizer_state_dict"])
            self.assertEqual(
                identity.to_dict(),
                {"path": str(identity.path), "sha256": identity.sha256, "epoch": 7},
            )

    def test_rejects_wrong_digest_or_changed_data_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parent.pt"
            self._save_parent(path)
            digest = sha256_file(path)
            with self.assertRaisesRegex(LearningError, "SHA-256 mismatch"):
                _load_initial_checkpoint(
                    path,
                    expected_sha256="0" * 64,
                    model=CompactVIO(self.model_config),
                    runtime_config=self.runtime_config,
                    dataset_id="synthetic-vio",
                    split_sha256=self.split_sha256,
                    train_sequence_ids=("train",),
                    validation_sequence_ids=("validation",),
                    source_sha256=self.source_sha256,
                    calibration_sha256=self.calibration_sha256,
                )
            with self.assertRaisesRegex(LearningError, "data configuration differs"):
                _load_initial_checkpoint(
                    path,
                    expected_sha256=digest,
                    model=CompactVIO(self.model_config),
                    runtime_config=replace(
                        self.runtime_config,
                        data=replace(self.runtime_config.data, image_mean=0.5),
                    ),
                    dataset_id="synthetic-vio",
                    split_sha256=self.split_sha256,
                    train_sequence_ids=("train",),
                    validation_sequence_ids=("validation",),
                    source_sha256=self.source_sha256,
                    calibration_sha256=self.calibration_sha256,
                )


if __name__ == "__main__":
    unittest.main()

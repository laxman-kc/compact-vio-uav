from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from compact_vio.learning.cli import (
    _bounded_subset_indices,
    _empirical_percentile,
    _prepare_output_directory,
    _runtime_training_config,
    build_parser,
    load_run_spec,
)
from compact_vio.learning.errors import LearningError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v1.json"
STRIDE_CONFIG_PATH = REPOSITORY_ROOT / "configs/training/euroc_compact_vio_v2_stride_augmented.json"
SPLIT_PATH = REPOSITORY_ROOT / "configs/data/euroc_vicon_v1.json"


class LearningCliTests(unittest.TestCase):
    def test_checked_in_experiment_and_split_bind_exact_runtime_config(self) -> None:
        spec = load_run_spec(CONFIG_PATH)

        self.assertEqual(spec.experiment_id, "euroc-compact-vio-v1")
        self.assertEqual(spec.dataset_doi, "10.3929/ethz-b-000690084")
        self.assertEqual(spec.training.model.image_width_px, 256)
        self.assertEqual(spec.training.model.image_height_px, 160)
        self.assertEqual(spec.training.data.image_mean, 0.5)
        self.assertEqual(spec.training.data.image_std, 0.25)
        self.assertEqual(spec.training_frame_strides, (1,))
        self.assertEqual(
            spec.splits.train,
            ("V1_02_medium", "V2_01_easy", "V2_02_medium"),
        )
        self.assertEqual(spec.splits.validation, ("V1_03_difficult",))
        self.assertEqual(spec.splits.test, ("V2_03_difficult",))
        self.assertEqual(len(spec.config_sha256), 64)
        self.assertEqual(len(spec.split_sha256), 64)
        self.assertEqual(
            spec.archive_sha256_by_sequence()["V2_03_difficult"],
            "6daf2cbc2de9a6bc4e02866c99ed01c29a5c7c164756f06c4f72656192977cfc",
        )

    def test_stride_augmented_config_retains_v1_model_and_declares_two_strides(self) -> None:
        baseline = load_run_spec(CONFIG_PATH)
        augmented = load_run_spec(STRIDE_CONFIG_PATH)

        self.assertEqual(augmented.training, baseline.training)
        self.assertEqual(augmented.training_frame_strides, (1, 2))
        self.assertEqual(
            augmented.experiment_id,
            "euroc-compact-vio-v2-stride-augmented",
        )

    def test_overlapping_integration_and_train_split_is_rejected(self) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        split = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
        split["development_split"]["integration_only"] = ["V1_02_medium"]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            split_path = root / "split.json"
            config_path = root / "config.json"
            split_path.write_text(json.dumps(split), encoding="utf-8")
            config["split_manifest"] = str(split_path)
            config_path.write_text(json.dumps(config), encoding="utf-8")

            with self.assertRaisesRegex(LearningError, "must be disjoint"):
                load_run_spec(config_path)

    def test_nonempty_output_directory_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            output.mkdir()
            (output / "existing.json").write_text("{}", encoding="utf-8")

            with self.assertRaisesRegex(LearningError, "non-empty"):
                _prepare_output_directory(output)

    def test_parser_declares_only_supported_devices(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--config",
                "config.json",
                "--data-root",
                "data",
                "--output-dir",
                "outputs/run",
                "--device",
                "cuda",
                "--smoke",
            ]
        )
        self.assertEqual(args.device, "cuda")
        self.assertTrue(args.smoke)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "--config",
                    "config.json",
                    "--data-root",
                    "data",
                    "--output-dir",
                    "outputs/run",
                    "--device",
                    "metal",
                ]
            )

    def test_smoke_runtime_config_changes_only_epoch_budget(self) -> None:
        declared = load_run_spec(CONFIG_PATH).training
        smoke = _runtime_training_config(declared, smoke=True)
        self.assertEqual(smoke.epochs, 2)
        self.assertEqual(smoke.model, declared.model)
        self.assertEqual(smoke.data, declared.data)
        self.assertEqual(smoke.batch_size, declared.batch_size)
        self.assertEqual(_runtime_training_config(declared, smoke=False), declared)

    def test_smoke_subset_is_deterministic_and_spans_the_full_dataset(self) -> None:
        self.assertEqual(_bounded_subset_indices(5, 10), (0, 1, 2, 3, 4))
        selected = _bounded_subset_indices(1000, 64)
        self.assertEqual(len(selected), 64)
        self.assertEqual(selected[0], 0)
        self.assertEqual(selected[-1], 999)
        self.assertEqual(len(set(selected)), len(selected))

    def test_empirical_percentile_uses_nearest_rank(self) -> None:
        values = (0.04, 0.01, 0.03, 0.02)
        self.assertEqual(_empirical_percentile(values, 0.5), 0.02)
        self.assertEqual(_empirical_percentile(values, 0.95), 0.04)


if __name__ == "__main__":
    unittest.main()

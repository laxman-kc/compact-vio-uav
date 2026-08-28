from __future__ import annotations

import csv
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

try:
    import torch
    from PIL import Image

    TORCH_STACK_AVAILABLE = True
except ImportError:
    TORCH_STACK_AVAILABLE = False

if TORCH_STACK_AVAILABLE:
    from compact_vio.data.euroc import load_euroc_sequence
    from compact_vio.learning.checkpoint import (
        CheckpointProvenance,
        load_checkpoint,
        save_checkpoint,
    )
    from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
    from compact_vio.learning.dataset import (
        EuRoCPairDataset,
        SampleIdentity,
        VIOBatch,
        collate_vio_batch,
    )
    from compact_vio.learning.inference import predict_batch
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.training import motion_loss, seed_everything


def _transform() -> dict[str, object]:
    return {
        "rows": 4,
        "cols": 4,
        "data": [
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
        ],
    }


def _write_csv(path: Path, header: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _write_asl_fixture(directory: str) -> Path:
    root = Path(directory) / "V1_01_easy"
    camera = root / "mav0/cam0"
    imu = root / "mav0/imu0"
    ground_truth = root / "mav0/state_groundtruth_estimate0"
    (camera / "data").mkdir(parents=True)
    imu.mkdir(parents=True)
    ground_truth.mkdir(parents=True)
    camera_yaml = {
        "sensor_type": "camera",
        "comment": "test",
        "T_BS": _transform(),
        "rate_hz": 20,
        "resolution": [6, 4],
        "camera_model": "pinhole",
        "intrinsics": [4.0, 4.0, 3.0, 2.0],
        "distortion_model": "radial-tangential",
        "distortion_coefficients": [0.0, 0.0, 0.0, 0.0],
    }
    imu_yaml = {
        "sensor_type": "imu",
        "comment": "test",
        "T_BS": _transform(),
        "rate_hz": 200,
        "gyroscope_noise_density": 0.001,
        "gyroscope_random_walk": 0.001,
        "accelerometer_noise_density": 0.01,
        "accelerometer_random_walk": 0.01,
    }
    ground_truth_yaml = {
        "sensor_type": "visual-inertial",
        "comment": "test",
        "T_BS": _transform(),
        "rate_hz": 100,
    }
    for path, content in (
        (camera / "sensor.yaml", camera_yaml),
        (imu / "sensor.yaml", imu_yaml),
        (ground_truth / "sensor.yaml", ground_truth_yaml),
    ):
        path.write_text(json.dumps(content), encoding="utf-8")
    for timestamp, value in ((100, 32), (200, 96), (300, 160)):
        Image.new("L", (6, 4), color=value).save(camera / "data" / f"{timestamp}.png")
    _write_csv(
        camera / "data.csv",
        ("#timestamp [ns]", "filename"),
        [(100, "100.png"), (200, "200.png"), (300, "300.png")],
    )
    _write_csv(
        imu / "data.csv",
        (
            "#timestamp [ns]",
            "w_RS_S_x [rad s^-1]",
            "w_RS_S_y [rad s^-1]",
            "w_RS_S_z [rad s^-1]",
            "a_RS_S_x [m s^-2]",
            "a_RS_S_y [m s^-2]",
            "a_RS_S_z [m s^-2]",
        ),
        [
            (100, 99, 99, 99, 99, 99, 99),
            (150, 1, 2, 3, 4, 5, 6),
            (200, 2, 3, 4, 5, 6, 7),
            (250, 3, 4, 5, 6, 7, 8),
            (300, 4, 5, 6, 7, 8, 9),
        ],
    )
    gt_header = (
        "#timestamp",
        "p_RS_R_x [m]",
        "p_RS_R_y [m]",
        "p_RS_R_z [m]",
        "q_RS_w []",
        "q_RS_x []",
        "q_RS_y []",
        "q_RS_z []",
        "v_RS_R_x [m s^-1]",
        "v_RS_R_y [m s^-1]",
        "v_RS_R_z [m s^-1]",
        "b_w_RS_S_x [rad s^-1]",
        "b_w_RS_S_y [rad s^-1]",
        "b_w_RS_S_z [rad s^-1]",
        "b_a_RS_S_x [m s^-2]",
        "b_a_RS_S_y [m s^-2]",
        "b_a_RS_S_z [m s^-2]",
    )
    _write_csv(
        ground_truth / "data.csv",
        gt_header,
        [
            (100, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            (200, 1, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            (300, 2, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        ],
    )
    return root


@unittest.skipUnless(TORCH_STACK_AVAILABLE, "PyTorch and Pillow training extras are not installed")
class LearningTorchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model_config = ModelConfig(
            image_height_px=32,
            image_width_px=48,
            visual_feature_dim=32,
            imu_hidden_dim=16,
            fusion_hidden_dim=32,
            dropout_probability=0.0,
        )
        self.training_config = TrainingConfig(
            model=self.model_config,
            data=DataConfig(),
            batch_size=2,
            epochs=1,
            num_workers=0,
            use_amp=False,
        )

    def _batch(self) -> VIOBatch:
        identities = (
            SampleIdentity("synthetic", 100, 200),
            SampleIdentity("synthetic", 200, 300),
        )
        return VIOBatch(
            frame_pairs=torch.randn(2, 2, 32, 48),
            imu=torch.randn(2, 4, 6),
            imu_lengths=torch.tensor([4, 2]),
            delta_time_s=torch.tensor([[0.05], [0.05]]),
            target_motion=torch.randn(2, 6),
            identities=identities,
        )

    def test_model_shapes_finite_loss_and_backpropagation(self) -> None:
        seed_everything(11)
        model = CompactVIO(self.model_config)
        batch = self._batch()
        output = model(
            batch.frame_pairs,
            batch.imu,
            batch.imu_lengths,
            batch.delta_time_s,
        )
        self.assertEqual(output.relative_translation_m.shape, (2, 3))
        self.assertEqual(output.relative_rotation_vector_rad.shape, (2, 3))
        total, _, _ = motion_loss(
            output.motion_vector,
            batch.target_motion,
            translation_weight=1.0,
            rotation_weight=10.0,
        )
        self.assertTrue(torch.isfinite(total))
        total.backward()
        self.assertTrue(any(parameter.grad is not None for parameter in model.parameters()))

    def test_eval_inference_is_deterministic_and_ignores_imu_padding(self) -> None:
        seed_everything(13)
        model = CompactVIO(self.model_config)
        batch = self._batch()
        first = predict_batch(model, batch)
        second = predict_batch(model, batch)
        torch.testing.assert_close(first.motion_vectors, second.motion_vectors, rtol=0, atol=0)
        altered_imu = batch.imu.clone()
        altered_imu[1, 2:] = 10000.0
        altered = VIOBatch(
            frame_pairs=batch.frame_pairs,
            imu=altered_imu,
            imu_lengths=batch.imu_lengths,
            delta_time_s=batch.delta_time_s,
            target_motion=batch.target_motion,
            identities=batch.identities,
        )
        padded = predict_batch(model, altered)
        torch.testing.assert_close(
            first.motion_vectors[1], padded.motion_vectors[1], rtol=0, atol=0
        )

    def test_dataset_consumes_exact_causal_imu_window_and_collates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sequence = load_euroc_sequence(_write_asl_fixture(directory))
            dataset = EuRoCPairDataset(
                (sequence,),
                model_config=self.model_config,
                data_config=DataConfig(
                    gyroscope_scale_rad_s=1.0,
                    accelerometer_scale_m_s2=1.0,
                ),
            )
            first = dataset[0]
            second = dataset[1]
            self.assertEqual(len(dataset), 2)
            self.assertEqual(first["imu"][:, 0].tolist(), [1.0, 2.0])
            self.assertFalse(torch.any(first["imu"] == 99.0))
            self.assertEqual(first["target_motion"][:3].tolist(), [1.0, 0.0, 0.0])
            batch = collate_vio_batch((first, second))
            self.assertEqual(batch.frame_pairs.shape, (2, 2, 32, 48))
            self.assertEqual(batch.imu.shape, (2, 2, 6))
            self.assertEqual(batch.imu_lengths.tolist(), [2, 2])

    def test_dataset_rejects_mismatched_imu_and_label_transform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sequence = load_euroc_sequence(_write_asl_fixture(directory))
            transform = list(list(row) for row in sequence.ground_truth_calibration.t_bs)
            transform[0][3] = 0.1
            mismatched = replace(
                sequence,
                ground_truth_calibration=replace(
                    sequence.ground_truth_calibration,
                    t_bs=tuple(tuple(row) for row in transform),
                ),
            )
            with self.assertRaisesRegex(ValueError, "different IMU and ground-truth"):
                EuRoCPairDataset((mismatched,), model_config=self.model_config)

    def test_checkpoint_round_trip_restores_predictions_and_metadata(self) -> None:
        seed_everything(17)
        model = CompactVIO(self.model_config)
        batch = self._batch()
        expected = predict_batch(model, batch).motion_vectors
        digest = "a" * 64
        provenance = CheckpointProvenance.create(
            dataset_id="EuRoC DOI 10.3929/ethz-b-000690084",
            split_id="test-split-v1",
            train_sequence_ids=("V1_01_easy",),
            validation_sequence_ids=("V2_01_easy",),
            source_sha256={"V1_01_easy": digest, "V2_01_easy": "b" * 64},
            calibration_sha256={"V1_01_easy": "c" * 64, "V2_01_easy": "d" * 64},
            code_revision="test-revision",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "checkpoint.pt"
            save_checkpoint(
                path,
                model=model,
                config=self.training_config,
                epoch=1,
                metrics={"validation/total_loss": 0.25},
                provenance=provenance,
            )
            restored = CompactVIO(self.model_config)
            metadata = load_checkpoint(path, model=restored)
            actual = predict_batch(restored, batch).motion_vectors
        torch.testing.assert_close(expected, actual, rtol=0, atol=0)
        self.assertEqual(metadata.epoch, 1)
        self.assertEqual(metadata.config, self.training_config)
        self.assertEqual(metadata.provenance, provenance)


if __name__ == "__main__":
    unittest.main()

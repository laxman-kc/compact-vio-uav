from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import torch
    from PIL import Image

    TORCH_STACK_AVAILABLE = True
except ImportError:
    TORCH_STACK_AVAILABLE = False

if TORCH_STACK_AVAILABLE:
    from compact_vio.data.euroc import (
        CameraCalibration,
        CameraFrame,
        EuRoCSensorSequence,
        ImuCalibration,
        ImuMeasurement,
    )
    from compact_vio.learning.config import DataConfig, ModelConfig
    from compact_vio.learning.dataset import (
        EuRoCInferencePairDataset,
        EuRoCInferenceSequenceDataset,
        SampleIdentity,
        VIOBatch,
        VIOSequenceBatch,
        collate_vio_batch,
        collate_vio_sequence_batch,
    )


_IDENTITY_TRANSFORM = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _sensor_sequence(
    root: Path,
    *,
    sequence_id: str,
    frame_count: int = 7,
) -> EuRoCSensorSequence:
    sequence_root = root / sequence_id
    image_root = sequence_root / "images"
    image_root.mkdir(parents=True)
    source_path = sequence_root / "sensor.yaml"
    timestamps = tuple(100_000_000 + index * 50_000_000 for index in range(frame_count))
    frames: list[CameraFrame] = []
    for index, timestamp_ns in enumerate(timestamps):
        image_path = image_root / f"{timestamp_ns}.png"
        Image.new("L", (12, 8), color=20 + index * 20).save(image_path)
        frames.append(
            CameraFrame(
                timestamp_ns=timestamp_ns,
                filename=image_path.name,
                image_path=image_path,
            )
        )

    imu: list[ImuMeasurement] = []
    for interval_index, current_timestamp_ns in enumerate(timestamps[1:], start=1):
        for timestamp_ns, multiplier in (
            (current_timestamp_ns - 25_000_000, 1.0),
            (current_timestamp_ns, 2.0),
        ):
            imu.append(
                ImuMeasurement(
                    timestamp_ns=timestamp_ns,
                    angular_velocity_rs_s_rad_s=(
                        interval_index * 2.0 * multiplier,
                        interval_index * 4.0 * multiplier,
                        interval_index * 6.0 * multiplier,
                    ),
                    linear_acceleration_rs_s_m_s2=(
                        interval_index * 8.0 * multiplier,
                        interval_index * 10.0 * multiplier,
                        interval_index * 12.0 * multiplier,
                    ),
                )
            )

    return EuRoCSensorSequence(
        sequence_id=sequence_id,
        root=sequence_root,
        camera_calibration=CameraCalibration(
            sensor_type="camera",
            comment="inference-dataset-test",
            t_bs=_IDENTITY_TRANSFORM,
            rate_hz=20.0,
            resolution_width_px=12,
            resolution_height_px=8,
            camera_model="pinhole",
            intrinsics=(8.0, 8.0, 6.0, 4.0),
            distortion_model="radial-tangential",
            distortion_coefficients=(0.0, 0.0, 0.0, 0.0),
            source_path=source_path,
        ),
        imu_calibration=ImuCalibration(
            sensor_type="imu",
            comment="inference-dataset-test",
            t_bs=_IDENTITY_TRANSFORM,
            rate_hz=200.0,
            gyroscope_noise_density=0.001,
            gyroscope_random_walk=0.001,
            accelerometer_noise_density=0.01,
            accelerometer_random_walk=0.01,
            source_path=source_path,
        ),
        camera_frames=tuple(frames),
        imu_measurements=tuple(imu),
    )


@unittest.skipUnless(TORCH_STACK_AVAILABLE, "PyTorch and Pillow training extras are not installed")
class EuRoCInferenceDatasetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.model_config = ModelConfig(
            image_height_px=8,
            image_width_px=12,
            visual_feature_dim=16,
            imu_hidden_dim=8,
            fusion_hidden_dim=16,
            dropout_probability=0.0,
        )
        self.data_config = DataConfig(
            image_mean=0.25,
            image_std=0.5,
            gyroscope_scale_rad_s=2.0,
            accelerometer_scale_m_s2=4.0,
        )

    @staticmethod
    def _identities(sample: dict[str, object]) -> tuple[SampleIdentity, ...]:
        identities = sample["identities"]
        assert isinstance(identities, tuple)
        return identities

    def test_pair_dataset_preserves_native_pairs_windows_and_normalization(self) -> None:
        sequence = _sensor_sequence(self.root, sequence_id="MH_01_easy")
        dataset = EuRoCInferencePairDataset(
            (sequence,),
            model_config=self.model_config,
            data_config=self.data_config,
        )

        self.assertFalse(hasattr(sequence, "ground_truth_states"))
        self.assertFalse(dataset.target_motion_is_reference)
        self.assertEqual(dataset.frame_strides, (1,))
        self.assertEqual(len(dataset), len(sequence.camera_frames) - 1)

        first = dataset[0]
        identity = first["identity"]
        self.assertEqual(
            identity,
            SampleIdentity(
                sequence_id="MH_01_easy",
                previous_timestamp_ns=100_000_000,
                current_timestamp_ns=150_000_000,
            ),
        )
        self.assertEqual(first["delta_time_s"].tolist(), [0.05000000074505806])
        self.assertEqual(
            first["imu"].tolist(),
            [
                [1.0, 2.0, 3.0, 2.0, 2.5, 3.0],
                [2.0, 4.0, 6.0, 4.0, 5.0, 6.0],
            ],
        )
        expected_pixel = ((20.0 / 255.0) - 0.25) / 0.5
        torch.testing.assert_close(
            first["frame_pair"][0],
            torch.full((8, 12), expected_pixel),
        )
        self.assertTrue(torch.equal(first["target_motion"], torch.zeros(6)))

        batch = collate_vio_batch((dataset[0], dataset[1]))
        self.assertIsInstance(batch, VIOBatch)
        self.assertEqual(batch.imu_lengths.tolist(), [2, 2])
        self.assertTrue(torch.equal(batch.target_motion, torch.zeros(2, 6)))

    def test_sequence_dataset_has_one_chain_retains_tail_and_exact_coverage(self) -> None:
        sequences = (
            _sensor_sequence(self.root, sequence_id="MH_01_easy"),
            _sensor_sequence(self.root, sequence_id="MH_02_easy"),
        )
        pair_dataset = EuRoCInferencePairDataset(
            sequences,
            model_config=self.model_config,
            data_config=self.data_config,
        )
        sequence_dataset = EuRoCInferenceSequenceDataset(
            sequences,
            unroll_pairs=4,
            model_config=self.model_config,
            data_config=self.data_config,
        )

        self.assertEqual(sequence_dataset.pair_count, 12)
        self.assertEqual(sequence_dataset.pair_count, len(pair_dataset))
        self.assertEqual(len(sequence_dataset), 4)
        self.assertEqual(
            tuple(
                (
                    sample["chain_id"],
                    sample["chunk_index"],
                    sample["chain_start"],
                    sample["chain_end"],
                    sample["frame_pairs"].shape[0],
                )
                for sample in (sequence_dataset[index] for index in range(len(sequence_dataset)))
            ),
            (
                ("MH_01_easy", 0, True, False, 4),
                ("MH_01_easy", 1, False, True, 2),
                ("MH_02_easy", 0, True, False, 4),
                ("MH_02_easy", 1, False, True, 2),
            ),
        )

        pair_identities = tuple(
            pair_dataset[index]["identity"] for index in range(len(pair_dataset))
        )
        sequence_identities = tuple(
            identity
            for index in range(len(sequence_dataset))
            for identity in self._identities(sequence_dataset[index])
        )
        self.assertEqual(sequence_identities, pair_identities)
        self.assertEqual(len(sequence_identities), len(set(sequence_identities)))
        for index in range(len(sequence_dataset)):
            sample = sequence_dataset[index]
            self.assertTrue(
                torch.equal(
                    sample["target_motion"],
                    torch.zeros(sample["frame_pairs"].shape[0], 6),
                )
            )

        batch = collate_vio_sequence_batch((sequence_dataset[0], sequence_dataset[1]))
        self.assertIsInstance(batch, VIOSequenceBatch)
        self.assertEqual(
            batch.step_mask.tolist(),
            [[True, True, True, True], [True, True, False, False]],
        )
        self.assertTrue(torch.equal(batch.target_motion, torch.zeros(2, 4, 6)))

    def test_invalid_inputs_cannot_enable_labels_stride_or_empty_chains(self) -> None:
        sequence = _sensor_sequence(self.root, sequence_id="MH_01_easy")
        with self.assertRaisesRegex(ValueError, "EuRoCSensorSequence"):
            EuRoCInferencePairDataset((object(),))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            EuRoCInferencePairDataset((sequence,), frame_strides=(2,))  # type: ignore[call-arg]
        for invalid in (0, -1, 1.5, True):
            with (
                self.subTest(unroll_pairs=invalid),
                self.assertRaisesRegex(ValueError, "unroll_pairs"),
            ):
                EuRoCInferenceSequenceDataset(
                    (sequence,),
                    unroll_pairs=invalid,  # type: ignore[arg-type]
                )

        one_frame = _sensor_sequence(
            self.root,
            sequence_id="MH_one_frame",
            frame_count=1,
        )
        with self.assertRaisesRegex(ValueError, "no native stride-one causal frame pair"):
            EuRoCInferencePairDataset((one_frame,))


if __name__ == "__main__":
    unittest.main()

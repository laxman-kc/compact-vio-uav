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
        EuRoCSequence,
        GroundTruthCalibration,
        GroundTruthState,
        ImuCalibration,
        ImuMeasurement,
    )
    from compact_vio.learning.config import DataConfig, ModelConfig
    from compact_vio.learning.dataset import (
        EuRoCPairDataset,
        EuRoCSequenceDataset,
        SampleIdentity,
        VIOSequenceBatch,
        collate_vio_sequence_batch,
    )


_IDENTITY_TRANSFORM = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _sequence(root: Path, *, sequence_id: str, frame_count: int = 7) -> EuRoCSequence:
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
    imu = tuple(
        ImuMeasurement(
            timestamp_ns=timestamp_ns,
            angular_velocity_rs_s_rad_s=(float(index), 0.0, 0.0),
            linear_acceleration_rs_s_m_s2=(0.0, float(index), 0.0),
        )
        for index, timestamp_ns in enumerate(timestamps[1:], start=1)
    )
    ground_truth = tuple(
        GroundTruthState(
            timestamp_ns=timestamp_ns,
            position_rs_r_m=(float(index), 0.0, 0.0),
            quaternion_rs_wxyz=(1.0, 0.0, 0.0, 0.0),
            velocity_rs_r_m_s=(0.0, 0.0, 0.0),
            gyroscope_bias_rs_s_rad_s=(0.0, 0.0, 0.0),
            accelerometer_bias_rs_s_m_s2=(0.0, 0.0, 0.0),
        )
        for index, timestamp_ns in enumerate(timestamps)
    )
    return EuRoCSequence(
        sequence_id=sequence_id,
        root=sequence_root,
        camera_calibration=CameraCalibration(
            sensor_type="camera",
            comment="sequence-dataset-test",
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
            comment="sequence-dataset-test",
            t_bs=_IDENTITY_TRANSFORM,
            rate_hz=200.0,
            gyroscope_noise_density=0.001,
            gyroscope_random_walk=0.001,
            accelerometer_noise_density=0.01,
            accelerometer_random_walk=0.01,
            source_path=source_path,
        ),
        ground_truth_calibration=GroundTruthCalibration(
            sensor_type="visual-inertial",
            comment="sequence-dataset-test",
            t_bs=_IDENTITY_TRANSFORM,
            rate_hz=100.0,
            source_path=source_path,
        ),
        camera_frames=tuple(frames),
        imu_measurements=imu,
        ground_truth_states=ground_truth,
    )


@unittest.skipUnless(TORCH_STACK_AVAILABLE, "PyTorch and Pillow training extras are not installed")
class EuRoCSequenceDatasetTests(unittest.TestCase):
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
            gyroscope_scale_rad_s=1.0,
            accelerometer_scale_m_s2=1.0,
        )

    @staticmethod
    def _identities(sample: dict[str, object]) -> tuple[SampleIdentity, ...]:
        identities = sample["identities"]
        assert isinstance(identities, tuple)
        return identities

    def test_stride_one_chunks_remain_chronological_and_retain_tail(self) -> None:
        sequence = _sequence(self.root, sequence_id="sequence-a")
        dataset = EuRoCSequenceDataset(
            (sequence,),
            unroll_pairs=4,
            model_config=self.model_config,
            data_config=self.data_config,
        )

        self.assertEqual(dataset.pair_count, 6)
        self.assertEqual(len(dataset), 2)
        first, tail = dataset[0], dataset[1]
        self.assertEqual(first["chunk_index"], 0)
        self.assertTrue(first["chain_start"])
        self.assertFalse(first["chain_end"])
        self.assertEqual(tail["chunk_index"], 1)
        self.assertFalse(tail["chain_start"])
        self.assertTrue(tail["chain_end"])
        identities = self._identities(first) + self._identities(tail)
        self.assertEqual(
            tuple(identity.previous_timestamp_ns for identity in identities),
            tuple(frame.timestamp_ns for frame in sequence.camera_frames[:-1]),
        )
        self.assertTrue(
            all(
                left.current_timestamp_ns == right.previous_timestamp_ns
                for left, right in zip(identities[:-1], identities[1:], strict=True)
            )
        )

    def test_stride_two_uses_separate_even_and_odd_phase_chains(self) -> None:
        sequence = _sequence(self.root, sequence_id="sequence-a")
        dataset = EuRoCSequenceDataset(
            (sequence,),
            unroll_pairs=8,
            model_config=self.model_config,
            data_config=self.data_config,
            frame_strides=(2,),
        )

        self.assertEqual(dataset.pair_count, 5)
        self.assertEqual(len(dataset), 2)
        even = self._identities(dataset[0])
        odd = self._identities(dataset[1])
        timestamps = tuple(frame.timestamp_ns for frame in sequence.camera_frames)
        self.assertEqual(
            tuple((item.previous_timestamp_ns, item.current_timestamp_ns) for item in even),
            (
                (timestamps[0], timestamps[2]),
                (timestamps[2], timestamps[4]),
                (timestamps[4], timestamps[6]),
            ),
        )
        self.assertEqual(
            tuple((item.previous_timestamp_ns, item.current_timestamp_ns) for item in odd),
            ((timestamps[1], timestamps[3]), (timestamps[3], timestamps[5])),
        )
        self.assertIn("phase=0", dataset[0]["chain_id"])
        self.assertIn("phase=1", dataset[1]["chain_id"])

    def test_sequence_identity_multiset_exactly_matches_pair_dataset(self) -> None:
        sequences = (
            _sequence(self.root, sequence_id="sequence-a"),
            _sequence(self.root, sequence_id="sequence-b"),
        )
        pair_dataset = EuRoCPairDataset(
            sequences,
            model_config=self.model_config,
            data_config=self.data_config,
            frame_strides=(1, 2),
        )
        sequence_dataset = EuRoCSequenceDataset(
            sequences,
            unroll_pairs=2,
            model_config=self.model_config,
            data_config=self.data_config,
            frame_strides=(1, 2),
        )

        pair_identities = [pair_dataset[index]["identity"] for index in range(len(pair_dataset))]
        sequence_identities = [
            identity
            for index in range(len(sequence_dataset))
            for identity in self._identities(sequence_dataset[index])
        ]
        self.assertEqual(sequence_dataset.pair_count, len(pair_dataset))
        self.assertCountEqual(sequence_identities, pair_identities)
        self.assertEqual(len(sequence_identities), len(set(sequence_identities)))

        for index in range(len(sequence_dataset)):
            identities = self._identities(sequence_dataset[index])
            self.assertEqual(len({item.sequence_id for item in identities}), 1)
            self.assertTrue(
                all(
                    left.current_timestamp_ns == right.previous_timestamp_ns
                    for left, right in zip(identities[:-1], identities[1:], strict=True)
                )
            )

    def test_collate_pads_steps_and_imu_with_safe_masked_dummies(self) -> None:
        sequence = _sequence(self.root, sequence_id="sequence-a")
        dataset = EuRoCSequenceDataset(
            (sequence,),
            unroll_pairs=4,
            model_config=self.model_config,
            data_config=self.data_config,
        )

        batch = collate_vio_sequence_batch((dataset[0], dataset[1]))
        self.assertIsInstance(batch, VIOSequenceBatch)
        self.assertEqual(batch.frame_pairs.shape, (2, 4, 2, 8, 12))
        self.assertEqual(batch.imu.shape, (2, 4, 1, 6))
        self.assertEqual(batch.imu_lengths.shape, (2, 4))
        self.assertEqual(batch.delta_time_s.shape, (2, 4, 1))
        self.assertEqual(batch.target_motion.shape, (2, 4, 6))
        self.assertEqual(
            batch.step_mask.tolist(),
            [[True, True, True, True], [True, True, False, False]],
        )
        self.assertEqual(batch.imu_lengths[1, 2:].tolist(), [1, 1])
        self.assertEqual(batch.delta_time_s[1, 2:, 0].tolist(), [1.0, 1.0])
        torch.testing.assert_close(batch.target_motion[1, 2:], torch.zeros(2, 6))
        self.assertEqual(batch.identities[1][2:], (None, None))
        self.assertEqual(batch.chain_ids[0], batch.chain_ids[1])
        self.assertEqual(batch.chunk_indices, (0, 1))
        self.assertEqual(batch.chain_starts, (True, False))
        self.assertEqual(batch.chain_ends, (False, True))

        moved = batch.to("cpu")
        self.assertIs(moved.identities, batch.identities)
        self.assertIs(moved.chain_ids, batch.chain_ids)
        self.assertIs(moved.chunk_indices, batch.chunk_indices)
        self.assertIs(moved.chain_starts, batch.chain_starts)
        self.assertIs(moved.chain_ends, batch.chain_ends)

    def test_invalid_unroll_and_stride_values_are_rejected(self) -> None:
        sequence = _sequence(self.root, sequence_id="sequence-a")
        for invalid in (0, -1, 1.5, True):
            with self.subTest(unroll_pairs=invalid):
                with self.assertRaisesRegex(ValueError, "unroll_pairs"):
                    EuRoCSequenceDataset(
                        (sequence,),
                        unroll_pairs=invalid,  # type: ignore[arg-type]
                        model_config=self.model_config,
                    )
        for invalid in ((), (0,), (1, 1), (True,)):
            with self.subTest(frame_strides=invalid):
                with self.assertRaisesRegex(ValueError, "frame_strides"):
                    EuRoCSequenceDataset(
                        (sequence,),
                        unroll_pairs=2,
                        model_config=self.model_config,
                        frame_strides=invalid,
                    )


if __name__ == "__main__":
    unittest.main()

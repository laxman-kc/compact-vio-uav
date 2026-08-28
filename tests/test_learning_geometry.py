from __future__ import annotations

import math
import unittest

from compact_vio.data.euroc import GroundTruthState
from compact_vio.learning import LearningError
from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
from compact_vio.learning.geometry import relative_motion_target


def _state(
    timestamp_ns: int,
    position: tuple[float, float, float],
    quaternion: tuple[float, float, float, float],
) -> GroundTruthState:
    return GroundTruthState(
        timestamp_ns=timestamp_ns,
        position_rs_r_m=position,
        quaternion_rs_wxyz=quaternion,
        velocity_rs_r_m_s=(0.0, 0.0, 0.0),
        gyroscope_bias_rs_s_rad_s=(0.0, 0.0, 0.0),
        accelerometer_bias_rs_s_m_s2=(0.0, 0.0, 0.0),
    )


class LearningGeometryTests(unittest.TestCase):
    def test_relative_translation_is_expressed_in_previous_sensor_frame(self) -> None:
        half = math.sqrt(0.5)
        previous = _state(100, (0.0, 0.0, 0.0), (half, 0.0, 0.0, half))
        current = _state(200, (0.0, 2.0, 0.0), (half, 0.0, 0.0, half))

        target = relative_motion_target(previous, current)

        self.assertAlmostEqual(target.translation_previous_m[0], 2.0)
        self.assertAlmostEqual(target.translation_previous_m[1], 0.0)
        self.assertAlmostEqual(target.translation_previous_m[2], 0.0)
        self.assertEqual(target.rotation_vector_rad, (0.0, 0.0, 0.0))

    def test_relative_rotation_uses_shortest_quaternion_log(self) -> None:
        half = math.sqrt(0.5)
        previous = _state(100, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))
        current = _state(200, (0.0, 0.0, 0.0), (-half, -half, 0.0, 0.0))

        target = relative_motion_target(previous, current)

        self.assertAlmostEqual(target.rotation_vector_rad[0], math.pi / 2.0)
        self.assertAlmostEqual(target.rotation_vector_rad[1], 0.0)
        self.assertAlmostEqual(target.rotation_vector_rad[2], 0.0)

    def test_target_rejects_reversed_time(self) -> None:
        state = _state(100, (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0))
        with self.assertRaisesRegex(LearningError, "must follow"):
            relative_motion_target(state, state)

    def test_training_config_round_trip_is_exact(self) -> None:
        config = TrainingConfig(
            model=ModelConfig(image_height_px=64, image_width_px=96),
            data=DataConfig(image_std=0.5),
            epochs=2,
            num_workers=0,
            use_amp=False,
        )
        self.assertEqual(TrainingConfig.from_dict(config.to_dict()), config)
        invalid = config.to_dict()
        invalid["invented"] = True
        with self.assertRaisesRegex(LearningError, "unknown training"):
            TrainingConfig.from_dict(invalid)

    def test_parses_checked_in_experiment_record_shape(self) -> None:
        record = {
            "schema_version": "1.0.0",
            "experiment_id": "euroc-compact-vio-v1",
            "seed": 9,
            "split_manifest": "configs/data/euroc.json",
            "image": {"width_px": 256, "height_px": 160, "mean": 0.5, "std": 0.25},
            "model": {
                "visual_feature_dim": 256,
                "imu_hidden_dim": 128,
                "fusion_hidden_dim": 256,
                "dropout": 0.1,
                "gyro_scale_rad_s": 1.0,
                "acceleration_scale_m_s2": 9.80665,
            },
            "optimization": {
                "epochs": 3,
                "batch_size": 8,
                "learning_rate": 0.0003,
                "weight_decay": 0.00001,
                "translation_loss_weight": 1.0,
                "rotation_loss_weight": 1.0,
                "gradient_clip_norm": 5.0,
                "num_workers": 2,
                "amp": True,
            },
            "sampling": {"frame_stride": 1, "max_pairs_per_sequence": None},
            "selection": {
                "metric": "validation_weighted_motion_loss",
                "mode": "min",
            },
        }
        config = TrainingConfig.from_mapping(record)
        self.assertEqual(config.model.image_width_px, 256)
        self.assertEqual(config.model.image_height_px, 160)
        self.assertEqual(config.model.imu_hidden_dim, 128)
        self.assertEqual(config.data.image_mean, 0.5)
        self.assertEqual(config.data.image_std, 0.25)
        self.assertEqual(config.data.accelerometer_scale_m_s2, 9.80665)
        self.assertEqual(config.epochs, 3)


if __name__ == "__main__":
    unittest.main()

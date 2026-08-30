from __future__ import annotations

import builtins
import csv
import io
import json
import math
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

try:
    import torch
    from PIL import Image

    INFERENCE_STACK_AVAILABLE = True
except ImportError:
    INFERENCE_STACK_AVAILABLE = False

from compact_vio.learning.config import DataConfig, ModelConfig
from compact_vio.learning.local_demo import _completion_status
from compact_vio.learning.local_demo import build_parser as build_demo_parser
from compact_vio.learning.recording_inference import (
    MotionEstimate,
    RecordingInferenceError,
    camera_samples,
    load_calibration,
    load_camera_timestamps,
    load_imu_csv,
    run_recording,
)
from compact_vio.learning.recording_inference import (
    main as recording_main,
)


class _FakeBackend:
    def __init__(self, motions: list[MotionEstimate]) -> None:
        self.model_config = ModelConfig(
            image_height_px=8,
            image_width_px=12,
            visual_feature_dim=16,
            imu_hidden_dim=8,
            fusion_hidden_dim=16,
            dropout_probability=0.0,
        )
        self.data_config = DataConfig(
            image_mean=0.5,
            image_std=0.25,
            gyroscope_scale_rad_s=5.0,
            accelerometer_scale_m_s2=20.0,
        )
        self.motions = motions
        self.calls: list[tuple[object, object, float, object | None]] = []

    def predict_step(
        self,
        frame_pair: object,
        imu_window: object,
        delta_time_s: float,
        state: object | None,
    ) -> tuple[MotionEstimate, object | None]:
        assert INFERENCE_STACK_AVAILABLE
        assert isinstance(frame_pair, torch.Tensor)
        assert isinstance(imu_window, torch.Tensor)
        self.calls.append((frame_pair.clone(), imu_window.clone(), delta_time_s, state))
        return self.motions[len(self.calls) - 1], f"state-{len(self.calls)}"


class _FakeRecordingBackend:
    backend_id = "fake-raw-recording/v1"
    calibration_usage = "used-by-fake-raw-backend"
    quality_status = "experimental_rejected"
    quality_warning = "EXPERIMENTAL MODEL: frozen quality gates failed."

    def __init__(self) -> None:
        self.call: tuple[object, object, object] | None = None

    def predict_recording(
        self,
        frames: object,
        imu_samples: object,
        calibration: object,
    ) -> tuple[MotionEstimate, ...]:
        self.call = (frames, imu_samples, calibration)
        return (
            MotionEstimate((0.25, 0.0, 0.0), (0.0, 0.0, 0.0)),
            MotionEstimate((0.25, 0.0, 0.0), (0.0, 0.0, 0.0)),
        )


class DependencyLightEntrypointTests(unittest.TestCase):
    def test_demo_help_does_not_import_gradio_torch_or_opencv(self) -> None:
        original_import = builtins.__import__

        def reject_optional(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            if name in {"cv2", "gradio", "torch"} or name.startswith(("cv2.", "gradio.", "torch.")):
                raise AssertionError("CLI help must not import optional runtimes")
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = reject_optional
        try:
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                build_demo_parser().parse_args(["--help"])
        finally:
            builtins.__import__ = original_import
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--checkpoint", output.getvalue())
        self.assertIn("--model-package", output.getvalue())
        self.assertIn("imu.T_BS must be identity", output.getvalue())

    def test_package_cli_requires_calibration_before_loading_package(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            status = recording_main(
                [
                    "--recording",
                    "missing-recording",
                    "--imu",
                    "missing-imu.csv",
                    "--model-package",
                    "missing-package/manifest.json",
                    "--output",
                    "missing-output",
                ]
            )
        self.assertEqual(status, 2)
        self.assertIn("--calibration is required with --model-package", error.getvalue())

    def test_demo_status_prominently_surfaces_rejected_quality(self) -> None:
        status = _completion_status(
            pair_count=2,
            frame_count=3,
            path_length_m=1.25,
            quality_warning="EXPERIMENTAL MODEL: frozen gates failed.",
        )
        self.assertTrue(status.startswith("⚠️ **MODEL QUALITY WARNING:**"))
        self.assertIn("EXPERIMENTAL MODEL", status)


@unittest.skipUnless(
    INFERENCE_STACK_AVAILABLE,
    "PyTorch and Pillow training extras are not installed",
)
class RecordingInferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.images = self.root / "images"
        self.images.mkdir()
        for timestamp, pixel in ((100, 51), (200, 102), (300, 153)):
            Image.new("L", (12, 8), color=pixel).save(self.images / f"{timestamp}.png")
        self.imu_csv = self.root / "imu.csv"
        self.imu_csv.write_text(
            "timestamp_ns,gyro_x_rad_s,gyro_y_rad_s,gyro_z_rad_s,"
            "accel_x_m_s2,accel_y_m_s2,accel_z_m_s2\n"
            "150,5,10,15,20,40,60\n"
            "200,10,15,20,40,60,80\n"
            "250,15,20,25,60,80,100\n"
            "300,20,25,30,80,100,120\n",
            encoding="utf-8",
        )
        self.calibration = self.root / "calibration.json"
        self.calibration.write_text(
            json.dumps({"camera_model": "pinhole", "intrinsics": [10, 10, 6, 4]}),
            encoding="utf-8",
        )

    def test_end_to_end_fake_backend_integrates_and_writes_all_artifacts(self) -> None:
        backend = _FakeBackend(
            [
                MotionEstimate((1.0, 0.0, 0.0), (0.0, 0.0, math.pi / 2.0)),
                MotionEstimate((1.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ]
        )
        result = run_recording(
            recording_path=self.images,
            imu_csv_path=self.imu_csv,
            calibration_path=self.calibration,
            output_directory=self.root / "result",
            backend=backend,
            sequence_id="synthetic-turn",
        )

        self.assertEqual(result.frame_count, 3)
        self.assertEqual(result.pair_count, 2)
        self.assertAlmostEqual(result.path_length_m, 2.0)
        self.assertAlmostEqual(result.final_displacement_m, math.sqrt(2.0))
        self.assertEqual(len(backend.calls), 2)
        self.assertIsNone(backend.calls[0][3])
        self.assertEqual(backend.calls[1][3], "state-1")
        self.assertAlmostEqual(backend.calls[0][2], 1e-7)

        first_frames, first_imu, _, _ = backend.calls[0]
        assert isinstance(first_frames, torch.Tensor)
        assert isinstance(first_imu, torch.Tensor)
        torch.testing.assert_close(
            first_frames[0],
            torch.full((8, 12), ((51.0 / 255.0) - 0.5) / 0.25),
        )
        torch.testing.assert_close(
            first_imu,
            torch.tensor([[1, 2, 3, 1, 2, 3], [2, 3, 4, 2, 3, 4]], dtype=torch.float32),
        )

        with result.trajectory_csv.open(newline="", encoding="utf-8") as handle:
            rows = tuple(csv.DictReader(handle))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[-1]["timestamp_ns"], "300")
        self.assertAlmostEqual(float(rows[-1]["x_m"]), 1.0, places=7)
        self.assertAlmostEqual(float(rows[-1]["y_m"]), 1.0, places=7)
        self.assertAlmostEqual(float(rows[1]["qw"]), math.sqrt(0.5), places=7)
        self.assertAlmostEqual(float(rows[1]["qz"]), math.sqrt(0.5), places=7)

        svg = result.trajectory_svg.read_text(encoding="utf-8")
        report = result.summary_html.read_text(encoding="utf-8")
        summary = json.loads(result.summary_json.read_text(encoding="utf-8"))
        self.assertIn("<svg", svg)
        self.assertNotIn("http://", report.replace('xmlns="http://www.w3.org/2000/svg"', ""))
        self.assertIn(svg, report)
        self.assertEqual(summary["predicted_pairs"], 2)
        self.assertEqual(len(summary["calibration_sha256"]), 64)
        self.assertIn("grayscale-resize-normalize", summary["calibration_usage"])

    def test_camera_and_imu_alias_csvs_are_accepted_strictly(self) -> None:
        camera_csv = self.root / "camera.csv"
        camera_csv.write_text(
            "#timestamp [ns],filename\n100,100.png\n200,200.png\n300,300.png\n",
            encoding="utf-8",
        )
        imu_csv = self.root / "short-imu.csv"
        imu_csv.write_text(
            "timestamp_ns,gx,gy,gz,ax,ay,az\n150,1,2,3,4,5,6\n250,7,8,9,10,11,12\n",
            encoding="utf-8",
        )

        timestamps = load_camera_timestamps(camera_csv)
        imu = load_imu_csv(imu_csv)
        with camera_samples(self.images, camera_csv) as frames:
            self.assertEqual(tuple(frame.timestamp_ns for frame in frames), (100, 200, 300))

        self.assertEqual(timestamps[0], (100, "100.png"))
        self.assertEqual(imu[1].angular_velocity_rad_s, (7.0, 8.0, 9.0))

    def test_timestamped_image_zip_runs_without_opencv(self) -> None:
        archive = self.root / "images.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            for image in sorted(self.images.iterdir()):
                handle.write(image, f"frames/{image.name}")
        backend = _FakeBackend(
            [
                MotionEstimate((0.1, 0.0, 0.0), (0.0, 0.0, 0.0)),
                MotionEstimate((0.1, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ]
        )

        result = run_recording(
            recording_path=archive,
            imu_csv_path=self.imu_csv,
            output_directory=self.root / "zip-result",
            backend=backend,
        )

        self.assertEqual(result.frame_count, 3)
        self.assertAlmostEqual(result.final_displacement_m, 0.2)

    def test_raw_recording_backend_receives_paths_timestamps_imu_and_calibration(self) -> None:
        backend = _FakeRecordingBackend()
        result = run_recording(
            recording_path=self.images,
            imu_csv_path=self.imu_csv,
            calibration_path=self.calibration,
            output_directory=self.root / "raw-result",
            backend=backend,  # type: ignore[arg-type]
        )

        self.assertAlmostEqual(result.final_displacement_m, 0.5)
        assert backend.call is not None
        frames, imu_samples, calibration = backend.call
        self.assertEqual(tuple(frame.timestamp_ns for frame in frames), (100, 200, 300))
        self.assertEqual(tuple(sample.timestamp_ns for sample in imu_samples), (150, 200, 250, 300))
        self.assertEqual(calibration["camera_model"], "pinhole")
        summary = json.loads(result.summary_json.read_text(encoding="utf-8"))
        self.assertEqual(summary["backend_id"], backend.backend_id)
        self.assertEqual(summary["calibration_usage"], backend.calibration_usage)
        self.assertEqual(summary["model_identity"], "not-declared")
        self.assertEqual(summary["motion_frame"], "previous camera/body frame")
        self.assertEqual(summary["quality_status"], "experimental_rejected")
        self.assertIn("EXPERIMENTAL MODEL", summary["quality_warning"])
        self.assertIn(
            "MODEL QUALITY WARNING",
            result.summary_html.read_text(encoding="utf-8"),
        )

    def test_missing_causal_imu_interval_is_rejected(self) -> None:
        sparse = self.root / "sparse.csv"
        sparse.write_text(
            "timestamp_ns,gx,gy,gz,ax,ay,az\n250,1,2,3,4,5,6\n",
            encoding="utf-8",
        )
        backend = _FakeBackend([MotionEstimate((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))] * 2)
        with self.assertRaisesRegex(RecordingInferenceError, "no causal IMU"):
            run_recording(
                recording_path=self.images,
                imu_csv_path=sparse,
                output_directory=self.root / "failed",
                backend=backend,
            )

    def test_bad_calibration_and_unsafe_zip_are_rejected(self) -> None:
        empty_calibration = self.root / "empty.json"
        empty_calibration.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(RecordingInferenceError, "non-empty mapping"):
            load_calibration(empty_calibration)

        unsafe = self.root / "unsafe.zip"
        with zipfile.ZipFile(unsafe, "w") as handle:
            handle.writestr("../100.png", b"not-an-image")
            handle.writestr("200.png", b"not-an-image")
        with self.assertRaisesRegex(RecordingInferenceError, "unsafe member path"):
            with camera_samples(unsafe):
                pass


if __name__ == "__main__":
    unittest.main()

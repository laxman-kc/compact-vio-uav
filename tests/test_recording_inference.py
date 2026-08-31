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
from types import SimpleNamespace
from unittest.mock import patch

try:
    import torch
    from PIL import Image

    INFERENCE_STACK_AVAILABLE = True
except ImportError:
    INFERENCE_STACK_AVAILABLE = False

from compact_vio.learning.config import DataConfig, ModelConfig
from compact_vio.learning.local_demo import (
    _completion_panel,
    _completion_status,
    _error_panel,
    _model_is_ready,
    _model_setup_panel,
    _path,
)
from compact_vio.learning.local_demo import build_parser as build_demo_parser
from compact_vio.learning.recording_inference import (
    ImuSample,
    MotionEstimate,
    RecordingInferenceError,
    assess_model_quality,
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


def _quality_backend(*, outcome: str = "rejected") -> object:
    final_passed = outcome == "accepted"
    final_path_ratio = 0.9 if final_passed else 0.5316322190201012
    final_drift = 0.01 if final_passed else 0.032806273676682145
    final_predicted_path = 117.61834450790347 if final_passed else 69.47744609800827
    final_drift_m = 1.3068704945322608 if final_passed else 4.287355110360628
    gates = {
        "coverage_ratio_min": 1.0,
        "normalized_final_translation_drift_max": 0.02,
        "path_length_ratio_max": 1.2,
        "path_length_ratio_min": 0.8,
        "require_pair_rotation_rmse_below_zero_motion": True,
        "require_pair_translation_rmse_below_zero_motion": True,
        "require_translation_ate_below_zero_motion": True,
    }
    sequences = [
        {"all_pass": True, "role": "development_validation"},
        {"all_pass": True, "role": "development_validation"},
        {
            "all_pass": final_passed,
            "coverage_ratio": 1.0,
            "final_translation_drift_m": final_drift_m,
            "normalized_final_translation_drift": final_drift,
            "pair_rotation_rmse_rad": 0.0000727281,
            "pair_translation_rmse_m": 0.0351848104,
            "path_length_ratio": final_path_ratio,
            "predicted_path_length_m": final_predicted_path,
            "reference_path_length_m": 130.68704945322608,
            "role": "final_test",
            "sequence_id": "MH_03_medium",
            "translation_ate_m": 3.8248968427,
            "zero_pair_rotation_rmse_rad": 0.0172287091,
            "zero_pair_translation_rmse_m": 0.0612102654,
            "zero_translation_ate_m": 4.6738549597,
        },
    ]
    return SimpleNamespace(
        quality_status="accepted" if final_passed else "experimental_rejected",
        package=SimpleNamespace(
            manifest={"evaluation": {"gates": gates, "outcome": outcome, "sequences": sequences}}
        ),
    )


class DependencyLightEntrypointTests(unittest.TestCase):
    def test_demo_builds_with_the_optional_gradio_stack(self) -> None:
        import gc
        import warnings

        try:
            import gradio  # noqa: F401
        except ImportError:
            self.skipTest("the optional Gradio demo stack is not installed")

        from compact_vio.learning.local_demo import build_demo

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=ResourceWarning)
            demo = build_demo(checkpoint_path=Path("placeholder"), device="cpu")
            workspace_owner = demo._compact_vio_result_workspace
            workspace = Path(workspace_owner.name)
            self.assertTrue(workspace.is_dir())
            demo.close()
            workspace_owner.cleanup()
            self.assertFalse(workspace.exists())
            del demo
            gc.collect()

    def test_demo_requires_a_model_artifact_before_inference(self) -> None:
        self.assertFalse(_model_is_ready(None))
        self.assertFalse(_model_is_ready("  "))
        self.assertTrue(_model_is_ready("model-package/manifest.json"))
        panel = _model_setup_panel()
        self.assertIn("Model package required", panel)
        self.assertIn("does not include model weights", panel)
        self.assertIn("Advanced model settings", panel)

    def test_demo_path_keeps_full_pathlib_value(self) -> None:
        self.assertEqual(_path(Path("/tmp/example.zip"), field="bundle"), "/tmp/example.zip")

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
        self.assertIn("Keep the rig stationary", output.getvalue())
        self.assertNotIn("--share", output.getvalue())

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            build_demo_parser().parse_args(["--host", "0.0.0.0"])

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
        self.assertTrue(status.startswith("Run completed:"))
        self.assertIn("Model accuracy is not yet reliable", status)

    def test_quality_assessment_separates_run_success_from_accuracy(self) -> None:
        quality = assess_model_quality(_quality_backend())
        self.assertEqual(quality.status, "rejected")
        self.assertEqual(quality.development_passed, 2)
        self.assertEqual(quality.development_total, 2)
        self.assertFalse(quality.final_test_passed)
        self.assertEqual(quality.failed_gates, ("distance travelled", "end-position drift"))
        self.assertAlmostEqual(quality.path_error_percent or 0.0, 46.83677809798988)
        self.assertIn("69.5 m for a 130.7 m path", quality.explanation)
        self.assertIn("not to measure distance", quality.recommended_use)

        panel = _completion_panel(
            pair_count=1,
            frame_count=2,
            path_length_m=0.034644,
            final_displacement_m=0.034644,
            elapsed_s=0.164532,
            quality=quality,
        )
        self.assertIn("Trajectory created", panel)
        self.assertIn("Accuracy for this recording: unverified", panel)
        self.assertIn("Packaged model:</strong> Benchmark not passed", panel)
        self.assertIn("Very short recording", panel)
        self.assertIn("0.035 m", panel)

    def test_quality_assessment_can_report_accepted_and_unknown_models(self) -> None:
        accepted = assess_model_quality(_quality_backend(outcome="accepted"))
        self.assertEqual(accepted.status, "accepted")
        self.assertTrue(accepted.final_test_passed)
        self.assertEqual(accepted.failed_gates, ())
        self.assertIn("All 3 packaged benchmark recordings passed", accepted.explanation)

        unknown = assess_model_quality(object())
        self.assertEqual(unknown.status, "not_assessed")
        self.assertIn("does not include a benchmark verdict", unknown.explanation)

    def test_quality_assessment_does_not_hide_failed_development_sequence(self) -> None:
        backend = _quality_backend(outcome="accepted")
        backend.quality_status = "experimental_rejected"
        evaluation = backend.package.manifest["evaluation"]
        evaluation["outcome"] = "rejected"
        development = evaluation["sequences"][0]
        development.update(
            {
                "sequence_id": "V1_03_difficult",
                "all_pass": False,
                "coverage_ratio": 1.0,
                "path_length_ratio": 0.5,
                "normalized_final_translation_drift": 0.01,
                "translation_ate_m": 1.0,
                "zero_translation_ate_m": 2.0,
                "pair_translation_rmse_m": 0.01,
                "zero_pair_translation_rmse_m": 0.02,
                "pair_rotation_rmse_rad": 0.01,
                "zero_pair_rotation_rmse_rad": 0.02,
            }
        )
        quality = assess_model_quality(backend)
        self.assertEqual(quality.status, "rejected")
        self.assertTrue(quality.final_test_passed)
        self.assertEqual(quality.failed_gates, ("V1 03 difficult: distance travelled",))
        self.assertIn("development benchmark recordings failed", quality.explanation)
        self.assertNotIn("held-out MH 03 medium test", quality.explanation)

    def test_strict_text_inputs_reject_duplicates_extreme_timestamps_and_csv_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate_json = root / "duplicate.json"
            duplicate_json.write_text(
                '{"camera":{"resolution":[12,8]},"camera":{"resolution":[14,9]}}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RecordingInferenceError, "duplicate JSON key"):
                load_calibration(duplicate_json)

            duplicate_yaml = root / "duplicate.yaml"
            duplicate_yaml.write_text(
                "camera:\n  resolution: [12, 8]\n  resolution: [14, 9]\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RecordingInferenceError, "duplicate YAML key"):
                load_calibration(duplicate_yaml)

            extreme = root / "extreme.csv"
            extreme.write_text(
                f"timestamp_ns,filename\n{1 << 63},a.png\n{(1 << 63) + 1},b.png\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RecordingInferenceError, "signed 64-bit range"):
                load_camera_timestamps(extreme)

            malformed = root / "malformed.csv"
            malformed.write_text(
                "timestamp_ns,filename\n1," + ("x" * 200_000) + "\n2,b.png\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RecordingInferenceError, "CSV is malformed"):
                load_camera_timestamps(malformed)

            malformed_header = root / "malformed-header.csv"
            malformed_header.write_text(("x" * 200_000) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RecordingInferenceError, "CSV is malformed"):
                load_camera_timestamps(malformed_header)

            invalid_utf8 = root / "invalid-utf8.csv"
            invalid_utf8.write_bytes(
                b"timestamp_ns,filename\n1,a.png\n2," + bytes((0xFF,)) + b".png\n"
            )
            with self.assertRaisesRegex(RecordingInferenceError, "CSV is malformed"):
                load_camera_timestamps(invalid_utf8)

        with self.assertRaisesRegex(RecordingInferenceError, "gyroscope value"):
            ImuSample(1, (1e308, 0.0, 0.0), (0.0, 0.0, 9.81))
        with self.assertRaisesRegex(RecordingInferenceError, "acceleration value"):
            ImuSample(1, (0.0, 0.0, 0.0), (1e308, 0.0, 9.81))

    def test_image_zip_rejects_case_duplicates_and_corrupted_member(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            duplicate = root / "duplicate.zip"
            with zipfile.ZipFile(duplicate, "w") as archive:
                archive.writestr("frames/100.png", b"one")
                archive.writestr("FRAMES/100.PNG", b"two")
            with self.assertRaisesRegex(RecordingInferenceError, "repeats a member path"):
                with camera_samples(duplicate):
                    pass

            corrupted = root / "corrupted.zip"
            with zipfile.ZipFile(corrupted, "w", compression=zipfile.ZIP_STORED) as archive:
                archive.writestr("100.png", b"one")
                archive.writestr("200.png", b"two")
            with zipfile.ZipFile(corrupted) as archive:
                member = archive.getinfo("100.png")
                offset = (
                    member.header_offset
                    + 30
                    + len(member.filename.encode("utf-8"))
                    + len(member.extra)
                )
            with corrupted.open("r+b") as handle:
                handle.seek(offset)
                original = handle.read(1)
                handle.seek(offset)
                handle.write(bytes((original[0] ^ 0xFF,)))
            with self.assertRaisesRegex(RecordingInferenceError, "cannot extract image ZIP"):
                with camera_samples(corrupted):
                    pass

    def test_demo_error_panel_is_actionable_and_escapes_content(self) -> None:
        panel = _error_panel("recording <script> is required")
        self.assertIn('role="alert"', panel)
        self.assertIn("This recording could not be processed", panel)
        self.assertIn("CompactVIO bundle ZIP", panel)
        self.assertIn("recording &lt;script&gt; is required", panel)
        self.assertNotIn("<script>", panel)


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
        self.assertEqual(summary["run_status"], "completed")
        self.assertEqual(summary["accuracy_for_this_recording"], "unverified_without_ground_truth")
        self.assertEqual(summary["model_quality"]["status"], "not_assessed")
        self.assertEqual(len(summary["calibration_sha256"]), 64)
        self.assertIn("grayscale-resize-normalize", summary["calibration_usage"])
        self.assertIn("Run completed", report)
        self.assertIn("does not prove the estimated path is accurate", report)
        self.assertIn("Accuracy for this recording:</strong> Unverified", report)
        self.assertIn("cannot measure whether the uploaded trajectory is correct", report)
        self.assertIn("Views are autoscaled", svg)
        self.assertIn(">start<", svg)
        self.assertIn(">end<", svg)
        self.assertIn("Estimated local path with 3 poses", svg)

    def test_output_publication_refuses_stale_files_and_cleans_failed_staging(self) -> None:
        stale = self.root / "stale-result"
        stale.mkdir()
        stale_summary = stale / "summary.json"
        stale_summary.write_text('{"run_status":"completed","sequence_id":"old"}\n')
        backend = _FakeBackend(
            [
                MotionEstimate((0.1, 0.0, 0.0), (0.0, 0.0, 0.0)),
                MotionEstimate((0.1, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ]
        )
        with self.assertRaisesRegex(RecordingInferenceError, "must be empty"):
            run_recording(
                recording_path=self.images,
                imu_csv_path=self.imu_csv,
                output_directory=stale,
                backend=backend,
                sequence_id="new",
            )
        self.assertEqual(
            json.loads(stale_summary.read_text(encoding="utf-8"))["sequence_id"],
            "old",
        )

        failed = self.root / "failed-publication"
        backend = _FakeBackend(
            [
                MotionEstimate((0.1, 0.0, 0.0), (0.0, 0.0, 0.0)),
                MotionEstimate((0.1, 0.0, 0.0), (0.0, 0.0, 0.0)),
            ]
        )
        with patch(
            "compact_vio.learning.recording_inference._atomic_text",
            side_effect=RecordingInferenceError("simulated export failure"),
        ):
            with self.assertRaisesRegex(RecordingInferenceError, "simulated export failure"):
                run_recording(
                    recording_path=self.images,
                    imu_csv_path=self.imu_csv,
                    output_directory=failed,
                    backend=backend,
                )
        self.assertFalse(failed.exists())
        self.assertEqual(tuple(self.root.glob(".failed-publication.staging-*")), ())

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
        self.assertEqual(summary["model_quality"]["status"], "rejected")
        report = result.summary_html.read_text(encoding="utf-8")
        self.assertIn("Model quality: Benchmark not passed", report)
        self.assertIn("Model accuracy is not reliable yet", report)

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

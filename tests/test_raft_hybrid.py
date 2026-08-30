from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from compact_vio.learning.raft_head_onnx import export_raft_head_onnx
from compact_vio.learning.raft_hybrid import (
    EVALUATION_RECORD_TYPE,
    EVALUATION_SCHEMA_VERSION,
    FEATURE_DIM,
    HEAD_HIDDEN_DIM,
    INPUT_HEIGHT,
    INPUT_WIDTH,
    RAFT_WEIGHTS_SHA256,
    RaftHybridBackend,
    RaftHybridError,
    _sha256_bool_tensor,
    _sha256_float_tensor,
    build_parser,
    build_raft_hybrid_package,
    euroc_calibration_document,
    load_raft_hybrid_package,
    parse_hybrid_calibration,
    raft_hybrid_candidate_id,
)
from compact_vio.learning.recording_inference import CameraSample, ImuSample

try:
    import torch
    from PIL import Image

    RUNTIME_AVAILABLE = True
except ImportError:
    RUNTIME_AVAILABLE = False

ONNX_STACK_AVAILABLE = bool(
    importlib.util.find_spec("onnx") and importlib.util.find_spec("onnxruntime")
)


def _identity_t_bs() -> list[list[float]]:
    return [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _calibration() -> dict[str, object]:
    return {
        "camera": {
            "T_BS": _identity_t_bs(),
            "camera_model": "pinhole",
            "distortion_coefficients": [0.0, 0.0, 0.0, 0.0],
            "distortion_model": "radtan",
            "intrinsics": [200.0, 200.0, 6.0, 4.0],
            "resolution": [12, 8],
        },
        "imu": {"T_BS": _identity_t_bs()},
    }


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def _evaluation_summary(
    *,
    raft_sha256: str,
    head_sha256: str,
    clamp_sha256: str,
    translation_post_matrix: object,
    accepted: bool = True,
) -> dict[str, object]:
    gates = {
        "coverage_ratio_min": 1.0,
        "normalized_final_translation_drift_max": 0.02,
        "path_length_ratio_max": 1.2,
        "path_length_ratio_min": 0.8,
        "require_pair_rotation_rmse_below_zero_motion": True,
        "require_pair_translation_rmse_below_zero_motion": True,
        "require_translation_ate_below_zero_motion": True,
    }

    def sequence(sequence_id: str, role: str, identity: str, *, passes: bool) -> dict[str, object]:
        predicted_path = 90.0 if passes else 50.0
        final_drift = 1.0 if passes else 3.0
        return {
            "all_pass": passes,
            "coverage_ratio": 1.0,
            "data_identity_sha256": identity,
            "expected_pairs": 100,
            "final_rotation_drift_rad": 0.02,
            "final_translation_drift_m": final_drift,
            "normalized_final_translation_drift": final_drift / 100.0,
            "pair_rotation_rmse_rad": 0.01,
            "pair_translation_rmse_m": 0.02,
            "path_length_ratio": predicted_path / 100.0,
            "predicted_pairs": 100,
            "predicted_path_length_m": predicted_path,
            "reference_path_length_m": 100.0,
            "role": role,
            "sequence_id": sequence_id,
            "translation_ate_m": 1.0,
            "zero_pair_rotation_rmse_rad": 0.02,
            "zero_pair_translation_rmse_m": 0.04,
            "zero_translation_ate_m": 2.0,
        }

    return {
        "candidate_id": raft_hybrid_candidate_id(
            raft_weights_sha256=raft_sha256,
            head_checkpoint_sha256=head_sha256,
            clamp_sha256=clamp_sha256,
            translation_post_matrix=translation_post_matrix,
        ),
        "gates": gates,
        "outcome": "accepted" if accepted else "rejected",
        "record_type": EVALUATION_RECORD_TYPE,
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "sequences": [
            sequence("development", "development_validation", "b" * 64, passes=True),
            sequence("final", "final_test", "c" * 64, passes=accepted),
        ],
    }


class RaftHybridDependencyLightTests(unittest.TestCase):
    def test_help_does_not_import_torch_torchvision_or_pillow(self) -> None:
        original_import = builtins.__import__

        def reject_optional(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            if name.split(".", 1)[0] in {"torch", "torchvision", "PIL"}:
                raise AssertionError("package CLI help must stay dependency-light")
            return original_import(name, globals, locals, fromlist, level)

        builtins.__import__ = reject_optional
        try:
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                build_parser().parse_args(["--help"])
        finally:
            builtins.__import__ = original_import
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--translation-post-matrix", output.getvalue())

    def test_combined_calibration_is_strict_and_preserves_native_values(self) -> None:
        parsed = parse_hybrid_calibration(_calibration())
        self.assertEqual(parsed.resolution_width_px, 12)
        self.assertEqual(parsed.intrinsics, (200.0, 200.0, 6.0, 4.0))
        invalid = _calibration()
        invalid["camera"]["distortion_model"] = "equidistant"  # type: ignore[index]
        with self.assertRaisesRegex(RaftHybridError, "pinhole.*radtan"):
            parse_hybrid_calibration(invalid)
        nonidentity_imu = _calibration()
        nonidentity_imu["imu"]["T_BS"][0][3] = 0.01  # type: ignore[index]
        with self.assertRaisesRegex(RaftHybridError, "imu.T_BS must be identity"):
            parse_hybrid_calibration(nonidentity_imu)


@unittest.skipUnless(RUNTIME_AVAILABLE, "PyTorch and Pillow runtime extras are not installed")
class RaftHybridRuntimeTests(unittest.TestCase):
    def _head_payload(self) -> dict[str, object]:
        return {
            "model_state_dict": {
                "network.0.weight": torch.zeros(HEAD_HIDDEN_DIM, FEATURE_DIM),
                "network.0.bias": torch.zeros(HEAD_HIDDEN_DIM),
                "network.2.weight": torch.zeros(HEAD_HIDDEN_DIM, HEAD_HIDDEN_DIM),
                "network.2.bias": torch.zeros(HEAD_HIDDEN_DIM),
                "network.4.weight": torch.zeros(3, HEAD_HIDDEN_DIM),
                "network.4.bias": torch.tensor([1.0, 2.0, 3.0]),
            },
            "feature_mean": torch.zeros(FEATURE_DIM),
            "feature_std": torch.ones(FEATURE_DIM),
            "target_mean": torch.zeros(3),
            "target_std": torch.ones(3),
            "architecture": {
                "type": "MLP",
                "feature_dim": FEATURE_DIM,
                "hidden_dim": HEAD_HIDDEN_DIM,
                "layers": [FEATURE_DIM, HEAD_HIDDEN_DIM, HEAD_HIDDEN_DIM, 3],
                "activation": "GELU",
            },
            "selected": {"epoch": 1},
        }

    def _clamp_payload(self, head_sha256: str) -> dict[str, object]:
        minimum = torch.full((FEATURE_DIM,), -100.0)
        maximum = torch.full((FEATURE_DIM,), 100.0)
        constant = torch.zeros(FEATURE_DIM, dtype=torch.bool)
        return {
            "record_type": "train_only_standardized_feature_clamp",
            "schema_version": 1,
            "train_sequence_ids": ["train-a"],
            "source_cache_path": "/source/cache.pt",
            "source_cache_sha256": "a" * 64,
            "head_checkpoint_path": "/source/head.pt",
            "head_checkpoint_sha256": head_sha256,
            "feature_dim": FEATURE_DIM,
            "rule": (
                "per-feature exact train standardized min/max; "
                "exact raw train constants forced to [0,0]"
            ),
            "clamp_min": minimum,
            "clamp_max": maximum,
            "constant_feature_mask": constant,
            "clamp_min_tensor_sha256": _sha256_float_tensor(minimum, field="minimum"),
            "clamp_max_tensor_sha256": _sha256_float_tensor(maximum, field="maximum"),
            "constant_mask_tensor_sha256": _sha256_bool_tensor(constant, field="constant"),
            "constant_feature_count": 0,
        }

    @unittest.skipUnless(ONNX_STACK_AVAILABLE, "ONNX and ONNX Runtime are not installed")
    def test_package_binds_assets_head_clamp_and_optional_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raft = root / "source-raft.pth"
            raft.write_bytes(b"synthetic official weights")
            head = root / "source-head.pt"
            torch.save(self._head_payload(), head)
            head_sha = hashlib.sha256(head.read_bytes()).hexdigest()
            clamp = root / "source-clamp.pt"
            torch.save(self._clamp_payload(head_sha), clamp)
            raft_sha = hashlib.sha256(raft.read_bytes()).hexdigest()
            clamp_sha = hashlib.sha256(clamp.read_bytes()).hexdigest()
            matrix = (2.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 4.0)
            evaluation = root / "evaluation.json"
            evaluation.write_text(
                _canonical_json(
                    _evaluation_summary(
                        raft_sha256=raft_sha,
                        head_sha256=head_sha,
                        clamp_sha256=clamp_sha,
                        translation_post_matrix=matrix,
                        accepted=False,
                    )
                ),
                encoding="utf-8",
            )
            onnx = root / "translation-head.onnx"
            onnx_manifest = root / "export.json"
            export_raft_head_onnx(
                head,
                clamp,
                onnx,
                onnx_manifest,
                expected_head_sha256=head_sha,
                expected_clamp_sha256=clamp_sha,
                translation_post_matrix=matrix,
            )
            with patch("compact_vio.learning.raft_hybrid.RAFT_WEIGHTS_SHA256", raft_sha):
                package = build_raft_hybrid_package(
                    root / "package",
                    raft_weights_path=raft,
                    head_checkpoint_path=head,
                    clamp_path=clamp,
                    evaluation_summary_path=evaluation,
                    translation_post_matrix=matrix,
                    head_onnx_path=onnx,
                    head_onnx_manifest_path=onnx_manifest,
                )
                loaded = load_raft_hybrid_package(package.manifest_path)
                packaged_matrix = loaded.manifest["architecture"][  # type: ignore[index]
                    "translation_post_matrix"
                ]
                self.assertEqual(
                    packaged_matrix,
                    [[2.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 4.0]],
                )
                self.assertIsNotNone(loaded.head_onnx_path)
                self.assertIsNotNone(loaded.head_onnx_manifest_path)
                self.assertEqual(
                    loaded.manifest["evaluation"]["outcome"],  # type: ignore[index]
                    "rejected",
                )
                self.assertEqual(loaded.manifest["quality_status"], "experimental_rejected")
                mismatch_payload = _evaluation_summary(
                    raft_sha256=raft_sha,
                    head_sha256=head_sha,
                    clamp_sha256=clamp_sha,
                    translation_post_matrix=matrix,
                    accepted=False,
                )
                mismatch_payload["candidate_id"] = f"raft-hybrid-sha256:{'0' * 64}"
                mismatch = root / "evaluation-mismatch.json"
                mismatch.write_text(_canonical_json(mismatch_payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    RaftHybridError, "does not bind the packaged candidate"
                ):
                    build_raft_hybrid_package(
                        root / "mismatch-package",
                        raft_weights_path=raft,
                        head_checkpoint_path=head,
                        clamp_path=clamp,
                        evaluation_summary_path=mismatch,
                        translation_post_matrix=matrix,
                        head_onnx_path=onnx,
                        head_onnx_manifest_path=onnx_manifest,
                    )
                manifest_bytes = loaded.manifest_path.read_bytes()
                forged = json.loads(manifest_bytes)
                forged["quality_status"] = "accepted"
                loaded.manifest_path.write_text(_canonical_json(forged), encoding="utf-8")
                with self.assertRaisesRegex(RaftHybridError, "quality_status is inconsistent"):
                    load_raft_hybrid_package(loaded.manifest_path)
                loaded.manifest_path.write_bytes(manifest_bytes)
                loaded.head_checkpoint_path.write_bytes(b"tampered")
                with self.assertRaisesRegex(RaftHybridError, "size or SHA-256"):
                    load_raft_hybrid_package(package.manifest_path)

    def test_raw_runtime_applies_post_head_matrix_and_returns_gyro_rotation(self) -> None:
        class FakeRaft:
            def __call__(self, image1: object, image2: object, **_: object) -> list[object]:
                assert isinstance(image1, torch.Tensor)
                return [
                    torch.zeros(image1.shape[0], 2, INPUT_HEIGHT, INPUT_WIDTH, device=image1.device)
                ]

        class ConstantHead:
            def __call__(self, features: object) -> object:
                assert isinstance(features, torch.Tensor)
                return torch.tensor([1.0, 2.0, 3.0]).expand(features.shape[0], -1)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            frames = []
            for timestamp, pixel in ((100, 50), (200, 100), (300, 150)):
                path = root / f"{timestamp}.png"
                Image.new("L", (12, 8), color=pixel).save(path)
                frames.append(CameraSample(timestamp, path))
            imu = tuple(
                ImuSample(timestamp, (0.0, 0.0, 0.0), (0.0, 0.0, 9.81))
                for timestamp in (0, 50, 100, 150, 200, 250, 300)
            )
            backend = object.__new__(RaftHybridBackend)
            backend.device = torch.device("cpu")
            backend.batch_size = 2
            backend.raft = FakeRaft()
            backend.raft_transforms = lambda first, second: (first, second)
            backend.head = ConstantHead()
            backend.feature_mean = torch.zeros(FEATURE_DIM)
            backend.feature_std = torch.ones(FEATURE_DIM)
            backend.target_mean = torch.zeros(3)
            backend.target_std = torch.ones(3)
            backend.clamp_min = torch.full((FEATURE_DIM,), -100.0)
            backend.clamp_max = torch.full((FEATURE_DIM,), 100.0)
            backend.translation_post_matrix = torch.diag(torch.tensor([2.0, 3.0, 4.0]))

            motions = backend.predict_recording(frames, imu, _calibration())
            wrong_size = root / "wrong-size.png"
            Image.new("L", (13, 8), color=0).save(wrong_size)
            wrong_frames = [CameraSample(100, wrong_size), *frames[1:]]
            with self.assertRaisesRegex(RaftHybridError, "do not match calibration resolution"):
                backend.predict_recording(wrong_frames, imu, _calibration())

        self.assertEqual(len(motions), 2)
        self.assertEqual(RaftHybridBackend.motion_frame, "previous IMU sensor frame")
        self.assertEqual(motions[0].translation_previous_m, (2.0, 6.0, 12.0))
        self.assertEqual(motions[0].rotation_vector_rad, (0.0, 0.0, 0.0))


_FROZEN_PARITY_ENV = (
    "COMPACT_VIO_RAFT_PARITY_PACKAGE_MANIFEST",
    "COMPACT_VIO_RAFT_PARITY_DATA_ROOT",
    "COMPACT_VIO_RAFT_PARITY_FEATURE_CACHE",
)


@unittest.skipUnless(
    RUNTIME_AVAILABLE and all(os.environ.get(name) for name in _FROZEN_PARITY_ENV),
    "exact RAFT package, EuRoC root, and frozen feature cache were not supplied",
)
class RaftHybridFrozenCacheParityTests(unittest.TestCase):
    """A10 replay of raw images/IMU against cache d71a...; four contiguous V1 pairs."""

    def test_real_torchvision_backend_matches_frozen_cache_and_head_output(self) -> None:
        import torchvision

        from compact_vio.data.euroc import load_euroc_sequence
        from compact_vio.learning.dataset import _supervised_pairs

        cache_path = Path(os.environ["COMPACT_VIO_RAFT_PARITY_FEATURE_CACHE"])
        self.assertEqual(
            hashlib.sha256(cache_path.read_bytes()).hexdigest(),
            "d71a4895b26044d3674f1b9dbd24263aa500f23c2d9f9845b9a4c368a82ee1a9",
        )
        backend = RaftHybridBackend(
            os.environ["COMPACT_VIO_RAFT_PARITY_PACKAGE_MANIFEST"],
            device=os.environ.get("COMPACT_VIO_RAFT_PARITY_DEVICE", "cuda"),
            batch_size=4,
        )
        self.assertEqual(
            backend.package.raft_weights_sha256,
            RAFT_WEIGHTS_SHA256,
        )
        self.assertEqual(
            backend.package.head_checkpoint_sha256,
            "bbb9c85a33af81347fd8044438190b42e501fe5be72ba553e8a7265ecf2ca2c5",
        )
        self.assertEqual(
            backend.package.clamp_sha256,
            "d9c11c6f900986ad4b08da86d31c907f86630ae8fd1b89bb338774b49f0a464a",
        )

        sequence = load_euroc_sequence(
            Path(os.environ["COMPACT_VIO_RAFT_PARITY_DATA_ROOT"]) / "V1_03_difficult"
        )
        records = _supervised_pairs(sequence, frame_strides=(1,))[:4]
        cache = torch.load(cache_path, map_location="cpu", weights_only=True)
        self.assertEqual(cache["metadata"]["gyro_bias_policy"], "causal-prefix")
        frozen = cache["sequences"]["V1_03_difficult"]
        expected_timestamps = frozen["timestamps_ns"][:4]
        observed_timestamps = torch.tensor(
            [
                [
                    record.pair.previous_frame.timestamp_ns,
                    record.pair.current_frame.timestamp_ns,
                ]
                for record in records
            ],
            dtype=torch.int64,
        )
        torch.testing.assert_close(observed_timestamps, expected_timestamps, rtol=0, atol=0)
        frames = [
            CameraSample(
                records[0].pair.previous_frame.timestamp_ns,
                records[0].pair.previous_frame.image_path,
            ),
            *[
                CameraSample(
                    record.pair.current_frame.timestamp_ns, record.pair.current_frame.image_path
                )
                for record in records
            ],
        ]
        imu = tuple(
            ImuSample(
                item.timestamp_ns,
                tuple(item.angular_velocity_rs_s_rad_s),
                tuple(item.linear_acceleration_rs_s_m_s2),
            )
            for item in sequence.imu_measurements
        )

        captured: list[object] = []
        original_head = backend.head

        class CaptureHead(torch.nn.Module):
            def forward(self, features: object) -> object:
                captured.append(features.detach().cpu())
                return original_head(features)

        backend.head = CaptureHead().to(backend.device).eval()
        motions = backend.predict_recording(
            frames,
            imu,
            euroc_calibration_document(sequence),
        )
        actual_z = torch.cat(captured)
        raw_features = frozen["features"][:4].to(torch.float32)
        expected_z = torch.maximum(
            torch.minimum(
                (raw_features - backend.feature_mean.cpu()) / backend.feature_std.cpu(),
                backend.clamp_max.cpu(),
            ),
            backend.clamp_min.cpu(),
        )
        context = (
            f"torch={torch.__version__}, torchvision={torchvision.__version__}, "
            f"device={backend.device}, rtol=5e-4, atol=5e-5"
        )
        torch.testing.assert_close(actual_z, expected_z, rtol=5e-4, atol=5e-5, msg=context)
        with torch.inference_mode():
            expected_translation = (
                backend.target_mean
                + backend.target_std * original_head(expected_z.to(backend.device))
            ) @ backend.translation_post_matrix.transpose(0, 1)
        actual_translation = torch.tensor(
            [motion.translation_previous_m for motion in motions], dtype=torch.float32
        )
        torch.testing.assert_close(
            actual_translation,
            expected_translation.cpu(),
            rtol=5e-4,
            atol=5e-5,
            msg=context,
        )
        torch.testing.assert_close(
            torch.tensor([motion.rotation_vector_rad for motion in motions]),
            frozen["gyro_rotation_vector"][:4],
            rtol=5e-4,
            atol=5e-5,
            msg=context,
        )


if __name__ == "__main__":
    unittest.main()

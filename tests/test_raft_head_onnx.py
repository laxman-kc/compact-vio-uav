from __future__ import annotations

import builtins
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from collections import OrderedDict
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from compact_vio.learning.errors import LearningError

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

ONNX_STACK_AVAILABLE = bool(
    importlib.util.find_spec("onnx") and importlib.util.find_spec("onnxruntime")
)

if TORCH_AVAILABLE:
    from compact_vio.learning.raft_head_onnx import (
        RAFT_HEAD_FORMULA,
        RAFT_HEAD_INPUT_NAMES,
        RAFT_HEAD_ONNX_OPSET,
        RAFT_HEAD_OUTPUT_NAMES,
        RaftHeadParityResult,
        RaftHeadParityRun,
        _load_frozen_sources,
        export_raft_head_onnx,
        verify_raft_head_onnx_manifest,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _float_tensor_sha256(value: object) -> str:
    contiguous = value.detach().cpu().to(torch.float32).contiguous()
    return hashlib.sha256(contiguous.numpy().tobytes(order="C")).hexdigest()


def _bool_tensor_sha256(value: object) -> str:
    contiguous = value.detach().cpu().to(torch.bool).contiguous()
    return hashlib.sha256(contiguous.numpy().tobytes(order="C")).hexdigest()


class RaftHeadOnnxDependencyLightTests(unittest.TestCase):
    def test_help_does_not_import_torch_or_onnx_stacks(self) -> None:
        original_import = builtins.__import__

        def reject_optional(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            if name.split(".", 1)[0] in {"torch", "onnx", "onnxruntime"}:
                raise AssertionError("--help must not import optional export dependencies")
            return original_import(name, globals, locals, fromlist, level)

        module_name = "compact_vio.learning.raft_head_onnx"
        original_module = sys.modules.pop(module_name, None)
        builtins.__import__ = reject_optional
        try:
            from compact_vio.learning.raft_head_onnx import main

            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                main(["--help"])
        finally:
            builtins.__import__ = original_import
            sys.modules.pop(module_name, None)
            if original_module is not None:
                sys.modules[module_name] = original_module
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--expected-clamp-sha256", output.getvalue())


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class RaftHeadOnnxTests(unittest.TestCase):
    def _artifacts(self, root: Path) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
        torch.manual_seed(831)
        state = OrderedDict(
            (
                ("network.0.weight", torch.randn(128, 831, dtype=torch.float32) * 0.01),
                ("network.0.bias", torch.randn(128, dtype=torch.float32) * 0.01),
                ("network.2.weight", torch.randn(128, 128, dtype=torch.float32) * 0.01),
                ("network.2.bias", torch.randn(128, dtype=torch.float32) * 0.01),
                ("network.4.weight", torch.randn(3, 128, dtype=torch.float32) * 0.01),
                ("network.4.bias", torch.randn(3, dtype=torch.float32) * 0.01),
            )
        )
        feature_mean = torch.linspace(-0.5, 0.5, 831, dtype=torch.float32)
        feature_std = torch.linspace(0.25, 1.25, 831, dtype=torch.float32)
        target_mean = torch.tensor([0.1, -0.2, 0.3], dtype=torch.float32)
        target_std = torch.tensor([0.4, 0.5, 0.6], dtype=torch.float32)
        head: dict[str, object] = {
            "model_state_dict": state,
            "feature_mean": feature_mean,
            "feature_std": feature_std,
            "target_mean": target_mean,
            "target_std": target_std,
            "architecture": {
                "type": "MLP",
                "feature_dim": 831,
                "hidden_dim": 128,
                "layers": [831, 128, 128, 3],
                "activation": "GELU",
            },
            # Deliberately not the development prototype's epoch/weight: any
            # compatible exact-schema selected head is accepted and hash-bound.
            "selected": {"epoch": 9, "trajectory_weight": 0.2, "score": 1.25},
        }
        head_path = root / "head.pt"
        torch.save(head, head_path)
        head_sha256 = _sha256(head_path)

        constant_mask = torch.zeros(831, dtype=torch.bool)
        constant_mask[::13] = True
        clamp_min = torch.full((831,), -1.5, dtype=torch.float32)
        clamp_max = torch.full((831,), 2.0, dtype=torch.float32)
        clamp_min[constant_mask] = 0.0
        clamp_max[constant_mask] = 0.0
        clamp: dict[str, object] = {
            "record_type": "train_only_standardized_feature_clamp",
            "schema_version": 1,
            "train_sequence_ids": ["train-a", "train-b"],
            "source_cache_path": "/frozen/train-cache.pt",
            "source_cache_sha256": "a" * 64,
            "head_checkpoint_path": "/frozen/head.pt",
            "head_checkpoint_sha256": head_sha256,
            "feature_dim": 831,
            "rule": (
                "per-feature exact train standardized min/max; "
                "exact raw train constants forced to [0,0]"
            ),
            "clamp_min": clamp_min,
            "clamp_max": clamp_max,
            "constant_feature_mask": constant_mask,
            "clamp_min_tensor_sha256": _float_tensor_sha256(clamp_min),
            "clamp_max_tensor_sha256": _float_tensor_sha256(clamp_max),
            "constant_mask_tensor_sha256": _bool_tensor_sha256(constant_mask),
            "constant_feature_count": int(constant_mask.sum()),
        }
        clamp_path = root / "clamp.pt"
        torch.save(clamp, clamp_path)
        return head_path, clamp_path, head, clamp

    def test_loaded_model_applies_exact_clamp_formula(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            head_path, clamp_path, head, clamp = self._artifacts(root)
            loaded = _load_frozen_sources(
                head_path,
                clamp_path,
                expected_head_sha256=_sha256(head_path),
                expected_clamp_sha256=_sha256(clamp_path),
            )
            standardized = torch.linspace(-4.0, 4.0, 2 * 831, dtype=torch.float32).reshape(2, 831)
            features = head["feature_mean"] + head["feature_std"] * standardized
            clamped = torch.maximum(
                torch.minimum(standardized, clamp["clamp_max"]), clamp["clamp_min"]
            )
            state = head["model_state_dict"]
            hidden_1 = torch.nn.functional.gelu(
                torch.nn.functional.linear(
                    clamped, state["network.0.weight"], state["network.0.bias"]
                )
            )
            hidden_2 = torch.nn.functional.gelu(
                torch.nn.functional.linear(
                    hidden_1, state["network.2.weight"], state["network.2.bias"]
                )
            )
            normalized = torch.nn.functional.linear(
                hidden_2, state["network.4.weight"], state["network.4.bias"]
            )
            expected = head["target_mean"] + head["target_std"] * normalized
            with torch.inference_mode():
                actual = loaded.model(features)
            torch.testing.assert_close(actual, expected, rtol=0, atol=0)

            tampered = dict(clamp)
            tampered["clamp_min_tensor_sha256"] = "0" * 64
            tampered_path = root / "tampered-clamp.pt"
            torch.save(tampered, tampered_path)
            with self.assertRaisesRegex(LearningError, "clamp_min tensor SHA-256 mismatch"):
                _load_frozen_sources(
                    head_path,
                    tampered_path,
                    expected_head_sha256=_sha256(head_path),
                    expected_clamp_sha256=_sha256(tampered_path),
                )

    @unittest.skipUnless(ONNX_STACK_AVAILABLE, "ONNX and ONNX Runtime are not installed")
    def test_mocked_export_is_exclusive_and_manifest_binds_exact_sources(self) -> None:
        parity = RaftHeadParityResult(
            provider="CPUExecutionProvider",
            absolute_tolerance=1e-5,
            relative_tolerance=1e-5,
            runs=(
                RaftHeadParityRun(1, 1, 1e-7),
                RaftHeadParityRun(2, 4, 2e-7),
            ),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            head_path, clamp_path, _, clamp = self._artifacts(root)
            model_path = root / "raft-head.onnx"
            manifest_path = root / "raft-head.onnx.json"
            matrix = (2.0, 0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 4.0)

            with patch(
                "compact_vio.learning.raft_head_onnx.check_raft_head_onnx_parity",
                return_value=parity,
            ):
                result = export_raft_head_onnx(
                    head_path,
                    clamp_path,
                    model_path,
                    manifest_path,
                    expected_head_sha256=_sha256(head_path),
                    expected_clamp_sha256=_sha256(clamp_path),
                    translation_post_matrix=matrix,
                )

            manifest = verify_raft_head_onnx_manifest(
                manifest_path,
                head_checkpoint_path=head_path,
                clamp_artifact_path=clamp_path,
            )
            self.assertEqual(result.model_sha256, _sha256(model_path))
            self.assertEqual(result.manifest_sha256, _sha256(manifest_path))
            self.assertEqual(manifest["export"]["formula"], RAFT_HEAD_FORMULA)
            self.assertEqual(manifest["export"]["opset_version"], RAFT_HEAD_ONNX_OPSET)
            self.assertEqual(manifest["export"]["dynamic_axes"], ["batch"])
            self.assertEqual(
                manifest["export"]["translation_post_matrix"],
                [[2.0, 0.0, 0.0], [0.0, 3.0, 0.0], [0.0, 0.0, 4.0]],
            )
            self.assertEqual(manifest["source_head"]["checkpoint_sha256"], _sha256(head_path))
            self.assertEqual(manifest["source_clamp"]["artifact_sha256"], _sha256(clamp_path))
            self.assertEqual(
                manifest["source_clamp"]["clamp_min_tensor_sha256"],
                clamp["clamp_min_tensor_sha256"],
            )
            self.assertEqual(
                manifest["source_clamp"]["clamp_max_tensor_sha256"],
                clamp["clamp_max_tensor_sha256"],
            )
            self.assertEqual(
                manifest["source_clamp"]["constant_mask_tensor_sha256"],
                clamp["constant_mask_tensor_sha256"],
            )
            self.assertEqual(manifest["parity"]["status"], "passed")

            original = json.loads(manifest_path.read_text(encoding="utf-8"))

            def write_tampered(name: str, mutate: object) -> Path:
                payload = json.loads(json.dumps(original))
                mutate(payload)
                path = root / f"tampered-{name}.json"
                path.write_text(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return path

            tampered_cases = (
                (
                    "formula",
                    lambda payload: payload["export"].__setitem__("formula", "tampered"),
                    "export contract",
                ),
                (
                    "io",
                    lambda payload: payload["io_contract"]["outputs"][0].__setitem__(
                        "frame", "wrong"
                    ),
                    "I/O contract",
                ),
                (
                    "parity",
                    lambda payload: payload["parity"].__setitem__("absolute_tolerance", 1.0),
                    "tolerances exceed",
                ),
                (
                    "parity-status",
                    lambda payload: payload["parity"].__setitem__("status", "fabricated"),
                    "status or provider",
                ),
                (
                    "architecture",
                    lambda payload: payload["source_head"]["architecture"].__setitem__(
                        "hidden_dim", 64
                    ),
                    "source architecture",
                ),
                (
                    "selected",
                    lambda payload: payload["source_head"].__setitem__("selected", {}),
                    "selected metadata",
                ),
                (
                    "clamp",
                    lambda payload: payload["source_clamp"].__setitem__("rule", "tampered"),
                    "source clamp contract",
                ),
            )
            for name, mutate, error in tampered_cases:
                with self.subTest(name=name), self.assertRaisesRegex(LearningError, error):
                    verify_raft_head_onnx_manifest(write_tampered(name, mutate))
            with self.assertRaisesRegex(LearningError, "refusing to overwrite"):
                export_raft_head_onnx(
                    head_path,
                    clamp_path,
                    model_path,
                    manifest_path,
                    expected_head_sha256=_sha256(head_path),
                    expected_clamp_sha256=_sha256(clamp_path),
                )

    def test_source_hash_mismatch_is_rejected_before_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            head_path, clamp_path, _, _ = self._artifacts(root)
            with self.assertRaisesRegex(LearningError, "head checkpoint SHA-256 mismatch"):
                export_raft_head_onnx(
                    head_path,
                    clamp_path,
                    root / "new.onnx",
                    root / "new.json",
                    expected_head_sha256="0" * 64,
                    expected_clamp_sha256=_sha256(clamp_path),
                )

    @unittest.skipUnless(ONNX_STACK_AVAILABLE, "ONNX and ONNX Runtime are not installed")
    def test_real_export_is_checked_dynamic_and_matches_onnx_runtime(self) -> None:
        import numpy as np
        import onnx
        import onnxruntime as ort

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            head_path, clamp_path, _, clamp = self._artifacts(root)
            model_path = root / "raft-head.onnx"
            manifest_path = root / "raft-head.onnx.json"
            post_matrix = (
                (1.0, 0.25, -0.5),
                (-0.75, 1.5, 0.1),
                (0.2, -0.3, 0.9),
            )
            result = export_raft_head_onnx(
                head_path,
                clamp_path,
                model_path,
                manifest_path,
                expected_head_sha256=_sha256(head_path),
                expected_clamp_sha256=_sha256(clamp_path),
                translation_post_matrix=post_matrix,
            )
            self.assertIsNotNone(result.parity)
            self.assertEqual([run.batch_size for run in result.parity.runs], [1, 4])
            self.assertLess(result.parity.max_translation_abs_error, 1e-5)

            graph = onnx.load_model(model_path)
            onnx.checker.check_model(graph, full_check=True)
            self.assertEqual(graph.graph.input[0].name, RAFT_HEAD_INPUT_NAMES[0])
            self.assertEqual(graph.graph.output[0].name, RAFT_HEAD_OUTPUT_NAMES[0])
            self.assertEqual(graph.graph.input[0].type.tensor_type.shape.dim[0].dim_param, "batch")
            self.assertEqual(graph.graph.input[0].type.tensor_type.shape.dim[1].dim_value, 831)
            metadata = {item.key: item.value for item in graph.metadata_props}
            self.assertEqual(
                metadata["compact_vio.raft_head_clamp_min_tensor_sha256"],
                clamp["clamp_min_tensor_sha256"],
            )
            self.assertEqual(
                metadata["compact_vio.raft_head_translation_post_matrix"],
                "[[1.0,0.25,-0.5],[-0.75,1.5,0.1],[0.2,-0.3,0.9]]",
            )

            identity_model = _load_frozen_sources(
                head_path,
                clamp_path,
                expected_head_sha256=_sha256(head_path),
                expected_clamp_sha256=_sha256(clamp_path),
            ).model
            features = torch.linspace(-2.0, 2.0, 2 * 831, dtype=torch.float32).reshape(2, 831)
            with torch.inference_mode():
                decoded = identity_model(features)
                expected = decoded @ torch.tensor(post_matrix, dtype=torch.float32).transpose(0, 1)
            session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
            (actual,) = session.run(
                list(RAFT_HEAD_OUTPUT_NAMES),
                {RAFT_HEAD_INPUT_NAMES[0]: features.numpy()},
            )
            np.testing.assert_allclose(actual, expected.numpy(), rtol=1e-5, atol=1e-5)

            manifest = verify_raft_head_onnx_manifest(manifest_path)
            self.assertEqual(manifest["artifact"]["onnx_sha256"], _sha256(model_path))
            self.assertEqual(
                manifest["export"]["translation_post_matrix"],
                [list(row) for row in post_matrix],
            )
            original_model = model_path.read_bytes()

            def rebind_artifact() -> None:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
                payload["artifact"]["byte_size"] = model_path.stat().st_size
                payload["artifact"]["onnx_sha256"] = _sha256(model_path)
                manifest_path.write_text(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    + "\n",
                    encoding="utf-8",
                )

            model_path.write_bytes(b"this is not an ONNX graph")
            rebind_artifact()
            with self.assertRaisesRegex(LearningError, "ONNX graph is invalid"):
                verify_raft_head_onnx_manifest(
                    manifest_path,
                    head_checkpoint_path=head_path,
                    clamp_artifact_path=clamp_path,
                    require_passed_parity=True,
                )

            model_path.write_bytes(original_model)
            tampered_graph = onnx.load_model(model_path)
            for item in tampered_graph.metadata_props:
                if item.key == "compact_vio.formula":
                    item.value = "tampered"
            onnx.save_model(tampered_graph, model_path)
            rebind_artifact()
            with self.assertRaisesRegex(LearningError, "metadata does not match"):
                verify_raft_head_onnx_manifest(
                    manifest_path,
                    head_checkpoint_path=head_path,
                    clamp_artifact_path=clamp_path,
                    require_passed_parity=True,
                )


if __name__ == "__main__":
    unittest.main()

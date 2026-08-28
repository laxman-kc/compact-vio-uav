from __future__ import annotations

import builtins
import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

if TORCH_AVAILABLE:
    from compact_vio.learning.checkpoint import CheckpointProvenance, save_checkpoint
    from compact_vio.learning.config import DataConfig, ModelConfig, TrainingConfig
    from compact_vio.learning.dataset import (
        SampleIdentity,
        VIOBatch,
        VIOSequenceBatch,
    )
    from compact_vio.learning.errors import LearningError
    from compact_vio.learning.inference import (
        load_inference_model,
        predict_batch,
        predict_sequence_batch,
    )
    from compact_vio.learning.inference_checkpoint import (
        INDEPENDENT_INFERENCE_POLICY_ID,
        STATEFUL_INFERENCE_POLICY_ID,
        _tensor_bytes,
        export_inference_checkpoint,
        load_inference_checkpoint,
        model_state_sha256,
    )
    from compact_vio.learning.model import CompactVIO
    from compact_vio.learning.training import seed_everything


LEGACY_ROTATION_POLICY = "shared-recurrent-fusion-state/v1"
V4_ROTATION_POLICY = "current-pair-zero-initialized-fusion-state/v1"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class InferenceExportDependencyLightTests(unittest.TestCase):
    def test_help_does_not_import_torch_checkpoint_modules(self) -> None:
        original_import = builtins.__import__

        def reject_torch(
            name: str,
            globals: object = None,
            locals: object = None,
            fromlist: object = (),
            level: int = 0,
        ) -> object:
            if name == "torch" or name.startswith("torch."):
                raise AssertionError("--help must not import Torch")
            return original_import(name, globals, locals, fromlist, level)

        sys.modules.pop("compact_vio.learning.inference_export_cli", None)
        builtins.__import__ = reject_torch
        try:
            from compact_vio.learning.inference_export_cli import main

            output = io.StringIO()
            with redirect_stdout(output), self.assertRaises(SystemExit) as raised:
                main(["--help"])
        finally:
            builtins.__import__ = original_import
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--expected-source-sha256", output.getvalue())


@unittest.skipUnless(TORCH_AVAILABLE, "PyTorch training extra is not installed")
class InferenceCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model_config = ModelConfig(
            image_height_px=32,
            image_width_px=48,
            visual_feature_dim=24,
            imu_hidden_dim=12,
            fusion_hidden_dim=24,
            dropout_probability=0.0,
            rotation_state_source=LEGACY_ROTATION_POLICY,
        )
        self.data_config = DataConfig(
            image_mean=0.45,
            image_std=0.2,
            gyroscope_scale_rad_s=4.0,
            accelerometer_scale_m_s2=18.0,
        )
        self.training_config = TrainingConfig(
            model=self.model_config,
            data=self.data_config,
            batch_size=2,
            epochs=3,
            num_workers=0,
            use_amp=False,
        )
        self.provenance = CheckpointProvenance.create(
            dataset_id="synthetic-export-contract",
            split_id="disjoint-export-split-v1",
            train_sequence_ids=("train",),
            validation_sequence_ids=("validation",),
            source_sha256={"train": "a" * 64, "validation": "b" * 64},
            calibration_sha256={"train": "c" * 64, "validation": "d" * 64},
            code_revision="export-contract-test-revision",
        )

    def _save_source(
        self,
        path: Path,
        *,
        model_config: ModelConfig | None = None,
    ) -> CompactVIO:
        config = replace(self.training_config, model=model_config or self.model_config)
        seed_everything(503)
        model = CompactVIO(config.model)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
        save_checkpoint(
            path,
            model=model,
            config=config,
            epoch=2,
            metrics={
                "train/weighted_motion_loss": 0.3,
                "validation/weighted_motion_loss": 0.2,
            },
            provenance=self.provenance,
            optimizer=optimizer,
        )
        return model

    def _batch(self) -> VIOBatch:
        return VIOBatch(
            frame_pairs=torch.randn(2, 2, 32, 48),
            imu=torch.randn(2, 4, 6),
            imu_lengths=torch.tensor([4, 3]),
            delta_time_s=torch.full((2, 1), 0.05),
            target_motion=torch.zeros(2, 6),
            identities=(
                SampleIdentity("synthetic", 100, 200),
                SampleIdentity("synthetic", 200, 300),
            ),
        )

    def _sequence_batch(self) -> VIOSequenceBatch:
        return VIOSequenceBatch(
            frame_pairs=torch.randn(1, 2, 2, 32, 48),
            imu=torch.randn(1, 2, 4, 6),
            imu_lengths=torch.full((1, 2), 4, dtype=torch.int64),
            delta_time_s=torch.full((1, 2, 1), 0.05),
            target_motion=torch.zeros(1, 2, 6),
            step_mask=torch.ones(1, 2, dtype=torch.bool),
            identities=(
                (
                    SampleIdentity("synthetic", 100, 200),
                    SampleIdentity("synthetic", 200, 300),
                ),
            ),
            chain_ids=("synthetic:stride=1",),
            chunk_indices=(0,),
            chain_starts=(True,),
            chain_ends=(True,),
        )

    def test_tensor_hash_uses_exact_torch_storage_bytes_without_numpy(self) -> None:
        floating = torch.tensor([1.0, -2.5], dtype=torch.float32)
        noncontiguous = torch.arange(8, dtype=torch.int16)[1:7:2]
        original_numpy = torch.Tensor.numpy

        def reject_numpy(self: torch.Tensor, *args: object, **kwargs: object) -> object:
            raise AssertionError("tensor hashing must not call Tensor.numpy")

        torch.Tensor.numpy = reject_numpy
        try:
            floating_bytes = _tensor_bytes(floating, name="floating")
            noncontiguous_bytes = _tensor_bytes(noncontiguous, name="noncontiguous")
            first = model_state_sha256({"floating": floating, "view": noncontiguous})
            second = model_state_sha256({"view": noncontiguous, "floating": floating})
        finally:
            torch.Tensor.numpy = original_numpy

        self.assertEqual(floating_bytes, struct.pack("=ff", 1.0, -2.5))
        self.assertEqual(noncontiguous_bytes, struct.pack("=hhh", 1, 3, 5))
        self.assertEqual(first, second)
        changed = floating.clone()
        changed[0] = torch.nextafter(changed[0], torch.tensor(float("inf")))
        self.assertNotEqual(
            first,
            model_state_sha256({"floating": changed, "view": noncontiguous}),
        )

    def test_canonical_identity_and_parity_survive_container_byte_variation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            destination = root / "inference.pt"
            alternate_container = root / "inference-alternate-container.pt"
            original = self._save_source(source)
            batch = self._batch()
            expected = predict_batch(original, batch).motion_vectors

            exported = export_inference_checkpoint(
                source,
                destination,
                expected_source_sha256=_sha256(source),
                inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )
            payload = torch.load(destination, map_location="cpu", weights_only=True)
            # The same semantic payload may have different outer bytes across
            # Torch serializers/runtimes; only its canonical identity must match.
            torch.save(payload, alternate_container, _use_new_zipfile_serialization=False)
            loaded = load_inference_checkpoint(
                destination,
                expected_artifact_sha256=_sha256(destination),
                expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )
            alternate_loaded = load_inference_checkpoint(
                alternate_container,
                expected_artifact_sha256=_sha256(alternate_container),
                expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )
            actual = predict_batch(loaded.model, batch).motion_vectors
            alternate_actual = predict_batch(alternate_loaded.model, batch).motion_vectors
            transparent_model, transparent_metadata = load_inference_model(
                destination,
                expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                expected_checkpoint_sha256=_sha256(destination),
            )
            transparent_actual = predict_batch(transparent_model, batch).motion_vectors

        self.assertEqual(
            set(payload),
            {
                "metadata",
                "metadata_sha256",
                "model_state_dict",
                "record_type",
                "schema_version",
            },
        )
        for forbidden in (
            "config",
            "epoch",
            "metrics",
            "optimizer_state_dict",
            "training_history",
        ):
            self.assertNotIn(forbidden, payload)
        self.assertNotIn("training_history", payload["metadata"])
        self.assertEqual(
            set(payload["metadata"]["source_lineage"]),
            {"checkpoint_sha256", "selected_epoch", "selected_metrics"},
        )
        canonical = json.dumps(
            payload["metadata"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        self.assertEqual(payload["metadata_sha256"], hashlib.sha256(canonical).hexdigest())
        self.assertEqual(exported.artifact_sha256, loaded.artifact_sha256)
        self.assertEqual(exported.artifact_transport_sha256, loaded.artifact_transport_sha256)
        self.assertNotEqual(exported.artifact_sha256, alternate_loaded.artifact_sha256)
        self.assertEqual(exported.metadata_sha256, loaded.metadata_sha256)
        self.assertEqual(exported.canonical_identity_sha256, loaded.canonical_identity_sha256)
        self.assertEqual(exported.metadata_sha256, alternate_loaded.metadata_sha256)
        self.assertEqual(loaded.identity, alternate_loaded.identity)
        self.assertEqual(loaded.identity.model_config, self.model_config)
        self.assertEqual(loaded.identity.data_config, self.data_config)
        self.assertEqual(loaded.identity.provenance, self.provenance)
        self.assertEqual(loaded.identity.training_config, self.training_config)
        self.assertEqual(loaded.identity.selected_source_epoch, 2)
        self.assertEqual(
            loaded.identity.metrics,
            {
                "train/weighted_motion_loss": 0.3,
                "validation/weighted_motion_loss": 0.2,
            },
        )
        self.assertEqual(
            loaded.identity.inference_policy_id,
            INDEPENDENT_INFERENCE_POLICY_ID,
        )
        self.assertEqual(transparent_metadata.config, self.training_config)
        self.assertEqual(transparent_metadata.epoch, 2)
        self.assertEqual(transparent_metadata.metrics, loaded.identity.metrics)
        self.assertEqual(transparent_metadata.provenance, self.provenance)
        torch.testing.assert_close(expected, actual, rtol=0, atol=0)
        torch.testing.assert_close(expected, alternate_actual, rtol=0, atol=0)
        torch.testing.assert_close(expected, transparent_actual, rtol=0, atol=0)
        self.assertTrue(torch.equal(expected, actual))
        self.assertTrue(torch.equal(expected, alternate_actual))
        self.assertTrue(torch.equal(expected, transparent_actual))

    def test_v2_v3_and_v4_policy_identities_and_stateful_parity_are_preserved(self) -> None:
        variants = (
            ("v2", self.model_config, INDEPENDENT_INFERENCE_POLICY_ID),
            ("v3", self.model_config, STATEFUL_INFERENCE_POLICY_ID),
            (
                "v4",
                replace(self.model_config, rotation_state_source=V4_ROTATION_POLICY),
                STATEFUL_INFERENCE_POLICY_ID,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for candidate_id, model_config, inference_policy in variants:
                with self.subTest(candidate_id=candidate_id):
                    source = root / f"{candidate_id}-training.pt"
                    destination = root / f"{candidate_id}-inference.pt"
                    original = self._save_source(source, model_config=model_config)
                    sequence = self._sequence_batch()
                    expected = predict_sequence_batch(original, sequence).motion_vectors
                    export_inference_checkpoint(
                        source,
                        destination,
                        expected_source_sha256=_sha256(source),
                        inference_policy_id=inference_policy,
                    )
                    loaded = load_inference_checkpoint(
                        destination,
                        expected_artifact_sha256=_sha256(destination),
                        expected_inference_policy_id=inference_policy,
                    )
                    actual = predict_sequence_batch(loaded.model, sequence).motion_vectors

                    self.assertEqual(
                        loaded.identity.model_config.rotation_state_source,
                        model_config.rotation_state_source,
                    )
                    self.assertEqual(loaded.identity.inference_policy_id, inference_policy)
                    torch.testing.assert_close(expected, actual, rtol=0, atol=0)
                    self.assertTrue(torch.equal(expected, actual))

    def test_loader_rejects_policy_mismatch_and_integrity_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            destination = root / "inference.pt"
            self._save_source(source)
            export_inference_checkpoint(
                source,
                destination,
                expected_source_sha256=_sha256(source),
                inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )
            with self.assertRaisesRegex(LearningError, "inference policy mismatch"):
                load_inference_checkpoint(
                    destination,
                    expected_artifact_sha256=_sha256(destination),
                    expected_inference_policy_id=STATEFUL_INFERENCE_POLICY_ID,
                )

            payload = torch.load(destination, map_location="cpu", weights_only=True)
            payload["metadata"]["source_lineage"]["checkpoint_sha256"] = "0" * 64
            metadata_tampered = root / "metadata-tampered.pt"
            torch.save(payload, metadata_tampered)
            with self.assertRaisesRegex(LearningError, "metadata SHA-256 mismatch"):
                load_inference_checkpoint(
                    metadata_tampered,
                    expected_artifact_sha256=_sha256(metadata_tampered),
                    expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )

            payload = torch.load(destination, map_location="cpu", weights_only=True)
            state = payload["model_state_dict"]
            first_name = sorted(state)[0]
            state[first_name] = state[first_name].clone()
            state[first_name].view(-1)[0] += 1.0
            state_tampered = root / "state-tampered.pt"
            torch.save(payload, state_tampered)
            with self.assertRaisesRegex(LearningError, "model-state SHA-256 mismatch"):
                load_inference_checkpoint(
                    state_tampered,
                    expected_artifact_sha256=_sha256(state_tampered),
                    expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )

    def test_inference_loading_requires_and_verifies_caller_trust_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            destination = root / "inference.pt"
            self._save_source(source)
            exported = export_inference_checkpoint(
                source,
                destination,
                expected_source_sha256=_sha256(source),
                inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )

            with self.assertRaises(TypeError):
                load_inference_checkpoint(  # type: ignore[call-arg]
                    destination,
                    expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )
            with self.assertRaisesRegex(
                LearningError,
                "requires expected_checkpoint_sha256",
            ):
                load_inference_model(
                    destination,
                    expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )
            original_torch_load = torch.load

            def reject_deserialization(*args: object, **kwargs: object) -> object:
                raise AssertionError("a trust-root mismatch must fail before torch.load")

            torch.load = reject_deserialization
            try:
                with self.assertRaisesRegex(LearningError, "artifact SHA-256 mismatch"):
                    load_inference_checkpoint(
                        destination,
                        expected_artifact_sha256="0" * 64,
                        expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                    )
                with self.assertRaisesRegex(LearningError, "checkpoint SHA-256 mismatch"):
                    load_inference_model(
                        destination,
                        expected_checkpoint_sha256="0" * 64,
                        expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                    )
            finally:
                torch.load = original_torch_load

            loaded = load_inference_checkpoint(
                destination,
                expected_artifact_sha256=exported.artifact_sha256,
                expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )
            self.assertEqual(loaded.artifact_sha256, exported.artifact_sha256)

    def test_transparent_loader_fails_closed_on_record_schema_or_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            destination = root / "inference.pt"
            self._save_source(source)
            legacy_model, legacy_metadata = load_inference_model(
                source,
                expected_inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                expected_checkpoint_sha256=_sha256(source),
            )
            self.assertIsInstance(legacy_model, CompactVIO)
            self.assertEqual(legacy_metadata.config, self.training_config)
            export_inference_checkpoint(
                source,
                destination,
                expected_source_sha256=_sha256(source),
                inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )
            original = torch.load(destination, map_location="cpu", weights_only=True)
            mutations = (
                ("wrong-record", {**original, "record_type": "not_the_record"}),
                ("wrong-schema", {**original, "schema_version": "2.0.0"}),
                ("extra-field", {**original, "unexpected": True}),
            )
            for name, payload in mutations:
                with self.subTest(name=name):
                    path = root / f"{name}.pt"
                    torch.save(payload, path)
                    with self.assertRaisesRegex(
                        LearningError,
                        "record type or schema is unsupported or incomplete",
                    ):
                        load_inference_model(
                            path,
                            expected_checkpoint_sha256=_sha256(path),
                        )

    def test_export_refuses_hash_mismatch_overwrite_symlinks_and_non_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "training.pt"
            self._save_source(source)

            with self.assertRaisesRegex(LearningError, "SHA-256 mismatch"):
                export_inference_checkpoint(
                    source,
                    root / "hash-mismatch.pt",
                    expected_source_sha256="0" * 64,
                    inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )

            existing = root / "existing.pt"
            existing.write_bytes(b"owner data")
            with self.assertRaisesRegex(LearningError, "refusing to overwrite"):
                export_inference_checkpoint(
                    source,
                    existing,
                    expected_source_sha256=_sha256(source),
                    inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )
            self.assertEqual(existing.read_bytes(), b"owner data")

            directory_destination = root / "directory-destination"
            directory_destination.mkdir()
            with self.assertRaisesRegex(LearningError, "refusing to overwrite"):
                export_inference_checkpoint(
                    source,
                    directory_destination,
                    expected_source_sha256=_sha256(source),
                    inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )

            source_link = root / "source-link.pt"
            source_link.symlink_to(source)
            with self.assertRaisesRegex(LearningError, "regular non-symlink"):
                export_inference_checkpoint(
                    source_link,
                    root / "from-link.pt",
                    expected_source_sha256=_sha256(source),
                    inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )

            destination_link = root / "destination-link.pt"
            destination_link.symlink_to(root / "missing-target.pt")
            with self.assertRaisesRegex(LearningError, "refusing to overwrite"):
                export_inference_checkpoint(
                    source,
                    destination_link,
                    expected_source_sha256=_sha256(source),
                    inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )

            inference_source = root / "inference-source.pt"
            export_inference_checkpoint(
                source,
                inference_source,
                expected_source_sha256=_sha256(source),
                inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
            )
            with self.assertRaisesRegex(
                LearningError,
                "source must use the supported training checkpoint schema",
            ):
                export_inference_checkpoint(
                    inference_source,
                    root / "re-export.pt",
                    expected_source_sha256=_sha256(inference_source),
                    inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )

            source_directory = root / "source-directory"
            source_directory.mkdir()
            with self.assertRaisesRegex(LearningError, "regular non-symlink"):
                export_inference_checkpoint(
                    source_directory,
                    root / "from-directory.pt",
                    expected_source_sha256="0" * 64,
                    inference_policy_id=INDEPENDENT_INFERENCE_POLICY_ID,
                )


if __name__ == "__main__":
    unittest.main()

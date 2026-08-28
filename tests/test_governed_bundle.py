from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from compact_vio.artifacts import create_manifest, inventory_bundle
from compact_vio.governed_bundle import (
    EVALUATION_CONFIG_PATH,
    GovernedBundleError,
    build_parser,
    main,
    validate_governed_bundle,
)
from compact_vio.learning.config import TrainingConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = REPOSITORY_ROOT / "experiments" / "schemas"
HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GovernedBundleDependencyLightTests(unittest.TestCase):
    def test_help_does_not_import_jsonschema_or_training_runtime(self) -> None:
        help_text = build_parser().format_help()

        self.assertIn("compact-vio-validate-governed-bundle", help_text)
        self.assertIn("--schema-dir", help_text)


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema governance extra is not installed")
class GovernedBundleTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name) / "governed"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @staticmethod
    def _environment() -> dict[str, object]:
        return {
            "git": {
                "repository": "https://example.invalid/compact-vio-uav.git",
                "commit_sha": "1" * 40,
                "branch": "main",
                "dirty": False,
            },
            "environment": {
                "os": "Fixture OS 1",
                "architecture": "x86_64",
                "fingerprint": "sha256:" + "2" * 64,
                "container_digest": None,
                "runtime_versions": {
                    "python": "3.13.7",
                    "torch": "2.7.0",
                },
            },
            "hardware": {
                "platform_role": "training_worker",
                "summary": "synthetic validation fixture",
                "cpu": "fixture CPU",
                "gpu": "fixture GPU",
                "memory_bytes": 1024,
                "driver": "fixture driver",
                "power_mode": None,
            },
        }

    @staticmethod
    def _kind(path: str) -> str:
        return {
            "environment.json": "environment",
            "provenance/acquisition-record.md": "configuration",
            "provenance/evaluation-config.json": "configuration",
            "provenance/split-manifest.json": "configuration",
            "resolved-config.json": "configuration",
            "trainer-output/artifact-manifest.json": "other",
            "trainer-output/checkpoint.pt": "checkpoint",
            "trainer-output/run-summary.json": "report",
            "trainer-output/test-metrics.json": "metrics",
            "trainer-output/test-predictions.jsonl": "trajectory",
            "trainer-output/training-history.json": "metrics",
        }[path]

    @staticmethod
    def _artifact_id(path: str) -> str:
        return "fixture-" + path.replace("/", "-").replace(".", "-")

    def _build(self) -> Path:
        self.root.mkdir()
        provenance = self.root / "provenance"
        provenance.mkdir()
        trainer = self.root / "trainer-output"
        trainer.mkdir()

        resolved_config = TrainingConfig(
            batch_size=2,
            epochs=3,
            num_workers=0,
            seed=20260828,
            use_amp=False,
        ).to_dict()
        _write_json(self.root / "resolved-config.json", resolved_config)
        resolved_sha256 = _sha256(self.root / "resolved-config.json")
        environment = self._environment()
        _write_json(self.root / "environment.json", environment)
        (provenance / "acquisition-record.md").write_text(
            "# Synthetic acquisition record\n",
            encoding="utf-8",
        )
        _write_json(
            provenance / "split-manifest.json",
            {
                "record_type": "synthetic_split_manifest",
                "schema_version": "1.0.0",
                "train": ["fixture-sequence"],
            },
        )
        evaluation_config = {
            "record_type": "resolved_evaluation_configuration",
            "schema_version": "1.0.0",
            "evaluation_sequence": "fixture-sequence",
            "evaluation_role": "development_test_fixture",
            "causal": True,
            "metric_scale_claim": False,
            "primary_alignment": "none",
            "metric_policy_id": "fixture/no-alignment/v1",
            "frame_stride": 1,
            "fusion_state_policy": "zero-per-independent-pair/v1",
            "coverage_policy": "all-eligible-pairs/v1",
            "controls": ["zero-motion/v1"],
            "limitations": ["Synthetic fixture only."],
        }
        _write_json(provenance / "evaluation-config.json", evaluation_config)

        (trainer / "checkpoint.pt").write_bytes(b"synthetic checkpoint bytes")
        (trainer / "test-predictions.jsonl").write_text(
            '{"prediction": [0, 0, 0, 0, 0, 0]}\n',
            encoding="utf-8",
        )
        _write_json(trainer / "test-metrics.json", {"coverage": {"produced": 1}})
        _write_json(trainer / "training-history.json", {"epochs": [1, 2, 3]})
        _write_json(
            trainer / "run-summary.json",
            {
                "completed_at": "2026-08-28T13:13:04Z",
                "config": {
                    "path": "/fixture/config.json",
                    "sha256": "4" * 64,
                },
                "experiment_id": "fixture-v5",
                "git_revision": "1" * 40,
                "runtime_config": resolved_config,
                "started_at": "2026-08-28T13:05:56Z",
                "status": "completed",
            },
        )
        create_manifest(trainer)

        records = inventory_bundle(self.root)
        artifacts = [
            {
                "artifact_id": self._artifact_id(record.path),
                "kind": self._kind(record.path),
                "retention_class": "reproducibility_critical",
                "rights_lane": "unresolved",
                "path": record.path,
                "byte_size": record.bytes,
                "sha256": record.sha256,
            }
            for record in records
        ]
        config_reference = {
            "path": "resolved-config.json",
            "sha256": resolved_sha256,
        }
        acquisition_reference = {
            "path": "provenance/acquisition-record.md",
            "sha256": _sha256(provenance / "acquisition-record.md"),
        }
        split_sha256 = _sha256(provenance / "split-manifest.json")
        evaluation_reference = {
            "path": EVALUATION_CONFIG_PATH,
            "sha256": _sha256(provenance / "evaluation-config.json"),
        }
        run_manifest = {
            "schema_version": "1.1.0",
            "run_id": "fixture-governed-v5",
            "created_at": "2026-08-28T13:05:56Z",
            "started_at": "2026-08-28T13:05:56Z",
            "finished_at": "2026-08-28T13:13:04Z",
            "status": "succeeded",
            "purpose": "Validate a synthetic governed wrapper; not a scientific result.",
            "protocol_revision": "reports/fixture-plan.md@" + "1" * 40,
            "provenance": environment,
            "experiment": {
                "candidate_family": "end_to_end_learned",
                "candidate_name": "fixture-v5",
                "candidate_version": "v5",
                "configuration": config_reference,
                "seeds": [20260828],
            },
            "data": {
                "datasets": [
                    {
                        "dataset_id": "fixture-dataset",
                        "dataset_version": "1",
                        "registry_revision": "fixture-registry@" + "1" * 40,
                        "acquisition_manifest": acquisition_reference,
                        "splits": [
                            {
                                "name": "fixture-development-split",
                                "role": "train",
                                "manifest_path": "provenance/split-manifest.json",
                                "manifest_sha256": split_sha256,
                                "source_group_policy": "whole fixture sequences",
                            }
                        ],
                    }
                ],
                "preprocessing": config_reference,
            },
            "evaluation": {
                "configuration": evaluation_reference,
                "metric_scale_claim": False,
                "primary_alignment": "none",
                "causal": True,
                "metrics_artifact_id": self._artifact_id("trainer-output/test-metrics.json"),
                "coverage_artifact_id": self._artifact_id("trainer-output/test-metrics.json"),
            },
            "artifacts": artifacts,
            "outcome": {
                "summary": "Trainer completed; fixture acceptance is outside scope.",
                "exit_code": 0,
                "failure_category": "none",
            },
            "protocol_deviations": ["Synthetic test fixture only; it is not retained evidence."],
        }
        _write_json(self.root / "run-manifest.json", run_manifest)
        create_manifest(self.root)
        return self.root

    def _recreate_outer_manifest(self) -> None:
        (self.root / "artifact-manifest.json").unlink()
        create_manifest(self.root)

    def _run_manifest(self) -> dict[str, object]:
        return json.loads((self.root / "run-manifest.json").read_text(encoding="utf-8"))

    def _write_run_manifest(self, value: dict[str, object]) -> None:
        _write_json(self.root / "run-manifest.json", value)

    def _update_run_artifact_identity(self, path: str) -> None:
        run = self._run_manifest()
        artifact = next(item for item in run["artifacts"] if item["path"] == path)  # type: ignore[index]
        target = self.root / path
        artifact["byte_size"] = target.stat().st_size
        artifact["sha256"] = _sha256(target)
        self._write_run_manifest(run)

    def test_validates_exact_nested_and_outer_bundle_bindings(self) -> None:
        root = self._build()

        report = validate_governed_bundle(root, schema_directory=SCHEMA_DIRECTORY)

        self.assertEqual(report.run_id, "fixture-governed-v5")
        self.assertEqual(report.payload_file_count, 12)
        self.assertEqual(report.declared_artifact_count, 11)
        self.assertEqual(report.trainer_payload_file_count, 5)
        self.assertEqual(report.run_manifest_sha256, _sha256(root / "run-manifest.json"))
        self.assertEqual(
            report.artifact_manifest_sha256,
            _sha256(root / "artifact-manifest.json"),
        )
        self.assertEqual(
            report.trainer_manifest_sha256,
            _sha256(root / "trainer-output/artifact-manifest.json"),
        )
        self.assertEqual(
            report.evaluation_config_sha256,
            _sha256(root / EVALUATION_CONFIG_PATH),
        )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main([str(root), "--schema-dir", str(SCHEMA_DIRECTORY)])
        event = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(event["event"], "governed_bundle_validated")
        self.assertTrue(event["ok"])

    def test_rejects_run_manifest_schema_failure(self) -> None:
        self._build()
        run = self._run_manifest()
        run["unsupported"] = True
        self._write_run_manifest(run)
        self._recreate_outer_manifest()

        with self.assertRaisesRegex(GovernedBundleError, "schema validation failed"):
            validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_rejects_missing_run_manifest_and_unclassified_payload(self) -> None:
        with self.subTest(case="missing-run-manifest"):
            self._build()
            (self.root / "run-manifest.json").unlink()
            self._recreate_outer_manifest()
            with self.assertRaisesRegex(GovernedBundleError, "missing required path"):
                validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

        self.tearDown()
        self.setUp()
        with self.subTest(case="unclassified-payload"):
            self._build()
            (self.root / "unclassified.txt").write_text("not declared", encoding="utf-8")
            self._recreate_outer_manifest()
            with self.assertRaisesRegex(GovernedBundleError, "classify every outer payload"):
                validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_rejects_declared_artifact_identity_or_duplicate_id(self) -> None:
        with self.subTest(case="identity"):
            self._build()
            run = self._run_manifest()
            run["artifacts"][0]["sha256"] = "0" * 64  # type: ignore[index]
            self._write_run_manifest(run)
            self._recreate_outer_manifest()
            with self.assertRaisesRegex(GovernedBundleError, "identity differs"):
                validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

        self.tearDown()
        self.setUp()
        with self.subTest(case="duplicate-id"):
            self._build()
            run = self._run_manifest()
            run["artifacts"][1]["artifact_id"] = run["artifacts"][0][  # type: ignore[index]
                "artifact_id"
            ]
            self._write_run_manifest(run)
            self._recreate_outer_manifest()
            with self.assertRaisesRegex(GovernedBundleError, "duplicate run artifact_id"):
                validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_rejects_environment_projection_mismatch(self) -> None:
        self._build()
        environment = json.loads((self.root / "environment.json").read_text(encoding="utf-8"))
        environment["hardware"]["summary"] = "different worker"
        _write_json(self.root / "environment.json", environment)
        self._update_run_artifact_identity("environment.json")
        self._recreate_outer_manifest()

        with self.assertRaisesRegex(GovernedBundleError, "provenance projection"):
            validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_rejects_resolved_configuration_not_matching_trainer_runtime(self) -> None:
        self._build()
        config = json.loads((self.root / "resolved-config.json").read_text(encoding="utf-8"))
        config["batch_size"] = 4
        _write_json(self.root / "resolved-config.json", config)
        config_sha256 = _sha256(self.root / "resolved-config.json")
        run = self._run_manifest()
        for field in (
            run["experiment"]["configuration"],  # type: ignore[index]
            run["data"]["preprocessing"],  # type: ignore[index]
        ):
            field["sha256"] = config_sha256
        artifact = next(
            item
            for item in run["artifacts"]
            if item["path"] == "resolved-config.json"  # type: ignore[index]
        )
        artifact["byte_size"] = (self.root / "resolved-config.json").stat().st_size
        artifact["sha256"] = config_sha256
        self._write_run_manifest(run)
        self._recreate_outer_manifest()

        with self.assertRaisesRegex(GovernedBundleError, "run-summary.runtime_config"):
            validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_binds_every_configuration_reference_to_outer_inventory(self) -> None:
        cases = (
            "experiment.configuration",
            "data.preprocessing",
            "data.datasets[0].acquisition_manifest",
            "data.datasets[0].splits[0]",
            "evaluation.configuration",
        )
        for index, case in enumerate(cases):
            if index:
                self.tearDown()
                self.setUp()
            with self.subTest(reference=case):
                self._build()
                run = self._run_manifest()
                if case == "experiment.configuration":
                    reference = run["experiment"]["configuration"]  # type: ignore[index]
                    reference["sha256"] = "0" * 64
                elif case == "data.preprocessing":
                    reference = run["data"]["preprocessing"]  # type: ignore[index]
                    reference["sha256"] = "0" * 64
                elif case == "data.datasets[0].acquisition_manifest":
                    reference = run["data"]["datasets"][0][  # type: ignore[index]
                        "acquisition_manifest"
                    ]
                    reference["sha256"] = "0" * 64
                elif case == "data.datasets[0].splits[0]":
                    split = run["data"]["datasets"][0]["splits"][0]  # type: ignore[index]
                    split["manifest_sha256"] = "0" * 64
                else:
                    reference = run["evaluation"]["configuration"]  # type: ignore[index]
                    reference["sha256"] = "0" * 64
                self._write_run_manifest(run)
                self._recreate_outer_manifest()

                with self.assertRaisesRegex(
                    GovernedBundleError,
                    re.escape(f"run {case} SHA-256 does not match the outer artifact identity"),
                ):
                    validate_governed_bundle(
                        self.root,
                        schema_directory=SCHEMA_DIRECTORY,
                    )

    def test_rejects_evaluation_configuration_bound_to_training_config(self) -> None:
        self._build()
        run = self._run_manifest()
        run["evaluation"]["configuration"] = dict(  # type: ignore[index]
            run["experiment"]["configuration"]  # type: ignore[index]
        )
        self._write_run_manifest(run)
        self._recreate_outer_manifest()

        with self.assertRaisesRegex(
            GovernedBundleError,
            "evaluation.configuration must bind the exact provenance/evaluation-config.json bytes",
        ):
            validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_rejects_configuration_reference_with_wrong_artifact_kind(self) -> None:
        self._build()
        run = self._run_manifest()
        evaluation_artifact = next(
            artifact
            for artifact in run["artifacts"]  # type: ignore[index]
            if artifact["path"] == EVALUATION_CONFIG_PATH
        )
        evaluation_artifact["kind"] = "report"
        self._write_run_manifest(run)
        self._recreate_outer_manifest()

        with self.assertRaisesRegex(
            GovernedBundleError,
            "evaluation.configuration must reference an artifact declared as kind configuration",
        ):
            validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_rejects_evaluation_config_semantics_differing_from_run_manifest(self) -> None:
        self._build()
        evaluation_path = self.root / EVALUATION_CONFIG_PATH
        evaluation_config = json.loads(evaluation_path.read_text(encoding="utf-8"))
        evaluation_config["causal"] = False
        _write_json(evaluation_path, evaluation_config)
        self._update_run_artifact_identity(EVALUATION_CONFIG_PATH)
        run = self._run_manifest()
        run["evaluation"]["configuration"]["sha256"] = _sha256(  # type: ignore[index]
            evaluation_path
        )
        self._write_run_manifest(run)
        self._recreate_outer_manifest()

        with self.assertRaisesRegex(GovernedBundleError, "causal differs"):
            validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_rejects_stale_nested_trainer_manifest_even_when_outer_is_fresh(self) -> None:
        self._build()
        checkpoint = self.root / "trainer-output/checkpoint.pt"
        checkpoint.write_bytes(b"changed but outer-inventoried bytes")
        self._update_run_artifact_identity("trainer-output/checkpoint.pt")
        self._recreate_outer_manifest()

        with self.assertRaisesRegex(GovernedBundleError, "nested trainer-output.*mismatch"):
            validate_governed_bundle(self.root, schema_directory=SCHEMA_DIRECTORY)

    def test_cli_failure_is_machine_readable(self) -> None:
        root = self._build()
        (root / "environment.json").write_bytes(b"tampered")
        stderr = io.StringIO()

        with redirect_stderr(stderr):
            exit_code = main([str(root), "--schema-dir", str(SCHEMA_DIRECTORY)])

        event = json.loads(stderr.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(event["event"], "governed_bundle_validation_failed")
        self.assertFalse(event["ok"])


if __name__ == "__main__":
    unittest.main()

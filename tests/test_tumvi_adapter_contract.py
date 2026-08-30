from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from unittest import mock

import compact_vio.data.tumvi_adapter_contract as contract_module
from compact_vio.data.tumvi_adapter_contract import (
    TumviAdapterContract,
    TumviAdapterContractError,
    load_tumvi_adapter_contract,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_RELATIVE = Path("configs/data/tumvi_room4_512_16_adapter_contract_v1.json")
CONTRACT_PATH = REPOSITORY_ROOT / CONTRACT_RELATIVE
CONTRACT_DOCUMENT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
EVIDENCE_PATHS = tuple(item["path"] for item in CONTRACT_DOCUMENT["source_evidence"].values())


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ("git", "-C", os.fspath(root), *arguments),
        check=True,
        capture_output=True,
    )


def _write_document(root: Path, document: object) -> None:
    path = root / CONTRACT_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


@contextmanager
def _committed_contract_repository():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for relative in EVIDENCE_PATHS:
            source = REPOSITORY_ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        _write_document(root, CONTRACT_DOCUMENT)
        _git(root, "init", "-q")
        _git(root, "add", ".")
        _git(
            root,
            "-c",
            "user.name=Contract Test",
            "-c",
            "user.email=contract-test@example.invalid",
            "commit",
            "-q",
            "-m",
            "contract fixture",
        )
        yield root


class TumviAdapterContractTests(unittest.TestCase):
    def _assert_document_error(
        self,
        mutate: object,
        pattern: str,
    ) -> None:
        with _committed_contract_repository() as root:
            document = copy.deepcopy(CONTRACT_DOCUMENT)
            mutate(document)  # type: ignore[operator]
            _write_document(root, document)
            with self.assertRaisesRegex(TumviAdapterContractError, pattern):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

    def test_loads_exact_tracked_contract_with_only_false_readiness(self) -> None:
        with _committed_contract_repository() as root:
            contract = load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        self.assertIs(type(contract), TumviAdapterContract)
        self.assertRegex(contract.sha256, r"^[0-9a-f]{64}$")
        self.assertRegex(contract.git_revision, r"^[0-9a-f]{40}$")
        self.assertEqual(contract.contract_id, "tumvi-room4-512-16-adapter-contract-v1")
        self.assertEqual(
            contract.source_evidence.format_inspection_report.sha256,
            "8048a399d611051e807c9824cdb141a5e6db1bcf77f9bd197483223fe887ef30",
        )
        readiness = contract.result_contract.readiness
        self.assertTrue(all(getattr(readiness, item.name) is False for item in fields(readiness)))
        self.assertFalse(hasattr(contract, "__dict__"))
        self.assertFalse(hasattr(readiness, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            contract.contract_id = "changed"  # type: ignore[misc]

    def test_public_export_surface_is_loader_only(self) -> None:
        self.assertEqual(
            contract_module.__all__,
            [
                "TumviAdapterContract",
                "TumviAdapterContractError",
                "load_tumvi_adapter_contract",
            ],
        )

    def test_contract_preserves_source_labels_and_blocks_semantic_projection(self) -> None:
        with _committed_contract_repository() as root:
            contract = load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        pose = contract.pose_reference_contract
        self.assertEqual(pose.record_name, "TumviSourceLabeledPoseRow")
        self.assertEqual(
            pose.fields,
            (
                "timestamp_source_label_ns",
                "p_rs_r_x_source_label_lexeme",
                "p_rs_r_y_source_label_lexeme",
                "p_rs_r_z_source_label_lexeme",
                "q_rs_w_source_label_lexeme",
                "q_rs_x_source_label_lexeme",
                "q_rs_y_source_label_lexeme",
                "q_rs_z_source_label_lexeme",
            ),
        )
        self.assertIsNone(pose.quaternion_norm_policy)
        self.assertIsNone(pose.normalization_policy)
        self.assertIsNone(pose.interpolation_policy)
        self.assertIsNone(pose.maximum_interpolation_bracket_ns)
        outputs = dict(contract.result_contract.record_outputs)
        self.assertNotIn("pose_observation", outputs)
        self.assertNotIn("structural_segment", outputs)
        self.assertNotIn("prospective_structural_segment", outputs)
        self.assertIn("source_labeled_pose_row", outputs)
        self.assertIn("stereo_index_row", outputs)

    def test_clock_gap_segment_and_preprocessing_choices_are_null_or_blocked(self) -> None:
        with _committed_contract_repository() as root:
            contract = load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        interval = contract.interval_policy
        self.assertIsNone(interval.clock_offset_ns)
        self.assertIsNone(interval.maximum_camera_gap_ns)
        self.assertIsNone(interval.maximum_imu_gap_ns)
        self.assertIsNone(interval.maximum_pose_gap_ns)
        self.assertIn("no-clock-equivalence-claim", interval.coverage_interval)
        self.assertIn("integer-token-order-only", interval.comparison_semantics)
        self.assertIn("blocked", interval.operational_eligibility)
        self.assertFalse(interval.segment_construction_ready)
        self.assertIsNone(interval.segment_rule)
        self.assertIsNone(interval.minimum_frames_per_structural_segment)
        image = contract.image_preprocessing_boundary
        self.assertFalse(image.full_indexed_image_existence_verified)
        self.assertFalse(image.whole_file_png_validity_verified)
        self.assertFalse(image.decodability_verified)
        for field in (
            "decoder",
            "decoded_dtype",
            "sample_range_mapping",
            "channel_policy",
            "normalization",
        ):
            self.assertIsNone(getattr(image, field))
        self.assertEqual(image.image_bytes_authorized, 0)

    def test_csv_lexical_contract_is_mechanical_and_preserves_numeric_lexemes(self) -> None:
        with _committed_contract_repository() as root:
            contract = load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        csv = contract.csv_grammars
        self.assertEqual(csv.common.delimiter, ",")
        self.assertEqual(csv.common.line_ending, "lf-only")
        self.assertEqual(csv.common.final_line_ending, "required")
        self.assertEqual(csv.common.quoting, "forbidden")
        self.assertIsNone(csv.common.quote_character)
        self.assertIsNone(csv.common.escape_character)
        self.assertEqual(csv.common.field_whitespace_normalization, "forbidden")
        self.assertEqual(
            csv.common.header_comparison,
            "exact-raw-cell-no-whitespace-normalization/v1",
        )
        self.assertEqual(csv.timestamp_lexeme.fullmatch_regex, r"(?:0|[1-9][0-9]*)")
        self.assertEqual(csv.timestamp_lexeme.minimum_value, 0)
        self.assertEqual(csv.timestamp_lexeme.maximum_value, 2**63 - 1)
        self.assertEqual(csv.timestamp_lexeme.maximum_token_bytes, 19)
        self.assertEqual(
            csv.numeric_lexeme.fullmatch_regex,
            r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?",
        )
        self.assertEqual(csv.numeric_lexeme.maximum_token_bytes, 128)
        self.assertEqual(csv.numeric_lexeme.output_representation, "original-ascii-lexeme")
        self.assertIsNone(csv.numeric_lexeme.numeric_conversion)
        filename = csv.camera_index.filename_grammar
        self.assertEqual(filename.fullmatch_regex, r"(?:0|[1-9][0-9]*)\.png")
        self.assertEqual(filename.stem_maximum_value, 2**63 - 1)
        self.assertEqual(filename.maximum_token_bytes, 23)

    def test_each_csv_column_has_one_exact_source_lexeme_output_mapping(self) -> None:
        with _committed_contract_repository() as root:
            contract = load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        csv = contract.csv_grammars
        camera = csv.camera_index
        self.assertEqual(camera.minimum_data_rows, 1)
        self.assertEqual(camera.stream_role_output_field, "stream_role")
        self.assertEqual(
            camera.output_fields,
            ("stream_role", "timestamp_source_label_ns", "filename_source_lexeme"),
        )
        self.assertEqual(
            tuple(item.source_header for item in camera.column_grammars),
            camera.header,
        )
        self.assertEqual(
            tuple(item.output_field for item in camera.column_grammars),
            camera.output_fields[1:],
        )
        for stream in (csv.imu_stream, csv.pose_reference_stream):
            self.assertEqual(stream.minimum_data_rows, 1)
            self.assertEqual(len(stream.column_grammars), stream.row_arity)
            self.assertEqual(
                tuple(item.source_header for item in stream.column_grammars),
                stream.header,
            )
            self.assertEqual(
                tuple(item.output_field for item in stream.column_grammars),
                stream.output_fields,
            )
            self.assertEqual(stream.column_grammars[0].lexeme_grammar, "timestamp_lexeme")
            self.assertTrue(
                all(item.lexeme_grammar == "numeric_lexeme" for item in stream.column_grammars[1:])
            )
        outputs = dict(contract.result_contract.record_outputs)
        self.assertEqual(outputs["camera_index_row"], camera.output_fields)
        self.assertEqual(outputs["imu_row"], csv.imu_stream.output_fields)
        self.assertEqual(
            outputs["source_labeled_pose_row"],
            csv.pose_reference_stream.output_fields,
        )

    def test_rejects_column_reordering_regrouping_empty_streams_or_missing_role(self) -> None:
        def reorder(document: dict[str, object]) -> None:
            columns = document["csv_grammars"]["imu_stream"]["column_grammars"]
            columns[1], columns[2] = columns[2], columns[1]

        def regroup(document: dict[str, object]) -> None:
            document["csv_grammars"]["pose_reference_stream"]["output_fields"][1] = (
                "p_rs_r_source_label_values"
            )

        def empty_allowed(document: dict[str, object]) -> None:
            document["csv_grammars"]["imu_stream"]["minimum_data_rows"] = 0

        def missing_role(document: dict[str, object]) -> None:
            document["csv_grammars"]["camera_index"]["stream_role_output_field"] = None

        for label, mutate, pattern in (
            ("reorder", reorder, "column_grammars"),
            ("regroup", regroup, "output_fields"),
            ("empty", empty_allowed, "minimum_data_rows"),
            ("role", missing_role, "stream_role_output_field"),
        ):
            with self.subTest(case=label):
                self._assert_document_error(mutate, pattern)

    def test_rejects_lexical_grammar_relaxations_and_numeric_conversion(self) -> None:
        def crlf(document: dict[str, object]) -> None:
            document["csv_grammars"]["common"]["line_ending"] = "lf-or-crlf"

        def quotes(document: dict[str, object]) -> None:
            document["csv_grammars"]["common"]["quoting"] = "minimal"

        def timestamp(document: dict[str, object]) -> None:
            document["csv_grammars"]["timestamp_lexeme"]["fullmatch_regex"] = "[0-9]+"

        def numeric(document: dict[str, object]) -> None:
            document["csv_grammars"]["numeric_lexeme"]["numeric_conversion"] = "float64"

        def filename(document: dict[str, object]) -> None:
            document["csv_grammars"]["camera_index"]["filename_grammar"]["maximum_token_bytes"] = 24

        for label, mutate, pattern in (
            ("crlf", crlf, "line_ending"),
            ("quotes", quotes, "quoting"),
            ("timestamp", timestamp, "fullmatch_regex"),
            ("numeric", numeric, "numeric_conversion"),
            ("filename", filename, "maximum_token_bytes"),
        ):
            with self.subTest(case=label):
                self._assert_document_error(mutate, pattern)

    def test_loader_reads_only_contract_and_six_exact_tracked_evidence_files(self) -> None:
        with _committed_contract_repository() as root:
            opened: list[str] = []
            original = contract_module._read_regular_no_symlinks

            def recording_read(
                repo_root: Path,
                relative: str,
                *,
                field: str,
            ) -> bytes:
                opened.append(relative)
                return original(repo_root, relative, field=field)

            with mock.patch.object(
                contract_module,
                "_read_regular_no_symlinks",
                side_effect=recording_read,
            ):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        expected_once = [CONTRACT_RELATIVE.as_posix(), *EVIDENCE_PATHS]
        self.assertEqual(opened, [*expected_once, *expected_once])
        for relative in opened:
            self.assertFalse(relative.startswith("data/"))
            self.assertNotIn("/sensor.yaml", relative)
            self.assertFalse(relative.endswith(".png"))
            self.assertNotIn("src/compact_vio/learning/", relative)
            self.assertNotIn("model", relative.lower())

    def test_rejects_duplicate_root_and_nested_json_keys(self) -> None:
        with _committed_contract_repository() as root:
            path = root / CONTRACT_RELATIVE
            raw = path.read_text(encoding="utf-8")
            path.write_text(
                raw.replace(
                    '  "schema_version": "1.0.0",',
                    '  "schema_version": "1.0.0",\n  "schema_version": "1.0.0",',
                    1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TumviAdapterContractError, "duplicate JSON key"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

            path.write_text(
                raw.replace(
                    '    "decoder": null,',
                    '    "decoder": null,\n    "decoder": null,',
                    1,
                ),
                encoding="utf-8",
            )
            self.assertNotEqual(path.read_text(encoding="utf-8"), raw)
            with self.assertRaisesRegex(TumviAdapterContractError, "duplicate JSON key"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

    def test_rejects_missing_extra_wrong_order_and_bool_as_int(self) -> None:
        def missing(document: dict[str, object]) -> None:
            del document["scope"]

        def extra(document: dict[str, object]) -> None:
            document["unexpected"] = False

        def order(document: dict[str, object]) -> None:
            result = document["result_contract"]  # type: ignore[assignment]
            result["limitations"] = list(reversed(result["limitations"]))

        def bool_as_int(document: dict[str, object]) -> None:
            result = document["result_contract"]  # type: ignore[assignment]
            result["readiness"]["adapter_ready"] = 0

        for label, mutate, pattern in (
            ("missing", missing, "non-exact keys"),
            ("extra", extra, "non-exact keys"),
            ("order", order, "limitations"),
            ("bool", bool_as_int, "exact JSON type bool"),
        ):
            with self.subTest(case=label):
                self._assert_document_error(mutate, pattern)

    def test_rejects_non_null_thresholds_or_true_readiness(self) -> None:
        def clock_threshold(document: dict[str, object]) -> None:
            interval = document["interval_policy"]  # type: ignore[assignment]
            interval["clock_offset_ns"] = 0

        def pose_threshold(document: dict[str, object]) -> None:
            pose = document["pose_reference_contract"]  # type: ignore[assignment]
            pose["maximum_interpolation_bracket_ns"] = 1

        def decoder(document: dict[str, object]) -> None:
            image = document["image_preprocessing_boundary"]  # type: ignore[assignment]
            image["decoder"] = "pillow"

        def readiness(document: dict[str, object]) -> None:
            result = document["result_contract"]  # type: ignore[assignment]
            result["readiness"]["segment_construction_ready"] = True

        for label, mutate, pattern in (
            ("clock", clock_threshold, "clock_offset_ns"),
            ("pose", pose_threshold, "maximum_interpolation_bracket_ns"),
            ("decoder", decoder, "decoder"),
            ("readiness", readiness, "segment_construction_ready"),
        ):
            with self.subTest(case=label):
                self._assert_document_error(mutate, pattern)

    def test_rejects_euroc_full_state_or_semantic_output_mutations(self) -> None:
        def full_state(document: dict[str, object]) -> None:
            grammar = document["csv_grammars"]  # type: ignore[assignment]
            grammar["pose_reference_stream"]["header"].extend(
                [
                    "v_RS_R_x [m s^-1]",
                    "v_RS_R_y [m s^-1]",
                    "v_RS_R_z [m s^-1]",
                ]
            )

        def semantic_type(document: dict[str, object]) -> None:
            pose = document["pose_reference_contract"]  # type: ignore[assignment]
            pose["record_name"] = "GroundTruthState"

        for label, mutate in (("full-state", full_state), ("semantic", semantic_type)):
            with self.subTest(case=label):
                self._assert_document_error(mutate, "must")

    def test_rejects_noncanonical_or_forbidden_evidence_before_opening_it(self) -> None:
        with _committed_contract_repository() as root:
            document = copy.deepcopy(CONTRACT_DOCUMENT)
            document["source_evidence"]["candidate"]["path"] = "data/secret.json"
            _write_document(root, document)
            opened: list[str] = []
            original = contract_module._read_regular_no_symlinks

            def recording_read(
                repo_root: Path,
                relative: str,
                *,
                field: str,
            ) -> bytes:
                opened.append(relative)
                return original(repo_root, relative, field=field)

            with (
                mock.patch.object(
                    contract_module,
                    "_read_regular_no_symlinks",
                    side_effect=recording_read,
                ),
                self.assertRaisesRegex(TumviAdapterContractError, "source_evidence.candidate.path"),
            ):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)
            self.assertEqual(opened, [CONTRACT_RELATIVE.as_posix()])

        self._assert_document_error(
            lambda document: document["source_evidence"]["candidate"].__setitem__(
                "path", "../candidate.json"
            ),
            "source_evidence.candidate.path",
        )

    def test_rejects_untracked_or_worktree_changed_contract(self) -> None:
        with _committed_contract_repository() as root:
            path = root / CONTRACT_RELATIVE
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(TumviAdapterContractError, "contract worktree bytes"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        with _committed_contract_repository() as root:
            _git(root, "rm", "--cached", "-q", "--", CONTRACT_RELATIVE.as_posix())
            _git(
                root,
                "-c",
                "user.name=Contract Test",
                "-c",
                "user.email=contract-test@example.invalid",
                "commit",
                "-q",
                "-m",
                "untrack contract",
            )
            with self.assertRaisesRegex(TumviAdapterContractError, "Git evidence check failed"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

    def test_rejects_changed_untracked_wrong_hash_or_symlink_evidence(self) -> None:
        candidate = CONTRACT_DOCUMENT["source_evidence"]["candidate"]["path"]
        with _committed_contract_repository() as root:
            path = root / candidate
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(TumviAdapterContractError, "worktree bytes"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        with _committed_contract_repository() as root:
            path = root / candidate
            path.write_bytes(path.read_bytes() + b"\n")
            _git(root, "add", "--", candidate)
            _git(
                root,
                "-c",
                "user.name=Contract Test",
                "-c",
                "user.email=contract-test@example.invalid",
                "commit",
                "-q",
                "-m",
                "change evidence",
            )
            with self.assertRaisesRegex(TumviAdapterContractError, "SHA-256 mismatch"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        with _committed_contract_repository() as root:
            _git(root, "rm", "--cached", "-q", "--", candidate)
            _git(
                root,
                "-c",
                "user.name=Contract Test",
                "-c",
                "user.email=contract-test@example.invalid",
                "commit",
                "-q",
                "-m",
                "untrack evidence",
            )
            with self.assertRaisesRegex(TumviAdapterContractError, "Git evidence check failed"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        with _committed_contract_repository() as root:
            path = root / candidate
            path.unlink()
            path.symlink_to(root / EVIDENCE_PATHS[1])
            with self.assertRaisesRegex(TumviAdapterContractError, "symlink"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

    def test_descriptor_bound_reader_rejects_hardlinks_and_ancestor_swap(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            external_root = Path(outside)
            (root / "evidence").mkdir()
            external_item = external_root / "item"
            external_item.write_bytes(b"external")
            os.link(external_item, root / "evidence/item")
            with self.assertRaisesRegex(TumviAdapterContractError, "exactly one hard link"):
                contract_module._read_regular_no_symlinks(
                    root,
                    "evidence/item",
                    field="hardlink evidence",
                )

        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            external_root = Path(outside)
            (root / "evidence").mkdir()
            (root / "evidence/item").write_bytes(b"inside")
            (external_root / "item").write_bytes(b"outside")
            original_open = os.open
            swapped = False

            def swapping_open(
                path: os.PathLike[str] | str,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if path == "item" and dir_fd is not None and not swapped:
                    swapped = True
                    (root / "evidence").rename(root / "evidence-bound")
                    (root / "evidence").symlink_to(external_root, target_is_directory=True)
                if dir_fd is None:
                    return original_open(path, flags, mode)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            with (
                mock.patch.object(contract_module.os, "open", side_effect=swapping_open),
                self.assertRaisesRegex(TumviAdapterContractError, "without following symlinks"),
            ):
                contract_module._read_regular_no_symlinks(
                    root,
                    "evidence/item",
                    field="raced evidence",
                )
            self.assertTrue(swapped)

    def test_rejects_head_movement_and_binds_blobs_to_captured_revision(self) -> None:
        with _committed_contract_repository() as root:
            original = contract_module._read_regular_no_symlinks
            moved = False

            def moving_read(repo_root: Path, relative: str, *, field: str) -> bytes:
                nonlocal moved
                raw = original(repo_root, relative, field=field)
                if not moved:
                    moved = True
                    _git(
                        root,
                        "-c",
                        "user.name=Contract Test",
                        "-c",
                        "user.email=contract-test@example.invalid",
                        "commit",
                        "--allow-empty",
                        "-q",
                        "-m",
                        "move HEAD",
                    )
                return raw

            with (
                mock.patch.object(
                    contract_module,
                    "_read_regular_no_symlinks",
                    side_effect=moving_read,
                ),
                self.assertRaisesRegex(TumviAdapterContractError, "HEAD changed"),
            ):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)
            self.assertTrue(moved)

    def test_mapping_member_order_does_not_change_returned_tuple_order(self) -> None:
        with _committed_contract_repository() as root:
            document = copy.deepcopy(CONTRACT_DOCUMENT)
            limits = document["resource_limits"]["maximum_csv_bytes_by_role"]
            document["resource_limits"]["maximum_csv_bytes_by_role"] = dict(
                reversed(tuple(limits.items()))
            )
            outputs = document["result_contract"]["record_outputs"]
            document["result_contract"]["record_outputs"] = dict(reversed(tuple(outputs.items())))
            _write_document(root, document)
            _git(root, "add", "--", CONTRACT_RELATIVE.as_posix())
            _git(
                root,
                "-c",
                "user.name=Contract Test",
                "-c",
                "user.email=contract-test@example.invalid",
                "commit",
                "-q",
                "-m",
                "reorder object members",
            )
            contract = load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        self.assertEqual(
            tuple(name for name, _ in contract.resource_limits.maximum_csv_bytes_by_role),
            ("cam0", "cam1", "imu", "pose"),
        )
        self.assertEqual(
            tuple(name for name, _ in contract.result_contract.record_outputs),
            ("camera_index_row", "stereo_index_row", "imu_row", "source_labeled_pose_row"),
        )

    def test_public_records_reject_forged_authority_and_readiness(self) -> None:
        with _committed_contract_repository() as root:
            contract = load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root)

        with self.assertRaisesRegex(TumviAdapterContractError, "adapter_ready"):
            replace(contract.result_contract.readiness, adapter_ready=True)
        with self.assertRaisesRegex(TumviAdapterContractError, "scientific_authority"):
            replace(contract.result_contract, scientific_authority="full")
        with self.assertRaisesRegex(TumviAdapterContractError, "clock_offset_ns"):
            replace(contract.interval_policy, clock_offset_ns=0)
        with self.assertRaisesRegex(TumviAdapterContractError, "decoder"):
            replace(contract.image_preprocessing_boundary, decoder="pillow")
        with self.assertRaisesRegex((TypeError, ValueError), "InitVar '_seal'"):
            replace(contract, path="configs/data/copied-contract.json")
        with self.assertRaisesRegex((TypeError, ValueError), "InitVar '_seal'"):
            replace(contract, sha256="0" * 64)
        with self.assertRaisesRegex((TypeError, ValueError), "InitVar '_seal'"):
            replace(contract, git_revision="1" * 40)
        direct_arguments = {item.name: getattr(contract, item.name) for item in fields(contract)}
        with self.assertRaisesRegex(TumviAdapterContractError, "strict loader"):
            TumviAdapterContract(_seal=object(), **direct_arguments)

    def test_rejects_contract_outside_repo_or_nested_repo_root(self) -> None:
        with _committed_contract_repository() as root, tempfile.TemporaryDirectory() as outside:
            outside_path = Path(outside) / "contract.json"
            outside_path.write_text(json.dumps(CONTRACT_DOCUMENT), encoding="utf-8")
            with self.assertRaisesRegex(TumviAdapterContractError, "inside the repository"):
                load_tumvi_adapter_contract(outside_path, repo_root=root)
            with self.assertRaisesRegex(TumviAdapterContractError, "Git worktree root"):
                load_tumvi_adapter_contract(CONTRACT_RELATIVE, repo_root=root / "configs")

    def test_rejects_identical_contract_at_an_alternate_tracked_path(self) -> None:
        with _committed_contract_repository() as root:
            alternate = Path("configs/data/copied-adapter-contract.json")
            (root / alternate).write_bytes((root / CONTRACT_RELATIVE).read_bytes())
            _git(root, "add", "--", alternate.as_posix())
            _git(
                root,
                "-c",
                "user.name=Contract Test",
                "-c",
                "user.email=contract-test@example.invalid",
                "commit",
                "-q",
                "-m",
                "add alternate contract path",
            )
            with self.assertRaisesRegex(TumviAdapterContractError, "canonical path"):
                load_tumvi_adapter_contract(alternate, repo_root=root)


if __name__ == "__main__":
    unittest.main()

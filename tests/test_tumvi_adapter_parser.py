from __future__ import annotations

import ast
import copy
import hashlib
import io
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest import mock

import compact_vio.data.tumvi_adapter_parser as parser_module
from compact_vio.data.tumvi_adapter_contract import load_tumvi_adapter_contract
from compact_vio.data.tumvi_adapter_parser import (
    PARSER_ACCOUNTING_POLICY_ID,
    TumviAdapterParserError,
    TumviCameraIndexBatch,
    TumviCameraIndexRow,
    TumviImuBatch,
    TumviSourceLabeledPoseBatch,
    TumviStereoIndexBatch,
    TumviSyntheticSourceIdentity,
    parse_tumvi_camera_index,
    parse_tumvi_imu_stream,
    parse_tumvi_pose_reference_stream,
    parse_tumvi_stereo_indexes,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = Path("configs/data/tumvi_room4_512_16_adapter_contract_v1.json")
CONTRACT_SHA256 = "4368580eb601958f1c402ee6f85d3207d9bb41282c51f4dee505482c1a6542d5"
CAMERA_HEADER = "#timestamp [ns],filename"
IMU_HEADER = (
    "#timestamp [ns],w_RS_S_x [rad s^-1],w_RS_S_y [rad s^-1],"
    "w_RS_S_z [rad s^-1],a_RS_S_x [m s^-2],a_RS_S_y [m s^-2],"
    "a_RS_S_z [m s^-2]"
)
POSE_HEADER = (
    "#timestamp [ns],p_RS_R_x [m],p_RS_R_y [m],p_RS_R_z [m],q_RS_w [],q_RS_x [],q_RS_y [],q_RS_z []"
)
KNOWN_REAL_SHA256 = (
    "feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67",
    "4249d4036b3c03c55b709f6f634d975d024999fb017ab3539cfa71580793a3be",
    "073a3e957efa8ff638ea41402cac9654b40897631d566a3ffee090208597db2a",
)


def _raw(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("ascii")


def _identity(raw: bytes) -> tuple[int, str]:
    return len(raw), hashlib.sha256(raw).hexdigest()


class _BytesIOSubclass(io.BytesIO):
    pass


class TumviAdapterParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_tumvi_adapter_contract(CONTRACT_PATH, repo_root=REPOSITORY_ROOT)

    def _camera(
        self,
        raw: bytes,
        *,
        role: str = "cam0",
        source: object | None = None,
        path: object | None = None,
        size: object | None = None,
        sha256: object | None = None,
    ) -> TumviCameraIndexBatch:
        exact_size, exact_sha256 = _identity(raw)
        selected_source = io.BytesIO(raw) if source is None else source
        selected_path = f"mav0/{role}/data.csv" if path is None else path
        return parse_tumvi_camera_index(
            selected_source,
            contract=self.contract,
            stream_role=role,
            source_path=selected_path,  # type: ignore[arg-type]
            expected_source_size_bytes=exact_size if size is None else size,  # type: ignore[arg-type]
            expected_source_sha256=exact_sha256 if sha256 is None else sha256,  # type: ignore[arg-type]
        )

    def test_public_surface_and_accounting_policy_are_exact(self) -> None:
        self.assertEqual(
            parser_module.__all__,
            [
                "PARSER_ACCOUNTING_POLICY_ID",
                "TumviAdapterParserError",
                "TumviCameraIndexBatch",
                "TumviCameraIndexRow",
                "TumviImuBatch",
                "TumviImuRow",
                "TumviSourceLabeledPoseBatch",
                "TumviSourceLabeledPoseRow",
                "TumviStereoIndexBatch",
                "TumviStereoIndexRow",
                "TumviSyntheticSourceIdentity",
                "parse_tumvi_camera_index",
                "parse_tumvi_imu_stream",
                "parse_tumvi_pose_reference_stream",
                "parse_tumvi_stereo_indexes",
            ],
        )
        self.assertEqual(
            PARSER_ACCOUNTING_POLICY_ID,
            "tumvi-synthetic-csv-accounting-total-and-line-bytes-include-lf-"
            "data-rows-exclude-header-exact-bytesio-position-zero-open-at-eof/v1",
        )

    def test_parses_camera_rows_with_exact_contract_and_source_provenance(self) -> None:
        raw = _raw(CAMERA_HEADER, "10,10.png", "12,12.png")
        source = io.BytesIO(raw)
        batch = self._camera(raw, source=source)

        self.assertIs(type(batch), TumviCameraIndexBatch)
        self.assertEqual(batch.contract_id, "tumvi-room4-512-16-adapter-contract-v1")
        self.assertEqual(batch.contract_sha256, CONTRACT_SHA256)
        self.assertEqual(batch.parser_accounting_policy_id, PARSER_ACCOUNTING_POLICY_ID)
        self.assertEqual(
            batch.source.parser_accounting_policy_id,
            PARSER_ACCOUNTING_POLICY_ID,
        )
        self.assertEqual(batch.source_scope, "synthetic-fixture-only-origin-not-authenticated/v1")
        self.assertEqual(batch.scientific_authority, "none")
        self.assertEqual(batch.source.stream_role, "cam0")
        self.assertEqual(batch.source.source_path, "mav0/cam0/data.csv")
        self.assertEqual(batch.source.source_size_bytes, len(raw))
        self.assertEqual(batch.source.source_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            batch.rows,
            (
                batch.rows[0],
                batch.rows[1],
            ),
        )
        self.assertEqual(batch.rows[0].timestamp_source_label_ns, 10)
        self.assertEqual(batch.rows[0].filename_source_lexeme, "10.png")
        self.assertEqual(batch.rows[1].stream_role, "cam0")
        self.assertFalse(source.closed)
        self.assertEqual(source.tell(), len(raw))
        self.assertEqual(source.read(1), b"")

    def test_parses_imu_and_preserves_original_numeric_lexemes_without_float_values(self) -> None:
        raw = _raw(
            IMU_HEADER,
            "20,+0,.5,1.,-2E-3,0004,5e+2",
            "21,-0,0.50,1.0,+2e3,4.,.25",
        )
        source = io.BytesIO(raw)
        size, sha256 = _identity(raw)
        batch = parse_tumvi_imu_stream(
            source,
            contract=self.contract,
            source_path="mav0/imu0/data.csv",
            expected_source_size_bytes=size,
            expected_source_sha256=sha256,
        )

        self.assertIs(type(batch), TumviImuBatch)
        self.assertEqual(batch.source.stream_role, "imu")
        self.assertEqual(batch.source.source_path, "mav0/imu0/data.csv")
        self.assertEqual(batch.rows[0].w_rs_s_x_source_label_lexeme, "+0")
        self.assertEqual(batch.rows[0].w_rs_s_y_source_label_lexeme, ".5")
        self.assertEqual(batch.rows[0].w_rs_s_z_source_label_lexeme, "1.")
        self.assertEqual(batch.rows[0].a_rs_s_x_source_label_lexeme, "-2E-3")
        self.assertEqual(batch.rows[0].a_rs_s_y_source_label_lexeme, "0004")
        self.assertTrue(
            all(
                type(getattr(row, field)) is str
                for row in batch.rows
                for field in (
                    "w_rs_s_x_source_label_lexeme",
                    "w_rs_s_y_source_label_lexeme",
                    "w_rs_s_z_source_label_lexeme",
                    "a_rs_s_x_source_label_lexeme",
                    "a_rs_s_y_source_label_lexeme",
                    "a_rs_s_z_source_label_lexeme",
                )
            )
        )
        self.assertFalse(source.closed)
        self.assertEqual(source.tell(), len(raw))

    def test_parses_source_labeled_pose_without_semantic_projection(self) -> None:
        raw = _raw(
            POSE_HEADER,
            "30,1.000,-2,+3e-2,1.,-0,.000,0E0",
            "31,1.100,-2,+3e-2,1.,-0,.000,0E0",
        )
        source = io.BytesIO(raw)
        size, sha256 = _identity(raw)
        batch = parse_tumvi_pose_reference_stream(
            source,
            contract=self.contract,
            source_path="mav0/mocap0/data.csv",
            expected_source_size_bytes=size,
            expected_source_sha256=sha256,
        )

        self.assertIs(type(batch), TumviSourceLabeledPoseBatch)
        self.assertEqual(batch.source.stream_role, "pose")
        self.assertEqual(batch.source.source_path, "mav0/mocap0/data.csv")
        self.assertEqual(batch.scientific_authority, "none")
        self.assertEqual(batch.rows[0].p_rs_r_x_source_label_lexeme, "1.000")
        self.assertEqual(batch.rows[0].q_rs_w_source_label_lexeme, "1.")
        for forbidden in ("velocity", "bias", "ground_truth", "quaternion_norm"):
            self.assertFalse(hasattr(batch.rows[0], forbidden))
        self.assertFalse(source.closed)
        self.assertEqual(source.tell(), len(raw))

    def test_parses_stereo_only_when_every_raw_byte_and_eof_match(self) -> None:
        raw = _raw(CAMERA_HEADER, "40,40.png", "50,50.png")
        cam0 = io.BytesIO(raw)
        cam1 = io.BytesIO(raw)
        size, sha256 = _identity(raw)
        batch = parse_tumvi_stereo_indexes(
            cam0,
            cam1,
            contract=self.contract,
            cam0_source_path="mav0/cam0/data.csv",
            cam1_source_path="mav0/cam1/data.csv",
            cam0_expected_source_size_bytes=size,
            cam0_expected_source_sha256=sha256,
            cam1_expected_source_size_bytes=size,
            cam1_expected_source_sha256=sha256,
        )

        self.assertIs(type(batch), TumviStereoIndexBatch)
        self.assertEqual(batch.cam0_source.source_sha256, batch.cam1_source.source_sha256)
        self.assertEqual(batch.cam0_source.source_size_bytes, batch.cam1_source.source_size_bytes)
        self.assertEqual(batch.cam0_source.source_path, "mav0/cam0/data.csv")
        self.assertEqual(batch.cam1_source.source_path, "mav0/cam1/data.csv")
        self.assertEqual(batch.rows[0].cam0_filename_source_lexeme, "40.png")
        self.assertEqual(batch.rows[0].cam1_filename_source_lexeme, "40.png")
        self.assertFalse(cam0.closed)
        self.assertFalse(cam1.closed)
        self.assertEqual((cam0.tell(), cam1.tell()), (len(raw), len(raw)))

    def test_stereo_rejects_raw_line_mismatch_unequal_eof_and_claimed_identity(self) -> None:
        canonical = _raw(CAMERA_HEADER, "1,1.png")
        mismatch = _raw(CAMERA_HEADER, "2,2.png")
        longer = _raw(CAMERA_HEADER, "1,1.png", "2,2.png")

        def call(left: bytes, right: bytes, *, claimed_same: bool = True) -> None:
            left_size, left_sha = _identity(left)
            right_size, right_sha = _identity(right)
            if claimed_same:
                right_size, right_sha = left_size, left_sha
            parse_tumvi_stereo_indexes(
                io.BytesIO(left),
                io.BytesIO(right),
                contract=self.contract,
                cam0_source_path="mav0/cam0/data.csv",
                cam1_source_path="mav0/cam1/data.csv",
                cam0_expected_source_size_bytes=left_size,
                cam0_expected_source_sha256=left_sha,
                cam1_expected_source_size_bytes=right_size,
                cam1_expected_source_sha256=right_sha,
            )

        with self.assertRaisesRegex(TumviAdapterParserError, "not byte-identical"):
            call(canonical, mismatch)
        with self.assertRaisesRegex(
            TumviAdapterParserError, "EOF at different bytes|exceeds expected"
        ):
            call(canonical, longer)
        with self.assertRaisesRegex(TumviAdapterParserError, "expected source identities"):
            call(canonical, mismatch, claimed_same=False)

        class EqualityCallback:
            def __ne__(self, other: object) -> bool:
                raise AssertionError(f"untrusted stereo equality executed for {other!r}")

        size, sha256 = _identity(canonical)
        with self.assertRaisesRegex(TumviAdapterParserError, "exact int/string types"):
            parse_tumvi_stereo_indexes(
                io.BytesIO(canonical),
                io.BytesIO(canonical),
                contract=self.contract,
                cam0_source_path="mav0/cam0/data.csv",
                cam1_source_path="mav0/cam1/data.csv",
                cam0_expected_source_size_bytes=EqualityCallback(),  # type: ignore[arg-type]
                cam0_expected_source_sha256=sha256,
                cam1_expected_source_size_bytes=size,
                cam1_expected_source_sha256=sha256,
            )

    def test_stereo_rejects_the_same_bytesio_object_even_with_duplicated_lines(self) -> None:
        duplicated = _raw(CAMERA_HEADER, CAMERA_HEADER, "1,1.png", "1,1.png")
        source = io.BytesIO(duplicated)
        size, sha256 = _identity(_raw(CAMERA_HEADER, "1,1.png"))
        with self.assertRaisesRegex(TumviAdapterParserError, "distinct"):
            parse_tumvi_stereo_indexes(
                source,
                source,
                contract=self.contract,
                cam0_source_path="mav0/cam0/data.csv",
                cam1_source_path="mav0/cam1/data.csv",
                cam0_expected_source_size_bytes=size,
                cam0_expected_source_sha256=sha256,
                cam1_expected_source_size_bytes=size,
                cam1_expected_source_sha256=sha256,
            )
        self.assertFalse(source.closed)

    def test_requires_exact_open_bytesio_at_position_zero(self) -> None:
        raw = _raw(CAMERA_HEADER, "1,1.png")
        invalid_sources: tuple[tuple[str, object, str], ...] = (
            ("raw bytes", raw, "exact io.BytesIO"),
            ("text stream", io.StringIO(raw.decode("ascii")), "exact io.BytesIO"),
            ("subclass", _BytesIOSubclass(raw), "exact io.BytesIO"),
        )
        for label, source, pattern in invalid_sources:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    pattern,
                ),
            ):
                self._camera(raw, source=source)

        nonzero = io.BytesIO(raw)
        nonzero.read(1)
        with self.assertRaisesRegex(TumviAdapterParserError, "byte zero"):
            self._camera(raw, source=nonzero)

        closed = io.BytesIO(raw)
        closed.close()
        with self.assertRaisesRegex(TumviAdapterParserError, "open"):
            self._camera(raw, source=closed)

    def test_failure_leaves_source_open_without_promising_position(self) -> None:
        raw = (CAMERA_HEADER + "\n1,1.png").encode("ascii")
        source = io.BytesIO(raw)
        with self.assertRaisesRegex(TumviAdapterParserError, "end with LF"):
            self._camera(raw, source=source)
        self.assertFalse(source.closed)

    def test_requires_exact_role_derived_path_and_fixed_contract_bytes(self) -> None:
        raw = _raw(CAMERA_HEADER, "1,1.png")
        for role, path, pattern in (
            ("cam2", "mav0/cam2/data.csv", "cam0 or cam1"),
            ("cam0", "mav0/cam1/data.csv", "contract-derived cam0 path"),
            ("cam0", Path("mav0/cam0/data.csv"), "exact text"),
        ):
            with (
                self.subTest(role=role, path=path),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    pattern,
                ),
            ):
                self._camera(raw, role=role, path=path)

        with self.assertRaisesRegex(TumviAdapterParserError, "exact loader-sealed"):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=object(),  # type: ignore[arg-type]
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

        uninitialized_contract = object.__new__(type(self.contract))
        with self.assertRaisesRegex(TumviAdapterParserError, "missing a required sealed field"):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=uninitialized_contract,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

        forged = copy.deepcopy(self.contract)
        object.__setattr__(forged, "sha256", "0" * 64)
        with self.assertRaisesRegex(TumviAdapterParserError, "exact frozen Gate 1 contract bytes"):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=forged,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

        for nested, field, value in (
            ("layout", "imu_stream_path", "mav0/other/data.csv"),
            ("csv_grammars", "numeric_lexeme", object()),
            ("resource_limits", "maximum_csv_rows_per_file", 1),
            ("result_contract", "scientific_authority", "full"),
        ):
            forged = copy.deepcopy(self.contract)
            object.__setattr__(getattr(forged, nested), field, value)
            with (
                self.subTest(nested=nested, field=field),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    "nested invariant validation failed|foreign nested value type",
                ),
            ):
                parse_tumvi_camera_index(
                    io.BytesIO(raw),
                    contract=forged,
                    stream_role="cam0",
                    source_path="mav0/cam0/data.csv",
                    expected_source_size_bytes=len(raw),
                    expected_source_sha256=hashlib.sha256(raw).hexdigest(),
                )

        class CallbackRecord:
            def __post_init__(self) -> None:
                raise AssertionError("untrusted nested callback executed")

        forged = copy.deepcopy(self.contract)
        object.__setattr__(forged, "layout", CallbackRecord())
        with self.assertRaisesRegex(
            TumviAdapterParserError,
            "foreign nested value type",
        ):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=forged,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

        class EqualityCallback:
            def __ne__(self, other: object) -> bool:
                raise AssertionError(f"untrusted contract equality executed for {other!r}")

        forged = copy.deepcopy(self.contract)
        object.__setattr__(forged, "contract_id", EqualityCallback())
        with self.assertRaisesRegex(TumviAdapterParserError, "foreign nested value type"):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=forged,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

        callback_hits: list[str] = []

        class HashingMeta(type):
            def __hash__(cls) -> int:
                callback_hits.append("hash callback")
                return 0

        class HashingRecord(metaclass=HashingMeta):
            pass

        forged = copy.deepcopy(self.contract)
        object.__setattr__(forged, "layout", HashingRecord())
        with self.assertRaisesRegex(TumviAdapterParserError, "foreign nested value type"):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=forged,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )
        self.assertEqual(callback_hits, [])

        forged = copy.deepcopy(self.contract)
        object.__setattr__(forged.layout, "sequence_directory_name", forged.layout)
        with self.assertRaisesRegex(TumviAdapterParserError, "cycle or shared"):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=forged,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

        shared: object = ("x",)
        for _ in range(20):
            shared = (shared, shared)
        forged = copy.deepcopy(self.contract)
        object.__setattr__(forged.layout, "excluded_prefixes", shared)
        with self.assertRaisesRegex(TumviAdapterParserError, "cycle or shared"):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=forged,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

        forged = copy.deepcopy(self.contract)
        object.__setattr__(
            forged.resource_limits,
            "maximum_csv_bytes_by_role",
            (("cam0",),),
        )
        with self.assertRaisesRegex(
            TumviAdapterParserError,
            "nested invariant validation failed",
        ):
            parse_tumvi_camera_index(
                io.BytesIO(raw),
                contract=forged,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                expected_source_size_bytes=len(raw),
                expected_source_sha256=hashlib.sha256(raw).hexdigest(),
            )

    def test_expected_size_and_sha_are_exact_and_verified(self) -> None:
        raw = _raw(CAMERA_HEADER, "1,1.png")
        cases = (
            (True, hashlib.sha256(raw).hexdigest(), "positive exact integer"),
            (0, hashlib.sha256(raw).hexdigest(), "positive exact integer"),
            (len(raw) - 1, hashlib.sha256(raw).hexdigest(), "exceeds expected"),
            (len(raw) + 1, hashlib.sha256(raw).hexdigest(), "size does not equal"),
            (len(raw), "A" * 64, "lowercase hexadecimal"),
            (len(raw), "0" * 63, "lowercase hexadecimal"),
            (len(raw), "0" * 64, "SHA-256 does not equal"),
        )
        for size, sha256, pattern in cases:
            with (
                self.subTest(size=size, sha256=sha256),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    pattern,
                ),
            ):
                self._camera(raw, size=size, sha256=sha256)

        source = io.BytesIO(raw)
        with self.assertRaisesRegex(TumviAdapterParserError, "contract limit"):
            self._camera(raw, source=source, size=98_058)
        self.assertEqual(source.tell(), 0)

    def test_known_real_source_hashes_are_denied_before_any_read(self) -> None:
        raw = _raw(CAMERA_HEADER, "1,1.png")
        for known_sha256 in KNOWN_REAL_SHA256:
            source = io.BytesIO(raw)
            with (
                self.subTest(sha256=known_sha256),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    "known inspected real-source identity",
                ),
            ):
                self._camera(raw, source=source, sha256=known_sha256)
            self.assertEqual(source.tell(), 0)
            self.assertFalse(source.closed)

    def test_rejects_raw_csv_transport_and_header_violations(self) -> None:
        valid_row = b"1,1.png\n"
        cases = (
            ("BOM", b"\xef\xbb\xbf" + CAMERA_HEADER.encode() + b"\n" + valid_row, "BOM"),
            ("CR", CAMERA_HEADER.encode() + b"\r\n" + valid_row, "carriage-return"),
            ("NUL", CAMERA_HEADER.encode() + b"\n1,1.png\x00\n", "NUL"),
            ("quote", CAMERA_HEADER.encode() + b'\n1,"1.png"\n', "quoted CSV"),
            ("non-ASCII", CAMERA_HEADER.encode() + b"\n1,\xc3\xa9.png\n", "ASCII"),
            ("missing final LF", CAMERA_HEADER.encode() + b"\n1,1.png", "end with LF"),
            ("header whitespace", b" #timestamp [ns],filename\n" + valid_row, "header"),
            ("header reorder", b"filename,#timestamp [ns]\n" + valid_row, "header"),
            ("extra header", CAMERA_HEADER.encode() + b",extra\n" + valid_row, "header"),
        )
        for label, raw, pattern in cases:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    pattern,
                ),
            ):
                self._camera(raw)

    def test_rejects_blank_comment_arity_whitespace_and_empty_data_cells(self) -> None:
        cases = (
            ("blank", _raw(CAMERA_HEADER, "", "1,1.png"), "blank"),
            ("comment", _raw(CAMERA_HEADER, "#other,field"), "comment"),
            ("short", _raw(CAMERA_HEADER, "1"), "arity"),
            ("long", _raw(CAMERA_HEADER, "1,1.png,extra"), "arity"),
            ("timestamp whitespace", _raw(CAMERA_HEADER, " 1,1.png"), "timestamp token"),
            ("filename whitespace", _raw(CAMERA_HEADER, "1,1.png "), "filename token"),
            ("empty timestamp", _raw(CAMERA_HEADER, ",1.png"), "timestamp token"),
            ("empty filename", _raw(CAMERA_HEADER, "1,"), "filename token"),
        )
        for label, raw, pattern in cases:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    pattern,
                ),
            ):
                self._camera(raw)

    def test_rejects_timestamp_order_range_and_lexeme_violations(self) -> None:
        cases = (
            ("leading zero", _raw(CAMERA_HEADER, "01,01.png"), "timestamp token"),
            ("negative", _raw(CAMERA_HEADER, "-1,1.png"), "timestamp token"),
            ("positive sign", _raw(CAMERA_HEADER, "+1,1.png"), "timestamp token"),
            (
                "overflow",
                _raw(CAMERA_HEADER, "9223372036854775808,9223372036854775808.png"),
                "timestamp token|exceeds",
            ),
            ("duplicate", _raw(CAMERA_HEADER, "1,1.png", "1,1.png"), "strictly increasing"),
            ("backward", _raw(CAMERA_HEADER, "2,2.png", "1,1.png"), "strictly increasing"),
        )
        for label, raw, pattern in cases:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    pattern,
                ),
            ):
                self._camera(raw)

    def test_rejects_unsafe_or_timestamp_inconsistent_filenames(self) -> None:
        cases = (
            ("leading zero", "1,01.png"),
            ("wrong case", "1,1.PNG"),
            ("slash", "1,dir/1.png"),
            ("backslash", r"1,dir\1.png"),
            ("wrong stem", "1,2.png"),
            ("dot prefix", "1,.1.png"),
        )
        for label, row in cases:
            with self.subTest(label=label), self.assertRaises(TumviAdapterParserError):
                self._camera(_raw(CAMERA_HEADER, row))

    def test_rejects_invalid_nonfinite_empty_or_oversized_numeric_lexemes(self) -> None:
        invalid = ("nan", "NaN", "inf", "-Infinity", "1 2", " 1", "1 ", "", ".", "1e", "--1")
        for token in invalid:
            row = f"1,{token},2,3,4,5,6"
            raw = _raw(IMU_HEADER, row)
            size, sha256 = _identity(raw)
            with (
                self.subTest(token=token),
                self.assertRaisesRegex(
                    TumviAdapterParserError,
                    "numeric token",
                ),
            ):
                parse_tumvi_imu_stream(
                    io.BytesIO(raw),
                    contract=self.contract,
                    source_path="mav0/imu0/data.csv",
                    expected_source_size_bytes=size,
                    expected_source_sha256=sha256,
                )

        oversized = "1" * 129
        raw = _raw(IMU_HEADER, f"1,{oversized},2,3,4,5,6")
        size, sha256 = _identity(raw)
        with self.assertRaisesRegex(TumviAdapterParserError, "numeric token"):
            parse_tumvi_imu_stream(
                io.BytesIO(raw),
                contract=self.contract,
                source_path="mav0/imu0/data.csv",
                expected_source_size_bytes=size,
                expected_source_sha256=sha256,
            )

    def test_enforces_minimum_rows_maximum_columns_line_bytes_and_row_count(self) -> None:
        header_only = _raw(CAMERA_HEADER)
        with self.assertRaisesRegex(TumviAdapterParserError, "minimum_data_rows"):
            self._camera(header_only)

        nine_columns = _raw(POSE_HEADER, "1,1,2,3,4,5,6,7,8")
        size, sha256 = _identity(nine_columns)
        with self.assertRaisesRegex(TumviAdapterParserError, "maximum_csv_columns"):
            parse_tumvi_pose_reference_stream(
                io.BytesIO(nine_columns),
                contract=self.contract,
                source_path="mav0/mocap0/data.csv",
                expected_source_size_bytes=size,
                expected_source_sha256=sha256,
            )

        oversized_line = (IMU_HEADER + "\n1," + "1" * 1_048_576 + ",2,3,4,5,6\n").encode()
        size, sha256 = _identity(oversized_line)
        self.assertLess(size, 2_232_296)
        with self.assertRaisesRegex(TumviAdapterParserError, "physical line exceeds"):
            parse_tumvi_imu_stream(
                io.BytesIO(oversized_line),
                contract=self.contract,
                source_path="mav0/imu0/data.csv",
                expected_source_size_bytes=size,
                expected_source_sha256=sha256,
            )

        forged = copy.deepcopy(self.contract)
        object.__setattr__(forged.resource_limits, "maximum_csv_rows_per_file", 1)
        two_rows = _raw(CAMERA_HEADER, "1,1.png", "2,2.png")
        with (
            mock.patch.object(parser_module, "_require_contract", return_value=forged),
            self.assertRaisesRegex(TumviAdapterParserError, "data-row count exceeds"),
        ):
            self._camera(two_rows)

    def test_rows_sources_and_batches_reject_direct_or_replace_forgery(self) -> None:
        raw = _raw(CAMERA_HEADER, "1,1.png")
        batch = self._camera(raw)
        row = batch.rows[0]
        self.assertFalse(hasattr(row, "__dict__"))
        self.assertFalse(hasattr(batch, "__dict__"))
        self.assertFalse(hasattr(batch.source, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            row.filename_source_lexeme = "2.png"  # type: ignore[misc]
        with self.assertRaisesRegex((TypeError, ValueError), "InitVar '_seal'"):
            replace(row, filename_source_lexeme="2.png")
        with self.assertRaisesRegex(TumviAdapterParserError, "only be constructed"):
            TumviCameraIndexRow(
                _seal=object(),
                stream_role="cam0",
                timestamp_source_label_ns=1,
                filename_source_lexeme="1.png",
            )
        with self.assertRaisesRegex(TumviAdapterParserError, "only be constructed"):
            TumviSyntheticSourceIdentity(
                _seal=object(),
                contract_id=batch.contract_id,
                contract_sha256=batch.contract_sha256,
                stream_role="cam0",
                source_path="mav0/cam0/data.csv",
                source_size_bytes=len(raw),
                source_sha256=hashlib.sha256(raw).hexdigest(),
                source_scope=batch.source_scope,
                scientific_authority="none",
                parser_accounting_policy_id=PARSER_ACCOUNTING_POLICY_ID,
            )
        with self.assertRaisesRegex((TypeError, ValueError), "InitVar '_seal'"):
            replace(batch, scientific_authority="full")

    def test_parser_import_graph_and_execution_have_no_filesystem_or_downstream_access(
        self,
    ) -> None:
        parser_path = REPOSITORY_ROOT / "src/compact_vio/data/tumvi_adapter_parser.py"
        tree = ast.parse(parser_path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)
        self.assertEqual(
            imported,
            {
                "__future__",
                "dataclasses",
                "hashlib",
                "io",
                "re",
                "compact_vio.data.tumvi_adapter_contract",
            },
        )
        forbidden_fragments = (
            "euroc",
            "learning",
            "model",
            "torch",
            "PIL",
            "pathlib",
            "subprocess",
        )
        self.assertFalse(
            any(fragment in name for name in imported for fragment in forbidden_fragments)
        )
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"open", "compile", "eval", "exec", "__import__"}
                for node in ast.walk(tree)
            )
        )
        raw = _raw(CAMERA_HEADER, "1,1.png")
        with mock.patch("builtins.open", side_effect=AssertionError("filesystem access")):
            batch = self._camera(raw)
        self.assertEqual(batch.rows[0].filename_source_lexeme, "1.png")


if __name__ == "__main__":
    unittest.main()

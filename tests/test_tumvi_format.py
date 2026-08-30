from __future__ import annotations

import hashlib
import io
import struct
import unittest
import zlib
from unittest import mock

from compact_vio.data.tumvi_format import (
    CsvInspectionLimits,
    CsvIssueCounts,
    GapStatistics,
    PngIhdrContract,
    TumviFormatError,
    inspect_numeric_csv,
    inspect_png_ihdr,
    inspect_stereo_camera_indexes,
)

CAMERA_HEADER = ("#timestamp [ns]", "filename")
IMU_HEADER = (
    "#timestamp [ns]",
    "w_x",
    "w_y",
    "w_z",
    "a_x",
    "a_y",
    "a_z",
)
PNG_CONTRACT = PngIhdrContract(width=512, height=512, bit_depth=16)


def _bytes(*lines: str) -> io.BytesIO:
    return io.BytesIO("\n".join(lines).encode("utf-8") + b"\n")


def _png_prefix(
    *,
    width: int = 512,
    height: int = 512,
    bit_depth: int = 16,
    color_type: int = 0,
    compression: int = 0,
    filter_method: int = 0,
    interlace: int = 0,
    chunk_length: int = 13,
    chunk_type: bytes = b"IHDR",
    valid_crc: bool = True,
    valid_signature: bool = True,
) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n" if valid_signature else b"not-a-pn"
    data = struct.pack(
        ">IIBBBBB",
        width,
        height,
        bit_depth,
        color_type,
        compression,
        filter_method,
        interlace,
    )
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    if not valid_crc:
        crc ^= 1
    return signature + struct.pack(">I", chunk_length) + chunk_type + data + struct.pack(">I", crc)


class TumviCsvFormatTests(unittest.TestCase):
    def test_streams_exact_stereo_indexes_and_records_gap_and_membership_facts(self) -> None:
        content = (
            "#timestamp [ns],filename",
            "100,100.png",
            "110,110.png",
            "125,125.png",
        )
        result = inspect_stereo_camera_indexes(
            _bytes(*content),
            _bytes(*content),
            expected_header=CAMERA_HEADER,
            required_png_basenames=("100.png", "125.png"),
        )

        self.assertTrue(result.conforms)
        self.assertTrue(result.exact_index_equality)
        self.assertEqual(result.violations, ())
        for camera in (result.cam0, result.cam1):
            self.assertEqual(camera.header, CAMERA_HEADER)
            self.assertEqual(camera.arity, 2)
            self.assertEqual(camera.row_count, 3)
            self.assertEqual(camera.first_timestamp_ns, 100)
            self.assertEqual(camera.last_timestamp_ns, 125)
            self.assertEqual(camera.gaps, GapStatistics(2, 10, 15, 25))
            self.assertEqual(
                camera.observed_required_png_basenames,
                ("100.png", "125.png"),
            )
            self.assertEqual(camera.required_png_occurrence_counts, (1, 1))
            self.assertEqual(camera.issues.valid_timestamp_count, 3)
            self.assertEqual(camera.issues.duplicate_camera_filename_count, 0)
            self.assertEqual(camera.source_size_bytes, len("\n".join(content)) + 1)
            self.assertFalse(hasattr(camera, "rows"))

    def test_utf8_bom_is_observed_without_changing_parsed_header(self) -> None:
        raw = b"\xef\xbb\xbf#timestamp [ns],value\n1,2\n"
        result = inspect_numeric_csv(
            io.BytesIO(raw),
            role="numeric",
            expected_header=("#timestamp [ns]", "value"),
        )

        self.assertTrue(result.conforms)
        self.assertTrue(result.utf8_bom_present)
        self.assertEqual(result.header, ("#timestamp [ns]", "value"))
        self.assertEqual(result.source_size_bytes, len(raw))
        self.assertEqual(result.source_sha256, hashlib.sha256(raw).hexdigest())

    def test_stereo_equality_is_exact_source_byte_identity(self) -> None:
        canonical = b"#timestamp [ns],filename\n1,1.png\n"
        semantically_equal = b"#timestamp [ns],filename\n1, 1.png\n"
        result = inspect_stereo_camera_indexes(
            io.BytesIO(canonical),
            io.BytesIO(semantically_equal),
            expected_header=CAMERA_HEADER,
            required_png_basenames=("1.png",),
        )

        self.assertTrue(result.cam0.conforms)
        self.assertTrue(result.cam1.conforms)
        self.assertFalse(result.exact_index_equality)
        self.assertEqual(result.violations, ("camera_index_mismatch",))
        self.assertNotEqual(result.cam0.source_sha256, result.cam1.source_sha256)

    def test_streams_numeric_csv_without_retaining_values(self) -> None:
        result = inspect_numeric_csv(
            _bytes(
                "#timestamp [ns],w_x,w_y,w_z,a_x,a_y,a_z",
                "10,0,-1.5,2e-3,4,5,6",
                "14,1,2,3,4.5,6,7",
            ),
            role="imu0",
            expected_header=IMU_HEADER,
        )

        self.assertTrue(result.conforms)
        self.assertEqual(result.row_count, 2)
        self.assertEqual(result.first_timestamp_ns, 10)
        self.assertEqual(result.last_timestamp_ns, 14)
        self.assertEqual(result.gaps, GapStatistics(1, 4, 4, 4))
        self.assertEqual(result.required_png_basenames, ())
        self.assertFalse(hasattr(result, "numeric_values"))

    def test_header_utf8_comment_and_arity_mismatches_are_bounded_observations(self) -> None:
        cases = (
            (
                "invalid UTF-8",
                io.BytesIO(b"\xff,b\n1,2\n"),
                ("invalid_utf8", "no_data_rows"),
            ),
            (
                "missing comment marker",
                _bytes("timestamp [ns],value", "1,2"),
                ("invalid_header_comment_syntax", "header_mismatch"),
            ),
            (
                "duplicate header",
                _bytes("#timestamp [ns],timestamp [ns]", "1,2"),
                ("duplicate_header_field", "header_mismatch"),
            ),
            (
                "later comment",
                _bytes("#timestamp [ns],value", "# another comment,value"),
                ("unexpected_comment_row",),
            ),
            (
                "blank row",
                _bytes("#timestamp [ns],value", "", "1,2"),
                ("blank_data_row",),
            ),
            (
                "wrong arity",
                _bytes("#timestamp [ns],value", "1,2,3"),
                ("row_arity_mismatch",),
            ),
            (
                "observed arity remains structural",
                _bytes("#timestamp [ns],value,extra", "1,2,3"),
                ("header_mismatch",),
            ),
        )
        for label, source, expected_violations in cases:
            with self.subTest(label=label):
                result = inspect_numeric_csv(
                    source,
                    role="numeric",
                    expected_header=("#timestamp [ns]", "value"),
                )
                self.assertFalse(result.conforms)
                for violation in expected_violations:
                    self.assertIn(violation, result.violations)
                self.assertLessEqual(len(result.violations), 32)
                if label == "later comment":
                    self.assertEqual(result.issues.unexpected_comment_row_count, 1)
                if label == "blank row":
                    self.assertEqual(result.issues.blank_row_count, 1)
                if label == "wrong arity":
                    self.assertEqual(result.issues.ragged_row_count, 1)

    def test_timestamp_grammar_int64_order_and_uniqueness_fail_closed(self) -> None:
        cases = (
            ("01", "invalid_timestamp_lexeme"),
            (str(1 << 63), "timestamp_exceeds_int64"),
        )
        for token, violation in cases:
            with self.subTest(token=token):
                result = inspect_numeric_csv(
                    _bytes("#timestamp [ns],value", f"{token},1"),
                    role="numeric",
                    expected_header=("#timestamp [ns]", "value"),
                )
                self.assertFalse(result.conforms)
                self.assertIn(violation, result.violations)
                issue_field = (
                    "invalid_timestamp_lexeme_count"
                    if violation == "invalid_timestamp_lexeme"
                    else "timestamp_exceeds_int64_count"
                )
                self.assertEqual(getattr(result.issues, issue_field), 1)

        duplicate = inspect_numeric_csv(
            _bytes("#timestamp [ns],value", "10,1", "10,2"),
            role="numeric",
            expected_header=("#timestamp [ns]", "value"),
        )
        self.assertIn("duplicate_timestamp", duplicate.violations)
        self.assertEqual(duplicate.issues.duplicate_timestamp_count, 1)
        self.assertEqual(duplicate.gaps, GapStatistics(0, None, None, 0))

        backward = inspect_numeric_csv(
            _bytes("#timestamp [ns],value", "10,1", "9,2"),
            role="numeric",
            expected_header=("#timestamp [ns]", "value"),
        )
        self.assertIn("out_of_order_timestamp", backward.violations)
        self.assertEqual(backward.issues.out_of_order_timestamp_count, 1)
        self.assertEqual(backward.gaps, GapStatistics(0, None, None, 0))

    def test_nonfinite_and_nonnumeric_fields_are_observed(self) -> None:
        result = inspect_numeric_csv(
            _bytes("#timestamp [ns],value", "1,nan", "2,not-a-number", "3,inf"),
            role="numeric",
            expected_header=("#timestamp [ns]", "value"),
        )
        self.assertFalse(result.conforms)
        self.assertIn("non_finite_numeric_field", result.violations)
        self.assertIn("invalid_numeric_field", result.violations)
        self.assertEqual(result.issues.valid_timestamp_count, 3)
        self.assertEqual(result.issues.invalid_numeric_field_count, 1)
        self.assertEqual(result.issues.non_finite_numeric_field_count, 2)

    def test_camera_names_membership_and_exact_cross_camera_equality_are_required(self) -> None:
        unsafe = inspect_stereo_camera_indexes(
            _bytes("#timestamp [ns],filename", "1,../1.png"),
            _bytes("#timestamp [ns],filename", "1,../1.png"),
            expected_header=CAMERA_HEADER,
            required_png_basenames=("1.png",),
        )
        self.assertFalse(unsafe.conforms)
        self.assertIn("unsafe_camera_filename", unsafe.cam0.violations)
        self.assertEqual(unsafe.cam0.issues.unsafe_camera_filename_count, 1)
        self.assertIn("required_png_not_in_camera_index", unsafe.cam0.violations)

        mismatch = inspect_stereo_camera_indexes(
            _bytes("#timestamp [ns],filename", "1,1.png", "2,2.png"),
            _bytes("#timestamp [ns],filename", "1,1.png", "3,2.png"),
            expected_header=CAMERA_HEADER,
            required_png_basenames=("1.png", "2.png"),
        )
        self.assertFalse(mismatch.conforms)
        self.assertFalse(mismatch.exact_index_equality)
        self.assertEqual(mismatch.violations, ("camera_index_mismatch",))

        selected_timestamp_mismatch = inspect_stereo_camera_indexes(
            _bytes("#timestamp [ns],filename", "2,1.png"),
            _bytes("#timestamp [ns],filename", "2,1.png"),
            expected_header=CAMERA_HEADER,
            required_png_basenames=("1.png",),
        )
        self.assertFalse(selected_timestamp_mismatch.conforms)
        self.assertIn(
            "required_png_stem_timestamp_mismatch",
            selected_timestamp_mismatch.cam0.violations,
        )

        duplicate_filename = inspect_stereo_camera_indexes(
            _bytes("#timestamp [ns],filename", "1,1.png", "2,1.png"),
            _bytes("#timestamp [ns],filename", "1,1.png", "2,1.png"),
            expected_header=CAMERA_HEADER,
            required_png_basenames=("1.png",),
        )
        self.assertFalse(duplicate_filename.conforms)
        self.assertIn("duplicate_camera_filename", duplicate_filename.cam0.violations)
        self.assertIn(
            "required_png_not_exactly_once",
            duplicate_filename.cam0.violations,
        )
        self.assertEqual(duplicate_filename.cam0.required_png_occurrence_counts, (2,))
        self.assertEqual(
            duplicate_filename.cam0.issues.duplicate_camera_filename_count,
            1,
        )

    def test_csv_api_and_resource_bounds_are_strict(self) -> None:
        with self.assertRaisesRegex(TumviFormatError, "header syntax"):
            inspect_numeric_csv(
                _bytes("#timestamp,value", "1,2"),
                role="numeric",
                expected_header=("timestamp", "value"),
            )
        with self.assertRaisesRegex(TumviFormatError, "max_line_bytes"):
            inspect_numeric_csv(
                _bytes("#timestamp,value", "1," + "1" * 32),
                role="numeric",
                expected_header=("#timestamp", "value"),
                limits=CsvInspectionLimits(max_bytes=128, max_line_bytes=16),
            )
        with self.assertRaises(TumviFormatError):
            GapStatistics(2, 10, 20, 100)
        with self.assertRaisesRegex(TumviFormatError, "max_rows"):
            inspect_numeric_csv(
                _bytes("#timestamp,value", "1,2", "2,3"),
                role="numeric",
                expected_header=("#timestamp", "value"),
                limits=CsvInspectionLimits(max_rows=1),
            )
        with self.assertRaisesRegex(TumviFormatError, "max_columns"):
            inspect_numeric_csv(
                _bytes("#timestamp,value", "1,2,3"),
                role="numeric",
                expected_header=("#timestamp", "value"),
                limits=CsvInspectionLimits(max_columns=2),
            )
        with self.assertRaisesRegex(TumviFormatError, "PNG integer boundary"):
            PngIhdrContract(width=1 << 31, height=1, bit_depth=16)

    def test_malformed_csv_is_a_bounded_content_observation(self) -> None:
        result = inspect_numeric_csv(
            io.BytesIO(b'#timestamp,value\n1,"unterminated\n'),
            role="numeric",
            expected_header=("#timestamp", "value"),
        )

        self.assertFalse(result.conforms)
        self.assertIn("invalid_csv_syntax", result.violations)
        self.assertEqual(result.source_size_bytes, 33)
        self.assertIsInstance(result.issues, CsvIssueCounts)


class TumviPngFormatTests(unittest.TestCase):
    def test_interprets_exact_ihdr_without_pixel_decompression(self) -> None:
        prefix = _png_prefix()
        with mock.patch.object(zlib, "decompress", side_effect=AssertionError("must not decode")):
            result = inspect_png_ihdr(
                prefix,
                total_size_bytes=284_188,
                expected=PNG_CONTRACT,
            )

        self.assertTrue(result.conforms)
        self.assertEqual(result.width, 512)
        self.assertEqual(result.height, 512)
        self.assertEqual(result.bit_depth, 16)
        self.assertEqual(result.color_type, 0)
        self.assertEqual(result.compression_method, 0)
        self.assertEqual(result.filter_method, 0)
        self.assertEqual(result.interlace_method, 0)
        self.assertEqual(result.ihdr_crc32, zlib.crc32(prefix[12:29]) & 0xFFFFFFFF)

    def test_signature_ihdr_length_type_and_crc_are_checked(self) -> None:
        cases = (
            (_png_prefix(valid_signature=False), "invalid_png_signature"),
            (_png_prefix(chunk_length=12), "invalid_ihdr_length"),
            (_png_prefix(chunk_type=b"JHDR"), "ihdr_not_first"),
            (_png_prefix(valid_crc=False), "invalid_ihdr_crc"),
        )
        for prefix, violation in cases:
            with self.subTest(violation=violation):
                result = inspect_png_ihdr(
                    prefix,
                    total_size_bytes=1_000,
                    expected=PNG_CONTRACT,
                )
                self.assertFalse(result.conforms)
                self.assertIn(violation, result.violations)

    def test_ihdr_profile_and_legal_png_fields_are_observed_without_color_inference(self) -> None:
        cases = (
            (_png_prefix(width=511), "width_mismatch"),
            (_png_prefix(height=511), "height_mismatch"),
            (_png_prefix(bit_depth=8), "bit_depth_mismatch"),
            (
                _png_prefix(bit_depth=4, color_type=2),
                "invalid_bit_depth_color_type_pair",
            ),
            (_png_prefix(compression=1), "unsupported_compression_method"),
            (_png_prefix(filter_method=1), "unsupported_filter_method"),
            (_png_prefix(interlace=2), "invalid_interlace_method"),
            (_png_prefix(width=0), "invalid_png_dimensions"),
        )
        for prefix, violation in cases:
            with self.subTest(violation=violation):
                result = inspect_png_ihdr(
                    prefix,
                    total_size_bytes=1_000,
                    expected=PNG_CONTRACT,
                )
                self.assertFalse(result.conforms)
                self.assertIn(violation, result.violations)

        legal_truecolor = inspect_png_ihdr(
            _png_prefix(color_type=2),
            total_size_bytes=1_000,
            expected=PNG_CONTRACT,
        )
        self.assertTrue(legal_truecolor.conforms)
        self.assertEqual(legal_truecolor.color_type, 2)

    def test_png_api_requires_exact_prefix_and_bounded_total_size(self) -> None:
        prefix = _png_prefix()
        with self.assertRaisesRegex(TumviFormatError, "exactly the first 33"):
            inspect_png_ihdr(
                prefix + b"payload",
                total_size_bytes=40,
                expected=PNG_CONTRACT,
            )
        with self.assertRaisesRegex(TumviFormatError, "max_total_bytes"):
            inspect_png_ihdr(
                prefix,
                total_size_bytes=1_001,
                expected=PNG_CONTRACT,
                max_total_bytes=1_000,
            )


if __name__ == "__main__":
    unittest.main()

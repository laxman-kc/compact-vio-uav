"""Bounded structural observations for an exact TUM VI compatibility slice.

The CSV inspectors stream decoded records without retaining raw rows.  The PNG
inspector accepts and interprets exactly the 33-byte signature/IHDR prefix; it
never receives compressed image payload bytes and performs no pixel decoding.
"""

from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import struct
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import BinaryIO

_MAX_TIMESTAMP_NS = (1 << 63) - 1
_MAX_PNG_DIMENSION = 0x7FFFFFFF
_TIMESTAMP = re.compile(r"(?:0|[1-9][0-9]*)")
_SAFE_PNG_BASENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\.png")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_VALID_BIT_DEPTHS = {
    0: frozenset((1, 2, 4, 8, 16)),
    2: frozenset((8, 16)),
    3: frozenset((1, 2, 4, 8)),
    4: frozenset((8, 16)),
    6: frozenset((8, 16)),
}
DEFAULT_MAX_PNG_BYTES = 16_777_216


class TumviFormatError(ValueError):
    """The inspection API or its resource boundary is invalid."""


def _exact_int(value: object, *, field: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise TumviFormatError(f"{field} must be an integer >= {minimum}")
    return value


def _exact_optional_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    return _exact_int(value, field=field)


def _exact_text_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if type(value) is not tuple or any(type(item) is not str for item in value):
        raise TumviFormatError(f"{field} must be a tuple of strings")
    return value


@dataclass(frozen=True, slots=True)
class CsvInspectionLimits:
    """Hard streaming bounds for one CSV input."""

    max_bytes: int = 16_777_216
    max_rows: int = 2_000_000
    max_columns: int = 64
    max_line_bytes: int = 1_048_576
    max_violations: int = 32

    def __post_init__(self) -> None:
        for field in (
            "max_bytes",
            "max_rows",
            "max_columns",
            "max_line_bytes",
            "max_violations",
        ):
            _exact_int(getattr(self, field), field=field, minimum=1)
        if self.max_line_bytes > self.max_bytes:
            raise TumviFormatError("max_line_bytes must not exceed max_bytes")


DEFAULT_CSV_LIMITS = CsvInspectionLimits()


@dataclass(frozen=True, slots=True)
class GapStatistics:
    """Exact integer statistics for consecutive positive timestamp gaps."""

    gap_count: int
    minimum_gap_ns: int | None
    maximum_gap_ns: int | None
    total_gap_ns: int

    def __post_init__(self) -> None:
        count = _exact_int(self.gap_count, field="gap_count")
        total = _exact_int(self.total_gap_ns, field="total_gap_ns")
        minimum = _exact_optional_int(self.minimum_gap_ns, field="minimum_gap_ns")
        maximum = _exact_optional_int(self.maximum_gap_ns, field="maximum_gap_ns")
        if count == 0:
            if minimum is not None or maximum is not None or total != 0:
                raise TumviFormatError("empty gap statistics must use null bounds and zero total")
            return
        if minimum is None or maximum is None or minimum < 1 or minimum > maximum:
            raise TumviFormatError("non-empty gap statistics require ordered positive bounds")
        if not minimum * count <= total <= maximum * count:
            raise TumviFormatError("gap total is outside the exact count/bounds invariant")


@dataclass(frozen=True, slots=True)
class CsvIssueCounts:
    """Exact bounded aggregate counts; no raw CSV values are retained."""

    valid_timestamp_count: int
    invalid_timestamp_lexeme_count: int
    timestamp_exceeds_int64_count: int
    duplicate_timestamp_count: int
    out_of_order_timestamp_count: int
    blank_row_count: int
    ragged_row_count: int
    unexpected_comment_row_count: int
    invalid_numeric_field_count: int
    non_finite_numeric_field_count: int
    unsafe_camera_filename_count: int
    duplicate_camera_filename_count: int

    def __post_init__(self) -> None:
        for field in self.__dataclass_fields__:
            _exact_int(getattr(self, field), field=field)


@dataclass(frozen=True, slots=True)
class CsvStructureObservation:
    """Bounded structural facts from one streamed CSV."""

    role: str
    header: tuple[str, ...]
    expected_header: tuple[str, ...]
    source_size_bytes: int
    source_sha256: str
    utf8_bom_present: bool
    arity: int
    row_count: int
    first_timestamp_ns: int | None
    last_timestamp_ns: int | None
    gaps: GapStatistics
    required_png_basenames: tuple[str, ...]
    observed_required_png_basenames: tuple[str, ...]
    required_png_occurrence_counts: tuple[int, ...]
    issues: CsvIssueCounts
    conforms: bool
    violations: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.role) is not str or not self.role:
            raise TumviFormatError("role must be non-empty text")
        header = _exact_text_tuple(self.header, field="header")
        expected = _exact_text_tuple(self.expected_header, field="expected_header")
        required = _exact_text_tuple(
            self.required_png_basenames,
            field="required_png_basenames",
        )
        observed = _exact_text_tuple(
            self.observed_required_png_basenames,
            field="observed_required_png_basenames",
        )
        violations = _exact_text_tuple(self.violations, field="violations")
        _exact_int(self.source_size_bytes, field="source_size_bytes")
        if (
            type(self.source_sha256) is not str
            or re.fullmatch(r"[0-9a-f]{64}", self.source_sha256) is None
        ):
            raise TumviFormatError("source_sha256 must be a lowercase SHA-256 digest")
        if type(self.utf8_bom_present) is not bool:
            raise TumviFormatError("utf8_bom_present must be a boolean")
        arity = _exact_int(self.arity, field="arity")
        rows = _exact_int(self.row_count, field="row_count")
        first = _exact_optional_int(self.first_timestamp_ns, field="first_timestamp_ns")
        last = _exact_optional_int(self.last_timestamp_ns, field="last_timestamp_ns")
        if arity != len(header):
            raise TumviFormatError("arity must equal the observed header length")
        if len(set(required)) != len(required) or len(set(observed)) != len(observed):
            raise TumviFormatError("required/observed PNG basename tuples must be unique")
        if any(name not in required for name in observed):
            raise TumviFormatError("observed required PNG basenames must be a required subset")
        if type(self.required_png_occurrence_counts) is not tuple or any(
            type(count) is not int or count < 0 for count in self.required_png_occurrence_counts
        ):
            raise TumviFormatError("required PNG occurrence counts must be non-negative integers")
        if len(self.required_png_occurrence_counts) != len(required):
            raise TumviFormatError("required PNG occurrence counts must align with required names")
        expected_observed = tuple(
            name
            for name, count in zip(required, self.required_png_occurrence_counts, strict=True)
            if count > 0
        )
        if observed != expected_observed:
            raise TumviFormatError("observed required PNG names disagree with occurrence counts")
        if type(self.issues) is not CsvIssueCounts:
            raise TumviFormatError("issues must be an exact CsvIssueCounts")
        if type(self.gaps) is not GapStatistics:
            raise TumviFormatError("gaps must be GapStatistics")
        if type(self.conforms) is not bool:
            raise TumviFormatError("conforms must be a boolean")
        if self.conforms != (not violations):
            raise TumviFormatError("conforms must equal the absence of violations")
        if len(set(violations)) != len(violations) or any(not item for item in violations):
            raise TumviFormatError("violations must contain unique non-empty codes")
        if rows == 0 and (first is not None or last is not None):
            raise TumviFormatError("an empty CSV cannot report timestamp endpoints")
        if first is not None and last is not None and first > last and self.conforms:
            raise TumviFormatError("conforming timestamp endpoints must be ordered")
        if self.conforms:
            if header != expected or rows < 1 or first is None or last is None:
                raise TumviFormatError("conforming CSV observations require exact non-empty data")
            if self.gaps.gap_count != rows - 1:
                raise TumviFormatError("conforming gap count must equal row_count - 1")
            if self.gaps.total_gap_ns != last - first:
                raise TumviFormatError("conforming gap total must equal last - first")


@dataclass(frozen=True, slots=True)
class StereoCameraIndexObservation:
    """Two camera indexes inspected and compared in lockstep."""

    cam0: CsvStructureObservation
    cam1: CsvStructureObservation
    exact_index_equality: bool
    conforms: bool
    violations: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            type(self.cam0) is not CsvStructureObservation
            or type(self.cam1) is not CsvStructureObservation
        ):
            raise TumviFormatError("cam0 and cam1 must be exact CSV observations")
        if type(self.exact_index_equality) is not bool or type(self.conforms) is not bool:
            raise TumviFormatError("stereo equality and conformance must be booleans")
        violations = _exact_text_tuple(self.violations, field="violations")
        if len(set(violations)) != len(violations) or any(not item for item in violations):
            raise TumviFormatError("stereo violations must be unique non-empty codes")
        if self.conforms != (
            self.cam0.conforms
            and self.cam1.conforms
            and self.exact_index_equality
            and not violations
        ):
            raise TumviFormatError("stereo conforms is inconsistent with its observations")


@dataclass(frozen=True, slots=True)
class PngIhdrContract:
    """Source-backed comparisons that do not infer PNG color type."""

    width: int
    height: int
    bit_depth: int

    def __post_init__(self) -> None:
        width = _exact_int(self.width, field="width", minimum=1)
        height = _exact_int(self.height, field="height", minimum=1)
        bit_depth = _exact_int(self.bit_depth, field="bit_depth", minimum=1)
        if width > _MAX_PNG_DIMENSION or height > _MAX_PNG_DIMENSION:
            raise TumviFormatError("PNG contract dimensions exceed the PNG integer boundary")
        if bit_depth not in (1, 2, 4, 8, 16):
            raise TumviFormatError("PNG contract bit_depth is not recognized")


@dataclass(frozen=True, slots=True)
class PngIhdrObservation:
    """Facts interpreted from exactly the PNG signature and IHDR chunk."""

    total_size_bytes: int
    width: int
    height: int
    bit_depth: int
    color_type: int
    compression_method: int
    filter_method: int
    interlace_method: int
    ihdr_crc32: int
    conforms: bool
    violations: tuple[str, ...]

    def __post_init__(self) -> None:
        _exact_int(self.total_size_bytes, field="total_size_bytes", minimum=33)
        for field in (
            "width",
            "height",
            "bit_depth",
            "color_type",
            "compression_method",
            "filter_method",
            "interlace_method",
            "ihdr_crc32",
        ):
            _exact_int(getattr(self, field), field=field)
        if self.ihdr_crc32 > 0xFFFFFFFF:
            raise TumviFormatError("ihdr_crc32 exceeds uint32")
        if type(self.conforms) is not bool:
            raise TumviFormatError("conforms must be a boolean")
        violations = _exact_text_tuple(self.violations, field="violations")
        if len(set(violations)) != len(violations) or any(not item for item in violations):
            raise TumviFormatError("PNG violations must be unique non-empty codes")
        if self.conforms != (not violations):
            raise TumviFormatError("conforms must equal the absence of PNG violations")


class _ViolationSet:
    def __init__(self, maximum: int) -> None:
        self._maximum = maximum
        self._items: list[str] = []
        self._seen: set[str] = set()

    def add(self, code: str) -> None:
        if code in self._seen:
            return
        self._seen.add(code)
        if len(self._items) < self._maximum:
            self._items.append(code)
        elif "additional_violations_omitted" not in self._items:
            self._items[-1] = "additional_violations_omitted"

    def tuple(self) -> tuple[str, ...]:
        return tuple(self._items)


class _BoundedUtf8Lines:
    def __init__(self, source: BinaryIO, limits: CsvInspectionLimits) -> None:
        if not hasattr(source, "readline"):
            raise TumviFormatError("CSV source must provide binary readline")
        self._source = source
        self._limits = limits
        self._total = 0
        self._sha256 = hashlib.sha256()
        self._first_physical_line = True
        self.utf8_bom_present = False
        self.complete = False

    def __iter__(self) -> _BoundedUtf8Lines:
        return self

    def __next__(self) -> str:
        try:
            raw = self._source.readline(self._limits.max_line_bytes + 1)
        except OSError as exc:
            raise TumviFormatError(f"cannot read CSV source: {exc}") from exc
        if type(raw) is not bytes:
            raise TumviFormatError("CSV source readline must return exact bytes")
        if not raw:
            self.complete = True
            raise StopIteration
        if len(raw) > self._limits.max_line_bytes:
            raise TumviFormatError("CSV physical line exceeds max_line_bytes")
        self._total += len(raw)
        if self._total > self._limits.max_bytes:
            raise TumviFormatError("CSV source exceeds max_bytes")
        self._sha256.update(raw)
        if self._first_physical_line:
            self._first_physical_line = False
            if raw.startswith(b"\xef\xbb\xbf"):
                self.utf8_bom_present = True
                raw = raw[3:]
        try:
            return raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise _CsvContentError("invalid_utf8") from exc

    @property
    def source_size_bytes(self) -> int:
        return self._total

    @property
    def source_sha256(self) -> str:
        if not self.complete:
            raise TumviFormatError("CSV source must be exhausted before hashing")
        return self._sha256.hexdigest()


class _CsvContentError(Exception):
    pass


def _normalized_header(row: list[str], violations: _ViolationSet) -> tuple[str, ...]:
    header = tuple(value.strip() for value in row)
    if not header:
        violations.add("missing_header")
        return ()
    if any(not value or any(character in value for character in "\x00\r\n") for value in header):
        violations.add("invalid_header_field")
    if not header[0].startswith("#") or header[0].startswith("##") or not header[0][1:].strip():
        violations.add("invalid_header_comment_syntax")
    if any(value.startswith("#") for value in header[1:]):
        violations.add("invalid_header_comment_syntax")
    labels = (header[0][1:].strip(),) + header[1:]
    if len(set(labels)) != len(labels):
        violations.add("duplicate_header_field")
    return header


def _validated_spec(
    expected_header: tuple[str, ...],
    limits: CsvInspectionLimits,
) -> tuple[str, ...]:
    if type(limits) is not CsvInspectionLimits:
        raise TumviFormatError("limits must be an exact CsvInspectionLimits")
    expected = _exact_text_tuple(expected_header, field="expected_header")
    if not expected or len(expected) > limits.max_columns:
        raise TumviFormatError("expected_header has an invalid column count")
    violations = _ViolationSet(limits.max_violations)
    normalized = _normalized_header(list(expected), violations)
    if violations.tuple():
        raise TumviFormatError("expected_header does not satisfy the header syntax contract")
    return normalized


def _safe_png_basename(value: str) -> bool:
    return (
        _SAFE_PNG_BASENAME.fullmatch(value) is not None
        and 1 <= len(value) <= 255
        and os.path.basename(value) == value
        and "/" not in value
        and "\\" not in value
    )


def _validated_required_pngs(value: tuple[str, ...]) -> tuple[str, ...]:
    required = _exact_text_tuple(value, field="required_png_basenames")
    if not required or len(set(required)) != len(required):
        raise TumviFormatError("required_png_basenames must be non-empty and unique")
    if any(not _safe_png_basename(name) for name in required):
        raise TumviFormatError("required_png_basenames contains an unsafe name")
    for name in required:
        stem = name.removesuffix(".png")
        if _TIMESTAMP.fullmatch(stem) is None or int(stem) > _MAX_TIMESTAMP_NS:
            raise TumviFormatError(
                "required PNG basenames must have canonical int64 timestamp stems"
            )
    return required


class _CsvCursor:
    def __init__(
        self,
        source: BinaryIO,
        *,
        role: str,
        expected_header: tuple[str, ...],
        limits: CsvInspectionLimits,
        required_png_basenames: tuple[str, ...] = (),
        camera: bool,
    ) -> None:
        if type(role) is not str or not role:
            raise TumviFormatError("role must be non-empty text")
        self.role = role
        self.expected_header = _validated_spec(expected_header, limits)
        self.limits = limits
        self.required = required_png_basenames
        self.camera = camera
        self.violations = _ViolationSet(limits.max_violations)
        self.lines = _BoundedUtf8Lines(source, limits)
        self.reader = csv.reader(self.lines, strict=True)
        self.header: tuple[str, ...] = ()
        self.row_count = 0
        self.first_timestamp: int | None = None
        self.last_timestamp: int | None = None
        self.previous_timestamp: int | None = None
        self.gap_count = 0
        self.minimum_gap: int | None = None
        self.maximum_gap: int | None = None
        self.total_gap = 0
        self.timestamp_series_complete = True
        self.required_occurrences = {name: 0 for name in self.required}
        self.seen_camera_filenames: set[str] = set()
        self.issue_counts = {field: 0 for field in CsvIssueCounts.__dataclass_fields__}
        self._closed = False
        self._read_header()

    def _increment(self, field: str) -> None:
        self.issue_counts[field] += 1

    def _read_header(self) -> None:
        try:
            row = next(self.reader)
        except StopIteration:
            self.violations.add("missing_header")
            self._closed = True
            return
        except _CsvContentError as exc:
            self.violations.add(str(exc))
            self._closed = True
            return
        except csv.Error:
            self.violations.add("invalid_csv_syntax")
            self._closed = True
            return
        self.header = _normalized_header(row, self.violations)
        if len(self.header) > self.limits.max_columns:
            raise TumviFormatError("CSV header exceeds max_columns")
        if self.header != self.expected_header:
            self.violations.add("header_mismatch")

    def _timestamp(self, value: str) -> int | None:
        token = value.strip()
        if _TIMESTAMP.fullmatch(token) is None:
            self.violations.add("invalid_timestamp_lexeme")
            self._increment("invalid_timestamp_lexeme_count")
            self.timestamp_series_complete = False
            return None
        timestamp = int(token)
        if timestamp > _MAX_TIMESTAMP_NS:
            self.violations.add("timestamp_exceeds_int64")
            self._increment("timestamp_exceeds_int64_count")
            self.timestamp_series_complete = False
            return None
        self._increment("valid_timestamp_count")
        previous = self.previous_timestamp
        if self.first_timestamp is None:
            self.first_timestamp = timestamp
        if previous is not None:
            if timestamp == previous:
                self.violations.add("duplicate_timestamp")
                self._increment("duplicate_timestamp_count")
                self.timestamp_series_complete = False
            elif timestamp < previous:
                self.violations.add("out_of_order_timestamp")
                self._increment("out_of_order_timestamp_count")
                self.timestamp_series_complete = False
            elif self.timestamp_series_complete:
                gap = timestamp - previous
                self.gap_count += 1
                self.total_gap += gap
                self.minimum_gap = gap if self.minimum_gap is None else min(self.minimum_gap, gap)
                self.maximum_gap = gap if self.maximum_gap is None else max(self.maximum_gap, gap)
        self.previous_timestamp = timestamp
        self.last_timestamp = timestamp
        return timestamp

    def _camera_row(self, row: list[str]) -> tuple[int, str] | None:
        timestamp = self._timestamp(row[0])
        filename = row[1].strip()
        if not _safe_png_basename(filename):
            self.violations.add("unsafe_camera_filename")
            self._increment("unsafe_camera_filename_count")
        if filename in self.seen_camera_filenames:
            self.violations.add("duplicate_camera_filename")
            self._increment("duplicate_camera_filename_count")
        else:
            self.seen_camera_filenames.add(filename)
        if filename in self.required:
            self.required_occurrences[filename] += 1
            if timestamp is not None and int(filename.removesuffix(".png")) != timestamp:
                self.violations.add("required_png_stem_timestamp_mismatch")
        if timestamp is None or not _safe_png_basename(filename):
            return None
        return timestamp, filename

    def _numeric_row(self, row: list[str]) -> tuple[int, str] | None:
        timestamp = self._timestamp(row[0])
        for value in row[1:]:
            token = value.strip()
            try:
                number = float(token)
            except ValueError:
                self.violations.add("invalid_numeric_field")
                self._increment("invalid_numeric_field_count")
                continue
            if not token or not math.isfinite(number):
                self.violations.add("non_finite_numeric_field")
                self._increment("non_finite_numeric_field_count")
        return None if timestamp is None else (timestamp, "")

    def _drain_remaining_bytes(self) -> None:
        while not self.lines.complete:
            try:
                next(self.lines)
            except StopIteration:
                break
            except _CsvContentError as exc:
                self.violations.add(str(exc))

    def rows(self) -> Iterator[tuple[int, str] | None]:
        if self._closed:
            self._drain_remaining_bytes()
            return
        try:
            for row in self.reader:
                self.row_count += 1
                if self.row_count > self.limits.max_rows:
                    raise TumviFormatError("CSV source exceeds max_rows")
                if len(row) > self.limits.max_columns:
                    raise TumviFormatError("CSV row exceeds max_columns")
                if not row or all(not value.strip() for value in row):
                    self.violations.add("blank_data_row")
                    self._increment("blank_row_count")
                    yield None
                    continue
                if row[0].strip().startswith("#"):
                    self.violations.add("unexpected_comment_row")
                    self._increment("unexpected_comment_row_count")
                    yield None
                    continue
                if not self.header or len(row) != len(self.header):
                    self.violations.add("row_arity_mismatch")
                    self._increment("ragged_row_count")
                    self.timestamp_series_complete = False
                    yield None
                    continue
                if self.camera and len(row) != 2:
                    yield None
                    continue
                yield self._camera_row(row) if self.camera else self._numeric_row(row)
        except _CsvContentError as exc:
            self.violations.add(str(exc))
        except csv.Error:
            self.violations.add("invalid_csv_syntax")
        finally:
            self._drain_remaining_bytes()
            self._closed = True

    def observation(self) -> CsvStructureObservation:
        if not self._closed:
            raise TumviFormatError("CSV rows must be exhausted before observation")
        if self.row_count == 0:
            self.violations.add("no_data_rows")
        if self.camera:
            for name in self.required:
                occurrence_count = self.required_occurrences[name]
                if occurrence_count == 0:
                    self.violations.add("required_png_not_in_camera_index")
                elif occurrence_count != 1:
                    self.violations.add("required_png_not_exactly_once")
        if not self.timestamp_series_complete:
            gaps = GapStatistics(0, None, None, 0)
        else:
            gaps = GapStatistics(
                self.gap_count,
                self.minimum_gap,
                self.maximum_gap,
                self.total_gap,
            )
        violations = self.violations.tuple()
        return CsvStructureObservation(
            role=self.role,
            header=self.header,
            expected_header=self.expected_header,
            source_size_bytes=self.lines.source_size_bytes,
            source_sha256=self.lines.source_sha256,
            utf8_bom_present=self.lines.utf8_bom_present,
            arity=len(self.header),
            row_count=self.row_count,
            first_timestamp_ns=self.first_timestamp,
            last_timestamp_ns=self.last_timestamp,
            gaps=gaps,
            required_png_basenames=self.required,
            observed_required_png_basenames=tuple(
                name for name in self.required if self.required_occurrences[name] > 0
            ),
            required_png_occurrence_counts=tuple(
                self.required_occurrences[name] for name in self.required
            ),
            issues=CsvIssueCounts(**self.issue_counts),
            conforms=not violations,
            violations=violations,
        )


def inspect_stereo_camera_indexes(
    cam0: BinaryIO,
    cam1: BinaryIO,
    *,
    expected_header: tuple[str, ...],
    required_png_basenames: tuple[str, ...],
    limits: CsvInspectionLimits = DEFAULT_CSV_LIMITS,
) -> StereoCameraIndexObservation:
    """Stream and compare two camera indexes without retaining their rows."""

    required = _validated_required_pngs(required_png_basenames)
    left = _CsvCursor(
        cam0,
        role="cam0_index",
        expected_header=expected_header,
        limits=limits,
        required_png_basenames=required,
        camera=True,
    )
    right = _CsvCursor(
        cam1,
        role="cam1_index",
        expected_header=expected_header,
        limits=limits,
        required_png_basenames=required,
        camera=True,
    )
    for _ in left.rows():
        pass
    for _ in right.rows():
        pass
    left_observation = left.observation()
    right_observation = right.observation()
    exact = (
        left_observation.source_size_bytes == right_observation.source_size_bytes
        and left_observation.source_sha256 == right_observation.source_sha256
    )
    violations: list[str] = []
    if not exact:
        violations.append("camera_index_mismatch")
    return StereoCameraIndexObservation(
        cam0=left_observation,
        cam1=right_observation,
        exact_index_equality=exact,
        conforms=left_observation.conforms and right_observation.conforms and exact,
        violations=tuple(violations),
    )


def inspect_numeric_csv(
    source: BinaryIO,
    *,
    role: str,
    expected_header: tuple[str, ...],
    limits: CsvInspectionLimits = DEFAULT_CSV_LIMITS,
) -> CsvStructureObservation:
    """Stream one timestamp-plus-finite-numeric CSV into bounded observations."""

    cursor = _CsvCursor(
        source,
        role=role,
        expected_header=expected_header,
        limits=limits,
        camera=False,
    )
    for _ in cursor.rows():
        pass
    return cursor.observation()


def inspect_png_ihdr(
    prefix: bytes,
    *,
    total_size_bytes: int,
    expected: PngIhdrContract,
    max_total_bytes: int = DEFAULT_MAX_PNG_BYTES,
) -> PngIhdrObservation:
    """Interpret exactly a PNG signature and IHDR chunk, never image payload."""

    if type(prefix) is not bytes or len(prefix) != 33:
        raise TumviFormatError("prefix must be exactly the first 33 PNG bytes")
    total_size = _exact_int(total_size_bytes, field="total_size_bytes", minimum=33)
    maximum = _exact_int(max_total_bytes, field="max_total_bytes", minimum=33)
    if total_size > maximum:
        raise TumviFormatError("PNG total size exceeds max_total_bytes")
    if type(expected) is not PngIhdrContract:
        raise TumviFormatError("expected must be an exact PngIhdrContract")

    violations = _ViolationSet(32)
    if prefix[:8] != _PNG_SIGNATURE:
        violations.add("invalid_png_signature")
    chunk_length = struct.unpack(">I", prefix[8:12])[0]
    chunk_type = prefix[12:16]
    if chunk_length != 13:
        violations.add("invalid_ihdr_length")
    if chunk_type != b"IHDR":
        violations.add("ihdr_not_first")
    width, height = struct.unpack(">II", prefix[16:24])
    bit_depth = prefix[24]
    color_type = prefix[25]
    compression_method = prefix[26]
    filter_method = prefix[27]
    interlace_method = prefix[28]
    recorded_crc = struct.unpack(">I", prefix[29:33])[0]
    computed_crc = zlib.crc32(prefix[12:29]) & 0xFFFFFFFF
    if recorded_crc != computed_crc:
        violations.add("invalid_ihdr_crc")
    if width < 1 or width > _MAX_PNG_DIMENSION or height < 1 or height > _MAX_PNG_DIMENSION:
        violations.add("invalid_png_dimensions")
    legal_depths = _PNG_VALID_BIT_DEPTHS.get(color_type)
    if legal_depths is None or bit_depth not in legal_depths:
        violations.add("invalid_bit_depth_color_type_pair")
    if compression_method != 0:
        violations.add("unsupported_compression_method")
    if filter_method != 0:
        violations.add("unsupported_filter_method")
    if interlace_method not in (0, 1):
        violations.add("invalid_interlace_method")
    if width != expected.width:
        violations.add("width_mismatch")
    if height != expected.height:
        violations.add("height_mismatch")
    if bit_depth != expected.bit_depth:
        violations.add("bit_depth_mismatch")
    result = violations.tuple()
    return PngIhdrObservation(
        total_size_bytes=total_size,
        width=width,
        height=height,
        bit_depth=bit_depth,
        color_type=color_type,
        compression_method=compression_method,
        filter_method=filter_method,
        interlace_method=interlace_method,
        ihdr_crc32=recorded_crc,
        conforms=not result,
        violations=result,
    )

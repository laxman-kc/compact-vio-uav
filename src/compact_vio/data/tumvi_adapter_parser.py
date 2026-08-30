"""Pure, bounded parsers for synthetic TUM-VI CSV fixtures.

This module accepts only an exact, open :class:`io.BytesIO` positioned at byte
zero.  It has no filesystem loader and authenticates neither the origin nor
the scientific meaning of input bytes.  A successful parse consumes each
stream through EOF, leaves it open, and materializes a tuple only within the
row bound frozen by the Gate 1 contract.  On failure the stream remains open,
but its position is deliberately unspecified.

Accounting is exact: total bytes include the header and every LF byte;
physical-line bytes include their trailing LF; row limits count data rows and
exclude the header; minimum-row checks also count data rows.  Reads are
incremental and bounded by the remaining source/contract limits plus one byte.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import InitVar, dataclass, fields

from compact_vio.data.tumvi_adapter_contract import (
    CameraIndexGrammar,
    CameraStreamLayout,
    ColumnGrammar,
    CsvCommonGrammar,
    CsvGrammars,
    CsvStreamGrammar,
    EvidenceIdentity,
    FilenameGrammar,
    ImagePreprocessingBoundary,
    IntervalPolicy,
    LayoutContract,
    NumericLexemeGrammar,
    ObservedPngHeaders,
    PoseReferenceContract,
    ReadinessContract,
    ResourceLimits,
    ResultContract,
    SourceEvidence,
    StereoPolicy,
    TimestampLexemeGrammar,
    TumviAdapterContract,
    TumviAdapterContractError,
)

PARSER_ACCOUNTING_POLICY_ID = (
    "tumvi-synthetic-csv-accounting-total-and-line-bytes-include-lf-"
    "data-rows-exclude-header-exact-bytesio-position-zero-open-at-eof/v1"
)

_CONTRACT_ID = "tumvi-room4-512-16-adapter-contract-v1"
_CONTRACT_SHA256 = "4368580eb601958f1c402ee6f85d3207d9bb41282c51f4dee505482c1a6542d5"
_CONTRACT_PATH = "configs/data/tumvi_room4_512_16_adapter_contract_v1.json"
_SOURCE_SCOPE = "synthetic-fixture-only-origin-not-authenticated/v1"
_SCIENTIFIC_AUTHORITY = "none"
_OUTPUT_SEAL = object()

_TIMESTAMP_PATTERN = re.compile(rb"(?:0|[1-9][0-9]*)")
_NUMERIC_PATTERN = re.compile(rb"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?")
_FILENAME_PATTERN = re.compile(rb"(?:0|[1-9][0-9]*)\.png")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

_CAMERA_HEADER = ("#timestamp [ns]", "filename")
_IMU_HEADER = (
    "#timestamp [ns]",
    "w_RS_S_x [rad s^-1]",
    "w_RS_S_y [rad s^-1]",
    "w_RS_S_z [rad s^-1]",
    "a_RS_S_x [m s^-2]",
    "a_RS_S_y [m s^-2]",
    "a_RS_S_z [m s^-2]",
)
_POSE_HEADER = (
    "#timestamp [ns]",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
    "q_RS_w []",
    "q_RS_x []",
    "q_RS_y []",
    "q_RS_z []",
)
_EXPECTED_PATHS = {
    "cam0": "mav0/cam0/data.csv",
    "cam1": "mav0/cam1/data.csv",
    "imu": "mav0/imu0/data.csv",
    "pose": "mav0/mocap0/data.csv",
}
_EXPECTED_BYTE_LIMITS = {
    "cam0": 98_057,
    "cam1": 98_057,
    "imu": 2_232_296,
    "pose": 1_481_244,
}
_KNOWN_REAL_SOURCE_SHA256 = frozenset(
    {
        "feff54e5a721df968901ae0ec5af1d6ca45c12e758ef8e9e965b812ca87c8d67",
        "4249d4036b3c03c55b709f6f634d975d024999fb017ab3539cfa71580793a3be",
        "073a3e957efa8ff638ea41402cac9654b40897631d566a3ffee090208597db2a",
    }
)
_CONTRACT_RECORD_TYPES = (
    CameraIndexGrammar,
    CameraStreamLayout,
    ColumnGrammar,
    CsvCommonGrammar,
    CsvGrammars,
    CsvStreamGrammar,
    EvidenceIdentity,
    FilenameGrammar,
    ImagePreprocessingBoundary,
    IntervalPolicy,
    LayoutContract,
    NumericLexemeGrammar,
    ObservedPngHeaders,
    PoseReferenceContract,
    ReadinessContract,
    ResourceLimits,
    ResultContract,
    SourceEvidence,
    StereoPolicy,
    TimestampLexemeGrammar,
    TumviAdapterContract,
)


class TumviAdapterParserError(ValueError):
    """Synthetic input violates the exact Gate 1 parser boundary."""


def _require_exact_contract_tree(
    value: object,
    *,
    _seen_ids: set[int] | None = None,
    _node_count: list[int] | None = None,
    _depth: int = 0,
) -> None:
    """Reject foreign objects before any equality or validation callback."""

    if _depth > 32:
        raise TumviAdapterParserError("contract value tree exceeds its fixed depth bound")
    value_type = type(value)
    if value_type is str or value_type is int or value_type is bool or value_type is type(None):
        return
    seen_ids = set() if _seen_ids is None else _seen_ids
    node_count = [0] if _node_count is None else _node_count
    marker = id(value)
    if marker in seen_ids:
        raise TumviAdapterParserError("contract value tree contains a cycle or shared composite")
    seen_ids.add(marker)
    node_count[0] += 1
    if node_count[0] > 2_048:
        raise TumviAdapterParserError("contract value tree exceeds its fixed node bound")
    if value_type is tuple:
        for item in value:
            _require_exact_contract_tree(
                item,
                _seen_ids=seen_ids,
                _node_count=node_count,
                _depth=_depth + 1,
            )
        return
    if not any(value_type is expected for expected in _CONTRACT_RECORD_TYPES):
        raise TumviAdapterParserError("contract contains a foreign nested value type")
    for item in fields(value):
        try:
            nested_value = getattr(value, item.name)
        except AttributeError as exc:
            raise TumviAdapterParserError(
                "contract record is missing a required sealed field"
            ) from exc
        _require_exact_contract_tree(
            nested_value,
            _seen_ids=seen_ids,
            _node_count=node_count,
            _depth=_depth + 1,
        )


def _require_output_seal(seal: object, *, record: str) -> None:
    if seal is not _OUTPUT_SEAL:
        raise TumviAdapterParserError(f"{record} may only be constructed by this parser")


def _exact_timestamp(value: object, *, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 9_223_372_036_854_775_807:
        raise TumviAdapterParserError(f"{field} must be an exact unsigned int64")
    return value


def _exact_text(value: object, *, field: str) -> str:
    if type(value) is not str or not value:
        raise TumviAdapterParserError(f"{field} must be non-empty exact text")
    return value


def _exact_numeric_lexeme(value: object, *, field: str) -> str:
    text = _exact_text(value, field=field)
    try:
        raw = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise TumviAdapterParserError(f"{field} must be ASCII") from exc
    if len(raw) > 128 or _NUMERIC_PATTERN.fullmatch(raw) is None:
        raise TumviAdapterParserError(f"{field} must preserve an exact numeric ASCII lexeme")
    return text


def _exact_filename(value: object, timestamp: int, *, field: str) -> str:
    text = _exact_text(value, field=field)
    try:
        raw = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise TumviAdapterParserError(f"{field} must be ASCII") from exc
    if len(raw) > 23 or _FILENAME_PATTERN.fullmatch(raw) is None:
        raise TumviAdapterParserError(f"{field} must be an exact safe PNG basename lexeme")
    if int(raw[:-4]) != timestamp:
        raise TumviAdapterParserError(f"{field} stem must equal its timestamp token")
    return text


@dataclass(frozen=True, slots=True)
class TumviSyntheticSourceIdentity:
    """Origin-unauthenticated identity computed from one synthetic-only stream."""

    _seal: InitVar[object]
    contract_id: str
    contract_sha256: str
    parser_accounting_policy_id: str
    stream_role: str
    source_path: str
    source_size_bytes: int
    source_sha256: str
    source_scope: str
    scientific_authority: str

    def __post_init__(self, _seal: object) -> None:
        _require_output_seal(_seal, record=type(self).__name__)
        if self.contract_id != _CONTRACT_ID or self.contract_sha256 != _CONTRACT_SHA256:
            raise TumviAdapterParserError("source identity must bind the exact Gate 1 contract")
        if self.parser_accounting_policy_id != PARSER_ACCOUNTING_POLICY_ID:
            raise TumviAdapterParserError("source identity accounting policy mismatch")
        if self.stream_role not in _EXPECTED_PATHS:
            raise TumviAdapterParserError("source identity has an unsupported stream role")
        if self.source_path != _EXPECTED_PATHS[self.stream_role]:
            raise TumviAdapterParserError("source identity path must be role-derived")
        if type(self.source_size_bytes) is not int or self.source_size_bytes < 1:
            raise TumviAdapterParserError("source_size_bytes must be a positive exact integer")
        if self.source_size_bytes > _EXPECTED_BYTE_LIMITS[self.stream_role]:
            raise TumviAdapterParserError("source identity exceeds its role byte limit")
        if (
            type(self.source_sha256) is not str
            or _SHA256_PATTERN.fullmatch(self.source_sha256) is None
        ):
            raise TumviAdapterParserError("source_sha256 must be lowercase hexadecimal")
        if self.source_sha256 in _KNOWN_REAL_SOURCE_SHA256:
            raise TumviAdapterParserError("known inspected real-source identities are prohibited")
        if self.source_scope != _SOURCE_SCOPE or self.scientific_authority != _SCIENTIFIC_AUTHORITY:
            raise TumviAdapterParserError(
                "source identity cannot claim origin or scientific authority"
            )


@dataclass(frozen=True, slots=True)
class TumviCameraIndexRow:
    _seal: InitVar[object]
    stream_role: str
    timestamp_source_label_ns: int
    filename_source_lexeme: str

    def __post_init__(self, _seal: object) -> None:
        _require_output_seal(_seal, record=type(self).__name__)
        if self.stream_role not in ("cam0", "cam1"):
            raise TumviAdapterParserError("camera row role must be cam0 or cam1")
        timestamp = _exact_timestamp(
            self.timestamp_source_label_ns,
            field="timestamp_source_label_ns",
        )
        _exact_filename(self.filename_source_lexeme, timestamp, field="filename_source_lexeme")


@dataclass(frozen=True, slots=True)
class TumviImuRow:
    _seal: InitVar[object]
    timestamp_source_label_ns: int
    w_rs_s_x_source_label_lexeme: str
    w_rs_s_y_source_label_lexeme: str
    w_rs_s_z_source_label_lexeme: str
    a_rs_s_x_source_label_lexeme: str
    a_rs_s_y_source_label_lexeme: str
    a_rs_s_z_source_label_lexeme: str

    def __post_init__(self, _seal: object) -> None:
        _require_output_seal(_seal, record=type(self).__name__)
        _exact_timestamp(self.timestamp_source_label_ns, field="timestamp_source_label_ns")
        for item in fields(self)[1:]:
            _exact_numeric_lexeme(getattr(self, item.name), field=item.name)


@dataclass(frozen=True, slots=True)
class TumviSourceLabeledPoseRow:
    _seal: InitVar[object]
    timestamp_source_label_ns: int
    p_rs_r_x_source_label_lexeme: str
    p_rs_r_y_source_label_lexeme: str
    p_rs_r_z_source_label_lexeme: str
    q_rs_w_source_label_lexeme: str
    q_rs_x_source_label_lexeme: str
    q_rs_y_source_label_lexeme: str
    q_rs_z_source_label_lexeme: str

    def __post_init__(self, _seal: object) -> None:
        _require_output_seal(_seal, record=type(self).__name__)
        _exact_timestamp(self.timestamp_source_label_ns, field="timestamp_source_label_ns")
        for item in fields(self)[1:]:
            _exact_numeric_lexeme(getattr(self, item.name), field=item.name)


@dataclass(frozen=True, slots=True)
class TumviStereoIndexRow:
    _seal: InitVar[object]
    timestamp_source_label_ns: int
    cam0_filename_source_lexeme: str
    cam1_filename_source_lexeme: str

    def __post_init__(self, _seal: object) -> None:
        _require_output_seal(_seal, record=type(self).__name__)
        timestamp = _exact_timestamp(
            self.timestamp_source_label_ns,
            field="timestamp_source_label_ns",
        )
        _exact_filename(
            self.cam0_filename_source_lexeme,
            timestamp,
            field="cam0_filename_source_lexeme",
        )
        _exact_filename(
            self.cam1_filename_source_lexeme,
            timestamp,
            field="cam1_filename_source_lexeme",
        )


def _assert_batch_authority(
    seal: object,
    *,
    record: str,
    contract_id: str,
    contract_sha256: str,
    parser_accounting_policy_id: str,
    source_scope: str,
    scientific_authority: str,
) -> None:
    _require_output_seal(seal, record=record)
    if contract_id != _CONTRACT_ID or contract_sha256 != _CONTRACT_SHA256:
        raise TumviAdapterParserError("batch must bind the exact Gate 1 contract")
    if parser_accounting_policy_id != PARSER_ACCOUNTING_POLICY_ID:
        raise TumviAdapterParserError("batch accounting policy mismatch")
    if source_scope != _SOURCE_SCOPE or scientific_authority != _SCIENTIFIC_AUTHORITY:
        raise TumviAdapterParserError("batch cannot claim origin or scientific authority")


def _exact_row_tuple(value: object, row_type: type, *, field: str) -> tuple:
    if type(value) is not tuple or not value or any(type(item) is not row_type for item in value):
        raise TumviAdapterParserError(f"{field} must be a non-empty exact tuple of sealed rows")
    timestamps = tuple(item.timestamp_source_label_ns for item in value)
    if any(
        current <= previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ):
        raise TumviAdapterParserError(f"{field} timestamps must be strictly increasing")
    return value


@dataclass(frozen=True, slots=True)
class TumviCameraIndexBatch:
    _seal: InitVar[object]
    contract_id: str
    contract_sha256: str
    parser_accounting_policy_id: str
    source_scope: str
    scientific_authority: str
    source: TumviSyntheticSourceIdentity
    rows: tuple[TumviCameraIndexRow, ...]

    def __post_init__(self, _seal: object) -> None:
        _assert_batch_authority(
            _seal,
            record=type(self).__name__,
            contract_id=self.contract_id,
            contract_sha256=self.contract_sha256,
            parser_accounting_policy_id=self.parser_accounting_policy_id,
            source_scope=self.source_scope,
            scientific_authority=self.scientific_authority,
        )
        if type(self.source) is not TumviSyntheticSourceIdentity or self.source.stream_role not in (
            "cam0",
            "cam1",
        ):
            raise TumviAdapterParserError("camera batch requires a sealed camera source identity")
        rows = _exact_row_tuple(self.rows, TumviCameraIndexRow, field="rows")
        if any(row.stream_role != self.source.stream_role for row in rows):
            raise TumviAdapterParserError("camera row roles must equal the source role")
        filenames = tuple(row.filename_source_lexeme for row in rows)
        if len(filenames) != len(set(filenames)):
            raise TumviAdapterParserError("camera filenames must be unique")


@dataclass(frozen=True, slots=True)
class TumviImuBatch:
    _seal: InitVar[object]
    contract_id: str
    contract_sha256: str
    parser_accounting_policy_id: str
    source_scope: str
    scientific_authority: str
    source: TumviSyntheticSourceIdentity
    rows: tuple[TumviImuRow, ...]

    def __post_init__(self, _seal: object) -> None:
        _assert_batch_authority(
            _seal,
            record=type(self).__name__,
            contract_id=self.contract_id,
            contract_sha256=self.contract_sha256,
            parser_accounting_policy_id=self.parser_accounting_policy_id,
            source_scope=self.source_scope,
            scientific_authority=self.scientific_authority,
        )
        if (
            type(self.source) is not TumviSyntheticSourceIdentity
            or self.source.stream_role != "imu"
        ):
            raise TumviAdapterParserError("IMU batch requires the sealed IMU source identity")
        _exact_row_tuple(self.rows, TumviImuRow, field="rows")


@dataclass(frozen=True, slots=True)
class TumviSourceLabeledPoseBatch:
    _seal: InitVar[object]
    contract_id: str
    contract_sha256: str
    parser_accounting_policy_id: str
    source_scope: str
    scientific_authority: str
    source: TumviSyntheticSourceIdentity
    rows: tuple[TumviSourceLabeledPoseRow, ...]

    def __post_init__(self, _seal: object) -> None:
        _assert_batch_authority(
            _seal,
            record=type(self).__name__,
            contract_id=self.contract_id,
            contract_sha256=self.contract_sha256,
            parser_accounting_policy_id=self.parser_accounting_policy_id,
            source_scope=self.source_scope,
            scientific_authority=self.scientific_authority,
        )
        if (
            type(self.source) is not TumviSyntheticSourceIdentity
            or self.source.stream_role != "pose"
        ):
            raise TumviAdapterParserError("pose batch requires the sealed pose source identity")
        _exact_row_tuple(self.rows, TumviSourceLabeledPoseRow, field="rows")


@dataclass(frozen=True, slots=True)
class TumviStereoIndexBatch:
    _seal: InitVar[object]
    contract_id: str
    contract_sha256: str
    parser_accounting_policy_id: str
    source_scope: str
    scientific_authority: str
    cam0_source: TumviSyntheticSourceIdentity
    cam1_source: TumviSyntheticSourceIdentity
    rows: tuple[TumviStereoIndexRow, ...]

    def __post_init__(self, _seal: object) -> None:
        _assert_batch_authority(
            _seal,
            record=type(self).__name__,
            contract_id=self.contract_id,
            contract_sha256=self.contract_sha256,
            parser_accounting_policy_id=self.parser_accounting_policy_id,
            source_scope=self.source_scope,
            scientific_authority=self.scientific_authority,
        )
        for source, role in ((self.cam0_source, "cam0"), (self.cam1_source, "cam1")):
            if type(source) is not TumviSyntheticSourceIdentity or source.stream_role != role:
                raise TumviAdapterParserError("stereo batch requires exact cam0/cam1 identities")
        if (
            self.cam0_source.source_size_bytes != self.cam1_source.source_size_bytes
            or self.cam0_source.source_sha256 != self.cam1_source.source_sha256
        ):
            raise TumviAdapterParserError("stereo source identities must be byte-identical")
        _exact_row_tuple(self.rows, TumviStereoIndexRow, field="rows")


def _require_contract(contract: object) -> TumviAdapterContract:
    if type(contract) is not TumviAdapterContract:
        raise TumviAdapterParserError(
            "contract must be an exact loader-sealed TumviAdapterContract"
        )
    _require_exact_contract_tree(contract)
    if (
        contract.contract_id != _CONTRACT_ID
        or contract.sha256 != _CONTRACT_SHA256
        or contract.path != _CONTRACT_PATH
    ):
        raise TumviAdapterParserError("parser requires the exact frozen Gate 1 contract bytes")
    if (
        type(contract.git_revision) is not str
        or re.fullmatch(r"[0-9a-f]{40}", contract.git_revision) is None
    ):
        raise TumviAdapterParserError("contract revision identity is invalid")

    # Frozen dataclasses can still be forged with ``object.__setattr__``.
    # Re-run every nested Gate 1 invariant before trusting policy values or
    # reproducing the contract identity in parser output.
    try:
        for record, record_type in (
            (contract.source_evidence, SourceEvidence),
            (contract.layout, LayoutContract),
            (contract.csv_grammars, CsvGrammars),
            (contract.stereo_policy, StereoPolicy),
            (contract.interval_policy, IntervalPolicy),
            (contract.pose_reference_contract, PoseReferenceContract),
            (contract.image_preprocessing_boundary, ImagePreprocessingBoundary),
            (contract.resource_limits, ResourceLimits),
            (contract.result_contract, ResultContract),
        ):
            if type(record) is not record_type:
                raise TumviAdapterContractError("nested contract record type mismatch")
            record_type.__post_init__(record)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise TumviAdapterParserError("contract nested invariant validation failed") from exc

    common = contract.csv_grammars.common
    common_values = (
        common.encoding,
        common.utf8_bom,
        common.nul_bytes,
        common.carriage_return_bytes,
        common.line_ending,
        common.final_line_ending,
        common.delimiter,
        common.quoting,
        common.quote_character,
        common.escape_character,
        common.doublequote_escaping,
        common.embedded_newlines,
        common.blank_rows,
        common.comment_data_rows,
        common.field_whitespace_normalization,
        common.header_comparison,
        common.timestamps_strictly_increasing,
    )
    if common_values != (
        "utf-8",
        "forbidden",
        "forbidden",
        "forbidden",
        "lf-only",
        "required",
        ",",
        "forbidden",
        None,
        None,
        False,
        "forbidden",
        "forbidden",
        "forbidden",
        "forbidden",
        "exact-raw-cell-no-whitespace-normalization/v1",
        True,
    ):
        raise TumviAdapterParserError(
            "contract CSV common grammar is not the frozen Gate 1 grammar"
        )

    timestamp = contract.csv_grammars.timestamp_lexeme
    numeric = contract.csv_grammars.numeric_lexeme
    if (
        timestamp.fullmatch_regex != r"(?:0|[1-9][0-9]*)"
        or timestamp.minimum_value != 0
        or timestamp.maximum_value != 9_223_372_036_854_775_807
        or timestamp.maximum_token_bytes != 19
        or numeric.fullmatch_regex
        != r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))(?:[eE][+-]?[0-9]+)?"
        or numeric.maximum_token_bytes != 128
        or numeric.numeric_conversion is not None
    ):
        raise TumviAdapterParserError("contract token grammar is not the frozen Gate 1 grammar")

    camera = contract.csv_grammars.camera_index
    imu = contract.csv_grammars.imu_stream
    pose = contract.csv_grammars.pose_reference_stream
    camera_layout = tuple((item.role, item.index_path) for item in contract.layout.camera_streams)
    if (
        camera_layout != (("cam0", _EXPECTED_PATHS["cam0"]), ("cam1", _EXPECTED_PATHS["cam1"]))
        or contract.layout.imu_stream_path != _EXPECTED_PATHS["imu"]
        or contract.layout.pose_reference_stream_path != _EXPECTED_PATHS["pose"]
        or contract.layout.real_payload_access != "not_authorized_by_contract"
        or contract.layout.calibration_access != "not_authorized"
        or camera.roles != ("cam0", "cam1")
        or camera.header != _CAMERA_HEADER
        or camera.row_arity != 2
        or camera.minimum_data_rows != 1
        or not camera.filename_stem_equals_timestamp
        or not camera.filenames_unique
        or imu.header != _IMU_HEADER
        or imu.row_arity != 7
        or imu.minimum_data_rows != 1
        or pose.header != _POSE_HEADER
        or pose.row_arity != 8
        or pose.minimum_data_rows != 1
    ):
        raise TumviAdapterParserError("contract layouts or stream grammars are not frozen")

    limits = contract.resource_limits
    if (
        limits.maximum_csv_rows_per_file != 1_000_000
        or limits.maximum_csv_line_bytes != 1_048_576
        or limits.maximum_csv_columns != 8
        or dict(limits.maximum_csv_bytes_by_role) != _EXPECTED_BYTE_LIMITS
        or not limits.streaming_required
        or not limits.fail_on_limit
        or limits.maximum_image_bytes_read != 0
    ):
        raise TumviAdapterParserError("contract resource limits are not frozen")
    if (
        not contract.stereo_policy.exact_index_bytes_required
        or not contract.stereo_policy.exact_ordered_timestamp_filename_rows_required
        or contract.stereo_policy.monocular_fallback
    ):
        raise TumviAdapterParserError("contract stereo policy is not strict")
    readiness = contract.result_contract.readiness
    if any(getattr(readiness, item.name) is not False for item in fields(readiness)):
        raise TumviAdapterParserError("parser contract must not claim operational readiness")
    if contract.result_contract.scientific_authority != _SCIENTIFIC_AUTHORITY:
        raise TumviAdapterParserError("parser contract must have no scientific authority")
    return contract


def _derived_path(contract: TumviAdapterContract, role: str, supplied: object) -> str:
    if type(supplied) is not str:
        raise TumviAdapterParserError("source_path must be exact text")
    if role in ("cam0", "cam1"):
        derived = next(
            item.index_path for item in contract.layout.camera_streams if item.role == role
        )
    elif role == "imu":
        derived = contract.layout.imu_stream_path
    else:
        derived = contract.layout.pose_reference_stream_path
    if supplied != derived:
        raise TumviAdapterParserError(f"source_path must equal the contract-derived {role} path")
    return derived


class _BoundedLines:
    __slots__ = (
        "_digest",
        "_expected_sha256",
        "_expected_size",
        "_finished",
        "_line_limit",
        "_role_limit",
        "_source",
        "_total",
    )

    def __init__(
        self,
        source: object,
        *,
        role: str,
        expected_size: object,
        expected_sha256: object,
        line_limit: int,
        role_limit: int,
    ) -> None:
        if type(source) is not io.BytesIO:
            raise TumviAdapterParserError("source must be an exact io.BytesIO")
        if source.closed:
            raise TumviAdapterParserError("source must be open")
        if source.tell() != 0:
            raise TumviAdapterParserError("source must be positioned at byte zero")
        if type(expected_size) is not int or expected_size < 1:
            raise TumviAdapterParserError(
                "expected_source_size_bytes must be a positive exact integer"
            )
        if expected_size > role_limit:
            raise TumviAdapterParserError(f"expected {role} size exceeds the contract limit")
        if type(expected_sha256) is not str or _SHA256_PATTERN.fullmatch(expected_sha256) is None:
            raise TumviAdapterParserError("expected_source_sha256 must be lowercase hexadecimal")
        if expected_sha256 in _KNOWN_REAL_SOURCE_SHA256:
            raise TumviAdapterParserError("known inspected real-source identity is prohibited")
        self._source = source
        self._expected_size = expected_size
        self._expected_sha256 = expected_sha256
        self._line_limit = line_limit
        self._role_limit = role_limit
        self._total = 0
        self._digest = hashlib.sha256()
        self._finished = False

    @property
    def total(self) -> int:
        return self._total

    @property
    def sha256(self) -> str:
        return self._digest.hexdigest()

    def next_line(self) -> bytes | None:
        if self._finished:
            raise TumviAdapterParserError("source reader cannot be reused after EOF")
        remaining = min(self._expected_size, self._role_limit) - self._total
        read_limit = min(self._line_limit, max(remaining, 0)) + 1
        raw = self._source.readline(read_limit)
        if type(raw) is not bytes:
            raise TumviAdapterParserError("BytesIO.readline returned a non-bytes value")
        if raw == b"":
            self._finished = True
            return None
        self._total += len(raw)
        self._digest.update(raw)
        if self._total > self._expected_size:
            raise TumviAdapterParserError("source exceeds expected_source_size_bytes")
        if self._total > self._role_limit:
            raise TumviAdapterParserError("source exceeds its role byte limit")
        if len(raw) > self._line_limit:
            raise TumviAdapterParserError(
                "physical line exceeds maximum_csv_line_bytes including LF"
            )
        if not raw.endswith(b"\n"):
            raise TumviAdapterParserError("every physical line must end with LF")
        if b"\r" in raw:
            raise TumviAdapterParserError("carriage-return bytes are forbidden")
        if b"\x00" in raw:
            raise TumviAdapterParserError("NUL bytes are forbidden")
        if b'"' in raw:
            raise TumviAdapterParserError("quoted CSV is forbidden")
        if b"\xef\xbb\xbf" in raw:
            raise TumviAdapterParserError("UTF-8 BOM bytes are forbidden")
        if any(byte > 0x7F for byte in raw):
            raise TumviAdapterParserError("CSV headers and lexemes must be ASCII")
        if raw.count(b",") + 1 > 8:
            raise TumviAdapterParserError("physical row exceeds maximum_csv_columns")
        return raw

    def finish(self) -> None:
        if not self._finished:
            raise TumviAdapterParserError("source must be consumed through EOF before finalization")
        if self._source.closed:
            raise TumviAdapterParserError("parser must not close its source")
        if self._source.tell() != self._total:
            raise TumviAdapterParserError(
                "successful parsing must leave its exact source positioned at EOF"
            )
        if self._total != self._expected_size:
            raise TumviAdapterParserError("source size does not equal expected_source_size_bytes")
        if self.sha256 != self._expected_sha256:
            raise TumviAdapterParserError("source SHA-256 does not equal expected_source_sha256")


def _header(reader: _BoundedLines, expected: tuple[str, ...]) -> None:
    raw = reader.next_line()
    if raw is None:
        raise TumviAdapterParserError("CSV source is empty")
    if raw[:-1] != b",".join(item.encode("ascii") for item in expected):
        raise TumviAdapterParserError("CSV header is not an exact raw-cell match")


def _data_body(raw: bytes, *, arity: int) -> tuple[bytes, ...]:
    body = raw[:-1]
    if not body:
        raise TumviAdapterParserError("blank data rows are forbidden")
    if body.startswith(b"#"):
        raise TumviAdapterParserError("comment data rows are forbidden")
    cells = tuple(body.split(b","))
    if len(cells) != arity:
        raise TumviAdapterParserError("data row arity does not equal the frozen header arity")
    return cells


def _timestamp(raw: bytes, *, previous: int | None) -> int:
    if len(raw) > 19 or _TIMESTAMP_PATTERN.fullmatch(raw) is None:
        raise TumviAdapterParserError("timestamp token violates the exact unsigned-decimal grammar")
    value = int(raw)
    if value > 9_223_372_036_854_775_807:
        raise TumviAdapterParserError("timestamp token exceeds unsigned int64 contract maximum")
    if previous is not None and value <= previous:
        raise TumviAdapterParserError("timestamps must be strictly increasing and unique")
    return value


def _numeric(raw: bytes) -> str:
    if len(raw) > 128 or _NUMERIC_PATTERN.fullmatch(raw) is None:
        raise TumviAdapterParserError(
            "numeric token violates the exact finite ASCII lexeme grammar"
        )
    return raw.decode("ascii")


def _camera_values(
    raw: bytes,
    *,
    previous: int | None,
    seen_filenames: set[str],
) -> tuple[int, str]:
    timestamp_raw, filename_raw = _data_body(raw, arity=2)
    timestamp = _timestamp(timestamp_raw, previous=previous)
    if len(filename_raw) > 23 or _FILENAME_PATTERN.fullmatch(filename_raw) is None:
        raise TumviAdapterParserError("filename token violates the exact safe PNG basename grammar")
    filename = filename_raw.decode("ascii")
    if int(filename_raw[:-4]) != timestamp:
        raise TumviAdapterParserError("filename stem must equal the row timestamp token")
    if filename in seen_filenames:
        raise TumviAdapterParserError("camera filenames must be unique")
    seen_filenames.add(filename)
    return timestamp, filename


def _identity(
    contract: TumviAdapterContract,
    *,
    role: str,
    source_path: str,
    reader: _BoundedLines,
) -> TumviSyntheticSourceIdentity:
    return TumviSyntheticSourceIdentity(
        _seal=_OUTPUT_SEAL,
        contract_id=contract.contract_id,
        contract_sha256=contract.sha256,
        parser_accounting_policy_id=PARSER_ACCOUNTING_POLICY_ID,
        stream_role=role,
        source_path=source_path,
        source_size_bytes=reader.total,
        source_sha256=reader.sha256,
        source_scope=_SOURCE_SCOPE,
        scientific_authority=_SCIENTIFIC_AUTHORITY,
    )


def _batch_authority(contract: TumviAdapterContract) -> dict[str, str]:
    return {
        "contract_id": contract.contract_id,
        "contract_sha256": contract.sha256,
        "parser_accounting_policy_id": PARSER_ACCOUNTING_POLICY_ID,
        "source_scope": _SOURCE_SCOPE,
        "scientific_authority": _SCIENTIFIC_AUTHORITY,
    }


def parse_tumvi_camera_index(
    source: object,
    *,
    contract: TumviAdapterContract,
    stream_role: str,
    source_path: str,
    expected_source_size_bytes: int,
    expected_source_sha256: str,
) -> TumviCameraIndexBatch:
    """Parse one synthetic camera index without opening any path or image."""

    contract = _require_contract(contract)
    if type(stream_role) is not str or stream_role not in ("cam0", "cam1"):
        raise TumviAdapterParserError("stream_role must be exact text cam0 or cam1")
    derived_path = _derived_path(contract, stream_role, source_path)
    limits = contract.resource_limits
    reader = _BoundedLines(
        source,
        role=stream_role,
        expected_size=expected_source_size_bytes,
        expected_sha256=expected_source_sha256,
        line_limit=limits.maximum_csv_line_bytes,
        role_limit=dict(limits.maximum_csv_bytes_by_role)[stream_role],
    )
    _header(reader, contract.csv_grammars.camera_index.header)
    rows: list[TumviCameraIndexRow] = []
    previous: int | None = None
    seen: set[str] = set()
    while (raw := reader.next_line()) is not None:
        if len(rows) >= limits.maximum_csv_rows_per_file:
            raise TumviAdapterParserError("data-row count exceeds maximum_csv_rows_per_file")
        timestamp, filename = _camera_values(raw, previous=previous, seen_filenames=seen)
        rows.append(
            TumviCameraIndexRow(
                _seal=_OUTPUT_SEAL,
                stream_role=stream_role,
                timestamp_source_label_ns=timestamp,
                filename_source_lexeme=filename,
            )
        )
        previous = timestamp
    if len(rows) < contract.csv_grammars.camera_index.minimum_data_rows:
        raise TumviAdapterParserError("camera index has fewer than minimum_data_rows")
    reader.finish()
    return TumviCameraIndexBatch(
        _seal=_OUTPUT_SEAL,
        **_batch_authority(contract),
        source=_identity(contract, role=stream_role, source_path=derived_path, reader=reader),
        rows=tuple(rows),
    )


def _parse_numeric_rows(
    source: object,
    *,
    contract: TumviAdapterContract,
    role: str,
    source_path: str,
    expected_source_size_bytes: int,
    expected_source_sha256: str,
) -> tuple[_BoundedLines, tuple[tuple[int, tuple[str, ...]], ...]]:
    grammar = (
        contract.csv_grammars.imu_stream
        if role == "imu"
        else contract.csv_grammars.pose_reference_stream
    )
    limits = contract.resource_limits
    reader = _BoundedLines(
        source,
        role=role,
        expected_size=expected_source_size_bytes,
        expected_sha256=expected_source_sha256,
        line_limit=limits.maximum_csv_line_bytes,
        role_limit=dict(limits.maximum_csv_bytes_by_role)[role],
    )
    _header(reader, grammar.header)
    rows: list[tuple[int, tuple[str, ...]]] = []
    previous: int | None = None
    while (raw := reader.next_line()) is not None:
        if len(rows) >= limits.maximum_csv_rows_per_file:
            raise TumviAdapterParserError("data-row count exceeds maximum_csv_rows_per_file")
        cells = _data_body(raw, arity=grammar.row_arity)
        timestamp = _timestamp(cells[0], previous=previous)
        rows.append((timestamp, tuple(_numeric(cell) for cell in cells[1:])))
        previous = timestamp
    if len(rows) < grammar.minimum_data_rows:
        raise TumviAdapterParserError(f"{role} stream has fewer than minimum_data_rows")
    reader.finish()
    return reader, tuple(rows)


def parse_tumvi_imu_stream(
    source: object,
    *,
    contract: TumviAdapterContract,
    source_path: str,
    expected_source_size_bytes: int,
    expected_source_sha256: str,
) -> TumviImuBatch:
    """Parse synthetic IMU source-label lexemes without numeric conversion."""

    contract = _require_contract(contract)
    derived_path = _derived_path(contract, "imu", source_path)
    reader, parsed = _parse_numeric_rows(
        source,
        contract=contract,
        role="imu",
        source_path=derived_path,
        expected_source_size_bytes=expected_source_size_bytes,
        expected_source_sha256=expected_source_sha256,
    )
    output_fields = (
        "w_rs_s_x_source_label_lexeme",
        "w_rs_s_y_source_label_lexeme",
        "w_rs_s_z_source_label_lexeme",
        "a_rs_s_x_source_label_lexeme",
        "a_rs_s_y_source_label_lexeme",
        "a_rs_s_z_source_label_lexeme",
    )
    rows = tuple(
        TumviImuRow(
            _seal=_OUTPUT_SEAL,
            timestamp_source_label_ns=timestamp,
            **dict(zip(output_fields, values, strict=True)),
        )
        for timestamp, values in parsed
    )
    return TumviImuBatch(
        _seal=_OUTPUT_SEAL,
        **_batch_authority(contract),
        source=_identity(contract, role="imu", source_path=derived_path, reader=reader),
        rows=rows,
    )


def parse_tumvi_pose_reference_stream(
    source: object,
    *,
    contract: TumviAdapterContract,
    source_path: str,
    expected_source_size_bytes: int,
    expected_source_sha256: str,
) -> TumviSourceLabeledPoseBatch:
    """Parse pose-header-labelled lexemes without assigning pose semantics."""

    contract = _require_contract(contract)
    derived_path = _derived_path(contract, "pose", source_path)
    reader, parsed = _parse_numeric_rows(
        source,
        contract=contract,
        role="pose",
        source_path=derived_path,
        expected_source_size_bytes=expected_source_size_bytes,
        expected_source_sha256=expected_source_sha256,
    )
    output_fields = (
        "p_rs_r_x_source_label_lexeme",
        "p_rs_r_y_source_label_lexeme",
        "p_rs_r_z_source_label_lexeme",
        "q_rs_w_source_label_lexeme",
        "q_rs_x_source_label_lexeme",
        "q_rs_y_source_label_lexeme",
        "q_rs_z_source_label_lexeme",
    )
    rows = tuple(
        TumviSourceLabeledPoseRow(
            _seal=_OUTPUT_SEAL,
            timestamp_source_label_ns=timestamp,
            **dict(zip(output_fields, values, strict=True)),
        )
        for timestamp, values in parsed
    )
    return TumviSourceLabeledPoseBatch(
        _seal=_OUTPUT_SEAL,
        **_batch_authority(contract),
        source=_identity(contract, role="pose", source_path=derived_path, reader=reader),
        rows=rows,
    )


def parse_tumvi_stereo_indexes(
    cam0_source: object,
    cam1_source: object,
    *,
    contract: TumviAdapterContract,
    cam0_source_path: str,
    cam1_source_path: str,
    cam0_expected_source_size_bytes: int,
    cam0_expected_source_sha256: str,
    cam1_expected_source_size_bytes: int,
    cam1_expected_source_sha256: str,
) -> TumviStereoIndexBatch:
    """Parse only byte-identical cam0/cam1 synthetic index rows in lockstep."""

    contract = _require_contract(contract)
    if cam0_source is cam1_source:
        raise TumviAdapterParserError("stereo parsing requires two distinct exact BytesIO sources")
    cam0_path = _derived_path(contract, "cam0", cam0_source_path)
    cam1_path = _derived_path(contract, "cam1", cam1_source_path)
    if (
        type(cam0_expected_source_size_bytes) is not int
        or type(cam1_expected_source_size_bytes) is not int
        or type(cam0_expected_source_sha256) is not str
        or type(cam1_expected_source_sha256) is not str
    ):
        raise TumviAdapterParserError("stereo expected identities must use exact int/string types")
    if (
        cam0_expected_source_size_bytes != cam1_expected_source_size_bytes
        or cam0_expected_source_sha256 != cam1_expected_source_sha256
    ):
        raise TumviAdapterParserError("stereo expected source identities must be identical")
    limits = contract.resource_limits
    role_limits = dict(limits.maximum_csv_bytes_by_role)
    cam0 = _BoundedLines(
        cam0_source,
        role="cam0",
        expected_size=cam0_expected_source_size_bytes,
        expected_sha256=cam0_expected_source_sha256,
        line_limit=limits.maximum_csv_line_bytes,
        role_limit=role_limits["cam0"],
    )
    cam1 = _BoundedLines(
        cam1_source,
        role="cam1",
        expected_size=cam1_expected_source_size_bytes,
        expected_sha256=cam1_expected_source_sha256,
        line_limit=limits.maximum_csv_line_bytes,
        role_limit=role_limits["cam1"],
    )
    raw0 = cam0.next_line()
    raw1 = cam1.next_line()
    if raw0 is None or raw1 is None or raw0 != raw1:
        raise TumviAdapterParserError("stereo headers must be present and byte-identical")
    expected_header = b",".join(item.encode("ascii") for item in _CAMERA_HEADER) + b"\n"
    if raw0 != expected_header:
        raise TumviAdapterParserError("stereo header is not the exact frozen raw header")

    rows: list[TumviStereoIndexRow] = []
    previous: int | None = None
    seen: set[str] = set()
    while True:
        raw0 = cam0.next_line()
        raw1 = cam1.next_line()
        if raw0 is None or raw1 is None:
            if raw0 is not None or raw1 is not None:
                raise TumviAdapterParserError("stereo sources reached EOF at different bytes")
            break
        if raw0 != raw1:
            raise TumviAdapterParserError("stereo index sources are not byte-identical")
        if len(rows) >= limits.maximum_csv_rows_per_file:
            raise TumviAdapterParserError("data-row count exceeds maximum_csv_rows_per_file")
        timestamp, filename = _camera_values(raw0, previous=previous, seen_filenames=seen)
        rows.append(
            TumviStereoIndexRow(
                _seal=_OUTPUT_SEAL,
                timestamp_source_label_ns=timestamp,
                cam0_filename_source_lexeme=filename,
                cam1_filename_source_lexeme=filename,
            )
        )
        previous = timestamp
    if len(rows) < contract.csv_grammars.camera_index.minimum_data_rows:
        raise TumviAdapterParserError("stereo indexes have fewer than minimum_data_rows")
    cam0.finish()
    cam1.finish()
    return TumviStereoIndexBatch(
        _seal=_OUTPUT_SEAL,
        **_batch_authority(contract),
        cam0_source=_identity(contract, role="cam0", source_path=cam0_path, reader=cam0),
        cam1_source=_identity(contract, role="cam1", source_path=cam1_path, reader=cam1),
        rows=tuple(rows),
    )


__all__ = [
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
]

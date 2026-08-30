"""Strict, non-executable contract for a future TUM-VI-specific adapter.

Loading this record validates only committed policy and evidence identities.
It never opens the ignored dataset tree, calibration, image payloads, or model
code, and a valid contract deliberately leaves every operational readiness
flag false.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, fields, is_dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_RECORD_TYPE = "tumvi_adapter_contract"
_SCHEMA_VERSION = "1.0.0"
_CONTRACT_ID = "tumvi-room4-512-16-adapter-contract-v1"
_SCOPE = "synthetic-grammar-record-and-coverage-policy-only-no-real-payload-access/v1"
_CONTRACT_PATH = "configs/data/tumvi_room4_512_16_adapter_contract_v1.json"
_MAX_TRACKED_FILE_BYTES = 1_048_576
_CONSTRUCTION_SEAL = object()


class TumviAdapterContractError(ValueError):
    """The checked adapter contract or one of its tracked identities is invalid."""


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceEvidence:
    candidate: EvidenceIdentity
    compatibility_slice_receipt: EvidenceIdentity
    format_inspection_spec: EvidenceIdentity
    format_inspection_receipt: EvidenceIdentity
    format_inspection_report: EvidenceIdentity
    rejected_euroc_adapter: EvidenceIdentity

    def __post_init__(self) -> None:
        _assert_constructed_exact(self, _EXPECTED_EVIDENCE, field="SourceEvidence")


@dataclass(frozen=True, slots=True)
class CameraStreamLayout:
    role: str
    index_path: str
    image_directory: str


@dataclass(frozen=True, slots=True)
class LayoutContract:
    sequence_directory_name: str
    camera_streams: tuple[CameraStreamLayout, ...]
    imu_stream_path: str
    pose_reference_stream_path: str
    excluded_prefixes: tuple[str, ...]
    calibration_access: str
    real_payload_access: str

    def __post_init__(self) -> None:
        _assert_constructed_exact(self, _EXPECTED_LAYOUT, field="LayoutContract")


@dataclass(frozen=True, slots=True)
class CsvCommonGrammar:
    encoding: str
    utf8_bom: str
    nul_bytes: str
    carriage_return_bytes: str
    line_ending: str
    final_line_ending: str
    delimiter: str
    quoting: str
    quote_character: None
    escape_character: None
    doublequote_escaping: bool
    embedded_newlines: str
    blank_rows: str
    comment_data_rows: str
    field_whitespace_normalization: str
    header_comparison: str
    timestamps_strictly_increasing: bool


@dataclass(frozen=True, slots=True)
class TimestampLexemeGrammar:
    charset: str
    whitespace: str
    fullmatch_regex: str
    minimum_value: int
    maximum_value: int
    maximum_token_bytes: int
    output_representation: str


@dataclass(frozen=True, slots=True)
class NumericLexemeGrammar:
    charset: str
    whitespace: str
    fullmatch_regex: str
    decimal_separator: str
    exponent_markers: tuple[str, ...]
    nonfinite_literals: str
    maximum_token_bytes: int
    output_representation: str
    numeric_conversion: None


@dataclass(frozen=True, slots=True)
class FilenameGrammar:
    charset: str
    case_sensitive: bool
    whitespace: str
    fullmatch_regex: str
    stem_minimum_value: int
    stem_maximum_value: int
    maximum_token_bytes: int
    path_separators: str
    output_representation: str


@dataclass(frozen=True, slots=True)
class ColumnGrammar:
    source_header: str
    lexeme_grammar: str
    output_field: str


@dataclass(frozen=True, slots=True)
class CameraIndexGrammar:
    roles: tuple[str, ...]
    header: tuple[str, ...]
    row_arity: int
    minimum_data_rows: int
    stream_role_output_field: str
    column_grammars: tuple[ColumnGrammar, ...]
    output_fields: tuple[str, ...]
    filename_grammar: FilenameGrammar
    filename_stem_equals_timestamp: bool
    filenames_unique: bool


@dataclass(frozen=True, slots=True)
class CsvStreamGrammar:
    header: tuple[str, ...]
    row_arity: int
    minimum_data_rows: int
    column_grammars: tuple[ColumnGrammar, ...]
    output_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CsvGrammars:
    common: CsvCommonGrammar
    timestamp_lexeme: TimestampLexemeGrammar
    numeric_lexeme: NumericLexemeGrammar
    camera_index: CameraIndexGrammar
    imu_stream: CsvStreamGrammar
    pose_reference_stream: CsvStreamGrammar

    def __post_init__(self) -> None:
        _assert_constructed_exact(self, _EXPECTED_CSV_GRAMMARS, field="CsvGrammars")


@dataclass(frozen=True, slots=True)
class StereoPolicy:
    exact_index_bytes_required: bool
    exact_ordered_timestamp_filename_rows_required: bool
    require_each_filename_once_per_index: bool
    full_indexed_image_existence_required_before_real_execution: bool
    monocular_fallback: bool

    def __post_init__(self) -> None:
        _assert_constructed_exact(self, _EXPECTED_STEREO_POLICY, field="StereoPolicy")


@dataclass(frozen=True, slots=True)
class IntervalPolicy:
    coverage_interval: str
    comparison_semantics: str
    outside_camera_timestamp_action: str
    segment_rule: None
    minimum_frames_per_structural_segment: None
    imu_window: str
    require_nonempty_imu_window: bool
    clock_offset_ns: None
    maximum_camera_gap_ns: None
    maximum_imu_gap_ns: None
    maximum_pose_gap_ns: None
    operational_eligibility: str
    segment_construction_ready: bool
    pose_at_camera_timestamp: str
    allow_timestamp_shift: bool
    allow_clock_correction: bool
    allow_extrapolation: bool
    allow_resampling: bool

    def __post_init__(self) -> None:
        _assert_constructed_exact(self, _EXPECTED_INTERVAL_POLICY, field="IntervalPolicy")


@dataclass(frozen=True, slots=True)
class PoseReferenceContract:
    record_name: str
    fields: tuple[str, ...]
    field_semantics: str
    reference_role: str
    velocity_fields: str
    gyroscope_bias_fields: str
    accelerometer_bias_fields: str
    quaternion_norm_policy: None
    normalization_policy: None
    interpolation_policy: None
    maximum_interpolation_bracket_ns: None
    extrapolation: str
    ground_truth_ready: bool

    def __post_init__(self) -> None:
        _assert_constructed_exact(
            self,
            _EXPECTED_POSE_REFERENCE,
            field="PoseReferenceContract",
        )


@dataclass(frozen=True, slots=True)
class ObservedPngHeaders:
    file_count: int
    interpreted_bytes_per_file: int
    width_px: int
    height_px: int
    bit_depth: int
    color_type: int
    standard_id: str
    standard_url: str


@dataclass(frozen=True, slots=True)
class ImagePreprocessingBoundary:
    observed_selected_png_headers: ObservedPngHeaders
    full_indexed_image_existence_verified: bool
    whole_file_png_validity_verified: bool
    decodability_verified: bool
    decoder: None
    decoded_dtype: None
    sample_range_mapping: None
    channel_policy: None
    normalization: None
    preprocessing_ready: bool
    image_bytes_authorized: int
    permitted_output: str

    def __post_init__(self) -> None:
        _assert_constructed_exact(
            self,
            _EXPECTED_IMAGE_BOUNDARY,
            field="ImagePreprocessingBoundary",
        )


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    maximum_csv_rows_per_file: int
    maximum_csv_line_bytes: int
    maximum_csv_columns: int
    maximum_csv_bytes_by_role: tuple[tuple[str, int], ...]
    maximum_image_bytes_read: int
    streaming_required: bool
    fail_on_limit: bool

    def __post_init__(self) -> None:
        _assert_resource_limits(self)


@dataclass(frozen=True, slots=True)
class ReadinessContract:
    real_payload_execution_authorized: bool
    adapter_implemented: bool
    adapter_ready: bool
    calibration_ready: bool
    clock_mapping_ready: bool
    pose_semantics_ready: bool
    ground_truth_ready: bool
    png_decode_ready: bool
    preprocessing_ready: bool
    full_image_population_ready: bool
    segment_construction_ready: bool
    dataset_selected: bool
    membership_assigned: bool
    model_access_authorized: bool

    def __post_init__(self) -> None:
        _assert_constructed_exact(self, _EXPECTED_READINESS, field="ReadinessContract")


@dataclass(frozen=True, slots=True)
class ResultContract:
    contract_validation_outcomes: tuple[str, ...]
    record_outputs: tuple[tuple[str, tuple[str, ...]], ...]
    readiness: ReadinessContract
    scientific_authority: str
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        _assert_result_contract(self)


@dataclass(frozen=True, slots=True)
class TumviAdapterContract:
    _seal: InitVar[object]
    path: str
    sha256: str
    git_revision: str
    contract_id: str
    source_evidence: SourceEvidence
    layout: LayoutContract
    csv_grammars: CsvGrammars
    stereo_policy: StereoPolicy
    interval_policy: IntervalPolicy
    pose_reference_contract: PoseReferenceContract
    image_preprocessing_boundary: ImagePreprocessingBoundary
    resource_limits: ResourceLimits
    result_contract: ResultContract

    def __post_init__(self, _seal: object) -> None:
        if _seal is not _CONSTRUCTION_SEAL:
            raise TumviAdapterContractError(
                "TumviAdapterContract may only be constructed by the strict loader"
            )
        _assert_top_level_contract(self)


_EXPECTED_EVIDENCE = {
    "candidate": {
        "path": "configs/data/tumvi_room4_512_16_candidate_v1.json",
        "sha256": "0de942674afcadd2f768385a82c52b8cb65eea14d5e8c4d17dc9e48262023740",
    },
    "compatibility_slice_receipt": {
        "path": (
            "governance/datasets/acquisitions/"
            "tumvi-room4-512-16-compatibility-slice-2026-08-29.receipt.json"
        ),
        "sha256": "a60402b91d3fcd8fa893ee3d15bd7a4314ac60cfbee22254cf40bdd97134a820",
    },
    "format_inspection_spec": {
        "path": "configs/data/tumvi_room4_512_16_format_inspection_v1.json",
        "sha256": "e8dd0bc98c7be85fed6d92d319bafec75c9f658584ea83d17ac93c6f47bdf1a7",
    },
    "format_inspection_receipt": {
        "path": (
            "governance/datasets/acquisitions/"
            "tumvi-room4-512-16-format-inspection-2026-08-29.receipt.json"
        ),
        "sha256": "30697326550331146f676c88ad5a50756701c91e57084e0ff7178e9d3fbb7846",
    },
    "format_inspection_report": {
        "path": "reports/tumvi-room4-512-16-format-inspection-2026-08-29.md",
        "sha256": "8048a399d611051e807c9824cdb141a5e6db1bcf77f9bd197483223fe887ef30",
    },
    "rejected_euroc_adapter": {
        "path": "src/compact_vio/data/euroc.py",
        "sha256": "bfcddb06e7516d148253e8db38a7247ce51064ef13c28b934cdbb3980fc238fd",
    },
}

_EXPECTED_LAYOUT = {
    "sequence_directory_name": "dataset-room4_512_16",
    "camera_streams": [
        {
            "role": "cam0",
            "index_path": "mav0/cam0/data.csv",
            "image_directory": "mav0/cam0/data",
        },
        {
            "role": "cam1",
            "index_path": "mav0/cam1/data.csv",
            "image_directory": "mav0/cam1/data",
        },
    ],
    "imu_stream_path": "mav0/imu0/data.csv",
    "pose_reference_stream_path": "mav0/mocap0/data.csv",
    "excluded_prefixes": ["dso"],
    "calibration_access": "not_authorized",
    "real_payload_access": "not_authorized_by_contract",
}

_CAMERA_HEADER = ["#timestamp [ns]", "filename"]
_IMU_HEADER = [
    "#timestamp [ns]",
    "w_RS_S_x [rad s^-1]",
    "w_RS_S_y [rad s^-1]",
    "w_RS_S_z [rad s^-1]",
    "a_RS_S_x [m s^-2]",
    "a_RS_S_y [m s^-2]",
    "a_RS_S_z [m s^-2]",
]
_POSE_HEADER = [
    "#timestamp [ns]",
    "p_RS_R_x [m]",
    "p_RS_R_y [m]",
    "p_RS_R_z [m]",
    "q_RS_w []",
    "q_RS_x []",
    "q_RS_y []",
    "q_RS_z []",
]
_IMU_OUTPUT_FIELDS = [
    "timestamp_source_label_ns",
    "w_rs_s_x_source_label_lexeme",
    "w_rs_s_y_source_label_lexeme",
    "w_rs_s_z_source_label_lexeme",
    "a_rs_s_x_source_label_lexeme",
    "a_rs_s_y_source_label_lexeme",
    "a_rs_s_z_source_label_lexeme",
]
_POSE_OUTPUT_FIELDS = [
    "timestamp_source_label_ns",
    "p_rs_r_x_source_label_lexeme",
    "p_rs_r_y_source_label_lexeme",
    "p_rs_r_z_source_label_lexeme",
    "q_rs_w_source_label_lexeme",
    "q_rs_x_source_label_lexeme",
    "q_rs_y_source_label_lexeme",
    "q_rs_z_source_label_lexeme",
]
_IMU_COLUMN_GRAMMARS = [
    {
        "source_header": source_header,
        "lexeme_grammar": "timestamp_lexeme" if index == 0 else "numeric_lexeme",
        "output_field": _IMU_OUTPUT_FIELDS[index],
    }
    for index, source_header in enumerate(_IMU_HEADER)
]
_POSE_COLUMN_GRAMMARS = [
    {
        "source_header": source_header,
        "lexeme_grammar": "timestamp_lexeme" if index == 0 else "numeric_lexeme",
        "output_field": _POSE_OUTPUT_FIELDS[index],
    }
    for index, source_header in enumerate(_POSE_HEADER)
]
_EXPECTED_CSV_GRAMMARS = {
    "common": {
        "encoding": "utf-8",
        "utf8_bom": "forbidden",
        "nul_bytes": "forbidden",
        "carriage_return_bytes": "forbidden",
        "line_ending": "lf-only",
        "final_line_ending": "required",
        "delimiter": ",",
        "quoting": "forbidden",
        "quote_character": None,
        "escape_character": None,
        "doublequote_escaping": False,
        "embedded_newlines": "forbidden",
        "blank_rows": "forbidden",
        "comment_data_rows": "forbidden",
        "field_whitespace_normalization": "forbidden",
        "header_comparison": "exact-raw-cell-no-whitespace-normalization/v1",
        "timestamps_strictly_increasing": True,
    },
    "timestamp_lexeme": {
        "charset": "ascii",
        "whitespace": "forbidden",
        "fullmatch_regex": r"(?:0|[1-9][0-9]*)",
        "minimum_value": 0,
        "maximum_value": 9_223_372_036_854_775_807,
        "maximum_token_bytes": 19,
        "output_representation": "unsigned-int64-exact/v1",
    },
    "numeric_lexeme": {
        "charset": "ascii",
        "whitespace": "forbidden",
        "fullmatch_regex": (
            r"[+-]?(?:(?:[0-9]+(?:\.[0-9]*)?)|(?:\.[0-9]+))"
            r"(?:[eE][+-]?[0-9]+)?"
        ),
        "decimal_separator": ".",
        "exponent_markers": ["e", "E"],
        "nonfinite_literals": "forbidden",
        "maximum_token_bytes": 128,
        "output_representation": "original-ascii-lexeme",
        "numeric_conversion": None,
    },
    "camera_index": {
        "roles": ["cam0", "cam1"],
        "header": _CAMERA_HEADER,
        "row_arity": 2,
        "minimum_data_rows": 1,
        "stream_role_output_field": "stream_role",
        "column_grammars": [
            {
                "source_header": "#timestamp [ns]",
                "lexeme_grammar": "timestamp_lexeme",
                "output_field": "timestamp_source_label_ns",
            },
            {
                "source_header": "filename",
                "lexeme_grammar": "filename_grammar",
                "output_field": "filename_source_lexeme",
            },
        ],
        "output_fields": [
            "stream_role",
            "timestamp_source_label_ns",
            "filename_source_lexeme",
        ],
        "filename_grammar": {
            "charset": "ascii",
            "case_sensitive": True,
            "whitespace": "forbidden",
            "fullmatch_regex": r"(?:0|[1-9][0-9]*)\.png",
            "stem_minimum_value": 0,
            "stem_maximum_value": 9_223_372_036_854_775_807,
            "maximum_token_bytes": 23,
            "path_separators": "forbidden",
            "output_representation": "safe-basename-original-ascii-lexeme",
        },
        "filename_stem_equals_timestamp": True,
        "filenames_unique": True,
    },
    "imu_stream": {
        "header": _IMU_HEADER,
        "row_arity": 7,
        "minimum_data_rows": 1,
        "column_grammars": _IMU_COLUMN_GRAMMARS,
        "output_fields": _IMU_OUTPUT_FIELDS,
    },
    "pose_reference_stream": {
        "header": _POSE_HEADER,
        "row_arity": 8,
        "minimum_data_rows": 1,
        "column_grammars": _POSE_COLUMN_GRAMMARS,
        "output_fields": _POSE_OUTPUT_FIELDS,
    },
}

_EXPECTED_STEREO_POLICY = {
    "exact_index_bytes_required": True,
    "exact_ordered_timestamp_filename_rows_required": True,
    "require_each_filename_once_per_index": True,
    "full_indexed_image_existence_required_before_real_execution": True,
    "monocular_fallback": False,
}

_EXPECTED_INTERVAL_POLICY = {
    "coverage_interval": (
        "closed-intersection-of-source-labeled-timestamp-token-ranges-no-clock-equivalence-claim/v1"
    ),
    "comparison_semantics": "integer-token-order-only-no-clock-equivalence-claim/v1",
    "outside_camera_timestamp_action": (
        "prospective-exclude-without-shift-clamp-extrapolation-or-resampling-not-executable/v1"
    ),
    "segment_rule": None,
    "minimum_frames_per_structural_segment": None,
    "imu_window": "(previous_camera_timestamp,current_camera_timestamp]",
    "require_nonempty_imu_window": True,
    "clock_offset_ns": None,
    "maximum_camera_gap_ns": None,
    "maximum_imu_gap_ns": None,
    "maximum_pose_gap_ns": None,
    "operational_eligibility": (
        "blocked-until-clock-mapping-and-full-image-existence-evidence-are-separately-frozen"
    ),
    "segment_construction_ready": False,
    "pose_at_camera_timestamp": "blocked-until-interpolation-policy-is-separately-frozen",
    "allow_timestamp_shift": False,
    "allow_clock_correction": False,
    "allow_extrapolation": False,
    "allow_resampling": False,
}

_EXPECTED_POSE_REFERENCE = {
    "record_name": "TumviSourceLabeledPoseRow",
    "fields": _POSE_OUTPUT_FIELDS,
    "field_semantics": "source-header-labels-only-units-frames-and-transform-unverified/v1",
    "reference_role": "unassigned",
    "velocity_fields": "absent",
    "gyroscope_bias_fields": "absent",
    "accelerometer_bias_fields": "absent",
    "quaternion_norm_policy": None,
    "normalization_policy": None,
    "interpolation_policy": None,
    "maximum_interpolation_bracket_ns": None,
    "extrapolation": "prohibited",
    "ground_truth_ready": False,
}

_EXPECTED_IMAGE_BOUNDARY = {
    "observed_selected_png_headers": {
        "file_count": 4,
        "interpreted_bytes_per_file": 33,
        "width_px": 512,
        "height_px": 512,
        "bit_depth": 16,
        "color_type": 0,
        "standard_id": "W3C-PNG-Third-Edition-2025-06-24",
        "standard_url": "https://www.w3.org/TR/2025/REC-png-3-20250624/",
    },
    "full_indexed_image_existence_verified": False,
    "whole_file_png_validity_verified": False,
    "decodability_verified": False,
    "decoder": None,
    "decoded_dtype": None,
    "sample_range_mapping": None,
    "channel_policy": None,
    "normalization": None,
    "preprocessing_ready": False,
    "image_bytes_authorized": 0,
    "permitted_output": "path-and-opaque-identity-only",
}

_EXPECTED_RESOURCE_LIMITS = {
    "maximum_csv_rows_per_file": 1_000_000,
    "maximum_csv_line_bytes": 1_048_576,
    "maximum_csv_columns": 8,
    "maximum_csv_bytes_by_role": {
        "cam0": 98_057,
        "cam1": 98_057,
        "imu": 2_232_296,
        "pose": 1_481_244,
    },
    "maximum_image_bytes_read": 0,
    "streaming_required": True,
    "fail_on_limit": True,
}

_EXPECTED_RECORD_OUTPUTS = {
    "camera_index_row": [
        "stream_role",
        "timestamp_source_label_ns",
        "filename_source_lexeme",
    ],
    "stereo_index_row": [
        "timestamp_source_label_ns",
        "cam0_filename_source_lexeme",
        "cam1_filename_source_lexeme",
    ],
    "imu_row": _IMU_OUTPUT_FIELDS,
    "source_labeled_pose_row": _POSE_OUTPUT_FIELDS,
}
_EXPECTED_READINESS = {
    "real_payload_execution_authorized": False,
    "adapter_implemented": False,
    "adapter_ready": False,
    "calibration_ready": False,
    "clock_mapping_ready": False,
    "pose_semantics_ready": False,
    "ground_truth_ready": False,
    "png_decode_ready": False,
    "preprocessing_ready": False,
    "full_image_population_ready": False,
    "segment_construction_ready": False,
    "dataset_selected": False,
    "membership_assigned": False,
    "model_access_authorized": False,
}
_LIMITATIONS = [
    "contract_only_no_real_payload_access",
    "source_header_labels_do_not_establish_units_frames_or_semantics",
    "timestamp_token_comparison_does_not_establish_clock_equivalence",
    "interval_policy_excludes_outside_rows_without_clock_correction",
    "null_gap_and_interpolation_thresholds_block_pose_association",
    "sparse_slice_does_not_establish_full_indexed_image_existence",
    "four_png_headers_do_not_establish_decodability_or_preprocessing",
    "does_not_select_dataset_or_assign_membership",
    "does_not_authorize_model_access_training_inference_evaluation_or_publication",
]
_EXPECTED_RESULT = {
    "contract_validation_outcomes": ["valid", "invalid"],
    "record_outputs": _EXPECTED_RECORD_OUTPUTS,
    "readiness": _EXPECTED_READINESS,
    "scientific_authority": "none",
    "limitations": _LIMITATIONS,
}

_ROOT_KEYS = {
    "record_type",
    "schema_version",
    "contract_id",
    "scope",
    "source_evidence",
    "layout",
    "csv_grammars",
    "stereo_policy",
    "interval_policy",
    "pose_reference_contract",
    "image_preprocessing_boundary",
    "resource_limits",
    "result_contract",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TumviAdapterContractError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _mapping(value: object, *, field: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise TumviAdapterContractError(f"{field} must be a JSON object with string keys")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise TumviAdapterContractError(
            f"{field} has non-exact keys; missing={missing}, extra={extra}"
        )
    return value


def _deep_exact(value: object, expected: object, *, field: str) -> None:
    if type(value) is not type(expected):
        raise TumviAdapterContractError(
            f"{field} must have exact JSON type {type(expected).__name__}"
        )
    if type(expected) is dict:
        actual_mapping = _mapping(value, field=field, keys=set(expected))
        for key, expected_item in expected.items():
            _deep_exact(actual_mapping[key], expected_item, field=f"{field}.{key}")
        return
    if type(expected) is list:
        actual_list = value
        if len(actual_list) != len(expected):
            raise TumviAdapterContractError(f"{field} must have exact ordered length")
        for index, (actual_item, expected_item) in enumerate(
            zip(actual_list, expected, strict=True)
        ):
            _deep_exact(actual_item, expected_item, field=f"{field}[{index}]")
        return
    if value != expected:
        raise TumviAdapterContractError(f"{field} must equal {expected!r}")


def _contract_json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            item.name: _contract_json_value(getattr(value, item.name)) for item in fields(value)
        }
    if type(value) is tuple:
        return [_contract_json_value(item) for item in value]
    return value


def _assert_constructed_exact(value: object, expected: object, *, field: str) -> None:
    _deep_exact(_contract_json_value(value), expected, field=field)


def _assert_resource_limits(value: ResourceLimits) -> None:
    expected_roles = tuple(_EXPECTED_RESOURCE_LIMITS["maximum_csv_bytes_by_role"])
    if tuple(name for name, _ in value.maximum_csv_bytes_by_role) != expected_roles:
        raise TumviAdapterContractError(
            "ResourceLimits.maximum_csv_bytes_by_role must have exact canonical roles"
        )
    actual = {
        "maximum_csv_rows_per_file": value.maximum_csv_rows_per_file,
        "maximum_csv_line_bytes": value.maximum_csv_line_bytes,
        "maximum_csv_columns": value.maximum_csv_columns,
        "maximum_csv_bytes_by_role": dict(value.maximum_csv_bytes_by_role),
        "maximum_image_bytes_read": value.maximum_image_bytes_read,
        "streaming_required": value.streaming_required,
        "fail_on_limit": value.fail_on_limit,
    }
    _deep_exact(actual, _EXPECTED_RESOURCE_LIMITS, field="ResourceLimits")


def _assert_result_contract(value: ResultContract) -> None:
    expected_outputs = tuple(_EXPECTED_RECORD_OUTPUTS)
    if tuple(name for name, _ in value.record_outputs) != expected_outputs:
        raise TumviAdapterContractError(
            "ResultContract.record_outputs must have exact canonical names"
        )
    actual = {
        "contract_validation_outcomes": list(value.contract_validation_outcomes),
        "record_outputs": {name: list(output) for name, output in value.record_outputs},
        "readiness": _contract_json_value(value.readiness),
        "scientific_authority": value.scientific_authority,
        "limitations": list(value.limitations),
    }
    _deep_exact(actual, _EXPECTED_RESULT, field="ResultContract")


def _assert_top_level_contract(value: TumviAdapterContract) -> None:
    if value.path != _CONTRACT_PATH:
        raise TumviAdapterContractError(f"TumviAdapterContract.path must equal {_CONTRACT_PATH!r}")
    if value.contract_id != _CONTRACT_ID:
        raise TumviAdapterContractError(
            f"TumviAdapterContract.contract_id must equal {_CONTRACT_ID!r}"
        )
    for field_name, text, length in (
        ("sha256", value.sha256, 64),
        ("git_revision", value.git_revision, 40),
    ):
        if (
            type(text) is not str
            or len(text) != length
            or any(character not in "0123456789abcdef" for character in text)
        ):
            raise TumviAdapterContractError(
                f"TumviAdapterContract.{field_name} must be lowercase hexadecimal"
            )
    expected_types = {
        "source_evidence": SourceEvidence,
        "layout": LayoutContract,
        "csv_grammars": CsvGrammars,
        "stereo_policy": StereoPolicy,
        "interval_policy": IntervalPolicy,
        "pose_reference_contract": PoseReferenceContract,
        "image_preprocessing_boundary": ImagePreprocessingBoundary,
        "resource_limits": ResourceLimits,
        "result_contract": ResultContract,
    }
    for field_name, expected_type in expected_types.items():
        if type(getattr(value, field_name)) is not expected_type:
            raise TumviAdapterContractError(
                f"TumviAdapterContract.{field_name} must be {expected_type.__name__}"
            )


def _canonical_relative(value: object, *, field: str) -> str:
    if type(value) is not str or not value or "\\" in value:
        raise TumviAdapterContractError(f"{field} must be canonical repository-relative text")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise TumviAdapterContractError(f"{field} must be canonical repository-relative text")
    return path.as_posix()


def _git(root: Path, *arguments: str) -> bytes:
    try:
        result = subprocess.run(
            ("git", "-C", os.fspath(root), *arguments),
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TumviAdapterContractError(f"cannot inspect tracked Git evidence: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise TumviAdapterContractError(f"Git evidence check failed: {detail or arguments!r}")
    return result.stdout


def _validated_repo_root(repo_root: os.PathLike[str] | str) -> tuple[Path, str]:
    supplied = Path(repo_root)
    try:
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise TumviAdapterContractError(f"repository root does not exist: {supplied}") from exc
    if not root.is_dir():
        raise TumviAdapterContractError(f"repository root is not a directory: {root}")
    top_level_raw = _git(root, "rev-parse", "--show-toplevel")
    try:
        top_level = Path(top_level_raw.decode("utf-8").strip()).resolve(strict=True)
    except (OSError, UnicodeError) as exc:
        raise TumviAdapterContractError("Git returned an invalid repository root") from exc
    if top_level != root:
        raise TumviAdapterContractError("repo_root must equal the Git worktree root")
    revision = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise TumviAdapterContractError("HEAD must resolve to a lowercase 40-character revision")
    return root, revision


def _relative_from_supplied(supplied: os.PathLike[str] | str, *, root: Path, field: str) -> str:
    candidate = Path(supplied)
    absolute = Path(os.path.abspath(candidate if candidate.is_absolute() else root / candidate))
    try:
        relative = absolute.relative_to(root).as_posix()
    except ValueError as exc:
        raise TumviAdapterContractError(f"{field} must be inside the repository") from exc
    return _canonical_relative(relative, field=field)


def _read_regular_no_symlinks(root: Path, relative: str, *, field: str) -> bytes:
    canonical = _canonical_relative(relative, field=field)
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise TumviAdapterContractError(
            f"cannot enforce descriptor-bound no-symlink traversal for {field}"
        )

    def open_bound() -> tuple[int, list[int]]:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        directories: list[int] = []
        try:
            directories.append(os.open(root, directory_flags))
            for part in PurePosixPath(canonical).parts[:-1]:
                descriptor = os.open(part, directory_flags, dir_fd=directories[-1])
                status = os.fstat(descriptor)
                if not stat.S_ISDIR(status.st_mode):
                    os.close(descriptor)
                    raise TumviAdapterContractError(f"{field} must have only directory ancestors")
                directories.append(descriptor)
            descriptor = os.open(
                PurePosixPath(canonical).parts[-1],
                file_flags,
                dir_fd=directories[-1],
            )
            return descriptor, directories
        except OSError as exc:
            for directory in reversed(directories):
                os.close(directory)
            raise TumviAdapterContractError(
                f"cannot open {field} without following symlinks: {root / canonical}"
            ) from exc
        except Exception:
            for directory in reversed(directories):
                os.close(directory)
            raise

    descriptor, directories = open_bound()
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise TumviAdapterContractError(f"{field} must be a regular file")
        if before.st_nlink != 1:
            raise TumviAdapterContractError(f"{field} must have exactly one hard link")
        if before.st_size > _MAX_TRACKED_FILE_BYTES:
            raise TumviAdapterContractError(f"{field} exceeds the tracked-file byte limit")
        chunks: list[bytes] = []
        remaining = _MAX_TRACKED_FILE_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_TRACKED_FILE_BYTES:
            raise TumviAdapterContractError(f"{field} exceeds the tracked-file byte limit")
        after = os.fstat(descriptor)
    except OSError as exc:
        raise TumviAdapterContractError(f"cannot read {field}: {root / canonical}") from exc
    finally:
        os.close(descriptor)
        for directory in reversed(directories):
            os.close(directory)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_nlink,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_nlink,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    if identity_before != identity_after or len(raw) != before.st_size:
        raise TumviAdapterContractError(f"{field} changed while being read")

    verification_descriptor, verification_directories = open_bound()
    try:
        verification = os.fstat(verification_descriptor)
    except OSError as exc:
        raise TumviAdapterContractError(f"cannot recheck {field}: {root / canonical}") from exc
    finally:
        os.close(verification_descriptor)
        for directory in reversed(verification_directories):
            os.close(directory)
    verification_identity = (
        verification.st_dev,
        verification.st_ino,
        verification.st_nlink,
        verification.st_size,
        verification.st_mtime_ns,
        verification.st_ctime_ns,
    )
    if not stat.S_ISREG(verification.st_mode) or verification.st_nlink != 1:
        raise TumviAdapterContractError(f"{field} must remain a single-link regular file")
    if verification_identity != identity_after:
        raise TumviAdapterContractError(f"{field} path identity changed while being read")
    return raw


def _assert_tracked_head_bytes(
    root: Path,
    relative: str,
    raw: bytes,
    *,
    field: str,
    revision: str,
) -> None:
    revision_path = f"{revision}:{relative}"
    kind = _git(root, "cat-file", "-t", revision_path).strip()
    if kind != b"blob":
        raise TumviAdapterContractError(f"{field} must be a tracked HEAD blob")
    head_raw = _git(root, "cat-file", "-p", revision_path)
    if len(head_raw) > _MAX_TRACKED_FILE_BYTES:
        raise TumviAdapterContractError(f"{field} HEAD blob exceeds the byte limit")
    if raw != head_raw:
        raise TumviAdapterContractError(f"{field} worktree bytes do not equal tracked HEAD")


def _assert_head_unchanged(root: Path, revision: str) -> None:
    if _git(root, "rev-parse", "HEAD").decode("ascii").strip() != revision:
        raise TumviAdapterContractError("HEAD changed while validating adapter contract")


def _source_evidence(parsed: Mapping[str, object]) -> SourceEvidence:
    def identity(name: str) -> EvidenceIdentity:
        value = parsed[name]
        if type(value) is not dict:
            raise TumviAdapterContractError(f"source_evidence.{name} must be an object")
        return EvidenceIdentity(value["path"], value["sha256"])

    return SourceEvidence(
        candidate=identity("candidate"),
        compatibility_slice_receipt=identity("compatibility_slice_receipt"),
        format_inspection_spec=identity("format_inspection_spec"),
        format_inspection_receipt=identity("format_inspection_receipt"),
        format_inspection_report=identity("format_inspection_report"),
        rejected_euroc_adapter=identity("rejected_euroc_adapter"),
    )


def _build_contract(
    parsed: Mapping[str, Any], *, relative: str, raw: bytes, revision: str
) -> TumviAdapterContract:
    layout = parsed["layout"]
    csv = parsed["csv_grammars"]
    common = csv["common"]
    timestamp_lexeme = csv["timestamp_lexeme"]
    numeric_lexeme = csv["numeric_lexeme"]
    camera = csv["camera_index"]
    imu = csv["imu_stream"]
    pose_csv = csv["pose_reference_stream"]
    stereo = parsed["stereo_policy"]
    interval = parsed["interval_policy"]
    pose = parsed["pose_reference_contract"]
    image = parsed["image_preprocessing_boundary"]
    observed = image["observed_selected_png_headers"]
    limits = parsed["resource_limits"]
    result = parsed["result_contract"]
    readiness = result["readiness"]
    return TumviAdapterContract(
        _seal=_CONSTRUCTION_SEAL,
        path=relative,
        sha256=hashlib.sha256(raw).hexdigest(),
        git_revision=revision,
        contract_id=_CONTRACT_ID,
        source_evidence=_source_evidence(parsed["source_evidence"]),
        layout=LayoutContract(
            sequence_directory_name=layout["sequence_directory_name"],
            camera_streams=tuple(CameraStreamLayout(**item) for item in layout["camera_streams"]),
            imu_stream_path=layout["imu_stream_path"],
            pose_reference_stream_path=layout["pose_reference_stream_path"],
            excluded_prefixes=tuple(layout["excluded_prefixes"]),
            calibration_access=layout["calibration_access"],
            real_payload_access=layout["real_payload_access"],
        ),
        csv_grammars=CsvGrammars(
            common=CsvCommonGrammar(**common),
            timestamp_lexeme=TimestampLexemeGrammar(**timestamp_lexeme),
            numeric_lexeme=NumericLexemeGrammar(
                **{
                    **numeric_lexeme,
                    "exponent_markers": tuple(numeric_lexeme["exponent_markers"]),
                }
            ),
            camera_index=CameraIndexGrammar(
                roles=tuple(camera["roles"]),
                header=tuple(camera["header"]),
                row_arity=camera["row_arity"],
                minimum_data_rows=camera["minimum_data_rows"],
                stream_role_output_field=camera["stream_role_output_field"],
                column_grammars=tuple(
                    ColumnGrammar(**column) for column in camera["column_grammars"]
                ),
                output_fields=tuple(camera["output_fields"]),
                filename_grammar=FilenameGrammar(**camera["filename_grammar"]),
                filename_stem_equals_timestamp=camera["filename_stem_equals_timestamp"],
                filenames_unique=camera["filenames_unique"],
            ),
            imu_stream=CsvStreamGrammar(
                header=tuple(imu["header"]),
                row_arity=imu["row_arity"],
                minimum_data_rows=imu["minimum_data_rows"],
                column_grammars=tuple(ColumnGrammar(**column) for column in imu["column_grammars"]),
                output_fields=tuple(imu["output_fields"]),
            ),
            pose_reference_stream=CsvStreamGrammar(
                header=tuple(pose_csv["header"]),
                row_arity=pose_csv["row_arity"],
                minimum_data_rows=pose_csv["minimum_data_rows"],
                column_grammars=tuple(
                    ColumnGrammar(**column) for column in pose_csv["column_grammars"]
                ),
                output_fields=tuple(pose_csv["output_fields"]),
            ),
        ),
        stereo_policy=StereoPolicy(**stereo),
        interval_policy=IntervalPolicy(**interval),
        pose_reference_contract=PoseReferenceContract(
            record_name=pose["record_name"],
            fields=tuple(pose["fields"]),
            field_semantics=pose["field_semantics"],
            reference_role=pose["reference_role"],
            velocity_fields=pose["velocity_fields"],
            gyroscope_bias_fields=pose["gyroscope_bias_fields"],
            accelerometer_bias_fields=pose["accelerometer_bias_fields"],
            quaternion_norm_policy=pose["quaternion_norm_policy"],
            normalization_policy=pose["normalization_policy"],
            interpolation_policy=pose["interpolation_policy"],
            maximum_interpolation_bracket_ns=pose["maximum_interpolation_bracket_ns"],
            extrapolation=pose["extrapolation"],
            ground_truth_ready=pose["ground_truth_ready"],
        ),
        image_preprocessing_boundary=ImagePreprocessingBoundary(
            observed_selected_png_headers=ObservedPngHeaders(**observed),
            full_indexed_image_existence_verified=image["full_indexed_image_existence_verified"],
            whole_file_png_validity_verified=image["whole_file_png_validity_verified"],
            decodability_verified=image["decodability_verified"],
            decoder=image["decoder"],
            decoded_dtype=image["decoded_dtype"],
            sample_range_mapping=image["sample_range_mapping"],
            channel_policy=image["channel_policy"],
            normalization=image["normalization"],
            preprocessing_ready=image["preprocessing_ready"],
            image_bytes_authorized=image["image_bytes_authorized"],
            permitted_output=image["permitted_output"],
        ),
        resource_limits=ResourceLimits(
            maximum_csv_rows_per_file=limits["maximum_csv_rows_per_file"],
            maximum_csv_line_bytes=limits["maximum_csv_line_bytes"],
            maximum_csv_columns=limits["maximum_csv_columns"],
            maximum_csv_bytes_by_role=tuple(
                (name, limits["maximum_csv_bytes_by_role"][name])
                for name in _EXPECTED_RESOURCE_LIMITS["maximum_csv_bytes_by_role"]
            ),
            maximum_image_bytes_read=limits["maximum_image_bytes_read"],
            streaming_required=limits["streaming_required"],
            fail_on_limit=limits["fail_on_limit"],
        ),
        result_contract=ResultContract(
            contract_validation_outcomes=tuple(result["contract_validation_outcomes"]),
            record_outputs=tuple(
                (name, tuple(result["record_outputs"][name])) for name in _EXPECTED_RECORD_OUTPUTS
            ),
            readiness=ReadinessContract(**readiness),
            scientific_authority=result["scientific_authority"],
            limitations=tuple(result["limitations"]),
        ),
    )


def load_tumvi_adapter_contract(
    path: os.PathLike[str] | str,
    *,
    repo_root: os.PathLike[str] | str,
) -> TumviAdapterContract:
    """Load the exact checked contract and its tracked non-payload evidence.

    The contract itself and every evidence file must be regular, symlink-free,
    tracked HEAD blobs whose worktree bytes equal their committed bytes. Layout
    paths are policy strings only and are never resolved or opened.
    """

    root, revision = _validated_repo_root(repo_root)
    relative = _relative_from_supplied(path, root=root, field="contract path")
    if relative != _CONTRACT_PATH:
        raise TumviAdapterContractError(
            f"contract path must equal the canonical path {_CONTRACT_PATH!r}"
        )
    raw = _read_regular_no_symlinks(root, relative, field="adapter contract")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise TumviAdapterContractError("adapter contract must be UTF-8 without a BOM")
    try:
        parsed_value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except TumviAdapterContractError:
        raise
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TumviAdapterContractError(
            f"adapter contract is not strict UTF-8 JSON: {exc}"
        ) from exc
    root_object = _mapping(parsed_value, field="adapter contract", keys=_ROOT_KEYS)
    for key, expected in (
        ("record_type", _RECORD_TYPE),
        ("schema_version", _SCHEMA_VERSION),
        ("contract_id", _CONTRACT_ID),
        ("scope", _SCOPE),
    ):
        _deep_exact(root_object[key], expected, field=key)
    for key, expected in (
        ("source_evidence", _EXPECTED_EVIDENCE),
        ("layout", _EXPECTED_LAYOUT),
        ("csv_grammars", _EXPECTED_CSV_GRAMMARS),
        ("stereo_policy", _EXPECTED_STEREO_POLICY),
        ("interval_policy", _EXPECTED_INTERVAL_POLICY),
        ("pose_reference_contract", _EXPECTED_POSE_REFERENCE),
        ("image_preprocessing_boundary", _EXPECTED_IMAGE_BOUNDARY),
        ("resource_limits", _EXPECTED_RESOURCE_LIMITS),
        ("result_contract", _EXPECTED_RESULT),
    ):
        _deep_exact(root_object[key], expected, field=key)

    _assert_tracked_head_bytes(
        root,
        relative,
        raw,
        field="adapter contract",
        revision=revision,
    )
    bound_files = [(relative, raw, "adapter contract")]
    evidence = root_object["source_evidence"]
    for name, expected in _EXPECTED_EVIDENCE.items():
        evidence_path = _canonical_relative(expected["path"], field=f"source_evidence.{name}.path")
        evidence_raw = _read_regular_no_symlinks(
            root,
            evidence_path,
            field=f"source_evidence.{name}",
        )
        _assert_tracked_head_bytes(
            root,
            evidence_path,
            evidence_raw,
            field=f"source_evidence.{name}",
            revision=revision,
        )
        if hashlib.sha256(evidence_raw).hexdigest() != evidence[name]["sha256"]:
            raise TumviAdapterContractError(f"source_evidence.{name} SHA-256 mismatch")
        bound_files.append((evidence_path, evidence_raw, f"source_evidence.{name}"))
    for bound_path, bound_raw, bound_field in bound_files:
        if _read_regular_no_symlinks(root, bound_path, field=bound_field) != bound_raw:
            raise TumviAdapterContractError(f"{bound_field} changed during final validation")
    _assert_head_unchanged(root, revision)
    return _build_contract(root_object, relative=relative, raw=raw, revision=revision)


__all__ = [
    "TumviAdapterContract",
    "TumviAdapterContractError",
    "load_tumvi_adapter_contract",
]

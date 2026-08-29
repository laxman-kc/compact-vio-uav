"""Quarantined acquisition, inventory, and extraction for TAR archives.

The publisher identity and the locally observed SHA-256 are intentionally
separate.  A dataset publisher may provide only an exact byte length and MD5
before the first acquisition; callers must pin the observed SHA-256 before
this module will extract any archive member.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tarfile
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

try:
    import fcntl
except ImportError:  # pragma: no cover - POSIX-only operation fails closed below.
    fcntl = None  # type: ignore[assignment]

_USER_AGENT = "compact-vio-uav/0.1 (research archive acquisition)"
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_CONTENT_RANGE = re.compile(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)")
_COPY_CHUNK_SIZE = 8 * 1024 * 1024
_MAX_DOWNLOAD_CHUNK_SIZE = 16 * 1024 * 1024


class ArchiveError(RuntimeError):
    """Raised when an archive operation cannot preserve its trust boundary."""


def _lower_hex(value: object, *, length: int, field: str) -> str:
    if (
        type(value) is not str
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ArchiveError(f"{field} must be {length} lowercase hexadecimal characters")
    return value


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _validate_https_url(value: object, *, field: str) -> urllib.parse.SplitResult:
    if type(value) is not str:
        raise ArchiveError(f"{field} must be a string")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ArchiveError(f"{field} must be an absolute HTTPS URL")
    if parsed.username is not None or parsed.password is not None:
        raise ArchiveError(f"{field} must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ArchiveError(f"{field} must not contain a query or fragment")
    return parsed


def _validate_https_origin(value: object, *, field: str) -> str:
    parsed = _validate_https_url(value, field=field)
    if parsed.path not in ("", "/") or parsed.query:
        raise ArchiveError(f"{field} must contain only scheme and authority")
    return f"{parsed.scheme}://{parsed.netloc}"


def _origin(parsed: urllib.parse.SplitResult) -> str:
    return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True, slots=True)
class PublishedArchiveIdentity:
    """Immutable identity published before or after first acquisition.

    ``sha256`` may be ``None`` only while the first verified acquisition is
    unresolved.  Verification still computes and returns the observed
    SHA-256 without mutating this record.
    """

    archive_id: str
    filename: str
    url: str
    size_bytes: int
    md5: str
    sha256: str | None = None
    allowed_redirect_urls: tuple[str, ...] = ()
    allowed_redirect_origins: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.archive_id) is not str
            or _SAFE_IDENTIFIER.fullmatch(self.archive_id) is None
            or self.archive_id in (".", "..")
        ):
            raise ArchiveError("archive_id must be one safe identifier")
        if (
            type(self.filename) is not str
            or not self.filename
            or "/" in self.filename
            or "\\" in self.filename
            or Path(self.filename).name != self.filename
            or not self.filename.endswith(".tar")
        ):
            raise ArchiveError("filename must be one uncompressed .tar basename")
        _validate_https_url(self.url, field="archive URL")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise ArchiveError("size_bytes must be a positive integer")
        _lower_hex(self.md5, length=32, field="md5")
        if self.sha256 is not None:
            _lower_hex(self.sha256, length=64, field="sha256")
        if type(self.allowed_redirect_urls) is not tuple:
            raise ArchiveError("allowed_redirect_urls must be a tuple")
        if type(self.allowed_redirect_origins) is not tuple:
            raise ArchiveError("allowed_redirect_origins must be a tuple")
        if len(set(self.allowed_redirect_urls)) != len(self.allowed_redirect_urls):
            raise ArchiveError("allowed_redirect_urls must be unique")
        if len(set(self.allowed_redirect_origins)) != len(self.allowed_redirect_origins):
            raise ArchiveError("allowed_redirect_origins must be unique")
        for index, url in enumerate(self.allowed_redirect_urls):
            _validate_https_url(url, field=f"allowed_redirect_urls[{index}]")
        for index, origin in enumerate(self.allowed_redirect_origins):
            _validate_https_origin(origin, field=f"allowed_redirect_origins[{index}]")


_AUTHORIZATION_CAPABILITY = object()


@dataclass(frozen=True, slots=True, init=False)
class AuthorizedArchiveAcquisition:
    """Validated reviewed authority required by the mutating downloader.

    Instances cannot be constructed directly; they are created only by
    :func:`load_authorized_archive_acquisition` after exact record validation.
    """

    identity: PublishedArchiveIdentity
    authorization_record_id: str
    authorization_record_sha256: str
    destination_path: str
    reviewed_by: str
    reviewed_at: str
    _capability: object

    @classmethod
    def _from_validated_record(
        cls,
        *,
        identity: PublishedArchiveIdentity,
        authorization_record_id: str,
        authorization_record_sha256: str,
        destination_path: str,
        reviewed_by: str,
        reviewed_at: str,
    ) -> AuthorizedArchiveAcquisition:
        instance = object.__new__(cls)
        object.__setattr__(instance, "identity", identity)
        object.__setattr__(instance, "authorization_record_id", authorization_record_id)
        object.__setattr__(
            instance,
            "authorization_record_sha256",
            authorization_record_sha256,
        )
        object.__setattr__(instance, "destination_path", destination_path)
        object.__setattr__(instance, "reviewed_by", reviewed_by)
        object.__setattr__(instance, "reviewed_at", reviewed_at)
        object.__setattr__(instance, "_capability", _AUTHORIZATION_CAPABILITY)
        return instance


@dataclass(frozen=True, slots=True)
class PublishedChecksumSidecar:
    """Exact publisher-side checksum evidence, not received-byte authority."""

    url: str
    allowed_redirect_urls: tuple[str, ...]
    allowed_redirect_origins: tuple[str, ...]
    exact_body: str
    published_md5: str


@dataclass(frozen=True, slots=True)
class DatasetArchiveCandidate:
    """Validated non-executable candidate with no received-byte promotion."""

    schema_version: str
    recorded_at: str
    dataset_id: str
    sequence_id: str
    published_identity: PublishedArchiveIdentity
    md5_sidecar: PublishedChecksumSidecar
    evidence_path: str


def _exact_object(value: object, *, field: str, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise ArchiveError(f"{field} must be a JSON object with string keys")
    if set(value) != keys:
        raise ArchiveError(f"{field} fields must equal {sorted(keys)!r}")
    return value


def _exact_string(value: object, *, field: str) -> str:
    if type(value) is not str or not value:
        raise ArchiveError(f"{field} must be a non-empty string")
    return value


def _exact_positive_int(value: object, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ArchiveError(f"{field} must be a positive integer")
    return value


def _exact_string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise ArchiveError(f"{field} must be a non-empty JSON array")
    result = tuple(
        _exact_string(item, field=f"{field}[{index}]") for index, item in enumerate(value)
    )
    if len(set(result)) != len(result):
        raise ArchiveError(f"{field} values must be unique")
    return result


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveError(f"duplicate JSON field is prohibited: {key!r}")
        result[key] = value
    return result


def _require_literal(value: object, expected: object, *, field: str) -> None:
    if type(value) is not type(expected) or value != expected:
        raise ArchiveError(f"{field} must equal {expected!r}")


def _validate_url_list(
    value: object,
    *,
    field: str,
    origins: tuple[str, ...],
) -> tuple[str, ...]:
    urls = _exact_string_tuple(value, field=field)
    for index, url in enumerate(urls):
        parsed = _validate_https_url(url, field=f"{field}[{index}]")
        if _origin(parsed) not in origins:
            raise ArchiveError(f"{field}[{index}] origin is not explicitly allowed")
    return urls


def _validate_http_observation(
    value: object,
    *,
    field: str,
    method: str,
    allowed_redirect_urls: tuple[str, ...],
) -> tuple[int, str]:
    item = _exact_object(
        value,
        field=field,
        keys={
            "method",
            "request_observed_at",
            "request_status_code",
            "redirect_target",
            "redirect_observed_at",
            "redirect_status_code",
            "observed_content_length_bytes",
            "last_modified",
        },
    )
    _require_literal(item["method"], method, field=f"{field}.method")
    _require_literal(item["request_status_code"], 302, field=f"{field}.request_status_code")
    _require_literal(
        item["redirect_status_code"],
        200,
        field=f"{field}.redirect_status_code",
    )
    redirect_target = _exact_string(item["redirect_target"], field=f"{field}.redirect_target")
    if redirect_target not in allowed_redirect_urls:
        raise ArchiveError(f"{field}.redirect_target is not exactly allowlisted")
    for timestamp_field in ("request_observed_at", "redirect_observed_at"):
        timestamp = _exact_string(item[timestamp_field], field=f"{field}.{timestamp_field}")
        timestamp_pattern = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
        if re.fullmatch(timestamp_pattern, timestamp) is None:
            raise ArchiveError(
                f"{field}.{timestamp_field} must be a second-precision UTC timestamp"
            )
    content_length = _exact_positive_int(
        item["observed_content_length_bytes"],
        field=f"{field}.observed_content_length_bytes",
    )
    last_modified = _exact_string(item["last_modified"], field=f"{field}.last_modified")
    return content_length, last_modified


def _validate_candidate_context(root: dict[str, Any]) -> None:
    dataset = _exact_object(
        root["dataset"],
        field="dataset",
        keys={
            "dataset_id",
            "name",
            "publisher",
            "landing_page",
            "official_512_export_directory",
            "dataset_doi",
            "benchmark_publication_doi",
            "benchmark_publication_doi_scope",
            "rights",
        },
    )
    for field in ("dataset_id", "name", "publisher", "benchmark_publication_doi"):
        _exact_string(dataset[field], field=f"dataset.{field}")
    _require_literal(dataset["dataset_doi"], None, field="dataset.dataset_doi")
    _require_literal(
        dataset["benchmark_publication_doi_scope"],
        "benchmark_publication_not_dataset_deposit",
        field="dataset.benchmark_publication_doi_scope",
    )
    for field in ("landing_page", "official_512_export_directory"):
        _validate_https_url(dataset[field], field=f"dataset.{field}")
    rights = _exact_object(
        dataset["rights"],
        field="dataset.rights",
        keys={
            "data_label",
            "data_url",
            "code_label",
            "code_url",
            "authoritative_statement_url",
        },
    )
    for field in ("data_label", "code_label"):
        _exact_string(rights[field], field=f"dataset.rights.{field}")
    for field in ("data_url", "code_url", "authoritative_statement_url"):
        _validate_https_url(rights[field], field=f"dataset.rights.{field}")

    capabilities = _exact_object(
        root["published_capabilities"],
        field="published_capabilities",
        keys={"capture_domain", "cameras", "imu", "processed_sequence_statements"},
    )
    _exact_string(capabilities["capture_domain"], field="published_capabilities.capture_domain")
    cameras = _exact_object(
        capabilities["cameras"],
        field="published_capabilities.cameras",
        keys={"count", "type", "published_rate_hz", "hardware_synchronized_with_imu"},
    )
    _exact_positive_int(cameras["count"], field="published_capabilities.cameras.count")
    _exact_string(cameras["type"], field="published_capabilities.cameras.type")
    _exact_positive_int(
        cameras["published_rate_hz"],
        field="published_capabilities.cameras.published_rate_hz",
    )
    _require_literal(
        cameras["hardware_synchronized_with_imu"],
        True,
        field="published_capabilities.cameras.hardware_synchronized_with_imu",
    )
    imu = _exact_object(
        capabilities["imu"],
        field="published_capabilities.imu",
        keys={"published_rate_hz", "accelerometer_axes", "gyroscope_axes"},
    )
    for field in ("published_rate_hz", "accelerometer_axes", "gyroscope_axes"):
        _exact_positive_int(imu[field], field=f"published_capabilities.imu.{field}")
    statements = _exact_object(
        capabilities["processed_sequence_statements"],
        field="published_capabilities.processed_sequence_statements",
        keys={
            "consistent_camera_imu_ground_truth_timestamps",
            "imu_scaling_and_axis_alignment_applied",
            "ground_truth_pose_frame",
            "room_ground_truth_coverage",
            "ground_truth_source",
        },
    )
    for field in (
        "consistent_camera_imu_ground_truth_timestamps",
        "imu_scaling_and_axis_alignment_applied",
    ):
        _require_literal(statements[field], True, field=f"processed_sequence_statements.{field}")
    for field in ("ground_truth_pose_frame", "room_ground_truth_coverage", "ground_truth_source"):
        _exact_string(statements[field], field=f"processed_sequence_statements.{field}")

    intent = _exact_object(
        root["candidate_intent"],
        field="candidate_intent",
        keys={
            "proposed_lane",
            "uav_domain_confirmation",
            "publishable_superiority_claim",
            "deployment_or_flight_claim",
        },
    )
    _require_literal(
        intent["proposed_lane"],
        "external_full_pose_generalization_candidate_only",
        field="candidate_intent.proposed_lane",
    )
    for field in (
        "uav_domain_confirmation",
        "publishable_superiority_claim",
        "deployment_or_flight_claim",
    ):
        _require_literal(intent[field], False, field=f"candidate_intent.{field}")

    unresolved_keys = {
        "owner_authorization_for_bounded_acquisition",
        "evaluation_unit_selection_and_approval",
        "archive_sha256_and_safe_layout",
        "exact_calibration_artifact_and_hashes",
        "ground_truth_schema_pose_convention_and_parser",
        "image_16_bit_decoding_and_preprocessing",
        "source_group_and_membership_role",
        "adapter_compatibility",
        "evaluation_protocol",
    }
    unresolved = _exact_object(root["unresolved"], field="unresolved", keys=unresolved_keys)
    for field in unresolved_keys:
        _require_literal(unresolved[field], True, field=f"unresolved.{field}")
    notes = root["notes"]
    if type(notes) is not list or not notes:
        raise ArchiveError("notes must be a non-empty JSON array")
    for index, note in enumerate(notes):
        _exact_string(note, field=f"notes[{index}]")


def load_dataset_archive_candidate(
    path: os.PathLike[str] | str,
) -> DatasetArchiveCandidate:
    """Load the exact non-executable candidate record without granting authority."""

    record_path = Path(path)
    try:
        document = json.loads(
            record_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except ArchiveError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveError(f"cannot read dataset archive candidate {record_path}: {exc}") from exc
    root = _exact_object(
        document,
        field="dataset archive candidate",
        keys={
            "record_type",
            "schema_version",
            "record_status",
            "identity_state",
            "recorded_at",
            "authority",
            "dataset",
            "candidate_unit",
            "published_capabilities",
            "candidate_intent",
            "unresolved",
            "evidence",
            "notes",
        },
    )
    _require_literal(root["record_type"], "dataset_unit_candidate", field="record_type")
    _require_literal(root["schema_version"], "1.0.0", field="schema_version")
    _require_literal(
        root["record_status"],
        "candidate_non_executable",
        field="record_status",
    )
    _require_literal(
        root["identity_state"],
        "published_identity_only",
        field="identity_state",
    )
    recorded_at = _exact_string(root["recorded_at"], field="recorded_at")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", recorded_at) is None:
        raise ArchiveError("recorded_at must be an ISO calendar date")
    authority_keys = {
        "selects_dataset",
        "approves_acquisition",
        "approves_extraction",
        "approves_training",
        "approves_inference",
        "approves_evaluation",
    }
    authority = _exact_object(root["authority"], field="authority", keys=authority_keys)
    for field in authority_keys:
        _require_literal(authority[field], False, field=f"authority.{field}")

    _validate_candidate_context(root)
    dataset = root["dataset"]
    assert type(dataset) is dict
    dataset_id = _exact_string(dataset["dataset_id"], field="dataset.dataset_id")
    unit = _exact_object(
        root["candidate_unit"],
        field="candidate_unit",
        keys={
            "sequence_id",
            "source_group_id",
            "membership_role",
            "distribution_format",
            "image_resolution",
            "published_image_bit_depth",
            "filename",
            "official_request_url",
            "allowed_redirect_urls",
            "allowed_redirect_origins",
            "http_observations",
            "md5_sidecar",
            "received_size_bytes",
            "received_md5",
            "received_sha256",
            "expanded_size_bytes",
            "archive_layout_status",
        },
    )
    sequence_id = _exact_string(unit["sequence_id"], field="candidate_unit.sequence_id")
    if _SAFE_IDENTIFIER.fullmatch(sequence_id) is None:
        raise ArchiveError("candidate_unit.sequence_id must be one safe identifier")
    for field in ("source_group_id", "membership_role"):
        _require_literal(unit[field], None, field=f"candidate_unit.{field}")
    _require_literal(
        unit["distribution_format"],
        "euroc_dso_tar",
        field="candidate_unit.distribution_format",
    )
    resolution = unit["image_resolution"]
    if type(resolution) is not list or len(resolution) != 2:
        raise ArchiveError("candidate_unit.image_resolution must contain exactly two integers")
    for index, dimension in enumerate(resolution):
        _exact_positive_int(dimension, field=f"candidate_unit.image_resolution[{index}]")
    _exact_positive_int(
        unit["published_image_bit_depth"],
        field="candidate_unit.published_image_bit_depth",
    )
    filename = _exact_string(unit["filename"], field="candidate_unit.filename")
    request_url = _exact_string(
        unit["official_request_url"],
        field="candidate_unit.official_request_url",
    )
    request_parsed = _validate_https_url(
        request_url,
        field="candidate_unit.official_request_url",
    )
    if PurePosixPath(request_parsed.path).name != filename:
        raise ArchiveError("candidate filename does not match the official request URL")
    origins = _exact_string_tuple(
        unit["allowed_redirect_origins"],
        field="candidate_unit.allowed_redirect_origins",
    )
    for index, origin in enumerate(origins):
        _validate_https_origin(origin, field=f"candidate_unit.allowed_redirect_origins[{index}]")
    redirect_urls = _validate_url_list(
        unit["allowed_redirect_urls"],
        field="candidate_unit.allowed_redirect_urls",
        origins=origins,
    )
    content_length, _ = _validate_http_observation(
        unit["http_observations"],
        field="candidate_unit.http_observations",
        method="HEAD",
        allowed_redirect_urls=redirect_urls,
    )

    sidecar = _exact_object(
        unit["md5_sidecar"],
        field="candidate_unit.md5_sidecar",
        keys={
            "official_request_url",
            "allowed_redirect_urls",
            "allowed_redirect_origins",
            "http_observations",
            "exact_body",
            "published_md5",
        },
    )
    sidecar_url = _exact_string(
        sidecar["official_request_url"],
        field="candidate_unit.md5_sidecar.official_request_url",
    )
    _validate_https_url(sidecar_url, field="candidate_unit.md5_sidecar.official_request_url")
    sidecar_origins = _exact_string_tuple(
        sidecar["allowed_redirect_origins"],
        field="candidate_unit.md5_sidecar.allowed_redirect_origins",
    )
    for index, origin in enumerate(sidecar_origins):
        _validate_https_origin(
            origin,
            field=f"candidate_unit.md5_sidecar.allowed_redirect_origins[{index}]",
        )
    sidecar_redirects = _validate_url_list(
        sidecar["allowed_redirect_urls"],
        field="candidate_unit.md5_sidecar.allowed_redirect_urls",
        origins=sidecar_origins,
    )
    sidecar_content_length, _ = _validate_http_observation(
        sidecar["http_observations"],
        field="candidate_unit.md5_sidecar.http_observations",
        method="GET",
        allowed_redirect_urls=sidecar_redirects,
    )
    published_md5 = _lower_hex(
        sidecar["published_md5"],
        length=32,
        field="candidate_unit.md5_sidecar.published_md5",
    )
    exact_body = _exact_string(
        sidecar["exact_body"],
        field="candidate_unit.md5_sidecar.exact_body",
    )
    if len(exact_body.encode("utf-8")) != sidecar_content_length:
        raise ArchiveError("MD5 sidecar exact_body byte length does not match its observation")
    if exact_body != f"{published_md5}  {filename}\n":
        raise ArchiveError("MD5 sidecar exact_body is not the exact checksum line plus LF")
    if sidecar_url != f"{request_url}.md5" or sidecar_redirects != tuple(
        f"{url}.md5" for url in redirect_urls
    ):
        raise ArchiveError("MD5 sidecar URLs do not exactly bind the archive URLs")
    for field in (
        "received_size_bytes",
        "received_md5",
        "received_sha256",
        "expanded_size_bytes",
    ):
        _require_literal(unit[field], None, field=f"candidate_unit.{field}")
    _require_literal(
        unit["archive_layout_status"],
        "unresolved_not_downloaded",
        field="candidate_unit.archive_layout_status",
    )
    evidence = _exact_string(root["evidence"], field="evidence")
    evidence_parts = evidence.split("/")
    if (
        evidence.startswith("/")
        or "\\" in evidence
        or any(part in ("", ".", "..") for part in evidence_parts)
        or not evidence.endswith(".md")
    ):
        raise ArchiveError("evidence must be a canonical relative Markdown path")

    identity = PublishedArchiveIdentity(
        archive_id=f"{dataset_id}-{sequence_id}",
        filename=filename,
        url=request_url,
        size_bytes=content_length,
        md5=published_md5,
        sha256=None,
        allowed_redirect_urls=redirect_urls,
        allowed_redirect_origins=origins,
    )
    return DatasetArchiveCandidate(
        schema_version="1.0.0",
        recorded_at=recorded_at,
        dataset_id=dataset_id,
        sequence_id=sequence_id,
        published_identity=identity,
        md5_sidecar=PublishedChecksumSidecar(
            url=sidecar_url,
            allowed_redirect_urls=sidecar_redirects,
            allowed_redirect_origins=sidecar_origins,
            exact_body=exact_body,
            published_md5=published_md5,
        ),
        evidence_path=evidence,
    )


def load_authorized_archive_acquisition(
    path: os.PathLike[str] | str,
    identity: PublishedArchiveIdentity,
) -> AuthorizedArchiveAcquisition:
    """Load an approved record bound to one identity, destination, and scope."""

    if type(identity) is not PublishedArchiveIdentity:
        raise ArchiveError("identity must be a PublishedArchiveIdentity")
    record_path = Path(path)
    try:
        record_bytes = record_path.read_bytes()
        document = json.loads(
            record_bytes.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except ArchiveError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ArchiveError(
            f"cannot read archive acquisition authorization {record_path}: {exc}"
        ) from exc
    root = _exact_object(
        document,
        field="archive acquisition authorization",
        keys={
            "record_type",
            "schema_version",
            "record_status",
            "authorization_record_id",
            "scope",
            "reviewed_by",
            "reviewed_at",
            "authority",
            "archive_identity",
            "destination_path",
        },
    )
    _require_literal(
        root["record_type"],
        "dataset_archive_acquisition_authorization",
        field="record_type",
    )
    _require_literal(root["schema_version"], "1.0.0", field="schema_version")
    _require_literal(root["record_status"], "approved", field="record_status")
    _require_literal(root["scope"], "archive_acquisition_only", field="scope")
    record_id = _exact_string(
        root["authorization_record_id"],
        field="authorization_record_id",
    )
    if _SAFE_IDENTIFIER.fullmatch(record_id) is None or record_id in (".", ".."):
        raise ArchiveError("authorization_record_id must be one safe identifier")
    reviewed_by = _exact_string(root["reviewed_by"], field="reviewed_by")
    reviewed_at = _exact_string(root["reviewed_at"], field="reviewed_at")
    timestamp_pattern = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z"
    if re.fullmatch(timestamp_pattern, reviewed_at) is None:
        raise ArchiveError("reviewed_at must be a second-precision UTC timestamp")
    authority = _exact_object(
        root["authority"],
        field="authority",
        keys={"approves_acquisition", "approves_extraction"},
    )
    _require_literal(
        authority["approves_acquisition"],
        True,
        field="authority.approves_acquisition",
    )
    _require_literal(
        authority["approves_extraction"],
        False,
        field="authority.approves_extraction",
    )
    archive = _exact_object(
        root["archive_identity"],
        field="archive_identity",
        keys={
            "archive_id",
            "filename",
            "url",
            "size_bytes",
            "md5",
            "sha256",
            "allowed_redirect_urls",
            "allowed_redirect_origins",
        },
    )
    expected_archive_values: dict[str, object] = {
        "archive_id": identity.archive_id,
        "filename": identity.filename,
        "url": identity.url,
        "size_bytes": identity.size_bytes,
        "md5": identity.md5,
        "sha256": identity.sha256,
        "allowed_redirect_urls": list(identity.allowed_redirect_urls),
        "allowed_redirect_origins": list(identity.allowed_redirect_origins),
    }
    for field, expected in expected_archive_values.items():
        _require_literal(archive[field], expected, field=f"archive_identity.{field}")
    destination_path = _exact_string(root["destination_path"], field="destination_path")
    destination = Path(destination_path)
    if not destination.is_absolute() or str(destination) != destination_path:
        raise ArchiveError("destination_path must be one canonical absolute path")
    return AuthorizedArchiveAcquisition._from_validated_record(
        identity=identity,
        authorization_record_id=record_id,
        authorization_record_sha256=hashlib.sha256(record_bytes).hexdigest(),
        destination_path=destination_path,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at,
    )


@dataclass(frozen=True, slots=True)
class ArchiveVerification:
    """Exact identity observed from a verified local archive."""

    archive_id: str
    filename: str
    source_url: str
    size_bytes: int
    md5: str
    sha256: str
    resolved_url: str | None
    redirect_chain: tuple[str, ...]
    authorization_record_id: str | None
    authorization_record_sha256: str | None


@dataclass(frozen=True, slots=True)
class TarLimits:
    """Fail-closed bounds applied before any member is extracted."""

    max_members: int = 250_000
    max_member_size_bytes: int = 8 * 1024 * 1024 * 1024
    max_expanded_size_bytes: int = 256 * 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        for field, value in (
            ("max_members", self.max_members),
            ("max_member_size_bytes", self.max_member_size_bytes),
            ("max_expanded_size_bytes", self.max_expanded_size_bytes),
        ):
            if type(value) is not int or value <= 0:
                raise ArchiveError(f"{field} must be a positive integer")


DEFAULT_TAR_LIMITS = TarLimits()


@dataclass(frozen=True, slots=True)
class TarMemberRecord:
    """Canonical metadata for one safe TAR member."""

    path: str
    kind: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class TarInventory:
    """Read-only inventory produced without extracting archive content."""

    members: tuple[TarMemberRecord, ...]
    file_count: int
    expanded_size_bytes: int
    archive_sha256: str

    @property
    def member_count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class TarStructuralMemberRecord:
    """Inert header metadata for one member; never an extraction instruction."""

    path: str
    kind: str
    size_bytes: int
    link_target: str | None

    def __post_init__(self) -> None:
        if type(self.path) is not str or not self.path:
            raise ArchiveError("structural member path must be non-empty text")
        if type(self.kind) is not str or self.kind not in {
            "directory",
            "file",
            "symlink",
            "hardlink",
            "device",
            "fifo",
            "sparse",
            "non_regular",
        }:
            raise ArchiveError("structural member kind is unsupported")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ArchiveError("structural member size_bytes must be a non-negative integer")
        if self.kind in {"symlink", "hardlink"}:
            if type(self.link_target) is not str or not self.link_target:
                raise ArchiveError("link structural member requires a non-empty link_target")
            if "\x00" in self.link_target:
                raise ArchiveError("link structural member target contains NUL")
        elif self.link_target is not None:
            raise ArchiveError("non-link structural member cannot declare a link_target")


@dataclass(frozen=True, slots=True)
class TarStructuralAudit:
    """Bounded header-only evidence that never marks special members extractable."""

    members: tuple[TarStructuralMemberRecord, ...]
    regular_file_count: int
    non_regular_member_count: int
    expanded_regular_size_bytes: int
    archive_sha256: str
    strict_extraction_compatible: bool

    @property
    def member_count(self) -> int:
        return len(self.members)


@dataclass(frozen=True, slots=True)
class TarRegularSliceMember:
    """One exact regular-file member selected from a bound structural audit."""

    path: str
    size_bytes: int

    def __post_init__(self) -> None:
        if type(self.path) is not str or not self.path:
            raise ArchiveError("regular slice member path must be non-empty text")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ArchiveError("regular slice member size_bytes must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class TarExtractionReport:
    """Evidence returned after atomic extraction publication."""

    archive_sha256: str
    destination: str
    extracted_files: tuple[ExtractedFileReceipt, ...]
    expanded_size_bytes: int


@dataclass(frozen=True, slots=True)
class ExtractedFileReceipt:
    """Exact identity of one file copied into the validated staging tree."""

    path: str
    size_bytes: int
    sha256: str


def _open_regular_readonly(path: Path) -> tuple[BinaryIO, os.stat_result]:
    try:
        path_metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ArchiveError(f"cannot inspect archive {path}: {exc}") from exc
    if stat.S_ISLNK(path_metadata.st_mode) or not stat.S_ISREG(path_metadata.st_mode):
        raise ArchiveError(f"archive is not a regular non-symlink file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ArchiveError(f"cannot open regular non-symlink archive {path}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ArchiveError(f"archive is not a regular file: {path}")
        if _metadata_signature(metadata) != _metadata_signature(path_metadata):
            raise ArchiveError(f"archive path changed while it was being opened: {path}")
        handle = os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise
    return handle, metadata


def _metadata_signature(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _digest_open(handle: BinaryIO, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    handle.seek(0)
    while chunk := handle.read(_COPY_CHUNK_SIZE):
        digest.update(chunk)
    handle.seek(0)
    return digest.hexdigest()


def _verify_open_archive(
    handle: BinaryIO,
    initial_metadata: os.stat_result,
    identity: PublishedArchiveIdentity,
) -> ArchiveVerification:
    if initial_metadata.st_size != identity.size_bytes:
        raise ArchiveError(
            f"archive size mismatch for {identity.archive_id}: "
            f"expected {identity.size_bytes}, got {initial_metadata.st_size}"
        )
    actual_md5 = _digest_open(handle, "md5")
    if actual_md5 != identity.md5:
        raise ArchiveError(
            f"archive MD5 mismatch for {identity.archive_id}: "
            f"expected {identity.md5}, got {actual_md5}"
        )
    actual_sha256 = _digest_open(handle, "sha256")
    if identity.sha256 is not None and actual_sha256 != identity.sha256:
        raise ArchiveError(
            f"archive SHA-256 mismatch for {identity.archive_id}: "
            f"expected {identity.sha256}, got {actual_sha256}"
        )
    final_metadata = os.fstat(handle.fileno())
    if _metadata_signature(final_metadata) != _metadata_signature(initial_metadata):
        raise ArchiveError("archive changed while its identity was being verified")
    return ArchiveVerification(
        archive_id=identity.archive_id,
        filename=identity.filename,
        source_url=identity.url,
        size_bytes=identity.size_bytes,
        md5=actual_md5,
        sha256=actual_sha256,
        resolved_url=None,
        redirect_chain=(),
        authorization_record_id=None,
        authorization_record_sha256=None,
    )


def _assert_path_is_open_file(path: Path, handle: BinaryIO) -> None:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise ArchiveError(f"archive path changed during verification: {path}") from exc
    if _metadata_signature(current) != _metadata_signature(os.fstat(handle.fileno())):
        raise ArchiveError(f"archive path changed during verification: {path}")


def verify_archive(
    path: os.PathLike[str] | str,
    identity: PublishedArchiveIdentity,
) -> ArchiveVerification:
    """Verify size and publisher MD5 before computing the local SHA-256."""

    archive = Path(path)
    handle, metadata = _open_regular_readonly(archive)
    with handle:
        result = _verify_open_archive(handle, metadata, identity)
        _assert_path_is_open_file(archive, handle)
    return result


def _header(response: object, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get(name)
    return value.strip() if type(value) is str else None


def _decimal_header(response: object, name: str) -> int:
    value = _header(response, name)
    if value is None or not value.isdecimal():
        raise ArchiveError(f"download response requires an exact {name} header")
    return int(value)


def _validate_download_response(
    response: object,
    identity: PublishedArchiveIdentity,
    *,
    existing_bytes: int,
) -> None:
    status = getattr(response, "status", None)
    if status is None:
        status = response.getcode()  # type: ignore[attr-defined]
    expected_status = 206 if existing_bytes else 200
    if status != expected_status:
        raise ArchiveError(
            f"download HTTP status mismatch: expected {expected_status}, got {status}"
        )
    final_url = response.geturl()  # type: ignore[attr-defined]
    try:
        final_parsed = _validate_https_url(final_url, field="download final URL")
    except ArchiveError as exc:
        raise ArchiveError("download redirected to an unsafe URL") from exc
    if final_url != identity.url and (
        final_url not in identity.allowed_redirect_urls
        or _origin(final_parsed) not in identity.allowed_redirect_origins
    ):
        raise ArchiveError("download final URL is not in the exact redirect allowlist")
    content_encoding = _header(response, "Content-Encoding")
    if content_encoding is not None and content_encoding.lower() != "identity":
        raise ArchiveError("encoded HTTP responses cannot preserve the archive byte identity")
    remaining = identity.size_bytes - existing_bytes
    if _decimal_header(response, "Content-Length") != remaining:
        raise ArchiveError("download Content-Length does not match the expected remaining bytes")
    content_range = _header(response, "Content-Range")
    if existing_bytes:
        match = _CONTENT_RANGE.fullmatch(content_range or "")
        expected_end = identity.size_bytes - 1
        if match is None or tuple(map(int, match.groups())) != (
            existing_bytes,
            expected_end,
            identity.size_bytes,
        ):
            raise ArchiveError("download Content-Range does not exactly match the requested resume")
    elif content_range is not None:
        raise ArchiveError("full download response must not contain Content-Range")


class _ExactRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, identity: PublishedArchiveIdentity) -> None:
        super().__init__()
        self._identity = identity
        self.redirect_chain: list[str] = []

    def redirect_request(  # type: ignore[override]
        self,
        request: urllib.request.Request,
        file_pointer: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> urllib.request.Request | None:
        resolved = urllib.parse.urljoin(request.full_url, new_url)
        parsed = _validate_https_url(resolved, field="download redirect URL")
        if (
            resolved not in self._identity.allowed_redirect_urls
            or _origin(parsed) not in self._identity.allowed_redirect_origins
        ):
            raise ArchiveError("download redirect hop is not exactly allowlisted")
        if resolved in self.redirect_chain:
            raise ArchiveError("download redirect chain contains a repeated URL")
        self.redirect_chain.append(resolved)
        return super().redirect_request(
            request,
            file_pointer,  # type: ignore[arg-type]
            code,
            message,
            headers,  # type: ignore[arg-type]
            resolved,
        )


def _open_download_response(
    identity: PublishedArchiveIdentity,
    request: urllib.request.Request,
    *,
    timeout_seconds: float,
) -> tuple[object, tuple[str, ...]]:
    redirect_handler = _ExactRedirectHandler(identity)
    opener = urllib.request.build_opener(redirect_handler)
    response = opener.open(request, timeout=timeout_seconds)  # noqa: S310
    return response, tuple(redirect_handler.redirect_chain)


def _open_partial_for_write(
    path: Path,
    *,
    append: bool,
    expected_metadata: os.stat_result | None,
) -> BinaryIO:
    flags = os.O_WRONLY | getattr(os, "O_BINARY", 0)
    if expected_metadata is None:
        flags |= os.O_CREAT | os.O_EXCL
    elif append:
        flags |= os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ArchiveError(f"cannot open staged partial archive {path}: {exc}") from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        os.close(descriptor)
        raise ArchiveError(f"staged partial archive must be one singly-linked regular file: {path}")
    if expected_metadata is not None and not _same_inode(metadata, expected_metadata):
        os.close(descriptor)
        raise ArchiveError("staged partial archive changed before the download write")
    if not append:
        try:
            os.ftruncate(descriptor, 0)
        except OSError:
            os.close(descriptor)
            raise
    return os.fdopen(descriptor, "ab" if append else "wb")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and left.st_size == right.st_size
        and stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
    )


def _same_regular_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev == right.st_dev
        and left.st_ino == right.st_ino
        and stat.S_ISREG(left.st_mode)
        and stat.S_ISREG(right.st_mode)
    )


def _unlink_if_inode(path: Path, expected: os.stat_result) -> None:
    try:
        current = os.stat(path, follow_symlinks=False)
    except OSError:
        return
    if _same_regular_object(current, expected):
        try:
            path.unlink()
        except OSError:
            pass


def _require_stable_open_sha256(
    handle: BinaryIO,
    expected_sha256: str,
    *,
    phase: str,
) -> None:
    before = os.fstat(handle.fileno())
    actual_sha256 = _digest_open(handle, "sha256")
    after = os.fstat(handle.fileno())
    if _metadata_signature(after) != _metadata_signature(before):
        raise ArchiveError(f"archive metadata changed during {phase}")
    if actual_sha256 != expected_sha256:
        raise ArchiveError(f"archive bytes changed during {phase}")


def _publish_verified_file_no_replace(
    handle: BinaryIO,
    staged: Path,
    destination: Path,
    *,
    expected_sha256: str,
) -> None:
    verified_metadata = os.fstat(handle.fileno())
    bound = destination.parent / f".{destination.name}.verified-{secrets.token_hex(16)}"
    bound_metadata: os.stat_result | None = None
    published_metadata: os.stat_result | None = None
    destination_created = False
    try:
        os.link(staged, bound, follow_symlinks=False)
        bound_metadata = os.stat(bound, follow_symlinks=False)
        if not _same_inode(bound_metadata, os.fstat(handle.fileno())):
            raise ArchiveError("staged archive changed before verified publication")
        _require_stable_open_sha256(
            handle,
            expected_sha256,
            phase="verified inode binding",
        )
        try:
            os.link(bound, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise ArchiveError(f"refusing to overwrite archive: {destination}") from exc
        destination_created = True
        published_metadata = os.stat(destination, follow_symlinks=False)
        if not _same_inode(published_metadata, os.fstat(handle.fileno())):
            raise ArchiveError("published archive is not the verified archive inode")
        _require_stable_open_sha256(
            handle,
            expected_sha256,
            phase="final archive publication",
        )
    except ArchiveError:
        if destination_created:
            _unlink_if_inode(destination, os.fstat(handle.fileno()))
        raise
    except OSError as exc:
        if destination_created:
            _unlink_if_inode(destination, os.fstat(handle.fileno()))
        raise ArchiveError(f"cannot atomically publish archive {destination}: {exc}") from exc
    finally:
        if bound_metadata is not None:
            _unlink_if_inode(bound, bound_metadata)
    current_verified_metadata = os.fstat(handle.fileno())
    if _same_inode(verified_metadata, current_verified_metadata):
        _unlink_if_inode(staged, current_verified_metadata)
    _fsync_directory(destination.parent)


def _verify_and_publish_partial(
    identity: PublishedArchiveIdentity,
    partial: Path,
    target: Path,
) -> ArchiveVerification:
    handle, metadata = _open_regular_readonly(partial)
    with handle:
        result = _verify_open_archive(handle, metadata, identity)
        _assert_path_is_open_file(partial, handle)
        _publish_verified_file_no_replace(
            handle,
            partial,
            target,
            expected_sha256=result.sha256,
        )
    return result


@contextmanager
def _exclusive_acquisition_lock(target: Path) -> Iterator[None]:
    if fcntl is None:
        raise ArchiveError("archive acquisition locking requires POSIX fcntl")
    lock = target.parent / f".{target.name}.acquire.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock, flags, 0o600)
    except OSError as exc:
        raise ArchiveError(f"cannot create archive acquisition lock {lock}: {exc}") from exc
    try:
        lock_metadata = os.fstat(descriptor)
        if not stat.S_ISREG(lock_metadata.st_mode) or lock_metadata.st_nlink != 1:
            raise ArchiveError("archive acquisition lock must be one regular file")
        current_lock = os.stat(lock, follow_symlinks=False)
        if not _same_inode(lock_metadata, current_lock):
            raise ArchiveError("archive acquisition lock path changed while opening")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ArchiveError(f"archive acquisition is already active: {target}") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode())
        os.fsync(descriptor)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(descriptor)
        _fsync_directory(target.parent)


def _download_archive_locked(
    identity: PublishedArchiveIdentity,
    destination: os.PathLike[str] | str,
    *,
    chunk_size: int = _COPY_CHUNK_SIZE,
    timeout_seconds: float = 120.0,
) -> ArchiveVerification:
    """Download into ``<filename>.part`` and atomically publish verified bytes.

    A partial response is accepted only when status, ``Content-Range``, and
    ``Content-Length`` describe the exact unresolved suffix.  A validated 200
    full response safely restarts a resume that the server ignored.
    """

    if type(chunk_size) is not int or not 0 < chunk_size <= _MAX_DOWNLOAD_CHUNK_SIZE:
        raise ArchiveError(f"chunk_size must be between 1 and {_MAX_DOWNLOAD_CHUNK_SIZE} bytes")
    if type(timeout_seconds) not in (int, float) or timeout_seconds <= 0:
        raise ArchiveError("timeout_seconds must be positive")
    target = Path(destination)
    if target.name != identity.filename:
        raise ArchiveError("download destination basename must equal the published filename")
    target.parent.mkdir(parents=True, exist_ok=True)
    parent_metadata = os.lstat(target.parent)
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ArchiveError("download destination parent must be a real directory")
    if _lexists(target):
        return verify_archive(target, identity)

    partial = target.with_name(f"{target.name}.part")
    existing_bytes = 0
    partial_metadata: os.stat_result | None = None
    if _lexists(partial):
        partial_metadata = os.lstat(partial)
        if not stat.S_ISREG(partial_metadata.st_mode) or partial_metadata.st_nlink != 1:
            raise ArchiveError(
                f"staged partial archive must be one singly-linked regular file: {partial}"
            )
        existing_bytes = partial_metadata.st_size
    if existing_bytes > identity.size_bytes:
        raise ArchiveError("staged partial archive exceeds the published archive size")
    if existing_bytes == identity.size_bytes:
        return _verify_and_publish_partial(identity, partial, target)

    request = urllib.request.Request(
        identity.url,
        headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "identity"},
    )
    if existing_bytes:
        request.add_header("Range", f"bytes={existing_bytes}-")
    try:
        response, redirect_chain = _open_download_response(
            identity,
            request,
            timeout_seconds=timeout_seconds,
        )
        with response:
            status = getattr(response, "status", None)
            if status is None:
                status = response.getcode()
            response_offset = 0 if existing_bytes and status == 200 else existing_bytes
            _validate_download_response(response, identity, existing_bytes=response_offset)
            resolved_url = response.geturl()
            if resolved_url != identity.url and (
                not redirect_chain or redirect_chain[-1] != resolved_url
            ):
                raise ArchiveError("download final URL was not validated as a redirect hop")
            received = 0
            with _open_partial_for_write(
                partial,
                append=bool(response_offset),
                expected_metadata=partial_metadata,
            ) as output:
                while chunk := response.read(chunk_size):
                    if type(chunk) is not bytes:
                        raise ArchiveError("download response returned a non-bytes payload")
                    if received + len(chunk) > identity.size_bytes - response_offset:
                        raise ArchiveError("download response exceeded the published archive size")
                    output.write(chunk)
                    received += len(chunk)
                output.flush()
                os.fsync(output.fileno())
    except ArchiveError:
        raise
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        raise ArchiveError(f"download failed for {identity.archive_id}: {exc}") from exc
    if received != identity.size_bytes - response_offset:
        raise ArchiveError(
            f"download ended early: expected {identity.size_bytes - response_offset} bytes, "
            f"received {received}"
        )
    result = _verify_and_publish_partial(identity, partial, target)
    return replace(
        result,
        resolved_url=resolved_url,
        redirect_chain=redirect_chain,
    )


def download_archive(
    authorization: AuthorizedArchiveAcquisition,
    destination: os.PathLike[str] | str,
    *,
    chunk_size: int = _COPY_CHUNK_SIZE,
    timeout_seconds: float = 120.0,
) -> ArchiveVerification:
    """Acquire one archive under an exclusive per-target writer lock."""

    if (
        type(authorization) is not AuthorizedArchiveAcquisition
        or authorization._capability is not _AUTHORIZATION_CAPABILITY
    ):
        raise ArchiveError("download requires an AuthorizedArchiveAcquisition")
    identity = authorization.identity
    target = Path(destination)
    if str(target.absolute()) != authorization.destination_path:
        raise ArchiveError("download destination is outside the exact authorized scope")
    if target.name != identity.filename:
        raise ArchiveError("download destination basename must equal the published filename")
    target.parent.mkdir(parents=True, exist_ok=True)
    parent_metadata = os.lstat(target.parent)
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ArchiveError("download destination parent must be a real directory")
    with _exclusive_acquisition_lock(target):
        result = _download_archive_locked(
            identity,
            target,
            chunk_size=chunk_size,
            timeout_seconds=timeout_seconds,
        )
    return replace(
        result,
        authorization_record_id=authorization.authorization_record_id,
        authorization_record_sha256=authorization.authorization_record_sha256,
    )


def _normalize_member_path(raw: object, *, is_directory: bool = False) -> PurePosixPath:
    if type(raw) is not str or not raw or "\x00" in raw:
        raise ArchiveError("TAR member path must be a non-empty text path")
    if "\\" in raw:
        raise ArchiveError(f"TAR member path contains a prohibited backslash: {raw!r}")
    if raw.startswith("/"):
        raise ArchiveError(f"absolute TAR member path is prohibited: {raw!r}")
    raw_parts = raw.split("/")
    if raw_parts and len(raw_parts[0]) >= 2 and raw_parts[0][1] == ":":
        raise ArchiveError(f"absolute TAR member path is prohibited: {raw!r}")
    if ".." in raw_parts:
        raise ArchiveError(f"TAR path traversal is prohibited: {raw!r}")
    if is_directory and raw_parts[-1] == "":
        raw_parts = raw_parts[:-1]
    if not raw_parts or any(part in ("", ".") for part in raw_parts):
        raise ArchiveError(f"TAR member path is not canonical: {raw!r}")
    parts = [unicodedata.normalize("NFC", part) for part in raw_parts]
    if not parts or any(part in ("", ".", "..") or "\x00" in part for part in parts):
        raise ArchiveError(f"TAR member path has no safe normalized target: {raw!r}")
    return PurePosixPath(*parts)


def _is_sparse(member: tarfile.TarInfo) -> bool:
    sparse_map = getattr(member, "sparse", None)
    sparse_headers = any(
        key.startswith("GNU.sparse") or key == "SCHILY.realsize" for key in member.pax_headers
    )
    return member.type == tarfile.GNUTYPE_SPARSE or sparse_map is not None or sparse_headers


def _classify_member(member: tarfile.TarInfo) -> tuple[str, int]:
    if _is_sparse(member):
        raise ArchiveError(f"sparse TAR member is prohibited: {member.name!r}")
    if member.isdir():
        if member.size != 0:
            raise ArchiveError(f"TAR directory has a non-zero size: {member.name!r}")
        return "directory", 0
    if member.isreg():
        if type(member.size) is not int or member.size < 0:
            raise ArchiveError(f"TAR member has an invalid size: {member.name!r}")
        return "file", member.size
    if member.issym():
        label = "symlink"
    elif member.islnk():
        label = "hardlink"
    elif member.ischr() or member.isblk():
        label = "device"
    elif member.isfifo():
        label = "FIFO"
    else:
        label = "non-regular"
    raise ArchiveError(f"{label} TAR member is prohibited: {member.name!r}")


def _classify_structural_member(member: tarfile.TarInfo) -> tuple[str, int, str | None]:
    if type(member.size) is not int or member.size < 0:
        raise ArchiveError(f"TAR member has an invalid size: {member.name!r}")
    if _is_sparse(member):
        return "sparse", member.size, None
    if member.isdir():
        if member.size != 0:
            raise ArchiveError(f"TAR directory has a non-zero size: {member.name!r}")
        return "directory", 0, None
    if member.isreg():
        return "file", member.size, None
    if member.issym():
        return "symlink", member.size, member.linkname
    if member.islnk():
        return "hardlink", member.size, member.linkname
    if member.ischr() or member.isblk():
        return "device", member.size, None
    if member.isfifo():
        return "fifo", member.size, None
    return "non_regular", member.size, None


def _audit_open_tar_structure(
    handle: BinaryIO,
    *,
    limits: TarLimits,
    archive_sha256: str,
) -> TarStructuralAudit:
    handle.seek(0)
    records: list[TarStructuralMemberRecord] = []
    seen: set[PurePosixPath] = set()
    leaf_paths: set[PurePosixPath] = set()
    required_directories: set[PurePosixPath] = set()
    expanded_regular_size = 0
    regular_file_count = 0
    non_regular_member_count = 0
    try:
        with tarfile.open(fileobj=handle, mode="r:") as source:
            for member in source:
                if len(records) >= limits.max_members:
                    raise ArchiveError(f"TAR member count exceeds limit {limits.max_members}")
                kind, size_bytes, link_target = _classify_structural_member(member)
                path = _normalize_member_path(member.name, is_directory=kind == "directory")
                if path in seen:
                    raise ArchiveError(f"duplicate normalized TAR member path: {path}")
                if size_bytes > limits.max_member_size_bytes:
                    raise ArchiveError(
                        f"TAR member {path} exceeds size limit {limits.max_member_size_bytes}"
                    )
                ancestors = tuple(parent for parent in path.parents if str(parent) != ".")
                if any(parent in leaf_paths for parent in ancestors):
                    raise ArchiveError(f"TAR leaf/directory topology conflicts at {path}")
                if kind != "directory" and path in required_directories:
                    raise ArchiveError(f"TAR leaf/directory topology conflicts at {path}")
                seen.add(path)
                required_directories.update(ancestors)
                if kind == "file":
                    next_expanded_size = expanded_regular_size + size_bytes
                    if next_expanded_size > limits.max_expanded_size_bytes:
                        raise ArchiveError(
                            "TAR expanded regular-file size exceeds limit "
                            f"{limits.max_expanded_size_bytes}"
                        )
                    expanded_regular_size = next_expanded_size
                    regular_file_count += 1
                elif kind != "directory":
                    non_regular_member_count += 1
                if kind != "directory":
                    leaf_paths.add(path)
                records.append(TarStructuralMemberRecord(str(path), kind, size_bytes, link_target))
    except ArchiveError:
        raise
    except (OSError, EOFError, ValueError, tarfile.TarError) as exc:
        raise ArchiveError(f"cannot audit TAR archive structure: {exc}") from exc
    finally:
        handle.seek(0)
    return TarStructuralAudit(
        members=tuple(records),
        regular_file_count=regular_file_count,
        non_regular_member_count=non_regular_member_count,
        expanded_regular_size_bytes=expanded_regular_size,
        archive_sha256=archive_sha256,
        strict_extraction_compatible=non_regular_member_count == 0,
    )


def _inventory_open_tar(
    handle: BinaryIO,
    *,
    limits: TarLimits,
    archive_sha256: str,
) -> TarInventory:
    handle.seek(0)
    records: list[TarMemberRecord] = []
    seen: set[PurePosixPath] = set()
    regular_paths: set[PurePosixPath] = set()
    required_directories: set[PurePosixPath] = set()
    expanded_size = 0
    file_count = 0
    try:
        with tarfile.open(fileobj=handle, mode="r:") as source:
            for member in source:
                if len(records) >= limits.max_members:
                    raise ArchiveError(f"TAR member count exceeds limit {limits.max_members}")
                kind, size_bytes = _classify_member(member)
                path = _normalize_member_path(member.name, is_directory=kind == "directory")
                if path in seen:
                    raise ArchiveError(f"duplicate normalized TAR member path: {path}")
                if size_bytes > limits.max_member_size_bytes:
                    raise ArchiveError(
                        f"TAR member {path} exceeds size limit {limits.max_member_size_bytes}"
                    )
                next_expanded_size = expanded_size + size_bytes
                if next_expanded_size > limits.max_expanded_size_bytes:
                    raise ArchiveError(
                        f"TAR expanded size exceeds limit {limits.max_expanded_size_bytes}"
                    )
                ancestors = tuple(parent for parent in path.parents if str(parent) != ".")
                if any(parent in regular_paths for parent in ancestors):
                    raise ArchiveError(f"TAR file/directory topology conflicts at {path}")
                if kind == "file" and path in required_directories:
                    raise ArchiveError(f"TAR file/directory topology conflicts at {path}")
                seen.add(path)
                required_directories.update(ancestors)
                if kind == "file":
                    regular_paths.add(path)
                    file_count += 1
                expanded_size = next_expanded_size
                records.append(TarMemberRecord(str(path), kind, size_bytes))
    except ArchiveError:
        raise
    except (OSError, EOFError, ValueError, tarfile.TarError) as exc:
        raise ArchiveError(f"cannot inventory TAR archive: {exc}") from exc
    finally:
        handle.seek(0)
    return TarInventory(tuple(records), file_count, expanded_size, archive_sha256)


def inventory_tar(
    archive_path: os.PathLike[str] | str,
    *,
    expected_sha256: str,
    limits: TarLimits = DEFAULT_TAR_LIMITS,
) -> TarInventory:
    """Return a bounded inventory only after verifying the pinned SHA-256."""

    expected_sha256 = _lower_hex(expected_sha256, length=64, field="expected_sha256")
    if not isinstance(limits, TarLimits):
        raise ArchiveError("limits must be a TarLimits instance")
    archive = Path(archive_path)
    if archive.suffix != ".tar":
        raise ArchiveError("inventory accepts only an uncompressed .tar archive")
    handle, initial_metadata = _open_regular_readonly(archive)
    with handle:
        actual_sha256 = _digest_open(handle, "sha256")
        if actual_sha256 != expected_sha256:
            raise ArchiveError(
                f"archive SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        if _metadata_signature(os.fstat(handle.fileno())) != _metadata_signature(initial_metadata):
            raise ArchiveError("archive changed while its SHA-256 was being verified")
        result = _inventory_open_tar(
            handle,
            limits=limits,
            archive_sha256=actual_sha256,
        )
        _assert_path_is_open_file(archive, handle)
        return result


def audit_tar_structure(
    archive_path: os.PathLike[str] | str,
    *,
    expected_sha256: str,
    limits: TarLimits = DEFAULT_TAR_LIMITS,
) -> TarStructuralAudit:
    """Record bounded inert TAR headers without following links or extracting data.

    Unlike :func:`inventory_tar`, this function records non-regular member kinds
    as incompatibility evidence. It never treats them as safe for extraction.
    """

    expected_sha256 = _lower_hex(expected_sha256, length=64, field="expected_sha256")
    if not isinstance(limits, TarLimits):
        raise ArchiveError("limits must be a TarLimits instance")
    archive = Path(archive_path)
    if archive.suffix != ".tar":
        raise ArchiveError("structural audit accepts only an uncompressed .tar archive")
    handle, initial_metadata = _open_regular_readonly(archive)
    with handle:
        actual_sha256 = _digest_open(handle, "sha256")
        if actual_sha256 != expected_sha256:
            raise ArchiveError(
                f"archive SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
            )
        if _metadata_signature(os.fstat(handle.fileno())) != _metadata_signature(initial_metadata):
            raise ArchiveError("archive changed while its SHA-256 was being verified")
        result = _audit_open_tar_structure(
            handle,
            limits=limits,
            archive_sha256=actual_sha256,
        )
        _assert_path_is_open_file(archive, handle)
        return result


def _normalize_allowlist(allowed_files: tuple[str, ...]) -> tuple[str, ...]:
    if type(allowed_files) is not tuple or not allowed_files:
        raise ArchiveError("allowed_files must be a non-empty tuple of exact paths")
    normalized: list[str] = []
    for raw in allowed_files:
        path = _normalize_member_path(raw)
        canonical = str(path)
        if raw != canonical:
            raise ArchiveError(f"allowlist path must already be canonical: {raw!r}")
        normalized.append(canonical)
    if len(set(normalized)) != len(normalized):
        raise ArchiveError("allowed_files must not contain duplicate paths")
    return tuple(normalized)


def _validate_bound_structural_audit(
    audit: TarStructuralAudit,
    *,
    expected_sha256: str,
    limits: TarLimits,
) -> None:
    """Validate that an in-memory structural audit is internally exact and bounded."""

    if type(audit) is not TarStructuralAudit:
        raise ArchiveError("expected_structure must be a TarStructuralAudit")
    try:
        audit_sha256 = _lower_hex(
            audit.archive_sha256,
            length=64,
            field="expected_structure.archive_sha256",
        )
    except AttributeError as exc:
        raise ArchiveError("expected_structure is malformed") from exc
    if audit_sha256 != expected_sha256:
        raise ArchiveError("bound structural audit SHA-256 does not match expected archive")
    if type(audit.members) is not tuple:
        raise ArchiveError("bound structural audit members must be a tuple")
    for field in (
        "regular_file_count",
        "non_regular_member_count",
        "expanded_regular_size_bytes",
    ):
        value = getattr(audit, field, None)
        if type(value) is not int or value < 0:
            raise ArchiveError(f"bound structural audit {field} must be a non-negative integer")
    if type(audit.strict_extraction_compatible) is not bool:
        raise ArchiveError("bound structural audit strict_extraction_compatible must be a boolean")
    if len(audit.members) > limits.max_members:
        raise ArchiveError(f"bound structural audit exceeds member limit {limits.max_members}")

    seen: set[PurePosixPath] = set()
    leaf_paths: set[PurePosixPath] = set()
    required_directories: set[PurePosixPath] = set()
    regular_file_count = 0
    non_regular_member_count = 0
    expanded_regular_size = 0
    for index, record in enumerate(audit.members):
        if type(record) is not TarStructuralMemberRecord:
            raise ArchiveError(f"bound structural audit member {index} is not a structural record")
        try:
            record = TarStructuralMemberRecord(
                path=record.path,
                kind=record.kind,
                size_bytes=record.size_bytes,
                link_target=record.link_target,
            )
        except (ArchiveError, AttributeError) as exc:
            raise ArchiveError(
                f"bound structural audit member {index} is malformed: {exc}"
            ) from exc
        path = _normalize_member_path(
            record.path,
            is_directory=record.kind == "directory",
        )
        if str(path) != record.path:
            raise ArchiveError(f"bound structural audit path is not canonical: {record.path!r}")
        if path in seen:
            raise ArchiveError(f"duplicate bound structural audit path: {path}")
        if record.size_bytes > limits.max_member_size_bytes:
            raise ArchiveError(
                f"bound structural audit member {path} exceeds size limit "
                f"{limits.max_member_size_bytes}"
            )
        ancestors = tuple(parent for parent in path.parents if str(parent) != ".")
        if any(parent in leaf_paths for parent in ancestors):
            raise ArchiveError(f"bound structural audit topology conflicts at {path}")
        if record.kind != "directory" and path in required_directories:
            raise ArchiveError(f"bound structural audit topology conflicts at {path}")
        seen.add(path)
        required_directories.update(ancestors)
        if record.kind == "file":
            regular_file_count += 1
            expanded_regular_size += record.size_bytes
            if expanded_regular_size > limits.max_expanded_size_bytes:
                raise ArchiveError(
                    "bound structural audit expanded regular-file size exceeds limit "
                    f"{limits.max_expanded_size_bytes}"
                )
        elif record.kind != "directory":
            non_regular_member_count += 1
        if record.kind != "directory":
            leaf_paths.add(path)

    expected_values = (
        ("regular_file_count", audit.regular_file_count, regular_file_count),
        (
            "non_regular_member_count",
            audit.non_regular_member_count,
            non_regular_member_count,
        ),
        (
            "expanded_regular_size_bytes",
            audit.expanded_regular_size_bytes,
            expanded_regular_size,
        ),
        (
            "strict_extraction_compatible",
            audit.strict_extraction_compatible,
            non_regular_member_count == 0,
        ),
    )
    for field, actual, expected in expected_values:
        if type(actual) is not type(expected) or actual != expected:
            raise ArchiveError(
                f"bound structural audit {field} mismatch: expected {expected!r}, got {actual!r}"
            )


def _normalize_regular_slice(
    selected_files: tuple[TarRegularSliceMember, ...],
    *,
    audit: TarStructuralAudit,
    allowed_root: str,
) -> tuple[TarRegularSliceMember, ...]:
    root = _normalize_member_path(allowed_root, is_directory=True)
    if str(root) != allowed_root:
        raise ArchiveError("allowed_root must already be one canonical TAR directory path")
    if type(selected_files) is not tuple or not selected_files:
        raise ArchiveError("selected_files must be a non-empty tuple")
    selected: list[TarRegularSliceMember] = []
    for index, item in enumerate(selected_files):
        if type(item) is not TarRegularSliceMember:
            raise ArchiveError(f"selected_files[{index}] must be a TarRegularSliceMember")
        try:
            item = TarRegularSliceMember(path=item.path, size_bytes=item.size_bytes)
        except (ArchiveError, AttributeError) as exc:
            raise ArchiveError(f"selected_files[{index}] is malformed: {exc}") from exc
        path = _normalize_member_path(item.path)
        if str(path) != item.path:
            raise ArchiveError(f"selected regular path must already be canonical: {item.path!r}")
        if "dso" in path.parts:
            raise ArchiveError(f"selected regular path under a DSO tree is prohibited: {item.path}")
        if path == root or root not in path.parents:
            raise ArchiveError(
                f"selected regular path is outside allowed_root {allowed_root!r}: {item.path}"
            )
        selected.append(item)
    if len({item.path for item in selected}) != len(selected):
        raise ArchiveError("selected_files must not contain duplicate paths")

    audited_by_path = {record.path: record for record in audit.members}
    for item in selected:
        record = audited_by_path.get(item.path)
        if record is None:
            raise ArchiveError(f"selected regular TAR member is absent from audit: {item.path}")
        if record.kind != "file":
            raise ArchiveError(f"selected TAR member is not audited as a regular file: {item.path}")
        if record.size_bytes != item.size_bytes:
            raise ArchiveError(
                f"selected TAR member size differs from audit for {item.path}: "
                f"expected {item.size_bytes}, got {record.size_bytes}"
            )
    return tuple(selected)


def _atomic_publish_directory_no_replace(staged: Path, destination: Path) -> None:
    """Atomically rename a directory while failing if destination exists."""

    if _lexists(destination):
        raise ArchiveError(f"refusing to overwrite extraction destination: {destination}")
    source_bytes = os.fsencode(staged)
    destination_bytes = os.fsencode(destination)
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        renamex = libc.renamex_np
        renamex.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        renamex.restype = ctypes.c_int
        result = renamex(source_bytes, destination_bytes, 0x00000004)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise ArchiveError("atomic no-replace publication is unavailable on this platform")
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(-100, source_bytes, -100, destination_bytes, 1)  # RENAME_NOREPLACE
    elif os.name == "nt":
        try:
            os.rename(staged, destination)
        except FileExistsError as exc:
            raise ArchiveError(
                f"refusing to overwrite extraction destination: {destination}"
            ) from exc
        _fsync_directory(destination.parent)
        return
    else:
        raise ArchiveError("atomic no-replace publication is unavailable on this platform")
    if result != 0:
        error_number = ctypes.get_errno()
        if error_number in (errno.EEXIST, errno.ENOTEMPTY):
            raise ArchiveError(f"refusing to overwrite extraction destination: {destination}")
        raise ArchiveError(
            f"cannot atomically publish extraction destination {destination}: "
            f"{os.strerror(error_number)}"
        )
    _fsync_directory(destination.parent)


def _copy_exact_member(
    source: tarfile.TarFile,
    member: tarfile.TarInfo,
    target: Path,
    *,
    canonical_path: str,
) -> ExtractedFileReceipt:
    input_handle = source.extractfile(member)
    if input_handle is None:
        raise ArchiveError(f"cannot read allowed TAR member: {member.name!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    remaining = member.size
    digest = hashlib.sha256()
    try:
        with input_handle, target.open("xb") as output:
            while remaining:
                chunk = input_handle.read(min(_COPY_CHUNK_SIZE, remaining))
                if not chunk:
                    raise ArchiveError(f"TAR member ended early: {member.name!r}")
                output.write(chunk)
                digest.update(chunk)
                remaining -= len(chunk)
            if input_handle.read(1):
                raise ArchiveError(f"TAR member exceeded its declared size: {member.name!r}")
            output.flush()
            os.fsync(output.fileno())
    except OSError as exc:
        raise ArchiveError(f"cannot extract allowed TAR member {member.name!r}: {exc}") from exc
    return ExtractedFileReceipt(canonical_path, member.size, digest.hexdigest())


def _verify_staging_tree(
    staging: Path,
    expected: tuple[ExtractedFileReceipt, ...],
) -> None:
    expected_by_path = {receipt.path: receipt for receipt in expected}
    expected_directories = {
        str(parent)
        for receipt in expected
        for parent in PurePosixPath(receipt.path).parents
        if str(parent) != "."
    }
    observed_paths: set[str] = set()
    for current_root, directory_names, file_names in os.walk(staging, followlinks=False):
        current = Path(current_root)
        for name in directory_names:
            directory = current / name
            metadata = os.stat(directory, follow_symlinks=False)
            if not stat.S_ISDIR(metadata.st_mode):
                raise ArchiveError(f"staging validator left a non-directory path: {directory}")
            relative_directory = directory.relative_to(staging).as_posix()
            if relative_directory not in expected_directories:
                raise ArchiveError(
                    f"staging validator added an unexpected directory: {relative_directory}"
                )
        for name in file_names:
            path = current / name
            metadata = os.stat(path, follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode):
                raise ArchiveError(f"staging validator left a non-regular file: {path}")
            if metadata.st_nlink != 1:
                raise ArchiveError(f"staging validator left a multiply-linked file: {path}")
            relative = path.relative_to(staging).as_posix()
            receipt = expected_by_path.get(relative)
            if receipt is None:
                raise ArchiveError(f"staging validator added an unexpected file: {relative}")
            handle, _ = _open_regular_readonly(path)
            with handle:
                sha256 = _digest_open(handle, "sha256")
            if metadata.st_size != receipt.size_bytes or sha256 != receipt.sha256:
                raise ArchiveError(f"staging validator changed extracted file: {relative}")
            observed_paths.add(relative)
    missing = set(expected_by_path) - observed_paths
    if missing:
        raise ArchiveError(f"staging validator removed extracted files: {sorted(missing)!r}")


def _open_staging_directory(path: Path) -> tuple[int, tuple[int, int, int]]:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        raise ArchiveError(f"cannot bind regular-slice staging directory {path}: {exc}") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise ArchiveError("regular-slice staging root must be a real directory")
    return descriptor, (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _assert_same_staging_directory(
    path: Path,
    descriptor: int,
    expected: tuple[int, int, int],
) -> None:
    try:
        path_metadata = os.lstat(path)
        open_metadata = os.fstat(descriptor)
    except OSError as exc:
        raise ArchiveError(f"regular-slice staging root changed: {exc}") from exc
    path_identity = (path_metadata.st_dev, path_metadata.st_ino, path_metadata.st_mode)
    open_identity = (open_metadata.st_dev, open_metadata.st_ino, open_metadata.st_mode)
    if (
        stat.S_ISLNK(path_metadata.st_mode)
        or not stat.S_ISDIR(path_metadata.st_mode)
        or path_identity != expected
        or open_identity != expected
    ):
        raise ArchiveError("regular-slice staging root identity changed")


def _remove_regular_slice_staging(path: Path) -> None:
    """Remove only the staging entry itself; never traverse a substituted link."""

    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return
    except OSError:
        return
    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        shutil.rmtree(path, ignore_errors=True)
        return
    try:
        path.unlink()
    except OSError:
        return


def extract_tar(
    archive_path: os.PathLike[str] | str,
    destination: os.PathLike[str] | str,
    *,
    expected_sha256: str,
    allowed_files: tuple[str, ...],
    validate_staging: Callable[[Path, tuple[ExtractedFileReceipt, ...]], None],
    limits: TarLimits = DEFAULT_TAR_LIMITS,
) -> TarExtractionReport:
    """Extract an exact allowlist after SHA pinning, then publish atomically.

    All archive members are inventoried and safety-checked, including members
    that are not selected.  Only explicitly named regular files are copied.
    """

    expected_sha256 = _lower_hex(expected_sha256, length=64, field="expected_sha256")
    if not isinstance(limits, TarLimits):
        raise ArchiveError("limits must be a TarLimits instance")
    if not callable(validate_staging):
        raise ArchiveError("validate_staging must be a callable semantic gate")
    allowlist = _normalize_allowlist(allowed_files)
    output = Path(destination)
    if not output.name or output.name in (".", ".."):
        raise ArchiveError("extraction destination must name one new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent_metadata = os.lstat(output.parent)
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ArchiveError("extraction destination parent must be a real directory")
    if _lexists(output):
        raise ArchiveError(f"refusing to overwrite extraction destination: {output}")

    archive = Path(archive_path)
    if archive.suffix != ".tar":
        raise ArchiveError("extraction accepts only an uncompressed .tar archive")
    handle, initial_metadata = _open_regular_readonly(archive)
    staging: Path | None = None
    with handle:
        first_sha256 = _digest_open(handle, "sha256")
        if first_sha256 != expected_sha256:
            raise ArchiveError(
                f"archive SHA-256 mismatch: expected {expected_sha256}, got {first_sha256}"
            )
        if _metadata_signature(os.fstat(handle.fileno())) != _metadata_signature(initial_metadata):
            raise ArchiveError("archive changed while its SHA-256 was being verified")
        inventory = _inventory_open_tar(
            handle,
            limits=limits,
            archive_sha256=first_sha256,
        )
        members_by_path = {member.path: member for member in inventory.members}
        for path in allowlist:
            record = members_by_path.get(path)
            if record is None:
                raise ArchiveError(f"allowlisted TAR member is absent: {path}")
            if record.kind != "file":
                raise ArchiveError(f"allowlisted TAR member is not a regular file: {path}")

        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
        selected_paths = set(allowlist)
        copied: dict[str, ExtractedFileReceipt] = {}
        try:
            handle.seek(0)
            with tarfile.open(fileobj=handle, mode="r:") as source:
                for member in source:
                    kind, _ = _classify_member(member)
                    path = str(
                        _normalize_member_path(member.name, is_directory=kind == "directory")
                    )
                    if path not in selected_paths:
                        continue
                    if kind != "file" or path in copied:
                        raise ArchiveError(f"allowed TAR member changed during extraction: {path}")
                    copied[path] = _copy_exact_member(
                        source,
                        member,
                        staging / Path(*PurePosixPath(path).parts),
                        canonical_path=path,
                    )
            missing = selected_paths - set(copied)
            if missing:
                raise ArchiveError(
                    f"allowed TAR members disappeared during extraction: {sorted(missing)!r}"
                )
            receipts = tuple(copied[path] for path in allowlist)
            try:
                validate_staging(staging, receipts)
            except ArchiveError:
                raise
            except Exception as exc:
                raise ArchiveError(f"staging semantic validation failed: {exc}") from exc
            _verify_staging_tree(staging, receipts)
            final_sha256 = _digest_open(handle, "sha256")
            if final_sha256 != expected_sha256:
                raise ArchiveError("archive changed while allowed files were being extracted")
            _assert_path_is_open_file(archive, handle)
            _atomic_publish_directory_no_replace(staging, output)
            staging = None
        except ArchiveError:
            raise
        except (OSError, EOFError, ValueError, tarfile.TarError) as exc:
            raise ArchiveError(f"cannot extract TAR archive: {exc}") from exc
        finally:
            if staging is not None:
                shutil.rmtree(staging, ignore_errors=True)

    return TarExtractionReport(
        archive_sha256=expected_sha256,
        destination=str(output),
        extracted_files=receipts,
        expanded_size_bytes=sum(member.size_bytes for member in receipts),
    )


def extract_tar_regular_slice(
    archive_path: os.PathLike[str] | str,
    destination: os.PathLike[str] | str,
    *,
    expected_sha256: str,
    expected_structure: TarStructuralAudit,
    allowed_root: str,
    selected_files: tuple[TarRegularSliceMember, ...],
    validate_staging: Callable[[Path, tuple[ExtractedFileReceipt, ...]], None],
    limits: TarLimits = DEFAULT_TAR_LIMITS,
) -> TarExtractionReport:
    """Copy exact regular files only when every live TAR header matches an audit.

    Non-selected special members are compared as inert header metadata. They are
    never opened, followed, copied, or interpreted as filesystem instructions.
    The stricter :func:`extract_tar` policy remains unchanged.
    """

    expected_sha256 = _lower_hex(expected_sha256, length=64, field="expected_sha256")
    if not isinstance(limits, TarLimits):
        raise ArchiveError("limits must be a TarLimits instance")
    if not callable(validate_staging):
        raise ArchiveError("validate_staging must be a callable semantic gate")
    _validate_bound_structural_audit(
        expected_structure,
        expected_sha256=expected_sha256,
        limits=limits,
    )
    selection = _normalize_regular_slice(
        selected_files,
        audit=expected_structure,
        allowed_root=allowed_root,
    )

    output = Path(destination)
    if not output.name or output.name in (".", ".."):
        raise ArchiveError("regular-slice destination must name one new directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    parent_metadata = os.lstat(output.parent)
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ArchiveError("regular-slice destination parent must be a real directory")
    if _lexists(output):
        raise ArchiveError(f"refusing to overwrite regular-slice destination: {output}")

    archive = Path(archive_path)
    if archive.suffix != ".tar":
        raise ArchiveError("regular-slice extraction accepts only an uncompressed .tar archive")
    handle, initial_metadata = _open_regular_readonly(archive)
    staging: Path | None = None
    staging_descriptor: int | None = None
    with handle:
        first_sha256 = _digest_open(handle, "sha256")
        if first_sha256 != expected_sha256:
            raise ArchiveError(
                f"archive SHA-256 mismatch: expected {expected_sha256}, got {first_sha256}"
            )
        if _metadata_signature(os.fstat(handle.fileno())) != _metadata_signature(initial_metadata):
            raise ArchiveError("archive changed while its SHA-256 was being verified")

        live_structure = _audit_open_tar_structure(
            handle,
            limits=limits,
            archive_sha256=first_sha256,
        )
        if live_structure != expected_structure:
            raise ArchiveError("live TAR headers do not exactly equal the bound structural audit")

        staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.staging-", dir=output.parent))
        selected_by_path = {item.path: item for item in selection}
        copied: dict[str, ExtractedFileReceipt] = {}
        live_member_count = 0
        try:
            staging_descriptor, staging_identity = _open_staging_directory(staging)
            handle.seek(0)
            with tarfile.open(fileobj=handle, mode="r:") as source:
                for index, member in enumerate(source):
                    if index >= len(expected_structure.members):
                        raise ArchiveError(
                            "live TAR gained a member after structural-audit comparison"
                        )
                    kind, size_bytes, link_target = _classify_structural_member(member)
                    path = str(
                        _normalize_member_path(member.name, is_directory=kind == "directory")
                    )
                    live_record = TarStructuralMemberRecord(
                        path=path,
                        kind=kind,
                        size_bytes=size_bytes,
                        link_target=link_target,
                    )
                    if live_record != expected_structure.members[index]:
                        raise ArchiveError(
                            f"live TAR header {index} changed from the bound structural audit"
                        )
                    live_member_count += 1
                    selected = selected_by_path.get(path)
                    if selected is None:
                        continue
                    if kind != "file" or size_bytes != selected.size_bytes or path in copied:
                        raise ArchiveError(
                            f"selected regular TAR member changed during copy: {path}"
                        )
                    copied[path] = _copy_exact_member(
                        source,
                        member,
                        staging / Path(*PurePosixPath(path).parts),
                        canonical_path=path,
                    )
            if live_member_count != len(expected_structure.members):
                raise ArchiveError("live TAR lost members after structural-audit comparison")
            missing = set(selected_by_path) - set(copied)
            if missing:
                raise ArchiveError(
                    f"selected regular TAR members disappeared during copy: {sorted(missing)!r}"
                )
            receipts = tuple(copied[item.path] for item in selection)
            try:
                validate_staging(staging, receipts)
            except ArchiveError:
                raise
            except Exception as exc:
                raise ArchiveError(f"regular-slice staging validation failed: {exc}") from exc
            _assert_same_staging_directory(staging, staging_descriptor, staging_identity)
            _verify_staging_tree(staging, receipts)
            _assert_same_staging_directory(staging, staging_descriptor, staging_identity)
            final_sha256 = _digest_open(handle, "sha256")
            if final_sha256 != expected_sha256:
                raise ArchiveError("archive changed while the regular slice was being copied")
            if _metadata_signature(os.fstat(handle.fileno())) != _metadata_signature(
                initial_metadata
            ):
                raise ArchiveError("archive metadata changed while the regular slice was copied")
            _assert_path_is_open_file(archive, handle)
            _assert_same_staging_directory(staging, staging_descriptor, staging_identity)
            _atomic_publish_directory_no_replace(staging, output)
            staging = None
        except ArchiveError:
            raise
        except (OSError, EOFError, ValueError, tarfile.TarError) as exc:
            raise ArchiveError(f"cannot copy regular TAR slice: {exc}") from exc
        finally:
            if staging_descriptor is not None:
                os.close(staging_descriptor)
            if staging is not None:
                _remove_regular_slice_staging(staging)

    return TarExtractionReport(
        archive_sha256=expected_sha256,
        destination=str(output),
        extracted_files=receipts,
        expanded_size_bytes=sum(member.size_bytes for member in receipts),
    )

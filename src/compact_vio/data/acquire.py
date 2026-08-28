"""Reproducible acquisition and safe extraction for EuRoC archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from compact_vio.data.euroc import (
    EuRoCDataError,
    load_euroc_sensor_sequence,
    load_euroc_sequence,
    sha256_file,
)
from compact_vio.data.euroc_position import load_euroc_position_reference

_USER_AGENT = "compact-vio-uav/0.1 (research dataset acquisition)"
_ALLOWED_SENSOR_PATHS = (
    PurePosixPath("mav0/cam0"),
    PurePosixPath("mav0/imu0"),
    PurePosixPath("mav0/state_groundtruth_estimate0"),
    PurePosixPath("mav0/leica0"),
)
_STATE_REFERENCE_PATH = PurePosixPath("mav0/state_groundtruth_estimate0")
_POSITION_REFERENCE_PATH = PurePosixPath("mav0/leica0")
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class EuRoCAcquisitionError(RuntimeError):
    """Raised when acquisition cannot preserve the declared archive identity."""


def _safe_identifier(value: object, *, field: str) -> str:
    if type(value) is not str or _SAFE_IDENTIFIER.fullmatch(value) is None or value in (".", ".."):
        raise EuRoCAcquisitionError(f"{field} must be one safe identifier without path separators")
    return value


@dataclass(frozen=True, slots=True)
class ArchivePlan:
    archive_id: str
    filename: str
    url: str
    size_bytes: int
    md5: str
    sha256: str
    sequences: tuple[str, ...]

    def __post_init__(self) -> None:
        for field, value in (
            ("archive_id", self.archive_id),
            ("filename", self.filename),
            ("url", self.url),
        ):
            if type(value) is not str or not value.strip():
                raise EuRoCAcquisitionError(f"{field} must be a non-empty string")
        _safe_identifier(self.archive_id, field="archive_id")
        if (
            "/" in self.filename
            or "\\" in self.filename
            or PurePosixPath(self.filename).name != self.filename
            or not self.filename.endswith(".zip")
        ):
            raise EuRoCAcquisitionError("filename must be one .zip basename")
        if not self.url.startswith("https://"):
            raise EuRoCAcquisitionError("archive URL must use HTTPS")
        if type(self.size_bytes) is not int or self.size_bytes <= 0:
            raise EuRoCAcquisitionError("size_bytes must be a positive integer")
        if (
            type(self.md5) is not str
            or len(self.md5) != 32
            or any(character not in "0123456789abcdef" for character in self.md5)
        ):
            raise EuRoCAcquisitionError("md5 must be 32 lowercase hexadecimal characters")
        if (
            type(self.sha256) is not str
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise EuRoCAcquisitionError("sha256 must be 64 lowercase hexadecimal characters")
        if type(self.sequences) is not tuple or not self.sequences:
            raise EuRoCAcquisitionError("sequences must be a non-empty tuple")
        if len(set(self.sequences)) != len(self.sequences):
            raise EuRoCAcquisitionError("archive sequence identifiers must be unique")
        for value in self.sequences:
            _safe_identifier(value, field="sequence identifier")


def _exact_dict(value: object, *, field: str) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise EuRoCAcquisitionError(f"{field} must be a JSON object with string keys")
    return value


def load_archive_plans(path: os.PathLike[str] | str) -> dict[str, ArchivePlan]:
    """Load archive identities from the committed acquisition-plan document."""

    plan_path = Path(path)
    try:
        document = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EuRoCAcquisitionError(f"cannot read acquisition plan {plan_path}: {exc}") from exc
    root = _exact_dict(document, field="acquisition plan")
    if root.get("record_type") != "euroc_acquisition_plan":
        raise EuRoCAcquisitionError("record_type must equal euroc_acquisition_plan")
    archives = root.get("archives")
    if type(archives) is not list or not archives:
        raise EuRoCAcquisitionError("archives must be a non-empty JSON array")
    result: dict[str, ArchivePlan] = {}
    for index, raw in enumerate(archives):
        item = _exact_dict(raw, field=f"archives[{index}]")
        expected = {
            "archive_id",
            "filename",
            "url",
            "size_bytes",
            "md5",
            "sha256",
            "sequences",
        }
        if set(item) != expected:
            raise EuRoCAcquisitionError(f"archives[{index}] fields must equal {sorted(expected)!r}")
        sequences = item["sequences"]
        if type(sequences) is not list:
            raise EuRoCAcquisitionError(f"archives[{index}].sequences must be an array")
        plan = ArchivePlan(
            archive_id=item["archive_id"],
            filename=item["filename"],
            url=item["url"],
            size_bytes=item["size_bytes"],
            md5=item["md5"],
            sha256=item["sha256"],
            sequences=tuple(sequences),
        )
        if plan.archive_id in result:
            raise EuRoCAcquisitionError(f"duplicate archive_id {plan.archive_id!r}")
        result[plan.archive_id] = plan
    return result


def _digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise EuRoCAcquisitionError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def verify_archive(path: os.PathLike[str] | str, plan: ArchivePlan) -> dict[str, object]:
    """Verify exact byte length and ETH-published MD5, then compute SHA-256."""

    archive = Path(path)
    if not archive.is_file() or archive.is_symlink():
        raise EuRoCAcquisitionError(f"archive is not a regular non-symlink file: {archive}")
    size = archive.stat().st_size
    if size != plan.size_bytes:
        raise EuRoCAcquisitionError(
            f"archive size mismatch for {plan.archive_id}: expected {plan.size_bytes}, got {size}"
        )
    actual_md5 = _digest(archive, "md5")
    if actual_md5 != plan.md5:
        raise EuRoCAcquisitionError(
            f"archive MD5 mismatch for {plan.archive_id}: expected {plan.md5}, got {actual_md5}"
        )
    actual_sha256 = sha256_file(archive)
    if actual_sha256 != plan.sha256:
        raise EuRoCAcquisitionError(
            f"archive SHA-256 mismatch for {plan.archive_id}: "
            f"expected {plan.sha256}, got {actual_sha256}"
        )
    return {
        "archive_id": plan.archive_id,
        "filename": plan.filename,
        "size_bytes": size,
        "md5": actual_md5,
        "sha256": actual_sha256,
        "source_url": plan.url,
    }


def download_archive(
    plan: ArchivePlan,
    destination: os.PathLike[str] | str,
    *,
    chunk_size: int = 8 * 1024 * 1024,
) -> dict[str, object]:
    """Download with safe resume and return verified archive identity."""

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.is_symlink():
        raise EuRoCAcquisitionError(f"refusing symlink destination: {target}")
    existing = target.stat().st_size if target.exists() else 0
    if existing > plan.size_bytes:
        raise EuRoCAcquisitionError("partial archive is larger than the declared archive")
    if existing == plan.size_bytes:
        return verify_archive(target, plan)

    request = urllib.request.Request(plan.url, headers={"User-Agent": _USER_AGENT})
    if existing:
        request.add_header("Range", f"bytes={existing}-")
    try:
        response = urllib.request.urlopen(request, timeout=120)  # noqa: S310
    except (OSError, urllib.error.URLError) as exc:
        raise EuRoCAcquisitionError(f"cannot download {plan.archive_id}: {exc}") from exc

    status = getattr(response, "status", response.getcode())
    if existing and status != 206:
        response.close()
        existing = 0
        request = urllib.request.Request(plan.url, headers={"User-Agent": _USER_AGENT})
        try:
            response = urllib.request.urlopen(request, timeout=120)  # noqa: S310
        except (OSError, urllib.error.URLError) as exc:
            raise EuRoCAcquisitionError(f"cannot restart {plan.archive_id}: {exc}") from exc
    mode = "ab" if existing else "wb"
    try:
        with response, target.open(mode) as handle:
            while chunk := response.read(chunk_size):
                handle.write(chunk)
    except OSError as exc:
        raise EuRoCAcquisitionError(f"download failed for {plan.archive_id}: {exc}") from exc
    return verify_archive(target, plan)


def _safe_member_target(
    member: zipfile.ZipInfo,
    *,
    selected_sequences: set[str],
) -> tuple[str, PurePosixPath] | None:
    raw = member.filename.replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise EuRoCAcquisitionError(f"unsafe ZIP member path: {member.filename!r}")
    mode = member.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise EuRoCAcquisitionError(f"ZIP symlink is prohibited: {member.filename!r}")
    sequence_indexes = [
        index for index, part in enumerate(path.parts) if part in selected_sequences
    ]
    if not sequence_indexes:
        return None
    if len(sequence_indexes) != 1:
        raise EuRoCAcquisitionError(f"ambiguous sequence path: {member.filename!r}")
    index = sequence_indexes[0]
    sequence = path.parts[index]
    relative = PurePosixPath(*path.parts[index + 1 :])
    if not relative.parts:
        return None
    if not any(
        relative == prefix or prefix in relative.parents for prefix in _ALLOWED_SENSOR_PATHS
    ):
        return None
    return sequence, relative


def _safe_inner_relative(member: zipfile.ZipInfo, *, sequence: str) -> PurePosixPath | None:
    raw = member.filename.replace("\\", "/")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise EuRoCAcquisitionError(f"unsafe nested ZIP member path: {member.filename!r}")
    mode = member.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise EuRoCAcquisitionError(f"nested ZIP symlink is prohibited: {member.filename!r}")
    if sequence in path.parts:
        index = path.parts.index(sequence)
        relative = PurePosixPath(*path.parts[index + 1 :])
    else:
        relative = path
    if not relative.parts:
        return None
    if not any(
        relative == prefix or prefix in relative.parents for prefix in _ALLOWED_SENSOR_PATHS
    ):
        return None
    return relative


def _extract_inner_sequence(
    archive: Path,
    destination: Path,
    *,
    sequence: str,
) -> int:
    count = 0
    seen: set[PurePosixPath] = set()
    try:
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                relative = _safe_inner_relative(member, sequence=sequence)
                if relative is None or member.is_dir():
                    continue
                if relative in seen:
                    raise EuRoCAcquisitionError(
                        f"duplicate nested ZIP member for {sequence}: {relative}"
                    )
                seen.add(relative)
                target = destination / Path(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(member) as input_handle, target.open("xb") as output_handle:
                    shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
                count += 1
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        if isinstance(exc, EuRoCAcquisitionError):
            raise
        raise EuRoCAcquisitionError(
            f"cannot extract nested sequence archive {archive}: {exc}"
        ) from exc
    return count


def extract_sequences(
    archive_path: os.PathLike[str] | str,
    destination_root: os.PathLike[str] | str,
    sequences: tuple[str, ...],
) -> tuple[dict[str, object], ...]:
    """Safely extract cam0/IMU plus supported reference streams.

    The supported reference streams are the full state estimate under
    ``mav0/state_groundtruth_estimate0`` and the position-only Leica stream
    under ``mav0/leica0``. Every extracted sequence must contain at least one
    of them; every stream that is present is validated before publication.
    """

    if type(sequences) is not tuple or not sequences or len(set(sequences)) != len(sequences):
        raise EuRoCAcquisitionError("sequences must be a non-empty unique tuple")
    for value in sequences:
        _safe_identifier(value, field="sequence identifier")
    archive = Path(archive_path)
    destination = Path(destination_root)
    destination.mkdir(parents=True, exist_ok=True)
    selected = set(sequences)
    for sequence in sequences:
        if (destination / sequence).exists():
            raise EuRoCAcquisitionError(f"refusing to overwrite sequence: {sequence}")

    with tempfile.TemporaryDirectory(prefix=".euroc-extract-", dir=destination) as temp_name:
        temporary = Path(temp_name)
        seen: set[tuple[str, PurePosixPath]] = set()
        extracted_files = {sequence: 0 for sequence in sequences}
        nested_archives: dict[str, Path] = {}
        try:
            with zipfile.ZipFile(archive) as source:
                for member in source.infolist():
                    normalized = PurePosixPath(member.filename.replace("\\", "/"))
                    for sequence in sequences:
                        if (
                            sequence in normalized.parts
                            and normalized.name == f"{sequence}.zip"
                            and not member.is_dir()
                        ):
                            nested_directory = temporary / ".nested"
                            nested_directory.mkdir(exist_ok=True)
                            nested_target = nested_directory / f"{sequence}.zip"
                            if sequence in nested_archives:
                                raise EuRoCAcquisitionError(
                                    f"duplicate nested archive for {sequence!r}"
                                )
                            with (
                                source.open(member) as input_handle,
                                nested_target.open("xb") as output_handle,
                            ):
                                shutil.copyfileobj(
                                    input_handle,
                                    output_handle,
                                    length=1024 * 1024,
                                )
                            nested_archives[sequence] = nested_target
                            break
                    mapped = _safe_member_target(member, selected_sequences=selected)
                    if mapped is None or member.is_dir():
                        continue
                    if mapped in seen:
                        raise EuRoCAcquisitionError(f"duplicate mapped ZIP member: {mapped!r}")
                    seen.add(mapped)
                    sequence, relative = mapped
                    target = temporary / sequence / Path(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as input_handle, target.open("xb") as output_handle:
                        shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
                    extracted_files[sequence] += 1
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            if isinstance(exc, EuRoCAcquisitionError):
                raise
            raise EuRoCAcquisitionError(f"cannot extract {archive}: {exc}") from exc

        for sequence, nested_archive in nested_archives.items():
            if extracted_files[sequence]:
                raise EuRoCAcquisitionError(
                    f"archive contains both direct and nested ASL data for {sequence!r}"
                )
            extracted_files[sequence] = _extract_inner_sequence(
                nested_archive,
                temporary / sequence,
                sequence=sequence,
            )

        reports: list[dict[str, object]] = []
        for sequence in sequences:
            if extracted_files[sequence] == 0:
                raise EuRoCAcquisitionError(f"sequence {sequence!r} was not found in archive")
            staged = temporary / sequence
            try:
                sensor_sequence = load_euroc_sensor_sequence(staged)
                state_reference_root = staged.joinpath(*_STATE_REFERENCE_PATH.parts)
                position_reference_root = staged.joinpath(*_POSITION_REFERENCE_PATH.parts)
                has_state_reference = state_reference_root.exists()
                has_position_reference = position_reference_root.exists()
                if not has_state_reference and not has_position_reference:
                    raise EuRoCDataError(
                        "sequence has no supported reference stream "
                        "(state_groundtruth_estimate0 or leica0)"
                    )

                ground_truth_state_count = 0
                if has_state_reference:
                    ground_truth_state_count = len(load_euroc_sequence(staged).ground_truth_states)

                position_reference_count = 0
                if has_position_reference:
                    position_reference_count = len(load_euroc_position_reference(staged).positions)
            except EuRoCDataError as exc:
                raise EuRoCAcquisitionError(
                    f"extracted sequence {sequence!r} failed validation: {exc}"
                ) from exc
            reports.append(
                {
                    "sequence_id": sequence,
                    "camera_frame_count": len(sensor_sequence.camera_frames),
                    "imu_measurement_count": len(sensor_sequence.imu_measurements),
                    "ground_truth_state_count": ground_truth_state_count,
                    "position_reference_count": position_reference_count,
                    "extracted_file_count": extracted_files[sequence],
                }
            )
        for sequence in sequences:
            (temporary / sequence).replace(destination / sequence)
    return tuple(reports)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--archive", required=True, help="archive_id from the plan")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--sequence", action="append", default=[])
    parser.add_argument("--verify-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plans = load_archive_plans(args.plan)
        if args.archive not in plans:
            raise EuRoCAcquisitionError(f"unknown archive_id {args.archive!r}")
        plan = plans[args.archive]
        archive_path = args.raw_dir / plan.filename
        identity = (
            verify_archive(archive_path, plan)
            if args.verify_only
            else download_archive(plan, archive_path)
        )
        result: dict[str, object] = {"archive": identity, "sequences": []}
        if args.sequence:
            if args.data_dir is None:
                raise EuRoCAcquisitionError("--data-dir is required with --sequence")
            requested = tuple(args.sequence)
            unknown = sorted(set(requested) - set(plan.sequences))
            if unknown:
                raise EuRoCAcquisitionError(f"sequences are not in archive: {unknown!r}")
            result["sequences"] = list(extract_sequences(archive_path, args.data_dir, requested))
        print(json.dumps(result, indent=2, sort_keys=True))
    except EuRoCAcquisitionError as exc:
        print(f"compact-vio-euroc: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

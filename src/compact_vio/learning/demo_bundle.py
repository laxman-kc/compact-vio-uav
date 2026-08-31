"""Safe one-file recording bundles and a deterministic workflow example.

A bundle is a ZIP with one optional wrapper directory and this payload::

    frames/<timestamp_ns>.png
    imu.csv
    calibration.json  # or calibration.yaml / calibration.yml
    camera.csv         # optional

The bundle is intentionally small and strict.  It is a convenience container;
the extracted files still pass through the normal recording, IMU, and
calibration validators before inference.
"""

from __future__ import annotations

import json
import stat
import tempfile
import zipfile
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from compact_vio.learning.errors import LearningError

_IMAGE_SUFFIXES = frozenset({".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff"})
_CALIBRATION_NAMES = ("calibration.json", "calibration.yaml", "calibration.yml")
_MAX_MEMBERS = 20_000
_MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
_MAX_MEMBER_BYTES = 256 * 1024 * 1024
_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
_MAX_MANIFEST_BYTES = 1024 * 1024


class _DuplicateJsonKeyError(ValueError):
    """Raised when strict JSON parsing encounters a repeated object key."""


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


class RecordingBundleError(LearningError):
    """Raised when a recording bundle is unsafe, ambiguous, or incomplete."""


@dataclass(frozen=True, slots=True)
class RecordingBundleInputs:
    """Resolved normal-run inputs held alive by :func:`open_recording_bundle`."""

    recording_path: Path
    imu_csv_path: Path
    calibration_path: Path
    camera_timestamps_path: Path | None
    display_name: str
    is_workflow_example: bool = False


def _safe_relative_name(name: str) -> PurePosixPath:
    pure = PurePosixPath(name)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
        or "\\" in name
        or "\x00" in name
    ):
        raise RecordingBundleError(f"bundle contains an unsafe path: {name!r}")
    return pure


def _payload_root(files: tuple[PurePosixPath, ...]) -> PurePosixPath:
    direct_names = {path.as_posix() for path in files}
    if "imu.csv" in direct_names and any(name in direct_names for name in _CALIBRATION_NAMES):
        return PurePosixPath()
    first_parts = {path.parts[0] for path in files}
    if len(first_parts) != 1:
        raise RecordingBundleError(
            "bundle must contain imu.csv, calibration.json/yaml, and frames/ at its root"
        )
    wrapper = PurePosixPath(next(iter(first_parts)))
    wrapped_names = {
        PurePosixPath(*path.parts[1:]).as_posix() for path in files if len(path.parts) > 1
    }
    if "imu.csv" not in wrapped_names or not any(
        name in wrapped_names for name in _CALIBRATION_NAMES
    ):
        raise RecordingBundleError(
            "bundle must contain imu.csv, calibration.json/yaml, and frames/"
        )
    return wrapper


def _relative_to_payload(path: PurePosixPath, root: PurePosixPath) -> PurePosixPath:
    if not root.parts:
        return path
    if not path.parts or path.parts[0] != root.parts[0] or len(path.parts) == 1:
        raise RecordingBundleError("bundle mixes files inside and outside its wrapper directory")
    return PurePosixPath(*path.parts[1:])


def _validate_payload_members(
    members: tuple[zipfile.ZipInfo, ...],
) -> tuple[PurePosixPath, dict[PurePosixPath, zipfile.ZipInfo]]:
    if not members:
        raise RecordingBundleError("recording bundle is empty")
    if len(members) > _MAX_MEMBERS:
        raise RecordingBundleError("recording bundle contains too many entries")

    files: list[PurePosixPath] = []
    seen: set[str] = set()
    seen_casefold: set[str] = set()
    total_bytes = 0
    by_path: dict[PurePosixPath, zipfile.ZipInfo] = {}
    for member in members:
        pure = _safe_relative_name(member.filename)
        canonical = pure.as_posix()
        folded = canonical.casefold()
        if canonical in seen or folded in seen_casefold:
            raise RecordingBundleError(f"bundle repeats a path: {member.filename!r}")
        seen.add(canonical)
        seen_casefold.add(folded)
        unix_mode = member.external_attr >> 16
        file_type = stat.S_IFMT(unix_mode)
        if file_type == stat.S_IFLNK:
            raise RecordingBundleError("recording bundle must not contain symbolic links")
        if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise RecordingBundleError("recording bundle must contain only files/directories")
        if member.flag_bits & 0x1:
            raise RecordingBundleError("encrypted recording bundles are not supported")
        if member.is_dir():
            continue
        if member.file_size > _MAX_MEMBER_BYTES:
            raise RecordingBundleError("recording bundle entry exceeds the size limit")
        total_bytes += member.file_size
        if total_bytes > _MAX_TOTAL_BYTES:
            raise RecordingBundleError("recording bundle exceeds the expansion limit")
        if member.file_size and member.compress_size == 0:
            raise RecordingBundleError("recording bundle has an invalid compression size")
        if (
            member.file_size
            and member.compress_size
            and member.file_size > member.compress_size * _MAX_COMPRESSION_RATIO
        ):
            raise RecordingBundleError("recording bundle compression ratio is unsafe")
        files.append(pure)
        by_path[pure] = member

    file_tuple = tuple(files)
    root = _payload_root(file_tuple)
    relative: dict[PurePosixPath, zipfile.ZipInfo] = {}
    for path, member in by_path.items():
        payload_path = _relative_to_payload(path, root)
        value = payload_path.as_posix()
        allowed_root = value in {
            "imu.csv",
            "camera.csv",
            "compact-vio-bundle.json",
            *_CALIBRATION_NAMES,
        }
        allowed_frame = (
            len(payload_path.parts) == 2
            and payload_path.parts[0] == "frames"
            and payload_path.suffix.lower() in _IMAGE_SUFFIXES
        )
        if not allowed_root and not allowed_frame:
            raise RecordingBundleError(f"unsupported bundle entry: {value!r}")
        if value == "compact-vio-bundle.json" and member.file_size > _MAX_MANIFEST_BYTES:
            raise RecordingBundleError("bundle manifest exceeds the size limit")
        relative[payload_path] = member

    calibration = tuple(name for name in _CALIBRATION_NAMES if PurePosixPath(name) in relative)
    if len(calibration) != 1:
        raise RecordingBundleError("bundle must contain exactly one calibration.json/yaml file")
    if PurePosixPath("imu.csv") not in relative:
        raise RecordingBundleError("bundle is missing imu.csv")
    frame_count = sum(path.parts[0] == "frames" for path in relative)
    if frame_count < 2:
        raise RecordingBundleError("bundle must contain at least two images in frames/")
    return root, relative


def _extract_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with archive.open(member, "r") as source, destination.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                written += len(chunk)
                if written > member.file_size or written > _MAX_MEMBER_BYTES:
                    raise RecordingBundleError("bundle entry expanded beyond its declared size")
                target.write(chunk)
    except (OSError, EOFError, RuntimeError, zipfile.BadZipFile, zlib.error) as exc:
        raise RecordingBundleError(
            f"cannot extract recording bundle entry {member.filename!r}: {exc}"
        ) from exc
    if written != member.file_size:
        raise RecordingBundleError("bundle entry size changed during extraction")


@contextmanager
def open_recording_bundle(path: Path | str) -> Any:
    """Open a checked recording ZIP and yield normal inference input paths."""

    source = Path(path)
    if source.suffix.lower() != ".zip" or source.is_symlink() or not source.is_file():
        raise RecordingBundleError("recording bundle must be a regular .zip file")
    try:
        source_bytes = source.stat().st_size
    except OSError as exc:
        raise RecordingBundleError(f"cannot inspect recording bundle: {exc}") from exc
    if source_bytes > _MAX_SOURCE_BYTES:
        raise RecordingBundleError("recording bundle exceeds the compressed size limit")
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RecordingBundleError(f"cannot open recording bundle: {exc}") from exc

    with archive, tempfile.TemporaryDirectory(prefix="compact-vio-bundle-") as directory:
        _root, members = _validate_payload_members(tuple(archive.infolist()))
        extracted = Path(directory)
        for payload_path, member in members.items():
            _extract_member(archive, member, extracted.joinpath(*payload_path.parts))

        calibration_names = tuple(
            name for name in _CALIBRATION_NAMES if (extracted / name).is_file()
        )
        manifest_path = extracted / "compact-vio-bundle.json"
        is_example = False
        display_name = source.stem
        if manifest_path.is_file():
            try:
                manifest = json.loads(
                    manifest_path.read_text(encoding="utf-8"),
                    object_pairs_hook=_unique_json_object,
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                _DuplicateJsonKeyError,
            ) as exc:
                raise RecordingBundleError(f"cannot parse compact-vio-bundle.json: {exc}") from exc
            if type(manifest) is not dict:
                raise RecordingBundleError("compact-vio-bundle.json must be a JSON object")
            allowed = {"schema_version", "name", "workflow_example"}
            if set(manifest) - allowed:
                raise RecordingBundleError("compact-vio-bundle.json contains unsupported fields")
            if manifest.get("schema_version") != "1.0":
                raise RecordingBundleError("bundle manifest schema_version must be '1.0'")
            name = manifest.get("name", display_name)
            if type(name) is not str or not name.strip() or len(name) > 120:
                raise RecordingBundleError("bundle manifest name must be 1-120 characters")
            example = manifest.get("workflow_example", False)
            if type(example) is not bool:
                raise RecordingBundleError("bundle manifest workflow_example must be boolean")
            display_name = name.strip()
            is_example = example

        yield RecordingBundleInputs(
            recording_path=extracted / "frames",
            imu_csv_path=extracted / "imu.csv",
            calibration_path=extracted / calibration_names[0],
            camera_timestamps_path=(extracted / "camera.csv")
            if (extracted / "camera.csv").is_file()
            else None,
            display_name=display_name,
            is_workflow_example=is_example,
        )


def create_workflow_example_bundle(destination: Path | str) -> Path:
    """Create a deterministic synthetic bundle for exercising the whole UI flow.

    The frames and IMU values are synthetic and do not carry accuracy evidence.
    Pillow is imported only when this optional demo helper is called.
    """

    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RecordingBundleError(
            "the built-in example requires Pillow from the data or demo extra"
        ) from exc

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise RecordingBundleError(f"example bundle already exists: {target}")
    start_ns = 2_000_000_000
    camera_step_ns = 50_000_000
    timestamps = tuple(start_ns + index * camera_step_ns for index in range(12))
    calibration = {
        "camera": {
            "T_BS": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            "camera_model": "pinhole",
            "distortion_coefficients": [0.0, 0.0, 0.0, 0.0],
            "distortion_model": "radtan",
            "intrinsics": [200.0, 200.0, 188.0, 120.0],
            "resolution": [376, 240],
        },
        "imu": {
            "T_BS": [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        },
    }
    manifest = {
        "schema_version": "1.0",
        "name": "Built-in synthetic workflow example",
        "workflow_example": True,
    }
    with tempfile.TemporaryDirectory(prefix="compact-vio-example-") as directory:
        root = Path(directory)
        frames = root / "frames"
        frames.mkdir()
        for index, timestamp in enumerate(timestamps):
            image = Image.new("L", (376, 240), color=22)
            draw = ImageDraw.Draw(image)
            offset = index * 3
            for x in range(-40, 416, 40):
                draw.line((x + offset, 0, x + offset, 239), fill=58, width=2)
            for y in range(0, 280, 40):
                draw.line((0, y, 375, y), fill=58, width=2)
            draw.rectangle((70 + offset, 70, 150 + offset, 150), outline=235, width=5)
            draw.ellipse((245 - offset, 92, 295 - offset, 142), outline=182, width=4)
            image.save(frames / f"{timestamp}.png", format="PNG", optimize=False)

        imu_lines = [
            "timestamp_ns,gyro_x_rad_s,gyro_y_rad_s,gyro_z_rad_s,"
            "accel_x_m_s2,accel_y_m_s2,accel_z_m_s2"
        ]
        end_ns = timestamps[-1]
        for timestamp in range(0, end_ns + 5_000_000, 5_000_000):
            imu_lines.append(f"{timestamp},0.0,0.0,0.001,0.0,0.0,9.81")
        (root / "imu.csv").write_text("\n".join(imu_lines) + "\n", encoding="utf-8")
        (root / "calibration.json").write_text(
            json.dumps(calibration, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (root / "compact-vio-bundle.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                for source in sorted(root.rglob("*")):
                    if source.is_file():
                        member = zipfile.ZipInfo(
                            source.relative_to(root).as_posix(),
                            date_time=(1980, 1, 1, 0, 0, 0),
                        )
                        member.create_system = 3
                        member.external_attr = 0o100644 << 16
                        archive.writestr(
                            member,
                            source.read_bytes(),
                            compress_type=zipfile.ZIP_DEFLATED,
                            compresslevel=9,
                        )
        except OSError as exc:
            target.unlink(missing_ok=True)
            raise RecordingBundleError(f"cannot create built-in example bundle: {exc}") from exc
    return target


__all__ = [
    "RecordingBundleError",
    "RecordingBundleInputs",
    "create_workflow_example_bundle",
    "open_recording_bundle",
]

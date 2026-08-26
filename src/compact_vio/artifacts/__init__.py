"""Deterministic experiment-bundle manifests.

This module inventories a bundle without following symbolic links, writes a
canonical JSON manifest atomically, and verifies a bundle against that
manifest.  It intentionally depends only on the Python standard library so it
can be used during recovery even when the training environment is unavailable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import stat
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

DEFAULT_MANIFEST_PATH = "artifact-manifest.json"
SCHEMA_VERSION = 1
HASH_ALGORITHM = "sha256"
_HASH_CHUNK_SIZE = 1024 * 1024
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024


class ArtifactError(Exception):
    """Base class for expected artifact-manifest failures."""


class UnsafeBundleError(ArtifactError):
    """Raised when a bundle contains an unsafe or unsupported path."""


class ManifestFormatError(ArtifactError):
    """Raised when a manifest is malformed or non-canonical."""


class ArtifactIOError(ArtifactError):
    """Raised when a bundle cannot be read or a manifest cannot be written."""


@dataclass(frozen=True, order=True, slots=True)
class FileRecord:
    """The content identity of one regular file in a bundle."""

    path: str
    bytes: int
    sha256: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "bytes": self.bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    """A versioned, sorted set of bundle file records."""

    files: tuple[FileRecord, ...]
    schema_version: int = SCHEMA_VERSION
    hash_algorithm: str = HASH_ALGORITHM

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "hash_algorithm": self.hash_algorithm,
            "files": [record.to_dict() for record in self.files],
        }

    def to_json_bytes(self) -> bytes:
        """Return the canonical, byte-stable JSON representation."""

        return (
            json.dumps(
                self.to_dict(),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class SizeMismatch:
    path: str
    expected: int
    actual: int

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class HashMismatch:
    path: str
    expected: str
    actual: str

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """All differences found while verifying a bundle."""

    missing: tuple[str, ...]
    unexpected: tuple[str, ...]
    size_mismatches: tuple[SizeMismatch, ...]
    hash_mismatches: tuple[HashMismatch, ...]

    @property
    def ok(self) -> bool:
        return not (self.missing or self.unexpected or self.size_mismatches or self.hash_mismatches)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "missing": list(self.missing),
            "unexpected": list(self.unexpected),
            "size_mismatches": [item.to_dict() for item in self.size_mismatches],
            "hash_mismatches": [item.to_dict() for item in self.hash_mismatches],
        }


def _canonical_relative_path(value: str, *, field: str = "path") -> str:
    if not isinstance(value, str):
        raise ManifestFormatError(f"{field} must be a string")
    if not value or "\x00" in value or "\\" in value:
        raise UnsafeBundleError(f"unsafe {field}: {value!r}")

    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise UnsafeBundleError(f"{field} must be a canonical relative POSIX path: {value!r}")
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise UnsafeBundleError(f"unsafe {field}: {value!r}")
    return value


def _bundle_root(bundle_root: os.PathLike[str] | str) -> Path:
    supplied = Path(bundle_root)
    try:
        if supplied.is_symlink():
            raise UnsafeBundleError(f"bundle root must not be a symbolic link: {supplied}")
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise ArtifactIOError(f"cannot resolve bundle root {supplied}: {exc}") from exc
    if not root.is_dir():
        raise UnsafeBundleError(f"bundle root is not a directory: {root}")
    return root


def _manifest_destination(root: Path, manifest_path: str) -> tuple[str, Path]:
    relative = _canonical_relative_path(manifest_path, field="manifest path")
    destination = root.joinpath(*PurePosixPath(relative).parts)
    return relative, destination


def _directory_open_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _open_root_descriptor(root: Path) -> int:
    if os.scandir not in os.supports_fd or os.open not in os.supports_dir_fd:
        raise ArtifactIOError(
            "secure descriptor-relative directory traversal is unavailable on this platform"
        )
    descriptor: int | None = None
    try:
        descriptor = os.open(root, _directory_open_flags())
        status = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise ArtifactIOError(f"cannot open bundle root {root}: {exc}") from exc
    if not stat.S_ISDIR(status.st_mode):
        os.close(descriptor)
        raise UnsafeBundleError(f"bundle root is not a directory: {root}")
    return descriptor


def _safe_hash_entry(
    directory_descriptor: int,
    name: str,
    display_path: str,
    expected_status: os.stat_result,
) -> tuple[int, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    try:
        descriptor = os.open(name, flags, dir_fd=directory_descriptor)
    except OSError as exc:
        raise ArtifactIOError(f"cannot open bundle file {display_path}: {exc}") from exc

    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise UnsafeBundleError(f"bundle entry is not a regular file: {display_path}")
        if expected_status.st_ino != before.st_ino or expected_status.st_dev != before.st_dev:
            raise ArtifactIOError(f"bundle file changed while opening: {display_path}")

        digest = hashlib.sha256()
        byte_count = 0
        while True:
            chunk = os.read(descriptor, _HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
            byte_count += len(chunk)

        after = os.fstat(descriptor)
        if (
            byte_count != before.st_size
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ino != after.st_ino
            or before.st_dev != after.st_dev
        ):
            raise ArtifactIOError(f"bundle file changed while hashing: {display_path}")
        return byte_count, digest.hexdigest()
    except OSError as exc:
        raise ArtifactIOError(f"cannot hash bundle file {display_path}: {exc}") from exc
    finally:
        os.close(descriptor)


def _inventory_directory(
    directory_descriptor: int,
    prefix: PurePosixPath,
    excluded: frozenset[str],
    records: list[FileRecord],
) -> None:
    try:
        with os.scandir(directory_descriptor) as iterator:
            names = sorted(entry.name for entry in iterator)
    except OSError as exc:
        display = prefix.as_posix() if prefix.parts else "."
        raise ArtifactIOError(f"cannot read bundle directory {display}: {exc}") from exc

    for name in names:
        relative = (prefix / name).as_posix()
        _canonical_relative_path(relative)
        try:
            entry_status = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if stat.S_ISLNK(entry_status.st_mode):
                raise UnsafeBundleError(f"bundle contains a symbolic link: {relative}")
            if stat.S_ISDIR(entry_status.st_mode):
                child_descriptor = os.open(
                    name,
                    _directory_open_flags(),
                    dir_fd=directory_descriptor,
                )
                try:
                    opened_status = os.fstat(child_descriptor)
                    if (
                        entry_status.st_ino != opened_status.st_ino
                        or entry_status.st_dev != opened_status.st_dev
                    ):
                        raise ArtifactIOError(f"bundle directory changed while opening: {relative}")
                    _inventory_directory(child_descriptor, prefix / name, excluded, records)
                finally:
                    os.close(child_descriptor)
                continue
            if not stat.S_ISREG(entry_status.st_mode):
                raise UnsafeBundleError(f"bundle entry is not a regular file: {relative}")
        except OSError as exc:
            raise ArtifactIOError(f"cannot inspect bundle entry {relative}: {exc}") from exc

        if relative in excluded:
            continue
        byte_count, digest = _safe_hash_entry(directory_descriptor, name, relative, entry_status)
        records.append(FileRecord(path=relative, bytes=byte_count, sha256=digest))


def inventory_bundle(
    bundle_root: os.PathLike[str] | str,
    *,
    exclude: Iterable[str] = (),
) -> tuple[FileRecord, ...]:
    """Recursively inventory regular files below *bundle_root*.

    Paths are returned as canonical POSIX paths in lexical order.  Symbolic
    links and special files are rejected rather than followed or ignored.
    """

    root = _bundle_root(bundle_root)
    excluded = frozenset(_canonical_relative_path(path, field="excluded path") for path in exclude)
    records: list[FileRecord] = []
    root_descriptor = _open_root_descriptor(root)
    try:
        _inventory_directory(root_descriptor, PurePosixPath(), excluded, records)
    finally:
        os.close(root_descriptor)
    records.sort(key=lambda record: record.path)
    return tuple(records)


def create_manifest(
    bundle_root: os.PathLike[str] | str,
    *,
    manifest_path: str = DEFAULT_MANIFEST_PATH,
) -> ArtifactManifest:
    """Inventory a bundle and atomically create its canonical manifest.

    The destination must not already exist. Frozen evidence is never replaced
    implicitly; callers must choose a new bundle or manifest path.
    """

    root = _bundle_root(bundle_root)
    relative, _ = _manifest_destination(root, manifest_path)
    manifest = ArtifactManifest(files=inventory_bundle(root, exclude=(relative,)))
    _atomic_write_new_manifest(root, relative, manifest.to_json_bytes())
    return manifest


def _open_manifest_parent(root: Path, manifest_path: str, *, create: bool) -> tuple[int, str]:
    parts = PurePosixPath(manifest_path).parts
    current_descriptor = _open_root_descriptor(root)
    try:
        for part in parts[:-1]:
            try:
                child_descriptor = os.open(
                    part,
                    _directory_open_flags(),
                    dir_fd=current_descriptor,
                )
            except FileNotFoundError:
                if not create:
                    raise ArtifactIOError(
                        f"manifest directory does not exist: {root / manifest_path}"
                    ) from None
                try:
                    os.mkdir(part, mode=0o700, dir_fd=current_descriptor)
                    os.fsync(current_descriptor)
                    child_descriptor = os.open(
                        part,
                        _directory_open_flags(),
                        dir_fd=current_descriptor,
                    )
                except OSError as exc:
                    raise ArtifactIOError(
                        f"cannot create manifest directory component {part!r}: {exc}"
                    ) from exc
            except OSError as exc:
                raise UnsafeBundleError(
                    f"manifest path crosses an unsafe directory component {part!r}: {exc}"
                ) from exc
            os.close(current_descriptor)
            current_descriptor = child_descriptor
        return current_descriptor, parts[-1]
    except Exception:
        os.close(current_descriptor)
        raise


def _atomic_write_new_manifest(root: Path, manifest_path: str, content: bytes) -> None:
    parent_descriptor, destination_name = _open_manifest_parent(root, manifest_path, create=True)
    temporary_name = f".compact-vio-manifest-{secrets.token_hex(12)}.tmp"
    temporary_descriptor: int | None = None
    temporary_exists = False
    try:
        try:
            existing = os.stat(
                destination_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            existing = None
        if existing is not None:
            kind = "symbolic link" if stat.S_ISLNK(existing.st_mode) else "existing entry"
            raise UnsafeBundleError(
                f"refusing to overwrite {kind} at manifest path: {root / manifest_path}"
            )

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        temporary_descriptor = os.open(
            temporary_name,
            flags,
            0o600,
            dir_fd=parent_descriptor,
        )
        temporary_exists = True
        view = memoryview(content)
        while view:
            written = os.write(temporary_descriptor, view)
            if written <= 0:
                raise ArtifactIOError("manifest write made no progress")
            view = view[written:]
        os.fsync(temporary_descriptor)
        os.close(temporary_descriptor)
        temporary_descriptor = None

        # A hard link publishes the completely written inode and fails atomically
        # if any destination entry appeared. No existing bundle file is replaced.
        os.link(
            temporary_name,
            destination_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        os.unlink(temporary_name, dir_fd=parent_descriptor)
        temporary_exists = False
        os.fsync(parent_descriptor)
    except FileExistsError as exc:
        raise UnsafeBundleError(
            f"refusing to overwrite existing manifest path: {root / manifest_path}"
        ) from exc
    except ArtifactError:
        raise
    except OSError as exc:
        raise ArtifactIOError(
            f"cannot atomically create manifest {root / manifest_path}: {exc}"
        ) from exc
    finally:
        if temporary_descriptor is not None:
            os.close(temporary_descriptor)
        if temporary_exists:
            try:
                os.unlink(temporary_name, dir_fd=parent_descriptor)
            except OSError:
                pass
        os.close(parent_descriptor)


def _read_regular_file(root: Path, manifest_path: str) -> bytes:
    parent_descriptor, name = _open_manifest_parent(root, manifest_path, create=False)
    try:
        try:
            path_status = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            raise ArtifactIOError(f"manifest does not exist: {root / manifest_path}") from None
        if stat.S_ISLNK(path_status.st_mode):
            raise UnsafeBundleError(f"manifest is a symbolic link: {root / manifest_path}")
        if not stat.S_ISREG(path_status.st_mode):
            raise UnsafeBundleError(f"manifest is not a regular file: {root / manifest_path}")

        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise UnsafeBundleError(f"manifest is not a regular file: {root / manifest_path}")
            if path_status.st_ino != before.st_ino or path_status.st_dev != before.st_dev:
                raise ArtifactIOError(f"manifest changed while opening: {root / manifest_path}")
            if before.st_size > _MAX_MANIFEST_BYTES:
                raise ManifestFormatError(
                    f"manifest exceeds {_MAX_MANIFEST_BYTES} bytes: {root / manifest_path}"
                )

            chunks: list[bytes] = []
            remaining = before.st_size
            while remaining:
                chunk = os.read(descriptor, min(_HASH_CHUNK_SIZE, remaining))
                if not chunk:
                    raise ArtifactIOError(f"manifest changed while reading: {root / manifest_path}")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise ArtifactIOError(f"manifest changed while reading: {root / manifest_path}")
            after = os.fstat(descriptor)
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ino != after.st_ino
                or before.st_dev != after.st_dev
            ):
                raise ArtifactIOError(f"manifest changed while reading: {root / manifest_path}")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise ArtifactIOError(f"cannot read manifest {root / manifest_path}: {exc}") from exc
    finally:
        os.close(parent_descriptor)


def _require_exact_keys(
    value: Mapping[str, Any], expected: frozenset[str], *, context: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing keys {missing}")
        if unknown:
            details.append(f"unknown keys {unknown}")
        raise ManifestFormatError(f"{context} has invalid fields: {', '.join(details)}")


def manifest_from_dict(value: object) -> ArtifactManifest:
    """Validate and construct a manifest from parsed JSON data."""

    if not isinstance(value, dict):
        raise ManifestFormatError("manifest root must be a JSON object")
    _require_exact_keys(
        value,
        frozenset(("schema_version", "hash_algorithm", "files")),
        context="manifest",
    )

    version = value["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise ManifestFormatError("schema_version must be an integer")
    if version != SCHEMA_VERSION:
        raise ManifestFormatError(
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}"
        )
    if value["hash_algorithm"] != HASH_ALGORITHM:
        raise ManifestFormatError(
            f"unsupported hash_algorithm {value['hash_algorithm']!r}; expected {HASH_ALGORITHM!r}"
        )

    raw_files = value["files"]
    if not isinstance(raw_files, list):
        raise ManifestFormatError("files must be a JSON array")

    records: list[FileRecord] = []
    seen: set[str] = set()
    for index, raw_record in enumerate(raw_files):
        context = f"files[{index}]"
        if not isinstance(raw_record, dict):
            raise ManifestFormatError(f"{context} must be a JSON object")
        _require_exact_keys(
            raw_record,
            frozenset(("path", "bytes", "sha256")),
            context=context,
        )
        relative = _canonical_relative_path(raw_record["path"], field=f"{context}.path")
        size = raw_record["bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ManifestFormatError(f"{context}.bytes must be a non-negative integer")
        digest = raw_record["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ManifestFormatError(
                f"{context}.sha256 must be 64 lowercase hexadecimal characters"
            )
        if relative in seen:
            raise ManifestFormatError(f"duplicate manifest path: {relative}")
        seen.add(relative)
        records.append(FileRecord(path=relative, bytes=size, sha256=digest))

    paths = [record.path for record in records]
    if paths != sorted(paths):
        raise ManifestFormatError("manifest file records must be sorted by path")
    return ArtifactManifest(files=tuple(records))


def load_manifest(
    bundle_root: os.PathLike[str] | str,
    *,
    manifest_path: str = DEFAULT_MANIFEST_PATH,
) -> ArtifactManifest:
    """Load and strictly validate a bundle manifest."""

    root = _bundle_root(bundle_root)
    relative, destination = _manifest_destination(root, manifest_path)

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ManifestFormatError(f"duplicate JSON object key: {key!r}")
            result[key] = value
        return result

    try:
        raw = _read_regular_file(root, relative)
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except UnicodeDecodeError as exc:
        raise ManifestFormatError(f"manifest is not valid UTF-8: {destination}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestFormatError(
            f"manifest is not valid JSON at line {exc.lineno}, column {exc.colno}: {destination}"
        ) from exc
    return manifest_from_dict(parsed)


def verify_bundle(
    bundle_root: os.PathLike[str] | str,
    *,
    manifest_path: str = DEFAULT_MANIFEST_PATH,
) -> VerificationReport:
    """Compare a bundle with its manifest and return all content differences."""

    root = _bundle_root(bundle_root)
    relative, _ = _manifest_destination(root, manifest_path)
    expected_manifest = load_manifest(root, manifest_path=relative)
    actual_records = inventory_bundle(root, exclude=(relative,))

    expected = {record.path: record for record in expected_manifest.files}
    actual = {record.path: record for record in actual_records}
    expected_paths = set(expected)
    actual_paths = set(actual)

    common = sorted(expected_paths & actual_paths)
    size_mismatches = tuple(
        SizeMismatch(path, expected[path].bytes, actual[path].bytes)
        for path in common
        if expected[path].bytes != actual[path].bytes
    )
    hash_mismatches = tuple(
        HashMismatch(path, expected[path].sha256, actual[path].sha256)
        for path in common
        if expected[path].sha256 != actual[path].sha256
    )
    return VerificationReport(
        missing=tuple(sorted(expected_paths - actual_paths)),
        unexpected=tuple(sorted(actual_paths - expected_paths)),
        size_mismatches=size_mismatches,
        hash_mismatches=hash_mismatches,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m compact_vio.artifacts",
        description="Create or verify deterministic experiment-bundle manifests.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("create", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("bundle", help="bundle directory")
        subparser.add_argument(
            "--manifest",
            default=DEFAULT_MANIFEST_PATH,
            help=f"relative manifest path (default: {DEFAULT_MANIFEST_PATH})",
        )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Exit status 0 means success, 1 means verification differences were found,
    and 2 means the input, bundle, or manifest was invalid.
    """

    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "create":
            manifest = create_manifest(arguments.bundle, manifest_path=arguments.manifest)
            print(
                json.dumps(
                    {
                        "ok": True,
                        "manifest": arguments.manifest,
                        "files": len(manifest.files),
                    },
                    sort_keys=True,
                )
            )
            return 0

        report = verify_bundle(arguments.bundle, manifest_path=arguments.manifest)
        print(json.dumps(report.to_dict(), sort_keys=True))
        return 0 if report.ok else 1
    except ArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "ArtifactError",
    "ArtifactIOError",
    "ArtifactManifest",
    "DEFAULT_MANIFEST_PATH",
    "FileRecord",
    "HashMismatch",
    "ManifestFormatError",
    "SizeMismatch",
    "UnsafeBundleError",
    "VerificationReport",
    "create_manifest",
    "inventory_bundle",
    "load_manifest",
    "main",
    "manifest_from_dict",
    "verify_bundle",
]

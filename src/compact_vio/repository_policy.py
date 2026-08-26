"""Deterministic policy checks for files intended for Git.

The checker reports filenames and detector names, never matching secret values.
It is intentionally conservative: only high-confidence credential formats and
private-key headers are detected. It complements, but does not replace, hosted
secret scanning and review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

MAX_TRACKED_BYTES = 10 * 1024 * 1024
FORBIDDEN_SUFFIXES = frozenset({".pt", ".pth", ".ckpt", ".onnx", ".engine", ".plan"})
TEXT_SUFFIXES = frozenset({".json", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"})
TEXT_FILENAMES = frozenset({".gitattributes", ".gitignore"})
_SECRET_PATTERNS = (
    ("private_key", re.compile(rb"-----BEGIN (?:[A-Z0-9][A-Z0-9 ]* )?PRIVATE KEY-----")),
    ("github_token", re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("aws_access_key", re.compile(rb"AKIA[0-9A-Z]{16}")),
)


class RepositoryPolicyError(Exception):
    """Raised when the repository root or Git inventory cannot be inspected."""


@dataclass(frozen=True, order=True, slots=True)
class Violation:
    """One policy violation without any captured file content."""

    path: str
    code: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "detail": self.detail}


def _canonical_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise ValueError("path is empty or contains a forbidden character")
    path = PurePosixPath(value)
    if path.is_absolute() or value != path.as_posix():
        raise ValueError("path is not a canonical repository-relative POSIX path")
    if not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise ValueError("path contains an unsafe component")
    return value


def _read_regular_file(path: Path, expected: os.stat_result) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise RepositoryPolicyError(f"tracked entry is not a regular file: {path}")
        if expected.st_dev != opened.st_dev or expected.st_ino != opened.st_ino:
            raise RepositoryPolicyError(f"tracked file changed while opening: {path}")
        chunks: list[bytes] = []
        remaining = opened.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise RepositoryPolicyError(f"tracked file changed while reading: {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise RepositoryPolicyError(f"tracked file changed while reading: {path}")
        finished = os.fstat(descriptor)
        if (
            opened.st_size != finished.st_size
            or opened.st_mtime_ns != finished.st_mtime_ns
            or opened.st_dev != finished.st_dev
            or opened.st_ino != finished.st_ino
        ):
            raise RepositoryPolicyError(f"tracked file changed while reading: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def check_paths(
    repository_root: os.PathLike[str] | str,
    paths: Iterable[str],
    *,
    max_bytes: int = MAX_TRACKED_BYTES,
) -> tuple[Violation, ...]:
    """Check an explicit set of intended tracked paths.

    This function never searches ignored or unrelated files. Results are sorted
    and contain no matching file content.
    """

    root = Path(repository_root).resolve(strict=True)
    if not root.is_dir():
        raise RepositoryPolicyError(f"repository root is not a directory: {root}")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes < 0:
        raise ValueError("max_bytes must be a non-negative integer")

    violations: list[Violation] = []
    seen: set[str] = set()
    for supplied in sorted(paths):
        try:
            relative = _canonical_path(supplied)
        except ValueError as exc:
            violations.append(Violation(str(supplied), "unsafe_path", str(exc)))
            continue
        if relative in seen:
            violations.append(Violation(relative, "duplicate_path", "path appears more than once"))
            continue
        seen.add(relative)
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            status = path.lstat()
        except FileNotFoundError:
            violations.append(Violation(relative, "missing", "tracked path does not exist"))
            continue
        except OSError as exc:
            raise RepositoryPolicyError(f"cannot inspect tracked path {relative}: {exc}") from exc

        if stat.S_ISLNK(status.st_mode):
            violations.append(
                Violation(relative, "symlink", "tracked symbolic links are forbidden")
            )
            continue
        if not stat.S_ISREG(status.st_mode):
            violations.append(
                Violation(relative, "special_file", "tracked entry is not a regular file")
            )
            continue
        if status.st_size > max_bytes:
            violations.append(
                Violation(
                    relative,
                    "file_too_large",
                    f"{status.st_size} bytes exceeds the {max_bytes}-byte policy limit",
                )
            )
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            violations.append(
                Violation(
                    relative,
                    "forbidden_artifact",
                    "binary artifact type is not allowed in Git",
                )
            )

        content = _read_regular_file(path, status)
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_FILENAMES:
            if b"\x00" in content:
                violations.append(
                    Violation(relative, "text_nul", "governed text contains a NUL byte")
                )
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                violations.append(
                    Violation(relative, "invalid_utf8", "governed text is not valid UTF-8")
                )
        for detector, pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                violations.append(
                    Violation(
                        relative,
                        f"secret_{detector}",
                        f"high-confidence {detector} pattern detected; value suppressed",
                    )
                )

    return tuple(sorted(violations))


def intended_git_paths(repository_root: os.PathLike[str] | str) -> tuple[str, ...]:
    """Return cached and non-ignored untracked paths from Git."""

    root = Path(repository_root).resolve(strict=True)
    try:
        output = subprocess.check_output(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
            ]
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RepositoryPolicyError(f"cannot obtain Git file inventory: {exc}") from exc
    try:
        return tuple(item.decode("utf-8") for item in output.split(b"\0") if item)
    except UnicodeDecodeError as exc:
        raise RepositoryPolicyError("Git inventory contains a non-UTF-8 path") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-repo-check",
        description=(
            "Check intended Git files for artifact, size, text, and secret policy violations."
        ),
    )
    parser.add_argument("repository", nargs="?", default=".", help="repository root")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        paths = intended_git_paths(arguments.repository)
        violations = check_paths(arguments.repository, paths)
    except (RepositoryPolicyError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "ok": not violations,
                "files_checked": len(paths),
                "violations": [violation.to_dict() for violation in violations],
            },
            sort_keys=True,
        )
    )
    return 0 if not violations else 1


if __name__ == "__main__":
    raise SystemExit(main())

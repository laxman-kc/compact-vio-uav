#!/usr/bin/env python3
"""Create CompactVIO's synthetic workflow bundle without running inference."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from pathlib import Path

_DEFAULT_OUTPUT = Path("outputs/compact-vio-workflow-example.zip")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Create the rights-cleared synthetic CompactVIO workflow bundle. "
            "This command does not load a model or run inference."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        help=f"destination ZIP path (default: {_DEFAULT_OUTPUT})",
    )
    return parser


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        from compact_vio.learning.demo_bundle import (
            RecordingBundleError,
            create_workflow_example_bundle,
        )
    except ImportError as error:
        raise SystemExit(
            "CompactVIO and its data dependency are required. "
            "Install them with: python -m pip install -e '.[data]'"
        ) from error

    try:
        output = create_workflow_example_bundle(args.output)
    except RecordingBundleError as error:
        raise SystemExit(f"Cannot create example bundle: {error}") from error

    print(f"Created: {output}")
    print(f"Size: {output.stat().st_size} bytes")
    print(f"SHA-256: {_sha256(output)}")
    print("No model was loaded and no inference was run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command-line export of a selected training checkpoint for inference."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from compact_vio.learning.errors import LearningError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compact-vio-export-inference",
        description=(
            "Export a validated training checkpoint as an optimizer-free inference artifact."
        ),
    )
    parser.add_argument(
        "--source-checkpoint",
        required=True,
        help="regular non-symlink training checkpoint file",
    )
    parser.add_argument(
        "--expected-source-sha256",
        required=True,
        help="published lowercase SHA-256 of the selected training checkpoint",
    )
    parser.add_argument(
        "--inference-policy",
        required=True,
        metavar="POLICY_ID",
        help="frozen state reset/carry policy ID, validated by the exporter",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="new inference checkpoint path; existing paths are never overwritten",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        # Keep parser construction and ``--help`` available in installations
        # without the optional Torch training stack.
        from compact_vio.learning.inference_checkpoint import (
            ARTIFACT_TRANSPORT_SHA256_SCOPE_ID,
            METADATA_SHA256_SCOPE_ID,
            export_inference_checkpoint,
        )

        result = export_inference_checkpoint(
            args.source_checkpoint,
            args.output,
            expected_source_sha256=args.expected_source_sha256,
            inference_policy_id=args.inference_policy,
        )
    except (LearningError, OSError, RuntimeError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "event": "inference_export_failed",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "artifact_sha256": result.artifact_sha256,
                "artifact_transport_sha256": result.artifact_transport_sha256,
                "artifact_transport_sha256_scope_id": ARTIFACT_TRANSPORT_SHA256_SCOPE_ID,
                "canonical_identity_sha256": result.canonical_identity_sha256,
                "canonical_identity_sha256_scope_id": METADATA_SHA256_SCOPE_ID,
                "event": "inference_export_complete",
                "execution_api_id": result.identity.execution_api_id,
                "inference_policy_id": result.identity.inference_policy_id,
                "metadata_sha256": result.metadata_sha256,
                "model_state_sha256": result.identity.model_state_sha256,
                "output": str(result.path),
                "selected_source_epoch": result.identity.selected_source_epoch,
                "selected_source_metrics": result.identity.metrics,
                "source_checkpoint_sha256": result.identity.source_checkpoint_sha256,
            },
            sort_keys=True,
            allow_nan=False,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]

"""Score one learned-VIO checkpoint on one complete EuRoC full-pose sequence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from compact_vio.learning.errors import LearningError

_STATE_POLICIES = ("independent", "stateful")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise LearningError(f"cannot hash checkpoint {path}: {exc}") from exc
    return digest.hexdigest()


def _increment(
    identity: Any,
    motion: Any,
) -> Any:
    from compact_vio.evaluation.se3 import RelativePoseIncrement

    values = tuple(float(value) for value in motion.tolist())
    return RelativePoseIncrement(
        sequence_id=identity.sequence_id,
        sample_id=f"{identity.previous_timestamp_ns}:{identity.current_timestamp_ns}",
        start_timestamp_ns=identity.previous_timestamp_ns,
        end_timestamp_ns=identity.current_timestamp_ns,
        translation_previous_body_m=values[:3],  # type: ignore[arg-type]
        rotation_vector_previous_to_current_rad=values[3:],  # type: ignore[arg-type]
    )


def evaluate_checkpoint_on_euroc_sequence(
    checkpoint_path: Path | str,
    sequence_root: Path | str,
    *,
    device: Any = "cpu",
    unroll_pairs: int = 128,
    num_workers: int = 0,
    expected_checkpoint_sha256: str | None = None,
    state_policy: str,
) -> dict[str, object]:
    """Run a frozen checkpoint and return raw full-pose and zero-motion metrics."""

    try:
        import torch
        from torch.utils.data import DataLoader

        from compact_vio.data.euroc import load_euroc_sequence
        from compact_vio.evaluation.se3 import (
            RelativePoseIncrement,
            evaluate_relative_pose_sequence,
            zero_motion_baseline,
        )
        from compact_vio.learning.dataset import (
            EuRoCSequenceDataset,
            collate_vio_sequence_batch,
        )
        from compact_vio.learning.inference import (
            load_inference_model,
            predict_sequence_batch,
        )
        from compact_vio.learning.inference_checkpoint import (
            INDEPENDENT_INFERENCE_POLICY_ID,
            STATEFUL_INFERENCE_POLICY_ID,
        )
    except ImportError as exc:  # pragma: no cover - dependency-light installation
        from compact_vio.learning.errors import LearningDependencyError

        raise LearningDependencyError(
            "full-pose checkpoint evaluation requires the project training extra"
        ) from exc

    if type(unroll_pairs) is not int or unroll_pairs <= 0:
        raise LearningError("unroll_pairs must be a positive integer")
    if type(num_workers) is not int or num_workers < 0:
        raise LearningError("num_workers must be a non-negative integer")
    if type(state_policy) is not str or state_policy not in _STATE_POLICIES:
        raise LearningError(f"state_policy must be one of {_STATE_POLICIES!r}")
    inference_policy_id = (
        INDEPENDENT_INFERENCE_POLICY_ID
        if state_policy == "independent"
        else STATEFUL_INFERENCE_POLICY_ID
    )
    effective_unroll_pairs = 1 if state_policy == "independent" else unroll_pairs
    actual_device = torch.device(device)
    if actual_device.type == "cuda" and not torch.cuda.is_available():
        raise LearningError("CUDA was requested but torch.cuda.is_available() is false")
    checkpoint = Path(checkpoint_path).resolve()
    sequence_path = Path(sequence_root).resolve()
    observed_checkpoint_sha256 = _sha256_file(checkpoint)
    if (
        expected_checkpoint_sha256 is not None
        and expected_checkpoint_sha256 != observed_checkpoint_sha256
    ):
        raise LearningError(
            "checkpoint SHA-256 mismatch: expected "
            f"{expected_checkpoint_sha256}, got {observed_checkpoint_sha256}"
        )
    model, metadata = load_inference_model(
        checkpoint,
        device=actual_device,
        expected_inference_policy_id=inference_policy_id,
        expected_checkpoint_sha256=expected_checkpoint_sha256,
    )
    sequence = load_euroc_sequence(sequence_path)
    dataset = EuRoCSequenceDataset(
        (sequence,),
        unroll_pairs=effective_unroll_pairs,
        model_config=metadata.config.model,
        data_config=metadata.config.data,
        frame_strides=(1,),
    )
    loader = DataLoader(
        dataset,
        batch_size=1,
        shuffle=False,
        num_workers=num_workers,
        collate_fn=collate_vio_sequence_batch,
        pin_memory=actual_device.type == "cuda",
        persistent_workers=num_workers > 0,
    )

    reference: list[RelativePoseIncrement] = []
    predicted: list[RelativePoseIncrement] = []
    fusion_state: torch.Tensor | None = None
    active_chain_id: str | None = None
    next_chunk_index = 0
    for batch in loader:
        if len(batch.chain_ids) != 1:
            raise LearningError("full-pose evaluation requires sequence batch size one")
        chain_id = batch.chain_ids[0]
        chunk_index = batch.chunk_indices[0]
        if batch.chain_starts[0]:
            if chunk_index != 0:
                raise LearningError("a chain start must have chunk_index zero")
            fusion_state = None
            active_chain_id = chain_id
            next_chunk_index = 0
        if chain_id != active_chain_id or chunk_index != next_chunk_index:
            raise LearningError("evaluation chunks must be contiguous within one native chain")
        output = predict_sequence_batch(
            model,
            batch,
            device=actual_device,
            initial_fusion_state=fusion_state,
        )
        if not torch.equal(output.step_mask, batch.step_mask.to(device="cpu")):
            raise LearningError("prediction mask differs from the source sequence mask")
        fusion_state = output.final_fusion_state if state_policy == "stateful" else None
        for step, active in enumerate(batch.step_mask[0].tolist()):
            if not active:
                continue
            identity = batch.identities[0][step]
            if identity is None:
                raise LearningError("valid evaluation step has no source identity")
            reference.append(_increment(identity, batch.target_motion[0, step].to(device="cpu")))
            predicted.append(_increment(identity, output.motion_vectors[0, step]))
        next_chunk_index += 1
        if batch.chain_ends[0]:
            fusion_state = None
            active_chain_id = None
            next_chunk_index = 0

    if active_chain_id is not None:
        raise LearningError("evaluation ended before the active sequence chain completed")
    if len(reference) != dataset.pair_count or len(predicted) != dataset.pair_count:
        raise LearningError(
            "checkpoint evaluation did not produce exact complete native-pair coverage"
        )
    candidate_metrics = evaluate_relative_pose_sequence(tuple(reference), tuple(predicted))
    zero_metrics = zero_motion_baseline(tuple(reference))
    if candidate_metrics.reference_path_length_m <= 0.0:
        raise LearningError("reference path length must be positive for the acceptance ratio")
    path_length_ratio = (
        candidate_metrics.predicted_path_length_m / candidate_metrics.reference_path_length_m
    )
    checks = {
        "complete_full_pose_coverage": candidate_metrics.complete,
        "beats_zero_raw_translation_ate": (
            candidate_metrics.raw_translation_ate_rmse_m < zero_metrics.raw_translation_ate_rmse_m
        ),
        "beats_zero_final_translation_drift": (
            candidate_metrics.final_translation_drift_m < zero_metrics.final_translation_drift_m
        ),
        "beats_zero_relative_translation": (
            candidate_metrics.relative_translation_rmse_m < zero_metrics.relative_translation_rmse_m
        ),
        "beats_zero_relative_rotation": (
            candidate_metrics.relative_rotation_rmse_rad < zero_metrics.relative_rotation_rmse_rad
        ),
        "path_length_ratio_in_0_8_to_1_2": 0.8 <= path_length_ratio <= 1.2,
    }
    return {
        "record_type": "compact_vio_full_pose_checkpoint_evaluation",
        "schema_version": "1.0.0",
        "sequence_id": sequence.sequence_id,
        "checkpoint": {
            "path": str(checkpoint),
            "sha256": observed_checkpoint_sha256,
            "selected_epoch": metadata.epoch,
        },
        "inference": {
            "device": str(actual_device),
            "policy_id": inference_policy_id,
            "state_policy": state_policy,
            "requested_unroll_pairs": unroll_pairs,
            "effective_unroll_pairs": effective_unroll_pairs,
        },
        "candidate": asdict(candidate_metrics),
        "zero_motion": asdict(zero_metrics),
        "path_length_ratio": path_length_ratio,
        "acceptance_checks": checks,
        "accepted": all(checks.values()),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate one checkpoint on one complete EuRoC full-pose sequence."
    )
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--sequence", required=True, type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--state-policy", choices=_STATE_POLICIES, required=True)
    parser.add_argument("--unroll-pairs", type=int, default=128)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument("--checkpoint-sha256")
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        result = evaluate_checkpoint_on_euroc_sequence(
            args.checkpoint,
            args.sequence,
            device=args.device,
            unroll_pairs=args.unroll_pairs,
            num_workers=args.num_workers,
            expected_checkpoint_sha256=args.checkpoint_sha256,
            state_policy=args.state_policy,
        )
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (LearningError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover - exercised through main
    raise SystemExit(main())


__all__ = ["build_parser", "evaluate_checkpoint_on_euroc_sequence", "main"]

"""One-way terminal execution-envelope projection.

The projection intentionally omits every replay and estimator payload.  It is
an evidence envelope, not a serial form of ``RecorderSnapshot``: this module
does not provide reconstruction or deserialization.
"""

from __future__ import annotations

import json
from dataclasses import replace

from compact_vio.estimator import EstimatorOutput, OutputConvention
from compact_vio.execution import RecorderFailure, RecorderSnapshot, RecorderState
from compact_vio.replay import ReplayEvent

SCHEMA_VERSION = "1.0.0"
RECORD_TYPE = "recorder_snapshot_envelope"
PAYLOAD_POLICY_ID = "payloads-omitted-no-representation-no-hash/v1"


class RecorderSnapshotEnvelopeError(ValueError):
    """Raised when a snapshot cannot be projected as a terminal envelope."""


def _event_to_dict(event: ReplayEvent[object]) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "sequence_index": event.sequence_index,
        "stream_id": event.stream_id,
        "kind": event.kind.value,
        "clock_id": event.clock_id,
        "measurement_time_ns": event.measurement_time_ns,
        "available_time_ns": event.available_time_ns,
        "valid": event.valid,
    }


def _convention_to_dict(convention: OutputConvention) -> dict[str, object]:
    return {
        "convention_id": convention.convention_id,
        "reference_frame_id": convention.reference_frame_id,
        "tracked_frame_id": convention.tracked_frame_id,
        "transform_direction": convention.transform_direction,
        "translation_unit": convention.translation_unit,
        "rotation_representation": convention.rotation_representation,
        "rotation_unit": convention.rotation_unit,
        "health_schema_id": convention.health_schema_id,
    }


def _output_to_dict(output: EstimatorOutput[object]) -> dict[str, object]:
    return {
        "convention": _convention_to_dict(output.convention),
        "clock_id": output.clock_id,
        "estimate_time_ns": output.estimate_time_ns,
        "available_time_ns": output.available_time_ns,
        "reset_generation": output.reset_generation,
        "health_code": output.health_code,
        "valid": output.valid,
        "interface_id": output.interface_id,
        "initialized": output.initialized,
    }


def _failure_to_dict(failure: RecorderFailure) -> dict[str, object]:
    return {
        "event_id": failure.event.event_id,
        "event_sequence_index": failure.event.sequence_index,
        "exception_type_id": failure.exception_type_id,
        "session_delivery_recorded": failure.session_delivery_recorded,
        "reset_transition_applied": failure.reset_transition_applied,
    }


def recorder_snapshot_envelope_to_dict(
    snapshot: RecorderSnapshot,
) -> dict[str, object]:
    """Project one exact, valid terminal snapshot without payload material."""

    if type(snapshot) is not RecorderSnapshot:
        raise RecorderSnapshotEnvelopeError("snapshot must be an exact RecorderSnapshot")
    try:
        replace(snapshot)
    except Exception as error:
        raise RecorderSnapshotEnvelopeError(
            f"snapshot violates RecorderSnapshot: {error}"
        ) from error
    if snapshot.state is RecorderState.ACTIVE:
        raise RecorderSnapshotEnvelopeError("snapshot must be terminal")

    policy = snapshot.execution_policy
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": RECORD_TYPE,
        "payload_policy_id": PAYLOAD_POLICY_ID,
        "trace_id": snapshot.trace_id,
        "execution_policy": {
            "policy_id": policy.policy_id,
            "replay_exhaustion_semantics_id": policy.replay_exhaustion_semantics_id,
            "processing_exception_semantics_id": (policy.processing_exception_semantics_id),
            "process_control_exception_semantics_id": (
                policy.process_control_exception_semantics_id
            ),
            "unattempted_suffix_semantics_id": policy.unattempted_suffix_semantics_id,
        },
        "clock_id": snapshot.clock_id,
        "state": snapshot.state.value,
        "watermark_ns": snapshot.watermark_ns,
        "replay": {
            "consumed_count": snapshot.replay_consumed_count,
            "remaining_count": snapshot.replay_remaining_count,
            "exhausted": snapshot.replay_exhausted,
        },
        "session": {
            "delivered_event_count": snapshot.session_delivered_event_count,
            "reset_generation": snapshot.session_reset_generation,
        },
        "planned_events": [_event_to_dict(event) for event in snapshot.planned_events],
        "successful_batches": [
            {
                "event_id": batch.event.event_id,
                "event_sequence_index": batch.event.sequence_index,
                "outputs": [_output_to_dict(output) for output in batch.outputs],
            }
            for batch in snapshot.batches
        ],
        "failure": (None if snapshot.failure is None else _failure_to_dict(snapshot.failure)),
    }


def recorder_snapshot_envelope_to_json_bytes(snapshot: RecorderSnapshot) -> bytes:
    """Return canonical sorted, indented UTF-8 JSON terminated by one newline."""

    envelope = recorder_snapshot_envelope_to_dict(snapshot)
    rendered = (
        json.dumps(
            envelope,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    try:
        return rendered.encode("utf-8")
    except UnicodeEncodeError as error:
        raise RecorderSnapshotEnvelopeError(
            "snapshot envelope metadata must be valid UTF-8 text"
        ) from error


__all__ = [
    "PAYLOAD_POLICY_ID",
    "RECORD_TYPE",
    "SCHEMA_VERSION",
    "RecorderSnapshotEnvelopeError",
    "recorder_snapshot_envelope_to_dict",
    "recorder_snapshot_envelope_to_json_bytes",
]

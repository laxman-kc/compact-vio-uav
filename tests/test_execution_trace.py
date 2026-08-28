from __future__ import annotations

import json
import unittest
from collections.abc import Callable
from dataclasses import fields

from compact_vio.estimator import (
    EstimatorInterfaceDeclaration,
    EstimatorOutput,
    OutputConvention,
)
from compact_vio.execution import (
    CausalEstimatorRecorder,
    ExecutionLifecyclePolicyDeclaration,
    RecorderSnapshot,
    RecorderState,
)
from compact_vio.execution_trace import (
    PAYLOAD_POLICY_ID,
    RECORD_TYPE,
    SCHEMA_VERSION,
    RecorderSnapshotEnvelopeError,
    recorder_snapshot_envelope_to_dict,
    recorder_snapshot_envelope_to_json_bytes,
)
from compact_vio.replay import EventKind, ReplayEvent

CLOCK_ID = "synthetic-clock-μ"
TRACE_ID = "synthetic-trace-λ"

EXECUTION_POLICY = ExecutionLifecyclePolicyDeclaration(
    policy_id="synthetic-execution-policy-v1",
    replay_exhaustion_semantics_id="synthetic-replay-exhaustion-v1",
    processing_exception_semantics_id="synthetic-processing-exception-v1",
    process_control_exception_semantics_id="synthetic-process-control-exception-v1",
    unattempted_suffix_semantics_id="synthetic-unattempted-suffix-v1",
)

CONVENTION = OutputConvention(
    convention_id="synthetic-convention-v1",
    reference_frame_id="synthetic-reference-frame",
    tracked_frame_id="synthetic-tracked-frame",
    transform_direction="synthetic-reference-from-tracked",
    translation_unit="synthetic-translation-unit",
    rotation_representation="synthetic-rotation-representation",
    rotation_unit="synthetic-rotation-unit",
    health_schema_id="synthetic-health-schema-v1",
)

INTERFACE = EstimatorInterfaceDeclaration(
    interface_id="synthetic-interface-v1",
    state_schema_id="synthetic-state-schema-v1",
    state_variable_ids=("synthetic-pose", "synthetic-velocity"),
    metric_scale_mechanism_id="synthetic-scale-mechanism-v1",
    initialization_policy_id="synthetic-initialization-policy-v1",
    initialization_state_at_session_start=True,
    reset_policy_id="synthetic-reset-policy-v1",
    initialization_state_after_reset=False,
    valid_output_requires_initialized=True,
    recurrence_policy_id="synthetic-recurrence-policy-v1",
    recurrence_warmup_policy_id="synthetic-warmup-policy-v1",
    output_timestamp_semantics_id="synthetic-output-timestamp-v1",
    output_schedule_id="synthetic-output-schedule-v1",
    causality_policy_id="synthetic-causality-policy-v1",
    algorithmic_latency_definition_id="synthetic-algorithmic-latency-v1",
    processing_latency_definition_id="synthetic-processing-latency-v1",
    staleness_policy_id="synthetic-staleness-policy-v1",
    input_gap_policy_id="synthetic-input-gap-policy-v1",
)


class _FunctionEstimator:
    def __init__(
        self,
        function: Callable[[ReplayEvent[object]], tuple[EstimatorOutput[object], ...]],
    ) -> None:
        self._function = function

    def ingest(
        self,
        event: ReplayEvent[object],
        /,
    ) -> tuple[EstimatorOutput[object], ...]:
        return self._function(event)


class _UnobservablePayload:
    """Payload whose observation fails the test immediately."""

    def __repr__(self) -> str:
        raise AssertionError("payload repr must not be called")

    def __str__(self) -> str:
        raise AssertionError("payload str must not be called")

    def __bytes__(self) -> bytes:
        raise AssertionError("payload bytes must not be called")

    def __iter__(self):
        raise AssertionError("payload must not be traversed")

    def __eq__(self, other: object) -> bool:
        del other
        raise AssertionError("payload must not be compared")

    def __hash__(self) -> int:
        raise AssertionError("payload must not be hashed")


def _event(
    sequence_index: int,
    *,
    kind: EventKind = EventKind.IMU,
    payload: object | None = None,
    valid: bool = True,
) -> ReplayEvent[object]:
    if payload is None:
        payload = object()
    return ReplayEvent(
        event_id=f"event-{sequence_index}-δ",
        sequence_index=sequence_index,
        stream_id="control-δ" if kind is EventKind.RESET else "sensor-δ",
        kind=kind,
        clock_id=CLOCK_ID,
        measurement_time_ns=sequence_index * 10,
        available_time_ns=sequence_index * 10 + 2,
        payload=payload,
        valid=valid,
    )


def _output(
    event: ReplayEvent[object],
    *,
    ordinal: int,
    payload: object | None,
    valid: bool,
    initialized: bool = True,
) -> EstimatorOutput[object]:
    return EstimatorOutput(
        convention=CONVENTION,
        clock_id=event.clock_id,
        estimate_time_ns=event.measurement_time_ns + ordinal,
        available_time_ns=event.available_time_ns + ordinal,
        reset_generation=0,
        health_code=f"synthetic-health-{ordinal}-{'valid' if valid else 'invalid'}-δ",
        valid=valid,
        payload=payload,
        interface_id=INTERFACE.interface_id,
        initialized=initialized,
    )


def _recorder(
    events: tuple[ReplayEvent[object], ...],
    function: Callable[[ReplayEvent[object]], tuple[EstimatorOutput[object], ...]],
) -> CausalEstimatorRecorder[object, object]:
    return CausalEstimatorRecorder(
        events,
        _FunctionEstimator(function),
        clock_id=CLOCK_ID,
        convention=CONVENTION,
        interface=INTERFACE,
        trace_id=TRACE_ID,
        execution_policy=EXECUTION_POLICY,
    )


def _completed_snapshot(
    *,
    event_payload: object | None = None,
    output_payload: object | None = None,
) -> RecorderSnapshot:
    first = _event(3, kind=EventKind.CAMERA, payload=event_payload, valid=False)
    second = _event(4, payload=event_payload)
    if output_payload is None:
        output_payload = object()

    def run(event: ReplayEvent[object]) -> tuple[EstimatorOutput[object], ...]:
        if event is first:
            return ()
        return (
            _output(event, ordinal=0, payload=output_payload, valid=True),
            _output(event, ordinal=1, payload=None, valid=False, initialized=False),
        )

    return _recorder((first, second), run).record_to(1_000)


def _forge_record(source: object, **changes: object) -> object:
    forged = object.__new__(type(source))
    for field in fields(source):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(source, field.name)),
        )
    return forged


def _nested_keys(value: object, *, top_level: bool = True) -> tuple[str, ...]:
    keys: list[str] = []
    if type(value) is dict:
        for key, child in value.items():
            if type(key) is str and not (top_level and key == "payload_policy_id"):
                keys.append(key)
            keys.extend(_nested_keys(child, top_level=False))
    elif type(value) is list:
        for child in value:
            keys.extend(_nested_keys(child, top_level=False))
    return tuple(keys)


class RecorderSnapshotEnvelopeTests(unittest.TestCase):
    def test_empty_completed_snapshot_has_exact_v1_shape(self) -> None:
        snapshot = _recorder((), lambda _: ()).snapshot()

        envelope = recorder_snapshot_envelope_to_dict(snapshot)

        self.assertEqual(
            envelope,
            {
                "schema_version": "1.0.0",
                "record_type": "recorder_snapshot_envelope",
                "payload_policy_id": ("payloads-omitted-no-representation-no-hash/v1"),
                "trace_id": TRACE_ID,
                "execution_policy": {
                    "policy_id": EXECUTION_POLICY.policy_id,
                    "replay_exhaustion_semantics_id": (
                        EXECUTION_POLICY.replay_exhaustion_semantics_id
                    ),
                    "processing_exception_semantics_id": (
                        EXECUTION_POLICY.processing_exception_semantics_id
                    ),
                    "process_control_exception_semantics_id": (
                        EXECUTION_POLICY.process_control_exception_semantics_id
                    ),
                    "unattempted_suffix_semantics_id": (
                        EXECUTION_POLICY.unattempted_suffix_semantics_id
                    ),
                },
                "clock_id": CLOCK_ID,
                "state": "completed",
                "watermark_ns": None,
                "replay": {
                    "consumed_count": 0,
                    "remaining_count": 0,
                    "exhausted": True,
                },
                "session": {
                    "delivered_event_count": 0,
                    "reset_generation": 0,
                },
                "planned_events": [],
                "successful_batches": [],
                "failure": None,
            },
        )
        self.assertEqual(SCHEMA_VERSION, envelope["schema_version"])
        self.assertEqual(RECORD_TYPE, envelope["record_type"])
        self.assertEqual(PAYLOAD_POLICY_ID, envelope["payload_policy_id"])

    def test_completed_envelope_preserves_order_and_all_nonpayload_metadata(self) -> None:
        snapshot = _completed_snapshot()

        envelope = recorder_snapshot_envelope_to_dict(snapshot)

        self.assertEqual(envelope["state"], "completed")
        self.assertEqual(envelope["watermark_ns"], 1_000)
        self.assertEqual(
            envelope["replay"],
            {"consumed_count": 2, "remaining_count": 0, "exhausted": True},
        )
        self.assertEqual(
            envelope["session"],
            {"delivered_event_count": 2, "reset_generation": 0},
        )
        self.assertEqual(
            envelope["planned_events"],
            [
                {
                    "event_id": "event-3-δ",
                    "sequence_index": 3,
                    "stream_id": "sensor-δ",
                    "kind": "camera",
                    "clock_id": CLOCK_ID,
                    "measurement_time_ns": 30,
                    "available_time_ns": 32,
                    "valid": False,
                },
                {
                    "event_id": "event-4-δ",
                    "sequence_index": 4,
                    "stream_id": "sensor-δ",
                    "kind": "imu",
                    "clock_id": CLOCK_ID,
                    "measurement_time_ns": 40,
                    "available_time_ns": 42,
                    "valid": True,
                },
            ],
        )
        batches = envelope["successful_batches"]
        self.assertIs(type(batches), list)
        self.assertEqual(
            [(batch["event_id"], batch["event_sequence_index"]) for batch in batches],
            [("event-3-δ", 3), ("event-4-δ", 4)],
        )
        self.assertEqual(batches[0]["outputs"], [])
        self.assertEqual(
            batches[1]["outputs"],
            [
                {
                    "convention": {
                        "convention_id": CONVENTION.convention_id,
                        "reference_frame_id": CONVENTION.reference_frame_id,
                        "tracked_frame_id": CONVENTION.tracked_frame_id,
                        "transform_direction": CONVENTION.transform_direction,
                        "translation_unit": CONVENTION.translation_unit,
                        "rotation_representation": (CONVENTION.rotation_representation),
                        "rotation_unit": CONVENTION.rotation_unit,
                        "health_schema_id": CONVENTION.health_schema_id,
                    },
                    "clock_id": CLOCK_ID,
                    "estimate_time_ns": 40,
                    "available_time_ns": 42,
                    "reset_generation": 0,
                    "health_code": "synthetic-health-0-valid-δ",
                    "valid": True,
                    "interface_id": INTERFACE.interface_id,
                    "initialized": True,
                },
                {
                    "convention": {
                        "convention_id": CONVENTION.convention_id,
                        "reference_frame_id": CONVENTION.reference_frame_id,
                        "tracked_frame_id": CONVENTION.tracked_frame_id,
                        "transform_direction": CONVENTION.transform_direction,
                        "translation_unit": CONVENTION.translation_unit,
                        "rotation_representation": (CONVENTION.rotation_representation),
                        "rotation_unit": CONVENTION.rotation_unit,
                        "health_schema_id": CONVENTION.health_schema_id,
                    },
                    "clock_id": CLOCK_ID,
                    "estimate_time_ns": 41,
                    "available_time_ns": 43,
                    "reset_generation": 0,
                    "health_code": "synthetic-health-1-invalid-δ",
                    "valid": False,
                    "interface_id": INTERFACE.interface_id,
                    "initialized": False,
                },
            ],
        )
        self.assertIsNone(envelope["failure"])

    def test_failed_reset_envelope_retains_failure_and_unattempted_suffix_metadata(
        self,
    ) -> None:
        class SyntheticResetError(RuntimeError):
            pass

        reset = _event(1, kind=EventKind.RESET)
        later = _event(2)

        def fail(_: ReplayEvent[object]) -> tuple[EstimatorOutput[object], ...]:
            raise SyntheticResetError("secret failure message must be omitted")

        snapshot = _recorder((reset, later), fail).record_to(100)

        envelope = recorder_snapshot_envelope_to_dict(snapshot)
        encoded = recorder_snapshot_envelope_to_json_bytes(snapshot)

        self.assertEqual(envelope["state"], "failed")
        self.assertEqual(
            envelope["replay"],
            {"consumed_count": 1, "remaining_count": 1, "exhausted": False},
        )
        self.assertEqual(
            envelope["session"],
            {"delivered_event_count": 1, "reset_generation": 1},
        )
        self.assertEqual(envelope["successful_batches"], [])
        self.assertEqual(
            [event["event_id"] for event in envelope["planned_events"]],
            [reset.event_id, later.event_id],
        )
        self.assertEqual(
            envelope["failure"],
            {
                "event_id": reset.event_id,
                "event_sequence_index": reset.sequence_index,
                "exception_type_id": (
                    f"{SyntheticResetError.__module__}.{SyntheticResetError.__qualname__}"
                ),
                "session_delivery_recorded": True,
                "reset_transition_applied": True,
            },
        )
        self.assertNotIn(b"secret failure message", encoded)

    def test_payloads_are_never_observed_and_cannot_change_envelope_bytes(self) -> None:
        first_event_payload: dict[str, object] = {"event-secret-A": _UnobservablePayload()}
        first_event_payload["cycle"] = first_event_payload
        first_output_payload: list[object] = [
            "output-secret-A",
            _UnobservablePayload(),
        ]
        first_output_payload.append(first_output_payload)

        second_event_payload: dict[str, object] = {"event-secret-B": _UnobservablePayload()}
        second_event_payload["cycle"] = second_event_payload
        second_output_payload: list[object] = [
            "output-secret-B",
            _UnobservablePayload(),
        ]
        second_output_payload.append(second_output_payload)

        first_snapshot = _completed_snapshot(
            event_payload=first_event_payload,
            output_payload=first_output_payload,
        )
        second_snapshot = _completed_snapshot(
            event_payload=second_event_payload,
            output_payload=second_output_payload,
        )

        first_envelope = recorder_snapshot_envelope_to_dict(first_snapshot)
        first_bytes = recorder_snapshot_envelope_to_json_bytes(first_snapshot)
        second_bytes = recorder_snapshot_envelope_to_json_bytes(second_snapshot)

        self.assertEqual(first_bytes, second_bytes)
        for secret in (
            b"event-secret-A",
            b"event-secret-B",
            b"output-secret-A",
            b"output-secret-B",
        ):
            self.assertNotIn(secret, first_bytes)
            self.assertNotIn(secret, second_bytes)
        self.assertFalse(any("payload" in key.casefold() for key in _nested_keys(first_envelope)))
        self.assertEqual(first_envelope["payload_policy_id"], PAYLOAD_POLICY_ID)

    def test_json_bytes_are_deterministic_sorted_indented_utf8_with_one_newline(
        self,
    ) -> None:
        snapshot = _completed_snapshot()
        envelope = recorder_snapshot_envelope_to_dict(snapshot)

        first = recorder_snapshot_envelope_to_json_bytes(snapshot)
        second = recorder_snapshot_envelope_to_json_bytes(snapshot)
        expected = (
            json.dumps(
                envelope,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")

        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertTrue(first.startswith(b"{\n"))
        self.assertTrue(first.endswith(b"\n"))
        self.assertFalse(first.endswith(b"\n\n"))
        self.assertIn(TRACE_ID.encode("utf-8"), first)
        self.assertNotIn(b"\\u03bb", first)
        self.assertEqual(json.loads(first), envelope)

    def test_non_utf8_scalar_metadata_fails_with_envelope_error(self) -> None:
        recorder = CausalEstimatorRecorder(
            (),
            _FunctionEstimator(lambda _: ()),
            clock_id=CLOCK_ID,
            convention=CONVENTION,
            interface=INTERFACE,
            trace_id="\ud800",
            execution_policy=EXECUTION_POLICY,
        )

        with self.assertRaisesRegex(RecorderSnapshotEnvelopeError, "UTF-8"):
            recorder_snapshot_envelope_to_json_bytes(recorder.snapshot())

    def test_rejects_wrong_type_and_nonterminal_snapshot(self) -> None:
        for wrong in (None, object(), "snapshot"):
            with self.subTest(wrong_type=type(wrong).__name__):
                with self.assertRaises(RecorderSnapshotEnvelopeError):
                    recorder_snapshot_envelope_to_dict(wrong)  # type: ignore[arg-type]

        event = _event(1)
        active = _recorder((event,), lambda _: ()).snapshot()
        self.assertIs(active.state, RecorderState.ACTIVE)

        with self.assertRaisesRegex(RecorderSnapshotEnvelopeError, "terminal"):
            recorder_snapshot_envelope_to_dict(active)
        with self.assertRaisesRegex(RecorderSnapshotEnvelopeError, "terminal"):
            recorder_snapshot_envelope_to_json_bytes(active)

    def test_rejects_forged_nested_policy_event_output_and_failure(self) -> None:
        completed = _completed_snapshot()
        policy = _forge_record(
            completed.execution_policy,
            processing_exception_semantics_id=" ",
        )
        forged_policy_snapshot = _forge_record(completed, execution_policy=policy)

        original_event = completed.planned_events[0]
        event = _forge_record(original_event, event_id=" ")
        first_batch = completed.batches[0]
        batch_with_event = _forge_record(first_batch, event=event)
        forged_event_snapshot = _forge_record(
            completed,
            planned_events=(event, *completed.planned_events[1:]),
            batches=(batch_with_event, *completed.batches[1:]),
        )

        output = completed.batches[1].outputs[0]
        malformed_output = _forge_record(output, health_code=" ")
        second_batch = _forge_record(
            completed.batches[1],
            outputs=(malformed_output, *completed.batches[1].outputs[1:]),
        )
        forged_output_snapshot = _forge_record(
            completed,
            batches=(completed.batches[0], second_batch),
        )

        failed_event = _event(1)

        def fail(_: ReplayEvent[object]) -> tuple[EstimatorOutput[object], ...]:
            raise RuntimeError("not serialized")

        failed = _recorder((failed_event,), fail).record_to(100)
        malformed_failure = _forge_record(failed.failure, exception_type_id=" ")
        forged_failure_snapshot = _forge_record(failed, failure=malformed_failure)

        for label, snapshot in (
            ("policy", forged_policy_snapshot),
            ("event", forged_event_snapshot),
            ("output", forged_output_snapshot),
            ("failure", forged_failure_snapshot),
        ):
            with self.subTest(record=label):
                with self.assertRaises(RecorderSnapshotEnvelopeError):
                    recorder_snapshot_envelope_to_dict(snapshot)
                with self.assertRaises(RecorderSnapshotEnvelopeError):
                    recorder_snapshot_envelope_to_json_bytes(snapshot)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import inspect
import sys
import unittest
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace

from compact_vio.estimator import (
    EstimatorOutput,
    OutputConvention,
)
from compact_vio.evaluation import (
    OutputCoverageLedger,
    OutputCoverageOutcome,
    OutputEnvelopeSlot,
    OutputStatus,
    bind_output_coverage,
    summarize_output_coverage,
)
from compact_vio.execution import (
    CausalEstimatorRecorder,
    ExecutionLifecyclePolicyDeclaration,
    ExecutionRecorderError,
    RecorderState,
)
from compact_vio.replay import CausalReplay, EventKind, ReplayContractError, ReplayEvent

CONVENTION = OutputConvention(
    convention_id="synthetic-recorder-output-v1",
    reference_frame_id="synthetic-reference",
    tracked_frame_id="synthetic-tracked",
    transform_direction="synthetic-direction",
    translation_unit="synthetic-unit",
    rotation_representation="synthetic-rotation",
    rotation_unit="synthetic-rotation-unit",
    health_schema_id="synthetic-health-v1",
)

EXECUTION_POLICY = ExecutionLifecyclePolicyDeclaration(
    policy_id="synthetic-execution-policy-v1",
    replay_exhaustion_semantics_id="synthetic-replay-exhaustion-v1",
    processing_exception_semantics_id="synthetic-processing-exception-v1",
    process_control_exception_semantics_id="synthetic-process-control-exception-v1",
    unattempted_suffix_semantics_id="synthetic-unattempted-suffix-v1",
)


def _event(
    sequence_index: int,
    *,
    kind: EventKind = EventKind.IMU,
    valid: bool = True,
    clock_id: str = "synthetic-clock",
) -> ReplayEvent[int]:
    return ReplayEvent(
        event_id=f"event-{sequence_index}",
        sequence_index=sequence_index,
        stream_id="control" if kind is EventKind.RESET else "sensor",
        kind=kind,
        clock_id=clock_id,
        measurement_time_ns=sequence_index * 10,
        available_time_ns=sequence_index * 10,
        payload=sequence_index,
        valid=valid,
    )


def _output(
    event: ReplayEvent[int],
    *,
    valid: bool = True,
    reset_generation: int = 0,
    estimate_time_ns: int | None = None,
) -> EstimatorOutput[object]:
    if estimate_time_ns is None:
        estimate_time_ns = event.measurement_time_ns
    return EstimatorOutput(
        convention=CONVENTION,
        clock_id=event.clock_id,
        estimate_time_ns=estimate_time_ns,
        available_time_ns=event.available_time_ns,
        reset_generation=reset_generation,
        health_code="synthetic-valid" if valid else "synthetic-invalid",
        valid=valid,
        payload=object() if valid else None,
    )


class _FunctionEstimator:
    def __init__(
        self,
        function: Callable[[ReplayEvent[int]], tuple[EstimatorOutput[object], ...]],
    ) -> None:
        self.function = function
        self.seen: list[ReplayEvent[int]] = []

    def ingest(
        self,
        event: ReplayEvent[int],
        /,
    ) -> tuple[EstimatorOutput[object], ...]:
        self.seen.append(event)
        return self.function(event)


def _recorder(
    events: tuple[ReplayEvent[int], ...],
    estimator: _FunctionEstimator,
) -> CausalEstimatorRecorder[int, object]:
    return CausalEstimatorRecorder(
        events,
        estimator,
        clock_id="synthetic-clock",
        convention=CONVENTION,
        trace_id="synthetic-execution-trace-v1",
        execution_policy=EXECUTION_POLICY,
    )


class ExecutionLifecyclePolicyDeclarationTests(unittest.TestCase):
    def _values(self) -> dict[str, object]:
        return {
            "policy_id": "synthetic-execution-policy-v1",
            "replay_exhaustion_semantics_id": "synthetic-replay-exhaustion-v1",
            "processing_exception_semantics_id": "synthetic-processing-exception-v1",
            "process_control_exception_semantics_id": ("synthetic-process-control-exception-v1"),
            "unattempted_suffix_semantics_id": "synthetic-unattempted-suffix-v1",
        }

    def _declaration(self, **updates: object) -> ExecutionLifecyclePolicyDeclaration:
        values = self._values()
        values.update(updates)
        return ExecutionLifecyclePolicyDeclaration(**values)  # type: ignore[arg-type]

    def test_every_identifier_is_explicit_nonblank_exact_text(self) -> None:
        class TextSubclass(str):
            pass

        for field in self._values():
            for value in (" ", 1, TextSubclass("synthetic")):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ExecutionRecorderError, field):
                        self._declaration(**{field: value})

    def test_declaration_is_immutable_and_has_no_policy_defaults(self) -> None:
        declaration = self._declaration()

        self.assertFalse(hasattr(declaration, "__dict__"))
        self.assertTrue(
            all(
                parameter.default is inspect.Parameter.empty
                for parameter in inspect.signature(
                    ExecutionLifecyclePolicyDeclaration
                ).parameters.values()
            )
        )
        with self.assertRaises(FrozenInstanceError):
            declaration.policy_id = "changed"  # type: ignore[misc]


class CausalEstimatorRecorderTests(unittest.TestCase):
    def test_empty_replay_starts_completed_with_structurally_frozen_snapshot(self) -> None:
        recorder = _recorder((), _FunctionEstimator(lambda _: ()))

        snapshot = recorder.snapshot()

        self.assertIs(snapshot.execution_policy, EXECUTION_POLICY)
        self.assertEqual(snapshot.execution_policy_id, EXECUTION_POLICY.policy_id)
        self.assertEqual(snapshot.state, RecorderState.COMPLETED)
        self.assertIsNone(snapshot.watermark_ns)
        self.assertEqual(snapshot.batches, ())
        self.assertIsNone(snapshot.failure)
        self.assertTrue(snapshot.replay_exhausted)
        self.assertEqual(snapshot.replay_consumed_count, 0)
        self.assertEqual(snapshot.session_delivered_event_count, 0)
        self.assertFalse(hasattr(snapshot, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            snapshot.state = RecorderState.ACTIVE  # type: ignore[misc]

    def test_record_to_processes_due_events_one_at_a_time_and_preserves_output_tuples(
        self,
    ) -> None:
        events = (_event(1), _event(2), _event(3))
        first = _output(events[0], estimate_time_ns=1)
        second_a = _output(events[1])
        second_b = _output(events[1], valid=False)

        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            if event is events[0]:
                return (first,)
            if event is events[1]:
                return (second_a, second_b)
            return ()

        estimator = _FunctionEstimator(adapter)
        recorder = _recorder(events, estimator)

        snapshot = recorder.record_to(100)

        self.assertEqual(snapshot.state, RecorderState.COMPLETED)
        self.assertEqual(tuple(batch.event for batch in snapshot.batches), events)
        self.assertIs(snapshot.batches[0].outputs[0], first)
        self.assertEqual(snapshot.batches[1].outputs, (second_a, second_b))
        self.assertEqual(snapshot.batches[2].outputs, ())
        self.assertEqual(estimator.seen, list(events))
        self.assertEqual(snapshot.replay_consumed_count, 3)
        self.assertEqual(snapshot.session_delivered_event_count, 3)
        self.assertNotEqual(events[0].measurement_time_ns, first.estimate_time_ns)

    def test_partial_and_no_due_watermarks_preserve_point_in_time_snapshots(self) -> None:
        events = (_event(1), _event(2))
        recorder = _recorder(events, _FunctionEstimator(lambda event: (_output(event),)))

        before_due = recorder.record_to(9)
        first = recorder.record_to(10)
        completed = recorder.record_to(20)

        self.assertIs(before_due.execution_policy, EXECUTION_POLICY)
        self.assertIs(first.execution_policy, EXECUTION_POLICY)
        self.assertIs(completed.execution_policy, EXECUTION_POLICY)
        self.assertEqual(before_due.state, RecorderState.ACTIVE)
        self.assertEqual(before_due.watermark_ns, 9)
        self.assertEqual(before_due.batches, ())
        self.assertEqual(first.state, RecorderState.ACTIVE)
        self.assertEqual(len(first.batches), 1)
        self.assertEqual(completed.state, RecorderState.COMPLETED)
        self.assertEqual(len(completed.batches), 2)
        self.assertEqual(len(first.batches), 1)

    def test_reset_and_invalid_events_are_delivered_and_recorded_unchanged(self) -> None:
        events = (
            _event(1, valid=False),
            _event(2, kind=EventKind.RESET),
            _event(3),
        )
        generation = 0

        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            nonlocal generation
            if event.kind is EventKind.RESET:
                generation += 1
                return ()
            return (_output(event, reset_generation=generation),)

        recorder = _recorder(events, _FunctionEstimator(adapter))

        snapshot = recorder.record_to(100)

        self.assertFalse(snapshot.batches[0].event.valid)
        self.assertEqual(snapshot.batches[1].event.kind, EventKind.RESET)
        self.assertEqual(snapshot.batches[1].outputs, ())
        self.assertEqual(snapshot.batches[2].outputs[0].reset_generation, 1)
        self.assertEqual(snapshot.session_reset_generation, 1)
        with self.assertRaisesRegex(ExecutionRecorderError, "attempted reset events"):
            replace(snapshot, session_reset_generation=0)

    def test_failed_reset_retains_the_incremented_generation(self) -> None:
        reset = _event(1, kind=EventKind.RESET)

        def fail(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise RuntimeError("synthetic reset failure")

        snapshot = _recorder((reset,), _FunctionEstimator(fail)).record_to(10)

        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(snapshot.session_reset_generation, 1)
        self.assertTrue(snapshot.failure.session_delivery_recorded)
        self.assertTrue(snapshot.failure.reset_transition_applied)
        with self.assertRaisesRegex(ExecutionRecorderError, "requires the reset transition"):
            replace(snapshot.failure, reset_transition_applied=False)
        with self.assertRaisesRegex(ExecutionRecorderError, "attempted reset events"):
            replace(snapshot, session_reset_generation=0)

    def test_middle_adapter_failure_is_terminal_and_leaves_later_events_unconsumed(
        self,
    ) -> None:
        events = tuple(_event(index) for index in range(1, 5))

        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            if event is events[1]:
                raise RuntimeError("synthetic secret-free failure")
            return (_output(event),)

        estimator = _FunctionEstimator(adapter)
        recorder = _recorder(events, estimator)

        snapshot = recorder.record_to(100)

        self.assertIs(snapshot.execution_policy, EXECUTION_POLICY)
        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(tuple(batch.event for batch in snapshot.batches), (events[0],))
        self.assertIs(snapshot.failure.event, events[1])
        self.assertTrue(snapshot.failure.session_delivery_recorded)
        self.assertEqual(snapshot.failure.exception_type_id, "builtins.RuntimeError")
        self.assertFalse(hasattr(snapshot.failure, "exception_message"))
        self.assertEqual(snapshot.replay_consumed_count, 2)
        self.assertEqual(snapshot.session_delivered_event_count, 2)
        self.assertEqual(snapshot.replay_remaining_count, 2)
        self.assertEqual(estimator.seen, [events[0], events[1]])

        with self.assertRaisesRegex(ExecutionRecorderError, "terminal"):
            recorder.record_to(100)
        self.assertEqual(recorder.snapshot(), snapshot)
        self.assertEqual(estimator.seen, [events[0], events[1]])

    def test_failure_on_final_event_is_failed_even_when_replay_is_exhausted(self) -> None:
        event = _event(1)

        def adapter(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise ValueError("synthetic failure")

        recorder = _recorder((event,), _FunctionEstimator(adapter))
        snapshot = recorder.record_to(10)

        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertTrue(snapshot.replay_exhausted)
        self.assertEqual(snapshot.batches, ())
        self.assertIs(snapshot.failure.event, event)

    def test_malformed_multi_output_return_commits_no_partial_batch(self) -> None:
        event = _event(1)
        estimator = _FunctionEstimator(lambda event: (_output(event),))
        estimator.function = lambda event: (  # type: ignore[assignment,return-value]
            _output(event),
            "malformed-output",
        )
        recorder = _recorder((event,), estimator)

        snapshot = recorder.record_to(10)

        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(snapshot.batches, ())
        self.assertEqual(
            snapshot.failure.exception_type_id,
            "compact_vio.estimator.EstimatorContractError",
        )

    def test_tuple_subclass_cannot_hide_a_produced_output(self) -> None:
        class LengthHidingTuple(tuple):
            def __len__(self) -> int:
                return 0

        event = _event(1)
        hidden = LengthHidingTuple((_output(event),))
        estimator = _FunctionEstimator(lambda _: ())
        estimator.function = lambda _: hidden  # type: ignore[assignment,return-value]

        snapshot = _recorder((event,), estimator).record_to(10)

        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(snapshot.batches, ())
        self.assertEqual(
            snapshot.failure.exception_type_id,
            "compact_vio.estimator.EstimatorContractError",
        )

    def test_process_control_exception_terminalizes_then_reraises(self) -> None:
        events = (_event(1), _event(2))

        def interrupt(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise KeyboardInterrupt

        recorder = _recorder(events, _FunctionEstimator(interrupt))

        with self.assertRaises(KeyboardInterrupt):
            recorder.record_to(100)

        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(snapshot.failure.exception_type_id, "builtins.KeyboardInterrupt")
        self.assertTrue(snapshot.failure.session_delivery_recorded)
        self.assertEqual(snapshot.replay_remaining_count, 1)

    def test_interrupt_after_release_retains_undelivered_failure(self) -> None:
        events = (_event(1), _event(2))
        recorder = _recorder(events, _FunctionEstimator(lambda event: (_output(event),)))
        release_next = recorder._replay.release_next_to  # type: ignore[attr-defined]

        def release_then_interrupt(watermark_ns: int):
            release_next(watermark_ns)
            raise KeyboardInterrupt

        recorder._replay.release_next_to = release_then_interrupt  # type: ignore[attr-defined,method-assign]

        with self.assertRaises(KeyboardInterrupt):
            recorder.record_to(100)

        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertIs(snapshot.failure.event, events[0])
        self.assertFalse(snapshot.failure.session_delivery_recorded)
        self.assertFalse(snapshot.failure.reset_transition_applied)
        self.assertEqual(snapshot.replay_consumed_count, 1)
        self.assertEqual(snapshot.session_delivered_event_count, 0)
        self.assertEqual(snapshot.replay_remaining_count, 1)

    def test_interrupt_inside_release_rolls_back_without_losing_event(self) -> None:
        event = _event(1)
        recorder = _recorder((event,), _FunctionEstimator(lambda item: (_output(item),)))
        source_lines, first_line = inspect.getsourcelines(CausalReplay.release_next_to)
        cursor_line = first_line + next(
            index for index, line in enumerate(source_lines) if "self._cursor += 1" in line
        )

        def interrupt_before_cursor(frame, trace_event, arg):
            del arg
            if (
                frame.f_code is CausalReplay.release_next_to.__code__
                and trace_event == "line"
                and frame.f_lineno == cursor_line
            ):
                sys.settrace(None)
                raise KeyboardInterrupt
            return interrupt_before_cursor

        sys.settrace(interrupt_before_cursor)
        try:
            with self.assertRaises(KeyboardInterrupt):
                recorder.record_to(10)
        finally:
            sys.settrace(None)

        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.state, RecorderState.ACTIVE)
        self.assertIsNone(snapshot.watermark_ns)
        self.assertEqual(snapshot.replay_consumed_count, 0)
        self.assertEqual(recorder.record_to(10).state, RecorderState.COMPLETED)

    def test_interrupt_before_session_delivery_retains_undelivered_failure(self) -> None:
        event = _event(1, kind=EventKind.RESET)
        recorder = _recorder((event,), _FunctionEstimator(lambda item: (_output(item),)))

        def interrupt_before_delivery(_: ReplayEvent[int]):
            raise KeyboardInterrupt

        recorder._session.ingest = interrupt_before_delivery  # type: ignore[attr-defined,method-assign]

        with self.assertRaises(KeyboardInterrupt):
            recorder.record_to(10)

        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertIs(snapshot.failure.event, event)
        self.assertFalse(snapshot.failure.session_delivery_recorded)
        self.assertFalse(snapshot.failure.reset_transition_applied)
        self.assertEqual(snapshot.replay_consumed_count, 1)
        self.assertEqual(snapshot.session_delivered_event_count, 0)
        self.assertEqual(snapshot.session_reset_generation, 0)

    def test_interrupt_between_reset_transition_and_delivery_is_representable(self) -> None:
        reset = _event(1, kind=EventKind.RESET)
        recorder = _recorder((reset,), _FunctionEstimator(lambda _: ()))

        def interrupt_after_reset(_: ReplayEvent[int]):
            recorder._session._reset_generation += 1  # type: ignore[attr-defined]
            raise KeyboardInterrupt

        recorder._session.ingest = interrupt_after_reset  # type: ignore[attr-defined,method-assign]

        with self.assertRaises(KeyboardInterrupt):
            recorder.record_to(10)

        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertFalse(snapshot.failure.session_delivery_recorded)
        self.assertTrue(snapshot.failure.reset_transition_applied)
        self.assertEqual(snapshot.session_delivered_event_count, 0)
        self.assertEqual(snapshot.session_reset_generation, 1)

    def test_process_control_classification_uses_real_exception_type(self) -> None:
        class ControlSignal(BaseException):
            @property
            def __class__(self) -> type[Exception]:
                return Exception

        event = _event(1)

        def interrupt(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise ControlSignal

        recorder = _recorder((event,), _FunctionEstimator(interrupt))

        with self.assertRaises(ControlSignal):
            recorder.record_to(10)

        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(
            snapshot.failure.exception_type_id,
            f"{ControlSignal.__module__}.{ControlSignal.__qualname__}",
        )

    def test_process_control_exception_during_batch_retention_rolls_back_batch(self) -> None:
        class InterruptAfterAppend(list):
            def append(self, value: object) -> None:
                super().append(value)
                raise KeyboardInterrupt

        event = _event(1)
        recorder = _recorder((event,), _FunctionEstimator(lambda event: (_output(event),)))
        recorder._batches = InterruptAfterAppend()  # type: ignore[attr-defined]

        with self.assertRaises(KeyboardInterrupt):
            recorder.record_to(10)

        snapshot = recorder.snapshot()
        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(snapshot.batches, ())
        self.assertIs(snapshot.failure.event, event)
        self.assertEqual(snapshot.failure.exception_type_id, "builtins.KeyboardInterrupt")
        self.assertTrue(snapshot.failure.session_delivery_recorded)

    def test_reentrant_recording_becomes_one_terminal_processing_failure(self) -> None:
        event = _event(1)
        recorder: CausalEstimatorRecorder[int, object]

        def reenter(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            recorder.record_to(10)
            return ()

        recorder = _recorder((event,), _FunctionEstimator(reenter))

        snapshot = recorder.record_to(10)

        self.assertEqual(snapshot.state, RecorderState.FAILED)
        self.assertEqual(snapshot.batches, ())
        self.assertEqual(
            snapshot.failure.exception_type_id,
            "compact_vio.execution.ExecutionRecorderError",
        )

    def test_bad_watermark_is_nonterminal_and_does_not_change_progress(self) -> None:
        event = _event(1)
        recorder = _recorder((event,), _FunctionEstimator(lambda event: (_output(event),)))
        first = recorder.record_to(9)

        with self.assertRaisesRegex(ReplayContractError, "must not move backward"):
            recorder.record_to(8)

        self.assertEqual(recorder.snapshot(), first)
        completed = recorder.record_to(10)
        self.assertEqual(completed.state, RecorderState.COMPLETED)

    def test_completed_recorder_allows_idempotent_forward_watermark_only(self) -> None:
        event = _event(1)
        estimator = _FunctionEstimator(lambda event: (_output(event),))
        recorder = _recorder((event,), estimator)
        completed = recorder.record_to(10)

        later = recorder.record_to(100)

        self.assertEqual(later.state, RecorderState.COMPLETED)
        self.assertEqual(later.batches, completed.batches)
        self.assertEqual(len(estimator.seen), 1)
        with self.assertRaisesRegex(ReplayContractError, "must not move backward"):
            recorder.record_to(99)

    def test_constructor_owns_fresh_wrappers_and_rejects_malformed_inputs(self) -> None:
        event = _event(1)
        estimator = _FunctionEstimator(lambda _: ())
        recorder = CausalEstimatorRecorder(
            (event,),
            estimator,
            clock_id="synthetic-clock",
            convention=CONVENTION,
            trace_id="trace",
            execution_policy=EXECUTION_POLICY,
        )
        self.assertIs(recorder.snapshot().planned_events[0], event)

        with self.assertRaisesRegex(ReplayContractError, "uses clock"):
            CausalEstimatorRecorder(
                (_event(1, clock_id="other-clock"),),
                estimator,
                clock_id="synthetic-clock",
                convention=CONVENTION,
                trace_id="trace",
                execution_policy=EXECUTION_POLICY,
            )

        with self.assertRaisesRegex(ExecutionRecorderError, "events must be an iterable"):
            CausalEstimatorRecorder(
                None,  # type: ignore[arg-type]
                estimator,
                clock_id="synthetic-clock",
                convention=CONVENTION,
                trace_id="trace",
                execution_policy=EXECUTION_POLICY,
            )

        with self.assertRaisesRegex(ExecutionRecorderError, "trace_id"):
            CausalEstimatorRecorder(
                (event,),
                estimator,
                clock_id="synthetic-clock",
                convention=CONVENTION,
                trace_id=" ",
                execution_policy=EXECUTION_POLICY,
            )
        with self.assertRaisesRegex(
            ExecutionRecorderError,
            "ExecutionLifecyclePolicyDeclaration",
        ):
            CausalEstimatorRecorder(
                (event,),
                estimator,
                clock_id="synthetic-clock",
                convention=CONVENTION,
                trace_id="trace",
                execution_policy="raw-policy-id",  # type: ignore[arg-type]
            )

    def test_constructor_and_snapshot_revalidate_forged_nested_policy(self) -> None:
        forged = object.__new__(ExecutionLifecyclePolicyDeclaration)
        for field in fields(EXECUTION_POLICY):
            object.__setattr__(
                forged,
                field.name,
                " "
                if field.name == "processing_exception_semantics_id"
                else getattr(
                    EXECUTION_POLICY,
                    field.name,
                ),
            )

        event = _event(1)
        estimator = _FunctionEstimator(lambda _: ())
        with self.assertRaisesRegex(
            ExecutionRecorderError,
            "processing_exception_semantics_id",
        ):
            CausalEstimatorRecorder(
                (event,),
                estimator,
                clock_id="synthetic-clock",
                convention=CONVENTION,
                trace_id="trace",
                execution_policy=forged,
            )

        snapshot = _recorder((), estimator).snapshot()
        with self.assertRaisesRegex(
            ExecutionRecorderError,
            "processing_exception_semantics_id",
        ):
            replace(snapshot, execution_policy=forged)

    def test_snapshot_rejects_forged_counts_state_and_identity(self) -> None:
        recorder = _recorder((), _FunctionEstimator(lambda _: ()))
        snapshot = recorder.snapshot()

        for field, value, message in (
            ("trace_id", " ", "trace_id"),
            ("state", RecorderState.ACTIVE, "state"),
            ("replay_consumed_count", 1, "replay_consumed_count"),
            ("replay_exhausted", False, "replay_exhausted"),
            ("session_delivered_event_count", True, "non-negative integer"),
            ("session_reset_generation", 99, "attempted reset events"),
            ("batches", [], "batches"),
            ("planned_events", [], "planned_events"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ExecutionRecorderError, message):
                    replace(snapshot, **{field: value})

        event = _event(1)
        active = _recorder((event,), _FunctionEstimator(lambda _: ())).record_to(9)
        with self.assertRaisesRegex(ExecutionRecorderError, "complete planned event tuple"):
            replace(
                active,
                state=RecorderState.COMPLETED,
                replay_remaining_count=0,
                replay_exhausted=True,
            )

    def test_recorded_batches_feed_exact_coverage_binding_without_reconstruction(self) -> None:
        event = _event(1)
        recorder = _recorder((event,), _FunctionEstimator(lambda event: (_output(event),)))
        snapshot = recorder.record_to(10)
        outcome = OutputCoverageOutcome(
            opportunity_id="expected-0",
            output_status=OutputStatus.VALID,
            reference_available=True,
            usable=True,
            reason_codes=(),
        )
        summary = summarize_output_coverage(
            OutputCoverageLedger(
                ledger_id="synthetic-ledger",
                sequence_id="synthetic-sequence",
                segment_id="synthetic-segment",
                opportunity_definition_id="synthetic-opportunities",
                outcome_classification_policy_id="synthetic-classification",
                reason_schema_id="synthetic-reasons",
                expected_opportunity_ids=(outcome.opportunity_id,),
                outcomes=(outcome,),
            )
        )

        bound = bind_output_coverage(
            summary,
            batches=snapshot.batches,
            slots=(
                OutputEnvelopeSlot(
                    opportunity_id=outcome.opportunity_id,
                    trigger_event_id=event.event_id,
                    event_sequence_index=event.sequence_index,
                    output_ordinal=0,
                ),
            ),
        )

        self.assertIs(bound.batches[0], snapshot.batches[0])
        self.assertEqual(bound.observed_output_count, 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from collections.abc import Callable
from dataclasses import FrozenInstanceError, fields, replace

from compact_vio.estimator import EstimatorOutput, OutputConvention
from compact_vio.evaluation import (
    RECORDED_OUTPUT_COVERAGE_BINDING_ID,
    EventOutputBatch,
    ExecutionCoverageBindingError,
    OutputCoverageLedger,
    OutputCoverageOutcome,
    OutputEnvelopeSlot,
    OutputStatus,
    RecordedOutputCoverage,
    bind_recorded_output_coverage,
    summarize_output_coverage,
)
from compact_vio.execution import (
    CausalEstimatorRecorder,
    RecorderSnapshot,
    RecorderState,
)
from compact_vio.replay import EventKind, ReplayEvent

CONVENTION = OutputConvention(
    convention_id="synthetic-recorded-coverage-output-v1",
    reference_frame_id="synthetic-reference",
    tracked_frame_id="synthetic-tracked",
    transform_direction="synthetic-direction",
    translation_unit="synthetic-unit",
    rotation_representation="synthetic-rotation",
    rotation_unit="synthetic-rotation-unit",
    health_schema_id="synthetic-health-v1",
)


class _FunctionEstimator:
    def __init__(
        self,
        function: Callable[[ReplayEvent[int]], tuple[EstimatorOutput[object], ...]],
    ) -> None:
        self.function = function

    def ingest(
        self,
        event: ReplayEvent[int],
        /,
    ) -> tuple[EstimatorOutput[object], ...]:
        return self.function(event)


class _EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True


def _event(sequence_index: int) -> ReplayEvent[int]:
    return ReplayEvent(
        event_id=f"event-{sequence_index}",
        sequence_index=sequence_index,
        stream_id="sensor",
        kind=EventKind.IMU,
        clock_id="synthetic-clock",
        measurement_time_ns=sequence_index * 10,
        available_time_ns=sequence_index * 10,
        payload=sequence_index,
        valid=True,
    )


def _output(
    event: ReplayEvent[int],
    *,
    valid: bool = True,
) -> EstimatorOutput[object]:
    return EstimatorOutput(
        convention=CONVENTION,
        clock_id=event.clock_id,
        estimate_time_ns=event.measurement_time_ns,
        available_time_ns=event.available_time_ns,
        reset_generation=0,
        health_code="synthetic-valid" if valid else "synthetic-invalid",
        valid=valid,
        payload=object() if valid else None,
    )


def _snapshot(
    events: tuple[ReplayEvent[int], ...],
    function: Callable[[ReplayEvent[int]], tuple[EstimatorOutput[object], ...]],
    *,
    watermark_ns: int = 1_000,
) -> RecorderSnapshot:
    recorder = CausalEstimatorRecorder(
        events,
        _FunctionEstimator(function),
        clock_id="synthetic-clock",
        convention=CONVENTION,
        trace_id="synthetic-recorded-coverage-trace-v1",
        execution_policy_id="synthetic-recorded-coverage-policy-v1",
    )
    return recorder.record_to(watermark_ns)


def _outcome(
    opportunity_id: str,
    status: OutputStatus,
    *,
    reason_code: str | None = None,
) -> OutputCoverageOutcome:
    if status is OutputStatus.VALID:
        return OutputCoverageOutcome(
            opportunity_id=opportunity_id,
            output_status=status,
            reference_available=True,
            usable=True,
            reason_codes=(),
        )
    return OutputCoverageOutcome(
        opportunity_id=opportunity_id,
        output_status=status,
        reference_available=True,
        usable=False,
        reason_codes=(reason_code or f"caller-declared-{status.value}",),
    )


def _summary(
    outcomes: tuple[OutputCoverageOutcome, ...],
):
    return summarize_output_coverage(
        OutputCoverageLedger(
            ledger_id="synthetic-recorded-coverage-ledger-v1",
            sequence_id="synthetic-sequence",
            segment_id="synthetic-segment",
            opportunity_definition_id="caller-declared-opportunities-v1",
            outcome_classification_policy_id="caller-declared-outcomes-v1",
            reason_schema_id="caller-declared-reasons-v1",
            expected_opportunity_ids=tuple(outcome.opportunity_id for outcome in outcomes),
            outcomes=outcomes,
        )
    )


def _slot(
    opportunity_id: str,
    event: ReplayEvent[int],
    output_ordinal: int | None,
) -> OutputEnvelopeSlot:
    return OutputEnvelopeSlot(
        opportunity_id=opportunity_id,
        trigger_event_id=event.event_id,
        event_sequence_index=event.sequence_index,
        output_ordinal=output_ordinal,
    )


def _forged_snapshot(
    source: RecorderSnapshot,
    **changes: object,
) -> RecorderSnapshot:
    forged = object.__new__(RecorderSnapshot)
    for field in fields(source):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(source, field.name)),
        )
    return forged


def _forged_record(source: object, **changes: object) -> object:
    forged = object.__new__(type(source))
    for field in fields(source):
        object.__setattr__(
            forged,
            field.name,
            changes.get(field.name, getattr(source, field.name)),
        )
    return forged


class RecordedOutputCoverageTests(unittest.TestCase):
    def test_completed_execution_retains_full_snapshot_and_exact_output_binding(self) -> None:
        events = tuple(_event(index) for index in range(1, 4))

        def run(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            if event is events[0]:
                return (_output(event), _output(event, valid=False))
            if event is events[2]:
                return (_output(event),)
            return ()

        snapshot = _snapshot(events, run)
        outcomes = (
            _outcome("event-1-output-0", OutputStatus.VALID),
            _outcome("event-1-output-1", OutputStatus.INVALID),
            _outcome("event-2-missing", OutputStatus.MISSING),
            _outcome("event-3-output-0", OutputStatus.VALID),
        )
        summary = _summary(outcomes)
        slots = (
            _slot(outcomes[0].opportunity_id, events[0], 0),
            _slot(outcomes[1].opportunity_id, events[0], 1),
            _slot(outcomes[2].opportunity_id, events[1], None),
            _slot(outcomes[3].opportunity_id, events[2], 0),
        )

        result = bind_recorded_output_coverage(
            summary,
            snapshot=snapshot,
            slots=slots,
        )

        self.assertEqual(result.binding_id, RECORDED_OUTPUT_COVERAGE_BINDING_ID)
        self.assertIs(result.snapshot, snapshot)
        self.assertIs(result.coverage_summary, summary)
        self.assertIs(result.slots, slots)
        self.assertEqual(result.observed_output_count, 3)
        self.assertEqual(result.snapshot.planned_events, events)
        self.assertEqual(result.snapshot.state, RecorderState.COMPLETED)

    def test_failed_execution_allows_explicit_missing_failure_and_suffix_slots(self) -> None:
        events = tuple(_event(index) for index in range(1, 4))

        def fail_in_middle(
            event: ReplayEvent[int],
        ) -> tuple[EstimatorOutput[object], ...]:
            if event is events[1]:
                raise RuntimeError("synthetic adapter failure")
            return (_output(event),)

        snapshot = _snapshot(events, fail_in_middle)
        outcomes = (
            _outcome("first-produced", OutputStatus.VALID),
            _outcome(
                "failed-event-missing",
                OutputStatus.MISSING,
                reason_code="caller-classified-failed-trigger",
            ),
            _outcome(
                "suffix-event-missing",
                OutputStatus.MISSING,
                reason_code="caller-classified-unattempted-suffix",
            ),
        )
        summary = _summary(outcomes)

        result = bind_recorded_output_coverage(
            summary,
            snapshot=snapshot,
            slots=(
                _slot(outcomes[0].opportunity_id, events[0], 0),
                _slot(outcomes[1].opportunity_id, events[1], None),
                _slot(outcomes[2].opportunity_id, events[2], None),
            ),
        )

        self.assertEqual(result.snapshot.state, RecorderState.FAILED)
        self.assertIs(result.snapshot.failure.event, events[1])
        self.assertIs(result.snapshot.planned_events[2], events[2])
        self.assertEqual(result.observed_output_count, 1)
        self.assertEqual(
            result.coverage_summary.reason_counts[0].reason_code,
            "caller-classified-failed-trigger",
        )

    def test_failed_first_event_with_no_successful_batches_can_bind_all_missing(self) -> None:
        events = (_event(1), _event(2))

        def fail(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise RuntimeError("synthetic first-event failure")

        snapshot = _snapshot(events, fail)
        outcomes = (
            _outcome("failed", OutputStatus.MISSING),
            _outcome("unattempted", OutputStatus.MISSING),
        )

        result = bind_recorded_output_coverage(
            _summary(outcomes),
            snapshot=snapshot,
            slots=(
                _slot(outcomes[0].opportunity_id, events[0], None),
                _slot(outcomes[1].opportunity_id, events[1], None),
            ),
        )

        self.assertEqual(result.snapshot.batches, ())
        self.assertEqual(result.observed_output_count, 0)

    def test_active_snapshot_is_rejected_even_when_current_prefix_is_consistent(self) -> None:
        events = (_event(1), _event(2))
        snapshot = _snapshot(events, lambda event: (_output(event),), watermark_ns=10)
        self.assertEqual(snapshot.state, RecorderState.ACTIVE)
        summary = _summary((_outcome("first", OutputStatus.VALID),))

        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "terminal, not ACTIVE",
        ):
            bind_recorded_output_coverage(
                summary,
                snapshot=snapshot,
                slots=(_slot("first", events[0], 0),),
            )

    def test_produced_outcome_cannot_target_failed_or_unattempted_event(self) -> None:
        events = (_event(1), _event(2))

        def fail(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise RuntimeError("synthetic failure")

        snapshot = _snapshot(events, fail)
        summary = _summary((_outcome("claimed-produced", OutputStatus.VALID),))

        for event in events:
            with self.subTest(event=event.event_id):
                with self.assertRaisesRegex(
                    ExecutionCoverageBindingError,
                    "successfully recorded batch event",
                ):
                    bind_recorded_output_coverage(
                        summary,
                        snapshot=snapshot,
                        slots=(_slot("claimed-produced", event, 0),),
                    )

    def test_slots_require_exact_declared_order_and_known_planned_identity(self) -> None:
        events = (_event(1), _event(2))
        snapshot = _snapshot(events, lambda _: ())
        outcomes = (
            _outcome("first", OutputStatus.MISSING),
            _outcome("second", OutputStatus.MISSING),
        )
        summary = _summary(outcomes)
        complete = (
            _slot("first", events[0], None),
            _slot("second", events[1], None),
        )

        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "exactly and in order",
        ):
            bind_recorded_output_coverage(
                summary,
                snapshot=snapshot,
                slots=tuple(reversed(complete)),
            )

        unknown = replace(complete[0], trigger_event_id="unknown-event")
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "unknown planned event",
        ):
            bind_recorded_output_coverage(
                summary,
                snapshot=snapshot,
                slots=(unknown, complete[1]),
            )

        wrong_index = replace(complete[0], event_sequence_index=99)
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "wrong event_sequence_index",
        ):
            bind_recorded_output_coverage(
                summary,
                snapshot=snapshot,
                slots=(wrong_index, complete[1]),
            )

    def test_duplicate_out_of_range_and_unbound_recorded_outputs_fail(self) -> None:
        event = _event(1)
        snapshot = _snapshot((event,), lambda item: (_output(item),))

        duplicate_summary = _summary(
            (
                _outcome("first", OutputStatus.VALID),
                _outcome("duplicate", OutputStatus.VALID),
            )
        )
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "must not be bound twice",
        ):
            bind_recorded_output_coverage(
                duplicate_summary,
                snapshot=snapshot,
                slots=(
                    _slot("first", event, 0),
                    _slot("duplicate", event, 0),
                ),
            )

        one_valid = _summary((_outcome("expected", OutputStatus.VALID),))
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "does not identify",
        ):
            bind_recorded_output_coverage(
                one_valid,
                snapshot=snapshot,
                slots=(_slot("expected", event, 1),),
            )

        all_missing = _summary((_outcome("expected", OutputStatus.MISSING),))
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "every recorded output envelope",
        ):
            bind_recorded_output_coverage(
                all_missing,
                snapshot=snapshot,
                slots=(_slot("expected", event, None),),
            )

    def test_status_and_ordinal_must_match_recorded_envelope(self) -> None:
        event = _event(1)
        snapshot = _snapshot((event,), lambda item: (_output(item, valid=False),))

        valid_summary = _summary((_outcome("expected", OutputStatus.VALID),))
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "status must match",
        ):
            bind_recorded_output_coverage(
                valid_summary,
                snapshot=snapshot,
                slots=(_slot("expected", event, 0),),
            )

        invalid_summary = _summary((_outcome("expected", OutputStatus.INVALID),))
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "declare an output_ordinal",
        ):
            bind_recorded_output_coverage(
                invalid_summary,
                snapshot=snapshot,
                slots=(_slot("expected", event, None),),
            )

        missing_summary = _summary((_outcome("expected", OutputStatus.MISSING),))
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "missing outcome",
        ):
            bind_recorded_output_coverage(
                missing_summary,
                snapshot=snapshot,
                slots=(_slot("expected", event, 0),),
            )

    def test_wrong_types_and_class_spoofs_are_rejected_without_coercion(self) -> None:
        event = _event(1)
        snapshot = _snapshot((event,), lambda _: ())
        summary = _summary((_outcome("missing", OutputStatus.MISSING),))
        slot = _slot("missing", event, None)

        class SnapshotImpostor:
            @property
            def __class__(self) -> type[RecorderSnapshot]:
                return RecorderSnapshot

        class TupleSubclass(tuple):
            pass

        for changed_snapshot, changed_summary, changed_slots, message in (
            ("snapshot", summary, (slot,), "RecorderSnapshot"),
            (SnapshotImpostor(), summary, (slot,), "RecorderSnapshot"),
            (snapshot, "summary", (slot,), "OutputCoverageSummary"),
            (snapshot, summary, [slot], "exact tuple"),
            (snapshot, summary, TupleSubclass((slot,)), "exact tuple"),
            (snapshot, summary, ("slot",), "OutputEnvelopeSlot"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(ExecutionCoverageBindingError, message):
                    bind_recorded_output_coverage(
                        changed_summary,  # type: ignore[arg-type]
                        snapshot=changed_snapshot,  # type: ignore[arg-type]
                        slots=changed_slots,  # type: ignore[arg-type]
                    )

    def test_forged_snapshot_batch_identity_and_plan_order_are_revalidated(self) -> None:
        events = (_event(1), _event(2))
        snapshot = _snapshot(events, lambda event: (_output(event),))
        summary = _summary(
            (
                _outcome("first", OutputStatus.VALID),
                _outcome("second", OutputStatus.VALID),
            )
        )
        slots = (
            _slot("first", events[0], 0),
            _slot("second", events[1], 0),
        )

        equal_but_distinct_event = replace(events[0])
        forged_batch = replace(
            snapshot.batches[0],
            event=equal_but_distinct_event,
        )
        wrong_identity = _forged_snapshot(
            snapshot,
            batches=(forged_batch, snapshot.batches[1]),
        )
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "attempted events must be the exact prefix",
        ):
            bind_recorded_output_coverage(
                summary,
                snapshot=wrong_identity,
                slots=slots,
            )

        wrong_order = _forged_snapshot(
            snapshot,
            planned_events=tuple(reversed(snapshot.planned_events)),
        )
        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "RecorderSnapshot",
        ):
            bind_recorded_output_coverage(
                summary,
                snapshot=wrong_order,
                slots=slots,
            )

    def test_forged_exact_batch_revalidates_its_output_container(self) -> None:
        event = _event(1)
        snapshot = _snapshot((event,), lambda item: (_output(item),))
        summary = _summary((_outcome("expected", OutputStatus.VALID),))
        forged_batch = object.__new__(EventOutputBatch)
        object.__setattr__(forged_batch, "event", event)
        object.__setattr__(forged_batch, "outputs", [snapshot.batches[0].outputs[0]])
        forged = _forged_snapshot(snapshot, batches=(forged_batch,))

        with self.assertRaisesRegex(
            ExecutionCoverageBindingError,
            "outputs must be an exact tuple",
        ):
            bind_recorded_output_coverage(
                summary,
                snapshot=forged,
                slots=(_slot("expected", event, 0),),
            )

    def test_forged_nested_snapshot_records_are_revalidated(self) -> None:
        events = (_event(1), _event(2))

        def fail(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise RuntimeError("synthetic failure")

        failed_snapshot = _snapshot(events, fail)
        missing_summary = _summary((_outcome("missing", OutputStatus.MISSING),))
        missing_slot = (_slot("missing", events[1], None),)

        forged_suffix = _forged_record(
            events[1],
            kind="not-an-event-kind",
            measurement_time_ns=30,
            available_time_ns=20,
            valid=1,
        )
        forged_plan = _forged_snapshot(
            failed_snapshot,
            planned_events=(events[0], forged_suffix),
        )
        with self.assertRaisesRegex(ExecutionCoverageBindingError, "ReplayEvent"):
            bind_recorded_output_coverage(
                missing_summary,
                snapshot=forged_plan,
                slots=missing_slot,
            )

        forged_failure = _forged_record(
            failed_snapshot.failure,
            exception_type_id="",
        )
        forged_failure_snapshot = _forged_snapshot(
            failed_snapshot,
            failure=forged_failure,
        )
        with self.assertRaisesRegex(ExecutionCoverageBindingError, "RecorderFailure"):
            bind_recorded_output_coverage(
                missing_summary,
                snapshot=forged_failure_snapshot,
                slots=missing_slot,
            )

        completed = _snapshot((events[0],), lambda event: (_output(event),))
        original_output = completed.batches[0].outputs[0]
        forged_convention = _forged_record(
            original_output.convention,
            convention_id="",
        )
        forged_output = _forged_record(
            original_output,
            convention=forged_convention,
        )
        forged_batch = _forged_record(
            completed.batches[0],
            outputs=(forged_output,),
        )
        forged_output_snapshot = _forged_snapshot(
            completed,
            batches=(forged_batch,),
        )
        valid_summary = _summary((_outcome("valid", OutputStatus.VALID),))
        with self.assertRaisesRegex(ExecutionCoverageBindingError, "OutputConvention"):
            bind_recorded_output_coverage(
                valid_summary,
                snapshot=forged_output_snapshot,
                slots=(_slot("valid", events[0], 0),),
            )

    def test_forged_nested_coverage_records_are_revalidated(self) -> None:
        event = _event(1)
        snapshot = _snapshot((event,), lambda _: ())
        outcome = _outcome("missing", OutputStatus.MISSING)
        summary = _summary((outcome,))
        slots = (_slot("missing", event, None),)
        result = bind_recorded_output_coverage(
            summary,
            snapshot=snapshot,
            slots=slots,
        )

        forged_outcomes_container = _forged_record(
            summary.ledger,
            outcomes=[outcome],
        )
        forged_outcome = _forged_record(
            outcome,
            reference_available=1,
            usable=1,
            reason_codes=["forged"],
        )
        forged_outcome_record = _forged_record(
            summary.ledger,
            outcomes=(forged_outcome,),
        )
        forged_reason_count = _forged_record(
            summary.reason_counts[0],
            count=True,
        )
        forged_summaries = (
            _forged_record(summary, ledger=forged_outcomes_container),
            _forged_record(summary, ledger=forged_outcome_record),
            _forged_record(summary, reason_counts=(forged_reason_count,)),
        )

        for forged_summary in forged_summaries:
            with self.subTest(forged_summary=forged_summary):
                with self.assertRaises(ExecutionCoverageBindingError):
                    bind_recorded_output_coverage(
                        forged_summary,
                        snapshot=snapshot,
                        slots=slots,
                    )
                with self.assertRaises(ExecutionCoverageBindingError):
                    replace(result, coverage_summary=forged_summary)

    def test_result_revalidates_fields_and_is_frozen_and_slotted(self) -> None:
        event = _event(1)
        snapshot = _snapshot((event,), lambda _: ())
        summary = _summary((_outcome("missing", OutputStatus.MISSING),))
        result = bind_recorded_output_coverage(
            summary,
            snapshot=snapshot,
            slots=(_slot("missing", event, None),),
        )

        for field_name, value, message in (
            ("binding_id", "wrong", "binding_id"),
            ("binding_id", _EqualitySpoof(), "binding_id"),
            ("snapshot", "snapshot", "RecorderSnapshot"),
            ("coverage_summary", "summary", "OutputCoverageSummary"),
            ("slots", [], "exact tuple"),
            ("observed_output_count", True, "non-negative integer"),
            ("observed_output_count", 1, "observed_output_count"),
        ):
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(ExecutionCoverageBindingError, message):
                    replace(result, **{field_name: value})

        self.assertIsInstance(result, RecordedOutputCoverage)
        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.observed_output_count = 9  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()

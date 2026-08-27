from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from compact_vio.estimator import EstimatorOutput, OutputConvention
from compact_vio.evaluation import (
    EXACT_OUTPUT_COVERAGE_BINDING_ID,
    CoverageBindingError,
    EventOutputBatch,
    OutputCoverageLedger,
    OutputCoverageOutcome,
    OutputEnvelopeSlot,
    OutputStatus,
    bind_output_coverage,
    summarize_output_coverage,
)
from compact_vio.replay import EventKind, ReplayEvent

CONVENTION = OutputConvention(
    convention_id="synthetic-output-v1",
    reference_frame_id="synthetic-reference",
    tracked_frame_id="synthetic-tracked",
    transform_direction="synthetic-direction",
    translation_unit="synthetic-unit",
    rotation_representation="synthetic-rotation",
    rotation_unit="synthetic-rotation-unit",
    health_schema_id="synthetic-health-v1",
)


class _EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True


def _event(
    sequence_index: int,
    *,
    event_id: str | None = None,
    stream_id: str | None = None,
    measurement_time_ns: int | None = None,
    available_time_ns: int | None = None,
    clock_id: str = "synthetic-clock",
    kind: EventKind = EventKind.IMU,
    valid: bool = True,
) -> ReplayEvent[object]:
    if available_time_ns is None:
        available_time_ns = sequence_index * 10
    if measurement_time_ns is None:
        measurement_time_ns = available_time_ns
    return ReplayEvent(
        event_id=event_id or f"event-{sequence_index}",
        sequence_index=sequence_index,
        stream_id=stream_id
        or ("control" if kind is EventKind.RESET else f"stream-{sequence_index}"),
        kind=kind,
        clock_id=clock_id,
        measurement_time_ns=measurement_time_ns,
        available_time_ns=available_time_ns,
        payload=object(),
        valid=valid,
    )


def _output(
    *,
    valid: bool = True,
    estimate_time_ns: int = 10,
    available_time_ns: int = 10,
    clock_id: str = "synthetic-clock",
    reset_generation: int = 0,
) -> EstimatorOutput[object]:
    return EstimatorOutput(
        convention=CONVENTION,
        clock_id=clock_id,
        estimate_time_ns=estimate_time_ns,
        available_time_ns=available_time_ns,
        reset_generation=reset_generation,
        health_code="synthetic-valid" if valid else "synthetic-invalid",
        valid=valid,
        payload=object() if valid else None,
    )


def _outcome(
    opportunity_id: str,
    status: OutputStatus,
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
        reason_codes=(f"synthetic-{status.value}-reason",),
    )


def _summary(
    outcomes: tuple[OutputCoverageOutcome, ...],
):
    ledger = OutputCoverageLedger(
        ledger_id="synthetic-ledger-v1",
        sequence_id="synthetic-sequence",
        segment_id="synthetic-segment",
        opportunity_definition_id="synthetic-opportunities-v1",
        outcome_classification_policy_id="synthetic-outcome-policy-v1",
        reason_schema_id="synthetic-reasons-v1",
        expected_opportunity_ids=tuple(outcome.opportunity_id for outcome in outcomes),
        outcomes=outcomes,
    )
    return summarize_output_coverage(ledger)


def _slot(
    opportunity_id: str,
    event: ReplayEvent[object],
    output_ordinal: int | None,
) -> OutputEnvelopeSlot:
    return OutputEnvelopeSlot(
        opportunity_id=opportunity_id,
        trigger_event_id=event.event_id,
        event_sequence_index=event.sequence_index,
        output_ordinal=output_ordinal,
    )


class EventOutputBatchTests(unittest.TestCase):
    def test_batch_requires_exact_envelope_types_clock_and_causal_availability(self) -> None:
        event = _event(1)
        with self.assertRaisesRegex(CoverageBindingError, "ReplayEvent"):
            EventOutputBatch(event="event", outputs=())  # type: ignore[arg-type]
        with self.assertRaisesRegex(CoverageBindingError, "outputs must be a tuple"):
            EventOutputBatch(event=event, outputs=[])
        with self.assertRaisesRegex(CoverageBindingError, "EstimatorOutput"):
            EventOutputBatch(event=event, outputs=("output",))  # type: ignore[arg-type]
        with self.assertRaisesRegex(CoverageBindingError, "clock_id"):
            EventOutputBatch(event=event, outputs=(_output(clock_id="other-clock"),))
        with self.assertRaisesRegex(CoverageBindingError, "triggering event"):
            EventOutputBatch(
                event=_event(2),
                outputs=(_output(estimate_time_ns=10, available_time_ns=10),),
            )

    def test_batch_is_frozen_slotted_and_preserves_exact_tuple_identity(self) -> None:
        output = _output()
        batch = EventOutputBatch(event=_event(1), outputs=(output, output))

        self.assertIs(batch.outputs[0], output)
        self.assertIs(batch.outputs[1], output)
        self.assertFalse(hasattr(batch, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            batch.outputs = ()  # type: ignore[misc]


class OutputEnvelopeSlotTests(unittest.TestCase):
    def test_slot_requires_explicit_identity_event_and_optional_exact_ordinal(self) -> None:
        event = _event(1)
        base = _slot("expected-0", event, 0)
        for field, value, message in (
            ("opportunity_id", " ", "opportunity_id"),
            ("trigger_event_id", " ", "trigger_event_id"),
            ("event_sequence_index", True, "non-negative integer"),
            ("event_sequence_index", -1, "non-negative integer"),
            ("output_ordinal", True, "non-negative integer"),
            ("output_ordinal", -1, "non-negative integer"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(CoverageBindingError, message):
                    replace(base, **{field: value})

        self.assertIsNone(_slot("missing", event, None).output_ordinal)


class BindOutputCoverageTests(unittest.TestCase):
    def test_valid_invalid_and_missing_outcomes_bind_without_inference(self) -> None:
        produced_event = _event(1)
        silent_event = _event(2)
        valid_output = _output(valid=True)
        invalid_output = _output(valid=False)
        summary = _summary(
            (
                _outcome("expected-valid", OutputStatus.VALID),
                _outcome("expected-invalid", OutputStatus.INVALID),
                _outcome("expected-missing", OutputStatus.MISSING),
            )
        )

        result = bind_output_coverage(
            summary,
            batches=(
                EventOutputBatch(produced_event, (valid_output, invalid_output)),
                EventOutputBatch(silent_event, ()),
            ),
            slots=(
                _slot("expected-valid", produced_event, 0),
                _slot("expected-invalid", produced_event, 1),
                _slot("expected-missing", silent_event, None),
            ),
        )

        self.assertEqual(result.binding_id, EXACT_OUTPUT_COVERAGE_BINDING_ID)
        self.assertIs(result.coverage_summary, summary)
        self.assertEqual(result.observed_output_count, 2)
        self.assertEqual(result.coverage_summary.produced_count, 2)
        self.assertEqual(result.coverage_summary.missing_count, 1)

    def test_binding_uses_event_and_ordinal_not_estimate_timestamp_or_value_identity(self) -> None:
        event = _event(1, available_time_ns=100)
        repeated = _output(estimate_time_ns=1, available_time_ns=100)
        summary = _summary(
            (
                _outcome("first", OutputStatus.VALID),
                _outcome("second", OutputStatus.VALID),
            )
        )

        result = bind_output_coverage(
            summary,
            batches=(EventOutputBatch(event, (repeated, repeated)),),
            slots=(_slot("first", event, 0), _slot("second", event, 1)),
        )

        self.assertEqual(result.observed_output_count, 2)
        self.assertNotEqual(event.measurement_time_ns, repeated.estimate_time_ns)

    def test_invalid_or_reset_trigger_event_is_retained_without_auto_classification(self) -> None:
        invalid_event = _event(1, valid=False)
        reset_event = _event(2, kind=EventKind.RESET)
        summary = _summary(
            (
                _outcome("valid-from-invalid-input", OutputStatus.VALID),
                _outcome("missing-at-reset", OutputStatus.MISSING),
            )
        )

        result = bind_output_coverage(
            summary,
            batches=(
                EventOutputBatch(invalid_event, (_output(),)),
                EventOutputBatch(reset_event, ()),
            ),
            slots=(
                _slot("valid-from-invalid-input", invalid_event, 0),
                _slot("missing-at-reset", reset_event, None),
            ),
        )

        self.assertFalse(result.batches[0].event.valid)
        self.assertEqual(result.batches[1].event.kind, EventKind.RESET)
        self.assertEqual(result.coverage_summary.valid_count, 1)

    def test_slots_must_exhaust_expected_ids_in_exact_order(self) -> None:
        event = _event(1)
        summary = _summary(
            (
                _outcome("first", OutputStatus.VALID),
                _outcome("second", OutputStatus.MISSING),
            )
        )
        batches = (EventOutputBatch(event, (_output(),)),)
        complete = (_slot("first", event, 0), _slot("second", event, None))

        for slots in (
            complete[:1],
            complete + (_slot("extra", event, None),),
            tuple(reversed(complete)),
        ):
            with self.subTest(slots=slots):
                with self.assertRaisesRegex(CoverageBindingError, "exactly and in order"):
                    bind_output_coverage(summary, batches=batches, slots=slots)

        with self.assertRaisesRegex(CoverageBindingError, "slots must be a tuple"):
            bind_output_coverage(summary, batches=batches, slots=list(complete))

    def test_unknown_event_wrong_sequence_and_out_of_range_ordinal_fail(self) -> None:
        event = _event(1)
        summary = _summary((_outcome("expected", OutputStatus.VALID),))
        batches = (EventOutputBatch(event, (_output(),)),)

        with self.assertRaisesRegex(CoverageBindingError, "unknown trigger_event_id"):
            bind_output_coverage(
                summary,
                batches=batches,
                slots=(OutputEnvelopeSlot("expected", "unknown", event.sequence_index, 0),),
            )
        with self.assertRaisesRegex(CoverageBindingError, "wrong event_sequence_index"):
            bind_output_coverage(
                summary,
                batches=batches,
                slots=(
                    OutputEnvelopeSlot("expected", event.event_id, event.sequence_index + 1, 0),
                ),
            )
        with self.assertRaisesRegex(CoverageBindingError, "does not identify"):
            bind_output_coverage(
                summary,
                batches=batches,
                slots=(_slot("expected", event, 1),),
            )

    def test_missing_and_produced_ordinal_rules_are_exact(self) -> None:
        event = _event(1)
        valid_summary = _summary((_outcome("expected", OutputStatus.VALID),))
        missing_summary = _summary((_outcome("expected", OutputStatus.MISSING),))

        with self.assertRaisesRegex(CoverageBindingError, "must declare"):
            bind_output_coverage(
                valid_summary,
                batches=(EventOutputBatch(event, (_output(),)),),
                slots=(_slot("expected", event, None),),
            )
        with self.assertRaisesRegex(CoverageBindingError, "missing outcome"):
            bind_output_coverage(
                missing_summary,
                batches=(EventOutputBatch(event, ()),),
                slots=(_slot("expected", event, 0),),
            )

    def test_status_mismatch_and_duplicate_binding_fail(self) -> None:
        event = _event(1)
        invalid_summary = _summary((_outcome("expected", OutputStatus.INVALID),))
        with self.assertRaisesRegex(CoverageBindingError, "status must match"):
            bind_output_coverage(
                invalid_summary,
                batches=(EventOutputBatch(event, (_output(valid=True),)),),
                slots=(_slot("expected", event, 0),),
            )

        duplicate_summary = _summary(
            (
                _outcome("first", OutputStatus.VALID),
                _outcome("second", OutputStatus.VALID),
            )
        )
        with self.assertRaisesRegex(CoverageBindingError, "must not be bound twice"):
            bind_output_coverage(
                duplicate_summary,
                batches=(EventOutputBatch(event, (_output(),)),),
                slots=(_slot("first", event, 0), _slot("second", event, 0)),
            )

    def test_every_observed_envelope_must_be_bound_and_zero_output_events_may_be_extra(
        self,
    ) -> None:
        event = _event(1)
        zero_output_event = _event(2)
        summary = _summary((_outcome("first", OutputStatus.VALID),))

        with self.assertRaisesRegex(CoverageBindingError, "every observed output"):
            bind_output_coverage(
                summary,
                batches=(EventOutputBatch(event, (_output(), _output())),),
                slots=(_slot("first", event, 0),),
            )

        result = bind_output_coverage(
            summary,
            batches=(
                EventOutputBatch(event, (_output(),)),
                EventOutputBatch(zero_output_event, ()),
            ),
            slots=(_slot("first", event, 0),),
        )
        self.assertEqual(len(result.batches), 2)

    def test_batch_collection_rejects_duplicates_mixed_clocks_and_reordering(self) -> None:
        event = _event(1)
        summary = _summary((_outcome("expected", OutputStatus.VALID),))
        slot = (_slot("expected", event, 0),)

        duplicate_id = _event(2, event_id=event.event_id)
        with self.assertRaisesRegex(CoverageBindingError, "duplicate event_id"):
            bind_output_coverage(
                summary,
                batches=(
                    EventOutputBatch(event, (_output(),)),
                    EventOutputBatch(duplicate_id, ()),
                ),
                slots=slot,
            )

        duplicate_index = _event(1, event_id="other-event")
        with self.assertRaisesRegex(CoverageBindingError, "duplicate sequence_index"):
            bind_output_coverage(
                summary,
                batches=(
                    EventOutputBatch(event, (_output(),)),
                    EventOutputBatch(duplicate_index, ()),
                ),
                slots=slot,
            )

        other_clock = _event(2, clock_id="other-clock")
        with self.assertRaisesRegex(CoverageBindingError, "uses clock"):
            bind_output_coverage(
                summary,
                batches=(
                    EventOutputBatch(event, (_output(),)),
                    EventOutputBatch(other_clock, ()),
                ),
                slots=slot,
            )

        later = _event(2, available_time_ns=20)
        with self.assertRaisesRegex(CoverageBindingError, "must be ordered"):
            bind_output_coverage(
                summary,
                batches=(
                    EventOutputBatch(later, ()),
                    EventOutputBatch(event, (_output(),)),
                ),
                slots=slot,
            )

    def test_batch_events_must_satisfy_same_stream_measurement_order(self) -> None:
        summary = _summary((_outcome("expected", OutputStatus.VALID),))
        first = _event(
            1,
            stream_id="same-stream",
            measurement_time_ns=20,
            available_time_ns=20,
        )
        slot = (_slot("expected", first, 0),)

        for measurement_time_ns in (20, 10):
            second = _event(
                2,
                stream_id="same-stream",
                measurement_time_ns=measurement_time_ns,
                available_time_ns=30,
            )
            with self.subTest(measurement_time_ns=measurement_time_ns):
                with self.assertRaisesRegex(CoverageBindingError, "must increase within stream"):
                    bind_output_coverage(
                        summary,
                        batches=(
                            EventOutputBatch(first, (_output(available_time_ns=20),)),
                            EventOutputBatch(second, ()),
                        ),
                        slots=slot,
                    )

    def test_result_rejects_wrong_types_identifiers_and_forged_counts(self) -> None:
        event = _event(1)
        summary = _summary((_outcome("expected", OutputStatus.VALID),))
        result = bind_output_coverage(
            summary,
            batches=(EventOutputBatch(event, (_output(),)),),
            slots=(_slot("expected", event, 0),),
        )

        for field, value, message in (
            ("binding_id", "other", "binding_id"),
            ("binding_id", _EqualitySpoof(), "binding_id"),
            ("coverage_summary", "summary", "OutputCoverageSummary"),
            ("observed_output_count", 2, "observed_output_count"),
            ("observed_output_count", True, "non-negative integer"),
            ("batches", [], "non-empty tuple"),
            ("slots", [], "slots must be a tuple"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(CoverageBindingError, message):
                    replace(result, **{field: value})

        self.assertFalse(hasattr(result, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            result.observed_output_count = 0  # type: ignore[misc]

    def test_wrong_top_level_inputs_fail_without_coercion(self) -> None:
        event = _event(1)
        summary = _summary((_outcome("expected", OutputStatus.VALID),))
        batch = EventOutputBatch(event, (_output(),))
        slot = _slot("expected", event, 0)

        with self.assertRaisesRegex(CoverageBindingError, "OutputCoverageSummary"):
            bind_output_coverage("summary", batches=(batch,), slots=(slot,))  # type: ignore[arg-type]
        with self.assertRaisesRegex(CoverageBindingError, "batches must be a non-empty tuple"):
            bind_output_coverage(summary, batches=[], slots=(slot,))
        with self.assertRaisesRegex(CoverageBindingError, "EventOutputBatch"):
            bind_output_coverage(summary, batches=("batch",), slots=(slot,))
        with self.assertRaisesRegex(CoverageBindingError, "OutputEnvelopeSlot"):
            bind_output_coverage(summary, batches=(batch,), slots=("slot",))


if __name__ == "__main__":
    unittest.main()

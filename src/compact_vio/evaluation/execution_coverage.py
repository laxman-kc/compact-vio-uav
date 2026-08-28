"""Bind explicit output coverage to one terminal recorder snapshot.

This module joins caller-declared coverage outcomes to recorder-observed output
envelopes without deriving an output schedule, a failure classification, or a
run-success decision. Missing opportunities may name any event in the retained
plan, including the failed event and the unattempted suffix of a failed run.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from compact_vio.evaluation.coverage import (
    OutputCoverageSummary,
    OutputStatus,
    summarize_output_coverage,
)
from compact_vio.evaluation.coverage_binding import OutputEnvelopeSlot

if TYPE_CHECKING:
    from compact_vio.execution import RecorderSnapshot


RECORDED_OUTPUT_COVERAGE_BINDING_ID = (
    "output-coverage-binding/terminal-recorder-plan-event-output-ordinal/v1"
)


class ExecutionCoverageBindingError(ValueError):
    """Raised when terminal execution cannot support the declared coverage."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise ExecutionCoverageBindingError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if type(value) is not int or value < 0:
        raise ExecutionCoverageBindingError(f"{field} must be a non-negative integer")


def _validate_terminal_snapshot(snapshot: object) -> RecorderSnapshot:
    # Import locally because execution.py imports the lower-level coverage
    # envelope. Importing execution at module load time would create a cycle
    # while compact_vio.evaluation initializes.
    from compact_vio.execution import (
        RecorderSnapshot,
        RecorderState,
    )

    if type(snapshot) is not RecorderSnapshot:
        raise ExecutionCoverageBindingError("snapshot must be a RecorderSnapshot")
    try:
        replace(snapshot)
        for batch in snapshot.batches:
            replace(batch)
    except Exception as error:
        raise ExecutionCoverageBindingError(
            f"snapshot violates RecorderSnapshot: {error}"
        ) from error
    if snapshot.state is RecorderState.ACTIVE:
        raise ExecutionCoverageBindingError("snapshot must be terminal, not ACTIVE")
    return snapshot


def _validate_and_count(
    snapshot: object,
    coverage_summary: OutputCoverageSummary,
    slots: tuple[OutputEnvelopeSlot, ...],
) -> int:
    terminal_snapshot = _validate_terminal_snapshot(snapshot)

    if type(coverage_summary) is not OutputCoverageSummary:
        raise ExecutionCoverageBindingError("coverage_summary must be an OutputCoverageSummary")
    try:
        replace(coverage_summary)
        expected_summary = summarize_output_coverage(coverage_summary.ledger)
    except Exception as error:
        raise ExecutionCoverageBindingError(
            f"coverage_summary has an invalid retained ledger: {error}"
        ) from error
    if expected_summary != coverage_summary:
        raise ExecutionCoverageBindingError("coverage_summary must match its retained ledger")

    if type(slots) is not tuple:
        raise ExecutionCoverageBindingError("slots must be an exact tuple")
    if not all(type(slot) is OutputEnvelopeSlot for slot in slots):
        raise ExecutionCoverageBindingError("slots must contain only OutputEnvelopeSlot values")
    try:
        for slot in slots:
            replace(slot)
    except Exception as error:
        raise ExecutionCoverageBindingError(
            f"slots contain an invalid OutputEnvelopeSlot: {error}"
        ) from error

    expected_ids = coverage_summary.ledger.expected_opportunity_ids
    slot_ids = tuple(slot.opportunity_id for slot in slots)
    if slot_ids != expected_ids:
        raise ExecutionCoverageBindingError(
            "slots must match every expected opportunity exactly and in order"
        )

    planned_by_event_id = {event.event_id: event for event in terminal_snapshot.planned_events}
    batches_by_event_id = {batch.event.event_id: batch for batch in terminal_snapshot.batches}
    observed_targets = {
        (batch.event.event_id, output_ordinal)
        for batch in terminal_snapshot.batches
        for output_ordinal in range(len(batch.outputs))
    }
    bound_targets: set[tuple[str, int]] = set()

    for outcome, slot in zip(
        coverage_summary.ledger.outcomes,
        slots,
        strict=True,
    ):
        planned_event = planned_by_event_id.get(slot.trigger_event_id)
        if planned_event is None:
            raise ExecutionCoverageBindingError(
                f"slot {slot.opportunity_id!r} references an unknown planned event"
            )
        if planned_event.sequence_index != slot.event_sequence_index:
            raise ExecutionCoverageBindingError(
                f"slot {slot.opportunity_id!r} has the wrong event_sequence_index"
            )

        if outcome.output_status is OutputStatus.MISSING:
            if slot.output_ordinal is not None:
                raise ExecutionCoverageBindingError("missing outcome must use output_ordinal=None")
            continue

        if slot.output_ordinal is None:
            raise ExecutionCoverageBindingError("produced outcome must declare an output_ordinal")
        batch = batches_by_event_id.get(slot.trigger_event_id)
        if batch is None:
            raise ExecutionCoverageBindingError(
                "produced outcome must reference a successfully recorded batch event"
            )
        target = (slot.trigger_event_id, slot.output_ordinal)
        if target in bound_targets:
            raise ExecutionCoverageBindingError(
                "an observed output envelope must not be bound twice"
            )
        if target not in observed_targets:
            raise ExecutionCoverageBindingError(
                "output_ordinal does not identify a recorded output envelope"
            )
        output = batch.outputs[slot.output_ordinal]
        expected_status = OutputStatus.VALID if output.valid else OutputStatus.INVALID
        if outcome.output_status is not expected_status:
            raise ExecutionCoverageBindingError(
                "coverage outcome status must match the recorded output envelope"
            )
        bound_targets.add(target)

    if bound_targets != observed_targets:
        raise ExecutionCoverageBindingError(
            "every recorded output envelope must be bound to exactly one opportunity"
        )
    return len(observed_targets)


@dataclass(frozen=True, slots=True)
class RecordedOutputCoverage:
    """Explicit coverage bound to the complete plan of one terminal execution."""

    binding_id: str
    snapshot: RecorderSnapshot
    coverage_summary: OutputCoverageSummary
    slots: tuple[OutputEnvelopeSlot, ...]
    observed_output_count: int

    def __post_init__(self) -> None:
        _require_non_empty_text(self.binding_id, field="binding_id")
        if self.binding_id != RECORDED_OUTPUT_COVERAGE_BINDING_ID:
            raise ExecutionCoverageBindingError(
                f"binding_id must equal {RECORDED_OUTPUT_COVERAGE_BINDING_ID!r}"
            )
        _require_non_negative_integer(
            self.observed_output_count,
            field="observed_output_count",
        )
        actual_count = _validate_and_count(
            self.snapshot,
            self.coverage_summary,
            self.slots,
        )
        if self.observed_output_count != actual_count:
            raise ExecutionCoverageBindingError(
                "observed_output_count must match the retained recorder snapshot"
            )


def bind_recorded_output_coverage(
    coverage_summary: OutputCoverageSummary,
    *,
    snapshot: RecorderSnapshot,
    slots: tuple[OutputEnvelopeSlot, ...],
) -> RecordedOutputCoverage:
    """Bind declared outcomes to one terminal execution without inferring them."""

    observed_output_count = _validate_and_count(snapshot, coverage_summary, slots)
    return RecordedOutputCoverage(
        binding_id=RECORDED_OUTPUT_COVERAGE_BINDING_ID,
        snapshot=snapshot,
        coverage_summary=coverage_summary,
        slots=slots,
        observed_output_count=observed_output_count,
    )


__all__ = [
    "ExecutionCoverageBindingError",
    "RECORDED_OUTPUT_COVERAGE_BINDING_ID",
    "RecordedOutputCoverage",
    "bind_recorded_output_coverage",
]

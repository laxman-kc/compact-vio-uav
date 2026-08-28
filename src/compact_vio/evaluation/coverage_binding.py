"""Exact binding between coverage outcomes and replay-triggered output tuples.

This module never derives an output schedule or associates by timestamp. The
caller retains each triggering replay event and the estimator output tuple in
its original order, then binds every declared opportunity explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from compact_vio.estimator import EstimatorOutput
from compact_vio.evaluation.coverage import (
    OutputCoverageSummary,
    OutputStatus,
    summarize_output_coverage,
)
from compact_vio.replay import CausalReplay, ReplayContractError, ReplayEvent

EXACT_OUTPUT_COVERAGE_BINDING_ID = "output-coverage-binding/event-output-ordinal/v1"


class CoverageBindingError(ValueError):
    """Raised when replay/output evidence does not exactly support a coverage ledger."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise CoverageBindingError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if type(value) is not int or value < 0:
        raise CoverageBindingError(f"{field} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class EventOutputBatch:
    """One replay event and the exact ordered tuple returned for that event.

    The observable clock and availability checks are repeated here so a forged
    batch cannot contradict the causal envelope. This does not prove that the
    caller actually obtained the tuple from ``EstimatorSession.ingest``.
    """

    event: ReplayEvent[object]
    outputs: tuple[EstimatorOutput[object], ...]

    def __post_init__(self) -> None:
        if type(self.event) is not ReplayEvent:
            raise CoverageBindingError("event must be a ReplayEvent")
        try:
            replace(self.event)
        except Exception as error:
            raise CoverageBindingError(f"event violates ReplayEvent: {error}") from error
        if type(self.outputs) is not tuple:
            raise CoverageBindingError("outputs must be an exact tuple")
        for output in self.outputs:
            if type(output) is not EstimatorOutput:
                raise CoverageBindingError("outputs must contain only EstimatorOutput values")
            try:
                replace(output)
            except Exception as error:
                raise CoverageBindingError(f"output violates EstimatorOutput: {error}") from error
            if output.clock_id != self.event.clock_id:
                raise CoverageBindingError("output clock_id must match its triggering event")
            if output.available_time_ns < self.event.available_time_ns:
                raise CoverageBindingError("output cannot be available before its triggering event")


@dataclass(frozen=True, slots=True)
class OutputEnvelopeSlot:
    """Explicit binding for one expected opportunity.

    ``output_ordinal`` is the exact zero-based tuple position for a produced
    valid or invalid output. It is ``None`` only when the retained outcome is
    explicitly missing.
    """

    opportunity_id: str
    trigger_event_id: str
    event_sequence_index: int
    output_ordinal: int | None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.opportunity_id, field="opportunity_id")
        _require_non_empty_text(self.trigger_event_id, field="trigger_event_id")
        _require_non_negative_integer(
            self.event_sequence_index,
            field="event_sequence_index",
        )
        if self.output_ordinal is not None:
            _require_non_negative_integer(self.output_ordinal, field="output_ordinal")


def _validate_and_count(
    summary: OutputCoverageSummary,
    batches: tuple[EventOutputBatch, ...],
    slots: tuple[OutputEnvelopeSlot, ...],
) -> int:
    if type(summary) is not OutputCoverageSummary:
        raise CoverageBindingError("coverage_summary must be an OutputCoverageSummary")
    try:
        replace(summary)
        replace(summary.ledger)
        for outcome in summary.ledger.outcomes:
            replace(outcome)
        for reason_count in summary.reason_counts:
            replace(reason_count)
    except Exception as error:
        raise CoverageBindingError(
            f"coverage_summary violates its retained records: {error}"
        ) from error
    if summarize_output_coverage(summary.ledger) != summary:
        raise CoverageBindingError("coverage_summary must match its retained ledger")
    if type(batches) is not tuple or not batches:
        raise CoverageBindingError("batches must be a non-empty tuple")
    if not all(type(batch) is EventOutputBatch for batch in batches):
        raise CoverageBindingError("batches must contain only EventOutputBatch values")
    if type(slots) is not tuple:
        raise CoverageBindingError("slots must be a tuple")
    if not all(type(slot) is OutputEnvelopeSlot for slot in slots):
        raise CoverageBindingError("slots must contain only OutputEnvelopeSlot values")
    try:
        for batch in batches:
            replace(batch)
        for slot in slots:
            replace(slot)
    except Exception as error:
        raise CoverageBindingError(
            f"binding evidence violates its retained record contract: {error}"
        ) from error

    expected_ids = summary.ledger.expected_opportunity_ids
    slot_ids = tuple(slot.opportunity_id for slot in slots)
    if slot_ids != expected_ids:
        raise CoverageBindingError(
            "slots must match every expected opportunity exactly and in order"
        )

    events = tuple(batch.event for batch in batches)
    try:
        CausalReplay(events, clock_id=events[0].clock_id)
    except ReplayContractError as error:
        raise CoverageBindingError(f"batch events violate CausalReplay: {error}") from error
    batches_by_event_id = {batch.event.event_id: batch for batch in batches}

    observed_targets = {
        (batch.event.event_id, output_ordinal)
        for batch in batches
        for output_ordinal in range(len(batch.outputs))
    }
    bound_targets: set[tuple[str, int]] = set()
    for outcome, slot in zip(summary.ledger.outcomes, slots, strict=True):
        batch = batches_by_event_id.get(slot.trigger_event_id)
        if batch is None:
            raise CoverageBindingError(
                f"slot {slot.opportunity_id!r} references an unknown trigger_event_id"
            )
        if batch.event.sequence_index != slot.event_sequence_index:
            raise CoverageBindingError(
                f"slot {slot.opportunity_id!r} has the wrong event_sequence_index"
            )

        if outcome.output_status is OutputStatus.MISSING:
            if slot.output_ordinal is not None:
                raise CoverageBindingError("missing outcome must use output_ordinal=None")
            continue

        if slot.output_ordinal is None:
            raise CoverageBindingError("produced outcome must declare an output_ordinal")
        target = (slot.trigger_event_id, slot.output_ordinal)
        if target in bound_targets:
            raise CoverageBindingError("an observed output envelope must not be bound twice")
        if target not in observed_targets:
            raise CoverageBindingError("output_ordinal does not identify an observed envelope")
        output = batch.outputs[slot.output_ordinal]
        expected_status = OutputStatus.VALID if output.valid else OutputStatus.INVALID
        if outcome.output_status is not expected_status:
            raise CoverageBindingError(
                "coverage outcome status must match the bound output envelope"
            )
        bound_targets.add(target)

    if bound_targets != observed_targets:
        raise CoverageBindingError(
            "every observed output envelope must be bound to exactly one opportunity"
        )
    return len(observed_targets)


@dataclass(frozen=True, slots=True)
class BoundOutputCoverage:
    """Coverage summary plus the complete exact event/output binding evidence."""

    binding_id: str
    coverage_summary: OutputCoverageSummary
    batches: tuple[EventOutputBatch, ...]
    slots: tuple[OutputEnvelopeSlot, ...]
    observed_output_count: int

    def __post_init__(self) -> None:
        _require_non_empty_text(self.binding_id, field="binding_id")
        if self.binding_id != EXACT_OUTPUT_COVERAGE_BINDING_ID:
            raise CoverageBindingError(
                f"binding_id must equal {EXACT_OUTPUT_COVERAGE_BINDING_ID!r}"
            )
        _require_non_negative_integer(
            self.observed_output_count,
            field="observed_output_count",
        )
        actual_count = _validate_and_count(
            self.coverage_summary,
            self.batches,
            self.slots,
        )
        if self.observed_output_count != actual_count:
            raise CoverageBindingError(
                "observed_output_count must match the retained event/output batches"
            )


def bind_output_coverage(
    coverage_summary: OutputCoverageSummary,
    *,
    batches: tuple[EventOutputBatch, ...],
    slots: tuple[OutputEnvelopeSlot, ...],
) -> BoundOutputCoverage:
    """Bind every declared outcome and observed envelope exactly once."""

    observed_output_count = _validate_and_count(coverage_summary, batches, slots)
    return BoundOutputCoverage(
        binding_id=EXACT_OUTPUT_COVERAGE_BINDING_ID,
        coverage_summary=coverage_summary,
        batches=batches,
        slots=slots,
        observed_output_count=observed_output_count,
    )


__all__ = [
    "BoundOutputCoverage",
    "CoverageBindingError",
    "EXACT_OUTPUT_COVERAGE_BINDING_ID",
    "EventOutputBatch",
    "OutputEnvelopeSlot",
    "bind_output_coverage",
]

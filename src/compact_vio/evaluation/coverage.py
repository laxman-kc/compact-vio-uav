"""Explicit output-coverage accounting without an inferred output schedule.

The caller declares every expected opportunity and classifies its outcome under
named external policies. This module counts those declarations; it does not
associate timestamps, infer failures, or decide whether a run passed.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

EXPLICIT_OUTPUT_COVERAGE_ID = "output-coverage/explicit-opportunities/v1"


class CoverageContractError(ValueError):
    """Raised when a coverage ledger or summary is incomplete or inconsistent."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CoverageContractError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CoverageContractError(f"{field} must be a non-negative integer")


class OutputStatus(Enum):
    """Observed output state for one caller-declared expected opportunity."""

    MISSING = "missing"
    INVALID = "invalid"
    VALID = "valid"


@dataclass(frozen=True, slots=True)
class OutputCoverageOutcome:
    """The explicitly classified outcome for one expected opportunity."""

    opportunity_id: str
    output_status: OutputStatus
    reference_available: bool
    usable: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_empty_text(self.opportunity_id, field="opportunity_id")
        if not isinstance(self.output_status, OutputStatus):
            raise CoverageContractError("output_status must be an OutputStatus")
        if not isinstance(self.reference_available, bool):
            raise CoverageContractError("reference_available must be boolean")
        if not isinstance(self.usable, bool):
            raise CoverageContractError("usable must be boolean")
        if not isinstance(self.reason_codes, tuple):
            raise CoverageContractError("reason_codes must be a tuple")
        for reason_code in self.reason_codes:
            _require_non_empty_text(reason_code, field="reason_codes")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise CoverageContractError("reason_codes must not contain duplicates")

        if self.usable:
            if self.output_status is not OutputStatus.VALID:
                raise CoverageContractError("usable opportunity must have a valid output")
            if not self.reference_available:
                raise CoverageContractError("usable opportunity must have an available reference")
            if self.reason_codes:
                raise CoverageContractError("usable opportunity must not have reason_codes")
        elif not self.reason_codes:
            raise CoverageContractError(
                "non-usable opportunity must declare at least one reason_code"
            )


@dataclass(frozen=True, slots=True)
class OutputCoverageLedger:
    """A nonempty declared denominator and its exact one-for-one outcomes."""

    ledger_id: str
    sequence_id: str
    segment_id: str
    opportunity_definition_id: str
    outcome_classification_policy_id: str
    reason_schema_id: str
    expected_opportunity_ids: tuple[str, ...]
    outcomes: tuple[OutputCoverageOutcome, ...]

    def __post_init__(self) -> None:
        for field in (
            "ledger_id",
            "sequence_id",
            "segment_id",
            "opportunity_definition_id",
            "outcome_classification_policy_id",
            "reason_schema_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)
        if (
            not isinstance(self.expected_opportunity_ids, tuple)
            or not self.expected_opportunity_ids
        ):
            raise CoverageContractError("expected_opportunity_ids must be a non-empty tuple")
        for opportunity_id in self.expected_opportunity_ids:
            _require_non_empty_text(opportunity_id, field="expected_opportunity_ids")
        if len(self.expected_opportunity_ids) != len(set(self.expected_opportunity_ids)):
            raise CoverageContractError("expected_opportunity_ids must not contain duplicates")
        if not isinstance(self.outcomes, tuple):
            raise CoverageContractError("outcomes must be a tuple")
        if not all(isinstance(outcome, OutputCoverageOutcome) for outcome in self.outcomes):
            raise CoverageContractError("outcomes must contain only OutputCoverageOutcome values")
        outcome_ids = tuple(outcome.opportunity_id for outcome in self.outcomes)
        if outcome_ids != self.expected_opportunity_ids:
            raise CoverageContractError(
                "outcomes must match every expected_opportunity_id exactly and in order"
            )


@dataclass(frozen=True, slots=True)
class ReasonCount:
    """Number of opportunities carrying one caller-defined reason code."""

    reason_code: str
    count: int

    def __post_init__(self) -> None:
        _require_non_empty_text(self.reason_code, field="reason_code")
        _require_non_negative_integer(self.count, field="count")
        if self.count == 0:
            raise CoverageContractError("count must be positive")


def _aggregate(
    ledger: OutputCoverageLedger,
) -> tuple[int, int, int, int, int, int, tuple[ReasonCount, ...]]:
    missing_count = sum(item.output_status is OutputStatus.MISSING for item in ledger.outcomes)
    invalid_count = sum(item.output_status is OutputStatus.INVALID for item in ledger.outcomes)
    valid_count = sum(item.output_status is OutputStatus.VALID for item in ledger.outcomes)
    reference_available_count = sum(item.reference_available for item in ledger.outcomes)
    usable_count = sum(item.usable for item in ledger.outcomes)
    reason_counter = Counter(
        reason_code for item in ledger.outcomes for reason_code in item.reason_codes
    )
    reason_counts = tuple(
        ReasonCount(reason_code=reason_code, count=reason_counter[reason_code])
        for reason_code in sorted(reason_counter)
    )
    return (
        missing_count,
        invalid_count,
        valid_count,
        reference_available_count,
        len(ledger.expected_opportunity_ids) - reference_available_count,
        usable_count,
        reason_counts,
    )


@dataclass(frozen=True, slots=True)
class OutputCoverageSummary:
    """Exact partitions derived from one retained explicit-opportunity ledger."""

    summary_id: str
    ledger: OutputCoverageLedger
    expected_count: int
    missing_count: int
    invalid_count: int
    valid_count: int
    reference_available_count: int
    reference_unavailable_count: int
    usable_count: int
    non_usable_count: int
    reason_counts: tuple[ReasonCount, ...]

    def __post_init__(self) -> None:
        _require_non_empty_text(self.summary_id, field="summary_id")
        if self.summary_id != EXPLICIT_OUTPUT_COVERAGE_ID:
            raise CoverageContractError(f"summary_id must equal {EXPLICIT_OUTPUT_COVERAGE_ID!r}")
        if not isinstance(self.ledger, OutputCoverageLedger):
            raise CoverageContractError("ledger must be an OutputCoverageLedger")
        for field in (
            "expected_count",
            "missing_count",
            "invalid_count",
            "valid_count",
            "reference_available_count",
            "reference_unavailable_count",
            "usable_count",
            "non_usable_count",
        ):
            _require_non_negative_integer(getattr(self, field), field=field)
        if not isinstance(self.reason_counts, tuple) or not all(
            isinstance(reason_count, ReasonCount) for reason_count in self.reason_counts
        ):
            raise CoverageContractError("reason_counts must contain only ReasonCount values")

        expected = _aggregate(self.ledger)
        actual = (
            self.missing_count,
            self.invalid_count,
            self.valid_count,
            self.reference_available_count,
            self.reference_unavailable_count,
            self.usable_count,
            self.reason_counts,
        )
        if self.expected_count != len(self.ledger.expected_opportunity_ids):
            raise CoverageContractError("expected_count must match the retained ledger")
        if actual != expected:
            raise CoverageContractError("summary partitions must match the retained ledger")
        if self.non_usable_count != self.expected_count - self.usable_count:
            raise CoverageContractError("non_usable_count must equal expected_count - usable_count")

    @property
    def produced_count(self) -> int:
        """Count of valid or invalid outputs; missing opportunities are excluded."""

        return self.valid_count + self.invalid_count

    @property
    def produced_fraction(self) -> float:
        """Produced outputs divided by all explicitly expected opportunities."""

        return self.produced_count / self.expected_count

    @property
    def valid_fraction(self) -> float:
        """Valid outputs divided by all explicitly expected opportunities."""

        return self.valid_count / self.expected_count

    @property
    def usable_fraction(self) -> float:
        """Explicitly usable items divided by all expected opportunities."""

        return self.usable_count / self.expected_count


def summarize_output_coverage(ledger: OutputCoverageLedger) -> OutputCoverageSummary:
    """Count one retained explicit-opportunity ledger without inferring semantics."""

    if not isinstance(ledger, OutputCoverageLedger):
        raise CoverageContractError("ledger must be an OutputCoverageLedger")
    (
        missing_count,
        invalid_count,
        valid_count,
        reference_available_count,
        reference_unavailable_count,
        usable_count,
        reason_counts,
    ) = _aggregate(ledger)
    expected_count = len(ledger.expected_opportunity_ids)
    return OutputCoverageSummary(
        summary_id=EXPLICIT_OUTPUT_COVERAGE_ID,
        ledger=ledger,
        expected_count=expected_count,
        missing_count=missing_count,
        invalid_count=invalid_count,
        valid_count=valid_count,
        reference_available_count=reference_available_count,
        reference_unavailable_count=reference_unavailable_count,
        usable_count=usable_count,
        non_usable_count=expected_count - usable_count,
        reason_counts=reason_counts,
    )


__all__ = [
    "CoverageContractError",
    "EXPLICIT_OUTPUT_COVERAGE_ID",
    "OutputCoverageLedger",
    "OutputCoverageOutcome",
    "OutputCoverageSummary",
    "OutputStatus",
    "ReasonCount",
    "summarize_output_coverage",
]

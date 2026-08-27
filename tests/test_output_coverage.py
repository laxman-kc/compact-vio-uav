from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from compact_vio.evaluation import (
    EXPLICIT_OUTPUT_COVERAGE_ID,
    CoverageContractError,
    OutputCoverageLedger,
    OutputCoverageOutcome,
    OutputStatus,
    ReasonCount,
    summarize_output_coverage,
)


class _EqualitySpoof:
    def __eq__(self, other: object) -> bool:
        return True


def _opportunity(
    opportunity_id: str,
    *,
    output_status: OutputStatus = OutputStatus.VALID,
    reference_available: bool = True,
    usable: bool = True,
    reason_codes: tuple[str, ...] = (),
) -> OutputCoverageOutcome:
    return OutputCoverageOutcome(
        opportunity_id=opportunity_id,
        output_status=output_status,
        reference_available=reference_available,
        usable=usable,
        reason_codes=reason_codes,
    )


def _ledger(
    outcomes: tuple[OutputCoverageOutcome, ...],
    *,
    expected_opportunity_ids: tuple[str, ...] | None = None,
) -> OutputCoverageLedger:
    if expected_opportunity_ids is None:
        expected_opportunity_ids = tuple(outcome.opportunity_id for outcome in outcomes)
    return OutputCoverageLedger(
        ledger_id="synthetic-coverage-ledger-v1",
        sequence_id="synthetic-sequence",
        segment_id="synthetic-segment",
        opportunity_definition_id="synthetic-expected-output-opportunities-v1",
        outcome_classification_policy_id="synthetic-outcome-policy-v1",
        reason_schema_id="synthetic-non-usable-reasons-v1",
        expected_opportunity_ids=expected_opportunity_ids,
        outcomes=outcomes,
    )


class OutputCoverageOutcomeTests(unittest.TestCase):
    def test_usable_requires_valid_output_reference_and_no_reasons(self) -> None:
        for changed, message in (
            ({"output_status": OutputStatus.MISSING}, "valid output"),
            ({"output_status": OutputStatus.INVALID}, "valid output"),
            ({"reference_available": False}, "available reference"),
            ({"reason_codes": ("unexpected-reason",)}, "must not have"),
        ):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(CoverageContractError, message):
                    replace(_opportunity("expected-0"), **changed)

    def test_every_non_usable_opportunity_requires_declared_reasons(self) -> None:
        with self.assertRaisesRegex(CoverageContractError, "at least one reason_code"):
            _opportunity("expected-0", usable=False)

        excluded = _opportunity(
            "expected-0",
            usable=False,
            reason_codes=("declared-policy-exclusion",),
        )
        self.assertEqual(excluded.output_status, OutputStatus.VALID)
        self.assertTrue(excluded.reference_available)

    def test_status_booleans_and_reason_tuple_are_strict(self) -> None:
        base = _opportunity("expected-0")
        for field, value, message in (
            ("output_status", "valid", "OutputStatus"),
            ("reference_available", 1, "boolean"),
            ("usable", 1, "boolean"),
            ("reason_codes", [], "tuple"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(CoverageContractError, message):
                    replace(base, **{field: value})

    def test_reason_codes_are_nonblank_and_unique(self) -> None:
        for reason_codes, message in (
            ((" ",), "reason_codes"),
            (("same", "same"), "duplicates"),
        ):
            with self.subTest(reason_codes=reason_codes):
                with self.assertRaisesRegex(CoverageContractError, message):
                    _opportunity(
                        "expected-0",
                        usable=False,
                        reason_codes=reason_codes,
                    )


class OutputCoverageLedgerTests(unittest.TestCase):
    def test_ledger_requires_explicit_identity_policy_and_reason_schema(self) -> None:
        base = _ledger((_opportunity("expected-0"),))
        for field in (
            "ledger_id",
            "sequence_id",
            "segment_id",
            "opportunity_definition_id",
            "outcome_classification_policy_id",
            "reason_schema_id",
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(CoverageContractError, field):
                    replace(base, **{field: " "})

    def test_zero_expected_opportunities_is_undefined_and_rejected(self) -> None:
        with self.assertRaisesRegex(CoverageContractError, "expected_opportunity_ids"):
            _ledger(())
        with self.assertRaisesRegex(CoverageContractError, "expected_opportunity_ids"):
            replace(
                _ledger((_opportunity("expected-0"),)),
                expected_opportunity_ids=[],
            )

    def test_ids_are_unique_but_caller_order_is_not_inferred_or_sorted(self) -> None:
        ordered = _ledger(
            (
                _opportunity("z-last-lexically"),
                _opportunity("a-first-lexically"),
            )
        )
        self.assertEqual(
            ordered.expected_opportunity_ids,
            ("z-last-lexically", "a-first-lexically"),
        )

        with self.assertRaisesRegex(CoverageContractError, "duplicates"):
            _ledger(
                (_opportunity("same"), _opportunity("same")),
                expected_opportunity_ids=("same", "same"),
            )

    def test_outcomes_must_exhaust_the_independent_denominator_in_order(self) -> None:
        complete = (_opportunity("expected-0"), _opportunity("expected-1"))
        expected_ids = ("expected-0", "expected-1")

        with self.assertRaisesRegex(CoverageContractError, "every expected_opportunity_id"):
            _ledger(complete[:1], expected_opportunity_ids=expected_ids)
        with self.assertRaisesRegex(CoverageContractError, "every expected_opportunity_id"):
            _ledger(
                complete + (_opportunity("unexpected"),),
                expected_opportunity_ids=expected_ids,
            )
        with self.assertRaisesRegex(CoverageContractError, "every expected_opportunity_id"):
            _ledger(tuple(reversed(complete)), expected_opportunity_ids=expected_ids)

        base = _ledger(complete, expected_opportunity_ids=expected_ids)
        with self.assertRaisesRegex(CoverageContractError, "outcomes must be a tuple"):
            replace(base, outcomes=list(complete))

    def test_ledger_is_frozen_and_slotted(self) -> None:
        ledger = _ledger((_opportunity("expected-0"),))
        self.assertFalse(hasattr(ledger, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            ledger.sequence_id = "changed"  # type: ignore[misc]


class OutputCoverageSummaryTests(unittest.TestCase):
    def test_summary_retains_every_partition_and_reason(self) -> None:
        ledger = _ledger(
            (
                _opportunity("usable"),
                _opportunity(
                    "missing-with-reference",
                    output_status=OutputStatus.MISSING,
                    usable=False,
                    reason_codes=("missing-output",),
                ),
                _opportunity(
                    "invalid-with-reference",
                    output_status=OutputStatus.INVALID,
                    usable=False,
                    reason_codes=("invalid-output",),
                ),
                _opportunity(
                    "valid-without-reference",
                    reference_available=False,
                    usable=False,
                    reason_codes=("reference-unavailable",),
                ),
                _opportunity(
                    "explicit-exclusion",
                    usable=False,
                    reason_codes=("declared-policy-exclusion",),
                ),
                _opportunity(
                    "missing-without-reference",
                    output_status=OutputStatus.MISSING,
                    reference_available=False,
                    usable=False,
                    reason_codes=("missing-output", "reference-unavailable"),
                ),
            )
        )

        result = summarize_output_coverage(ledger)

        self.assertEqual(result.summary_id, EXPLICIT_OUTPUT_COVERAGE_ID)
        self.assertIs(result.ledger, ledger)
        self.assertEqual(result.expected_count, 6)
        self.assertEqual(result.missing_count, 2)
        self.assertEqual(result.invalid_count, 1)
        self.assertEqual(result.valid_count, 3)
        self.assertEqual(result.produced_count, 4)
        self.assertEqual(result.reference_available_count, 4)
        self.assertEqual(result.reference_unavailable_count, 2)
        self.assertEqual(result.usable_count, 1)
        self.assertEqual(result.non_usable_count, 5)
        self.assertAlmostEqual(result.produced_fraction, 4 / 6)
        self.assertAlmostEqual(result.valid_fraction, 3 / 6)
        self.assertAlmostEqual(result.usable_fraction, 1 / 6)
        self.assertEqual(
            result.reason_counts,
            (
                ReasonCount("declared-policy-exclusion", 1),
                ReasonCount("invalid-output", 1),
                ReasonCount("missing-output", 2),
                ReasonCount("reference-unavailable", 2),
            ),
        )
        self.assertGreater(
            sum(item.count for item in result.reason_counts),
            result.non_usable_count,
        )

    def test_all_unusable_and_all_usable_ledgers_remain_visible(self) -> None:
        all_missing = summarize_output_coverage(
            _ledger(
                (
                    _opportunity(
                        "expected-0",
                        output_status=OutputStatus.MISSING,
                        usable=False,
                        reason_codes=("missing-output",),
                    ),
                    _opportunity(
                        "expected-1",
                        output_status=OutputStatus.MISSING,
                        usable=False,
                        reason_codes=("missing-output",),
                    ),
                )
            )
        )
        self.assertEqual(all_missing.produced_fraction, 0.0)
        self.assertEqual(all_missing.usable_fraction, 0.0)
        self.assertEqual(all_missing.missing_count, 2)

        all_usable = summarize_output_coverage(
            _ledger((_opportunity("expected-0"), _opportunity("expected-1")))
        )
        self.assertEqual(all_usable.produced_fraction, 1.0)
        self.assertEqual(all_usable.valid_fraction, 1.0)
        self.assertEqual(all_usable.usable_fraction, 1.0)

    def test_equal_usable_fraction_does_not_collapse_distinct_causes(self) -> None:
        missing = summarize_output_coverage(
            _ledger(
                (
                    _opportunity(
                        "expected-0",
                        output_status=OutputStatus.MISSING,
                        usable=False,
                        reason_codes=("missing-output",),
                    ),
                )
            )
        )
        no_reference = summarize_output_coverage(
            _ledger(
                (
                    _opportunity(
                        "expected-0",
                        reference_available=False,
                        usable=False,
                        reason_codes=("reference-unavailable",),
                    ),
                )
            )
        )

        self.assertEqual(missing.usable_fraction, no_reference.usable_fraction)
        self.assertNotEqual(missing.missing_count, no_reference.missing_count)
        self.assertNotEqual(missing.valid_count, no_reference.valid_count)
        self.assertNotEqual(missing.reason_counts, no_reference.reason_counts)

    def test_summary_rejects_wrong_input_and_forged_public_values(self) -> None:
        with self.assertRaisesRegex(CoverageContractError, "OutputCoverageLedger"):
            summarize_output_coverage("ledger")  # type: ignore[arg-type]

        valid = summarize_output_coverage(_ledger((_opportunity("expected-0"),)))
        for field, value, message in (
            ("summary_id", "generic-completion", "summary_id"),
            ("summary_id", _EqualitySpoof(), "summary_id"),
            ("expected_count", 2, "expected_count"),
            ("missing_count", 1, "partitions"),
            ("non_usable_count", 1, "non_usable_count"),
            ("reason_counts", (ReasonCount("forged", 1),), "partitions"),
            ("usable_count", True, "usable_count"),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(CoverageContractError, message):
                    replace(valid, **{field: value})

    def test_summary_is_coverage_evidence_not_position_accuracy(self) -> None:
        result = summarize_output_coverage(_ledger((_opportunity("expected-0"),)))

        self.assertEqual(result.usable_count, 1)
        self.assertFalse(hasattr(result, "position"))
        self.assertFalse(hasattr(result, "translation_error"))


if __name__ == "__main__":
    unittest.main()

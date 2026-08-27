"""Framework-neutral evaluation primitives."""

from compact_vio.evaluation.coverage import (
    EXPLICIT_OUTPUT_COVERAGE_ID,
    CoverageContractError,
    OutputCoverageLedger,
    OutputCoverageOutcome,
    OutputCoverageSummary,
    OutputStatus,
    ReasonCount,
    summarize_output_coverage,
)
from compact_vio.evaluation.coverage_binding import (
    EXACT_OUTPUT_COVERAGE_BINDING_ID,
    BoundOutputCoverage,
    CoverageBindingError,
    EventOutputBatch,
    OutputEnvelopeSlot,
    bind_output_coverage,
)
from compact_vio.evaluation.translation import (
    EXACT_PAIR_TRANSLATION_RMSE_ID,
    ScaleCorrection,
    TimestampAssociation,
    TrajectoryAlignment,
    TrajectoryInterpolation,
    TranslationMetricError,
    TranslationRmsePolicy,
    TranslationRmseResult,
    exact_pair_translation_rmse,
)

__all__ = [
    "BoundOutputCoverage",
    "CoverageContractError",
    "CoverageBindingError",
    "EXACT_PAIR_TRANSLATION_RMSE_ID",
    "EXACT_OUTPUT_COVERAGE_BINDING_ID",
    "EXPLICIT_OUTPUT_COVERAGE_ID",
    "EventOutputBatch",
    "OutputCoverageLedger",
    "OutputCoverageOutcome",
    "OutputCoverageSummary",
    "OutputEnvelopeSlot",
    "OutputStatus",
    "ReasonCount",
    "ScaleCorrection",
    "TimestampAssociation",
    "TrajectoryAlignment",
    "TrajectoryInterpolation",
    "TranslationMetricError",
    "TranslationRmsePolicy",
    "TranslationRmseResult",
    "bind_output_coverage",
    "exact_pair_translation_rmse",
    "summarize_output_coverage",
]

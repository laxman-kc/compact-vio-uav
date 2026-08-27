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
    "CoverageContractError",
    "EXACT_PAIR_TRANSLATION_RMSE_ID",
    "EXPLICIT_OUTPUT_COVERAGE_ID",
    "OutputCoverageLedger",
    "OutputCoverageOutcome",
    "OutputCoverageSummary",
    "OutputStatus",
    "ReasonCount",
    "ScaleCorrection",
    "TimestampAssociation",
    "TrajectoryAlignment",
    "TrajectoryInterpolation",
    "TranslationMetricError",
    "TranslationRmsePolicy",
    "TranslationRmseResult",
    "exact_pair_translation_rmse",
    "summarize_output_coverage",
]

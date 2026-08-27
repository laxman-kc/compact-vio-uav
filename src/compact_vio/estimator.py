"""Framework-neutral estimator boundary for causal replay events.

This module defines only the common envelope shared by future classical,
learned, and hybrid estimators.  It deliberately leaves the odometry state,
sensor configuration, numerical backend, and model architecture unspecified.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from compact_vio.replay import EventKind, ReplayEvent

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class EstimatorContractError(ValueError):
    """Raised when an estimator value violates the common boundary."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EstimatorContractError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise EstimatorContractError(f"{field} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class OutputConvention:
    """Required declarations that give an opaque estimator payload meaning.

    Concrete values are intentionally not selected here.  A future accepted
    estimator profile must provide them without relying on library defaults.
    """

    convention_id: str
    reference_frame_id: str
    tracked_frame_id: str
    transform_direction: str
    translation_unit: str
    rotation_representation: str
    rotation_unit: str
    health_schema_id: str

    def __post_init__(self) -> None:
        for field in (
            "convention_id",
            "reference_frame_id",
            "tracked_frame_id",
            "transform_direction",
            "translation_unit",
            "rotation_representation",
            "rotation_unit",
            "health_schema_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)


@dataclass(frozen=True, slots=True)
class EstimatorOutput(Generic[OutputT]):
    """One explicitly timed estimator result with an opaque state payload."""

    convention: OutputConvention
    clock_id: str
    estimate_time_ns: int
    available_time_ns: int
    reset_generation: int
    health_code: str
    valid: bool
    payload: OutputT | None

    def __post_init__(self) -> None:
        if not isinstance(self.convention, OutputConvention):
            raise EstimatorContractError("convention must be an OutputConvention")
        _require_non_empty_text(self.clock_id, field="clock_id")
        _require_non_negative_integer(self.estimate_time_ns, field="estimate_time_ns")
        _require_non_negative_integer(self.available_time_ns, field="available_time_ns")
        _require_non_negative_integer(self.reset_generation, field="reset_generation")
        if self.available_time_ns < self.estimate_time_ns:
            raise EstimatorContractError("available_time_ns must not precede estimate_time_ns")
        _require_non_empty_text(self.health_code, field="health_code")
        if not isinstance(self.valid, bool):
            raise EstimatorContractError("valid must be boolean")
        if self.valid and self.payload is None:
            raise EstimatorContractError("valid output must carry a payload")
        if not self.valid and self.payload is not None:
            raise EstimatorContractError("invalid output must not carry a payload")


class Estimator(Protocol[InputT, OutputT]):
    """Protocol implemented by future estimator adapters.

    The adapter receives replay events unchanged and may emit zero or multiple
    output envelopes in deterministic adapter order. Reset is represented only
    by ``EventKind.RESET`` in that ordered event stream; there is no second
    out-of-band reset path.
    """

    def ingest(
        self,
        event: ReplayEvent[InputT],
        /,
    ) -> tuple[EstimatorOutput[OutputT], ...]:
        """Consume one event and return newly produced output envelopes."""
        ...


class EstimatorSession(Generic[InputT, OutputT]):
    """Validate one estimator adapter at the causal replay boundary.

    This wrapper checks observable envelope rules.  It cannot prove which
    opaque samples an estimator used internally; sample-lineage evidence is a
    later evaluator responsibility.
    """

    def __init__(
        self,
        estimator: Estimator[InputT, OutputT],
        *,
        clock_id: str,
        convention: OutputConvention,
    ) -> None:
        _require_non_empty_text(clock_id, field="clock_id")
        if not isinstance(convention, OutputConvention):
            raise EstimatorContractError("convention must be an OutputConvention")
        self._estimator = estimator
        self._clock_id = clock_id
        self._convention = convention
        self._reset_generation = 0

    @property
    def reset_generation(self) -> int:
        """Current generation, incremented once before each reset is handled."""

        return self._reset_generation

    def ingest(
        self,
        event: ReplayEvent[InputT],
    ) -> tuple[EstimatorOutput[OutputT], ...]:
        """Deliver one replay event and validate every returned output."""

        if not isinstance(event, ReplayEvent):
            raise EstimatorContractError("event must be a ReplayEvent")
        if event.clock_id != self._clock_id:
            raise EstimatorContractError(
                f"event uses clock {event.clock_id!r}, expected {self._clock_id!r}"
            )

        if event.kind is EventKind.RESET:
            self._reset_generation += 1

        outputs = self._estimator.ingest(event)
        if not isinstance(outputs, tuple):
            raise EstimatorContractError("estimator ingest must return a tuple")

        for output in outputs:
            self._validate_output(event, output)
        return outputs

    def _validate_output(
        self,
        event: ReplayEvent[InputT],
        output: object,
    ) -> None:
        if not isinstance(output, EstimatorOutput):
            raise EstimatorContractError(
                "estimator outputs must contain only EstimatorOutput values"
            )
        if output.convention != self._convention:
            raise EstimatorContractError("output convention differs from the session")
        if output.clock_id != self._clock_id:
            raise EstimatorContractError(
                f"output uses clock {output.clock_id!r}, expected {self._clock_id!r}"
            )
        if output.available_time_ns < event.available_time_ns:
            raise EstimatorContractError("output cannot be available before its triggering event")
        if output.reset_generation != self._reset_generation:
            raise EstimatorContractError(
                "output reset_generation differs from the session generation"
            )


__all__ = [
    "Estimator",
    "EstimatorContractError",
    "EstimatorOutput",
    "EstimatorSession",
    "OutputConvention",
]

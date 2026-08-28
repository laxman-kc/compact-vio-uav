"""Framework-neutral estimator boundary for causal replay events.

This module defines only the common envelope shared by future classical,
learned, and hybrid estimators. It deliberately leaves the odometry state,
sensor configuration, numerical backend, and model architecture unspecified.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Generic, Protocol, TypeVar

from compact_vio.replay import EventKind, ReplayEvent

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class EstimatorContractError(ValueError):
    """Raised when an estimator value violates the common boundary."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise EstimatorContractError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if type(value) is not int or value < 0:
        raise EstimatorContractError(f"{field} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class EstimatorInterfaceDeclaration:
    """Names the decisions every selected estimator profile must declare.

    The values are opaque, versioned identifiers. Requiring them here does not
    choose a state vector, scale mechanism, timing rule, or runtime policy.
    Those project values remain inputs to a later accepted profile.
    """

    interface_id: str
    state_schema_id: str
    state_variable_ids: tuple[str, ...]
    metric_scale_mechanism_id: str
    initialization_policy_id: str
    initialization_state_at_session_start: bool | None
    reset_policy_id: str
    initialization_state_after_reset: bool | None
    valid_output_requires_initialized: bool
    recurrence_policy_id: str
    recurrence_warmup_policy_id: str
    output_timestamp_semantics_id: str
    output_schedule_id: str
    causality_policy_id: str
    algorithmic_latency_definition_id: str
    processing_latency_definition_id: str
    staleness_policy_id: str
    input_gap_policy_id: str

    def __post_init__(self) -> None:
        for field in (
            "interface_id",
            "state_schema_id",
            "metric_scale_mechanism_id",
            "initialization_policy_id",
            "reset_policy_id",
            "recurrence_policy_id",
            "recurrence_warmup_policy_id",
            "output_timestamp_semantics_id",
            "output_schedule_id",
            "causality_policy_id",
            "algorithmic_latency_definition_id",
            "processing_latency_definition_id",
            "staleness_policy_id",
            "input_gap_policy_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)

        if type(self.state_variable_ids) is not tuple or not self.state_variable_ids:
            raise EstimatorContractError("state_variable_ids must be a non-empty tuple")
        for state_variable_id in self.state_variable_ids:
            _require_non_empty_text(
                state_variable_id,
                field="state_variable_ids",
            )
        if len(self.state_variable_ids) != len(set(self.state_variable_ids)):
            raise EstimatorContractError("state_variable_ids must not contain duplicates")
        for field in (
            "initialization_state_at_session_start",
            "initialization_state_after_reset",
        ):
            value = getattr(self, field)
            if value is not None and type(value) is not bool:
                raise EstimatorContractError(f"{field} must be boolean or None")
        if type(self.valid_output_requires_initialized) is not bool:
            raise EstimatorContractError("valid_output_requires_initialized must be boolean")


@dataclass(frozen=True, slots=True)
class OutputConvention:
    """Required declarations that give an opaque estimator payload meaning.

    Concrete values are intentionally not selected here. A future accepted
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
    interface_id: str | None = None
    initialized: bool | None = None

    def __post_init__(self) -> None:
        if type(self.convention) is not OutputConvention:
            raise EstimatorContractError("convention must be an OutputConvention")
        try:
            replace(self.convention)
        except Exception as error:
            raise EstimatorContractError(
                f"convention violates OutputConvention: {error}"
            ) from error
        _require_non_empty_text(self.clock_id, field="clock_id")
        _require_non_negative_integer(self.estimate_time_ns, field="estimate_time_ns")
        _require_non_negative_integer(self.available_time_ns, field="available_time_ns")
        _require_non_negative_integer(self.reset_generation, field="reset_generation")
        if self.available_time_ns < self.estimate_time_ns:
            raise EstimatorContractError("available_time_ns must not precede estimate_time_ns")
        _require_non_empty_text(self.health_code, field="health_code")
        if type(self.valid) is not bool:
            raise EstimatorContractError("valid must be boolean")
        if self.valid and self.payload is None:
            raise EstimatorContractError("valid output must carry a payload")
        if not self.valid and self.payload is not None:
            raise EstimatorContractError("invalid output must not carry a payload")
        if self.interface_id is not None:
            _require_non_empty_text(self.interface_id, field="interface_id")
        if self.initialized is not None and type(self.initialized) is not bool:
            raise EstimatorContractError("initialized must be boolean or None")
        if (self.interface_id is None) != (self.initialized is None):
            raise EstimatorContractError(
                "interface_id and initialized must both be absent or both be present"
            )


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

    Passing an interface enables the declared M3 contract. Omitting it keeps
    the earlier envelope available only as an explicitly undeclared legacy
    mode; legacy output is not evidence of M3 interface compliance.

    This wrapper checks observable envelope rules. It cannot prove which
    opaque samples an estimator used internally; sample-lineage evidence is a
    later evaluator responsibility.
    """

    def __init__(
        self,
        estimator: Estimator[InputT, OutputT],
        *,
        clock_id: str,
        convention: OutputConvention,
        interface: EstimatorInterfaceDeclaration | None = None,
    ) -> None:
        _require_non_empty_text(clock_id, field="clock_id")
        if type(convention) is not OutputConvention:
            raise EstimatorContractError("convention must be an OutputConvention")
        if interface is not None and type(interface) is not EstimatorInterfaceDeclaration:
            raise EstimatorContractError(
                "interface must be an EstimatorInterfaceDeclaration or None"
            )
        self._estimator = estimator
        self._clock_id = clock_id
        self._convention = convention
        self._interface = interface
        self._reset_generation = 0
        self._delivered_event_count = 0
        self._initialized = (
            None if interface is None else interface.initialization_state_at_session_start
        )

    @property
    def interface(self) -> EstimatorInterfaceDeclaration | None:
        """The declared interface, or None in compatibility-only mode."""

        return self._interface

    @property
    def clock_id(self) -> str:
        """Clock required for every event and output in this session."""

        return self._clock_id

    @property
    def delivered_event_count(self) -> int:
        """Events delivered to the adapter, including attempts that later fail."""

        return self._delivered_event_count

    @property
    def initialized(self) -> bool | None:
        """Unambiguous wrapper-observable state, or None if undeclared/ambiguous."""

        return self._initialized

    @property
    def reset_generation(self) -> int:
        """Current generation, incremented once before each reset is handled."""

        return self._reset_generation

    def ingest(
        self,
        event: ReplayEvent[InputT],
    ) -> tuple[EstimatorOutput[OutputT], ...]:
        """Deliver one replay event and validate every returned output."""

        if type(event) is not ReplayEvent:
            raise EstimatorContractError("event must be a ReplayEvent")
        if event.clock_id != self._clock_id:
            raise EstimatorContractError(
                f"event uses clock {event.clock_id!r}, expected {self._clock_id!r}"
            )

        if event.kind is EventKind.RESET:
            self._reset_generation += 1
            if self._interface is not None:
                self._initialized = self._interface.initialization_state_after_reset

        self._delivered_event_count += 1
        outputs = self._estimator.ingest(event)
        if type(outputs) is not tuple:
            raise EstimatorContractError("estimator ingest must return an exact tuple")

        for output in outputs:
            self._validate_output(event, output)

        if self._interface is not None and outputs:
            initialization_states = {output.initialized for output in outputs}
            self._initialized = (
                initialization_states.pop() if len(initialization_states) == 1 else None
            )
        return outputs

    def _validate_output(
        self,
        event: ReplayEvent[InputT],
        output: object,
    ) -> None:
        if type(output) is not EstimatorOutput:
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

        if self._interface is None:
            if output.interface_id is not None or output.initialized is not None:
                raise EstimatorContractError(
                    "legacy session output must not claim a declared interface"
                )
            return

        if output.interface_id != self._interface.interface_id:
            raise EstimatorContractError("output interface_id differs from the session interface")
        if type(output.initialized) is not bool:
            raise EstimatorContractError("declared output initialized must be boolean")
        if (
            self._interface.valid_output_requires_initialized
            and output.valid
            and not output.initialized
        ):
            raise EstimatorContractError("valid declared output requires initialized=true")


__all__ = [
    "Estimator",
    "EstimatorContractError",
    "EstimatorInterfaceDeclaration",
    "EstimatorOutput",
    "EstimatorSession",
    "OutputConvention",
]

"""Direct causal replay-to-estimator execution recording.

The recorder constructs and privately retains one fresh ``CausalReplay`` and
``EstimatorSession`` pair. It retains no partially validated event/output batch
and records the first failed event separately without retrying it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Generic, TypeVar

from compact_vio.estimator import (
    Estimator,
    EstimatorInterfaceDeclaration,
    EstimatorSession,
    OutputConvention,
)
from compact_vio.evaluation.coverage_binding import EventOutputBatch
from compact_vio.replay import CausalReplay, EventKind, ReplayContractError, ReplayEvent

InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class ExecutionRecorderError(RuntimeError):
    """Raised when recorder ownership or state is invalid."""


def _require_non_empty_text(value: object, *, field: str) -> None:
    if type(value) is not str or not value.strip():
        raise ExecutionRecorderError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if type(value) is not int or value < 0:
        raise ExecutionRecorderError(f"{field} must be a non-negative integer")


class RecorderState(Enum):
    """Observable recorder state without equating exhaustion and success."""

    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExecutionLifecyclePolicyDeclaration:
    """Names policies for the recorder's observable lifecycle behavior.

    These opaque identifiers do not select a failure taxonomy, threshold,
    output schedule, or scientific success rule. They only make the policies
    governing behavior already exposed by ``CausalEstimatorRecorder`` explicit.
    """

    policy_id: str
    replay_exhaustion_semantics_id: str
    processing_exception_semantics_id: str
    process_control_exception_semantics_id: str
    unattempted_suffix_semantics_id: str

    def __post_init__(self) -> None:
        for field in (
            "policy_id",
            "replay_exhaustion_semantics_id",
            "processing_exception_semantics_id",
            "process_control_exception_semantics_id",
            "unattempted_suffix_semantics_id",
        ):
            _require_non_empty_text(getattr(self, field), field=field)


@dataclass(frozen=True, slots=True)
class RecorderFailure:
    """First consumed event whose release, delivery, validation, or retention failed."""

    event: ReplayEvent[object]
    exception_type_id: str
    session_delivery_recorded: bool
    reset_transition_applied: bool

    def __post_init__(self) -> None:
        if type(self.event) is not ReplayEvent:
            raise ExecutionRecorderError("failure event must be a ReplayEvent")
        try:
            replace(self.event)
        except Exception as error:
            raise ExecutionRecorderError(f"failure event violates ReplayEvent: {error}") from error
        _require_non_empty_text(self.exception_type_id, field="exception_type_id")
        if type(self.session_delivery_recorded) is not bool:
            raise ExecutionRecorderError("session_delivery_recorded must be boolean")
        if type(self.reset_transition_applied) is not bool:
            raise ExecutionRecorderError("reset_transition_applied must be boolean")
        if self.reset_transition_applied and self.event.kind is not EventKind.RESET:
            raise ExecutionRecorderError("reset_transition_applied requires a RESET failure event")
        if (
            self.event.kind is EventKind.RESET
            and self.session_delivery_recorded
            and not self.reset_transition_applied
        ):
            raise ExecutionRecorderError("RESET session delivery requires the reset transition")


@dataclass(frozen=True, slots=True)
class RecorderSnapshot:
    """Structurally frozen in-memory snapshot from one recorder."""

    trace_id: str
    execution_policy: ExecutionLifecyclePolicyDeclaration
    clock_id: str
    planned_events: tuple[ReplayEvent[object], ...]
    state: RecorderState
    watermark_ns: int | None
    batches: tuple[EventOutputBatch, ...]
    failure: RecorderFailure | None
    replay_consumed_count: int
    replay_remaining_count: int
    replay_exhausted: bool
    session_delivered_event_count: int
    session_reset_generation: int

    def __post_init__(self) -> None:
        for field in ("trace_id", "clock_id"):
            _require_non_empty_text(getattr(self, field), field=field)
        if type(self.execution_policy) is not ExecutionLifecyclePolicyDeclaration:
            raise ExecutionRecorderError(
                "execution_policy must be an ExecutionLifecyclePolicyDeclaration"
            )
        try:
            replace(self.execution_policy)
        except Exception as error:
            raise ExecutionRecorderError(
                f"execution_policy violates ExecutionLifecyclePolicyDeclaration: {error}"
            ) from error
        if type(self.planned_events) is not tuple or not all(
            type(event) is ReplayEvent for event in self.planned_events
        ):
            raise ExecutionRecorderError("planned_events must contain only ReplayEvent values")
        try:
            CausalReplay(self.planned_events, clock_id=self.clock_id)
        except ReplayContractError as error:
            raise ExecutionRecorderError(f"planned_events violate CausalReplay: {error}") from error
        if type(self.state) is not RecorderState:
            raise ExecutionRecorderError("state must be a RecorderState")
        if self.watermark_ns is not None:
            _require_non_negative_integer(self.watermark_ns, field="watermark_ns")
        if type(self.batches) is not tuple or not all(
            type(batch) is EventOutputBatch for batch in self.batches
        ):
            raise ExecutionRecorderError("batches must contain only EventOutputBatch values")
        try:
            for batch in self.batches:
                replace(batch)
        except Exception as error:
            raise ExecutionRecorderError(f"batch violates EventOutputBatch: {error}") from error
        if self.failure is not None and type(self.failure) is not RecorderFailure:
            raise ExecutionRecorderError("failure must be a RecorderFailure or None")
        if self.failure is not None:
            try:
                replace(self.failure)
            except Exception as error:
                raise ExecutionRecorderError(
                    f"failure violates RecorderFailure: {error}"
                ) from error
        for field in (
            "replay_consumed_count",
            "replay_remaining_count",
            "session_delivered_event_count",
            "session_reset_generation",
        ):
            _require_non_negative_integer(getattr(self, field), field=field)
        if type(self.replay_exhausted) is not bool:
            raise ExecutionRecorderError("replay_exhausted must be boolean")
        attempted_count = len(self.batches) + (1 if self.failure is not None else 0)
        if self.replay_consumed_count != attempted_count:
            raise ExecutionRecorderError(
                "replay_consumed_count must equal successful batches plus failed event"
            )
        delivered_count = len(self.batches) + (
            1 if self.failure is not None and self.failure.session_delivery_recorded else 0
        )
        if self.session_delivered_event_count != delivered_count:
            raise ExecutionRecorderError(
                "session_delivered_event_count must match events delivered to the session"
            )
        if self.replay_consumed_count + self.replay_remaining_count != len(self.planned_events):
            raise ExecutionRecorderError(
                "replay counts must partition the complete planned event tuple"
            )
        if self.replay_exhausted != (self.replay_remaining_count == 0):
            raise ExecutionRecorderError(
                "replay_exhausted must exactly match replay_remaining_count"
            )
        if attempted_count > 0 and self.watermark_ns is None:
            raise ExecutionRecorderError("a nonempty trace must retain its replay watermark")

        expected_state = (
            RecorderState.FAILED
            if self.failure is not None
            else RecorderState.COMPLETED
            if self.replay_exhausted
            else RecorderState.ACTIVE
        )
        if self.state is not expected_state:
            raise ExecutionRecorderError("state must match failure and replay exhaustion")

        events = tuple(batch.event for batch in self.batches)
        if self.failure is not None:
            events += (self.failure.event,)
        for position, event in enumerate(events):
            if event is not self.planned_events[position]:
                raise ExecutionRecorderError(
                    "attempted events must be the exact prefix of planned_events"
                )
        delivered_events = tuple(batch.event for batch in self.batches)
        reset_count = sum(event.kind is EventKind.RESET for event in delivered_events)
        if self.failure is not None and self.failure.reset_transition_applied:
            reset_count += 1
        if self.session_reset_generation != reset_count:
            raise ExecutionRecorderError(
                "session_reset_generation must match attempted reset events"
            )
        if self.watermark_ns is not None and any(
            event.available_time_ns > self.watermark_ns for event in events
        ):
            raise ExecutionRecorderError("snapshot event availability must not exceed watermark_ns")
        if (
            self.watermark_ns is not None
            and attempted_count < len(self.planned_events)
            and self.planned_events[attempted_count].available_time_ns <= self.watermark_ns
            and self.failure is None
        ):
            raise ExecutionRecorderError(
                "an active snapshot must not leave an eligible planned event unattempted"
            )

    @property
    def execution_policy_id(self) -> str:
        """Compatibility view of the retained declaration identity."""

        return self.execution_policy.policy_id


class CausalEstimatorRecorder(Generic[InputT, OutputT]):
    """Record one fresh causal replay/session pair without prefetching events."""

    def __init__(
        self,
        events: Iterable[ReplayEvent[InputT]],
        estimator: Estimator[InputT, OutputT],
        *,
        clock_id: str,
        convention: OutputConvention,
        interface: EstimatorInterfaceDeclaration | None = None,
        trace_id: str,
        execution_policy: ExecutionLifecyclePolicyDeclaration,
    ) -> None:
        _require_non_empty_text(trace_id, field="trace_id")
        if type(execution_policy) is not ExecutionLifecyclePolicyDeclaration:
            raise ExecutionRecorderError(
                "execution_policy must be an ExecutionLifecyclePolicyDeclaration"
            )
        try:
            replace(execution_policy)
        except Exception as error:
            raise ExecutionRecorderError(
                f"execution_policy violates ExecutionLifecyclePolicyDeclaration: {error}"
            ) from error
        try:
            planned_events = tuple(events)
        except TypeError as error:
            raise ExecutionRecorderError("events must be an iterable") from error
        self._replay = CausalReplay(planned_events, clock_id=clock_id)
        self._session = EstimatorSession(
            estimator,
            clock_id=clock_id,
            convention=convention,
            interface=interface,
        )
        self._planned_events = planned_events
        self._trace_id = trace_id
        self._execution_policy = execution_policy
        self._batches: list[EventOutputBatch] = []
        self._failure: RecorderFailure | None = None
        self._processing = False
        self._expected_replay_consumed_count = 0
        self._expected_session_delivered_event_count = 0
        self._expected_watermark_ns: int | None = None

    def _check_owned_progress(self) -> None:
        if self._replay.consumed_count != self._expected_replay_consumed_count:
            raise ExecutionRecorderError("replay progress changed outside the recorder")
        if self._replay.watermark_ns != self._expected_watermark_ns:
            raise ExecutionRecorderError("replay watermark changed outside the recorder")
        if self._session.delivered_event_count != self._expected_session_delivered_event_count:
            raise ExecutionRecorderError("session progress changed outside the recorder")

    @property
    def batches(self) -> tuple[EventOutputBatch, ...]:
        """All successful complete batches recorded so far."""

        return self.snapshot().batches

    @property
    def failure(self) -> RecorderFailure | None:
        """First processing failure, or None while none has occurred."""

        return self.snapshot().failure

    @property
    def state(self) -> RecorderState:
        """Current active, completed, or failed state."""

        return self.snapshot().state

    def snapshot(self) -> RecorderSnapshot:
        """Return a structurally frozen snapshot without advancing execution."""

        if self._processing:
            raise ExecutionRecorderError("snapshot is unavailable while processing an event")
        self._check_owned_progress()
        state = (
            RecorderState.FAILED
            if self._failure is not None
            else RecorderState.COMPLETED
            if self._replay.exhausted
            else RecorderState.ACTIVE
        )
        return RecorderSnapshot(
            trace_id=self._trace_id,
            execution_policy=self._execution_policy,
            clock_id=self._replay.clock_id,
            planned_events=self._planned_events,
            state=state,
            watermark_ns=self._replay.watermark_ns,
            batches=tuple(self._batches),
            failure=self._failure,
            replay_consumed_count=self._replay.consumed_count,
            replay_remaining_count=self._replay.remaining_count,
            replay_exhausted=self._replay.exhausted,
            session_delivered_event_count=self._session.delivered_event_count,
            session_reset_generation=self._session.reset_generation,
        )

    def record_to(self, watermark_ns: int) -> RecorderSnapshot:
        """Record all events available through a causal watermark, one at a time.

        Ordinary processing exceptions become terminal failure evidence and are
        not re-raised. Process-control exceptions are recorded, terminalize the
        recorder, and are then re-raised.
        """

        if self._processing:
            raise ExecutionRecorderError("record_to is not reentrant")
        if self._failure is not None:
            raise ExecutionRecorderError("failed recorder is terminal and cannot retry")
        self._check_owned_progress()

        self._processing = True
        try:
            while True:
                replay_count_before = self._expected_replay_consumed_count
                session_count_before = self._expected_session_delivered_event_count
                reset_generation_before = self._session.reset_generation
                event: ReplayEvent[InputT] | None = None
                batch: EventOutputBatch | None = None
                try:
                    event = self._replay.release_next_to(watermark_ns)
                    if event is None:
                        self._expected_watermark_ns = self._replay.watermark_ns
                        break
                    outputs = self._session.ingest(event)
                    batch = EventOutputBatch(event=event, outputs=outputs)
                    self._batches.append(batch)
                    self._expected_watermark_ns = self._replay.watermark_ns
                    self._expected_replay_consumed_count = self._replay.consumed_count
                    self._expected_session_delivered_event_count = (
                        self._session.delivered_event_count
                    )
                except BaseException as error:
                    replay_count = self._replay.consumed_count
                    session_count = self._session.delivered_event_count
                    reset_generation = self._session.reset_generation
                    self._expected_watermark_ns = self._replay.watermark_ns
                    replay_delta = replay_count - replay_count_before
                    session_delta = session_count - session_count_before
                    reset_delta = reset_generation - reset_generation_before
                    if replay_delta == 0 and session_delta == 0:
                        raise
                    if replay_delta != 1 or session_delta not in (0, 1):
                        raise ExecutionRecorderError(
                            "processing changed replay or session by an unexpected count"
                        ) from error
                    self._expected_replay_consumed_count = replay_count
                    self._expected_session_delivered_event_count = session_count
                    if batch is not None and self._batches and self._batches[-1] is batch:
                        self._batches.pop()
                    failed_event = self._planned_events[replay_count_before]
                    if event is not None and event is not failed_event:
                        raise ExecutionRecorderError(
                            "released event differs from the planned event prefix"
                        ) from error
                    if (
                        reset_delta not in (0, 1)
                        or (reset_delta == 1 and failed_event.kind is not EventKind.RESET)
                        or (
                            failed_event.kind is EventKind.RESET
                            and session_delta == 1
                            and reset_delta != 1
                        )
                    ):
                        raise ExecutionRecorderError(
                            "processing changed reset generation unexpectedly"
                        ) from error
                    exception_type = type(error)
                    self._failure = RecorderFailure(
                        event=failed_event,
                        exception_type_id=(
                            f"{exception_type.__module__}.{exception_type.__qualname__}"
                        ),
                        session_delivery_recorded=session_delta == 1,
                        reset_transition_applied=reset_delta == 1,
                    )
                    if not issubclass(type(error), Exception):
                        raise
                    break
        finally:
            self._processing = False

        return self.snapshot()


__all__ = [
    "CausalEstimatorRecorder",
    "ExecutionLifecyclePolicyDeclaration",
    "ExecutionRecorderError",
    "RecorderFailure",
    "RecorderSnapshot",
    "RecorderState",
]

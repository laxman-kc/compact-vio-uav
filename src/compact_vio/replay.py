"""Deterministic causal replay for timestamped sensor events.

The replay core deliberately knows nothing about a particular dataset, camera
configuration, estimator, or payload type.  It only controls when an event may
be observed and preserves reset and invalid events for downstream handling.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

PayloadT = TypeVar("PayloadT")


class ReplayContractError(ValueError):
    """Raised when an event stream violates the causal replay contract."""


class EventKind(str, Enum):
    """Kinds understood by the modality-neutral replay boundary."""

    CAMERA = "camera"
    IMU = "imu"
    RESET = "reset"


def _require_non_empty_text(value: object, *, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReplayContractError(f"{field} must be a non-empty string")


def _require_non_negative_integer(value: object, *, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReplayContractError(f"{field} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ReplayEvent(Generic[PayloadT]):
    """One sensor or control event with separate measurement and availability time."""

    event_id: str
    sequence_index: int
    stream_id: str
    kind: EventKind
    clock_id: str
    measurement_time_ns: int
    available_time_ns: int
    payload: PayloadT
    valid: bool = True

    def __post_init__(self) -> None:
        _require_non_empty_text(self.event_id, field="event_id")
        _require_non_negative_integer(self.sequence_index, field="sequence_index")
        _require_non_empty_text(self.stream_id, field="stream_id")
        if not isinstance(self.kind, EventKind):
            raise ReplayContractError("kind must be an EventKind")
        _require_non_empty_text(self.clock_id, field="clock_id")
        _require_non_negative_integer(self.measurement_time_ns, field="measurement_time_ns")
        _require_non_negative_integer(self.available_time_ns, field="available_time_ns")
        if self.available_time_ns < self.measurement_time_ns:
            raise ReplayContractError("available_time_ns must not precede measurement_time_ns")
        if not isinstance(self.valid, bool):
            raise ReplayContractError("valid must be boolean")


class CausalReplay(Generic[PayloadT]):
    """Expose each event once, and only after its declared availability time."""

    def __init__(
        self,
        events: Iterable[ReplayEvent[PayloadT]],
        *,
        clock_id: str,
    ) -> None:
        _require_non_empty_text(clock_id, field="clock_id")
        event_tuple = tuple(events)

        event_ids: set[str] = set()
        sequence_indexes: set[int] = set()
        previous_ordering_key: tuple[int, int] | None = None
        previous_measurement_by_stream: dict[str, int] = {}

        for event in event_tuple:
            if not isinstance(event, ReplayEvent):
                raise ReplayContractError("events must contain only ReplayEvent values")
            if event.clock_id != clock_id:
                raise ReplayContractError(
                    f"event {event.event_id!r} uses clock {event.clock_id!r}, expected {clock_id!r}"
                )
            if event.event_id in event_ids:
                raise ReplayContractError(f"duplicate event_id: {event.event_id!r}")
            if event.sequence_index in sequence_indexes:
                raise ReplayContractError(f"duplicate sequence_index: {event.sequence_index}")

            ordering_key = (event.available_time_ns, event.sequence_index)
            if previous_ordering_key is not None and ordering_key < previous_ordering_key:
                raise ReplayContractError(
                    "events must be ordered by (available_time_ns, sequence_index)"
                )

            previous_measurement = previous_measurement_by_stream.get(event.stream_id)
            if (
                previous_measurement is not None
                and event.measurement_time_ns <= previous_measurement
            ):
                raise ReplayContractError(
                    f"measurement_time_ns must increase within stream {event.stream_id!r}"
                )

            event_ids.add(event.event_id)
            sequence_indexes.add(event.sequence_index)
            previous_ordering_key = ordering_key
            previous_measurement_by_stream[event.stream_id] = event.measurement_time_ns

        self._events = event_tuple
        self._clock_id = clock_id
        self._cursor = 0
        self._watermark_ns: int | None = None

    @property
    def clock_id(self) -> str:
        """Clock shared by every event in this replay."""

        return self._clock_id

    @property
    def watermark_ns(self) -> int | None:
        """Most recent replay watermark, or ``None`` before the first advance."""

        return self._watermark_ns

    @property
    def exhausted(self) -> bool:
        """Whether every event has been emitted."""

        return self._cursor == len(self._events)

    @property
    def consumed_count(self) -> int:
        """Number of events emitted so far."""

        return self._cursor

    @property
    def remaining_count(self) -> int:
        """Number of events not yet emitted."""

        return len(self._events) - self._cursor

    def advance_to(self, watermark_ns: int) -> tuple[ReplayEvent[PayloadT], ...]:
        """Emit unconsumed events available at or before ``watermark_ns``.

        A watermark may stay unchanged but cannot move backward.  Invalid and
        reset events are returned unchanged; downstream code must handle them
        explicitly rather than relying on replay to filter them.
        """

        _require_non_negative_integer(watermark_ns, field="watermark_ns")
        if self._watermark_ns is not None and watermark_ns < self._watermark_ns:
            raise ReplayContractError("watermark_ns must not move backward")

        start = self._cursor
        while (
            self._cursor < len(self._events)
            and self._events[self._cursor].available_time_ns <= watermark_ns
        ):
            self._cursor += 1

        self._watermark_ns = watermark_ns
        return self._events[start : self._cursor]


__all__ = ["CausalReplay", "EventKind", "ReplayContractError", "ReplayEvent"]

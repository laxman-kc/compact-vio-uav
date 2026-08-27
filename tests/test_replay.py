from __future__ import annotations

import inspect
import sys
import unittest

from compact_vio.replay import (
    CausalReplay,
    EventKind,
    ReplayContractError,
    ReplayEvent,
)


def _event(
    sequence_index: int,
    *,
    measurement_time_ns: int | None = None,
    available_time_ns: int | None = None,
    stream_id: str = "imu-0",
    kind: EventKind = EventKind.IMU,
    clock_id: str = "sensor-clock",
    valid: bool = True,
) -> ReplayEvent[int]:
    measurement = sequence_index * 10 if measurement_time_ns is None else measurement_time_ns
    available = measurement if available_time_ns is None else available_time_ns
    return ReplayEvent(
        event_id=f"event-{sequence_index}",
        sequence_index=sequence_index,
        stream_id=stream_id,
        kind=kind,
        clock_id=clock_id,
        measurement_time_ns=measurement,
        available_time_ns=available,
        payload=sequence_index,
        valid=valid,
    )


class CausalReplayTests(unittest.TestCase):
    def test_boundary_time_is_inclusive_and_future_event_stays_hidden(self) -> None:
        replay = CausalReplay([_event(1), _event(2)], clock_id="sensor-clock")

        self.assertEqual(replay.advance_to(10), (_event(1),))
        self.assertEqual(replay.consumed_count, 1)
        self.assertEqual(replay.remaining_count, 1)
        self.assertFalse(replay.exhausted)

        self.assertEqual(replay.advance_to(19), ())
        self.assertEqual(replay.advance_to(20), (_event(2),))
        self.assertTrue(replay.exhausted)

    def test_late_arrival_is_hidden_until_availability_time(self) -> None:
        imu = _event(1, measurement_time_ns=10, available_time_ns=15)
        delayed_camera = _event(
            2,
            measurement_time_ns=5,
            available_time_ns=20,
            stream_id="camera-0",
            kind=EventKind.CAMERA,
        )
        replay = CausalReplay([imu, delayed_camera], clock_id="sensor-clock")

        self.assertEqual(replay.advance_to(15), (imu,))
        self.assertEqual(replay.advance_to(19), ())
        self.assertEqual(replay.advance_to(20), (delayed_camera,))

    def test_equal_availability_uses_sequence_index_order(self) -> None:
        first = _event(3, measurement_time_ns=10, available_time_ns=30)
        second = _event(
            4,
            measurement_time_ns=20,
            available_time_ns=30,
            stream_id="camera-0",
            kind=EventKind.CAMERA,
        )
        replay = CausalReplay([first, second], clock_id="sensor-clock")

        self.assertEqual(replay.advance_to(30), (first, second))

    def test_repeated_advances_never_duplicate_events(self) -> None:
        event = _event(1)
        replay = CausalReplay([event], clock_id="sensor-clock")

        self.assertEqual(replay.advance_to(10), (event,))
        self.assertEqual(replay.advance_to(10), ())
        self.assertEqual(replay.advance_to(100), ())

    def test_release_next_to_drains_one_eligible_event_per_call(self) -> None:
        first = _event(1)
        second = _event(2)
        replay = CausalReplay([first, second], clock_id="sensor-clock")

        self.assertIs(replay.release_next_to(100), first)
        self.assertEqual(replay.consumed_count, 1)
        self.assertIs(replay.release_next_to(100), second)
        self.assertTrue(replay.exhausted)
        self.assertIsNone(replay.release_next_to(100))

    def test_release_next_to_preserves_unavailable_events_and_interoperates_with_advance(
        self,
    ) -> None:
        first = _event(1)
        second = _event(2)
        third = _event(3)
        replay = CausalReplay([first, second, third], clock_id="sensor-clock")

        self.assertIsNone(replay.release_next_to(9))
        self.assertEqual(replay.consumed_count, 0)
        self.assertIs(replay.release_next_to(10), first)
        self.assertEqual(replay.advance_to(100), (second, third))

        with self.assertRaisesRegex(ReplayContractError, "must not move backward"):
            replay.release_next_to(99)

    def test_interrupted_release_rolls_back_cursor_and_watermark(self) -> None:
        event = _event(1)
        replay = CausalReplay((event,), clock_id="sensor-clock")
        source_lines, first_line = inspect.getsourcelines(CausalReplay.release_next_to)
        cursor_line = first_line + next(
            index for index, line in enumerate(source_lines) if "self._cursor += 1" in line
        )

        def interrupt_before_cursor(frame, trace_event, arg):
            del arg
            if (
                frame.f_code is CausalReplay.release_next_to.__code__
                and trace_event == "line"
                and frame.f_lineno == cursor_line
            ):
                sys.settrace(None)
                raise KeyboardInterrupt
            return interrupt_before_cursor

        sys.settrace(interrupt_before_cursor)
        try:
            with self.assertRaises(KeyboardInterrupt):
                replay.release_next_to(10)
        finally:
            sys.settrace(None)

        self.assertIsNone(replay.watermark_ns)
        self.assertEqual(replay.consumed_count, 0)
        self.assertIs(replay.release_next_to(10), event)

    def test_backward_watermark_is_rejected_without_moving_cursor(self) -> None:
        first = _event(1)
        second = _event(2)
        replay = CausalReplay([first, second], clock_id="sensor-clock")
        self.assertEqual(replay.advance_to(10), (first,))

        with self.assertRaisesRegex(ReplayContractError, "must not move backward"):
            replay.advance_to(9)

        self.assertEqual(replay.watermark_ns, 10)
        self.assertEqual(replay.consumed_count, 1)
        self.assertEqual(replay.advance_to(20), (second,))

    def test_unsorted_input_is_rejected_instead_of_reordered(self) -> None:
        with self.assertRaisesRegex(ReplayContractError, "must be ordered"):
            CausalReplay([_event(2), _event(1)], clock_id="sensor-clock")

    def test_duplicate_ids_and_sequence_indexes_are_rejected(self) -> None:
        first = _event(1)
        duplicate_id = ReplayEvent(
            event_id=first.event_id,
            sequence_index=2,
            stream_id="camera-0",
            kind=EventKind.CAMERA,
            clock_id="sensor-clock",
            measurement_time_ns=20,
            available_time_ns=20,
            payload=2,
        )
        with self.assertRaisesRegex(ReplayContractError, "duplicate event_id"):
            CausalReplay([first, duplicate_id], clock_id="sensor-clock")

        duplicate_index = ReplayEvent(
            event_id="different-id",
            sequence_index=1,
            stream_id="camera-0",
            kind=EventKind.CAMERA,
            clock_id="sensor-clock",
            measurement_time_ns=20,
            available_time_ns=20,
            payload=2,
        )
        with self.assertRaisesRegex(ReplayContractError, "duplicate sequence_index"):
            CausalReplay([first, duplicate_index], clock_id="sensor-clock")

    def test_mixed_clocks_are_rejected(self) -> None:
        with self.assertRaisesRegex(ReplayContractError, "uses clock"):
            CausalReplay(
                [_event(1), _event(2, clock_id="other-clock")],
                clock_id="sensor-clock",
            )

    def test_replay_event_class_spoof_is_rejected(self) -> None:
        class EventImpostor:
            @property
            def __class__(self) -> type[ReplayEvent[object]]:
                return ReplayEvent

        with self.assertRaisesRegex(ReplayContractError, "ReplayEvent"):
            CausalReplay([EventImpostor()], clock_id="sensor-clock")

    def test_availability_before_measurement_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReplayContractError, "must not precede"):
            _event(1, measurement_time_ns=10, available_time_ns=9)

    def test_measurement_time_must_increase_within_each_stream(self) -> None:
        first = _event(1, measurement_time_ns=10, available_time_ns=10)
        repeated_measurement = _event(2, measurement_time_ns=10, available_time_ns=20)
        with self.assertRaisesRegex(ReplayContractError, "must increase within stream"):
            CausalReplay([first, repeated_measurement], clock_id="sensor-clock")

    def test_invalid_and_reset_events_are_not_filtered(self) -> None:
        invalid = _event(1, valid=False)
        reset = _event(
            2,
            stream_id="control",
            kind=EventKind.RESET,
            valid=True,
        )
        replay = CausalReplay([invalid, reset], clock_id="sensor-clock")

        emitted = replay.advance_to(20)
        self.assertEqual(emitted, (invalid, reset))
        self.assertFalse(emitted[0].valid)
        self.assertEqual(emitted[1].kind, EventKind.RESET)

    def test_empty_replay_is_exhausted(self) -> None:
        replay: CausalReplay[object] = CausalReplay([], clock_id="sensor-clock")

        self.assertTrue(replay.exhausted)
        self.assertEqual(replay.consumed_count, 0)
        self.assertEqual(replay.remaining_count, 0)
        self.assertEqual(replay.advance_to(0), ())

    def test_boolean_and_negative_time_values_are_rejected(self) -> None:
        with self.assertRaisesRegex(ReplayContractError, "non-negative integer"):
            _event(1, measurement_time_ns=True)
        replay = CausalReplay([], clock_id="sensor-clock")
        with self.assertRaisesRegex(ReplayContractError, "non-negative integer"):
            replay.advance_to(-1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from collections.abc import Callable

from compact_vio.estimator import (
    EstimatorContractError,
    EstimatorOutput,
    EstimatorSession,
    OutputConvention,
)
from compact_vio.replay import CausalReplay, EventKind, ReplayEvent

CONVENTION = OutputConvention(
    convention_id="test-odometry-v1",
    reference_frame_id="declared-reference-frame",
    tracked_frame_id="declared-tracked-frame",
    transform_direction="declared-by-test-profile",
    translation_unit="declared-by-test-profile",
    rotation_representation="declared-by-test-profile",
    rotation_unit="declared-by-test-profile",
    health_schema_id="test-health-v1",
)


def _event(
    *,
    sequence_index: int = 1,
    kind: EventKind = EventKind.IMU,
    clock_id: str = "sensor-clock",
    valid: bool = True,
) -> ReplayEvent[int]:
    return ReplayEvent(
        event_id=f"event-{sequence_index}",
        sequence_index=sequence_index,
        stream_id="control" if kind is EventKind.RESET else "sensor-0",
        kind=kind,
        clock_id=clock_id,
        measurement_time_ns=sequence_index * 10,
        available_time_ns=sequence_index * 10,
        payload=sequence_index,
        valid=valid,
    )


def _output(
    *,
    estimate_time_ns: int = 10,
    available_time_ns: int = 10,
    reset_generation: int = 0,
    health_code: str = "test-nominal",
    valid: bool = True,
    payload: object | None = "opaque-state",
    clock_id: str = "sensor-clock",
    convention: OutputConvention = CONVENTION,
) -> EstimatorOutput[object]:
    return EstimatorOutput(
        convention=convention,
        clock_id=clock_id,
        estimate_time_ns=estimate_time_ns,
        available_time_ns=available_time_ns,
        reset_generation=reset_generation,
        health_code=health_code,
        valid=valid,
        payload=payload,
    )


class _FunctionEstimator:
    def __init__(
        self,
        function: Callable[[ReplayEvent[int]], tuple[EstimatorOutput[object], ...]],
    ) -> None:
        self.function = function
        self.seen: list[ReplayEvent[int]] = []

    def ingest(
        self,
        event: ReplayEvent[int],
        /,
    ) -> tuple[EstimatorOutput[object], ...]:
        self.seen.append(event)
        return self.function(event)


class EstimatorOutputTests(unittest.TestCase):
    def test_valid_and_invalid_outputs_have_explicit_payload_rules(self) -> None:
        self.assertEqual(_output().payload, "opaque-state")
        self.assertIsNone(_output(valid=False, payload=None).payload)

        with self.assertRaisesRegex(EstimatorContractError, "must carry a payload"):
            _output(payload=None)
        with self.assertRaisesRegex(EstimatorContractError, "must not carry a payload"):
            _output(valid=False, payload="unexpected")

    def test_output_convention_requires_every_declaration(self) -> None:
        values = {
            "convention_id": "id",
            "reference_frame_id": "reference",
            "tracked_frame_id": "tracked",
            "transform_direction": "direction",
            "translation_unit": "unit",
            "rotation_representation": "rotation",
            "rotation_unit": "rotation-unit",
            "health_schema_id": "health",
        }
        for field in values:
            invalid = dict(values)
            invalid[field] = " "
            with self.subTest(field=field):
                with self.assertRaisesRegex(EstimatorContractError, field):
                    OutputConvention(**invalid)

    def test_output_rejects_missing_declarations_and_malformed_scalars(self) -> None:
        with self.assertRaisesRegex(EstimatorContractError, "OutputConvention"):
            _output(convention=None)  # type: ignore[arg-type]
        with self.assertRaisesRegex(EstimatorContractError, "clock_id"):
            _output(clock_id="")
        with self.assertRaisesRegex(EstimatorContractError, "non-negative integer"):
            _output(estimate_time_ns=True)
        with self.assertRaisesRegex(EstimatorContractError, "non-negative integer"):
            _output(available_time_ns=-1)
        with self.assertRaisesRegex(EstimatorContractError, "non-negative integer"):
            _output(reset_generation=True)
        with self.assertRaisesRegex(EstimatorContractError, "must not precede"):
            _output(estimate_time_ns=11, available_time_ns=10)
        with self.assertRaisesRegex(EstimatorContractError, "health_code"):
            _output(health_code="")
        with self.assertRaisesRegex(EstimatorContractError, "valid must be boolean"):
            _output(valid=1)  # type: ignore[arg-type]


class EstimatorSessionTests(unittest.TestCase):
    def _session(self, estimator: _FunctionEstimator) -> EstimatorSession[int, object]:
        return EstimatorSession(
            estimator,
            clock_id="sensor-clock",
            convention=CONVENTION,
        )

    def test_replay_event_flows_directly_to_estimator_without_conversion(self) -> None:
        event = _event()
        estimator = _FunctionEstimator(lambda _: (_output(),))
        session = self._session(estimator)
        replay = CausalReplay([event], clock_id="sensor-clock")

        released = replay.advance_to(event.available_time_ns)
        outputs = session.ingest(released[0])

        self.assertIs(estimator.seen[0], event)
        self.assertEqual(outputs, (_output(),))

    def test_zero_and_multiple_outputs_do_not_fix_an_output_rate(self) -> None:
        no_output = self._session(_FunctionEstimator(lambda _: ()))
        self.assertEqual(no_output.ingest(_event()), ())

        first = _output()
        second = _output(payload="second-opaque-state")
        multiple = self._session(_FunctionEstimator(lambda _: (first, second)))
        self.assertEqual(multiple.ingest(_event()), (first, second))

    def test_invalid_event_is_delivered_unchanged(self) -> None:
        invalid = _event(valid=False)
        estimator = _FunctionEstimator(lambda _: ())

        self._session(estimator).ingest(invalid)

        self.assertIs(estimator.seen[0], invalid)
        self.assertFalse(estimator.seen[0].valid)

    def test_reset_advances_generation_before_adapter_output_validation(self) -> None:
        generation = 0

        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            nonlocal generation
            if event.kind is EventKind.RESET:
                generation += 1
                return (
                    _output(
                        estimate_time_ns=event.measurement_time_ns,
                        available_time_ns=event.available_time_ns,
                        reset_generation=generation,
                        health_code="test-reset",
                        valid=False,
                        payload=None,
                    ),
                )
            return ()

        session = self._session(_FunctionEstimator(adapter))
        self.assertEqual(session.reset_generation, 0)

        session.ingest(_event(sequence_index=1, kind=EventKind.RESET))
        self.assertEqual(session.reset_generation, 1)
        session.ingest(_event(sequence_index=2, kind=EventKind.RESET))
        self.assertEqual(session.reset_generation, 2)

    def test_reset_and_later_outputs_cannot_use_an_old_generation(self) -> None:
        old = self._session(
            _FunctionEstimator(
                lambda _: (
                    _output(
                        reset_generation=0,
                        health_code="test-reset",
                        valid=False,
                        payload=None,
                    ),
                )
            )
        )
        with self.assertRaisesRegex(EstimatorContractError, "session generation"):
            old.ingest(_event(kind=EventKind.RESET))

        generation = 0

        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            nonlocal generation
            if event.kind is EventKind.RESET:
                generation += 1
                return ()
            return (
                _output(
                    estimate_time_ns=event.measurement_time_ns,
                    available_time_ns=event.available_time_ns,
                    reset_generation=0,
                ),
            )

        session = self._session(_FunctionEstimator(adapter))
        session.ingest(_event(sequence_index=1, kind=EventKind.RESET))
        with self.assertRaisesRegex(EstimatorContractError, "session generation"):
            session.ingest(_event(sequence_index=2))

    def test_session_rejects_clock_convention_and_availability_mismatch(self) -> None:
        with self.assertRaisesRegex(EstimatorContractError, "event uses clock"):
            self._session(_FunctionEstimator(lambda _: ())).ingest(_event(clock_id="other-clock"))

        wrong_clock = self._session(
            _FunctionEstimator(lambda _: (_output(clock_id="other-clock"),))
        )
        with self.assertRaisesRegex(EstimatorContractError, "output uses clock"):
            wrong_clock.ingest(_event())

        other_convention = OutputConvention(
            convention_id="other",
            reference_frame_id="reference",
            tracked_frame_id="tracked",
            transform_direction="direction",
            translation_unit="unit",
            rotation_representation="rotation",
            rotation_unit="rotation-unit",
            health_schema_id="health",
        )
        wrong_convention = self._session(
            _FunctionEstimator(lambda _: (_output(convention=other_convention),))
        )
        with self.assertRaisesRegex(EstimatorContractError, "convention differs"):
            wrong_convention.ingest(_event())

        early = self._session(
            _FunctionEstimator(lambda _: (_output(estimate_time_ns=9, available_time_ns=9),))
        )
        with self.assertRaisesRegex(EstimatorContractError, "triggering event"):
            early.ingest(_event())

    def test_session_rejects_wrong_return_container_and_item_type(self) -> None:
        list_return = _FunctionEstimator(lambda _: ())
        list_return.function = lambda _: []  # type: ignore[assignment,return-value]
        with self.assertRaisesRegex(EstimatorContractError, "return a tuple"):
            self._session(list_return).ingest(_event())

        wrong_item = _FunctionEstimator(lambda _: ())
        wrong_item.function = lambda _: ("not-output",)  # type: ignore[assignment,return-value]
        with self.assertRaisesRegex(EstimatorContractError, "EstimatorOutput"):
            self._session(wrong_item).ingest(_event())


if __name__ == "__main__":
    unittest.main()

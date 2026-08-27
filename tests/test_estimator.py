from __future__ import annotations

import unittest
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace

from compact_vio.estimator import (
    EstimatorContractError,
    EstimatorInterfaceDeclaration,
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

INTERFACE = EstimatorInterfaceDeclaration(
    interface_id="test-interface-v1",
    state_schema_id="test-state-schema-v1",
    state_variable_ids=("test-state-a", "test-state-b"),
    metric_scale_mechanism_id="test-scale-policy-v1",
    initialization_policy_id="test-initialization-policy-v1",
    initialization_state_at_session_start=False,
    reset_policy_id="test-reset-policy-v1",
    initialization_state_after_reset=False,
    valid_output_requires_initialized=True,
    recurrence_policy_id="test-recurrence-policy-v1",
    recurrence_warmup_policy_id="test-warmup-policy-v1",
    output_timestamp_semantics_id="test-output-time-policy-v1",
    output_schedule_id="test-output-schedule-v1",
    causality_policy_id="test-causality-policy-v1",
    algorithmic_latency_definition_id="test-algorithmic-latency-v1",
    processing_latency_definition_id="test-processing-latency-v1",
    staleness_policy_id="test-staleness-policy-v1",
    input_gap_policy_id="test-input-gap-policy-v1",
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
    interface_id: str | None = None,
    initialized: bool | None = None,
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
        interface_id=interface_id,
        initialized=initialized,
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


class EstimatorInterfaceDeclarationTests(unittest.TestCase):
    def _values(self) -> dict[str, object]:
        return {
            "interface_id": "test-interface-v1",
            "state_schema_id": "test-state-schema-v1",
            "state_variable_ids": ("test-state-a", "test-state-b"),
            "metric_scale_mechanism_id": "test-scale-policy-v1",
            "initialization_policy_id": "test-initialization-policy-v1",
            "initialization_state_at_session_start": False,
            "reset_policy_id": "test-reset-policy-v1",
            "initialization_state_after_reset": False,
            "valid_output_requires_initialized": True,
            "recurrence_policy_id": "test-recurrence-policy-v1",
            "recurrence_warmup_policy_id": "test-warmup-policy-v1",
            "output_timestamp_semantics_id": "test-output-time-policy-v1",
            "output_schedule_id": "test-output-schedule-v1",
            "causality_policy_id": "test-causality-policy-v1",
            "algorithmic_latency_definition_id": "test-algorithmic-latency-v1",
            "processing_latency_definition_id": "test-processing-latency-v1",
            "staleness_policy_id": "test-staleness-policy-v1",
            "input_gap_policy_id": "test-input-gap-policy-v1",
        }

    def _declaration(self, **updates: object) -> EstimatorInterfaceDeclaration:
        values = self._values()
        values.update(updates)
        return EstimatorInterfaceDeclaration(**values)  # type: ignore[arg-type]

    def test_every_policy_identifier_is_explicit_and_nonblank(self) -> None:
        for field, value in self._values().items():
            if not isinstance(value, str):
                continue
            with self.subTest(field=field):
                with self.assertRaisesRegex(EstimatorContractError, field):
                    self._declaration(**{field: " "})

    def test_state_variable_identifiers_are_a_unique_nonempty_tuple(self) -> None:
        invalid_values = (
            [],
            (),
            ("test-state", "test-state"),
            ("test-state", " "),
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    EstimatorContractError,
                    "state_variable_ids",
                ):
                    self._declaration(state_variable_ids=value)

    def test_initialization_semantics_are_explicit_profile_values(self) -> None:
        declaration = self._declaration(
            initialization_state_at_session_start=None,
            initialization_state_after_reset=True,
            valid_output_requires_initialized=False,
        )
        self.assertIsNone(declaration.initialization_state_at_session_start)
        self.assertTrue(declaration.initialization_state_after_reset)
        self.assertFalse(declaration.valid_output_requires_initialized)

        for field in (
            "initialization_state_at_session_start",
            "initialization_state_after_reset",
            "valid_output_requires_initialized",
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(EstimatorContractError, field):
                    self._declaration(**{field: 0})

    def test_declaration_is_immutable_and_does_not_select_numerical_values(self) -> None:
        declaration = self._declaration(
            state_variable_ids=("opaque-a",),
            metric_scale_mechanism_id="opaque-scale-decision",
            output_schedule_id="opaque-schedule-decision",
        )

        self.assertEqual(declaration.state_variable_ids, ("opaque-a",))
        self.assertFalse(hasattr(declaration, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            declaration.interface_id = "changed"  # type: ignore[misc]

    def test_latency_definitions_are_independently_required_but_may_share_an_id(
        self,
    ) -> None:
        declaration = self._declaration(
            algorithmic_latency_definition_id="same-explicit-definition",
            processing_latency_definition_id="same-explicit-definition",
        )

        self.assertEqual(
            declaration.algorithmic_latency_definition_id,
            declaration.processing_latency_definition_id,
        )


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

    def test_interface_identity_and_initialization_are_an_atomic_pair(self) -> None:
        with self.assertRaisesRegex(EstimatorContractError, "both be absent"):
            _output(interface_id=INTERFACE.interface_id, initialized=None)
        with self.assertRaisesRegex(EstimatorContractError, "both be absent"):
            _output(interface_id=None, initialized=True)


class EstimatorSessionTests(unittest.TestCase):
    def _session(self, estimator: _FunctionEstimator) -> EstimatorSession[int, object]:
        return EstimatorSession(
            estimator,
            clock_id="sensor-clock",
            convention=CONVENTION,
        )

    def _declared_session(
        self,
        estimator: _FunctionEstimator,
    ) -> EstimatorSession[int, object]:
        return EstimatorSession(
            estimator,
            clock_id="sensor-clock",
            convention=CONVENTION,
            interface=INTERFACE,
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
        self.assertEqual(no_output.delivered_event_count, 1)

        first = _output()
        second = _output(payload="second-opaque-state")
        multiple = self._session(_FunctionEstimator(lambda _: (first, second)))
        self.assertEqual(multiple.ingest(_event()), (first, second))
        self.assertEqual(multiple.delivered_event_count, 1)

    def test_delivered_event_count_retains_failed_adapter_and_validation_attempts(self) -> None:
        def raise_adapter(_: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            raise RuntimeError("synthetic adapter failure")

        adapter_failure = self._session(_FunctionEstimator(raise_adapter))
        with self.assertRaises(RuntimeError):
            adapter_failure.ingest(_event())
        self.assertEqual(adapter_failure.delivered_event_count, 1)

        invalid_estimator = _FunctionEstimator(lambda _: ())
        invalid_estimator.function = lambda _: []  # type: ignore[assignment,return-value]
        invalid_return = self._session(invalid_estimator)
        with self.assertRaisesRegex(EstimatorContractError, "exact tuple"):
            invalid_return.ingest(_event())
        self.assertEqual(invalid_return.delivered_event_count, 1)

        wrong_clock = self._session(_FunctionEstimator(lambda _: ()))
        with self.assertRaisesRegex(EstimatorContractError, "event uses clock"):
            wrong_clock.ingest(_event(clock_id="other-clock"))
        self.assertEqual(wrong_clock.delivered_event_count, 0)
        self.assertEqual(wrong_clock.clock_id, "sensor-clock")

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
        with self.assertRaisesRegex(EstimatorContractError, "exact tuple"):
            self._session(list_return).ingest(_event())

        class LengthHidingTuple(tuple):
            def __len__(self) -> int:
                return 0

        subclass_return = _FunctionEstimator(lambda _: ())
        subclass_return.function = lambda _: LengthHidingTuple(  # type: ignore[assignment,return-value]
            (_output(),)
        )
        with self.assertRaisesRegex(EstimatorContractError, "exact tuple"):
            self._session(subclass_return).ingest(_event())

        class TupleImpostor:
            @property
            def __class__(self) -> type[tuple[object, ...]]:
                return tuple

            def __iter__(self):
                yield _output()

            def __len__(self) -> int:
                return 0

        impostor_return = _FunctionEstimator(lambda _: ())
        impostor_return.function = lambda _: TupleImpostor()  # type: ignore[assignment,return-value]
        with self.assertRaisesRegex(EstimatorContractError, "exact tuple"):
            self._session(impostor_return).ingest(_event())

        class OutputImpostor:
            @property
            def __class__(self) -> type[EstimatorOutput[object]]:
                return EstimatorOutput

        output_impostor = _FunctionEstimator(lambda _: ())
        output_impostor.function = lambda _: (OutputImpostor(),)  # type: ignore[assignment,return-value]
        with self.assertRaisesRegex(EstimatorContractError, "EstimatorOutput"):
            self._session(output_impostor).ingest(_event())

        wrong_item = _FunctionEstimator(lambda _: ())
        wrong_item.function = lambda _: ("not-output",)  # type: ignore[assignment,return-value]
        with self.assertRaisesRegex(EstimatorContractError, "EstimatorOutput"):
            self._session(wrong_item).ingest(_event())

    def test_declared_session_tracks_explicit_initialization_transitions(self) -> None:
        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            initialized = event.sequence_index > 1
            return (
                _output(
                    estimate_time_ns=event.measurement_time_ns,
                    available_time_ns=event.available_time_ns,
                    valid=initialized,
                    payload="opaque-state" if initialized else None,
                    health_code=("test-nominal" if initialized else "test-initializing"),
                    interface_id=INTERFACE.interface_id,
                    initialized=initialized,
                ),
            )

        session = self._declared_session(_FunctionEstimator(adapter))
        self.assertIs(session.interface, INTERFACE)
        self.assertFalse(session.initialized)

        session.ingest(_event(sequence_index=1))
        self.assertFalse(session.initialized)
        session.ingest(_event(sequence_index=2))
        self.assertTrue(session.initialized)

    def test_declared_session_requires_matching_interface_and_boolean_state(self) -> None:
        for output in (
            _output(),
            _output(interface_id="other-interface", initialized=True),
        ):
            with self.subTest(interface_id=output.interface_id):
                session = self._declared_session(
                    _FunctionEstimator(lambda _, result=output: (result,))
                )
                with self.assertRaisesRegex(
                    EstimatorContractError,
                    "interface_id differs",
                ):
                    session.ingest(_event())

        with self.assertRaisesRegex(EstimatorContractError, "initialized"):
            _output(
                interface_id=INTERFACE.interface_id,
                initialized=0,  # type: ignore[arg-type]
            )

    def test_valid_output_requires_initialized_but_invalid_output_may_remain_initialized(
        self,
    ) -> None:
        invalid_state = self._declared_session(
            _FunctionEstimator(
                lambda _: (
                    _output(
                        interface_id=INTERFACE.interface_id,
                        initialized=False,
                    ),
                )
            )
        )
        with self.assertRaisesRegex(EstimatorContractError, "initialized=true"):
            invalid_state.ingest(_event())

        stale_but_initialized = self._declared_session(
            _FunctionEstimator(
                lambda _: (
                    _output(
                        valid=False,
                        payload=None,
                        health_code="test-stale",
                        interface_id=INTERFACE.interface_id,
                        initialized=True,
                    ),
                )
            )
        )
        stale_but_initialized.ingest(_event())
        self.assertTrue(stale_but_initialized.initialized)

    def test_declared_reset_applies_profile_state_before_adapter_runs(self) -> None:
        session: EstimatorSession[int, object]

        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            if event.kind is EventKind.RESET:
                self.assertFalse(session.initialized)
                return (
                    _output(
                        estimate_time_ns=event.measurement_time_ns,
                        available_time_ns=event.available_time_ns,
                        reset_generation=session.reset_generation,
                        health_code="test-reset",
                        valid=False,
                        payload=None,
                        interface_id=INTERFACE.interface_id,
                        initialized=False,
                    ),
                )
            return (
                _output(
                    estimate_time_ns=event.measurement_time_ns,
                    available_time_ns=event.available_time_ns,
                    interface_id=INTERFACE.interface_id,
                    initialized=True,
                ),
            )

        session = self._declared_session(_FunctionEstimator(adapter))
        session.ingest(_event(sequence_index=1))
        self.assertTrue(session.initialized)

        session.ingest(_event(sequence_index=2, kind=EventKind.RESET))
        self.assertEqual(session.reset_generation, 1)
        self.assertFalse(session.initialized)

    def test_profile_controls_start_reset_and_valid_initialization_semantics(
        self,
    ) -> None:
        profile = replace(
            INTERFACE,
            interface_id="test-warm-interface-v1",
            initialization_state_at_session_start=True,
            initialization_state_after_reset=True,
            valid_output_requires_initialized=False,
        )
        session: EstimatorSession[int, object]

        def adapter(event: ReplayEvent[int]) -> tuple[EstimatorOutput[object], ...]:
            self.assertTrue(session.initialized)
            return (
                _output(
                    estimate_time_ns=event.measurement_time_ns,
                    available_time_ns=event.available_time_ns,
                    reset_generation=session.reset_generation,
                    interface_id=profile.interface_id,
                    initialized=False,
                ),
            )

        session = EstimatorSession(
            _FunctionEstimator(adapter),
            clock_id="sensor-clock",
            convention=CONVENTION,
            interface=profile,
        )
        self.assertTrue(session.initialized)

        session.ingest(_event(sequence_index=1, kind=EventKind.RESET))
        self.assertFalse(session.initialized)

    def test_declared_state_changes_only_after_every_output_validates(self) -> None:
        first = _output(
            interface_id=INTERFACE.interface_id,
            initialized=True,
        )
        malformed_second = _output(
            interface_id="other-interface",
            initialized=True,
            payload="second-opaque-state",
        )
        session = self._declared_session(_FunctionEstimator(lambda _: (first, malformed_second)))

        with self.assertRaisesRegex(EstimatorContractError, "interface_id differs"):
            session.ingest(_event())
        self.assertFalse(session.initialized)

    def test_zero_outputs_do_not_change_declared_initialization(self) -> None:
        estimator = _FunctionEstimator(
            lambda _: (
                _output(
                    interface_id=INTERFACE.interface_id,
                    initialized=True,
                ),
            )
        )
        session = self._declared_session(estimator)
        session.ingest(_event(sequence_index=1))
        self.assertTrue(session.initialized)

        estimator.function = lambda _: ()
        session.ingest(_event(sequence_index=2))
        self.assertTrue(session.initialized)

    def test_mixed_output_states_make_the_wrapper_summary_ambiguous(self) -> None:
        uninitialized = _output(
            valid=False,
            payload=None,
            interface_id=INTERFACE.interface_id,
            initialized=False,
        )
        initialized = _output(
            payload="later-opaque-state",
            interface_id=INTERFACE.interface_id,
            initialized=True,
        )
        session = self._declared_session(_FunctionEstimator(lambda _: (uninitialized, initialized)))

        session.ingest(_event())
        self.assertIsNone(session.initialized)

    def test_legacy_session_cannot_claim_declared_interface_compliance(self) -> None:
        session = self._session(
            _FunctionEstimator(
                lambda _: (
                    _output(
                        interface_id=INTERFACE.interface_id,
                        initialized=True,
                    ),
                )
            )
        )

        self.assertIsNone(session.interface)
        self.assertIsNone(session.initialized)
        with self.assertRaisesRegex(EstimatorContractError, "legacy session"):
            session.ingest(_event())


if __name__ == "__main__":
    unittest.main()

"""ToF assessment 기반 로컬 경고 상태와 전체 projection 정책을 검증한다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum, auto
from threading import Event, Lock, Thread
from uuid import UUID

import pytest

from src.actuators.models import ActuatorCommand
from src.application.local_warning_coordinator import (
    LocalWarningAssessmentConflictError,
    LocalWarningCoordinator,
    LocalWarningDeliveryError,
    LocalWarningDeliveryFailure,
    LocalWarningDeliveryStage,
    LocalWarningZoneBinding,
)
from src.application.sensor_occupancy import OccupancyState
from src.application.tof_zone_authorization import (
    TofAuthorizationDecision,
    TofAuthorizationReason,
    TofZoneAuthorizationAssessment,
)
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import ZoneId, ZoneType, ZoneVisitId
from src.tracking.models import ParkingSessionId, PhysicalVehicleId


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(seconds=10)
MUCH_LATER = NOW + timedelta(seconds=20)

DISABLED_ZONE_ID = ZoneId(1)
EV_ZONE_ID = ZoneId(2)

VISIT_ID = ZoneVisitId(UUID(int=1))
VEHICLE_ID = PhysicalVehicleId(UUID(int=2))
SESSION_ID = ParkingSessionId(3)

DISABLED_BINDING = LocalWarningZoneBinding(
    zone_id=DISABLED_ZONE_ID,
    zone_type=ZoneType.DISABLED,
    led_actuator_id="disabled_zone_warning_led",
    led_action="BLINK",
    speaker_actuator_id="disabled_zone_warning_speaker",
    speaker_action="PLAY",
)
EV_BINDING = LocalWarningZoneBinding(
    zone_id=EV_ZONE_ID,
    zone_type=ZoneType.EV_CHARGING,
    led_actuator_id="ev_zone_warning_led",
    led_action="BLINK",
    speaker_actuator_id="ev_zone_warning_speaker",
    speaker_action="PLAY",
)


class FakeApplyResult(Enum):
    SUCCESS = auto()
    PRE_APPLY_FAILURE = auto()
    POST_APPLY_FAILURE = auto()


@dataclass(frozen=True)
class _QueuedApplyOutcome:
    result: FakeApplyResult
    error: Exception | None = None

    def __post_init__(self) -> None:
        if self.result is FakeApplyResult.SUCCESS:
            if self.error is not None:
                raise ValueError(
                    "SUCCESS outcome에는 error를 둘 수 없습니다."
                )
        elif not isinstance(self.error, Exception):
            raise ValueError(
                "실패 outcome에는 Exception이 필요합니다."
            )


def _pre_apply_failure(error: Exception) -> _QueuedApplyOutcome:
    return _QueuedApplyOutcome(
        result=FakeApplyResult.PRE_APPLY_FAILURE,
        error=error,
    )


def _post_apply_failure(error: Exception) -> _QueuedApplyOutcome:
    return _QueuedApplyOutcome(
        result=FakeApplyResult.POST_APPLY_FAILURE,
        error=error,
    )


@dataclass
class FakeActuatorPort:
    attempts: list[tuple[ActuatorCommand, ...]] = field(
        default_factory=list
    )
    applied_projections: list[tuple[ActuatorCommand, ...]] = field(
        default_factory=list
    )
    queued_outcomes: list[_QueuedApplyOutcome] = field(
        default_factory=list
    )

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        self.attempts.append(commands)

        outcome = (
            self.queued_outcomes.pop(0)
            if self.queued_outcomes
            else _QueuedApplyOutcome(FakeApplyResult.SUCCESS)
        )
        if outcome.result is FakeApplyResult.PRE_APPLY_FAILURE:
            assert outcome.error is not None
            raise outcome.error

        self.applied_projections.append(commands)
        if outcome.result is FakeApplyResult.POST_APPLY_FAILURE:
            assert outcome.error is not None
            raise outcome.error

    @property
    def projections(self) -> list[tuple[ActuatorCommand, ...]]:
        """첫 번째 커밋의 정상 정책 assertion과 호환되는 적용 기록."""

        return self.applied_projections


class BlockingFakeActuatorPort(FakeActuatorPort):
    def __init__(self, *, block_call_number: int = 1) -> None:
        super().__init__()
        self.block_call_number = block_call_number
        self.block_entered = Event()
        self.release = Event()
        self.second_call_entered = Event()
        self.max_concurrent_calls = 0

        self._entry_lock = Lock()
        self._entry_count = 0
        self._concurrent_calls = 0

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        with self._entry_lock:
            self._entry_count += 1
            call_number = self._entry_count
            self._concurrent_calls += 1
            self.max_concurrent_calls = max(
                self.max_concurrent_calls,
                self._concurrent_calls,
            )
            if call_number == 2:
                self.second_call_entered.set()

        try:
            if call_number == self.block_call_number:
                self.block_entered.set()
                if not self.release.wait(timeout=5):
                    raise AssertionError(
                        "blocking fake release가 전달되지 않았습니다."
                    )
            super().apply_projection(commands)
        finally:
            with self._entry_lock:
                self._concurrent_calls -= 1


class _ThreadFailureCapture:
    def __init__(self) -> None:
        self._lock = Lock()
        self.errors: list[BaseException] = []

    def run(self, operation: Callable[[], None]) -> None:
        try:
            operation()
        except BaseException as error:
            with self._lock:
                self.errors.append(error)


def _wait_for(event: Event) -> None:
    assert event.wait(timeout=5)


def _join(thread: Thread) -> None:
    thread.join(timeout=5)
    assert not thread.is_alive()


class _NonCallableActuatorPort:
    apply_projection = None


def _bindings() -> tuple[LocalWarningZoneBinding, ...]:
    # 입력 순서와 무관한 zone ID 정렬을 검증할 수 있도록 역순으로 제공한다.
    return EV_BINDING, DISABLED_BINDING


def _coordinator(
    *,
    bindings: tuple[LocalWarningZoneBinding, ...] | None = None,
    led_port: FakeActuatorPort | None = None,
    speaker_port: FakeActuatorPort | None = None,
) -> tuple[
    LocalWarningCoordinator,
    FakeActuatorPort,
    FakeActuatorPort,
]:
    active_led_port = led_port or FakeActuatorPort()
    active_speaker_port = speaker_port or FakeActuatorPort()
    coordinator = LocalWarningCoordinator(
        bindings=_bindings() if bindings is None else bindings,
        led_port=active_led_port,
        speaker_port=active_speaker_port,
    )
    return coordinator, active_led_port, active_speaker_port


def _observed(at: datetime = NOW) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at,
    )


def _assessment(
    zone_id: ZoneId,
    *,
    zone_type: ZoneType | None,
    occupancy_state: OccupancyState = OccupancyState.OCCUPIED,
    decision: TofAuthorizationDecision | None = (
        TofAuthorizationDecision.UNKNOWN
    ),
    reason: TofAuthorizationReason | None = (
        TofAuthorizationReason.VEHICLE_NOT_IDENTIFIED
    ),
    evaluated_at: datetime = NOW,
    assessment_revision: int = 1,
) -> TofZoneAuthorizationAssessment:
    confirmed = decision in {
        TofAuthorizationDecision.AUTHORIZED,
        TofAuthorizationDecision.UNAUTHORIZED,
    }

    return TofZoneAuthorizationAssessment(
        sensor_id=f"tof-zone-{int(zone_id)}",
        zone_id=zone_id,
        zone_type=zone_type,
        occupancy_state=occupancy_state,
        occupancy_revision=assessment_revision,
        occupancy_stable_since=(
            None
            if occupancy_state is OccupancyState.UNKNOWN
            else evaluated_at - timedelta(seconds=1)
        ),
        occupancy_observation=_observed(evaluated_at),
        zone_visit_id=VISIT_ID if confirmed else None,
        physical_vehicle_id=VEHICLE_ID if confirmed else None,
        parking_session_id=SESSION_ID if confirmed else None,
        context_revision=assessment_revision if confirmed else None,
        decision=decision,
        reason=reason,
        evaluated_at=evaluated_at,
        assessment_revision=assessment_revision,
    )


def _unauthorized(
    zone_id: ZoneId,
    zone_type: ZoneType,
    *,
    evaluated_at: datetime = NOW,
    assessment_revision: int = 1,
) -> TofZoneAuthorizationAssessment:
    return _assessment(
        zone_id,
        zone_type=zone_type,
        decision=TofAuthorizationDecision.UNAUTHORIZED,
        reason=None,
        evaluated_at=evaluated_at,
        assessment_revision=assessment_revision,
    )


def _authorized(
    zone_id: ZoneId,
    zone_type: ZoneType,
    *,
    evaluated_at: datetime = LATER,
    assessment_revision: int = 2,
) -> TofZoneAuthorizationAssessment:
    return _assessment(
        zone_id,
        zone_type=zone_type,
        decision=TofAuthorizationDecision.AUTHORIZED,
        reason=None,
        evaluated_at=evaluated_at,
        assessment_revision=assessment_revision,
    )


def _vacant(
    zone_id: ZoneId,
    zone_type: ZoneType,
    *,
    reason: TofAuthorizationReason = TofAuthorizationReason.ZONE_VACANT,
    evaluated_at: datetime = LATER,
    assessment_revision: int = 2,
) -> TofZoneAuthorizationAssessment:
    return _assessment(
        zone_id,
        zone_type=zone_type,
        occupancy_state=OccupancyState.VACANT,
        decision=None,
        reason=reason,
        evaluated_at=evaluated_at,
        assessment_revision=assessment_revision,
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"zone_id": ZoneId(0)},
        {"zone_id": True},
        {"zone_type": ZoneType.GENERAL},
        {"led_actuator_id": "  "},
        {"led_action": ""},
        {"speaker_actuator_id": "\t"},
        {"speaker_action": ""},
    ],
)
def test_binding_rejects_invalid_fields(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "zone_id": DISABLED_ZONE_ID,
        "zone_type": ZoneType.DISABLED,
        "led_actuator_id": "disabled-led",
        "led_action": "BLINK",
        "speaker_actuator_id": "disabled-speaker",
        "speaker_action": "PLAY",
    }
    values.update(overrides)

    with pytest.raises(ValueError):
        LocalWarningZoneBinding(**values)


def test_empty_bindings_are_rejected() -> None:
    with pytest.raises(ValueError, match="비어 있지 않은 tuple"):
        LocalWarningCoordinator(
            bindings=(),
            led_port=FakeActuatorPort(),
            speaker_port=FakeActuatorPort(),
        )


def test_non_tuple_bindings_are_rejected() -> None:
    with pytest.raises(ValueError, match="tuple"):
        LocalWarningCoordinator(
            bindings=[DISABLED_BINDING, EV_BINDING],  # type: ignore[arg-type]
            led_port=FakeActuatorPort(),
            speaker_port=FakeActuatorPort(),
        )


def test_duplicate_zone_id_is_rejected() -> None:
    duplicate = replace(EV_BINDING, zone_id=DISABLED_ZONE_ID)

    with pytest.raises(ValueError, match="zone_id가 중복"):
        LocalWarningCoordinator(
            bindings=(DISABLED_BINDING, duplicate),
            led_port=FakeActuatorPort(),
            speaker_port=FakeActuatorPort(),
        )


def test_duplicate_led_actuator_id_is_rejected() -> None:
    duplicate = replace(
        EV_BINDING,
        led_actuator_id=DISABLED_BINDING.led_actuator_id,
    )

    with pytest.raises(ValueError, match="LED actuator_id가 중복"):
        LocalWarningCoordinator(
            bindings=(DISABLED_BINDING, duplicate),
            led_port=FakeActuatorPort(),
            speaker_port=FakeActuatorPort(),
        )


def test_duplicate_speaker_actuator_id_is_rejected() -> None:
    duplicate = replace(
        EV_BINDING,
        speaker_actuator_id=DISABLED_BINDING.speaker_actuator_id,
    )

    with pytest.raises(ValueError, match="speaker actuator_id가 중복"):
        LocalWarningCoordinator(
            bindings=(DISABLED_BINDING, duplicate),
            led_port=FakeActuatorPort(),
            speaker_port=FakeActuatorPort(),
        )


def test_required_zone_type_binding_is_rejected_when_missing() -> None:
    with pytest.raises(
        ValueError,
        match="DISABLED와 EV_CHARGING binding",
    ):
        LocalWarningCoordinator(
            bindings=(DISABLED_BINDING,),
            led_port=FakeActuatorPort(),
            speaker_port=FakeActuatorPort(),
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_port"),
    [
        ("led_port", object()),
        ("speaker_port", object()),
        ("led_port", _NonCallableActuatorPort()),
        ("speaker_port", _NonCallableActuatorPort()),
    ],
)
def test_port_without_callable_apply_projection_is_rejected(
    field_name: str,
    invalid_port: object,
) -> None:
    led_port: object = FakeActuatorPort()
    speaker_port: object = FakeActuatorPort()

    if field_name == "led_port":
        led_port = invalid_port
    else:
        speaker_port = invalid_port

    with pytest.raises(
        ValueError,
        match=rf"{field_name}\.apply_projection은 callable",
    ):
        LocalWarningCoordinator(
            bindings=_bindings(),
            led_port=led_port,  # type: ignore[arg-type]
            speaker_port=speaker_port,  # type: ignore[arg-type]
        )


def test_initial_occupancy_unknown_does_not_call_ports() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    assessment = _assessment(
        DISABLED_ZONE_ID,
        zone_type=ZoneType.DISABLED,
        occupancy_state=OccupancyState.UNKNOWN,
        decision=None,
        reason=TofAuthorizationReason.OCCUPANCY_NOT_CONFIRMED,
    )

    assert assessment.occupancy_stable_since is None
    assert assessment.zone_visit_id is None
    assert assessment.physical_vehicle_id is None
    assert assessment.parking_session_id is None
    assert assessment.context_revision is None

    coordinator.consume_assessment(assessment)

    assert coordinator.active_zone_ids() == ()
    assert led_port.attempts == []
    assert speaker_port.attempts == []


def test_occupied_unknown_does_not_start_warning() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    coordinator.consume_assessment(
        _assessment(
            DISABLED_ZONE_ID,
            zone_type=ZoneType.DISABLED,
        )
    )

    assert coordinator.active_zone_ids() == ()
    assert led_port.attempts == []
    assert speaker_port.attempts == []


def test_none_zone_type_unknown_does_not_start_warning() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    coordinator.consume_assessment(
        _assessment(
            DISABLED_ZONE_ID,
            zone_type=None,
            occupancy_state=OccupancyState.UNKNOWN,
            decision=None,
            reason=TofAuthorizationReason.OCCUPANCY_NOT_CONFIRMED,
        )
    )

    assert coordinator.active_zone_ids() == ()
    assert led_port.attempts == []
    assert speaker_port.attempts == []


def test_disabled_unauthorized_activates_disabled_outputs() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert led_port.projections == [
        (
            ActuatorCommand(
                actuator_id="disabled_zone_warning_led",
                action="BLINK",
                reason="TOF_ZONE_UNAUTHORIZED",
                requested_at=NOW,
            ),
        )
    ]
    assert speaker_port.projections == [
        (
            ActuatorCommand(
                actuator_id="disabled_zone_warning_speaker",
                action="PLAY",
                reason="TOF_ZONE_UNAUTHORIZED",
                requested_at=NOW,
            ),
        )
    ]


def test_ev_unauthorized_activates_ev_outputs() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    coordinator.consume_assessment(
        _unauthorized(EV_ZONE_ID, ZoneType.EV_CHARGING)
    )

    assert coordinator.active_zone_ids() == (EV_ZONE_ID,)
    assert led_port.projections[0][0].actuator_id == (
        "ev_zone_warning_led"
    )
    assert speaker_port.projections[0][0].actuator_id == (
        "ev_zone_warning_speaker"
    )


def test_repeated_unauthorized_does_not_reapply_projection() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )
    coordinator.consume_assessment(
        _unauthorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            evaluated_at=LATER,
            assessment_revision=2,
        )
    )

    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1
    assert led_port.projections[0][0].requested_at == NOW
    assert speaker_port.projections[0][0].requested_at == NOW


def test_unknown_preserves_active_warning() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    coordinator.consume_assessment(
        _assessment(
            DISABLED_ZONE_ID,
            zone_type=ZoneType.DISABLED,
            evaluated_at=LATER,
            assessment_revision=2,
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1


def test_authorized_clears_only_its_zone() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    coordinator.consume_assessment(
        _authorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert coordinator.active_zone_ids() == ()
    assert led_port.projections[-1] == ()
    assert speaker_port.projections[-1] == ()


def test_unauthorized_after_authorized_starts_new_warning() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )
    coordinator.consume_assessment(
        _authorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    coordinator.consume_assessment(
        _unauthorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            evaluated_at=MUCH_LATER,
            assessment_revision=3,
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.projections) == 3
    assert len(speaker_port.projections) == 3
    assert led_port.projections[-1][0].requested_at == MUCH_LATER
    assert speaker_port.projections[-1][0].requested_at == MUCH_LATER


def test_trusted_vacant_clears_warning() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    coordinator.consume_assessment(
        _vacant(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert coordinator.active_zone_ids() == ()
    assert led_port.projections[-1] == ()
    assert speaker_port.projections[-1] == ()


def test_vacant_with_sensor_error_preserves_active_warning() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    coordinator.consume_assessment(
        _vacant(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            reason=(
                TofAuthorizationReason.SENSOR_OBSERVATION_UNRELIABLE
            ),
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1


def test_two_unauthorized_zones_create_two_led_commands() -> None:
    coordinator, led_port, _ = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(EV_ZONE_ID, ZoneType.EV_CHARGING)
    )
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert len(led_port.projections[-1]) == 2
    assert {
        command.actuator_id
        for command in led_port.projections[-1]
    } == {
        "disabled_zone_warning_led",
        "ev_zone_warning_led",
    }


def test_two_unauthorized_zones_create_two_speaker_commands() -> None:
    coordinator, _, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(EV_ZONE_ID, ZoneType.EV_CHARGING)
    )
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert len(speaker_port.projections[-1]) == 2
    assert {
        command.actuator_id
        for command in speaker_port.projections[-1]
    } == {
        "disabled_zone_warning_speaker",
        "ev_zone_warning_speaker",
    }


def test_projection_is_ordered_by_zone_id() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(EV_ZONE_ID, ZoneType.EV_CHARGING)
    )
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert [
        command.actuator_id
        for command in led_port.projections[-1]
    ] == [
        "disabled_zone_warning_led",
        "ev_zone_warning_led",
    ]
    assert [
        command.actuator_id
        for command in speaker_port.projections[-1]
    ] == [
        "disabled_zone_warning_speaker",
        "ev_zone_warning_speaker",
    ]


def test_clearing_one_zone_preserves_other_zone_in_full_projection() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )
    coordinator.consume_assessment(
        _unauthorized(
            EV_ZONE_ID,
            ZoneType.EV_CHARGING,
            evaluated_at=LATER,
            assessment_revision=2,
        )
    )

    coordinator.consume_assessment(
        _authorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            evaluated_at=MUCH_LATER,
            assessment_revision=3,
        )
    )

    assert coordinator.active_zone_ids() == (EV_ZONE_ID,)
    assert [
        command.actuator_id
        for command in led_port.projections[-1]
    ] == ["ev_zone_warning_led"]
    assert [
        command.actuator_id
        for command in speaker_port.projections[-1]
    ] == ["ev_zone_warning_speaker"]


def test_existing_requested_at_survives_other_zone_add_and_remove() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )
    coordinator.consume_assessment(
        _unauthorized(
            EV_ZONE_ID,
            ZoneType.EV_CHARGING,
            evaluated_at=LATER,
            assessment_revision=2,
        )
    )

    assert led_port.projections[-1][0].requested_at == NOW
    assert speaker_port.projections[-1][0].requested_at == NOW

    coordinator.consume_assessment(
        _authorized(
            EV_ZONE_ID,
            ZoneType.EV_CHARGING,
            evaluated_at=MUCH_LATER,
            assessment_revision=3,
        )
    )

    assert led_port.projections[-1][0].requested_at == NOW
    assert speaker_port.projections[-1][0].requested_at == NOW


def test_unregistered_zone_id_is_rejected() -> None:
    coordinator, _, _ = _coordinator()

    with pytest.raises(ValueError, match="등록되지 않은"):
        coordinator.consume_assessment(
            _assessment(
                ZoneId(999),
                zone_type=None,
                occupancy_state=OccupancyState.UNKNOWN,
                decision=None,
                reason=TofAuthorizationReason.OCCUPANCY_NOT_CONFIRMED,
            )
        )


def test_explicit_zone_type_mismatch_is_rejected() -> None:
    coordinator, _, _ = _coordinator()

    with pytest.raises(ValueError, match="zone_type이 binding과"):
        coordinator.consume_assessment(
            _assessment(
                DISABLED_ZONE_ID,
                zone_type=ZoneType.EV_CHARGING,
            )
        )


def test_none_zone_type_unknown_preserves_active_warning() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    coordinator.consume_assessment(
        _assessment(
            DISABLED_ZONE_ID,
            zone_type=None,
            evaluated_at=LATER,
            assessment_revision=2,
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1


def test_led_failure_does_not_skip_speaker() -> None:
    original_error = RuntimeError("LED unavailable")
    led_port = FakeActuatorPort(
        queued_outcomes=[_pre_apply_failure(original_error)]
    )
    coordinator, led_port, speaker_port = _coordinator(
        led_port=led_port
    )

    with pytest.raises(LocalWarningDeliveryError) as captured:
        coordinator.consume_assessment(
            _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
        )

    assert captured.value.failures == (
        LocalWarningDeliveryFailure(
            stage=LocalWarningDeliveryStage.LED,
            error=original_error,
        ),
    )
    assert speaker_port.applied_projections
    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)


def test_speaker_failure_preserves_successful_led_projection() -> None:
    original_error = RuntimeError("speaker unavailable")
    speaker_port = FakeActuatorPort(
        queued_outcomes=[_pre_apply_failure(original_error)]
    )
    coordinator, led_port, speaker_port = _coordinator(
        speaker_port=speaker_port
    )

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(
            _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
        )

    assert len(led_port.applied_projections) == 1
    assert speaker_port.applied_projections == []
    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)


def test_delivery_error_rejects_empty_failures() -> None:
    with pytest.raises(ValueError, match="비어 있지 않은 tuple"):
        LocalWarningDeliveryError(
            failures=(),
            active_zone_ids=(),
        )


def test_first_revision_one_is_accepted() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    coordinator.consume_assessment(
        _unauthorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            assessment_revision=1,
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.applied_projections) == 1
    assert len(speaker_port.applied_projections) == 1


def test_revision_zero_is_rejected_without_port_calls() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    with pytest.raises(ValueError, match="1 이상"):
        coordinator.consume_assessment(
            _unauthorized(
                DISABLED_ZONE_ID,
                ZoneType.DISABLED,
                assessment_revision=0,
            )
        )

    assert coordinator.active_zone_ids() == ()
    assert led_port.attempts == []
    assert speaker_port.attempts == []


def test_higher_revision_is_accepted() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            assessment_revision=1,
        )
    )

    coordinator.consume_assessment(
        _authorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            assessment_revision=2,
        )
    )

    assert coordinator.active_zone_ids() == ()
    assert led_port.applied_projections[-1] == ()
    assert speaker_port.applied_projections[-1] == ()


def test_lower_revision_does_not_change_state_or_projection() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            assessment_revision=2,
        )
    )
    led_attempts = tuple(led_port.attempts)
    speaker_attempts = tuple(speaker_port.attempts)

    coordinator.consume_assessment(
        _authorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            assessment_revision=1,
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert tuple(led_port.attempts) == led_attempts
    assert tuple(speaker_port.attempts) == speaker_attempts


def test_same_revision_same_assessment_is_clean_no_op() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    assessment = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )
    coordinator.consume_assessment(assessment)

    coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1
    assert led_port.applied_projections[0][0].requested_at == NOW


def test_same_revision_same_assessment_retries_dirty_port() -> None:
    original_error = RuntimeError("LED unavailable")
    led_port = FakeActuatorPort(
        queued_outcomes=[_pre_apply_failure(original_error)]
    )
    coordinator, led_port, speaker_port = _coordinator(
        led_port=led_port
    )
    assessment = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )

    with pytest.raises(LocalWarningDeliveryError) as captured:
        coordinator.consume_assessment(assessment)

    error = captured.value
    assert error.failures == (
        LocalWarningDeliveryFailure(
            stage=LocalWarningDeliveryStage.LED,
            error=original_error,
        ),
    )
    assert error.primary_error is original_error
    assert error.__cause__ is original_error
    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)

    coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 2
    assert len(led_port.applied_projections) == 1
    assert len(speaker_port.attempts) == 1


def test_same_revision_different_decision_is_conflict() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    existing = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )
    incoming = _authorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
        evaluated_at=NOW,
        assessment_revision=1,
    )
    coordinator.consume_assessment(existing)

    with pytest.raises(
        LocalWarningAssessmentConflictError
    ) as captured:
        coordinator.consume_assessment(incoming)

    error = captured.value
    assert error.zone_id == DISABLED_ZONE_ID
    assert error.assessment_revision == 1
    assert error.existing_assessment is existing
    assert error.incoming_assessment is incoming
    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1
    assert (
        led_port.applied_projections[-1][0].requested_at
        == existing.evaluated_at
    )
    assert (
        speaker_port.applied_projections[-1][0].requested_at
        == existing.evaluated_at
    )


def test_same_revision_different_evaluated_at_is_conflict() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    existing = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )
    incoming = replace(existing, evaluated_at=LATER)
    coordinator.consume_assessment(existing)

    with pytest.raises(LocalWarningAssessmentConflictError):
        coordinator.consume_assessment(incoming)

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1


def test_zone_revisions_are_independent() -> None:
    coordinator, led_port, speaker_port = _coordinator()

    coordinator.consume_assessment(
        _unauthorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            assessment_revision=5,
        )
    )
    coordinator.consume_assessment(
        _unauthorized(
            EV_ZONE_ID,
            ZoneType.EV_CHARGING,
            evaluated_at=LATER,
            assessment_revision=1,
        )
    )

    assert coordinator.active_zone_ids() == (
        DISABLED_ZONE_ID,
        EV_ZONE_ID,
    )
    assert len(led_port.applied_projections[-1]) == 2
    assert len(speaker_port.applied_projections[-1]) == 2


def test_speaker_only_failure_retry_calls_only_speaker() -> None:
    original_error = RuntimeError("speaker unavailable")
    speaker_port = FakeActuatorPort(
        queued_outcomes=[_pre_apply_failure(original_error)]
    )
    coordinator, led_port, speaker_port = _coordinator(
        speaker_port=speaker_port
    )
    assessment = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(assessment)
    coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 2


def test_both_port_failures_are_aggregated_in_stage_order() -> None:
    led_error = RuntimeError("GPIO unavailable")
    speaker_error = RuntimeError("audio unavailable")
    led_port = FakeActuatorPort(
        queued_outcomes=[_pre_apply_failure(led_error)]
    )
    speaker_port = FakeActuatorPort(
        queued_outcomes=[_post_apply_failure(speaker_error)]
    )
    coordinator, _, _ = _coordinator(
        led_port=led_port,
        speaker_port=speaker_port,
    )

    with pytest.raises(LocalWarningDeliveryError) as captured:
        coordinator.consume_assessment(
            _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
        )

    error = captured.value
    assert tuple(failure.stage for failure in error.failures) == (
        LocalWarningDeliveryStage.LED,
        LocalWarningDeliveryStage.SPEAKER,
    )
    assert error.failures[0].error is led_error
    assert error.failures[1].error is speaker_error
    assert error.primary_error is led_error
    assert error.__cause__ is led_error
    assert error.active_zone_ids == (DISABLED_ZONE_ID,)
    assert "LED: GPIO unavailable" in str(error)
    assert "SPEAKER: audio unavailable" in str(error)


def test_post_apply_activation_failure_then_authorized_forces_empty() -> None:
    original_error = RuntimeError("uncertain LED result")
    led_port = FakeActuatorPort(
        queued_outcomes=[_post_apply_failure(original_error)]
    )
    coordinator, led_port, _ = _coordinator(led_port=led_port)

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(
            _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
        )

    assert led_port.applied_projections[-1]

    coordinator.consume_assessment(
        _authorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert led_port.applied_projections[-1] == ()
    assert coordinator.active_zone_ids() == ()


def test_post_apply_activation_failure_then_vacant_forces_empty() -> None:
    original_error = RuntimeError("uncertain speaker result")
    speaker_port = FakeActuatorPort(
        queued_outcomes=[_post_apply_failure(original_error)]
    )
    coordinator, _, speaker_port = _coordinator(
        speaker_port=speaker_port
    )

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(
            _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
        )

    assert speaker_port.applied_projections[-1]

    coordinator.consume_assessment(
        _vacant(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )

    assert speaker_port.applied_projections[-1] == ()
    assert coordinator.active_zone_ids() == ()


def test_post_apply_failure_same_assessment_retry_cleans_dirty_state() -> None:
    original_error = RuntimeError("uncertain LED result")
    led_port = FakeActuatorPort(
        queued_outcomes=[_post_apply_failure(original_error)]
    )
    coordinator, led_port, speaker_port = _coordinator(
        led_port=led_port
    )
    assessment = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )

    with pytest.raises(LocalWarningDeliveryError) as captured:
        coordinator.consume_assessment(assessment)

    assert captured.value.failures == (
        LocalWarningDeliveryFailure(
            stage=LocalWarningDeliveryStage.LED,
            error=original_error,
        ),
    )
    assert len(led_port.attempts) == 1
    assert len(led_port.applied_projections) == 1
    assert len(speaker_port.attempts) == 1
    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)

    # 같은 assessment retry는 경고 정책을 다시 적용하지 않지만,
    # dirty port에는 현재 active projection을 다시 전달한다.
    coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 2
    assert len(led_port.applied_projections) == 2
    assert (
        led_port.applied_projections[0]
        == led_port.applied_projections[1]
    )
    assert (
        led_port.applied_projections[-1][0].requested_at
        == assessment.evaluated_at
    )
    assert len(speaker_port.attempts) == 1

    # 성공한 reconcile이 dirty를 해제했으므로 다음 retry는 no-op이다.
    coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 2
    assert len(speaker_port.attempts) == 1


def test_failed_clear_is_retried_with_same_assessment() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    )
    clear = _authorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
    clear_error = RuntimeError("LED clear unavailable")
    led_port.queued_outcomes.append(
        _pre_apply_failure(clear_error)
    )

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(clear)

    assert coordinator.active_zone_ids() == ()
    assert led_port.applied_projections[-1]
    assert speaker_port.applied_projections[-1] == ()

    coordinator.consume_assessment(clear)

    assert led_port.applied_projections[-1] == ()
    assert len(speaker_port.attempts) == 2


def test_higher_unknown_retries_dirty_active_projection() -> None:
    led_error = RuntimeError("LED unavailable")
    led_port = FakeActuatorPort(
        queued_outcomes=[_pre_apply_failure(led_error)]
    )
    coordinator, led_port, speaker_port = _coordinator(
        led_port=led_port
    )

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(
            _unauthorized(
                DISABLED_ZONE_ID,
                ZoneType.DISABLED,
                assessment_revision=1,
            )
        )

    coordinator.consume_assessment(
        _assessment(
            DISABLED_ZONE_ID,
            zone_type=ZoneType.DISABLED,
            evaluated_at=LATER,
            assessment_revision=2,
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 2
    assert len(speaker_port.attempts) == 1
    assert led_port.applied_projections[-1]


def test_stale_unknown_does_not_retry_dirty_port() -> None:
    led_error = RuntimeError("LED unavailable")
    led_port = FakeActuatorPort(
        queued_outcomes=[_pre_apply_failure(led_error)]
    )
    coordinator, led_port, speaker_port = _coordinator(
        led_port=led_port
    )

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(
            _unauthorized(
                DISABLED_ZONE_ID,
                ZoneType.DISABLED,
                assessment_revision=2,
            )
        )

    coordinator.consume_assessment(
        _assessment(
            DISABLED_ZONE_ID,
            zone_type=ZoneType.DISABLED,
            evaluated_at=LATER,
            assessment_revision=1,
        )
    )

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 1


def test_other_zone_is_preserved_in_projection_during_failure() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    coordinator.consume_assessment(
        _unauthorized(EV_ZONE_ID, ZoneType.EV_CHARGING)
    )
    led_error = RuntimeError("LED unavailable")
    led_port.queued_outcomes.append(
        _pre_apply_failure(led_error)
    )

    with pytest.raises(LocalWarningDeliveryError):
        coordinator.consume_assessment(
            _unauthorized(DISABLED_ZONE_ID, ZoneType.DISABLED)
        )

    assert coordinator.active_zone_ids() == (
        DISABLED_ZONE_ID,
        EV_ZONE_ID,
    )
    assert {
        command.actuator_id
        for command in led_port.attempts[-1]
    } == {
        "disabled_zone_warning_led",
        "ev_zone_warning_led",
    }
    assert len(speaker_port.applied_projections[-1]) == 2


def test_concurrent_zone_activation_preserves_both_zones() -> None:
    coordinator, led_port, speaker_port = _coordinator()
    start = Event()
    capture = _ThreadFailureCapture()

    def consume(assessment: TofZoneAuthorizationAssessment) -> None:
        _wait_for(start)
        coordinator.consume_assessment(assessment)

    threads = (
        Thread(
            target=capture.run,
            args=(
                lambda: consume(
                    _unauthorized(
                        DISABLED_ZONE_ID,
                        ZoneType.DISABLED,
                    )
                ),
            ),
        ),
        Thread(
            target=capture.run,
            args=(
                lambda: consume(
                    _unauthorized(
                        EV_ZONE_ID,
                        ZoneType.EV_CHARGING,
                    )
                ),
            ),
        ),
    )
    for thread in threads:
        thread.start()
    start.set()
    for thread in threads:
        _join(thread)

    assert capture.errors == []
    assert coordinator.active_zone_ids() == (
        DISABLED_ZONE_ID,
        EV_ZONE_ID,
    )
    assert len(led_port.applied_projections[-1]) == 2
    assert len(speaker_port.applied_projections[-1]) == 2
    assert len(
        {
            command.actuator_id
            for command in led_port.applied_projections[-1]
        }
    ) == 2
    assert len(
        {
            command.actuator_id
            for command in speaker_port.applied_projections[-1]
        }
    ) == 2


def test_concurrent_consumers_do_not_overlap_port_calls() -> None:
    led_port = BlockingFakeActuatorPort()
    coordinator, _, _ = _coordinator(led_port=led_port)
    capture = _ThreadFailureCapture()
    second_started = Event()

    first = Thread(
        target=capture.run,
        args=(
            lambda: coordinator.consume_assessment(
                _unauthorized(
                    DISABLED_ZONE_ID,
                    ZoneType.DISABLED,
                )
            ),
        ),
    )

    def consume_second() -> None:
        second_started.set()
        coordinator.consume_assessment(
            _unauthorized(
                EV_ZONE_ID,
                ZoneType.EV_CHARGING,
            )
        )

    second = Thread(
        target=capture.run,
        args=(consume_second,),
    )

    first.start()
    _wait_for(led_port.block_entered)

    second.start()
    _wait_for(second_started)

    # 첫 호출이 block된 동안 두 번째 port 진입이 발생하는지 bounded
    # window에서 관찰한다.
    overlap_observed = led_port.second_call_entered.wait(timeout=0.1)

    # 어느 thread의 회수가 실패하더라도 다른 thread의 join은 먼저 시도한다.
    led_port.release.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert overlap_observed is False
    assert led_port.second_call_entered.is_set()
    assert led_port.max_concurrent_calls == 1
    assert capture.errors == []


def test_concurrent_lower_revision_cannot_overwrite_higher_revision() -> None:
    led_port = BlockingFakeActuatorPort(block_call_number=2)
    coordinator, _, speaker_port = _coordinator(led_port=led_port)
    coordinator.consume_assessment(
        _unauthorized(
            DISABLED_ZONE_ID,
            ZoneType.DISABLED,
            assessment_revision=1,
        )
    )
    capture = _ThreadFailureCapture()
    lower_started = Event()

    higher = Thread(
        target=capture.run,
        args=(
            lambda: coordinator.consume_assessment(
                _authorized(
                    DISABLED_ZONE_ID,
                    ZoneType.DISABLED,
                    assessment_revision=3,
                )
            ),
        ),
    )

    def consume_lower() -> None:
        lower_started.set()
        coordinator.consume_assessment(
            _unauthorized(
                DISABLED_ZONE_ID,
                ZoneType.DISABLED,
                evaluated_at=MUCH_LATER,
                assessment_revision=2,
            )
        )

    lower = Thread(
        target=capture.run,
        args=(consume_lower,),
    )

    higher.start()
    _wait_for(led_port.block_entered)
    lower.start()
    _wait_for(lower_started)

    led_port.release.set()
    higher.join(timeout=5)
    lower.join(timeout=5)

    assert not higher.is_alive()
    assert not lower.is_alive()
    assert capture.errors == []
    assert coordinator.active_zone_ids() == ()
    assert led_port.applied_projections[-1] == ()
    assert speaker_port.applied_projections[-1] == ()
    assert len(led_port.attempts) == 2
    assert len(speaker_port.attempts) == 2

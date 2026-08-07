"""ToF assessment 기반 로컬 경고 상태와 전체 projection 정책을 검증한다."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.actuators.models import ActuatorCommand
from src.application.local_warning_coordinator import (
    LocalWarningCoordinator,
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


@dataclass
class FakeActuatorPort:
    attempts: list[tuple[ActuatorCommand, ...]] = field(
        default_factory=list
    )
    projections: list[tuple[ActuatorCommand, ...]] = field(
        default_factory=list
    )
    pre_apply_failures: list[Exception] = field(default_factory=list)

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        self.attempts.append(commands)

        # 장치 상태를 변경하기 전에 실패한 것이 확실한 경우만 모델링한다.
        # 적용 여부가 불확실한 실패의 복구는 후속 커밋의 dirty 상태 책임이다.
        if self.pre_apply_failures:
            raise self.pre_apply_failures.pop(0)

        self.projections.append(commands)


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


def test_led_pre_apply_failure_is_propagated_and_can_be_retried() -> None:
    led_port = FakeActuatorPort(
        pre_apply_failures=[RuntimeError("LED unavailable")]
    )
    coordinator, led_port, speaker_port = _coordinator(
        led_port=led_port
    )
    assessment = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )

    with pytest.raises(RuntimeError, match="LED unavailable"):
        coordinator.consume_assessment(assessment)

    assert coordinator.active_zone_ids() == (DISABLED_ZONE_ID,)
    assert len(led_port.attempts) == 1
    assert led_port.projections == []
    assert speaker_port.attempts == []

    coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 2
    assert len(led_port.projections) == 1
    assert len(speaker_port.projections) == 1


def test_speaker_pre_apply_failure_preserves_successful_led_projection() -> None:
    speaker_port = FakeActuatorPort(
        pre_apply_failures=[RuntimeError("speaker unavailable")]
    )
    coordinator, led_port, speaker_port = _coordinator(
        speaker_port=speaker_port
    )
    assessment = _unauthorized(
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
    )

    with pytest.raises(RuntimeError, match="speaker unavailable"):
        coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 1
    assert len(led_port.projections) == 1
    assert len(speaker_port.attempts) == 1
    assert speaker_port.projections == []

    coordinator.consume_assessment(assessment)

    assert len(led_port.attempts) == 1
    assert len(speaker_port.attempts) == 2
    assert len(speaker_port.projections) == 1

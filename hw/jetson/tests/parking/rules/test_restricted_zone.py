"""전용구역 RuleEvaluator의 삼상태 계약을 검증한다."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    IncidentKey,
    IncidentSignalValue,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.parking.rules.restricted_zone import evaluate
from src.parking.zone_registry import ZoneRegistry
from src.session.models import SessionContext
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    VehicleId,
)


T0 = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
SQUARE = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))


def observed() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=T0,
    )


def unknown() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
        last_reliable_observed_at=T0,
    )


def make_zone(zone_id: int, zone_type: ZoneType) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=SQUARE,
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="calibration-v1",
    )


def make_visit(
    zone_id: int,
    *,
    observation: ObservationStatus | None = None,
) -> ZoneVisit:
    return ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=zone_id)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(zone_id),
        zone_definition_version=ZoneDefinitionVersion(1),
        state=ZoneVisitState.INSIDE,
        observation=observation or observed(),
        entry_trusted_seconds=1.0,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
        entered_candidate_at=T0,
        entered_at=T0,
    )


def make_session(
    *,
    is_disabled_vehicle: bool | None,
    is_electric: bool | None,
) -> SessionContext:
    return SessionContext(
        parking_session_id=ParkingSessionId(10),
        vehicle_id=VehicleId(20),
        is_electric=is_electric,
        is_disabled_vehicle=is_disabled_vehicle,
    )


def make_context(
    *,
    zone_type: ZoneType,
    session_context: SessionContext | None,
    context_observation: ObservationStatus | None = None,
    vehicle_observation: ObservationStatus | None = None,
    visit_observation: ObservationStatus | None = None,
) -> RuleContext:
    vehicle_status = vehicle_observation or observed()
    vehicle = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.95,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="camera-1",
        observation=vehicle_status,
    )
    return RuleContext(
        vehicle=vehicle,
        observation=context_observation or observed(),
        session_context=session_context,
        active_zone_visits=(make_visit(1, observation=visit_observation),),
        parking_episode=None,
        parking_assignment=None,
        blocking_relations=(),
        zones=ZoneRegistry((make_zone(1, zone_type),)),
        observed_at=T0,
    )


def only_signal(context: RuleContext):
    signals = evaluate(context)
    assert len(signals) == 1
    return signals[0]


def test_unqualified_disabled_zone_visit_is_matched_and_confirmable() -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=False,
                is_electric=False,
            ),
        )
    )

    assert signal.key == IncidentKey.for_zone_visit(
        ZoneVisitId(UUID(int=1)),
        "DISABLED_ZONE_UNAUTHORIZED",
    )
    assert signal.value is IncidentSignalValue.MATCHED
    assert signal.confirmable is True


def test_qualified_disabled_zone_visit_is_not_matched() -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=True,
                is_electric=False,
            ),
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False


@pytest.mark.parametrize(
    "session_context",
    [
        None,
        make_session(is_disabled_vehicle=None, is_electric=False),
    ],
)
def test_missing_disabled_qualification_is_unknown(
    session_context: SessionContext | None,
) -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=session_context,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


def test_ev_qualification_uses_the_electric_flag() -> None:
    unauthorized = only_signal(
        make_context(
            zone_type=ZoneType.EV_CHARGING,
            session_context=make_session(
                is_disabled_vehicle=True,
                is_electric=False,
            ),
        )
    )
    authorized = only_signal(
        make_context(
            zone_type=ZoneType.EV_CHARGING,
            session_context=make_session(
                is_disabled_vehicle=False,
                is_electric=True,
            ),
        )
    )

    assert unauthorized.key.rule_code == "EV_ZONE_UNAUTHORIZED"
    assert unauthorized.value is IncidentSignalValue.MATCHED
    assert unauthorized.confirmable is True
    assert authorized.value is IncidentSignalValue.NOT_MATCHED
    assert authorized.confirmable is False


@pytest.mark.parametrize(
    ("context_observation", "vehicle_observation", "visit_observation"),
    [
        (unknown(), None, None),
        (None, unknown(), None),
        (None, None, unknown()),
    ],
)
def test_unreliable_required_observation_is_unknown(
    context_observation: ObservationStatus | None,
    vehicle_observation: ObservationStatus | None,
    visit_observation: ObservationStatus | None,
) -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=False,
                is_electric=False,
            ),
            context_observation=context_observation,
            vehicle_observation=vehicle_observation,
            visit_observation=visit_observation,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


def test_general_zone_produces_no_restricted_zone_signal() -> None:
    context = make_context(
        zone_type=ZoneType.GENERAL,
        session_context=make_session(
            is_disabled_vehicle=False,
            is_electric=False,
        ),
    )

    assert evaluate(context) == ()

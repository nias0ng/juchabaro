"""전용구역 RuleEvaluator의 삼상태 계약을 검증한다."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    AssignmentState,
    IncidentKey,
    IncidentSignalValue,
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingState,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.parking.rules.restricted_zone import (
    evaluate,
    qualification_for_zone,
)
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
        trusted_sample_max_gap_seconds=1.0,
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


def make_assignment(zone_id: int = 1) -> ParkingAssignment:
    return ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        representative_footprint=SQUARE,
        confidence=0.9,
        last_stable_at=T0,
        zone_id=ZoneId(zone_id),
    )


def make_episode(
    state: ParkingState,
    *,
    zone_id: int = 1,
    observation: ObservationStatus | None = None,
) -> ParkingEpisode:
    was_parked = state in {ParkingState.PARKED, ParkingState.MOVE_PENDING}
    return ParkingEpisode(
        episode_id=ParkingEpisodeId(UUID(int=10)),
        physical_vehicle_id=CAR,
        state=state,
        observation=observation or observed(),
        stationary_trusted_seconds=10.0,
        movement_trusted_seconds=0.0,
        parking_confirmation_seconds=5.0,
        movement_confirmation_seconds=1.0,
        last_signal=(
            MotionSignal.MOVING
            if state is ParkingState.MOVE_PENDING
            else MotionSignal.STATIONARY
        ),
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T0,
        trusted_sample_max_gap_seconds=1.0,
        assignment=make_assignment(zone_id),
        parked_at=(T0 if was_parked else None),
        movement_candidate_at=(
            T0 if state is ParkingState.MOVE_PENDING else None
        ),
    )


def make_context(
    *,
    zone_type: ZoneType,
    session_context: SessionContext | None,
    context_observation: ObservationStatus | None = None,
    vehicle_observation: ObservationStatus | None = None,
    visit_observation: ObservationStatus | None = None,
    parking_motion_observation: ObservationStatus | None = None,
    parking_state: ParkingState | None = ParkingState.PARKED,
    parking_zone_id: int = 1,
    parking_observation: ObservationStatus | None = None,
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
    episode = (
        None
        if parking_state is None
        else make_episode(
            parking_state,
            zone_id=parking_zone_id,
            observation=parking_observation,
        )
    )
    return RuleContext(
        vehicle=vehicle,
        observation=context_observation or observed(),
        parking_motion_observation=parking_motion_observation or observed(),
        session_context=session_context,
        active_zone_visits=(make_visit(1, observation=visit_observation),),
        parking_episode=episode,
        parking_assignment=None if episode is None else episode.assignment,
        placement_evidence=None,
        placement_evidence_source=None,
        blocking_relations=(),
        zones=ZoneRegistry((make_zone(1, zone_type),)),
        bad_parking_min_primary_overlap_ratio=0.75,
        bad_parking_min_secondary_overlap_ratio=0.25,
        out_of_zone_min_spot_overlap_ratio=0.50,
        observed_at=T0,
    )


def only_signal(context: RuleContext):
    signals = evaluate(context)
    assert len(signals) == 1
    return signals[0]


@pytest.mark.parametrize(
    ("zone_type", "is_disabled_vehicle", "is_electric", "expected"),
    [
        (ZoneType.DISABLED, True, False, True),
        (ZoneType.DISABLED, False, True, False),
        (ZoneType.DISABLED, None, True, None),
        (ZoneType.EV_CHARGING, False, True, True),
        (ZoneType.EV_CHARGING, True, False, False),
        (ZoneType.EV_CHARGING, True, None, None),
    ],
)
def test_qualification_for_zone_selects_the_zone_specific_attribute(
    zone_type: ZoneType,
    is_disabled_vehicle: bool | None,
    is_electric: bool | None,
    expected: bool | None,
) -> None:
    session_context = make_session(
        is_disabled_vehicle=is_disabled_vehicle,
        is_electric=is_electric,
    )

    assert qualification_for_zone(zone_type, session_context) is expected


@pytest.mark.parametrize(
    "zone_type",
    [ZoneType.DISABLED, ZoneType.EV_CHARGING],
)
def test_qualification_for_zone_without_session_context_is_unknown(
    zone_type: ZoneType,
) -> None:
    assert qualification_for_zone(zone_type, None) is None


@pytest.mark.parametrize(
    "zone_type",
    [
        ZoneType.GENERAL,
        ZoneType.AISLE,
        ZoneType.ENTRY_EXIT,
    ],
)
def test_qualification_for_zone_rejects_unsupported_zone_type(
    zone_type: ZoneType,
) -> None:
    with pytest.raises(ValueError):
        qualification_for_zone(zone_type, None)


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
    assert signal.evidence == {
        "isDisabledVehicle": False,
        "zoneId": ZoneId(1),
        "zoneType": ZoneType.DISABLED.value,
        "parkingState": ParkingState.PARKED.value,
        "parkingAssignmentState": AssignmentState.ASSIGNED.value,
        "parkingAssignmentZoneId": ZoneId(1),
    }


@pytest.mark.parametrize("parking_state", [None, ParkingState.STOP_PENDING])
def test_unqualified_visit_before_parking_is_not_matched(
    parking_state: ParkingState | None,
) -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=False,
                is_electric=False,
            ),
            parking_state=parking_state,
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False
    assert signal.evidence["reason"] == (
        "PARKING_NOT_CONFIRMED_IN_VISITED_ZONE"
    )


def test_parked_assignment_must_match_the_restricted_visit_zone() -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=False,
                is_electric=False,
            ),
            parking_zone_id=2,
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False
    assert signal.evidence["parkingAssignmentZoneId"] == ZoneId(2)


def test_move_pending_pauses_an_existing_restricted_incident() -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=False,
                is_electric=False,
            ),
            parking_state=ParkingState.MOVE_PENDING,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False
    assert signal.evidence["reason"] == "MOVEMENT_CONFIRMATION_PENDING"


def test_authoritative_qualification_clears_even_during_move_pending() -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=True,
                is_electric=False,
            ),
            parking_state=ParkingState.MOVE_PENDING,
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False


def test_unreliable_parked_episode_is_unknown() -> None:
    signal = only_signal(
        make_context(
            zone_type=ZoneType.DISABLED,
            session_context=make_session(
                is_disabled_vehicle=False,
                is_electric=False,
            ),
            parking_observation=unknown(),
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False
    assert signal.evidence["reason"] == (
        "PARKING_EPISODE_OBSERVATION_UNAVAILABLE"
    )


def test_entering_visit_does_not_confirm_camera_restricted_zone_incident() -> None:
    context = make_context(
        zone_type=ZoneType.DISABLED,
        session_context=make_session(
            is_disabled_vehicle=False,
            is_electric=False,
        ),
    )
    entering_visit = replace(
        context.active_zone_visits[0],
        state=ZoneVisitState.ENTERING,
        entry_trusted_seconds=0.0,
        entered_at=None,
    )
    context = replace(
        context,
        active_zone_visits=(entering_visit,),
    )

    signal = only_signal(context)

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False
    assert signal.evidence == {
        "reason": "REQUIRED_INPUT_UNAVAILABLE",
        "zoneId": ZoneId(1),
        "zoneType": ZoneType.DISABLED.value,
        "zoneVisitState": ZoneVisitState.ENTERING.value,
        "isDisabledVehicle": False,
        "parkingState": ParkingState.PARKED.value,
        "parkingAssignmentState": AssignmentState.ASSIGNED.value,
        "parkingAssignmentZoneId": ZoneId(1),
    }


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
    (
        "context_observation",
        "vehicle_observation",
        "visit_observation",
        "parking_motion_observation",
    ),
    [
        (unknown(), None, None, None),
        (None, unknown(), None, None),
        (None, None, unknown(), None),
        (None, None, None, unknown()),
    ],
)
def test_unreliable_required_observation_is_unknown(
    context_observation: ObservationStatus | None,
    vehicle_observation: ObservationStatus | None,
    visit_observation: ObservationStatus | None,
    parking_motion_observation: ObservationStatus | None,
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
            parking_motion_observation=parking_motion_observation,
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


def test_missing_zone_definition_produces_both_unknown_signals_in_order() -> None:
    context = make_context(
        zone_type=ZoneType.DISABLED,
        session_context=make_session(
            is_disabled_vehicle=False,
            is_electric=False,
        ),
    )
    context = replace(
        context,
        zones=ZoneRegistry((make_zone(2, ZoneType.GENERAL),)),
    )

    signals = evaluate(context)

    assert tuple(signal.key.rule_code for signal in signals) == (
        "DISABLED_ZONE_UNAUTHORIZED",
        "EV_ZONE_UNAUTHORIZED",
    )
    assert tuple(signal.value for signal in signals) == (
        IncidentSignalValue.UNKNOWN,
        IncidentSignalValue.UNKNOWN,
    )
    assert tuple(signal.confirmable for signal in signals) == (False, False)
    expected_evidence = {
        "reason": "ZONE_DEFINITION_UNAVAILABLE",
        "zoneId": ZoneId(1),
        "zoneVisitState": ZoneVisitState.INSIDE.value,
    }
    assert tuple(signal.evidence for signal in signals) == (
        expected_evidence,
        expected_evidence,
    )

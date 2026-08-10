"""EV 구역 장기 점유 RuleEvaluator의 삼상태 계약을 검증한다."""

from datetime import datetime, timedelta, timezone
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
from src.parking.rules.ev_overstay import evaluate
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
)


T0 = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
SQUARE = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))


def observed(at: datetime) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at,
    )


def unknown() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.CAMERA_UNAVAILABLE,
        last_reliable_observed_at=T0,
    )


def make_zone(
    *,
    zone_type: ZoneType = ZoneType.EV_CHARGING,
    allowed_duration_seconds: float | None = 60.0,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(1),
        zone_type=zone_type,
        polygon=SQUARE,
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="calibration-v1",
        allowed_duration_seconds=allowed_duration_seconds,
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
    observed_at: datetime,
    parked_at_seconds: float = 0.0,
    zone_id: int = 1,
    observation: ObservationStatus | None = None,
) -> ParkingEpisode:
    was_parked = state in {ParkingState.PARKED, ParkingState.MOVE_PENDING}
    return ParkingEpisode(
        episode_id=ParkingEpisodeId(UUID(int=2)),
        physical_vehicle_id=CAR,
        state=state,
        observation=observation or observed(observed_at),
        stationary_trusted_seconds=60.0 if was_parked else 0.0,
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
        updated_at=observed_at,
        trusted_sample_max_gap_seconds=1.0,
        assignment=make_assignment(zone_id) if was_parked else None,
        parked_at=(
            T0 + timedelta(seconds=parked_at_seconds)
            if was_parked
            else None
        ),
        movement_candidate_at=(
            observed_at if state is ParkingState.MOVE_PENDING else None
        ),
    )


def make_context(
    *,
    wall_clock_seconds: float = 0.0,
    trusted_occupancy_seconds: float = 0.0,
    parked_at_seconds: float = 0.0,
    zone_type: ZoneType = ZoneType.EV_CHARGING,
    allowed_duration_seconds: float | None = 60.0,
    context_observation: ObservationStatus | None = None,
    vehicle_observation: ObservationStatus | None = None,
    visit_observation: ObservationStatus | None = None,
    parking_motion_observation: ObservationStatus | None = None,
    parking_state: ParkingState | None = ParkingState.PARKED,
    parking_zone_id: int = 1,
    parking_observation: ObservationStatus | None = None,
    visit_state: ZoneVisitState = ZoneVisitState.INSIDE,
) -> RuleContext:
    observed_at = T0 + timedelta(seconds=wall_clock_seconds)
    reliable = observed(observed_at)
    vehicle = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.95,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=observed_at,
        camera_id="camera-1",
        observation=vehicle_observation or reliable,
    )
    visit = ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=1)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(1),
        zone_definition_version=ZoneDefinitionVersion(1),
        state=visit_state,
        observation=visit_observation or reliable,
        entry_trusted_seconds=trusted_occupancy_seconds,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=observed_at,
        entered_candidate_at=T0,
        entered_at=T0,
        exit_candidate_at=(observed_at if visit_state is ZoneVisitState.EXITING else None),
    )
    episode = (
        None
        if parking_state is None
        else make_episode(
            parking_state,
            observed_at=observed_at,
            parked_at_seconds=parked_at_seconds,
            zone_id=parking_zone_id,
            observation=parking_observation,
        )
    )
    return RuleContext(
        vehicle=vehicle,
        observation=context_observation or reliable,
        parking_motion_observation=parking_motion_observation or reliable,
        session_context=None,
        active_zone_visits=(visit,),
        parking_episode=episode,
        parking_assignment=None if episode is None else episode.assignment,
        placement_evidence=None,
        placement_evidence_source=None,
        blocking_relations=(),
        zones=ZoneRegistry(
            (
                make_zone(
                    zone_type=zone_type,
                    allowed_duration_seconds=allowed_duration_seconds,
                ),
            )
        ),
        bad_parking_min_primary_overlap_ratio=0.75,
        bad_parking_min_secondary_overlap_ratio=0.25,
        out_of_zone_min_spot_overlap_ratio=0.50,
        observed_at=observed_at,
    )


def only_signal(context: RuleContext):
    signals = evaluate(context)
    assert len(signals) == 1
    return signals[0]


def test_parking_duration_below_allowed_duration_is_not_matched() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=600.0,
            parked_at_seconds=540.1,
        )
    )

    assert signal.key == IncidentKey.for_zone_visit(
        ZoneVisitId(UUID(int=1)),
        "EV_OVERSTAY",
    )
    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False
    assert signal.evidence["parkedDurationSeconds"] == pytest.approx(59.9)


def test_parking_duration_at_allowed_duration_is_matched_and_confirmable() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=600.0,
            parked_at_seconds=540.0,
        )
    )

    assert signal.value is IncidentSignalValue.MATCHED
    assert signal.confirmable is True
    assert signal.evidence["parkedAt"] == (
        T0 + timedelta(seconds=540.0)
    ).isoformat()


def test_zone_visit_time_before_parking_does_not_count_toward_overstay() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=900.0,
            trusted_occupancy_seconds=900.0,
            parked_at_seconds=855.0,
            allowed_duration_seconds=75.0,
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False
    assert signal.evidence["parkedDurationSeconds"] == 45.0


def test_elapsed_wall_clock_after_parked_at_counts_toward_overstay() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=90.0,
            trusted_occupancy_seconds=45.0,
            parked_at_seconds=0.0,
            allowed_duration_seconds=75.0,
        )
    )

    assert signal.value is IncidentSignalValue.MATCHED
    assert signal.confirmable is True
    assert signal.evidence["parkedDurationSeconds"] == 90.0


def test_missing_allowed_duration_policy_is_unknown() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=24 * 60 * 60,
            trusted_occupancy_seconds=24 * 60 * 60,
            parked_at_seconds=0.0,
            allowed_duration_seconds=None,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


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
def test_unreliable_current_observation_pauses_as_unknown(
    context_observation: ObservationStatus | None,
    vehicle_observation: ObservationStatus | None,
    visit_observation: ObservationStatus | None,
    parking_motion_observation: ObservationStatus | None,
) -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=90.0,
            trusted_occupancy_seconds=90.0,
            context_observation=context_observation,
            vehicle_observation=vehicle_observation,
            visit_observation=visit_observation,
            parking_motion_observation=parking_motion_observation,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False


def test_non_ev_zone_produces_no_overstay_signal() -> None:
    assert evaluate(
        make_context(
            wall_clock_seconds=90.0,
            trusted_occupancy_seconds=90.0,
            zone_type=ZoneType.GENERAL,
            allowed_duration_seconds=None,
        )
    ) == ()


@pytest.mark.parametrize("parking_state", [None, ParkingState.STOP_PENDING])
def test_overstay_waits_for_confirmed_parking(
    parking_state: ParkingState | None,
) -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=600.0,
            parking_state=parking_state,
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False
    assert signal.evidence["reason"] == (
        "PARKING_NOT_CONFIRMED_IN_VISITED_ZONE"
    )


def test_parked_assignment_must_match_the_ev_visit_zone() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=600.0,
            parking_zone_id=2,
        )
    )

    assert signal.value is IncidentSignalValue.NOT_MATCHED
    assert signal.confirmable is False
    assert signal.evidence["parkingAssignmentZoneId"] == ZoneId(2)


def test_move_pending_pauses_an_existing_overstay() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=600.0,
            parking_state=ParkingState.MOVE_PENDING,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False
    assert signal.evidence["reason"] == "MOVEMENT_CONFIRMATION_PENDING"


def test_unreliable_parked_episode_pauses_as_unknown() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=600.0,
            trusted_occupancy_seconds=600.0,
            parking_observation=unknown(),
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False
    assert signal.evidence["reason"] == (
        "PARKING_EPISODE_OBSERVATION_UNAVAILABLE"
    )


def test_parked_at_after_observed_at_is_unknown() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=10.0,
            parked_at_seconds=11.0,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False
    assert signal.evidence["reason"] == "PARKED_AT_AFTER_OBSERVED_AT"


def test_visit_that_is_not_confirmed_inside_is_unknown() -> None:
    signal = only_signal(
        make_context(
            wall_clock_seconds=90.0,
            trusted_occupancy_seconds=90.0,
            visit_state=ZoneVisitState.EXITING,
        )
    )

    assert signal.value is IncidentSignalValue.UNKNOWN
    assert signal.confirmable is False

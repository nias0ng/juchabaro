"""불량 주차 계열의 독립 술어와 PARKED 확정 조건을 검증한다."""

from datetime import datetime, timezone
from uuid import UUID

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
from src.parking.rules.bad_parking import evaluate
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


def observed() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=T0,
    )


def unknown() -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.PARTIAL_FRAME,
        last_reliable_observed_at=T0,
    )


def make_assignment(
    state: AssignmentState,
    *,
    confidence: float = 0.9,
) -> ParkingAssignment:
    return ParkingAssignment(
        state=state,
        representative_footprint=SQUARE,
        confidence=confidence,
        last_stable_at=T0,
        zone_id=(ZoneId(1) if state is AssignmentState.ASSIGNED else None),
        unassigned_reason=(None if state is AssignmentState.ASSIGNED else state.value),
    )


def make_episode(
    state: ParkingState,
    *,
    assignment: ParkingAssignment | None = None,
    observation: ObservationStatus | None = None,
) -> ParkingEpisode:
    was_parked = state in {ParkingState.PARKED, ParkingState.MOVE_PENDING}
    durable_assignment = assignment or (
        make_assignment(AssignmentState.ASSIGNED) if was_parked else None
    )
    return ParkingEpisode(
        episode_id=ParkingEpisodeId(UUID(int=10)),
        physical_vehicle_id=CAR,
        state=state,
        observation=observation or observed(),
        stationary_trusted_seconds=10.0,
        movement_trusted_seconds=0.0,
        parking_confirmation_seconds=10.0,
        movement_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=1.0,
        last_signal=MotionSignal.STATIONARY,
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T0,
        assignment=durable_assignment,
        parked_at=(T0 if was_parked else None),
        movement_candidate_at=(T0 if state is ParkingState.MOVE_PENDING else None),
    )


def make_zone(zone_id: int, zone_type: ZoneType) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=SQUARE,
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="calibration-v1",
    )


def make_aisle_visit(*, observation: ObservationStatus | None = None) -> ZoneVisit:
    return ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=20)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(2),
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


def make_context(
    *,
    parking_assignment: ParkingAssignment | None,
    episode_state: ParkingState | None = ParkingState.PARKED,
    episode_assignment: ParkingAssignment | None = None,
    aisle_visit: ZoneVisit | None = None,
    context_observation: ObservationStatus | None = None,
    episode_observation: ObservationStatus | None = None,
) -> RuleContext:
    status = context_observation or observed()
    vehicle = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.95,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="camera-1",
        observation=status,
    )
    zones = (
        make_zone(1, ZoneType.GENERAL),
        make_zone(2, ZoneType.AISLE),
    )
    return RuleContext(
        vehicle=vehicle,
        observation=status,
        session_context=None,
        active_zone_visits=(() if aisle_visit is None else (aisle_visit,)),
        parking_episode=(
            None
            if episode_state is None
            else make_episode(
                episode_state,
                assignment=episode_assignment,
                observation=episode_observation,
            )
        ),
        parking_assignment=parking_assignment,
        blocking_relations=(),
        zones=ZoneRegistry(zones),
        bad_parking_min_primary_overlap_ratio=0.75,
        observed_at=T0,
    )


def signals_by_rule(context: RuleContext):
    signals = evaluate(context)
    assert {signal.key.rule_code for signal in signals} == {
        "BAD_PARKING",
        "OUT_OF_ZONE",
        "AISLE_BLOCK",
    }
    for signal in signals:
        assert signal.key == IncidentKey.for_physical_vehicle(
            CAR,
            signal.key.rule_code,
        )
    return {signal.key.rule_code: signal for signal in signals}


def test_assigned_parked_vehicle_matches_none_of_the_three_predicates() -> None:
    signals = signals_by_rule(
        make_context(parking_assignment=make_assignment(AssignmentState.ASSIGNED))
    )

    assert all(
        signal.value is IncidentSignalValue.NOT_MATCHED
        for signal in signals.values()
    )


def test_assigned_vehicle_below_primary_overlap_matches_bad_parking() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(
                AssignmentState.ASSIGNED,
                confidence=0.60,
            )
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["BAD_PARKING"].confirmable is True
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED
    assert signals["BAD_PARKING"].evidence["assignmentConfidence"] == 0.60
    assert (
        signals["BAD_PARKING"].evidence["badParkingMinPrimaryOverlapRatio"]
        == 0.75
    )


def test_primary_overlap_boundary_is_normal_parking() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(
                AssignmentState.ASSIGNED,
                confidence=0.75,
            )
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.NOT_MATCHED
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED


def test_ambiguous_assignment_matches_only_bad_parking() -> None:
    signals = signals_by_rule(
        make_context(parking_assignment=make_assignment(AssignmentState.AMBIGUOUS))
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["BAD_PARKING"].confirmable is True
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.NOT_MATCHED


def test_unassigned_location_matches_only_out_of_zone() -> None:
    signals = signals_by_rule(
        make_context(parking_assignment=make_assignment(AssignmentState.UNASSIGNED))
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.NOT_MATCHED
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.MATCHED
    assert signals["OUT_OF_ZONE"].confirmable is True
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.NOT_MATCHED


def test_bad_parking_and_aisle_block_can_match_independently_together() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(AssignmentState.AMBIGUOUS),
            aisle_visit=make_aisle_visit(),
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.MATCHED
    assert signals["BAD_PARKING"].confirmable is True
    assert signals["AISLE_BLOCK"].confirmable is True
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED


def test_latest_ephemeral_assignment_wins_over_episode_snapshot() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(AssignmentState.AMBIGUOUS),
            episode_assignment=make_assignment(AssignmentState.ASSIGNED),
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED


def test_matching_predicate_is_not_confirmable_before_parked() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(AssignmentState.AMBIGUOUS),
            episode_state=None,
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["BAD_PARKING"].confirmable is False


def test_move_pending_pauses_all_three_predicates_as_unknown() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(AssignmentState.AMBIGUOUS),
            episode_state=ParkingState.MOVE_PENDING,
            aisle_visit=make_aisle_visit(),
        )
    )

    assert all(
        signal.value is IncidentSignalValue.UNKNOWN
        and signal.confirmable is False
        for signal in signals.values()
    )


def test_unknown_parking_motion_dependency_pauses_all_three_predicates() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(AssignmentState.ASSIGNED),
            episode_observation=unknown(),
        )
    )

    assert all(
        signal.value is IncidentSignalValue.UNKNOWN
        and signal.confirmable is False
        and signal.evidence["reason"]
        == "PARKING_MOTION_DEPENDENCY_UNAVAILABLE"
        for signal in signals.values()
    )


def test_missing_assignment_only_makes_assignment_predicates_unknown() -> None:
    signals = signals_by_rule(make_context(parking_assignment=None))

    assert signals["BAD_PARKING"].value is IncidentSignalValue.UNKNOWN
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.UNKNOWN
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.NOT_MATCHED


def test_unknown_aisle_observation_does_not_hide_assignment_results() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(AssignmentState.AMBIGUOUS),
            aisle_visit=make_aisle_visit(observation=unknown()),
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.UNKNOWN


def test_unknown_frame_observation_pauses_all_three_predicates() -> None:
    signals = signals_by_rule(
        make_context(
            parking_assignment=make_assignment(AssignmentState.AMBIGUOUS),
            aisle_visit=make_aisle_visit(),
            context_observation=unknown(),
        )
    )

    assert all(
        signal.value is IncidentSignalValue.UNKNOWN
        and signal.confirmable is False
        for signal in signals.values()
    )

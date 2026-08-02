"""새 tracking·session 계약을 사용하는 ParkingPipeline 관통 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.models import (
    IncidentState,
    IncidentTransitionType,
    ParkingState,
    ParkingTransitionType,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisitState,
)
from src.parking.parking_episode_tracker import (
    MOVEMENT_CONFIRMED,
    InMemoryParkingEpisodeTracker,
)
from src.parking.pipeline import ParkingPipeline
from src.parking.rules.bad_parking import BAD_PARKING
from src.parking.rules.ev_overstay import EV_OVERSTAY
from src.parking.rules.restricted_zone import (
    DISABLED_ZONE_UNAUTHORIZED,
    EV_ZONE_UNAUTHORIZED,
)
from src.parking.zone_registry import ZoneRegistry
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.session.models import EntryAttemptId, SessionContext
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleAbsenceProgress,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    TrackingBatch,
    VehicleId,
)


T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
VERSION = ZoneDefinitionVersion(7)
CALIBRATION = "cam-1-v1"
SESSION = ParkingSessionId(101)
ATTEMPT = EntryAttemptId(UUID(int=102))

INSIDE = BoundingBox(0.15, 0.15, 0.25, 0.25)
OUTSIDE = BoundingBox(0.70, 0.70, 0.80, 0.80)
AMBIGUOUS = BoundingBox(0.20, 0.12, 0.30, 0.28)
ASSIGNED_FIRST = BoundingBox(0.11, 0.12, 0.19, 0.28)

SQUARE = ((0.10, 0.10), (0.40, 0.10), (0.40, 0.40), (0.10, 0.40))
FIRST_SPOT = ((0.10, 0.10), (0.30, 0.10), (0.30, 0.30), (0.10, 0.30))
SECOND_SPOT = ((0.20, 0.10), (0.40, 0.10), (0.40, 0.30), (0.20, 0.30))


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def zone(
    zone_id: int,
    zone_type: ZoneType,
    polygon=SQUARE,
    *,
    allowed_duration_seconds: float | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=polygon,
        zone_definition_version=VERSION,
        calibration_reference=CALIBRATION,
        allowed_duration_seconds=allowed_duration_seconds,
        charger_class="FAST" if zone_type is ZoneType.EV_CHARGING else None,
    )


DISABLED_ZONE = zone(1, ZoneType.DISABLED)
EV_ZONE = zone(
    2,
    ZoneType.EV_CHARGING,
    allowed_duration_seconds=60.0,
)
GENERAL_A = zone(3, ZoneType.GENERAL, FIRST_SPOT)
GENERAL_B = zone(4, ZoneType.GENERAL, SECOND_SPOT)

UNAUTHORIZED = SessionContext(
    parking_session_id=SESSION,
    vehicle_id=VehicleId(201),
    is_electric=False,
    is_disabled_vehicle=False,
)
DISABLED_QUALIFIED = SessionContext(
    parking_session_id=SESSION,
    vehicle_id=VehicleId(201),
    is_electric=False,
    is_disabled_vehicle=True,
)
ELECTRIC = SessionContext(
    parking_session_id=SESSION,
    vehicle_id=VehicleId(201),
    is_electric=True,
    is_disabled_vehicle=False,
)


def observed(seconds: float) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at(seconds),
    )


def snapshot(
    seconds: float,
    *,
    bbox: BoundingBox = INSIDE,
    motion: MotionSignal = MotionSignal.STATIONARY,
    segment: int = 1,
) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(segment),
        bbox=bbox,
        confidence=0.9,
        motion_signal=motion,
        observed_at=at(seconds),
        camera_id="cam-1",
        observation=observed(seconds),
    )


def batch(
    seconds: float,
    *vehicles: PhysicalVehicleSnapshot,
    ended_segments: tuple[TrackSegmentId, ...] = (),
    unobserved: tuple[PhysicalVehicleId, ...] = (),
    confirmed_absent: tuple[PhysicalVehicleId, ...] = (),
    batch_observation: ObservationStatus | None = None,
    full_area_observed: bool = True,
) -> TrackingBatch:
    confirmed = set(confirmed_absent)
    return TrackingBatch(
        camera_id="cam-1",
        frame_id=int(seconds),
        observed_at=at(seconds),
        vehicles=tuple(vehicles),
        ended_track_segment_ids=ended_segments,
        unobserved_physical_vehicle_ids=unobserved,
        absence_progress=tuple(
            PhysicalVehicleAbsenceProgress(
                physical_vehicle_id=vehicle_id,
                trusted_seconds=10.0 if vehicle_id in confirmed else 0.0,
                confirmed_at=at(seconds) if vehicle_id in confirmed else None,
            )
            for vehicle_id in unobserved
        ),
        observation=batch_observation or observed(seconds),
        full_area_observed=full_area_observed,
        all_detections_tracked=True,
        not_present_confirmed_vehicle_ids=confirmed_absent,
    )


def make_pipeline(
    zones: tuple[ZoneDefinition, ...],
    *,
    entry_seconds: float = 1.0,
    exit_seconds: float = 1.0,
    parking_seconds: float = 600.0,
    movement_seconds: float = 1.0,
    trusted_sample_max_gap_seconds: float = 300.0,
    incident_confirm_seconds: float = 0.0,
    incident_clear_seconds: float = 0.0,
    zone_overlap_ratio: float = 0.5,
    assignment_overlap_ratio: float = 0.5,
    ambiguous_margin: float = 0.05,
):
    registry = ZoneRegistry(zones)
    visit_tracker = InMemoryZoneVisitTracker(
        zone_definition_version=registry.zone_definition_version,
        entry_confirm_seconds=entry_seconds,
        exit_confirm_seconds=exit_seconds,
        trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
    )
    episode_tracker = InMemoryParkingEpisodeTracker(
        parking_confirmation_seconds=parking_seconds,
        movement_confirmation_seconds=movement_seconds,
        trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
    )
    reducer = InMemoryIncidentReducer(
        trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
        confirm_duration_seconds=incident_confirm_seconds,
        clear_duration_seconds=incident_clear_seconds,
    )
    pipeline = ParkingPipeline(
        zones=registry,
        zone_visit_tracker=visit_tracker,
        parking_episode_tracker=episode_tracker,
        incident_reducer=reducer,
        min_overlap_ratio=zone_overlap_ratio,
        assignment_min_overlap_ratio=assignment_overlap_ratio,
        assignment_ambiguous_margin=ambiguous_margin,
    )
    return pipeline, visit_tracker, episode_tracker, reducer


def transitions_for(result, rule_code: str):
    return tuple(
        transition
        for transition in result.incident_transitions
        if transition.incident.key.rule_code == rule_code
    )


def updates_for(result, rule_code: str):
    return tuple(
        incident
        for incident in result.incident_updates
        if incident.key.rule_code == rule_code
    )


def test_runtime_checkpoint_restores_all_parking_owners() -> None:
    pipeline, visit_tracker, episode_tracker, reducer = make_pipeline(
        (DISABLED_ZONE,),
        entry_seconds=0.0,
    )
    checkpoint = pipeline.checkpoint_state()

    pipeline.process(
        batch(0, snapshot(0)),
        session_contexts={CAR: UNAUTHORIZED},
    )
    assert visit_tracker.active_visits(CAR)
    assert episode_tracker.active_episode(CAR) is not None
    assert reducer.active_snapshot()

    pipeline.restore_state(checkpoint)

    assert visit_tracker.active_visits(CAR) == ()
    assert episode_tracker.active_episode(CAR) is None
    assert reducer.active_snapshot() == ()


def test_authoritative_context_opens_and_zone_exit_resolves_restricted_incident() -> None:
    pipeline, _, _, _ = make_pipeline((DISABLED_ZONE,))
    contexts = {CAR: UNAUTHORIZED}

    entering = pipeline.process(batch(0, snapshot(0)), session_contexts=contexts)
    assert transitions_for(entering, DISABLED_ZONE_UNAUTHORIZED) == ()

    opened_result = pipeline.process(batch(1, snapshot(1)), session_contexts=contexts)
    opened = transitions_for(opened_result, DISABLED_ZONE_UNAUTHORIZED)
    assert [item.transition_type for item in opened] == [IncidentTransitionType.OPEN]
    assert updates_for(opened_result, DISABLED_ZONE_UNAUTHORIZED) == (
        opened[0].incident,
    )

    exiting = pipeline.process(
        batch(2, snapshot(2, bbox=OUTSIDE)),
        session_contexts=contexts,
    )
    assert transitions_for(exiting, DISABLED_ZONE_UNAUTHORIZED) == ()

    ended = pipeline.process(
        batch(3, snapshot(3, bbox=OUTSIDE)),
        session_contexts=contexts,
    )
    resolved = transitions_for(ended, DISABLED_ZONE_UNAUTHORIZED)
    assert [item.transition_type for item in resolved] == [
        IncidentTransitionType.RESOLVE
    ]
    assert resolved[0].incident.incident_id == opened[0].incident.incident_id
    assert any(
        visit.state is ZoneVisitState.ENDED for visit in ended.zone_visit_updates
    )


def test_resolve_is_not_repeated_and_reentry_gets_a_new_incident() -> None:
    """종료된 visit은 한 번만 해소되고 재진입은 새 continuity를 만든다."""

    pipeline, _, _, reducer = make_pipeline(
        (DISABLED_ZONE,),
        entry_seconds=0.0,
        exit_seconds=0.0,
    )
    contexts = {CAR: UNAUTHORIZED}

    first_open = transitions_for(
        pipeline.process(batch(0, snapshot(0)), session_contexts=contexts),
        DISABLED_ZONE_UNAUTHORIZED,
    )[0]
    first_resolve = transitions_for(
        pipeline.process(
            batch(1, snapshot(1, bbox=OUTSIDE)),
            session_contexts=contexts,
        ),
        DISABLED_ZONE_UNAUTHORIZED,
    )[0]
    assert first_resolve.incident.incident_id == first_open.incident.incident_id

    still_outside = pipeline.process(
        batch(2, snapshot(2, bbox=OUTSIDE)),
        session_contexts=contexts,
    )
    assert transitions_for(still_outside, DISABLED_ZONE_UNAUTHORIZED) == ()

    second_open = transitions_for(
        pipeline.process(batch(3, snapshot(3)), session_contexts=contexts),
        DISABLED_ZONE_UNAUTHORIZED,
    )[0]
    assert second_open.incident.incident_id != first_open.incident.incident_id
    restricted_states = [
        incident.state
        for incident in reducer.snapshot()
        if incident.key.rule_code == DISABLED_ZONE_UNAUTHORIZED
    ]
    assert restricted_states == [IncidentState.RESOLVED, IncidentState.OPEN]


def test_context_is_supplied_outside_snapshot_and_may_arrive_late() -> None:
    pipeline, _, _, _ = make_pipeline((DISABLED_ZONE,), entry_seconds=0.0)

    without_context = pipeline.process(batch(0, snapshot(0)))
    assert transitions_for(without_context, DISABLED_ZONE_UNAUTHORIZED) == ()
    assert not hasattr(snapshot(0), "context")

    with_context = pipeline.process(
        batch(1, snapshot(1)),
        session_contexts={CAR: UNAUTHORIZED},
    )
    opened = transitions_for(with_context, DISABLED_ZONE_UNAUTHORIZED)
    assert [item.transition_type for item in opened] == [IncidentTransitionType.OPEN]
    assert opened[0].incident.parking_session_id == SESSION


def test_entry_attempt_can_correlate_incident_without_session_context() -> None:
    pipeline, _, _, _ = make_pipeline(
        (GENERAL_A, GENERAL_B),
        entry_seconds=0.0,
        parking_seconds=1.0,
    )
    attempts = {CAR: ATTEMPT}
    pipeline.process(
        batch(0, snapshot(0, bbox=AMBIGUOUS)),
        entry_attempt_ids=attempts,
    )

    result = pipeline.process(
        batch(1, snapshot(1, bbox=AMBIGUOUS)),
        entry_attempt_ids=attempts,
    )

    opened = transitions_for(result, BAD_PARKING)
    assert [item.transition_type for item in opened] == [IncidentTransitionType.OPEN]
    assert opened[0].incident.entry_attempt_id == ATTEMPT
    assert opened[0].incident.parking_session_id is None
    assert result.parking_transitions == ()


def test_qualified_vehicle_does_not_open_restricted_incident() -> None:
    pipeline, _, _, _ = make_pipeline((DISABLED_ZONE,), entry_seconds=0.0)

    for second in (0.0, 1.0):
        result = pipeline.process(
            batch(second, snapshot(second)),
            session_contexts={CAR: DISABLED_QUALIFIED},
        )
        assert transitions_for(result, DISABLED_ZONE_UNAUTHORIZED) == ()


def test_ev_charging_restricted_and_overstay_rules_are_both_wired() -> None:
    unauthorized_pipeline, _, _, _ = make_pipeline((EV_ZONE,), entry_seconds=0.0)
    unauthorized = unauthorized_pipeline.process(
        batch(0, snapshot(0)),
        session_contexts={CAR: UNAUTHORIZED},
    )
    assert [
        item.transition_type
        for item in transitions_for(unauthorized, EV_ZONE_UNAUTHORIZED)
    ] == [IncidentTransitionType.OPEN]

    electric_pipeline, _, _, _ = make_pipeline((EV_ZONE,), entry_seconds=0.0)
    electric_pipeline.process(batch(0, snapshot(0)), session_contexts={CAR: ELECTRIC})
    before_limit = electric_pipeline.process(
        batch(59, snapshot(59)),
        session_contexts={CAR: ELECTRIC},
    )
    assert transitions_for(before_limit, EV_OVERSTAY) == ()

    at_limit = electric_pipeline.process(
        batch(60, snapshot(60)),
        session_contexts={CAR: ELECTRIC},
    )
    assert [item.transition_type for item in transitions_for(at_limit, EV_OVERSTAY)] == [
        IncidentTransitionType.OPEN
    ]
    assert transitions_for(at_limit, EV_ZONE_UNAUTHORIZED) == ()


def test_ended_track_segment_and_track_loss_pause_without_terminal_transition() -> None:
    pipeline, visit_tracker, episode_tracker, _ = make_pipeline(
        (DISABLED_ZONE,),
        entry_seconds=0.0,
    )
    opened_result = pipeline.process(
        batch(0, snapshot(0)),
        session_contexts={CAR: UNAUTHORIZED},
    )
    assert transitions_for(opened_result, DISABLED_ZONE_UNAUTHORIZED)

    paused = pipeline.process(
        batch(
            10,
            ended_segments=(TrackSegmentId(1),),
            unobserved=(CAR,),
        )
    )

    assert paused.incident_transitions == ()
    assert [visit.state for visit in paused.zone_visit_updates] == [
        ZoneVisitState.INSIDE
    ]
    assert [episode.state for episode in paused.parking_episode_updates] == [
        ParkingState.STOP_PENDING
    ]
    restricted_updates = updates_for(paused, DISABLED_ZONE_UNAUTHORIZED)
    assert [incident.state for incident in restricted_updates] == [IncidentState.OPEN]
    assert restricted_updates[0].observation.state is ObservationState.UNKNOWN
    assert restricted_updates[0].observation.last_reliable_observed_at == at(0)
    assert visit_tracker.active_visits(CAR)[0].state is ZoneVisitState.INSIDE
    assert (
        visit_tracker.active_visits(CAR)[0].observation.last_reliable_observed_at
        == at(0)
    )
    active_episode = episode_tracker.active_episode(CAR)
    assert active_episode.state is ParkingState.STOP_PENDING
    assert active_episode.observation.last_reliable_observed_at == at(0)


def test_unobserved_vehicle_preserves_unreliable_batch_observation_reason() -> None:
    """Partial frame이나 pipeline 장애를 개별 track 소실로 바꾸지 않는다."""

    for state, reason in (
        (ObservationState.DEGRADED, ObservationReason.PARTIAL_FRAME),
        (ObservationState.UNKNOWN, ObservationReason.PIPELINE_STALLED),
    ):
        pipeline, _, _, _ = make_pipeline(
            (DISABLED_ZONE,),
            entry_seconds=0.0,
        )
        pipeline.process(
            batch(0, snapshot(0)),
            session_contexts={CAR: UNAUTHORIZED},
        )
        upstream_observation = ObservationStatus(
            state=state,
            reason=reason,
            last_reliable_observed_at=at(0),
        )

        paused = pipeline.process(
            batch(
                10,
                unobserved=(CAR,),
                batch_observation=upstream_observation,
                full_area_observed=False,
            )
        )

        assert paused.zone_visit_updates[0].observation == upstream_observation
        assert paused.parking_episode_updates[0].observation == upstream_observation
        restricted = updates_for(paused, DISABLED_ZONE_UNAUTHORIZED)
        assert restricted[0].observation == upstream_observation


def test_unobserved_gap_does_not_add_wall_clock_to_parking_timer() -> None:
    pipeline, _, _, _ = make_pipeline(
        (GENERAL_A,),
        entry_seconds=0.0,
        parking_seconds=5.0,
    )
    pipeline.process(batch(0, snapshot(0)))
    pipeline.process(batch(100, unobserved=(CAR,)))

    resumed = pipeline.process(batch(101, snapshot(101)))
    assert resumed.parking_episode_updates[-1].state is ParkingState.STOP_PENDING
    assert resumed.parking_episode_updates[-1].stationary_trusted_seconds == 0.0

    parked = pipeline.process(batch(106, snapshot(106)))
    assert parked.parking_episode_updates[-1].state is ParkingState.PARKED
    assert parked.parking_episode_updates[-1].stationary_trusted_seconds == 5.0


def test_confirmed_absence_requires_explicit_physical_exit() -> None:
    pipeline, visit_tracker, episode_tracker, _ = make_pipeline(
        (DISABLED_ZONE,),
        entry_seconds=0.0,
        parking_seconds=1.0,
    )
    contexts = {CAR: UNAUTHORIZED}
    pipeline.process(batch(0, snapshot(0)), session_contexts=contexts)
    pipeline.process(batch(1, snapshot(1)), session_contexts=contexts)

    confirmed_batch = pipeline.process(
        batch(
            2,
            unobserved=(CAR,),
            confirmed_absent=(CAR,),
        )
    )
    assert confirmed_batch.incident_transitions == ()
    assert visit_tracker.active_visits(CAR)[0].state is ZoneVisitState.INSIDE
    assert episode_tracker.active_episode(CAR).state is ParkingState.PARKED

    exit_plan = pipeline.physical_exit(
        physical_vehicle_id=CAR,
        observed_at=at(2),
        incident_termination_reason="SESSION_EXITED",
    )
    assert [visit.state for visit in exit_plan.zone_visit_updates] == [
        ZoneVisitState.ENDED
    ]
    assert [episode.state for episode in exit_plan.parking_episode_updates] == [
        ParkingState.ENDED
    ]
    resolved = transitions_for(exit_plan, DISABLED_ZONE_UNAUTHORIZED)
    assert [item.transition_type for item in resolved] == [
        IncidentTransitionType.RESOLVE
    ]
    assert resolved[0].incident.termination_reason == "SESSION_EXITED"
    assert visit_tracker.active_visits(CAR) == ()
    assert episode_tracker.active_episode(CAR) is None


def test_movement_ended_episode_rechecks_latest_geometry_before_resolving() -> None:
    pipeline, _, _, _ = make_pipeline(
        (GENERAL_A, GENERAL_B),
        entry_seconds=0.0,
        exit_seconds=0.0,
        parking_seconds=1.0,
        movement_seconds=1.0,
    )

    contexts = {CAR: UNAUTHORIZED}
    pipeline.process(
        batch(0, snapshot(0, bbox=AMBIGUOUS)),
        session_contexts=contexts,
    )
    parked = pipeline.process(
        batch(1, snapshot(1, bbox=AMBIGUOUS)),
        session_contexts=contexts,
    )
    assert [item.transition_type for item in parked.parking_transitions] == [
        ParkingTransitionType.PARKED
    ]
    opened = transitions_for(parked, BAD_PARKING)
    assert [item.transition_type for item in opened] == [IncidentTransitionType.OPEN]

    pending = pipeline.process(
        batch(2, snapshot(2, bbox=AMBIGUOUS, motion=MotionSignal.MOVING)),
        session_contexts=contexts,
    )
    assert pending.parking_episode_updates[-1].state is ParkingState.MOVE_PENDING
    assert transitions_for(pending, BAD_PARKING) == ()

    movement_ended = pipeline.process(
        batch(3, snapshot(3, bbox=AMBIGUOUS, motion=MotionSignal.MOVING)),
        session_contexts=contexts,
    )
    assert movement_ended.parking_episode_updates[-1].state is ParkingState.ENDED
    assert (
        movement_ended.parking_episode_updates[-1].termination_reason
        == MOVEMENT_CONFIRMED
    )
    assert [
        item.transition_type for item in movement_ended.parking_transitions
    ] == [ParkingTransitionType.UNPARKED]
    assert transitions_for(movement_ended, BAD_PARKING) == ()
    assert updates_for(movement_ended, BAD_PARKING)[-1].state is IncidentState.OPEN

    geometry_cleared = pipeline.process(
        batch(4, snapshot(4, bbox=ASSIGNED_FIRST, motion=MotionSignal.MOVING)),
        session_contexts=contexts,
    )
    resolved = transitions_for(geometry_cleared, BAD_PARKING)
    assert [item.transition_type for item in resolved] == [
        IncidentTransitionType.RESOLVE
    ]
    assert resolved[0].incident.incident_id == opened[0].incident.incident_id


def test_late_binding_on_movement_confirmation_materializes_both_revisions() -> None:
    pipeline, _, _, _ = make_pipeline(
        (GENERAL_A,),
        entry_seconds=0.0,
        parking_seconds=1.0,
        movement_seconds=1.0,
    )
    pipeline.process(batch(0, snapshot(0)))
    local_parked = pipeline.process(batch(1, snapshot(1)))
    pipeline.process(
        batch(2, snapshot(2, motion=MotionSignal.MOVING))
    )

    materialized = pipeline.process(
        batch(3, snapshot(3, motion=MotionSignal.MOVING)),
        session_contexts={CAR: UNAUTHORIZED},
    )

    assert local_parked.parking_episode_updates[-1].publication_revision == 0
    assert [item.transition_type for item in materialized.parking_transitions] == [
        ParkingTransitionType.PARKED,
        ParkingTransitionType.UNPARKED,
    ]
    assert [item.publication_revision for item in materialized.parking_transitions] == [
        1,
        2,
    ]
    assert materialized.parking_transitions[0].occurred_at == at(1)
    assert materialized.parking_transitions[1].occurred_at == at(3)


def test_local_only_incident_update_is_returned_without_publication() -> None:
    local_ev = zone(
        8,
        ZoneType.EV_CHARGING,
        allowed_duration_seconds=10.0,
    )
    pipeline, _, _, _ = make_pipeline((local_ev,), entry_seconds=0.0)
    pipeline.process(batch(0, snapshot(0)))

    local_open = pipeline.process(batch(10, snapshot(10)))
    assert transitions_for(local_open, EV_OVERSTAY) == ()
    updates = updates_for(local_open, EV_OVERSTAY)
    assert [incident.state for incident in updates] == [IncidentState.OPEN]
    assert updates[0].publication_revision == 0

    materialized = pipeline.process(
        batch(11, snapshot(11)),
        session_contexts={CAR: ELECTRIC},
    )
    published = transitions_for(materialized, EV_OVERSTAY)
    assert [item.transition_type for item in published] == [IncidentTransitionType.OPEN]
    assert published[0].incident.incident_id == updates[0].incident_id
    assert published[0].incident.publication_revision == 1


def test_blocking_relation_output_is_explicitly_empty() -> None:
    pipeline, _, _, _ = make_pipeline((GENERAL_A,), entry_seconds=0.0)

    result = pipeline.process(batch(0, snapshot(0)))

    assert result.blocking_relation_updates == ()


def test_zone_presence_and_assignment_thresholds_are_independent() -> None:
    half_overlap = BoundingBox(0.0, 0.12, 0.20, 0.28)
    pipeline, visit_tracker, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=1.0,
        zone_overlap_ratio=0.75,
        assignment_overlap_ratio=0.5,
    )

    pipeline.process(batch(0, snapshot(0, bbox=half_overlap)))
    parked = pipeline.process(batch(1, snapshot(1, bbox=half_overlap)))

    assert visit_tracker.active_visits(CAR) == ()
    assert parked.parking_episode_updates[-1].assignment.zone_id == GENERAL_A.zone_id

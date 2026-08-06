"""새 tracking·session 계약을 사용하는 ParkingPipeline 관통 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.diagnostics import DiagnosticEvent, DiagnosticEventType
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.blocking_relation_tracker import InMemoryBlockingRelationTracker
from src.parking.egress_aisle_registry import EgressAisleRegistry
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.models import (
    AssignmentState,
    BlockingRelationState,
    EgressAisleDefinition,
    EgressAisleDefinitionVersion,
    EgressAisleId,
    EntryExitRole,
    IncidentSignalValue,
    IncidentRuleTiming,
    IncidentState,
    IncidentTransitionType,
    ParkingState,
    ParkingTransitionType,
    PlacementEvidenceSource,
    PresenceSignal,
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
from src.parking.rules.bad_parking import BAD_PARKING, OUT_OF_ZONE
from src.parking.rules.double_parking import DOUBLE_PARKING
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
OTHER_CAR = PhysicalVehicleId(UUID(int=2))
VERSION = ZoneDefinitionVersion(7)
CALIBRATION = "cam-1-v1"
SESSION = ParkingSessionId(101)
ATTEMPT = EntryAttemptId(UUID(int=102))


class RecordingDiagnosticsSink:
    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)

INSIDE = BoundingBox(0.15, 0.15, 0.25, 0.25)
OUTSIDE = BoundingBox(0.70, 0.70, 0.80, 0.80)
AMBIGUOUS = BoundingBox(0.20, 0.12, 0.40, 0.28)
TWO_SPOT_51_49 = BoundingBox(0.198, 0.12, 0.398, 0.28)
TWO_SPOT_70_30 = BoundingBox(0.16, 0.12, 0.36, 0.28)
ASSIGNED_FIRST = BoundingBox(0.11, 0.12, 0.19, 0.28)
PROTRUDING_FROM_FIRST = BoundingBox(0.18, 0.12, 0.38, 0.28)

SQUARE = ((0.10, 0.10), (0.40, 0.10), (0.40, 0.40), (0.10, 0.40))
FIRST_SPOT = ((0.10, 0.10), (0.30, 0.10), (0.30, 0.30), (0.10, 0.30))
SECOND_SPOT = ((0.30, 0.10), (0.50, 0.10), (0.50, 0.30), (0.30, 0.30))
EXIT_SPOT = ((0.60, 0.10), (0.80, 0.10), (0.80, 0.30), (0.60, 0.30))
AISLE_STRIP = ((0.10, 0.50), (0.90, 0.50), (0.90, 0.95), (0.10, 0.95))
# 판정은 bbox 폴리곤 겹침이 아니라 bbox 중심의 기준선 기준 부호로 한다
# (571 finding 1). 기준선은 AISLE_STRIP 중심(0.5, 0.725)에서
# EXIT_SPOT 중심(0.7, 0.2)으로 향하는 단위벡터 (0.356, -0.934)가 정의한다.
# IN_EXIT_OUTWARD의 중심 (0.76, 0.13)은 이 축에 투영하면 EXIT_SPOT
# 중심보다 +0.0868만큼 외부 방향이고, IN_EXIT_INWARD의 중심 (0.64, 0.27)은
# -0.0868만큼 내부 방향이다 — 부호가 반대이므로 두 이름이 실제로 가리키는
# 쪽을 가른다. 두 bbox 모두 EXIT_SPOT 안에 완전히 포함되어 있어
# 존재 판정(overlap_ratio)에는 영향이 없다.
IN_EXIT_OUTWARD = BoundingBox(0.72, 0.10, 0.80, 0.16)
IN_EXIT_INWARD = BoundingBox(0.60, 0.24, 0.68, 0.30)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def zone(
    zone_id: int,
    zone_type: ZoneType,
    polygon=SQUARE,
    *,
    allowed_duration_seconds: float | None = None,
    egress_zone_ids: tuple[ZoneId, ...] = (),
    entry_exit_role: EntryExitRole | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=polygon,
        zone_definition_version=VERSION,
        calibration_reference=CALIBRATION,
        entry_exit_role=entry_exit_role,
        allowed_duration_seconds=allowed_duration_seconds,
        charger_class="FAST" if zone_type is ZoneType.EV_CHARGING else None,
        egress_zone_ids=egress_zone_ids,
    )


def egress(
    egress_zone_id: int,
    parking_zone_id: int,
    polygon,
) -> EgressAisleDefinition:
    return EgressAisleDefinition(
        egress_zone_id=EgressAisleId(egress_zone_id),
        parking_zone_id=ZoneId(parking_zone_id),
        polygon=polygon,
        egress_aisle_definition_version=EgressAisleDefinitionVersion(1),
        zone_definition_version=VERSION,
        calibration_reference=CALIBRATION,
    )


DISABLED_ZONE = zone(1, ZoneType.DISABLED)
EV_ZONE = zone(
    2,
    ZoneType.EV_CHARGING,
    allowed_duration_seconds=60.0,
)
GENERAL_A = zone(3, ZoneType.GENERAL, FIRST_SPOT)
GENERAL_B = zone(4, ZoneType.GENERAL, SECOND_SPOT)
EXIT_ZONE = zone(
    9,
    ZoneType.ENTRY_EXIT,
    EXIT_SPOT,
    entry_exit_role=EntryExitRole.EXIT,
)
AISLE_ZONE = zone(7, ZoneType.AISLE, AISLE_STRIP)
ENTRY_ZONE = zone(
    8,
    ZoneType.ENTRY_EXIT,
    EXIT_SPOT,
    entry_exit_role=EntryExitRole.ENTRY,
)

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


def degraded(*, last_reliable: float) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.DEGRADED,
        reason=ObservationReason.PARTIAL_FRAME,
        last_reliable_observed_at=at(last_reliable),
    )


def snapshot(
    seconds: float,
    *,
    vehicle: PhysicalVehicleId = CAR,
    bbox: BoundingBox = INSIDE,
    motion: MotionSignal = MotionSignal.STATIONARY,
    segment: int = 1,
    observation: ObservationStatus | None = None,
) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=vehicle,
        track_segment_id=TrackSegmentId(segment),
        bbox=bbox,
        confidence=0.9,
        motion_signal=motion,
        observed_at=at(seconds),
        camera_id="cam-1",
        observation=observation or observed(seconds),
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
    egress_areas: tuple[EgressAisleDefinition, ...] = (),
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
    bad_parking_overlap_ratio: float = 0.75,
    bad_parking_secondary_overlap_ratio: float = 0.25,
    out_of_zone_overlap_ratio: float = 0.50,
    blocking_confirm_seconds: float = 0.0,
    blocking_clear_seconds: float = 0.0,
    blocking_subject_overlap_ratio: float = 0.5,
    blocking_egress_coverage_ratio: float = 0.5,
    incident_rule_timings: tuple[IncidentRuleTiming, ...] = (),
    diagnostics_sink=None,
):
    registry = ZoneRegistry(zones)
    egress_registry = EgressAisleRegistry(
        egress_areas,
        egress_aisle_definition_version=EgressAisleDefinitionVersion(1),
        zone_definition_version=registry.zone_definition_version,
        calibration_reference=registry.calibration_reference,
        zones=registry,
    )
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
        rule_timings=incident_rule_timings,
    )
    relation_tracker = InMemoryBlockingRelationTracker(
        confirm_duration_seconds=blocking_confirm_seconds,
        clear_duration_seconds=blocking_clear_seconds,
        trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
    )
    pipeline = ParkingPipeline(
        zones=registry,
        egress_aisles=egress_registry,
        zone_visit_tracker=visit_tracker,
        parking_episode_tracker=episode_tracker,
        incident_reducer=reducer,
        blocking_relation_tracker=relation_tracker,
        min_overlap_ratio=zone_overlap_ratio,
        assignment_min_overlap_ratio=assignment_overlap_ratio,
        assignment_ambiguous_margin=ambiguous_margin,
        bad_parking_min_primary_overlap_ratio=bad_parking_overlap_ratio,
        bad_parking_min_secondary_overlap_ratio=(
            bad_parking_secondary_overlap_ratio
        ),
        out_of_zone_min_spot_overlap_ratio=out_of_zone_overlap_ratio,
        blocking_min_subject_overlap_ratio=blocking_subject_overlap_ratio,
        blocking_min_egress_coverage_ratio=blocking_egress_coverage_ratio,
        diagnostics_sink=diagnostics_sink,
    )
    return pipeline, visit_tracker, episode_tracker, reducer, relation_tracker


def test_parking_exit_and_incident_boundaries_emit_structured_diagnostics() -> None:
    diagnostics = RecordingDiagnosticsSink()
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE),
        parking_seconds=1.0,
        diagnostics_sink=diagnostics,
    )

    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(
        batch(1, snapshot(1, bbox=IN_EXIT_OUTWARD)),
        entry_attempt_ids={CAR: ATTEMPT},
    )
    assert pipeline.exit_zone_traversal_observed(
        CAR,
        observed_at=at(2),
        absence_trusted_seconds=30.0,
        absence_confirmation_seconds=30.0,
    )

    parking_events = [
        event
        for event in diagnostics.events
        if event.event_type
        is DiagnosticEventType.PARKING_ELIGIBILITY_EVALUATED
    ]
    assert parking_events[0].attributes["entryExitRole"] == "EXIT"
    assert parking_events[0].attributes["parkingState"] == "STOP_PENDING"
    exit_event = next(
        event
        for event in diagnostics.events
        if event.event_type is DiagnosticEventType.EXIT_TRAVERSAL_EVALUATED
    )
    assert exit_event.attributes["traversalObserved"] is True
    assert exit_event.attributes["absenceTrustedSeconds"] == 30.0


def test_incident_open_diagnostic_explains_null_zone_provenance() -> None:
    diagnostics = RecordingDiagnosticsSink()
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=1.0,
        diagnostics_sink=diagnostics,
    )

    pipeline.process(
        batch(0, snapshot(0, bbox=OUTSIDE)),
        entry_attempt_ids={CAR: ATTEMPT},
    )
    pipeline.process(
        batch(1, snapshot(1, bbox=OUTSIDE)),
        entry_attempt_ids={CAR: ATTEMPT},
    )

    event = next(
        event
        for event in diagnostics.events
        if event.event_type
        is DiagnosticEventType.INCIDENT_PROJECTION_EVALUATED
        and event.attributes["ruleCode"] == OUT_OF_ZONE
    )
    assert event.attributes["transitionType"] == "OPEN"
    assert event.attributes["zoneId"] is None
    assert event.attributes["zoneProvenance"] == "NONE_PHYSICAL_VEHICLE_SCOPE"


def test_pipeline_exports_rule_specific_timing_with_actual_rule_signal() -> None:
    bad_timing = IncidentRuleTiming(
        rule_code=BAD_PARKING,
        confirm_duration_seconds=2.0,
        clear_duration_seconds=3.0,
    )
    out_timing = IncidentRuleTiming(
        rule_code=OUT_OF_ZONE,
        confirm_duration_seconds=4.0,
        clear_duration_seconds=5.0,
    )
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, GENERAL_B),
        parking_seconds=1.0,
        incident_rule_timings=(bad_timing, out_timing),
    )

    result = pipeline.process(batch(0, snapshot(0, bbox=AMBIGUOUS)))
    diagnostics = {
        item.signal.key.rule_code: item
        for item in result.incident_signal_diagnostics
    }

    assert diagnostics[BAD_PARKING].signal.value is IncidentSignalValue.MATCHED
    assert diagnostics[BAD_PARKING].timing == bad_timing
    assert diagnostics[OUT_OF_ZONE].signal.value is (
        IncidentSignalValue.NOT_MATCHED
    )
    assert diagnostics[OUT_OF_ZONE].timing == out_timing
    candidate = updates_for(result, BAD_PARKING)[-1]
    assert candidate.confirm_duration_seconds == 2.0
    assert candidate.clear_duration_seconds == 3.0


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
    pipeline, visit_tracker, episode_tracker, reducer, _ = make_pipeline(
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


@pytest.mark.parametrize(
    ("parking_seconds", "sample_times", "expected_state"),
    (
        (10.0, (0.0,), ParkingState.STOP_PENDING),
        (1.0, (0.0, 1.0), ParkingState.PARKED),
    ),
)
def test_restore_active_rejects_assigned_episode_when_zone_is_missing(
    parking_seconds: float,
    sample_times: tuple[float, ...],
    expected_state: ParkingState,
) -> None:
    old_pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=parking_seconds,
    )
    result = None
    for seconds in sample_times:
        result = old_pipeline.process(
            batch(seconds, snapshot(seconds, bbox=ASSIGNED_FIRST))
        )
    assert result is not None
    episode = result.parking_episode_updates[-1]
    assert episode.state is expected_state
    assert episode.assignment is not None
    assert episode.assignment.zone_id == GENERAL_A.zone_id

    replacement_zone = ZoneDefinition(
        zone_id=ZoneId(30),
        zone_type=ZoneType.GENERAL,
        polygon=SQUARE,
        zone_definition_version=ZoneDefinitionVersion(8),
        calibration_reference="cam-1-v2",
    )
    (
        new_pipeline,
        new_visit_tracker,
        new_episode_tracker,
        _,
        _,
    ) = make_pipeline((replacement_zone,))

    with pytest.raises(
        ValueError,
        match=r"ParkingEpisode assignment.*zoneId=3",
    ):
        new_pipeline.restore_active(
            zone_visits=(),
            parking_episodes=(episode,),
            incidents=(),
        )

    # Cross-owner reference validation happens before any owner is mutated.
    assert new_visit_tracker.active_visits(CAR) == ()
    assert new_episode_tracker.active_episode(CAR) is None


def test_authoritative_context_opens_and_zone_exit_resolves_restricted_incident() -> None:
    pipeline, _, _, _, _ = make_pipeline((DISABLED_ZONE,))
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

    pipeline, _, _, reducer, _ = make_pipeline(
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
    pipeline, _, _, _, _ = make_pipeline((DISABLED_ZONE,), entry_seconds=0.0)

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
    pipeline, _, _, _, _ = make_pipeline(
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


@pytest.mark.parametrize(
    ("bbox", "expected_assignment", "primary", "secondary"),
    (
        (TWO_SPOT_51_49, AssignmentState.AMBIGUOUS, 0.51, 0.49),
        (TWO_SPOT_70_30, AssignmentState.ASSIGNED, 0.70, 0.30),
    ),
)
def test_two_spot_placement_opens_bad_parking_independent_of_assignment(
    bbox: BoundingBox,
    expected_assignment: AssignmentState,
    primary: float,
    secondary: float,
) -> None:
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, GENERAL_B),
        parking_seconds=1.0,
    )
    attempts = {CAR: ATTEMPT}
    pipeline.process(
        batch(0, snapshot(0, bbox=bbox)),
        entry_attempt_ids=attempts,
    )

    result = pipeline.process(
        batch(1, snapshot(1, bbox=bbox)),
        entry_attempt_ids=attempts,
    )

    assignment = result.parking_episode_updates[-1].assignment
    assert assignment is not None
    assert assignment.state is expected_assignment
    diagnostic = result.placement_diagnostics[0]
    assert diagnostic.evidence.primary_overlap_ratio == pytest.approx(primary)
    assert diagnostic.evidence.secondary_overlap_ratio == pytest.approx(secondary)
    assert diagnostic.evidence.spot_union_overlap_ratio == pytest.approx(1.0)
    assert diagnostic.bad_parking_signal.value is IncidentSignalValue.MATCHED
    assert [
        item.transition_type for item in transitions_for(result, BAD_PARKING)
    ] == [IncidentTransitionType.OPEN]


def test_assigned_vehicle_protruding_from_spot_opens_bad_parking() -> None:
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=1.0,
    )

    attempts = {CAR: ATTEMPT}
    pipeline.process(
        batch(0, snapshot(0, bbox=PROTRUDING_FROM_FIRST)),
        entry_attempt_ids=attempts,
    )
    result = pipeline.process(
        batch(1, snapshot(1, bbox=PROTRUDING_FROM_FIRST)),
        entry_attempt_ids=attempts,
    )

    assignment = result.parking_episode_updates[-1].assignment
    assert assignment is not None
    assert assignment.state is AssignmentState.ASSIGNED
    assert assignment.confidence == pytest.approx(0.60)
    opened = transitions_for(result, BAD_PARKING)
    assert [item.transition_type for item in opened] == [
        IncidentTransitionType.OPEN
    ]
    diagnostic = result.placement_diagnostics[0]
    assert diagnostic.source is PlacementEvidenceSource.PARKED_SNAPSHOT
    assert diagnostic.evidence.primary_overlap_ratio == pytest.approx(0.60)
    assert diagnostic.evidence.spot_union_overlap_ratio == pytest.approx(0.60)
    assert diagnostic.bad_parking_signal.value is IncidentSignalValue.MATCHED
    assert diagnostic.bad_parking_signal.confirmable is True
    assert diagnostic.out_of_zone_signal.value is IncidentSignalValue.NOT_MATCHED


def test_spot_union_below_threshold_opens_out_of_zone_not_bad_parking() -> None:
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=1.0,
    )

    attempts = {CAR: ATTEMPT}
    pipeline.process(
        batch(0, snapshot(0, bbox=OUTSIDE)),
        entry_attempt_ids=attempts,
    )
    result = pipeline.process(
        batch(1, snapshot(1, bbox=OUTSIDE)),
        entry_attempt_ids=attempts,
    )

    assert transitions_for(result, BAD_PARKING) == ()
    opened = transitions_for(result, OUT_OF_ZONE)
    assert [item.transition_type for item in opened] == [
        IncidentTransitionType.OPEN
    ]
    diagnostic = result.placement_diagnostics[0]
    assert diagnostic.source is PlacementEvidenceSource.PARKED_SNAPSHOT
    assert diagnostic.evidence.spot_union_overlap_ratio == pytest.approx(0.0)
    assert diagnostic.bad_parking_signal.value is IncidentSignalValue.NOT_MATCHED
    assert diagnostic.out_of_zone_signal.value is IncidentSignalValue.MATCHED
    assert diagnostic.out_of_zone_signal.confirmable is True


def test_parked_snapshot_ignores_final_frame_geometry_jitter() -> None:
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=2.0,
    )

    pipeline.process(batch(0, snapshot(0, bbox=ASSIGNED_FIRST)))
    pipeline.process(batch(1, snapshot(1, bbox=ASSIGNED_FIRST)))
    result = pipeline.process(batch(2, snapshot(2, bbox=OUTSIDE)))

    episode = result.parking_episode_updates[-1]
    assert episode.state is ParkingState.PARKED
    assert episode.assignment is not None
    assert episode.assignment.zone_id == GENERAL_A.zone_id
    assert episode.assignment.last_stable_at == at(0)
    diagnostic = result.placement_diagnostics[0]
    assert diagnostic.source is PlacementEvidenceSource.PARKED_SNAPSHOT
    assert diagnostic.evidence.representative_footprint == (
        (ASSIGNED_FIRST.x1, ASSIGNED_FIRST.y1),
        (ASSIGNED_FIRST.x2, ASSIGNED_FIRST.y1),
        (ASSIGNED_FIRST.x2, ASSIGNED_FIRST.y2),
        (ASSIGNED_FIRST.x1, ASSIGNED_FIRST.y2),
    )
    assert diagnostic.bad_parking_signal.value is IncidentSignalValue.NOT_MATCHED
    assert diagnostic.out_of_zone_signal.value is IncidentSignalValue.NOT_MATCHED
    assert transitions_for(result, BAD_PARKING) == ()
    assert transitions_for(result, OUT_OF_ZONE) == ()


def test_unknown_motion_freezes_bad_parking_clear_but_keeps_geometry_observed() -> None:
    pipeline, _, episode_tracker, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=1.0,
    )
    attempts = {CAR: ATTEMPT}
    pipeline.process(
        batch(0, snapshot(0, bbox=PROTRUDING_FROM_FIRST)),
        entry_attempt_ids=attempts,
    )
    opened = pipeline.process(
        batch(1, snapshot(1, bbox=PROTRUDING_FROM_FIRST)),
        entry_attempt_ids=attempts,
    )
    assert transitions_for(opened, BAD_PARKING)[0].transition_type is (
        IncidentTransitionType.OPEN
    )

    uncertain = pipeline.process(
        batch(
            2,
            snapshot(
                2,
                bbox=ASSIGNED_FIRST,
                motion=MotionSignal.UNKNOWN,
            ),
        ),
        entry_attempt_ids=attempts,
    )

    assert transitions_for(uncertain, BAD_PARKING) == ()
    bad_parking_update = updates_for(uncertain, BAD_PARKING)[-1]
    assert bad_parking_update.state is IncidentState.OPEN
    assert bad_parking_update.observation.state is ObservationState.UNKNOWN
    assert bad_parking_update.observation.reason is (
        ObservationReason.DEPENDENCY_UNAVAILABLE
    )
    assert uncertain.zone_visit_updates[-1].observation.state is (
        ObservationState.OBSERVED
    )
    active_episode = episode_tracker.active_episode(CAR)
    assert active_episode is not None
    assert active_episode.state is ParkingState.PARKED
    assert active_episode.observation.reason is (
        ObservationReason.DEPENDENCY_UNAVAILABLE
    )


def test_qualified_vehicle_does_not_open_restricted_incident() -> None:
    pipeline, _, _, _, _ = make_pipeline((DISABLED_ZONE,), entry_seconds=0.0)

    for second in (0.0, 1.0):
        result = pipeline.process(
            batch(second, snapshot(second)),
            session_contexts={CAR: DISABLED_QUALIFIED},
        )
        assert transitions_for(result, DISABLED_ZONE_UNAUTHORIZED) == ()


def test_ev_charging_restricted_and_overstay_rules_are_both_wired() -> None:
    unauthorized_pipeline, _, _, _, _ = make_pipeline((EV_ZONE,), entry_seconds=0.0)
    unauthorized = unauthorized_pipeline.process(
        batch(0, snapshot(0)),
        session_contexts={CAR: UNAUTHORIZED},
    )
    assert [
        item.transition_type
        for item in transitions_for(unauthorized, EV_ZONE_UNAUTHORIZED)
    ] == [IncidentTransitionType.OPEN]

    electric_pipeline, _, _, _, _ = make_pipeline((EV_ZONE,), entry_seconds=0.0)
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
    pipeline, visit_tracker, episode_tracker, _, _ = make_pipeline(
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
        pipeline, _, _, _, _ = make_pipeline(
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
    pipeline, _, _, _, _ = make_pipeline(
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


def test_unknown_motion_only_pauses_parking_episode_dependency() -> None:
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A,),
        entry_seconds=1.0,
        parking_seconds=5.0,
    )
    pipeline.process(batch(0, snapshot(0)))

    uncertain = pipeline.process(
        batch(1, snapshot(1, motion=MotionSignal.UNKNOWN))
    )

    assert uncertain.zone_visit_updates[-1].state is ZoneVisitState.INSIDE
    assert uncertain.zone_visit_updates[-1].observation.state is (
        ObservationState.OBSERVED
    )
    episode = uncertain.parking_episode_updates[-1]
    assert episode.state is ParkingState.STOP_PENDING
    assert episode.stationary_trusted_seconds == 0.0
    assert episode.observation.state is ObservationState.UNKNOWN
    assert episode.observation.reason is ObservationReason.DEPENDENCY_UNAVAILABLE
    assert episode.observation.last_reliable_observed_at == at(0)

    resumed = pipeline.process(batch(2, snapshot(2)))
    assert resumed.parking_episode_updates[-1].stationary_trusted_seconds == 0.0


def test_first_unknown_motion_keeps_geometry_without_opening_episode() -> None:
    pipeline, _, _, _, _ = make_pipeline((GENERAL_A,), entry_seconds=0.0)

    result = pipeline.process(
        batch(0, snapshot(0, motion=MotionSignal.UNKNOWN))
    )

    assert result.parking_episode_updates == ()
    assert result.zone_visit_updates[-1].observation.state is (
        ObservationState.OBSERVED
    )


def test_confirmed_absence_requires_explicit_physical_exit() -> None:
    pipeline, visit_tracker, episode_tracker, _, _ = make_pipeline(
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
    assert exit_plan.parking_transitions == ()
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
    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, GENERAL_B),
        entry_seconds=0.0,
        exit_seconds=0.0,
        parking_seconds=1.0,
        movement_seconds=0.5,
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
    assert updates_for(pending, BAD_PARKING)[-1].state is IncidentState.OPEN

    before_boundary = pipeline.process(
        batch(
            2.499999,
            snapshot(2.499999, bbox=AMBIGUOUS, motion=MotionSignal.MOVING),
        ),
        session_contexts=contexts,
    )
    assert before_boundary.parking_episode_updates[-1].state is (
        ParkingState.MOVE_PENDING
    )
    assert before_boundary.parking_transitions == ()

    movement_ended = pipeline.process(
        batch(2.5, snapshot(2.5, bbox=AMBIGUOUS, motion=MotionSignal.MOVING)),
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

    # terminal episode가 slot에서 제거된 다음에도 motion dependency가 UNKNOWN이면
    # 새 geometry로 기존 Incident의 clear timer를 진행하지 않는다.
    motion_unknown = pipeline.process(
        batch(
            2.75,
            snapshot(2.75, bbox=ASSIGNED_FIRST, motion=MotionSignal.UNKNOWN),
        ),
        session_contexts=contexts,
    )
    assert transitions_for(motion_unknown, BAD_PARKING) == ()
    assert updates_for(motion_unknown, BAD_PARKING)[-1].state is IncidentState.OPEN
    assert (
        motion_unknown.placement_diagnostics[0].bad_parking_signal.value
        is IncidentSignalValue.UNKNOWN
    )

    geometry_cleared = pipeline.process(
        batch(3, snapshot(3, bbox=ASSIGNED_FIRST, motion=MotionSignal.MOVING)),
        session_contexts=contexts,
    )
    resolved = transitions_for(geometry_cleared, BAD_PARKING)
    assert [item.transition_type for item in resolved] == [
        IncidentTransitionType.RESOLVE
    ]
    assert resolved[0].incident.incident_id == opened[0].incident.incident_id


def test_late_binding_on_movement_confirmation_materializes_both_revisions() -> None:
    pipeline, _, _, _, _ = make_pipeline(
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
    pipeline, _, _, _, _ = make_pipeline((local_ev,), entry_seconds=0.0)
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


def test_single_vehicle_batch_yields_no_blocking_relations() -> None:
    """subject·victim 후보 쌍이 없으면 관계는 계산되지 않는다."""

    pipeline, _, _, _, _ = make_pipeline((GENERAL_A,), entry_seconds=0.0)

    result = pipeline.process(batch(0, snapshot(0)))

    assert result.blocking_relation_updates == ()


AISLE_POLYGON = ((0.30, 0.0), (0.70, 0.0), (0.70, 1.0), (0.30, 1.0))
AISLE_BLOCKING_BBOX = BoundingBox(0.35, 0.40, 0.55, 0.60)


def test_small_egress_uses_coverage_ratio_for_blocking() -> None:
    """egress가 작아 차량 대비 overlap이 낮아도 완전 점유는 차단이다."""

    spot_with_egress = zone(5, ZoneType.GENERAL, FIRST_SPOT)
    small_egress = egress(
        9,
        5,
        ((0.40, 0.45), (0.45, 0.45), (0.45, 0.50), (0.40, 0.50)),
    )
    pipeline, _, _, _, _ = make_pipeline(
        (spot_with_egress,),
        egress_areas=(small_egress,),
        entry_seconds=0.0,
        parking_seconds=1.0,
        blocking_confirm_seconds=0.0,
        blocking_subject_overlap_ratio=0.5,
        blocking_egress_coverage_ratio=0.8,
    )

    def two_car_batch(seconds: float) -> TrackingBatch:
        return batch(
            seconds,
            snapshot(seconds, vehicle=CAR, bbox=ASSIGNED_FIRST),
            snapshot(
                seconds,
                vehicle=OTHER_CAR,
                bbox=AISLE_BLOCKING_BBOX,
            ),
        )

    pipeline.process(two_car_batch(0))
    parked = pipeline.process(two_car_batch(1))

    assert [
        relation.state for relation in parked.blocking_relation_updates
    ] == [BlockingRelationState.BLOCKING]


def test_double_parking_rule_receives_real_blocking_relation_signals() -> None:
    """victim이 PARKED되고 subject가 egress aisle을 막으면 BlockingRelation이
    실제로 만들어지고, double_parking 규칙이 그 신호로 Incident를 열고 닫는다."""

    spot_with_egress = zone(5, ZoneType.GENERAL, FIRST_SPOT)
    egress_area = egress(9, 5, AISLE_POLYGON)
    pipeline, _, _, _, relation_tracker = make_pipeline(
        (spot_with_egress,),
        egress_areas=(egress_area,),
        entry_seconds=0.0,
        parking_seconds=1.0,
        blocking_confirm_seconds=0.0,
        blocking_clear_seconds=0.0,
    )

    def two_car_batch(seconds: float, *, subject_bbox: BoundingBox) -> TrackingBatch:
        return batch(
            seconds,
            snapshot(seconds, vehicle=CAR, bbox=ASSIGNED_FIRST),
            snapshot(seconds, vehicle=OTHER_CAR, bbox=subject_bbox),
        )

    # entry_attempt_id로 OTHER_CAR(subject)를 상관시켜야 publish 가능한
    # Incident가 된다 — session/entry-attempt 없는 local-only CANDIDATE는
    # 다른 규칙(BAD_PARKING 등)과 동일하게 publication_revision이 0으로 남는다.
    subject_attempts = {OTHER_CAR: ATTEMPT}
    pipeline.process(
        two_car_batch(0, subject_bbox=AISLE_BLOCKING_BBOX),
        entry_attempt_ids=subject_attempts,
    )
    parked = pipeline.process(
        two_car_batch(1, subject_bbox=AISLE_BLOCKING_BBOX),
        entry_attempt_ids=subject_attempts,
    )

    assert parked.parking_episode_updates[0].state is ParkingState.PARKED
    assert [
        relation.state for relation in parked.blocking_relation_updates
    ] == [BlockingRelationState.BLOCKING]
    relation = parked.blocking_relation_updates[0]
    assert relation.subject_physical_vehicle_id == OTHER_CAR
    assert relation.victim_physical_vehicle_id == CAR
    assert relation.egress_zone_id == egress_area.egress_zone_id
    assert relation.source_parking_episode_id == parked.parking_episode_updates[0].episode_id
    assert relation_tracker.active_relations(OTHER_CAR) == (relation,)

    opened = transitions_for(parked, DOUBLE_PARKING)
    assert [item.transition_type for item in opened] == [IncidentTransitionType.OPEN]
    assert opened[0].incident.physical_vehicle_id == OTHER_CAR
    assert opened[0].incident.victim_physical_vehicle_id == CAR

    cleared = pipeline.process(
        two_car_batch(2, subject_bbox=OUTSIDE),
        entry_attempt_ids=subject_attempts,
    )

    resolved_relations = [
        r
        for r in cleared.blocking_relation_updates
        if r.state is BlockingRelationState.RESOLVED
    ]
    assert len(resolved_relations) == 1
    assert resolved_relations[0].blocking_relation_id == relation.blocking_relation_id
    resolved = transitions_for(cleared, DOUBLE_PARKING)
    assert [item.transition_type for item in resolved] == [
        IncidentTransitionType.RESOLVE
    ]
    assert resolved[0].incident.incident_id == opened[0].incident.incident_id
    assert relation_tracker.active_relations(OTHER_CAR) == ()


def test_blocking_relation_ends_when_victim_physically_exits() -> None:
    """victim의 확정 출차는 관계와 double_parking Incident를 함께 끝낸다."""

    spot_with_egress = zone(5, ZoneType.GENERAL, FIRST_SPOT)
    pipeline, _, _, _, relation_tracker = make_pipeline(
        (spot_with_egress,),
        egress_areas=(egress(9, 5, AISLE_POLYGON),),
        entry_seconds=0.0,
        parking_seconds=1.0,
        blocking_confirm_seconds=0.0,
        blocking_clear_seconds=0.0,
    )

    def two_car_batch(seconds: float) -> TrackingBatch:
        return batch(
            seconds,
            snapshot(seconds, vehicle=CAR, bbox=ASSIGNED_FIRST),
            snapshot(seconds, vehicle=OTHER_CAR, bbox=AISLE_BLOCKING_BBOX),
        )

    subject_attempts = {OTHER_CAR: ATTEMPT}
    pipeline.process(two_car_batch(0), entry_attempt_ids=subject_attempts)
    parked = pipeline.process(two_car_batch(1), entry_attempt_ids=subject_attempts)
    opened = transitions_for(parked, DOUBLE_PARKING)
    assert [item.transition_type for item in opened] == [IncidentTransitionType.OPEN]

    exit_plan = pipeline.physical_exit(
        physical_vehicle_id=CAR,
        observed_at=at(2),
    )

    assert [
        relation.state for relation in exit_plan.blocking_relation_updates
    ] == [BlockingRelationState.RESOLVED]
    resolved = transitions_for(exit_plan, DOUBLE_PARKING)
    assert [item.transition_type for item in resolved] == [
        IncidentTransitionType.RESOLVE
    ]
    assert resolved[0].incident.incident_id == opened[0].incident.incident_id
    assert relation_tracker.active_relations(OTHER_CAR) == ()


def test_blocking_relation_holds_when_victim_observation_is_unreliable() -> None:
    """§7 "한쪽 관측 UNKNOWN이면 lifecycle 유지, timer 정지" — subject가
    계속 aisle에 있어도 victim 관측이 흔들리면 관계는 clear로 넘어가지
    않고 BLOCKING을 유지한다."""

    spot_with_egress = zone(5, ZoneType.GENERAL, FIRST_SPOT)
    pipeline, _, _, _, relation_tracker = make_pipeline(
        (spot_with_egress,),
        egress_areas=(egress(9, 5, AISLE_POLYGON),),
        entry_seconds=0.0,
        parking_seconds=1.0,
        blocking_confirm_seconds=0.0,
        blocking_clear_seconds=5.0,
    )

    def two_car_batch(seconds: float, *, victim_observation=None) -> TrackingBatch:
        return batch(
            seconds,
            snapshot(
                seconds,
                vehicle=CAR,
                bbox=ASSIGNED_FIRST,
                observation=victim_observation,
            ),
            snapshot(seconds, vehicle=OTHER_CAR, bbox=AISLE_BLOCKING_BBOX),
        )

    pipeline.process(two_car_batch(0))
    parked = pipeline.process(two_car_batch(1))
    relation = parked.blocking_relation_updates[0]
    assert relation.state is BlockingRelationState.BLOCKING

    degraded_victim = pipeline.process(
        two_car_batch(2, victim_observation=degraded(last_reliable=1))
    )

    assert [
        r.state for r in degraded_victim.blocking_relation_updates
    ] == [BlockingRelationState.BLOCKING]
    held = degraded_victim.blocking_relation_updates[0]
    assert held.blocking_relation_id == relation.blocking_relation_id
    assert held.clear_trusted_seconds == 0.0
    assert held.confirm_trusted_seconds == relation.confirm_trusted_seconds
    assert held.observation.state is ObservationState.DEGRADED
    assert relation_tracker.active_relations(OTHER_CAR) == (held,)


def test_zone_presence_and_assignment_thresholds_are_independent() -> None:
    half_overlap = BoundingBox(0.0, 0.12, 0.20, 0.28)
    pipeline, visit_tracker, _, _, _ = make_pipeline(
        (GENERAL_A,),
        parking_seconds=1.0,
        zone_overlap_ratio=0.75,
        assignment_overlap_ratio=0.5,
    )

    pipeline.process(batch(0, snapshot(0, bbox=half_overlap)))
    parked = pipeline.process(batch(1, snapshot(1, bbox=half_overlap)))

    assert visit_tracker.active_visits(CAR) == ()
    assert parked.parking_episode_updates[-1].assignment.zone_id == GENERAL_A.zone_id


def test_open_exit_zone_visit_counts_as_traversal() -> None:
    """마지막으로 관측된 위치가 출차 구역이면 통과로 인정한다(565)."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_entering_visit_below_confirmation_still_counts_as_traversal() -> None:
    """ZONE_ENTRY_CONFIRM_SECONDS를 못 채우고 지나간 차도 통과로 인정한다.

    이게 이 정의의 핵심이다(565) — INSIDE 확정을 요구하면 빨리 나간 차가
    미탐되고, 그 세션은 영구히 닫히지 않는다.
    """

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=10.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(batch(1, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_parking_zone_visit_alone_is_not_traversal() -> None:
    pipeline, _, _, _, _ = make_pipeline((GENERAL_A,), entry_seconds=1.0)
    pipeline.process(batch(0, snapshot(0)))
    pipeline.process(batch(1, snapshot(1)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_entry_role_zone_visit_is_not_traversal() -> None:
    """같은 ENTRY_EXIT 구역이라도 role이 ENTRY면 출차 근거가 아니다(565)."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, ENTRY_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(batch(1, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_traversal_is_no_longer_observed_after_physical_exit() -> None:
    """읽기 순서 회귀: physical_exit()이 방문을 종료시키면 근거가 사라진다(565)."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(batch(1, unobserved=(CAR,)))
    assert pipeline.exit_zone_traversal_observed(CAR) is True

    pipeline.physical_exit(physical_vehicle_id=CAR, observed_at=at(2))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_visit_of_unknown_zone_is_ignored_without_raising() -> None:
    """설정 교체로 사라진 zone의 방문은 예외 없이 통과 미인정으로 처리한다(565).

    이 경로는 departure commit 중에 실행되므로 예외를 던지면 차량 종료
    자체가 실패한다. registry에 실제 EXIT 구역을 두어(571), 차량이 이미
    outward 접촉을 만든 상태에서 알 수 없는 zoneId의 방문이 섞여도 결과가
    그대로 유지되고 예외도 나지 않는지를 확인한다 — EXIT 구역이 없어
    접촉 집합이 항상 비어 있던 이전 registry로는 이 방문이 아무것도
    가르지 못했다.
    """

    pipeline, visit_tracker, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    visit_tracker.update(
        physical_vehicle_id=CAR,
        zone_id=ZoneId(999),
        signal=PresenceSignal.PRESENT,
        observation=observed(0),
        observed_at=at(0),
    )

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_inward_side_contact_alone_is_not_traversal() -> None:
    """출차 통로 안쪽에만 있던 차량은 통과로 인정하지 않는다(571).

    565에서는 이 경우도 통과였다 — 이 태스크가 좁히는 지점이다.
    """

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_INWARD)))
    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT_INWARD)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_outward_side_contact_while_stationary_is_traversal() -> None:
    """외부측에 정지해 있어도 통과로 인정한다(571).

    방향 조건을 쓰지 않는다는 결정을 고정한다 — 차단기 앞 정지 중
    추적이 끊겨도 세션이 미결되지 않아야 한다.
    """

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(
        batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD, motion=MotionSignal.STATIONARY))
    )
    pipeline.process(
        batch(1, snapshot(1, bbox=IN_EXIT_OUTWARD, motion=MotionSignal.STATIONARY))
    )
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_returning_to_inward_side_overwrites_outward_contact() -> None:
    """매 프레임 덮어쓰기 검증(571) — 외부측 접촉이 오래 남지 않는다."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    assert pipeline.exit_zone_traversal_observed(CAR) is True

    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT_INWARD)))
    pipeline.process(batch(2, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_unobserved_frames_preserve_the_last_outward_contact() -> None:
    """미관측 프레임은 접촉 상태를 지우지 않는다(571).

    부재 확정까지 5초가 걸리므로, 그동안 값이 유지돼야 판정이 성립한다.
    """

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    for seconds in (1, 2, 3, 4, 5):
        pipeline.process(batch(seconds, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_degraded_frame_does_not_overwrite_outward_contact() -> None:
    """신뢰할 수 없는 관측은 접촉 상태를 갱신하지 않는다(571)."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(
        batch(
            1,
            snapshot(
                1,
                bbox=IN_EXIT_INWARD,
                observation=degraded(last_reliable=0),
            ),
            batch_observation=degraded(last_reliable=0),
        )
    )

    assert pipeline.exit_zone_traversal_observed(CAR) is True


def test_registry_without_aisle_never_confirms_traversal() -> None:
    """외부 방향을 유도할 수 없으면 통과를 확정하지 않는다(571)."""

    pipeline, _, _, _, _ = make_pipeline((GENERAL_A, EXIT_ZONE), entry_seconds=1.0)
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    pipeline.process(batch(1, unobserved=(CAR,)))

    assert pipeline.exit_zone_traversal_observed(CAR) is False


def test_checkpoint_round_trip_preserves_outward_contact() -> None:
    """frame UnitOfWork 롤백이 접촉 상태도 함께 되돌린다(571)."""

    pipeline, _, _, _, _ = make_pipeline(
        (GENERAL_A, AISLE_ZONE, EXIT_ZONE), entry_seconds=1.0
    )
    pipeline.process(batch(0, snapshot(0, bbox=IN_EXIT_OUTWARD)))
    checkpoint = pipeline.checkpoint_state()

    pipeline.process(batch(1, snapshot(1, bbox=IN_EXIT_INWARD)))
    assert pipeline.exit_zone_traversal_observed(CAR) is False

    pipeline.restore_state(checkpoint)
    assert pipeline.exit_zone_traversal_observed(CAR) is True

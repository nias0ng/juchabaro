"""PlacementEvidence 기반 BAD_PARKING/OUT_OF_ZONE 삼상태 계약을 검증한다."""

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
    PlacementEvidence,
    PlacementEvidenceSource,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneOverlapEvidence,
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
VERSION = ZoneDefinitionVersion(1)
FOOTPRINT = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))
LEFT = ((0.1, 0.1), (0.2, 0.1), (0.2, 0.3), (0.1, 0.3))
RIGHT = ((0.2, 0.1), (0.3, 0.1), (0.3, 0.3), (0.2, 0.3))


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
    state: AssignmentState = AssignmentState.ASSIGNED,
    *,
    confidence: float = 0.9,
) -> ParkingAssignment:
    return ParkingAssignment(
        state=state,
        representative_footprint=FOOTPRINT,
        confidence=confidence,
        last_stable_at=T0,
        zone_id=(ZoneId(1) if state is AssignmentState.ASSIGNED else None),
        unassigned_reason=(None if state is AssignmentState.ASSIGNED else state.value),
    )


def make_evidence(
    *,
    primary: float = 0.8,
    secondary: float = 0.1,
    union: float = 0.9,
) -> PlacementEvidence:
    candidates = (
        ZoneOverlapEvidence(zone_id=ZoneId(1), overlap_ratio=primary),
        ZoneOverlapEvidence(zone_id=ZoneId(2), overlap_ratio=secondary),
    )
    if secondary > primary:
        candidates = tuple(
            sorted(
                candidates,
                key=lambda item: (-item.overlap_ratio, int(item.zone_id)),
            )
        )
    return PlacementEvidence(
        representative_footprint=FOOTPRINT,
        zone_definition_version=VERSION,
        observed_at=T0,
        candidate_overlaps=candidates,
        primary_zone_id=candidates[0].zone_id,
        primary_overlap_ratio=candidates[0].overlap_ratio,
        secondary_zone_id=candidates[1].zone_id,
        secondary_overlap_ratio=candidates[1].overlap_ratio,
        dominance_gap=candidates[0].overlap_ratio - candidates[1].overlap_ratio,
        spot_union_overlap_ratio=union,
        outside_spot_overlap_ratio=1.0 - union,
    )


def make_episode(
    state: ParkingState,
    *,
    assignment: ParkingAssignment | None = None,
    observation: ObservationStatus | None = None,
) -> ParkingEpisode:
    was_parked = state in {ParkingState.PARKED, ParkingState.MOVE_PENDING}
    durable_assignment = assignment or (
        make_assignment() if was_parked else None
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
    polygon = LEFT if zone_id == 1 else RIGHT
    if zone_type is ZoneType.AISLE:
        polygon = FOOTPRINT
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=polygon,
        zone_definition_version=VERSION,
        calibration_reference="calibration-v1",
    )


def make_aisle_visit(*, observation: ObservationStatus | None = None) -> ZoneVisit:
    return ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=20)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(3),
        zone_definition_version=VERSION,
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
    placement_evidence: PlacementEvidence | None = None,
    parking_assignment: ParkingAssignment | None = None,
    episode_state: ParkingState | None = ParkingState.PARKED,
    episode_assignment: ParkingAssignment | None = None,
    aisle_visit: ZoneVisit | None = None,
    context_observation: ObservationStatus | None = None,
    parking_motion_observation: ObservationStatus | None = None,
    episode_observation: ObservationStatus | None = None,
) -> RuleContext:
    status = context_observation or observed()
    evidence = placement_evidence
    assignment = parking_assignment
    vehicle = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.1, 0.1, 0.3, 0.3),
        confidence=0.95,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="camera-1",
        observation=status,
    )
    zones = (
        make_zone(1, ZoneType.GENERAL),
        make_zone(2, ZoneType.GENERAL),
        make_zone(3, ZoneType.AISLE),
    )
    return RuleContext(
        vehicle=vehicle,
        observation=status,
        parking_motion_observation=parking_motion_observation or observed(),
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
        parking_assignment=assignment,
        placement_evidence=evidence,
        placement_evidence_source=(
            None if evidence is None else PlacementEvidenceSource.PARKED_SNAPSHOT
        ),
        blocking_relations=(),
        zones=ZoneRegistry(zones),
        bad_parking_min_primary_overlap_ratio=0.75,
        bad_parking_min_secondary_overlap_ratio=0.25,
        out_of_zone_min_spot_overlap_ratio=0.50,
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


@pytest.mark.parametrize(
    ("primary", "secondary", "union", "bad", "out", "reasons"),
    [
        (0.80, 0.10, 0.90, False, False, ()),
        (0.75, 0.24, 0.99, False, False, ()),
        (0.74, 0.10, 0.84, True, False, ("LOW_PRIMARY_OVERLAP",)),
        (0.75, 0.25, 1.00, True, False, ("MULTI_SPOT_OVERLAP",)),
        (
            0.45,
            0.45,
            0.90,
            True,
            False,
            ("LOW_PRIMARY_OVERLAP", "MULTI_SPOT_OVERLAP"),
        ),
        (0.30, 0.00, 0.30, False, True, ()),
        (0.50, 0.00, 0.50, True, False, ("LOW_PRIMARY_OVERLAP",)),
    ],
)
def test_placement_truth_table(
    primary: float,
    secondary: float,
    union: float,
    bad: bool,
    out: bool,
    reasons: tuple[str, ...],
) -> None:
    signals = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(
                primary=primary,
                secondary=secondary,
                union=union,
            ),
            parking_assignment=make_assignment(),
        )
    )

    assert signals["BAD_PARKING"].value is (
        IncidentSignalValue.MATCHED if bad else IncidentSignalValue.NOT_MATCHED
    )
    assert signals["OUT_OF_ZONE"].value is (
        IncidentSignalValue.MATCHED if out else IncidentSignalValue.NOT_MATCHED
    )
    assert signals["BAD_PARKING"].evidence["reasons"] == reasons
    if out:
        assert signals["OUT_OF_ZONE"].evidence["reasons"] == (
            "INSUFFICIENT_SPOT_UNION_OVERLAP",
        )


def test_assignment_state_is_not_a_violation_proxy() -> None:
    ambiguous_normal = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(primary=0.80, secondary=0.10, union=0.90),
            parking_assignment=make_assignment(AssignmentState.AMBIGUOUS),
        )
    )
    unassigned_split = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(primary=0.45, secondary=0.45, union=0.90),
            parking_assignment=make_assignment(AssignmentState.UNASSIGNED),
        )
    )
    assigned_outside = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(primary=0.30, secondary=0.00, union=0.30),
            parking_assignment=make_assignment(AssignmentState.ASSIGNED),
        )
    )

    assert ambiguous_normal["BAD_PARKING"].value is IncidentSignalValue.NOT_MATCHED
    assert unassigned_split["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert unassigned_split["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED
    assert assigned_outside["BAD_PARKING"].value is IncidentSignalValue.NOT_MATCHED
    assert assigned_outside["OUT_OF_ZONE"].value is IncidentSignalValue.MATCHED


def test_bad_parking_and_aisle_block_can_match_independently_together() -> None:
    signals = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(primary=0.45, secondary=0.45, union=0.90),
            parking_assignment=make_assignment(AssignmentState.UNASSIGNED),
            aisle_visit=make_aisle_visit(),
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.MATCHED
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED


def test_matching_predicate_is_not_confirmable_before_parked() -> None:
    signals = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(primary=0.45, secondary=0.45, union=0.90),
            parking_assignment=make_assignment(AssignmentState.UNASSIGNED),
            episode_state=None,
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["BAD_PARKING"].confirmable is False


def test_move_pending_pauses_all_three_predicates_as_unknown() -> None:
    signals = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(),
            parking_assignment=make_assignment(),
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
            placement_evidence=make_evidence(),
            parking_assignment=make_assignment(),
            episode_observation=unknown(),
        )
    )

    assert all(
        signal.value is IncidentSignalValue.UNKNOWN
        and signal.evidence["reason"]
        == "PARKING_MOTION_DEPENDENCY_UNAVAILABLE"
        for signal in signals.values()
    )


def test_unknown_parking_motion_pauses_without_active_episode() -> None:
    signals = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(),
            parking_assignment=make_assignment(),
            episode_state=None,
            parking_motion_observation=unknown(),
        )
    )

    assert all(
        signal.value is IncidentSignalValue.UNKNOWN
        and signal.evidence["reason"]
        == "PARKING_MOTION_DEPENDENCY_UNAVAILABLE"
        for signal in signals.values()
    )


def test_missing_evidence_only_makes_placement_predicates_unknown() -> None:
    signals = signals_by_rule(
        make_context(parking_assignment=make_assignment())
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.UNKNOWN
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.UNKNOWN
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.NOT_MATCHED


def test_unknown_aisle_observation_does_not_hide_placement_results() -> None:
    signals = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(primary=0.45, secondary=0.45, union=0.90),
            parking_assignment=make_assignment(AssignmentState.UNASSIGNED),
            aisle_visit=make_aisle_visit(observation=unknown()),
        )
    )

    assert signals["BAD_PARKING"].value is IncidentSignalValue.MATCHED
    assert signals["OUT_OF_ZONE"].value is IncidentSignalValue.NOT_MATCHED
    assert signals["AISLE_BLOCK"].value is IncidentSignalValue.UNKNOWN


def test_unknown_frame_observation_pauses_all_three_predicates() -> None:
    signals = signals_by_rule(
        make_context(
            placement_evidence=make_evidence(),
            parking_assignment=make_assignment(),
            aisle_visit=make_aisle_visit(),
            context_observation=unknown(),
        )
    )

    assert all(
        signal.value is IncidentSignalValue.UNKNOWN
        and signal.confirmable is False
        for signal in signals.values()
    )

"""PlacementEvidence와 ParkingAssignment의 독립 geometry 계약을 검증한다."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.domain.models import ObservationState, ObservationStatus
from src.parking.assignment_resolver import (
    AMBIGUOUS_ZONE_OVERLAP,
    NO_ELIGIBLE_ZONE,
    analyze,
    assignment_from_evidence,
    resolve,
)
from src.parking.models import (
    AssignmentState,
    EntryExitRole,
    NormalizedPolygon,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
)

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
VERSION = ZoneDefinitionVersion(3)
BBOX = BoundingBox(0.1, 0.1, 0.3, 0.3)
FOOTPRINT: NormalizedPolygon = (
    (0.1, 0.1),
    (0.3, 0.1),
    (0.3, 0.3),
    (0.1, 0.3),
)
FAR: NormalizedPolygon = (
    (0.6, 0.6),
    (0.8, 0.6),
    (0.8, 0.8),
    (0.6, 0.8),
)
OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=T0,
)


def make_zone(
    zone_id: int,
    zone_type: ZoneType,
    polygon: NormalizedPolygon,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=polygon,
        zone_definition_version=VERSION,
        calibration_reference="camera-1:v3",
        entry_exit_role=(
            EntryExitRole.ENTRY
            if zone_type is ZoneType.ENTRY_EXIT
            else None
        ),
    )


def make_vehicle(bbox: BoundingBox = BBOX) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=bbox,
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="camera-1",
        observation=OBSERVED,
    )


def vertical_spot(
    left: float,
    right: float,
) -> NormalizedPolygon:
    return (
        (left, 0.1),
        (right, 0.1),
        (right, 0.3),
        (left, 0.3),
    )


def adjacent_pair(
    split: float,
    *,
    first_id: int = 1,
    second_id: int = 2,
) -> tuple[ZoneDefinition, ZoneDefinition]:
    return (
        make_zone(first_id, ZoneType.GENERAL, vertical_spot(0.1, split)),
        make_zone(second_id, ZoneType.GENERAL, vertical_spot(split, 0.3)),
    )


def resolve_with(
    *zones: ZoneDefinition,
    minimum: float = 0.1,
    margin: float = 0.1,
):
    return resolve(
        make_vehicle(),
        ZoneRegistry(zones),
        min_overlap_ratio=minimum,
        ambiguous_margin=margin,
    )


def test_analyze_preserves_ranked_51_49_and_union_evidence() -> None:
    evidence = analyze(make_vehicle(), ZoneRegistry(adjacent_pair(0.202)))

    assert evidence.primary_zone_id == ZoneId(1)
    assert evidence.primary_overlap_ratio == pytest.approx(0.51)
    assert evidence.secondary_zone_id == ZoneId(2)
    assert evidence.secondary_overlap_ratio == pytest.approx(0.49)
    assert evidence.dominance_gap == pytest.approx(0.02)
    assert evidence.spot_union_overlap_ratio == pytest.approx(1.0)
    assert evidence.outside_spot_overlap_ratio == pytest.approx(0.0)
    assert tuple(item.zone_id for item in evidence.candidate_overlaps) == (
        ZoneId(1),
        ZoneId(2),
    )


def test_candidate_tie_uses_zone_id_not_registry_order() -> None:
    left, right = adjacent_pair(0.2, first_id=20, second_id=10)

    forward = analyze(make_vehicle(), ZoneRegistry((left, right)))
    reverse = analyze(make_vehicle(), ZoneRegistry((right, left)))

    assert forward.candidate_overlaps == reverse.candidate_overlaps
    assert forward.primary_zone_id == ZoneId(10)
    assert forward.secondary_zone_id == ZoneId(20)


def test_single_overlapping_zone_is_assigned_with_complete_snapshot() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.GENERAL, FOOTPRINT),
        margin=0.0,
    )

    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)
    assert result.unassigned_reason is None
    assert result.representative_footprint == FOOTPRINT
    assert result.confidence == pytest.approx(1.0)
    assert result.last_stable_at == T0


def test_single_candidate_cannot_be_ambiguous_at_margin_boundary() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.GENERAL, vertical_spot(0.1, 0.2)),
        minimum=0.5,
        margin=0.5,
    )

    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_no_spot_candidate_is_unassigned_even_when_minimum_is_zero() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.AISLE, FOOTPRINT),
        minimum=0.0,
        margin=1.0,
    )

    assert result.state is AssignmentState.UNASSIGNED
    assert result.unassigned_reason == NO_ELIGIBLE_ZONE


def test_no_eligible_overlap_is_unassigned_with_reason() -> None:
    result = resolve_with(make_zone(1, ZoneType.GENERAL, FAR))

    assert result.state is AssignmentState.UNASSIGNED
    assert result.zone_id is None
    assert result.unassigned_reason == NO_ELIGIBLE_ZONE
    assert result.confidence == 0.0


def test_primary_below_minimum_keeps_best_overlap_evidence() -> None:
    first, second = adjacent_pair(0.2)
    result = resolve_with(first, second, minimum=0.51, margin=0.0)

    assert result.state is AssignmentState.UNASSIGNED
    assert result.confidence == pytest.approx(0.5)


def test_primary_equal_to_minimum_is_assignment_eligible() -> None:
    evidence = analyze(make_vehicle(), ZoneRegistry(adjacent_pair(0.2)))

    result = assignment_from_evidence(
        evidence,
        min_overlap_ratio=0.5,
        ambiguous_margin=0.0,
    )

    assert result.state is AssignmentState.AMBIGUOUS


def test_clear_70_30_winner_is_assigned() -> None:
    result = resolve_with(*adjacent_pair(0.24), minimum=0.5, margin=0.05)

    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)
    assert result.confidence == pytest.approx(0.7)


def test_ambiguity_margin_boundary_is_inclusive() -> None:
    result = resolve_with(*adjacent_pair(0.21), minimum=0.5, margin=0.1)

    assert result.state is AssignmentState.AMBIGUOUS
    assert result.unassigned_reason == AMBIGUOUS_ZONE_OVERLAP


def test_just_outside_ambiguity_margin_is_assigned() -> None:
    result = resolve_with(*adjacent_pair(0.21), minimum=0.5, margin=0.099)

    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_union_and_outside_include_only_spot_zones() -> None:
    zones = (
        make_zone(1, ZoneType.GENERAL, vertical_spot(0.11, 0.20)),
        make_zone(2, ZoneType.EV_CHARGING, vertical_spot(0.20, 0.29)),
        make_zone(3, ZoneType.AISLE, FOOTPRINT),
    )

    evidence = analyze(make_vehicle(), ZoneRegistry(zones))

    assert evidence.primary_overlap_ratio == pytest.approx(0.45)
    assert evidence.secondary_overlap_ratio == pytest.approx(0.45)
    assert evidence.spot_union_overlap_ratio == pytest.approx(0.9)
    assert evidence.outside_spot_overlap_ratio == pytest.approx(0.1)
    assert {item.zone_id for item in evidence.candidate_overlaps} == {
        ZoneId(1),
        ZoneId(2),
    }


def test_aisle_and_entry_exit_are_not_assignment_candidates() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.AISLE, FOOTPRINT),
        make_zone(2, ZoneType.ENTRY_EXIT, FOOTPRINT),
    )

    assert result.state is AssignmentState.UNASSIGNED


@pytest.mark.parametrize(
    "zone_type",
    [ZoneType.GENERAL, ZoneType.DISABLED, ZoneType.EV_CHARGING],
)
def test_all_canonical_spot_types_are_assignment_candidates(
    zone_type: ZoneType,
) -> None:
    result = resolve_with(make_zone(1, zone_type, FOOTPRINT), margin=0.0)
    assert result.state is AssignmentState.ASSIGNED


@pytest.mark.parametrize("field", ["minimum", "margin"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_ratio_configuration_must_be_finite_unit_interval(
    field: str,
    value: float,
) -> None:
    kwargs = {"minimum": 0.1, "margin": 0.1, field: value}
    with pytest.raises(ValueError, match="between 0 and 1"):
        resolve_with(
            make_zone(1, ZoneType.GENERAL, FOOTPRINT),
            **kwargs,
        )

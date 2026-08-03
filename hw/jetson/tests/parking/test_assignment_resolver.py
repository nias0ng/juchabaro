"""정본 ZoneDefinition에서 ParkingAssignment를 계산하는 resolver를 검증한다."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.domain.models import ObservationState, ObservationStatus
from src.parking.assignment_resolver import (
    AMBIGUOUS_ZONE_OVERLAP,
    NO_ELIGIBLE_ZONE,
    resolve,
)
from src.parking.geometry import overlap_ratio
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
FULL: NormalizedPolygon = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))
HALF: NormalizedPolygon = ((0.1, 0.1), (0.2, 0.1), (0.2, 0.3), (0.1, 0.3))
FAR: NormalizedPolygon = ((0.6, 0.6), (0.8, 0.6), (0.8, 0.8), (0.6, 0.8))
BBOX = BoundingBox(0.1, 0.1, 0.3, 0.3)
FOOTPRINT: NormalizedPolygon = FULL
OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=T0,
)


def make_zone(zone_id: int, zone_type: ZoneType, polygon: NormalizedPolygon) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=polygon,
        zone_definition_version=VERSION,
        calibration_reference="camera-1:v3",
        entry_exit_role=EntryExitRole.ENTRY if zone_type is ZoneType.ENTRY_EXIT else None,
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


def test_single_overlapping_zone_is_assigned_with_complete_snapshot() -> None:
    result = resolve_with(make_zone(1, ZoneType.GENERAL, FULL))

    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)
    assert result.unassigned_reason is None
    assert result.representative_footprint == FOOTPRINT
    assert result.confidence == pytest.approx(1.0)
    assert result.last_stable_at == T0


def test_no_eligible_overlap_is_unassigned_with_reason() -> None:
    result = resolve_with(make_zone(1, ZoneType.GENERAL, FAR))

    assert result.state is AssignmentState.UNASSIGNED
    assert result.zone_id is None
    assert result.unassigned_reason == NO_ELIGIBLE_ZONE
    assert result.confidence == 0.0


def test_overlap_below_minimum_keeps_best_overlap_evidence() -> None:
    result = resolve_with(make_zone(1, ZoneType.GENERAL, HALF), minimum=0.6)

    assert result.state is AssignmentState.UNASSIGNED
    assert result.confidence == pytest.approx(0.5)


def test_clear_winner_is_assigned() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.DISABLED, HALF),
    )
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_close_candidates_are_ambiguous_with_reason() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.DISABLED, FULL),
    )

    assert result.state is AssignmentState.AMBIGUOUS
    assert result.zone_id is None
    assert result.unassigned_reason == AMBIGUOUS_ZONE_OVERLAP
    assert result.confidence == pytest.approx(1.0)


def test_ambiguity_margin_boundary_is_inclusive() -> None:
    difference = overlap_ratio(FULL, BBOX) - overlap_ratio(HALF, BBOX)
    result = resolve_with(
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.GENERAL, HALF),
        margin=difference,
    )
    assert result.state is AssignmentState.AMBIGUOUS


def test_just_outside_ambiguity_margin_is_assigned() -> None:
    difference = overlap_ratio(FULL, BBOX) - overlap_ratio(HALF, BBOX)
    result = resolve_with(
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.GENERAL, HALF),
        margin=difference - 0.01,
    )
    assert result.state is AssignmentState.ASSIGNED


def test_aisle_and_entry_exit_are_not_assignment_candidates() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.AISLE, FULL),
        make_zone(2, ZoneType.ENTRY_EXIT, FULL),
    )
    assert result.state is AssignmentState.UNASSIGNED


def test_non_spot_does_not_make_a_spot_ambiguous() -> None:
    result = resolve_with(
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.AISLE, FULL),
        margin=1.0,
    )
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


@pytest.mark.parametrize("zone_type", [ZoneType.GENERAL, ZoneType.DISABLED, ZoneType.EV_CHARGING])
def test_all_canonical_spot_types_are_assignment_candidates(zone_type: ZoneType) -> None:
    result = resolve_with(make_zone(1, zone_type, FULL))
    assert result.state is AssignmentState.ASSIGNED


@pytest.mark.parametrize("field", ["minimum", "margin"])
@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan")])
def test_ratio_configuration_must_be_finite_unit_interval(field: str, value: float) -> None:
    kwargs = {"minimum": 0.1, "margin": 0.1, field: value}
    with pytest.raises(ValueError, match="between 0 and 1"):
        resolve_with(make_zone(1, ZoneType.GENERAL, FULL), **kwargs)

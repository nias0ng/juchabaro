"""대표 주차면 배정(assignment_resolver) 테스트 (T-10/462).

핵심 규약 세 개를 고정한다 (데이터흐름.md §3, `parking/models.py`의
`AssignmentState` docstring).
- 겹치는 스팟형 구역이 없으면 UNASSIGNED
- 최고·차순위 겹침 비율 차이가 마진 이내면 AMBIGUOUS로 두고 억지로
  하나를 고르지 않는다
- 그 외에는 겹침 비율이 가장 높은 구역에 ASSIGNED

AISLE/ENTRY_EXIT처럼 스팟이 아닌 구역은 겹침 비율이 아무리 높아도 배정
후보에서 제외한다 — 통행로에 서 있다고 "그 통행로를 배정받는" 것은
의미가 없다.
"""

from datetime import datetime, timezone

from src.parking.assignment_resolver import resolve
from src.parking.geometry import NormalizedPolygon, overlap_ratio
from src.parking.models import AssignmentState, ZoneId
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
)

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")


def make_zone(zone_id: int, zone_type: ZoneType, polygon: NormalizedPolygon) -> ParkingZone:
    return ParkingZone(
        zone_id=ZoneId(zone_id),
        zone_number=f"Z-{zone_id}",
        zone_type=zone_type,
        polygon=polygon,
    )


def make_vehicle(bbox: BoundingBox) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=bbox,
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="cam-1",
        context=None,
    )


# 정확히 겹치는 4각형 — bbox와 동일 좌표라 overlap_ratio가 1.0.
FULL = NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)))
BBOX_FULL = BoundingBox(0.1, 0.1, 0.3, 0.3)

# bbox 절반만 덮는 4각형 (왼쪽 절반) — overlap_ratio가 0.5.
HALF = NormalizedPolygon(((0.1, 0.1), (0.2, 0.1), (0.2, 0.3), (0.1, 0.3)))

# bbox와 전혀 안 겹치는 4각형.
FAR = NormalizedPolygon(((0.6, 0.6), (0.8, 0.6), (0.8, 0.8), (0.6, 0.8)))


def test_single_overlapping_zone_is_assigned() -> None:
    zones = ZoneRegistry([make_zone(1, ZoneType.GENERAL, FULL)])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)
    assert result.physical_vehicle_id == CAR


def test_no_overlapping_zone_is_unassigned() -> None:
    zones = ZoneRegistry([make_zone(1, ZoneType.GENERAL, FAR)])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.UNASSIGNED
    assert result.zone_id is None


def test_overlap_below_min_ratio_is_unassigned() -> None:
    """겹침 비율이 최소 기준 미만이면 후보에서도 빠진다 — 살짝 스친 것과
    실제로 걸쳐 있는 것을 구분한다."""
    zones = ZoneRegistry([make_zone(1, ZoneType.GENERAL, HALF)])  # ratio == 0.5
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.6, ambiguous_margin=0.1)
    assert result.state is AssignmentState.UNASSIGNED


def test_far_ahead_winner_is_assigned_despite_second_candidate() -> None:
    """1등과 2등 차이가 마진보다 크면 애매하지 않다 — 1등에 확정 배정한다."""
    zones = ZoneRegistry([
        make_zone(1, ZoneType.GENERAL, FULL),  # ratio == 1.0
        make_zone(2, ZoneType.GENERAL, HALF),  # ratio == 0.5, 차이 0.5 > 마진
    ])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_close_candidates_within_margin_are_ambiguous() -> None:
    """1등·2등 겹침 비율 차이가 마진 이내면 억지로 하나를 고르지 않는다."""
    zones = ZoneRegistry([
        make_zone(1, ZoneType.GENERAL, FULL),  # ratio == 1.0
        make_zone(2, ZoneType.DISABLED, FULL),  # 같은 자리에 겹친 다른 구역, ratio == 1.0
    ])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.AMBIGUOUS
    assert result.zone_id is None


def test_margin_boundary_is_inclusive() -> None:
    """차이가 마진과 정확히 같으면 AMBIGUOUS다(경계는 애매한 쪽으로 취급).

    두 구역의 실제 겹침 비율 차이를 직접 계산해서 마진으로 준다 — 폴리곤
    클리핑은 부동소수 오차로 정확히 1.0/0.5가 안 나올 수 있어서, 손으로
    고른 "0.5" 같은 값에 기대면 이 테스트가 resolve()가 아니라 부동소수
    오차를 검증하게 된다.
    """
    ratio_diff = overlap_ratio(FULL, BBOX_FULL) - overlap_ratio(HALF, BBOX_FULL)
    zones = ZoneRegistry([
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.GENERAL, HALF),
    ])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=ratio_diff)
    assert result.state is AssignmentState.AMBIGUOUS


def test_just_over_margin_is_assigned() -> None:
    ratio_diff = overlap_ratio(FULL, BBOX_FULL) - overlap_ratio(HALF, BBOX_FULL)
    zones = ZoneRegistry([
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.GENERAL, HALF),
    ])
    result = resolve(
        make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=ratio_diff - 0.01
    )
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_single_candidate_is_assigned_even_with_large_margin() -> None:
    """비교 대상(2등)이 아예 없으면 마진과 무관하게 확정 배정한다."""
    zones = ZoneRegistry([make_zone(1, ZoneType.GENERAL, FULL)])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.9)
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_non_spot_zone_types_are_excluded_from_candidates() -> None:
    """AISLE/ENTRY_EXIT은 겹침 비율이 높아도 배정 후보가 아니다."""
    zones = ZoneRegistry([
        make_zone(1, ZoneType.AISLE, FULL),
        make_zone(2, ZoneType.ENTRY_EXIT, FULL),
    ])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.UNASSIGNED


def test_non_spot_zone_does_not_count_as_the_second_candidate() -> None:
    """스팟형 구역 하나 + AISLE 하나가 동시에 겹쳐도, AISLE은 2등 후보가 될
    수 없으므로 확정 배정된다(마진 비교 대상에서 제외)."""
    zones = ZoneRegistry([
        make_zone(1, ZoneType.GENERAL, FULL),
        make_zone(2, ZoneType.AISLE, FULL),
    ])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.5)
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_empty_zone_registry_is_unassigned() -> None:
    """등록된 구역이 아예 없어도(빈 프레임, 초기화 직후 등) 예외 없이
    UNASSIGNED를 반환한다."""
    result = resolve(make_vehicle(BBOX_FULL), ZoneRegistry([]), min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.UNASSIGNED
    assert result.zone_id is None


def test_only_top_two_candidates_matter_when_three_zones_overlap() -> None:
    """3개 이상 겹쳐도 비교는 1등·2등만 한다 — 2등과 3등이 서로 아무리
    가까워도(심지어 동률이어도) 1등이 확실히 앞서 있으면 확정 배정된다."""
    zones = ZoneRegistry([
        make_zone(1, ZoneType.GENERAL, FULL),  # ratio == 1.0 (1등)
        make_zone(2, ZoneType.DISABLED, HALF),  # ratio == 0.5 (2등)
        make_zone(3, ZoneType.EV_FAST, HALF),  # ratio == 0.5 (3등, 2등과 동률)
    ])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)


def test_ev_and_disabled_zones_are_also_valid_candidates() -> None:
    zones = ZoneRegistry([make_zone(1, ZoneType.EV_FAST, FULL)])
    result = resolve(make_vehicle(BBOX_FULL), zones, min_overlap_ratio=0.1, ambiguous_margin=0.1)
    assert result.state is AssignmentState.ASSIGNED
    assert result.zone_id == ZoneId(1)

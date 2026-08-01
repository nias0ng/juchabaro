"""EV 구역 장기점유 규칙 테스트.

핵심 규약 세 개를 고정한다 (데이터흐름.md §4 ev_overstay.py, T-11/450).
- 판단 기준은 ZoneVisit 점유 시간(entered_at 기준)이지 ParkingEpisode(600초
  주차 확정)가 아니다 — parking_episode가 None이어도 확정된다.
- VehicleContext와 무관하다 — 자격 정보 없이도 확정된다(restricted_zone과
  다른 지점).
- 구역 allowed_minutes가 설정돼 있지 않으면 아무리 오래 머물러도 확정하지
  않는다.

성립(`evaluate_open`)만 이 모듈이 담당한다. 해소는 `IncidentReducer.
resolve_scope()`가 규칙을 거치지 않고 직접 처리한다(446 후속 리뷰와 동일한
구조 — `restricted_zone.py`, `test_restricted_zone.py` 참고).
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from src.parking.geometry import NormalizedPolygon
from src.parking.models import ZoneId, ZoneVisit, ZoneVisitId, ZoneVisitState
from src.parking.rules.ev_overstay import evaluate_open
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    VehicleContext,
)

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")
SQUARE = NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)))
UNAUTHORIZED = VehicleContext(
    parking_session_id=1, vehicle_id=1, is_electric=True, is_disabled_vehicle=False
)


def make_zone(zone_id: int, zone_type: ZoneType, allowed_minutes: float | None) -> ParkingZone:
    return ParkingZone(
        zone_id=ZoneId(zone_id),
        zone_number=f"Z-{zone_id}",
        zone_type=zone_type,
        polygon=SQUARE,
        allowed_minutes=allowed_minutes,
    )


def make_visit(
    zone_id: int,
    *,
    state: ZoneVisitState = ZoneVisitState.INSIDE,
    entered_at: datetime | None = T0,
) -> ZoneVisit:
    return ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=zone_id)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(zone_id),
        state=state,
        entered_candidate_at=T0,
        entered_at=entered_at if state is ZoneVisitState.INSIDE else None,
    )


def make_context(
    zones: list[ParkingZone],
    visits: list[ZoneVisit],
    *,
    observed_at: datetime = T0,
    vehicle_context: VehicleContext | None = None,
) -> RuleContext:
    snapshot = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=observed_at,
        camera_id="cam-1",
        context=vehicle_context,
    )
    return RuleContext(
        vehicle=snapshot,
        vehicle_context=vehicle_context,
        active_zone_visits=tuple(visits),
        parking_episode=None,
        parking_assignment=None,
        zones=ZoneRegistry(zones),
        observed_at=observed_at,
    )


def find(signals, zone_id: int):
    return next(s for s in signals if s.key.zone_id == ZoneId(zone_id))


def test_occupancy_under_allowed_minutes_is_not_confirmable() -> None:
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=30),
    ))
    signal = find(signals, 1)
    assert signal.key.rule_code == "EV_OVERSTAY"
    assert signal.matched is True
    assert signal.confirmable is False


def test_occupancy_at_allowed_minutes_is_confirmable() -> None:
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_SLOW, allowed_minutes=60.0)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=60),
    ))
    assert find(signals, 1).confirmable is True


def test_occupancy_over_allowed_minutes_is_confirmable() -> None:
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=90),
    ))
    assert find(signals, 1).confirmable is True


def test_missing_allowed_minutes_is_never_confirmable() -> None:
    """구역에 allowed_minutes가 설정돼 있지 않으면 아무리 오래 있어도 확정하지 않는다."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=None)],
        [make_visit(1)],
        observed_at=T0 + timedelta(days=1),
    ))
    assert find(signals, 1).confirmable is False


def test_does_not_wait_for_parking_confirmation() -> None:
    """parking_episode가 None이어도 확정된다 — ParkingEpisode와 무관하다."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=60),
    ))
    assert find(signals, 1).confirmable is True


def test_does_not_require_vehicle_context() -> None:
    """자격 정보 없이도 확정된다 — restricted_zone과 달리 신원과 무관하다."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=60),
        vehicle_context=None,
    ))
    assert find(signals, 1).confirmable is True


def test_disabled_zone_produces_no_signal() -> None:
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.DISABLED, allowed_minutes=None)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=90),
    ))
    assert signals == ()


def test_general_zone_produces_no_signal() -> None:
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.GENERAL, allowed_minutes=None)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=90),
    ))
    assert signals == ()


def test_entering_visit_produces_no_signal() -> None:
    """진입 확인이 끝나지 않은 방문은 판정 대상이 아니다."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1, state=ZoneVisitState.ENTERING, entered_at=None)],
    ))
    assert signals == ()


def test_exiting_visit_produces_no_signal() -> None:
    """이탈 확인 중인 방문도 아직 해소 대상이 아니다."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1, state=ZoneVisitState.EXITING, entered_at=None)],
    ))
    assert signals == ()


def test_inside_visit_without_entered_at_produces_no_signal() -> None:
    """계약상 INSIDE는 entered_at을 채워 두지만(zone_visit_tracker), 어겨도
    프레임 전체가 죽지 않고 이 방문만 조용히 건너뛴다는 방어 분기를 고정한다."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1, entered_at=None)],
        observed_at=T0 + timedelta(minutes=90),
    ))
    assert signals == ()


def test_outside_visit_produces_no_signal() -> None:
    """닫힌 방문은 이 모듈의 판정 대상이 아니다 — 해소는
    IncidentReducer.resolve_scope()의 몫이다(446 후속 리뷰와 동일한 구조)."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1, state=ZoneVisitState.OUTSIDE, entered_at=None)],
    ))
    assert signals == ()


def test_two_ev_zones_produce_two_independent_signals() -> None:
    signals = evaluate_open(make_context(
        [
            make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0),
            make_zone(2, ZoneType.EV_SLOW, allowed_minutes=None),
        ],
        [make_visit(1), make_visit(2)],
        observed_at=T0 + timedelta(minutes=90),
    ))
    assert find(signals, 1).confirmable is True
    assert find(signals, 2).confirmable is False


def test_unknown_zone_is_skipped_without_killing_the_frame() -> None:
    """등록되지 않은 구역을 가리키는 방문 하나가 프레임 전체 판정을 죽이면 안 된다."""
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1), make_visit(99)],
        observed_at=T0 + timedelta(minutes=90),
    ))
    assert [s.key.zone_id for s in signals] == [ZoneId(1)]


def test_evidence_includes_occupancy_details() -> None:
    signals = evaluate_open(make_context(
        [make_zone(1, ZoneType.EV_FAST, allowed_minutes=60.0)],
        [make_visit(1)],
        observed_at=T0 + timedelta(minutes=90),
    ))
    evidence = find(signals, 1).evidence
    assert evidence["elapsedMinutes"] == 90.0
    assert evidence["allowedMinutes"] == 60.0
    assert evidence["zoneType"] == "EV_FAST"
    assert evidence["zoneVisitEnteredAt"] == T0.isoformat()

"""전용구역 무자격 진입 규칙 테스트.

핵심 규약 세 개를 고정한다.
- 10분 주차 완료를 기다리지 않는다 (ZoneVisit이 INSIDE면 판정)
- 자격 정보가 None이면 confirmable=false (정보 없음을 무자격으로 보지 않는다)
- 자격이 있으면 matched=false를 반환해 RESOLVE 경로를 열어 둔다
"""

from datetime import datetime, timezone

from src.parking.geometry import NormalizedPolygon
from src.parking.models import ZoneId, ZoneVisit, ZoneVisitState
from src.parking.rules.models import RuleContext
from src.parking.rules.restricted_zone import evaluate
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


def make_zone(zone_id: int, zone_type: ZoneType) -> ParkingZone:
    return ParkingZone(
        zone_id=ZoneId(zone_id),
        zone_number=f"Z-{zone_id}",
        zone_type=zone_type,
        polygon=SQUARE,
        allowed_minutes=60.0 if zone_type in (ZoneType.EV_FAST, ZoneType.EV_SLOW) else None,
    )


def make_visit(zone_id: int, state: ZoneVisitState = ZoneVisitState.INSIDE) -> ZoneVisit:
    closed = state is ZoneVisitState.OUTSIDE
    return ZoneVisit(
        visit_id=f"visit-{zone_id}",
        physical_vehicle_id=CAR,
        zone_id=ZoneId(zone_id),
        state=state,
        entered_candidate_at=T0,
        entered_at=T0 if state is ZoneVisitState.INSIDE or closed else None,
        exited_at=T0 if closed else None,
    )


def make_context(
    zones: list[ParkingZone],
    visits: list[ZoneVisit],
    context: VehicleContext | None,
) -> RuleContext:
    snapshot = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="cam-1",
        context=context,
    )
    return RuleContext(
        vehicle=snapshot,
        vehicle_context=context,
        active_zone_visits=tuple(visits),
        parking_episode=None,
        parking_assignment=None,
        zones=ZoneRegistry(zones),
        observed_at=T0,
    )


NON_DISABLED = VehicleContext(
    parking_session_id=1, vehicle_id=1, is_electric=False, is_disabled_vehicle=False
)
DISABLED = VehicleContext(
    parking_session_id=1, vehicle_id=1, is_electric=False, is_disabled_vehicle=True
)
ELECTRIC = VehicleContext(
    parking_session_id=1, vehicle_id=1, is_electric=True, is_disabled_vehicle=False
)
UNKNOWN_CONTEXT = VehicleContext(
    parking_session_id=None, vehicle_id=None, is_electric=None, is_disabled_vehicle=None
)


def find(signals, rule_code):
    return next(s for s in signals if s.key.rule_code == rule_code)


def test_non_disabled_vehicle_in_disabled_zone_is_confirmable() -> None:
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)], [make_visit(1)], NON_DISABLED
    ))
    signal = find(signals, "DISABLED_ZONE_UNAUTHORIZED")
    assert signal.matched is True
    assert signal.confirmable is True
    assert signal.key.zone_visit_id == "visit-1"
    assert signal.key.zone_id == ZoneId(1)


def test_does_not_wait_for_parking_confirmation() -> None:
    """parking_episode가 None이어도 확정된다 — 10분을 기다리지 않는다."""
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)], [make_visit(1)], NON_DISABLED
    ))
    assert find(signals, "DISABLED_ZONE_UNAUTHORIZED").confirmable is True


def test_disabled_vehicle_in_disabled_zone_is_not_matched() -> None:
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)], [make_visit(1)], DISABLED
    ))
    matching = [s for s in signals if s.key.rule_code == "DISABLED_ZONE_UNAUTHORIZED"]
    assert len(matching) == 1, "자격 있는 차량도 matched=False 신호를 내야 IncidentReducer가 RESOLVE를 만들 수 있다"
    assert matching[0].matched is False


def test_unknown_qualification_is_not_confirmable() -> None:
    """정보를 못 얻은 것을 무자격으로 간주하면 안 된다."""
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)], [make_visit(1)], UNKNOWN_CONTEXT
    ))
    signal = find(signals, "DISABLED_ZONE_UNAUTHORIZED")
    assert signal.matched is True
    assert signal.confirmable is False


def test_missing_vehicle_context_is_not_confirmable() -> None:
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)], [make_visit(1)], None
    ))
    assert find(signals, "DISABLED_ZONE_UNAUTHORIZED").confirmable is False


def test_non_electric_vehicle_in_ev_zone_is_confirmable() -> None:
    signals = evaluate(make_context(
        [make_zone(2, ZoneType.EV_FAST)], [make_visit(2)], NON_DISABLED
    ))
    signal = find(signals, "EV_ZONE_UNAUTHORIZED")
    assert signal.matched is True
    assert signal.confirmable is True


def test_electric_vehicle_in_ev_zone_is_not_matched() -> None:
    signals = evaluate(make_context(
        [make_zone(2, ZoneType.EV_SLOW)], [make_visit(2)], ELECTRIC
    ))
    matching = [s for s in signals if s.key.rule_code == "EV_ZONE_UNAUTHORIZED"]
    assert len(matching) == 1, "자격 있는 차량도 matched=False 신호를 내야 IncidentReducer가 RESOLVE를 만들 수 있다"
    assert matching[0].matched is False


def test_general_zone_produces_no_signal() -> None:
    signals = evaluate(make_context(
        [make_zone(3, ZoneType.GENERAL)], [make_visit(3)], NON_DISABLED
    ))
    assert signals == ()


def test_entering_visit_produces_no_signal() -> None:
    """진입 확인이 끝나지 않은 방문은 판정 대상이 아니다."""
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)],
        [make_visit(1, ZoneVisitState.ENTERING)],
        NON_DISABLED,
    ))
    assert signals == ()


def test_exiting_visit_produces_no_signal() -> None:
    """이탈 확인 중에 사건을 닫으면 잠깐 가려진 차량이 위반을 지운다."""
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)],
        [make_visit(1, ZoneVisitState.EXITING)],
        NON_DISABLED,
    ))
    assert signals == ()


def test_closed_visit_produces_unmatched_signal() -> None:
    """방문이 닫히면 무자격 차량이어도 matched=False다 — 이것이 RESOLVE의 유일한 입력이다.

    이 신호가 없으면 사건이 영원히 EDGE_CONFIRMED로 남고, 재진입은 새
    zone_visit_id로 두 번째 OPEN을 만들어 미해소 사건이 계속 쌓인다.
    """
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)],
        [make_visit(1, ZoneVisitState.OUTSIDE)],
        NON_DISABLED,
    ))
    signal = find(signals, "DISABLED_ZONE_UNAUTHORIZED")
    assert signal.matched is False
    assert signal.key.zone_visit_id == "visit-1"
    assert signal.evidence["zoneVisitExitedAt"] == T0.isoformat()


def test_closed_visit_with_unknown_qualification_still_unmatched() -> None:
    """자격을 끝내 못 알아낸 채 방문이 끝나도 사건은 닫혀야 한다."""
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)],
        [make_visit(1, ZoneVisitState.OUTSIDE)],
        UNKNOWN_CONTEXT,
    ))
    assert find(signals, "DISABLED_ZONE_UNAUTHORIZED").matched is False


def test_two_restricted_zones_produce_two_signals() -> None:
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED), make_zone(2, ZoneType.EV_FAST)],
        [make_visit(1), make_visit(2)],
        NON_DISABLED,
    ))
    assert len(signals) == 2
    assert {s.key.rule_code for s in signals} == {
        "DISABLED_ZONE_UNAUTHORIZED", "EV_ZONE_UNAUTHORIZED"
    }


def test_unknown_zone_is_skipped_without_killing_the_frame() -> None:
    """등록되지 않은 구역을 가리키는 방문 하나가 프레임 전체 판정을 죽이면 안 된다.

    서버 구역 동기화가 들어오면 방문 도중 삭제된 구역이 상시 발생한다.
    """
    signals = evaluate(make_context(
        [make_zone(1, ZoneType.DISABLED)],
        [make_visit(1), make_visit(99)],
        NON_DISABLED,
    ))
    # 살아 있는 구역의 판정은 그대로 나온다.
    assert [s.key.zone_id for s in signals] == [ZoneId(1)]


def test_evidence_includes_qualification_flags() -> None:
    signals = evaluate(make_context(
        [make_zone(2, ZoneType.EV_FAST)], [make_visit(2)], NON_DISABLED
    ))
    evidence = find(signals, "EV_ZONE_UNAUTHORIZED").evidence
    assert evidence["isElectric"] is False
    assert evidence["zoneType"] == "EV_FAST"

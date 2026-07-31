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
    return ZoneVisit(
        visit_id=f"visit-{zone_id}",
        physical_vehicle_id=CAR,
        zone_id=ZoneId(zone_id),
        state=state,
        entered_candidate_at=T0,
        entered_at=T0 if state is ZoneVisitState.INSIDE else None,
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
    assert find(signals, "DISABLED_ZONE_UNAUTHORIZED").matched is False


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
    assert find(signals, "EV_ZONE_UNAUTHORIZED").matched is False


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


def test_evidence_includes_qualification_flags() -> None:
    signals = evaluate(make_context(
        [make_zone(2, ZoneType.EV_FAST)], [make_visit(2)], NON_DISABLED
    ))
    evidence = find(signals, "EV_ZONE_UNAUTHORIZED").evidence
    assert evidence["isElectric"] is False
    assert evidence["zoneType"] == "EV_FAST"

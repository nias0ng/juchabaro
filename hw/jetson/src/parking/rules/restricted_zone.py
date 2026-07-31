"""전용구역(장애인/전기차) 무자격 진입 판정.

상태를 보관하지 않는 순수 함수다. `ZoneVisit`이 `INSIDE`이면 판정하고 주차
완료(600초)를 기다리지 않는다 — 진입 자체가 위반 요건이다.

자격 정보(`is_disabled_vehicle`/`is_electric`)가 `None`이면 `matched=True`로
두되 `confirmable=False`를 반환한다. "정보를 못 얻음"을 "무자격"으로 간주하면
번호판 매칭이 실패한 차량이 전부 위반으로 통보된다.

자격이 확인돼 위반이 아닌 경우에는 `matched=False`를 반환한다. 이 신호가
없으면 `IncidentReducer`가 이미 열린 사건을 RESOLVE로 닫을 수 없다.
"""

from __future__ import annotations

from src.parking.models import (
    IncidentKey,
    IncidentSignal,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import EV_ZONE_TYPES, ParkingZone, ZoneType

DISABLED_ZONE_UNAUTHORIZED = "DISABLED_ZONE_UNAUTHORIZED"
EV_ZONE_UNAUTHORIZED = "EV_ZONE_UNAUTHORIZED"


def evaluate(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """INSIDE인 전용구역 방문마다 신호 하나를 만든다."""

    signals: list[IncidentSignal] = []
    for visit in context.active_zone_visits:
        if visit.state is not ZoneVisitState.INSIDE:
            continue
        zone = context.zones.get(visit.zone_id)
        signal = _evaluate_zone(context, visit, zone)
        if signal is not None:
            signals.append(signal)
    return tuple(signals)


def _evaluate_zone(
    context: RuleContext, visit: ZoneVisit, zone: ParkingZone
) -> IncidentSignal | None:
    if zone.zone_type is ZoneType.DISABLED:
        rule_code = DISABLED_ZONE_UNAUTHORIZED
        qualified = None if context.vehicle_context is None else context.vehicle_context.is_disabled_vehicle
        evidence_key = "isDisabledVehicle"
    elif zone.zone_type in EV_ZONE_TYPES:
        rule_code = EV_ZONE_UNAUTHORIZED
        qualified = None if context.vehicle_context is None else context.vehicle_context.is_electric
        evidence_key = "isElectric"
    else:
        return None

    # 자격이 확인되고 자격이 있으면 위반이 아니다 — matched=False로 RESOLVE를 연다.
    matched = qualified is not True
    # 자격을 모르면 확정하지 않는다. 백엔드 조회 재시도 동안 후보로만 유지된다.
    confirmable = qualified is False

    return IncidentSignal(
        key=IncidentKey(
            # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
            physical_vehicle_id=context.vehicle.physical_vehicle_id,
            rule_code=rule_code,
            zone_visit_id=visit.visit_id,
            zone_id=visit.zone_id,
        ),
        matched=matched,
        confirmable=confirmable,
        observed_at=context.observed_at,
        evidence={
            evidence_key: qualified,
            "zoneType": zone.zone_type.value,
            "zoneNumber": zone.zone_number,
            "zoneVisitEnteredAt": None if visit.entered_at is None else visit.entered_at.isoformat(),
        },
    )

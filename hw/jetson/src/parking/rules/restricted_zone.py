"""전용구역(장애인/전기차) 무자격 진입 판정.

상태를 보관하지 않는 순수 함수다. `ZoneVisit`이 `INSIDE`이면 판정하고 주차
완료(600초)를 기다리지 않는다 — 진입 자체가 위반 요건이다.

자격 정보(`is_disabled_vehicle`/`is_electric`)가 `None`이면 `matched=True`로
두되 `confirmable=False`를 반환한다. "정보를 못 얻음"을 "무자격"으로 간주하면
번호판 매칭이 실패한 차량이 전부 위반으로 통보된다.

자격이 확인돼 위반이 아닌 경우에는 `matched=False`를 반환한다. 이 신호가
없으면 `IncidentReducer`가 이미 열린 사건을 RESOLVE로 닫을 수 없다.

**방문이 끝난 경우에도 `matched=False`를 반환한다.** 트래커가 방문을 닫는
프레임에 `active_visits()`가 그 방문을 한 번 실어 보내며, 그것이 사건을 닫을
유일한 기회다. 이 신호를 만들지 않으면 사건이 영원히 EDGE_CONFIRMED로 남고,
같은 차량이 다시 들어오면 새 zone_visit_id로 두 번째 OPEN이 만들어져 미해소
사건이 드나들 때마다 쌓인다.

구역 정의에 없는 zone_id를 가리키는 방문은 신호 없이 건너뛴다. 예외를 그대로
올리면 방문 하나 때문에 그 프레임의 모든 규칙·모든 차량 판정이 죽는다.
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
    """판정 대상 전용구역 방문마다 신호 하나를 만든다.

    `INSIDE`인 방문은 위반 성립 여부를(`matched`는 자격에 따라), 방금 닫힌
    방문(`OUTSIDE`)은 항상 해소 신호(`matched=False`)를 만든다. `ENTERING`과
    `EXITING`은 성립도 해소도 아직 결정되지 않아 신호를 만들지 않는다 —
    이탈 확인 중에 사건을 닫으면 잠깐 가려진 차량이 위반을 지운다.
    """

    signals: list[IncidentSignal] = []
    for visit in context.active_zone_visits:
        if visit.state is ZoneVisitState.INSIDE:
            closed = False
        elif visit.state is ZoneVisitState.OUTSIDE:
            closed = True
        else:
            continue
        zone = context.zones.get_or_none(visit.zone_id)
        if zone is None:
            # 구역 정의에 없는 방문이다. 여기서 예외가 밖으로 나가면 이 프레임의
            # 모든 규칙·모든 차량 판정이 함께 죽는다 — 위반 하나를 놓치는 것보다
            # 프레임 전체를 잃는 쪽이 훨씬 비싸다. 서버 구역 동기화가 들어오면
            # 방문 도중 삭제된 구역이 상시 발생한다.
            continue
        signal = _evaluate_zone(context, visit, zone, closed=closed)
        if signal is not None:
            signals.append(signal)
    return tuple(signals)


def _evaluate_zone(
    context: RuleContext, visit: ZoneVisit, zone: ParkingZone, *, closed: bool
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

    if closed:
        # 방문이 끝났다. 자격 정보와 무관하게 더 이상 위반 상태가 아니므로
        # matched=False로 RESOLVE를 연다. confirmable은 해소 경로에서 축약기가
        # 보지 않지만, 이 판정에 미확정 요소가 없으므로 True가 맞다.
        matched = False
        confirmable = True
    else:
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
            "zoneVisitExitedAt": None if visit.exited_at is None else visit.exited_at.isoformat(),
        },
    )

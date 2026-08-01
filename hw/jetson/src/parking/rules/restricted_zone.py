"""전용구역(장애인/전기차) 무자격 진입 판정.

상태를 보관하지 않는 순수 함수다. `ZoneVisit`이 `INSIDE`이면 판정하고 주차
완료(600초)를 기다리지 않는다 — 진입 자체가 위반 요건이다.

자격 정보(`is_disabled_vehicle`/`is_electric`)가 `None`이면 `matched=True`로
두되 `confirmable=False`를 반환한다. "정보를 못 얻음"을 "무자격"으로 간주하면
번호판 매칭이 실패한 차량이 전부 위반으로 통보된다.

자격이 확인돼 위반이 아닌 경우에는 `matched=False`를 반환한다. 이 신호가
없으면 `IncidentReducer`가 이미 열린 사건을 RESOLVE로 닫을 수 없다.

**이 모듈은 성립(`INSIDE`) 판정만 한다(446 후속 리뷰로 해소 판정을 뺐다).**
전에는 방문이 닫힐 때도 이 모듈이 구역을 다시 조회해 `matched=False` 신호를
만들었는데, 그러려면 `rule_code`를 다시 알아내야 했다 — 구역 정의가 방문
도중 사라지면(서버 구역 동기화 등) 재구성이 안 돼 해소 자체가 조용히
생략되는 문제가 있었다. "방문이 끝났다"는 사실은 그 방문을 스코프로 삼은
사건이 끝났다는 뜻이지 규칙을 다시 판정할 문제가 아니므로, 해소는 이제
`IncidentReducer.resolve_scope()`가 `zone_visit_id`만으로 직접 처리한다
(`parking/incident_reducer.py` 참고) — 이 모듈을 거치지 않는다.

구역 정의에 없는 zone_id를 가리키는 방문은 신호 없이 건너뛴다. 예외를 그대로
올리면 방문 하나 때문에 그 프레임의 모든 규칙·모든 차량 판정이 죽는다.
"""

from __future__ import annotations

from src.parking.models import IncidentKey, IncidentSignal, ZoneVisit, ZoneVisitState
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import EV_ZONE_TYPES, ParkingZone, ZoneType

DISABLED_ZONE_UNAUTHORIZED = "DISABLED_ZONE_UNAUTHORIZED"
EV_ZONE_UNAUTHORIZED = "EV_ZONE_UNAUTHORIZED"


def evaluate_open(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """관측 중인 차량의 `INSIDE` 방문마다 위반 성립 신호를 만든다.

    자격 정보(`context.vehicle_context`)가 있어야 하므로 `RuleContext`를
    요구한다. `ENTERING`/`EXITING`/`OUTSIDE` 방문은 건너뛴다 — 성립도
    해소도 아직 결정되지 않았거나(진입·이탈 확인 중), 해소는
    `IncidentReducer.resolve_scope()`의 몫이다.
    """

    signals: list[IncidentSignal] = []
    for visit in context.active_zone_visits:
        if visit.state is not ZoneVisitState.INSIDE:
            continue
        zone = context.zones.get_or_none(visit.zone_id)
        if zone is None:
            # 구역 정의에 없는 방문이다. 여기서 예외가 밖으로 나가면 이 프레임의
            # 모든 규칙·모든 차량 판정이 함께 죽는다 — 위반 하나를 놓치는 것보다
            # 프레임 전체를 잃는 쪽이 훨씬 비싸다. 서버 구역 동기화가 들어오면
            # 방문 도중 삭제된 구역이 상시 발생한다.
            continue
        signal = _evaluate_open(context, visit, zone)
        if signal is not None:
            signals.append(signal)
    return tuple(signals)


def _evaluate_open(
    context: RuleContext, visit: ZoneVisit, zone: ParkingZone
) -> IncidentSignal | None:
    """방문이 성립 중(`INSIDE`)일 때의 판정. 자격 정보로 위반 여부를 가른다."""

    if zone.zone_type is ZoneType.DISABLED:
        rule_code = DISABLED_ZONE_UNAUTHORIZED
        evidence_key = "isDisabledVehicle"
        qualified = None if context.vehicle_context is None else context.vehicle_context.is_disabled_vehicle
    elif zone.zone_type in EV_ZONE_TYPES:
        rule_code = EV_ZONE_UNAUTHORIZED
        evidence_key = "isElectric"
        qualified = None if context.vehicle_context is None else context.vehicle_context.is_electric
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

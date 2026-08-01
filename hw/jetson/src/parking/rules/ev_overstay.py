"""전기차 구역 ZoneVisit의 허용 점유 시간 초과 규칙.

상태를 보관하지 않는 순수 함수다. `restricted_zone`과 달리 `VehicleContext`나
`ParkingEpisode`(600초 주차 확정)와 무관하다 — `ZoneVisit`이 `INSIDE`인 동안
`entered_at`부터 흐른 점유 시간만으로 판단한다(데이터흐름.md §4).

구역에 `allowed_minutes`가 설정돼 있지 않으면 아무리 오래 점유해도
확정하지 않는다 — 그 구역에는 애초에 장기점유 제한이 없다는 뜻이지, 정보가
나중에 채워지길 기다리는 상태가 아니다. 그래도 매 프레임 `confirmable=False`
신호를 계속 내는 것은 `restricted_zone`의 신원 미확정 처리와 같은
이유에서다 — 서버 구역 동기화로 `allowed_minutes`가 나중에 채워지면, 이미
누적된 `entered_at` 기준 점유 시간이 그대로 판정에 반영돼야 한다.

**이 모듈은 성립(`INSIDE`) 판정만 한다(446 후속 리뷰와 동일한 구조).** 해소는
`IncidentReducer.resolve_scope()`가 `zone_visit_id`만으로 직접 처리한다
(`parking/incident_reducer.py` 참고) — 이 모듈을 거치지 않는다.

구역 정의에 없는 zone_id를 가리키는 방문은 신호 없이 건너뛴다. 예외를 그대로
올리면 방문 하나 때문에 그 프레임의 모든 규칙·모든 차량 판정이 죽는다.
"""

from __future__ import annotations

from src.parking.models import IncidentKey, IncidentSignal, ZoneVisit, ZoneVisitState
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import EV_ZONE_TYPES, ParkingZone

EV_OVERSTAY = "EV_OVERSTAY"


def evaluate_open(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """관측 중인 차량의 EV구역 `INSIDE` 방문마다 점유 시간 판정 신호를 만든다.

    `ENTERING`/`EXITING`/`OUTSIDE` 방문은 건너뛴다 — 성립도 해소도 아직
    결정되지 않았거나(진입·이탈 확인 중), 해소는
    `IncidentReducer.resolve_scope()`의 몫이다.
    """

    signals: list[IncidentSignal] = []
    for visit in context.active_zone_visits:
        if visit.state is not ZoneVisitState.INSIDE:
            continue
        zone = context.zones.get_or_none(visit.zone_id)
        if zone is None:
            continue
        signal = _evaluate_open(context, visit, zone)
        if signal is not None:
            signals.append(signal)
    return tuple(signals)


def _evaluate_open(
    context: RuleContext, visit: ZoneVisit, zone: ParkingZone
) -> IncidentSignal | None:
    """방문이 성립 중(`INSIDE`)일 때의 판정. 점유 시간과 허용 시간을 비교한다."""

    if zone.zone_type not in EV_ZONE_TYPES:
        return None
    if visit.entered_at is None:
        # 계약상 INSIDE는 entered_at을 채워 두지만, 방어적으로 건너뛴다.
        return None

    elapsed_minutes = (context.observed_at - visit.entered_at).total_seconds() / 60.0
    confirmable = zone.allowed_minutes is not None and elapsed_minutes >= zone.allowed_minutes

    return IncidentSignal(
        key=IncidentKey(
            # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
            physical_vehicle_id=context.vehicle.physical_vehicle_id,
            rule_code=EV_OVERSTAY,
            zone_visit_id=visit.visit_id,
            zone_id=visit.zone_id,
        ),
        matched=True,
        confirmable=confirmable,
        observed_at=context.observed_at,
        evidence={
            "elapsedMinutes": round(elapsed_minutes, 3),
            "allowedMinutes": zone.allowed_minutes,
            "zoneType": zone.zone_type.value,
            "zoneNumber": zone.zone_number,
            "zoneVisitEnteredAt": visit.entered_at.isoformat(),
        },
    )

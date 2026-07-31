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

**성립(`INSIDE`) 판정과 해소(`OUTSIDE`) 판정은 입력을 분리한다.** 해소는
자격 정보와 무관하게 항상 `matched=False`다 — 그런데 예전엔 두 판정이 같은
함수에서 `RuleContext` 전체(= `vehicle_context` 포함)를 받았다. 그러면
"해소는 자격과 무관하다"는 규칙이 테스트로만 보장되고, 나중에 누가 해소
분기에도 자격 조건을 실수로 끼워 넣는 걸 타입 시그니처가 막아주지 못한다.
그래서 해소 판정 함수(`_evaluate_resolve`)는 `vehicle_context`를 아예 인자로
받지 않는다 — 구조적으로 참조할 수 없게 만드는 쪽이 주석보다 안전하다.

단, `rule_code`/증거 키를 정하는 zone_type 매핑(`_rule_for_zone`)은 두 판정이
반드시 공유한다. `IncidentReducer`는 `IncidentKey`(rule_code 포함)로 OPEN과
RESOLVE를 같은 사건으로 묶으므로, 이 매핑이 갈라지면 OPEN은 나가는데 RESOLVE의
rule_code가 달라져 사건이 영원히 닫히지 않는다.

**공개 진입점도 성립/해소로 나눈다.** `evaluate_open(context)`은 관측 중인
차량의 `RuleContext`가 있어야 한다 — 자격 정보가 거기서 나오기 때문이다.
`resolve_closed(visits=..., zones=..., observed_at=...)`은 `RuleContext`도
`PhysicalVehicleSnapshot`도 요구하지 않는다 — `ZoneVisit` 자체에 이미
`physical_vehicle_id`가 있어서다. 이게 중요한 이유는 `ParkingPipeline`이
추적 소실 차량의 강제 종료 방문을 판정할 때 "마지막으로 본 스냅샷"에 의존하지
않아도 되기 때문이다(리뷰 지적, 445) — 예전에는 그 스냅샷 캐시가 차량 종료
시점에 먼저 지워져 버려서, 나중에 `prune()`이 그 방문을 강제 종료로 반환해도
스냅샷이 없어 판정 자체가 생략되고 사건이 영원히 안 닫히는 버그가 있었다.

구역 정의에 없는 zone_id를 가리키는 방문은 신호 없이 건너뛴다. 예외를 그대로
올리면 방문 하나 때문에 그 프레임의 모든 규칙·모든 차량 판정이 죽는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.parking.models import (
    IncidentKey,
    IncidentSignal,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import EV_ZONE_TYPES, ParkingZone, ZoneRegistry, ZoneType
from src.tracking.models import PhysicalVehicleId

DISABLED_ZONE_UNAUTHORIZED = "DISABLED_ZONE_UNAUTHORIZED"
EV_ZONE_UNAUTHORIZED = "EV_ZONE_UNAUTHORIZED"


@dataclass(frozen=True)
class _ZoneRule:
    """전용구역 하나가 어떤 위반 코드·증거 키로 판정되는지."""

    rule_code: str
    evidence_key: str


def _rule_for_zone(zone: ParkingZone) -> _ZoneRule | None:
    """이 구역이 판정 대상 전용구역이면 규칙을, 아니면 `None`을 반환한다.

    OPEN·RESOLVE 양쪽이 반드시 이 함수 하나만 거쳐야 한다 — 갈라지면
    IncidentReducer가 두 신호를 같은 사건으로 묶지 못한다(모듈 docstring 참고).
    """

    if zone.zone_type is ZoneType.DISABLED:
        return _ZoneRule(rule_code=DISABLED_ZONE_UNAUTHORIZED, evidence_key="isDisabledVehicle")
    if zone.zone_type in EV_ZONE_TYPES:
        return _ZoneRule(rule_code=EV_ZONE_UNAUTHORIZED, evidence_key="isElectric")
    return None


def evaluate_open(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """관측 중인 차량의 `INSIDE` 방문마다 위반 성립 신호를 만든다.

    자격 정보(`context.vehicle_context`)가 있어야 하므로 `RuleContext`를
    요구한다. `ENTERING`/`EXITING`/`OUTSIDE` 방문은 건너뛴다 — 성립도
    해소도 아직 결정되지 않았거나(진입·이탈 확인 중), 해소는 `resolve_closed`의
    몫이다.
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
        rule = _rule_for_zone(zone)
        if rule is None:
            continue
        signals.append(_evaluate_open(context, visit, zone, rule))
    return tuple(signals)


def resolve_closed(
    *, visits: tuple[ZoneVisit, ...], zones: ZoneRegistry, observed_at: datetime
) -> tuple[IncidentSignal, ...]:
    """방금 닫힌(`OUTSIDE`) 방문마다 해소 신호를 만든다.

    `RuleContext`도 `PhysicalVehicleSnapshot`도 요구하지 않는다 — `ZoneVisit`
    자체가 판정에 필요한 전부(`physical_vehicle_id`, `zone_id`, `exited_at`)를
    담고 있다. 추적이 끊긴 차량의 강제 종료 방문(`ParkingPipeline.prune()`
    반환값)도 마지막 스냅샷 없이 그대로 판정할 수 있다는 뜻이다.
    """

    signals: list[IncidentSignal] = []
    for visit in visits:
        if visit.state is not ZoneVisitState.OUTSIDE:
            continue
        zone = zones.get_or_none(visit.zone_id)
        if zone is None:
            continue
        rule = _rule_for_zone(zone)
        if rule is None:
            continue
        signals.append(
            _evaluate_resolve(
                physical_vehicle_id=visit.physical_vehicle_id,
                observed_at=observed_at,
                visit=visit,
                zone=zone,
                rule=rule,
            )
        )
    return tuple(signals)


def _evaluate_open(
    context: RuleContext, visit: ZoneVisit, zone: ParkingZone, rule: _ZoneRule
) -> IncidentSignal:
    """방문이 성립 중(`INSIDE`)일 때의 판정. 자격 정보로 위반 여부를 가른다."""

    vehicle_context = context.vehicle_context
    if vehicle_context is None:
        qualified = None
    elif rule.rule_code == DISABLED_ZONE_UNAUTHORIZED:
        qualified = vehicle_context.is_disabled_vehicle
    else:
        qualified = vehicle_context.is_electric
    # 자격이 확인되고 자격이 있으면 위반이 아니다 — matched=False로 RESOLVE를 연다.
    matched = qualified is not True
    # 자격을 모르면 확정하지 않는다. 백엔드 조회 재시도 동안 후보로만 유지된다.
    confirmable = qualified is False

    return _make_signal(
        physical_vehicle_id=context.vehicle.physical_vehicle_id,
        observed_at=context.observed_at,
        visit=visit,
        zone=zone,
        rule=rule,
        qualified=qualified,
        matched=matched,
        confirmable=confirmable,
    )


def _evaluate_resolve(
    *,
    physical_vehicle_id: PhysicalVehicleId,
    observed_at: datetime,
    visit: ZoneVisit,
    zone: ParkingZone,
    rule: _ZoneRule,
) -> IncidentSignal:
    """방문이 방금 닫혔을(`OUTSIDE`) 때의 판정.

    `vehicle_context`를 인자로 받지 않는다 — 방문이 끝났다는 사실 자체가
    해소 사유이고 자격과는 무관하다. 인자로 받지 않으면 실수로 자격 조건을
    여기 끼워 넣는 게 애초에 불가능하다.
    """

    return _make_signal(
        physical_vehicle_id=physical_vehicle_id,
        observed_at=observed_at,
        visit=visit,
        zone=zone,
        rule=rule,
        qualified=None,
        matched=False,
        confirmable=True,
    )


def _make_signal(
    *,
    physical_vehicle_id: PhysicalVehicleId,
    observed_at: datetime,
    visit: ZoneVisit,
    zone: ParkingZone,
    rule: _ZoneRule,
    qualified: bool | None,
    matched: bool,
    confirmable: bool,
) -> IncidentSignal:
    return IncidentSignal(
        key=IncidentKey(
            # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
            physical_vehicle_id=physical_vehicle_id,
            rule_code=rule.rule_code,
            zone_visit_id=visit.visit_id,
            zone_id=visit.zone_id,
        ),
        matched=matched,
        confirmable=confirmable,
        observed_at=observed_at,
        evidence={
            rule.evidence_key: qualified,
            "zoneType": zone.zone_type.value,
            "zoneNumber": zone.zone_number,
            "zoneVisitEnteredAt": None if visit.entered_at is None else visit.entered_at.isoformat(),
            "zoneVisitExitedAt": None if visit.exited_at is None else visit.exited_at.isoformat(),
        },
    )

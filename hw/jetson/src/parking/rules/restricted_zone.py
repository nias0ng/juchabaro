"""장애인·전기차 전용구역의 차량 자격 의미와 무자격 점유 술어를 평가한다.

구역 종류별 자격 속성 선택은 ``qualification_for_zone``이 소유하며,
``evaluate``는 이를 camera 기반 ZoneVisit의 IncidentSignal로 변환한다.
이 모듈은 상태를 소유하지 않는다. 방문 수명과 확인·해소 timer는 각각
``ZoneVisitTracker``와 ``IncidentReducer``가 소유한다.
"""

from __future__ import annotations

from src.domain.models import ObservationState
from src.parking.models import (
    IncidentKey,
    IncidentSignal,
    IncidentSignalValue,
    ZoneType,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.session.models import SessionContext

DISABLED_ZONE_UNAUTHORIZED = "DISABLED_ZONE_UNAUTHORIZED"
EV_ZONE_UNAUTHORIZED = "EV_ZONE_UNAUTHORIZED"


def qualification_for_zone(
    zone_type: ZoneType,
    session_context: SessionContext | None,
) -> bool | None:
    """전용구역 종류에 대한 차량 자격 여부를 반환한다.

    ``True``와 ``False``는 각각 자격 있음과 없음을, ``None``은 authoritative
    context 또는 필요한 자격 값이 없어 판정할 수 없음을 뜻한다. 지원하지 않는
    zone type에는 ``ValueError``를 발생시킨다.
    """

    if zone_type is ZoneType.DISABLED:
        return (
            None
            if session_context is None
            else session_context.is_disabled_vehicle
        )
    if zone_type is ZoneType.EV_CHARGING:
        return None if session_context is None else session_context.is_electric
    raise ValueError(f"차량 자격을 지원하지 않는 zone type입니다: {zone_type.value}")


def evaluate(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """현재 차량의 active restricted-zone 방문을 모두 독립 평가한다."""

    signals: list[IncidentSignal] = []
    vehicle_id = context.vehicle.physical_vehicle_id
    for visit in context.active_zone_visits:
        if visit.physical_vehicle_id != vehicle_id:
            continue

        zone = context.zones.get_or_none(visit.zone_id)
        if zone is None:
            # 삭제되거나 불완전한 registry로 기존 사건을 거짓 해소하지
            # 않는다.
            for rule_code in (DISABLED_ZONE_UNAUTHORIZED, EV_ZONE_UNAUTHORIZED):
                signals.append(
                    _unknown_signal(
                        context,
                        visit,
                        rule_code,
                        reason="ZONE_DEFINITION_UNAVAILABLE",
                    )
                )
            continue

        if zone.zone_type is ZoneType.DISABLED:
            rule_code = DISABLED_ZONE_UNAUTHORIZED
            evidence_key = "isDisabledVehicle"
        elif zone.zone_type is ZoneType.EV_CHARGING:
            rule_code = EV_ZONE_UNAUTHORIZED
            evidence_key = "isElectric"
        else:
            continue

        qualified = qualification_for_zone(
            zone.zone_type,
            context.session_context,
        )

        if (
            context.observation.state is not ObservationState.OBSERVED
            or context.vehicle.observation.state is not ObservationState.OBSERVED
            or visit.observation.state is not ObservationState.OBSERVED
            or visit.state is not ZoneVisitState.INSIDE
            or qualified is None
        ):
            signals.append(
                _unknown_signal(
                    context,
                    visit,
                    rule_code,
                    reason="REQUIRED_INPUT_UNAVAILABLE",
                    extra_evidence={evidence_key: qualified},
                )
            )
            continue

        value = (
            IncidentSignalValue.NOT_MATCHED
            if qualified
            else IncidentSignalValue.MATCHED
        )
        signals.append(
            IncidentSignal(
                key=IncidentKey.for_zone_visit(visit.visit_id, rule_code),
                value=value,
                confirmable=value is IncidentSignalValue.MATCHED,
                observed_at=context.observed_at,
                evidence={
                    evidence_key: qualified,
                    "zoneId": visit.zone_id,
                    "zoneType": zone.zone_type.value,
                },
            )
        )

    return tuple(signals)


def _unknown_signal(
    context: RuleContext,
    visit: ZoneVisit,
    rule_code: str,
    *,
    reason: str,
    extra_evidence: dict[str, object] | None = None,
) -> IncidentSignal:
    evidence: dict[str, object] = {
        "reason": reason,
        "zoneId": visit.zone_id,
        "zoneVisitState": visit.state.value,
    }
    if extra_evidence is not None:
        evidence.update(extra_evidence)
    return IncidentSignal(
        key=IncidentKey.for_zone_visit(visit.visit_id, rule_code),
        value=IncidentSignalValue.UNKNOWN,
        confirmable=False,
        observed_at=context.observed_at,
        evidence=evidence,
    )

"""장애인·전기차 전용구역의 무자격 점유 술어를 평가한다.

이 모듈은 상태를 소유하지 않는다. 방문 수명과 확인·해소 timer는 각각
``ZoneVisitTracker``와 ``IncidentReducer``가 소유하며, 여기서는 현재 입력을
``MATCHED / NOT_MATCHED / UNKNOWN`` 중 하나로만 해석한다.
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

DISABLED_ZONE_UNAUTHORIZED = "DISABLED_ZONE_UNAUTHORIZED"
EV_ZONE_UNAUTHORIZED = "EV_ZONE_UNAUTHORIZED"


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
            qualified = (
                None
                if context.session_context is None
                else context.session_context.is_disabled_vehicle
            )
        elif zone.zone_type is ZoneType.EV_CHARGING:
            rule_code = EV_ZONE_UNAUTHORIZED
            evidence_key = "isElectric"
            qualified = (
                None
                if context.session_context is None
                else context.session_context.is_electric
            )
        else:
            continue

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

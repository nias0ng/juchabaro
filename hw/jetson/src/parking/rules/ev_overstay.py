"""EV 충전구역 방문의 허용 점유 시간 초과 술어를 평가한다.

허용 시간 정책과 방문 관측이 유효할 때만 ZoneVisit이 누적한 trusted
``PRESENT`` 점유 시간을 비교한다. wall-clock은 사용하지 않으므로 UNKNOWN,
``EXITING``과 capture·inference stall 구간은 초과 판정을 앞당기지 않는다.
"""

from __future__ import annotations

from src.domain.models import ObservationState
from src.parking.models import (
    IncidentKey,
    IncidentSignal,
    IncidentSignalValue,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import EV_ZONE_TYPES

EV_OVERSTAY = "EV_OVERSTAY"


def evaluate(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """현재 차량의 active EV 방문마다 초과 여부를 명시적으로 반환한다."""

    signals: list[IncidentSignal] = []
    vehicle_id = context.vehicle.physical_vehicle_id
    for visit in context.active_zone_visits:
        if visit.physical_vehicle_id != vehicle_id:
            continue

        zone = context.zones.get_or_none(visit.zone_id)
        if zone is None:
            signals.append(_unknown_signal(context, visit, "ZONE_DEFINITION_UNAVAILABLE"))
            continue
        if zone.zone_type not in EV_ZONE_TYPES:
            continue

        if (
            context.observation.state is not ObservationState.OBSERVED
            or context.vehicle.observation.state is not ObservationState.OBSERVED
            or visit.observation.state is not ObservationState.OBSERVED
            or visit.state is not ZoneVisitState.INSIDE
            or zone.allowed_duration_seconds is None
        ):
            signals.append(_unknown_signal(context, visit, "REQUIRED_INPUT_UNAVAILABLE"))
            continue

        trusted_occupancy_seconds = visit.entry_trusted_seconds
        matched = trusted_occupancy_seconds >= zone.allowed_duration_seconds
        signals.append(
            IncidentSignal(
                key=IncidentKey.for_zone_visit(visit.visit_id, EV_OVERSTAY),
                value=(
                    IncidentSignalValue.MATCHED
                    if matched
                    else IncidentSignalValue.NOT_MATCHED
                ),
                confirmable=matched,
                observed_at=context.observed_at,
                evidence={
                    "trustedOccupancySeconds": trusted_occupancy_seconds,
                    "allowedDurationSeconds": zone.allowed_duration_seconds,
                    "zoneId": visit.zone_id,
                    "zoneType": zone.zone_type.value,
                },
            )
        )

    return tuple(signals)


def _unknown_signal(
    context: RuleContext, visit: ZoneVisit, reason: str
) -> IncidentSignal:
    return IncidentSignal(
        key=IncidentKey.for_zone_visit(visit.visit_id, EV_OVERSTAY),
        value=IncidentSignalValue.UNKNOWN,
        confirmable=False,
        observed_at=context.observed_at,
        evidence={
            "reason": reason,
            "zoneId": visit.zone_id,
            "zoneVisitState": visit.state.value,
        },
    )

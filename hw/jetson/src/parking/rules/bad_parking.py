"""차량 범위의 불량주차·구역 외·통행로 침범 술어를 독립 평가한다.

최신 geometry 결과인 ``RuleContext.parking_assignment``가 술어 입력이다.
``ParkingEpisode``의 저장된 assignment는 감사 snapshot일 뿐 재평가에 쓰지 않고,
episode의 ``PARKED`` 상태만 새 Incident의 OPEN eligibility를 결정한다.
한 주차면에 배정됐더라도 차량 footprint의 1위 주차면 포함률이 정책값보다
낮으면 주차면 밖으로 튀어나온 불량 주차로 평가한다.
"""

from __future__ import annotations

from src.domain.models import ObservationState
from src.parking.models import (
    AssignmentState,
    IncidentKey,
    IncidentSignal,
    IncidentSignalValue,
    ParkingState,
    ZoneType,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext

BAD_PARKING = "BAD_PARKING"
OUT_OF_ZONE = "OUT_OF_ZONE"
AISLE_BLOCK = "AISLE_BLOCK"


def evaluate(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """서로 우선순위를 두지 않고 세 규칙의 현재 값을 모두 반환한다."""

    if not _frame_is_observed(context):
        return tuple(_unknown(context, code, "OBSERVATION_UNAVAILABLE") for code in _RULES)

    if (
        context.parking_episode is not None
        and context.parking_episode.observation.state
        is not ObservationState.OBSERVED
    ):
        return tuple(
            _unknown(context, code, "PARKING_MOTION_DEPENDENCY_UNAVAILABLE")
            for code in _RULES
        )

    if (
        context.parking_episode is not None
        and context.parking_episode.state is ParkingState.MOVE_PENDING
    ):
        return tuple(
            _unknown(context, code, "MOVEMENT_CONFIRMATION_PENDING")
            for code in _RULES
        )

    parked = (
        context.parking_episode is not None
        and context.parking_episode.state is ParkingState.PARKED
    )

    bad_value, out_value = _assignment_predicates(context)
    aisle_value = _aisle_predicate(context)
    return (
        _signal(context, BAD_PARKING, bad_value, parked),
        _signal(context, OUT_OF_ZONE, out_value, parked),
        _signal(context, AISLE_BLOCK, aisle_value, parked),
    )


_RULES = (BAD_PARKING, OUT_OF_ZONE, AISLE_BLOCK)


def _frame_is_observed(context: RuleContext) -> bool:
    return (
        context.observation.state is ObservationState.OBSERVED
        and context.vehicle.observation.state is ObservationState.OBSERVED
    )


def _assignment_predicates(
    context: RuleContext,
) -> tuple[IncidentSignalValue, IncidentSignalValue]:
    assignment = context.parking_assignment
    if assignment is None:
        return IncidentSignalValue.UNKNOWN, IncidentSignalValue.UNKNOWN
    if assignment.state is AssignmentState.AMBIGUOUS:
        return IncidentSignalValue.MATCHED, IncidentSignalValue.NOT_MATCHED
    if assignment.state is AssignmentState.UNASSIGNED:
        return IncidentSignalValue.NOT_MATCHED, IncidentSignalValue.MATCHED
    if assignment.confidence < context.bad_parking_min_primary_overlap_ratio:
        return IncidentSignalValue.MATCHED, IncidentSignalValue.NOT_MATCHED
    return IncidentSignalValue.NOT_MATCHED, IncidentSignalValue.NOT_MATCHED


def _aisle_predicate(context: RuleContext) -> IncidentSignalValue:
    uncertain = False
    vehicle_id = context.vehicle.physical_vehicle_id
    for visit in context.active_zone_visits:
        if visit.physical_vehicle_id != vehicle_id:
            continue
        zone = context.zones.get_or_none(visit.zone_id)
        if zone is None:
            uncertain = True
            continue
        if zone.zone_type is not ZoneType.AISLE:
            continue
        if (
            visit.observation.state is not ObservationState.OBSERVED
            or visit.state is not ZoneVisitState.INSIDE
        ):
            uncertain = True
            continue
        return IncidentSignalValue.MATCHED
    return IncidentSignalValue.UNKNOWN if uncertain else IncidentSignalValue.NOT_MATCHED


def _signal(
    context: RuleContext,
    rule_code: str,
    value: IncidentSignalValue,
    parked: bool,
) -> IncidentSignal:
    assignment = context.parking_assignment
    return IncidentSignal(
        key=IncidentKey.for_physical_vehicle(
            context.vehicle.physical_vehicle_id, rule_code
        ),
        value=value,
        confirmable=value is IncidentSignalValue.MATCHED and parked,
        observed_at=context.observed_at,
        evidence={
            "assignmentState": None if assignment is None else assignment.state.value,
            "assignmentZoneId": None if assignment is None else assignment.zone_id,
            "assignmentConfidence": (
                None if assignment is None else assignment.confidence
            ),
            "badParkingMinPrimaryOverlapRatio": (
                context.bad_parking_min_primary_overlap_ratio
            ),
            "parkingState": (
                None
                if context.parking_episode is None
                else context.parking_episode.state.value
            ),
        },
    )


def _unknown(context: RuleContext, rule_code: str, reason: str) -> IncidentSignal:
    return IncidentSignal(
        key=IncidentKey.for_physical_vehicle(
            context.vehicle.physical_vehicle_id, rule_code
        ),
        value=IncidentSignalValue.UNKNOWN,
        confirmable=False,
        observed_at=context.observed_at,
        evidence={"reason": reason},
    )

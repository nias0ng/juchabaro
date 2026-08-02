"""확인된 subject→victim 차단 관계를 이중주차 Incident 신호로 투영한다.

관계 후보는 같은 IncidentKey의 local Candidate만 만들 수 있고, 관계가
``BLOCKING``으로 확인된 뒤에만 confirmable하다. 관계의 terminal 처리는
reducer의 ``terminate_blocking_relation`` 직접 입력이 담당한다.
"""

from __future__ import annotations

from src.domain.models import ObservationState
from src.parking.models import (
    BlockingRelation,
    BlockingRelationState,
    IncidentKey,
    IncidentSignal,
    IncidentSignalValue,
)
from src.parking.rules.models import RuleContext

DOUBLE_PARKING = "DOUBLE_PARKING"


def evaluate(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """현재 차량이 subject인 nonterminal 차단 관계를 독립 평가한다."""

    signals: list[IncidentSignal] = []
    subject_id = context.vehicle.physical_vehicle_id
    for relation in context.blocking_relations:
        if relation.subject_physical_vehicle_id != subject_id:
            continue
        if relation.state in {
            BlockingRelationState.RESOLVED,
            BlockingRelationState.CANCELED,
        }:
            continue
        signals.append(_evaluate_relation(context, relation))
    return tuple(signals)


def _evaluate_relation(
    context: RuleContext, relation: BlockingRelation
) -> IncidentSignal:
    if (
        context.observation.state is not ObservationState.OBSERVED
        or context.vehicle.observation.state is not ObservationState.OBSERVED
        or relation.observation.state is not ObservationState.OBSERVED
        or relation.state is BlockingRelationState.CLEAR_PENDING
    ):
        value = IncidentSignalValue.UNKNOWN
        confirmable = False
    elif relation.state is BlockingRelationState.BLOCKING:
        value = IncidentSignalValue.MATCHED
        confirmable = True
    else:
        # Relation CANDIDATE와 Incident CANDIDATE가 같은 ID로 이어지되, 관계
        # confirmer를 우회해 OPEN하지 않도록 한다.
        value = IncidentSignalValue.MATCHED
        confirmable = False

    return IncidentSignal(
        key=IncidentKey.for_blocking_relation(
            relation.blocking_relation_id, DOUBLE_PARKING
        ),
        value=value,
        confirmable=confirmable,
        observed_at=context.observed_at,
        evidence={
            "subjectPhysicalVehicleId": str(relation.subject_physical_vehicle_id),
            "victimPhysicalVehicleId": str(relation.victim_physical_vehicle_id),
            "egressZoneId": relation.egress_zone_id,
            "blockingRelationState": relation.state.value,
        },
    )

"""lifecycle 상태를 만들지 않고 geometry evidence의 공간 위반을 평가한다.

Assignment와 위반은 하나의 immutable ``PlacementEvidence``를 서로 독립적으로
해석한다. 이 evaluator는 삼상태 signal만 만들며 confirm/clear lifecycle은
``IncidentReducer``만 소유한다.
"""

from __future__ import annotations

from src.domain.models import ObservationState
from src.parking.models import (
    IncidentKey,
    IncidentSignal,
    IncidentSignalValue,
    IncidentZoneContext,
    ParkingState,
    ZoneType,
    ZoneVisitState,
)
from src.parking.parking_eligibility import ParkingEligibilityValue
from src.parking.rules.models import RuleContext

BAD_PARKING = "BAD_PARKING"
OUT_OF_ZONE = "OUT_OF_ZONE"
AISLE_BLOCK = "AISLE_BLOCK"

_RULES = (BAD_PARKING, OUT_OF_ZONE, AISLE_BLOCK)


def evaluate(context: RuleContext) -> tuple[IncidentSignal, ...]:
    """모든 placement rule의 독립적인 삼상태 signal을 반환한다."""

    if context.parking_eligibility.value is not ParkingEligibilityValue.ELIGIBLE:
        return tuple(
            _unknown(
                context,
                code,
                f"PARKING_{context.parking_eligibility.reason}",
            )
            for code in _RULES
        )

    if not _frame_is_observed(context):
        return tuple(
            _unknown(context, code, "OBSERVATION_UNAVAILABLE")
            for code in _RULES
        )
    if (
        context.parking_motion_observation.state is not ObservationState.OBSERVED
        or (
            context.parking_episode is not None
            and context.parking_episode.observation.state
            is not ObservationState.OBSERVED
        )
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
    bad_value, out_value, bad_reasons, out_reasons = _placement_predicates(
        context
    )
    aisle_value, aisle_zone_context = _aisle_predicate(context)
    return (
        _signal(
            context,
            BAD_PARKING,
            bad_value,
            parked,
            reasons=bad_reasons,
        ),
        _signal(
            context,
            OUT_OF_ZONE,
            out_value,
            parked,
            reasons=out_reasons,
        ),
        _signal(
            context,
            AISLE_BLOCK,
            aisle_value,
            parked,
            open_zone_context=aisle_zone_context,
        ),
    )


def _frame_is_observed(context: RuleContext) -> bool:
    return (
        context.observation.state is ObservationState.OBSERVED
        and context.vehicle.observation.state is ObservationState.OBSERVED
    )


def _placement_predicates(
    context: RuleContext,
) -> tuple[
    IncidentSignalValue,
    IncidentSignalValue,
    tuple[str, ...],
    tuple[str, ...],
]:
    evidence = context.placement_evidence
    if evidence is None:
        return (
            IncidentSignalValue.UNKNOWN,
            IncidentSignalValue.UNKNOWN,
            (),
            (),
        )
    if (
        evidence.spot_union_overlap_ratio
        < context.out_of_zone_min_spot_overlap_ratio
    ):
        return (
            IncidentSignalValue.NOT_MATCHED,
            IncidentSignalValue.MATCHED,
            (),
            ("INSUFFICIENT_SPOT_UNION_OVERLAP",),
        )

    bad_reasons: list[str] = []
    if (
        evidence.primary_overlap_ratio
        < context.bad_parking_min_primary_overlap_ratio
    ):
        bad_reasons.append("LOW_PRIMARY_OVERLAP")
    if (
        evidence.secondary_overlap_ratio
        >= context.bad_parking_min_secondary_overlap_ratio
    ):
        bad_reasons.append("MULTI_SPOT_OVERLAP")
    return (
        (
            IncidentSignalValue.MATCHED
            if bad_reasons
            else IncidentSignalValue.NOT_MATCHED
        ),
        IncidentSignalValue.NOT_MATCHED,
        tuple(bad_reasons),
        (),
    )


def _aisle_predicate(
    context: RuleContext,
) -> tuple[IncidentSignalValue, IncidentZoneContext | None]:
    """복도 점유 술어와 OPEN에 고정할 대표 AISLE 문맥을 반환한다."""

    uncertain = False
    matched_zone_ids = []
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
        matched_zone_ids.append(visit.zone_id)
    if matched_zone_ids:
        return (
            IncidentSignalValue.MATCHED,
            IncidentZoneContext(zone_id=min(matched_zone_ids, key=int)),
        )
    return (
        (
            IncidentSignalValue.UNKNOWN
            if uncertain
            else IncidentSignalValue.NOT_MATCHED
        ),
        None,
    )


def _signal(
    context: RuleContext,
    rule_code: str,
    value: IncidentSignalValue,
    parked: bool,
    *,
    reasons: tuple[str, ...] = (),
    open_zone_context: IncidentZoneContext | None = None,
) -> IncidentSignal:
    confirmable = value is IncidentSignalValue.MATCHED and parked
    if rule_code == BAD_PARKING and confirmable:
        open_zone_context = _bad_parking_zone_context(context)
    elif not confirmable:
        open_zone_context = None
    return IncidentSignal(
        key=IncidentKey.for_physical_vehicle(
            context.vehicle.physical_vehicle_id,
            rule_code,
        ),
        value=value,
        confirmable=confirmable,
        observed_at=context.observed_at,
        evidence=_signal_evidence(context, reasons=reasons),
        open_zone_context=open_zone_context,
    )


def _bad_parking_zone_context(
    context: RuleContext,
) -> IncidentZoneContext | None:
    """PARKED snapshot에서 대표 구역과 유효한 추가 침범 구역을 뽑는다."""

    placement = context.placement_evidence
    if placement is None or not placement.candidate_overlaps:
        return None
    return IncidentZoneContext(
        zone_id=placement.candidate_overlaps[0].zone_id,
        related_zone_ids=tuple(
            candidate.zone_id
            for candidate in placement.candidate_overlaps[1:3]
            if candidate.overlap_ratio
            >= context.bad_parking_min_secondary_overlap_ratio
        ),
    )


def _unknown(context: RuleContext, rule_code: str, reason: str) -> IncidentSignal:
    return IncidentSignal(
        key=IncidentKey.for_physical_vehicle(
            context.vehicle.physical_vehicle_id,
            rule_code,
        ),
        value=IncidentSignalValue.UNKNOWN,
        confirmable=False,
        observed_at=context.observed_at,
        evidence=_signal_evidence(context, reason=reason),
    )


def _signal_evidence(
    context: RuleContext,
    *,
    reasons: tuple[str, ...] = (),
    reason: str | None = None,
) -> dict[str, object]:
    assignment = context.parking_assignment
    placement = context.placement_evidence
    result: dict[str, object] = {
        "assignmentState": None if assignment is None else assignment.state.value,
        "assignmentZoneId": None if assignment is None else assignment.zone_id,
        "assignmentConfidence": (
            None if assignment is None else assignment.confidence
        ),
        "placementEvidenceSource": (
            None
            if context.placement_evidence_source is None
            else context.placement_evidence_source.value
        ),
        "zoneDefinitionVersion": (
            None if placement is None else placement.zone_definition_version
        ),
        "primaryZoneId": None if placement is None else placement.primary_zone_id,
        "primaryOverlapRatio": (
            None if placement is None else placement.primary_overlap_ratio
        ),
        "secondaryZoneId": (
            None if placement is None else placement.secondary_zone_id
        ),
        "secondaryOverlapRatio": (
            None if placement is None else placement.secondary_overlap_ratio
        ),
        "dominanceGap": None if placement is None else placement.dominance_gap,
        "spotUnionOverlapRatio": (
            None if placement is None else placement.spot_union_overlap_ratio
        ),
        "outsideSpotOverlapRatio": (
            None if placement is None else placement.outside_spot_overlap_ratio
        ),
        "candidateOverlaps": (
            ()
            if placement is None
            else tuple(
                {
                    "zoneId": candidate.zone_id,
                    "overlapRatio": candidate.overlap_ratio,
                }
                for candidate in placement.candidate_overlaps
            )
        ),
        "badParkingMinPrimaryOverlapRatio": (
            context.bad_parking_min_primary_overlap_ratio
        ),
        "badParkingMinSecondaryOverlapRatio": (
            context.bad_parking_min_secondary_overlap_ratio
        ),
        "outOfZoneMinSpotOverlapRatio": (
            context.out_of_zone_min_spot_overlap_ratio
        ),
        "parkingState": (
            None
            if context.parking_episode is None
            else context.parking_episode.state.value
        ),
        "reasons": reasons,
    }
    if reason is not None:
        result["reason"] = reason
    return result

"""EV 충전구역의 확정 주차시간 초과 술어를 평가한다.

같은 EV 구역에 확정된 ``ParkingEpisode.PARKED``의 ``parked_at``부터 현재
관측 시각까지를 허용 시간과 비교한다. 백엔드가 PARKED 전이 시 저장하는
``ParkingSession.parkedAt``과 같은 원천 시각을 사용하되, Incident 생성과
증거 수집의 책임은 Jetson에 남긴다.
"""

from __future__ import annotations

from src.domain.models import ObservationState
from src.parking.models import (
    IncidentKey,
    IncidentSignal,
    IncidentSignalValue,
    ParkingState,
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

        episode = context.parking_episode
        assignment = None if episode is None else episode.assignment
        parking_evidence = {
            "parkingState": None if episode is None else episode.state.value,
            "parkingAssignmentZoneId": (
                None if assignment is None else assignment.zone_id
            ),
            "parkedAt": (
                None
                if episode is None or episode.parked_at is None
                else episode.parked_at.isoformat()
            ),
        }

        if (
            context.observation.state is not ObservationState.OBSERVED
            or context.vehicle.observation.state is not ObservationState.OBSERVED
            or visit.observation.state is not ObservationState.OBSERVED
            or visit.state is not ZoneVisitState.INSIDE
            or context.parking_motion_observation.state
            is not ObservationState.OBSERVED
            or zone.allowed_duration_seconds is None
        ):
            signals.append(
                _unknown_signal(
                    context,
                    visit,
                    "REQUIRED_INPUT_UNAVAILABLE",
                    extra_evidence=parking_evidence,
                )
            )
            continue

        if (
            episode is not None
            and episode.state
            in {ParkingState.PARKED, ParkingState.MOVE_PENDING}
            and episode.observation.state is not ObservationState.OBSERVED
        ):
            signals.append(
                _unknown_signal(
                    context,
                    visit,
                    "PARKING_EPISODE_OBSERVATION_UNAVAILABLE",
                    extra_evidence=parking_evidence,
                )
            )
            continue

        if episode is not None and episode.state is ParkingState.MOVE_PENDING:
            signals.append(
                _unknown_signal(
                    context,
                    visit,
                    "MOVEMENT_CONFIRMATION_PENDING",
                    extra_evidence=parking_evidence,
                )
            )
            continue

        parked_in_visited_zone = (
            episode is not None
            and episode.state is ParkingState.PARKED
            and assignment is not None
            and assignment.zone_id == visit.zone_id
        )
        if not parked_in_visited_zone:
            signals.append(
                IncidentSignal(
                    key=IncidentKey.for_zone_visit(visit.visit_id, EV_OVERSTAY),
                    value=IncidentSignalValue.NOT_MATCHED,
                    confirmable=False,
                    observed_at=context.observed_at,
                    evidence={
                        **parking_evidence,
                        "allowedDurationSeconds": zone.allowed_duration_seconds,
                        "zoneId": visit.zone_id,
                        "zoneType": zone.zone_type.value,
                        "reason": "PARKING_NOT_CONFIRMED_IN_VISITED_ZONE",
                    },
                )
            )
            continue

        assert episode.parked_at is not None
        parked_duration_seconds = (
            context.observed_at - episode.parked_at
        ).total_seconds()
        if parked_duration_seconds < 0.0:
            signals.append(
                _unknown_signal(
                    context,
                    visit,
                    "PARKED_AT_AFTER_OBSERVED_AT",
                    extra_evidence=parking_evidence,
                )
            )
            continue

        matched = parked_duration_seconds >= zone.allowed_duration_seconds
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
                    "parkedDurationSeconds": parked_duration_seconds,
                    "allowedDurationSeconds": zone.allowed_duration_seconds,
                    "zoneId": visit.zone_id,
                    "zoneType": zone.zone_type.value,
                    **parking_evidence,
                },
            )
        )

    return tuple(signals)


def _unknown_signal(
    context: RuleContext,
    visit: ZoneVisit,
    reason: str,
    *,
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
        key=IncidentKey.for_zone_visit(visit.visit_id, EV_OVERSTAY),
        value=IncidentSignalValue.UNKNOWN,
        confirmable=False,
        observed_at=context.observed_at,
        evidence=evidence,
    )

"""상태 없는 RuleEvaluator가 받는 ephemeral 평가 view.

규칙은 현재 술어를 `MATCHED / NOT_MATCHED / UNKNOWN`으로만 계산한다.
confirm·clear 시간과 Incident lifecycle은 IncidentReducer의 책임이며 이 view를
영속 event log로 저장하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from src.domain.models import ObservationStatus, require_aware
from src.parking.models import (
    BlockingRelation,
    ParkingAssignment,
    ParkingEpisode,
    ZoneVisit,
)
from src.session.models import SessionContext
from src.tracking.models import PhysicalVehicleSnapshot

if TYPE_CHECKING:
    from src.parking.zone_registry import ZoneRegistry


@dataclass(frozen=True, kw_only=True)
class RuleContext:
    """한 시점의 geometry·parking·authoritative context 평가 입력."""

    vehicle: PhysicalVehicleSnapshot
    observation: ObservationStatus
    session_context: SessionContext | None
    active_zone_visits: tuple[ZoneVisit, ...]
    parking_episode: ParkingEpisode | None
    parking_assignment: ParkingAssignment | None
    blocking_relations: tuple[BlockingRelation, ...]
    zones: ZoneRegistry
    observed_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if self.parking_episode is not None:
            if self.parking_episode.physical_vehicle_id != self.vehicle.physical_vehicle_id:
                raise ValueError("parking_episode must belong to RuleContext vehicle")

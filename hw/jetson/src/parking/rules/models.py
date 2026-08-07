"""상태 없는 RuleEvaluator가 받는 ephemeral 평가 view.

규칙은 현재 술어를 `MATCHED / NOT_MATCHED / UNKNOWN`으로만 계산한다.
confirm·clear 시간과 Incident lifecycle은 IncidentReducer의 책임이며 이 view를
영속 event log로 저장하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import math
from typing import TYPE_CHECKING

from src.domain.models import ObservationStatus, require_aware
from src.parking.models import (
    BlockingRelation,
    BlockingRelationId,
    EgressBlockingEvidence,
    ParkingAssignment,
    ParkingEpisode,
    PlacementEvidence,
    PlacementEvidenceSource,
    ZoneVisit,
)
from src.parking.parking_eligibility import (
    ELIGIBLE_PARKING,
    ParkingEligibilityDecision,
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
    # bbox/identity 관측과 별개인 MotionEstimator dependency 상태다. active
    # ParkingEpisode가 없는 frame에도 placement Incident timer를 안전하게 멈춘다.
    parking_motion_observation: ObservationStatus
    session_context: SessionContext | None
    active_zone_visits: tuple[ZoneVisit, ...]
    parking_episode: ParkingEpisode | None
    parking_assignment: ParkingAssignment | None
    placement_evidence: PlacementEvidence | None
    placement_evidence_source: PlacementEvidenceSource | None
    blocking_relations: tuple[BlockingRelation, ...]
    zones: ZoneRegistry
    bad_parking_min_primary_overlap_ratio: float
    bad_parking_min_secondary_overlap_ratio: float
    out_of_zone_min_spot_overlap_ratio: float
    observed_at: datetime
    # 현재 frame의 ephemeral geometry 근거다. relation·Incident
    # lifecycle이나 새 상태축을 소유하지 않는다.
    blocking_evidence: Mapping[
        BlockingRelationId, EgressBlockingEvidence
    ] = field(default_factory=dict)
    parking_eligibility: ParkingEligibilityDecision = ELIGIBLE_PARKING

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        for name in (
            "bad_parking_min_primary_overlap_ratio",
            "bad_parking_min_secondary_overlap_ratio",
            "out_of_zone_min_spot_overlap_ratio",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between 0 and 1")
        if (self.placement_evidence is None) != (
            self.placement_evidence_source is None
        ):
            raise ValueError(
                "placement evidence and its source must be provided together"
            )
        if self.parking_episode is not None:
            if self.parking_episode.physical_vehicle_id != self.vehicle.physical_vehicle_id:
                raise ValueError("parking_episode must belong to RuleContext vehicle")

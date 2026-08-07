"""현재 위치에서 새 주차 행위 판정을 시작해도 되는지 계산한다.

폴리곤과 ZoneVisit 정책은 이 모듈이 해석하고, ParkingEpisodeTracker에는
정규화한 삼상태 결정만 전달한다. 기존 PARKED 행위의 종료는 이 결정이 아니라
motion·physical exit owner가 계속 담당한다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
import math

from src.domain.models import ObservationState, ObservationStatus
from src.parking.geometry import overlap_ratio
from src.parking.models import ZoneDefinition, ZoneId, ZoneType, ZoneVisit
from src.tracking.models import PhysicalVehicleSnapshot


class ParkingEligibilityValue(str, Enum):
    """ParkingEpisode의 신규 정지 timer에 사용할 정책 신호."""

    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class ParkingEligibilityDecision:
    """주차 자격 결과와 운영 진단에 필요한 공간 근거."""

    value: ParkingEligibilityValue
    reason: str
    blocking_zone_id: ZoneId | None = None
    overlap_ratio: float | None = None

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("parking eligibility reason must not be empty")
        if self.overlap_ratio is not None and (
            not math.isfinite(self.overlap_ratio)
            or not 0.0 <= self.overlap_ratio <= 1.0
        ):
            raise ValueError("parking eligibility overlap ratio must be in [0, 1]")
        if self.value is ParkingEligibilityValue.ELIGIBLE and (
            self.blocking_zone_id is not None or self.overlap_ratio is not None
        ):
            raise ValueError("ELIGIBLE decision must not carry a blocking zone")


ELIGIBLE_PARKING = ParkingEligibilityDecision(
    value=ParkingEligibilityValue.ELIGIBLE,
    reason="OUTSIDE_ENTRY_EXIT",
)


def evaluate_parking_eligibility(
    *,
    vehicle: PhysicalVehicleSnapshot,
    observation: ObservationStatus,
    active_zone_visits: Sequence[ZoneVisit],
    zones: Sequence[ZoneDefinition],
    min_overlap_ratio: float,
) -> ParkingEligibilityDecision:
    """신뢰 geometry와 non-terminal visit으로 신규 주차 자격을 판정한다."""

    if not math.isfinite(min_overlap_ratio) or not 0.0 <= min_overlap_ratio <= 1.0:
        raise ValueError("min_overlap_ratio must be finite and in [0, 1]")
    if observation.state is not ObservationState.OBSERVED:
        return ParkingEligibilityDecision(
            value=ParkingEligibilityValue.UNKNOWN,
            reason="OBSERVATION_UNAVAILABLE",
        )

    entry_exit_zones = {
        zone.zone_id: zone
        for zone in zones
        if zone.zone_type is ZoneType.ENTRY_EXIT
    }
    overlaps = sorted(
        (
            (overlap_ratio(zone.polygon, vehicle.bbox), zone.zone_id)
            for zone in entry_exit_zones.values()
        ),
        key=lambda item: (-item[0], int(item[1])),
    )
    if overlaps and overlaps[0][0] >= min_overlap_ratio:
        ratio, zone_id = overlaps[0]
        return ParkingEligibilityDecision(
            value=ParkingEligibilityValue.INELIGIBLE,
            reason="ENTRY_EXIT_OVERLAP",
            blocking_zone_id=zone_id,
            overlap_ratio=ratio,
        )

    active_entry_exit_visits = sorted(
        (
            visit
            for visit in active_zone_visits
            if visit.zone_id in entry_exit_zones
        ),
        key=lambda visit: (visit.created_at, int(visit.zone_id)),
    )
    if active_entry_exit_visits:
        visit = active_entry_exit_visits[0]
        return ParkingEligibilityDecision(
            value=ParkingEligibilityValue.INELIGIBLE,
            reason="ENTRY_EXIT_VISIT_ACTIVE",
            blocking_zone_id=visit.zone_id,
            overlap_ratio=0.0,
        )
    return ELIGIBLE_PARKING

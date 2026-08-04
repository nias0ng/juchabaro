"""정상 차량 footprint 하나를 episode 소유 ParkingAssignment로 계산한다.

resolver 자체는 상태를 갖지 않는다. footprint가 authoritative할 만큼 안정적인지
호출자가 결정하고, 반환값을 해당 ``ParkingEpisode`` 안에 저장한다.
"""

from __future__ import annotations

import math

from src.parking.geometry import overlap_ratio
from src.parking.models import AssignmentState, NormalizedPolygon, ParkingAssignment
from src.parking.zone_registry import SPOT_ZONE_TYPES, ZoneRegistry
from src.tracking.models import BoundingBox, PhysicalVehicleSnapshot


NO_ELIGIBLE_ZONE = "NO_ELIGIBLE_ZONE"
AMBIGUOUS_ZONE_OVERLAP = "AMBIGUOUS_ZONE_OVERLAP"


def resolve(
    vehicle: PhysicalVehicleSnapshot,
    zones: ZoneRegistry,
    *,
    min_overlap_ratio: float,
    ambiguous_margin: float,
) -> ParkingAssignment:
    """정상 차량 sample의 대표 주차 위치 assignment를 반환한다.

    ``confidence``에는 가장 강한 spot overlap 근거를 기록한다. detector
    confidence와 공간 assignment confidence를 섞지 않으면서 모든 상태에
    결정론적인 값을 제공하기 위한 선택이다. ``min_overlap_ratio``는 1위
    구역의 배정 자격을 판단하고, 2위 구역은 기준 미만이어도 1위와의 차이가
    ``ambiguous_margin`` 이내인지 비교해 경계 걸침을 보존한다.
    """

    _validate_ratio(min_overlap_ratio, "min_overlap_ratio")
    _validate_ratio(ambiguous_margin, "ambiguous_margin")

    footprint = _bbox_polygon(vehicle.bbox)
    ranked = sorted(
        (
            (zone.zone_id, overlap_ratio(zone.polygon, vehicle.bbox))
            for zone in zones.all()
            if zone.zone_type in SPOT_ZONE_TYPES
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if not ranked or ranked[0][1] < min_overlap_ratio:
        return ParkingAssignment(
            state=AssignmentState.UNASSIGNED,
            representative_footprint=footprint,
            confidence=ranked[0][1] if ranked else 0.0,
            last_stable_at=vehicle.observed_at,
            unassigned_reason=NO_ELIGIBLE_ZONE,
        )

    top_zone_id, top_ratio = ranked[0]
    if len(ranked) >= 2 and top_ratio - ranked[1][1] <= ambiguous_margin:
        return ParkingAssignment(
            state=AssignmentState.AMBIGUOUS,
            representative_footprint=footprint,
            confidence=top_ratio,
            last_stable_at=vehicle.observed_at,
            unassigned_reason=AMBIGUOUS_ZONE_OVERLAP,
        )

    return ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        representative_footprint=footprint,
        confidence=top_ratio,
        last_stable_at=vehicle.observed_at,
        zone_id=top_zone_id,
    )


def _bbox_polygon(bbox: BoundingBox) -> NormalizedPolygon:
    return (
        (bbox.x1, bbox.y1),
        (bbox.x2, bbox.y1),
        (bbox.x2, bbox.y2),
        (bbox.x1, bbox.y2),
    )


def _validate_ratio(value: float, name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")

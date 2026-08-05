"""결정론적 PlacementEvidence와 ParkingAssignment 값을 계산한다.

이 모듈은 상태 없는 geometry owner이며 lifecycle을 만들지 않는다.
``ParkingEpisodeTracker``가 대표 assignment의 확정 시점을 소유하고,
RuleEvaluator는 같은 placement evidence를 독립적으로 해석한다.
"""

from __future__ import annotations

from datetime import datetime
import math

from src.parking.geometry import is_convex_polygon, polygon_overlap_ratio
from src.parking.models import (
    AssignmentState,
    NormalizedPolygon,
    ParkingAssignment,
    PlacementEvidence,
    ZoneOverlapEvidence,
)
from src.parking.zone_registry import SPOT_ZONE_TYPES, ZoneRegistry
from src.tracking.models import BoundingBox, PhysicalVehicleSnapshot


NO_ELIGIBLE_ZONE = "NO_ELIGIBLE_ZONE"
AMBIGUOUS_ZONE_OVERLAP = "AMBIGUOUS_ZONE_OVERLAP"
_RATIO_PRECISION_DIGITS = 12


def analyze(
    vehicle: PhysicalVehicleSnapshot,
    zones: ZoneRegistry,
) -> PlacementEvidence:
    """차량의 현재 detector footprint에 대한 공간 근거를 반환한다."""

    return analyze_footprint(
        _bbox_polygon(vehicle.bbox),
        observed_at=vehicle.observed_at,
        zones=zones,
    )


def analyze_footprint(
    footprint: NormalizedPolygon,
    *,
    observed_at: datetime,
    zones: ZoneRegistry,
) -> PlacementEvidence:
    """한 footprint의 주차면별 순위와 union/outside 비율을 반환한다."""

    if not is_convex_polygon(footprint):
        raise ValueError(
            "placement footprint는 넓이가 양수인 convex polygon이어야 합니다"
        )

    candidates = tuple(
        sorted(
            (
                ZoneOverlapEvidence(
                    zone_id=zone.zone_id,
                    overlap_ratio=_canonical_ratio(
                        polygon_overlap_ratio(
                            zone.polygon,
                            footprint,
                        )
                    ),
                )
                for zone in zones.all()
                if zone.zone_type in SPOT_ZONE_TYPES
            ),
            key=lambda item: (-item.overlap_ratio, int(item.zone_id)),
        )
    )
    primary = None if not candidates else candidates[0]
    secondary = None if len(candidates) < 2 else candidates[1]
    primary_ratio = 0.0 if primary is None else primary.overlap_ratio
    secondary_ratio = 0.0 if secondary is None else secondary.overlap_ratio

    # ZoneRegistry가 assignment 주차면의 내부 중첩을 금지한다. 공유 경계는
    # 넓이가 0이므로 각 overlap의 합을 spot union으로 사용할 수 있다.
    spot_union_ratio = _canonical_ratio(
        sum(item.overlap_ratio for item in candidates)
    )
    return PlacementEvidence(
        representative_footprint=footprint,
        zone_definition_version=zones.zone_definition_version,
        observed_at=observed_at,
        candidate_overlaps=candidates,
        primary_zone_id=None if primary is None else primary.zone_id,
        primary_overlap_ratio=primary_ratio,
        secondary_zone_id=None if secondary is None else secondary.zone_id,
        secondary_overlap_ratio=secondary_ratio,
        dominance_gap=_canonical_ratio(primary_ratio - secondary_ratio),
        spot_union_overlap_ratio=spot_union_ratio,
        outside_spot_overlap_ratio=_canonical_ratio(1.0 - spot_union_ratio),
    )


def assignment_from_evidence(
    evidence: PlacementEvidence,
    *,
    min_overlap_ratio: float,
    ambiguous_margin: float,
) -> ParkingAssignment:
    """placement evidence를 episode 소유 assignment 값으로 해석한다."""

    _validate_ratio(min_overlap_ratio, "min_overlap_ratio")
    _validate_ratio(ambiguous_margin, "ambiguous_margin")

    if evidence.primary_zone_id is None or (
        evidence.primary_overlap_ratio < min_overlap_ratio
    ):
        return ParkingAssignment(
            state=AssignmentState.UNASSIGNED,
            representative_footprint=evidence.representative_footprint,
            confidence=evidence.primary_overlap_ratio,
            last_stable_at=evidence.observed_at,
            unassigned_reason=NO_ELIGIBLE_ZONE,
        )

    if (
        evidence.secondary_zone_id is not None
        and evidence.dominance_gap <= ambiguous_margin
    ):
        return ParkingAssignment(
            state=AssignmentState.AMBIGUOUS,
            representative_footprint=evidence.representative_footprint,
            confidence=evidence.primary_overlap_ratio,
            last_stable_at=evidence.observed_at,
            unassigned_reason=AMBIGUOUS_ZONE_OVERLAP,
        )

    return ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        representative_footprint=evidence.representative_footprint,
        confidence=evidence.primary_overlap_ratio,
        last_stable_at=evidence.observed_at,
        zone_id=evidence.primary_zone_id,
    )


def resolve(
    vehicle: PhysicalVehicleSnapshot,
    zones: ZoneRegistry,
    *,
    min_overlap_ratio: float,
    ambiguous_margin: float,
) -> ParkingAssignment:
    """현재 차량의 assignment만 반환하는 호환 진입점이다."""

    return assignment_from_evidence(
        analyze(vehicle, zones),
        min_overlap_ratio=min_overlap_ratio,
        ambiguous_margin=ambiguous_margin,
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


def _clamp_ratio(value: float) -> float:
    return min(1.0, max(0.0, value))


def _canonical_ratio(value: float) -> float:
    """순위와 임계값 비교 전에 geometry 부동소수점 잡음을 제거한다."""

    return round(_clamp_ratio(value), _RATIO_PRECISION_DIGITS)

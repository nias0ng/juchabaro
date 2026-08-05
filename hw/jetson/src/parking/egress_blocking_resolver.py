"""egress aisle과 차량 footprint의 상태 없는 교차 근거를 계산한다.

AssignmentResolver와 같이 convex polygon 교차를 사용하지만,
주차면 배정과 출차 방해는 다른 정책이므로 evidence와 threshold를
공유하지 않는다. 이 값은 lifecycle이나 제9의 상태축이 아니다.
"""

from __future__ import annotations

from src.parking.geometry import (
    convex_polygon_intersection_area,
    is_convex_polygon,
    polygon_area,
)
from src.parking.models import (
    EgressAisleDefinition,
    EgressBlockingEvidence,
    NormalizedPolygon,
)
from src.tracking.models import BoundingBox


_RATIO_PRECISION_DIGITS = 12


def analyze(
    bbox: BoundingBox,
    egress_aisle: EgressAisleDefinition,
) -> EgressBlockingEvidence:
    """axis-aligned detector bbox를 convex footprint로 해석한다."""

    return analyze_footprint(_bbox_polygon(bbox), egress_aisle)


def analyze_footprint(
    footprint: NormalizedPolygon,
    egress_aisle: EgressAisleDefinition,
) -> EgressBlockingEvidence:
    """차량 포함률과 egress 점유율을 한 번의 교차로 계산한다."""

    if not is_convex_polygon(footprint):
        raise ValueError(
            "egress blocking footprint는 넓이가 양수인 "
            "convex polygon이어야 합니다"
        )
    footprint_area = polygon_area(footprint)
    egress_area = polygon_area(egress_aisle.polygon)
    intersection_area = convex_polygon_intersection_area(
        footprint,
        egress_aisle.polygon,
    )
    return EgressBlockingEvidence(
        egress_zone_id=egress_aisle.egress_zone_id,
        parking_zone_id=egress_aisle.parking_zone_id,
        representative_footprint=footprint,
        subject_overlap_ratio=_canonical_ratio(
            intersection_area / footprint_area
        ),
        egress_coverage_ratio=_canonical_ratio(
            intersection_area / egress_area
        ),
        intersection_area=round(intersection_area, _RATIO_PRECISION_DIGITS),
    )


def _bbox_polygon(bbox: BoundingBox) -> NormalizedPolygon:
    return (
        (bbox.x1, bbox.y1),
        (bbox.x2, bbox.y1),
        (bbox.x2, bbox.y2),
        (bbox.x1, bbox.y2),
    )


def _canonical_ratio(value: float) -> float:
    return round(min(1.0, max(0.0, value)), _RATIO_PRECISION_DIGITS)

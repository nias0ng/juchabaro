"""정본 zone polygon과 차량 bounding box의 기하 연산을 제공한다.

polygon은 ``parking.models.NormalizedPolygon``을 직접 사용한다. 좌표 검증은
``ZoneDefinition`` 같은 소유 domain model이 담당하고, 이 모듈은 결정론적인
기하 계산만 담당한다.
"""

from __future__ import annotations

from typing import Callable, Sequence

from src.parking.models import NormalizedPolygon
from src.tracking.models import BoundingBox


def bbox_area(bbox: BoundingBox) -> float:
    """bounding box의 정규화 면적을 반환한다."""

    return (bbox.x2 - bbox.x1) * (bbox.y2 - bbox.y1)


def bbox_center(bbox: BoundingBox) -> tuple[float, float]:
    """bounding box의 정규화 중심점을 반환한다."""

    return ((bbox.x1 + bbox.x2) / 2.0, (bbox.y1 + bbox.y2) / 2.0)


def _lerp_x(
    a: tuple[float, float], b: tuple[float, float], x: float
) -> tuple[float, float]:
    t = (x - a[0]) / (b[0] - a[0])
    return (x, a[1] + t * (b[1] - a[1]))


def _lerp_y(
    a: tuple[float, float], b: tuple[float, float], y: float
) -> tuple[float, float]:
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), y)


def _clip_half_plane(
    points: Sequence[tuple[float, float]],
    inside: Callable[[tuple[float, float]], bool],
    intersect: Callable[
        [tuple[float, float], tuple[float, float]], tuple[float, float]
    ],
) -> list[tuple[float, float]]:
    if not points:
        return []

    output: list[tuple[float, float]] = []
    previous = points[-1]
    previous_inside = inside(previous)
    for current in points:
        current_inside = inside(current)
        if current_inside:
            if not previous_inside:
                output.append(intersect(previous, current))
            output.append(current)
        elif previous_inside:
            output.append(intersect(previous, current))
        previous = current
        previous_inside = current_inside
    return output


def clip_polygon_to_bbox(
    points: Sequence[tuple[float, float]], bbox: BoundingBox
) -> list[tuple[float, float]]:
    """polygon을 축 정렬 bounding box 경계로 clipping한다."""

    clipped = list(points)
    clipped = _clip_half_plane(
        clipped,
        lambda point: point[0] >= bbox.x1,
        lambda a, b: _lerp_x(a, b, bbox.x1),
    )
    clipped = _clip_half_plane(
        clipped,
        lambda point: point[0] <= bbox.x2,
        lambda a, b: _lerp_x(a, b, bbox.x2),
    )
    clipped = _clip_half_plane(
        clipped,
        lambda point: point[1] >= bbox.y1,
        lambda a, b: _lerp_y(a, b, bbox.y1),
    )
    return _clip_half_plane(
        clipped,
        lambda point: point[1] <= bbox.y2,
        lambda a, b: _lerp_y(a, b, bbox.y2),
    )


def polygon_area(points: Sequence[tuple[float, float]]) -> float:
    """꼭짓점 방향과 무관한 shoelace formula로 polygon 면적을 계산한다."""

    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def overlap_ratio(polygon: NormalizedPolygon, bbox: BoundingBox) -> float:
    """교차 면적을 차량 면적으로 나눈 overlap ratio를 반환한다."""

    area = bbox_area(bbox)
    if area <= 0.0:
        return 0.0
    return _clamp_unit_ratio(polygon_area(clip_polygon_to_bbox(polygon, bbox)) / area)


def coverage_ratio(polygon: NormalizedPolygon, bbox: BoundingBox) -> float:
    """교차 면적을 zone 면적으로 나눈 coverage ratio를 반환한다."""

    area = polygon_area(polygon)
    if area <= 0.0:
        return 0.0
    return _clamp_unit_ratio(polygon_area(clip_polygon_to_bbox(polygon, bbox)) / area)


def _clamp_unit_ratio(value: float) -> float:
    """부동소수점 반올림으로 비율이 단위 구간을 벗어나지 않게 한다."""

    return min(1.0, max(0.0, value))

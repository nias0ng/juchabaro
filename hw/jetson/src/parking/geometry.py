"""구역 폴리곤과 차량 바운딩박스의 기하 계산.

구역의 종류·번호·허용시간 같은 메타데이터를 알지 않는다. 폴리곤과 박스만
받아 비율을 돌려주므로 `zone_registry`가 이 모듈에 의존하고 그 반대는 없다.

`ai/tracking/jetson_vehicle_tracking_baseline.py:154-282`에서 이관했다. 이관 중
`zone_coverage_ratio(zone, bbox)`를 `coverage_ratio(polygon, bbox)`로 좁혀
`ParkingZone` 의존을 끊었고, `_polygon_area`를 `polygon_area`로 공개했다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

from src.tracking.models import BoundingBox


@dataclass(frozen=True)
class NormalizedPolygon:
    """0~1 정규화 좌표 정점으로 표현한 구역 경계 (3개 이상, 단순 다각형 가정)."""

    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("폴리곤은 정점이 3개 이상이어야 합니다.")
        for x, y in self.points:
            if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
                raise ValueError("폴리곤 좌표는 숫자여야 합니다.")
            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError("폴리곤 좌표는 유한한 숫자여야 합니다.")
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("폴리곤 좌표는 0~1 범위여야 합니다.")


def bbox_area(bbox: BoundingBox) -> float:
    """바운딩박스 면적(정규화 단위)을 반환한다."""

    return (bbox.x2 - bbox.x1) * (bbox.y2 - bbox.y1)


def bbox_center(bbox: BoundingBox) -> tuple[float, float]:
    """바운딩박스 중심 좌표를 반환한다."""

    return ((bbox.x1 + bbox.x2) / 2.0, (bbox.y1 + bbox.y2) / 2.0)


def _lerp_x(a: tuple[float, float], b: tuple[float, float], x: float) -> tuple[float, float]:
    t = (x - a[0]) / (b[0] - a[0])
    return (x, a[1] + t * (b[1] - a[1]))


def _lerp_y(a: tuple[float, float], b: tuple[float, float], y: float) -> tuple[float, float]:
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), y)


def _clip_half_plane(
    points: Sequence[tuple[float, float]],
    inside: Callable[[tuple[float, float]], bool],
    intersect: Callable[[tuple[float, float], tuple[float, float]], tuple[float, float]],
) -> list[tuple[float, float]]:
    """Sutherland-Hodgman 알고리즘으로 다각형을 반평면 하나로 자른다."""

    if not points:
        return []
    output: list[tuple[float, float]] = []
    prev = points[-1]
    prev_inside = inside(prev)
    for curr in points:
        curr_inside = inside(curr)
        if curr_inside:
            if not prev_inside:
                output.append(intersect(prev, curr))
            output.append(curr)
        elif prev_inside:
            output.append(intersect(prev, curr))
        prev, prev_inside = curr, curr_inside
    return output


def clip_polygon_to_bbox(
    points: Sequence[tuple[float, float]], bbox: BoundingBox
) -> list[tuple[float, float]]:
    """구역 폴리곤을 차량 바운딩박스(축 정렬 사각형) 범위로 잘라낸다."""

    clipped = list(points)
    clipped = _clip_half_plane(clipped, lambda p: p[0] >= bbox.x1, lambda a, b: _lerp_x(a, b, bbox.x1))
    clipped = _clip_half_plane(clipped, lambda p: p[0] <= bbox.x2, lambda a, b: _lerp_x(a, b, bbox.x2))
    clipped = _clip_half_plane(clipped, lambda p: p[1] >= bbox.y1, lambda a, b: _lerp_y(a, b, bbox.y1))
    clipped = _clip_half_plane(clipped, lambda p: p[1] <= bbox.y2, lambda a, b: _lerp_y(a, b, bbox.y2))
    return clipped


def polygon_area(points: Sequence[tuple[float, float]]) -> float:
    """신 발끈(shoelace) 공식으로 다각형 면적을 계산한다. 정점 순서와 무관하다."""

    if len(points) < 3:
        return 0.0
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def overlap_ratio(polygon: NormalizedPolygon, bbox: BoundingBox) -> float:
    """겹친 면적이 **차체 면적**의 몇 배인지 계산한다 (0.0~1.0)."""

    area = bbox_area(bbox)
    if area <= 0.0:
        return 0.0
    return polygon_area(clip_polygon_to_bbox(polygon.points, bbox)) / area


def coverage_ratio(polygon: NormalizedPolygon, bbox: BoundingBox) -> float:
    """겹친 면적이 **구역 면적**의 몇 배인지 계산한다 (0.0~1.0).

    분모가 구역 자신의 면적이라 차량 크기와 무관하게 "이 구역이 얼마나
    침범당했는지"를 일관되게 잴 수 있다. 침범 판정용 지표다.
    """

    area = polygon_area(polygon.points)
    if area <= 0.0:
        return 0.0
    return polygon_area(clip_polygon_to_bbox(polygon.points, bbox)) / area

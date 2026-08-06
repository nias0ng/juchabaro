"""정본 zone polygon과 차량 bounding box의 기하 연산을 제공한다.

polygon은 ``parking.models.NormalizedPolygon``을 직접 사용한다. 좌표 검증은
``ZoneDefinition`` 같은 소유 domain model이 담당하고, 이 모듈은 결정론적인
기하 계산만 담당한다.
"""

from __future__ import annotations

from typing import Callable, Sequence

from src.parking.models import NormalizedPolygon
from src.tracking.models import BoundingBox


_GEOMETRY_EPSILON = 1e-12


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


def signed_polygon_area(points: Sequence[tuple[float, float]]) -> float:
    """부호 있는 shoelace 넓이를 반환한다. 양수는 반시계 방향이다."""

    if len(points) < 3:
        return 0.0
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return total / 2.0


def polygon_centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """shoelace 가중 중심을 반환한다.

    꼭짓점 순서(시계/반시계)와 시작 꼭짓점에 무관하다. 면적이 0인
    degenerate polygon은 중심이 정의되지 않으므로 거부한다. 모듈의 다른
    함수와 같은 epsilon 관례를 따라, 절대값이 ``_GEOMETRY_EPSILON``
    이하인 면적도 degenerate로 본다 — sliver polygon의 불안정한 중심을
    막는다.
    """

    area = signed_polygon_area(points)
    if abs(area) <= _GEOMETRY_EPSILON:
        raise ValueError("polygon centroid requires a non-zero area")

    weighted_x = 0.0
    weighted_y = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        cross = x1 * y2 - x2 * y1
        weighted_x += (x1 + x2) * cross
        weighted_y += (y1 + y2) * cross
    return (weighted_x / (6.0 * area), weighted_y / (6.0 * area))


def is_convex_polygon(points: Sequence[tuple[float, float]]) -> bool:
    """넓이가 양수인 simple polygon이 convex인지 반환한다."""

    if (
        len(points) < 3
        or polygon_area(points) <= _GEOMETRY_EPSILON
        or not _is_simple_polygon(points)
    ):
        return False
    direction = 0
    for index in range(len(points)):
        a = points[index]
        b = points[(index + 1) % len(points)]
        c = points[(index + 2) % len(points)]
        cross = _cross(a, b, c)
        if abs(cross) <= _GEOMETRY_EPSILON:
            continue
        current = 1 if cross > 0.0 else -1
        if direction == 0:
            direction = current
        elif current != direction:
            return False
    return direction != 0


def convex_polygon_intersection(
    subject: Sequence[tuple[float, float]],
    clip: Sequence[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """결정론적 Sutherland-Hodgman 방식으로 두 convex polygon을 교차한다."""

    if not is_convex_polygon(subject) or not is_convex_polygon(clip):
        raise ValueError("convex polygon intersection requires convex polygons")
    orientation = 1.0 if signed_polygon_area(clip) > 0.0 else -1.0
    output = list(subject)
    for index, edge_start in enumerate(clip):
        edge_end = clip[(index + 1) % len(clip)]
        if not output:
            break
        input_points = output
        output = []
        previous = input_points[-1]
        previous_inside = _inside_edge(
            previous,
            edge_start,
            edge_end,
            orientation,
        )
        for current in input_points:
            current_inside = _inside_edge(
                current,
                edge_start,
                edge_end,
                orientation,
            )
            if current_inside:
                if not previous_inside:
                    output.append(
                        _line_intersection(
                            previous,
                            current,
                            edge_start,
                            edge_end,
                        )
                    )
                output.append(current)
            elif previous_inside:
                output.append(
                    _line_intersection(
                        previous,
                        current,
                        edge_start,
                        edge_end,
                    )
                )
            previous = current
            previous_inside = current_inside
    return tuple(output)


def convex_polygon_intersection_area(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
) -> float:
    """두 convex polygon의 교차 넓이를 반환한다."""

    return polygon_area(convex_polygon_intersection(first, second))


def polygon_overlap_ratio(
    zone_polygon: NormalizedPolygon,
    footprint: NormalizedPolygon,
) -> float:
    """convex zone 교차 넓이를 차량 footprint 넓이로 나눈 비율을 반환한다."""

    area = polygon_area(footprint)
    if area <= 0.0:
        return 0.0
    return _clamp_unit_ratio(
        convex_polygon_intersection_area(footprint, zone_polygon) / area
    )


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


def _cross(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (
        c[0] - a[0]
    )


def _inside_edge(
    point: tuple[float, float],
    edge_start: tuple[float, float],
    edge_end: tuple[float, float],
    orientation: float,
) -> bool:
    return (
        orientation * _cross(edge_start, edge_end, point)
        >= -_GEOMETRY_EPSILON
    )


def _line_intersection(
    segment_start: tuple[float, float],
    segment_end: tuple[float, float],
    edge_start: tuple[float, float],
    edge_end: tuple[float, float],
) -> tuple[float, float]:
    segment_dx = segment_end[0] - segment_start[0]
    segment_dy = segment_end[1] - segment_start[1]
    edge_dx = edge_end[0] - edge_start[0]
    edge_dy = edge_end[1] - edge_start[1]
    denominator = segment_dx * edge_dy - segment_dy * edge_dx
    if abs(denominator) <= _GEOMETRY_EPSILON:
        return segment_end
    offset_x = edge_start[0] - segment_start[0]
    offset_y = edge_start[1] - segment_start[1]
    t = (offset_x * edge_dy - offset_y * edge_dx) / denominator
    return (
        segment_start[0] + t * segment_dx,
        segment_start[1] + t * segment_dy,
    )


def _is_simple_polygon(
    points: Sequence[tuple[float, float]],
) -> bool:
    if len(set(points)) != len(points):
        return False
    edge_count = len(points)
    for first_index in range(edge_count):
        first_start = points[first_index]
        first_end = points[(first_index + 1) % edge_count]
        for second_index in range(first_index + 1, edge_count):
            if (
                second_index == first_index
                or second_index == (first_index + 1) % edge_count
                or first_index == (second_index + 1) % edge_count
            ):
                continue
            second_start = points[second_index]
            second_end = points[(second_index + 1) % edge_count]
            if _segments_intersect(
                first_start,
                first_end,
                second_start,
                second_end,
            ):
                return False
    return True


def _segments_intersect(
    first_start: tuple[float, float],
    first_end: tuple[float, float],
    second_start: tuple[float, float],
    second_end: tuple[float, float],
) -> bool:
    first_to_start = _cross(first_start, first_end, second_start)
    first_to_end = _cross(first_start, first_end, second_end)
    second_to_start = _cross(second_start, second_end, first_start)
    second_to_end = _cross(second_start, second_end, first_end)
    # cross product 둘을 다시 곱하면 좌표 크기의 4제곱에 비례해 작은 polygon의
    # 교차를 놓친다. 각 orientation의 부호를 같은 면적 단위 epsilon으로 비교한다.
    first_straddles = (
        first_to_start > _GEOMETRY_EPSILON
        and first_to_end < -_GEOMETRY_EPSILON
    ) or (
        first_to_start < -_GEOMETRY_EPSILON
        and first_to_end > _GEOMETRY_EPSILON
    )
    second_straddles = (
        second_to_start > _GEOMETRY_EPSILON
        and second_to_end < -_GEOMETRY_EPSILON
    ) or (
        second_to_start < -_GEOMETRY_EPSILON
        and second_to_end > _GEOMETRY_EPSILON
    )
    if first_straddles and second_straddles:
        return True
    return any(
        abs(cross) <= _GEOMETRY_EPSILON
        and _point_on_segment(point, start, end)
        for cross, point, start, end in (
            (first_to_start, second_start, first_start, first_end),
            (first_to_end, second_end, first_start, first_end),
            (second_to_start, first_start, second_start, second_end),
            (second_to_end, first_end, second_start, second_end),
        )
    )


def _point_on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    return (
        min(start[0], end[0]) - _GEOMETRY_EPSILON
        <= point[0]
        <= max(start[0], end[0]) + _GEOMETRY_EPSILON
        and min(start[1], end[1]) - _GEOMETRY_EPSILON
        <= point[1]
        <= max(start[1], end[1]) + _GEOMETRY_EPSILON
    )

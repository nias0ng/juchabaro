"""정본 tuple polygon과 bounding box 기하 연산의 회귀를 검증한다."""

import pytest

from src.parking.geometry import (
    bbox_area,
    bbox_center,
    convex_polygon_intersection_area,
    coverage_ratio,
    is_convex_polygon,
    overlap_ratio,
    polygon_area,
    polygon_overlap_ratio,
)
from src.parking.models import NormalizedPolygon
from src.tracking.models import BoundingBox

FULL_FRAME: NormalizedPolygon = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
SMALL_SQUARE: NormalizedPolygon = ((0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2))


def test_polygon_area_of_square() -> None:
    assert polygon_area(SMALL_SQUARE) == pytest.approx(0.04)


def test_polygon_area_is_orientation_independent() -> None:
    assert polygon_area(tuple(reversed(SMALL_SQUARE))) == pytest.approx(
        polygon_area(SMALL_SQUARE)
    )


def test_polygon_area_of_degenerate_is_zero() -> None:
    assert polygon_area(((0.0, 0.0), (0.1, 0.1))) == 0.0


def test_bbox_area_and_center() -> None:
    bbox = BoundingBox(0.2, 0.2, 0.4, 0.6)
    assert bbox_area(bbox) == pytest.approx(0.08)
    assert bbox_center(bbox) == pytest.approx((0.3, 0.4))


def test_overlap_ratio_accepts_canonical_tuple_polygon() -> None:
    bbox = BoundingBox(0.2, 0.2, 0.4, 0.4)
    assert overlap_ratio(FULL_FRAME, bbox) == pytest.approx(1.0)


def test_overlap_ratio_no_overlap() -> None:
    bbox = BoundingBox(0.5, 0.5, 0.7, 0.7)
    assert overlap_ratio(SMALL_SQUARE, bbox) == 0.0


def test_overlap_ratio_half_overlap() -> None:
    bbox = BoundingBox(0.1, 0.0, 0.3, 0.2)
    assert overlap_ratio(SMALL_SQUARE, bbox) == pytest.approx(0.5)


def test_coverage_ratio_full_containment_regardless_of_bbox_size() -> None:
    moto_spot: NormalizedPolygon = (
        (0.10, 0.10),
        (0.15, 0.10),
        (0.15, 0.20),
        (0.10, 0.20),
    )
    truck_bbox = BoundingBox(0.06, 0.05, 0.40, 0.25)
    assert coverage_ratio(moto_spot, truck_bbox) == pytest.approx(1.0)


def test_coverage_ratio_partial_and_no_overlap() -> None:
    spot: NormalizedPolygon = ((0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3))
    assert coverage_ratio(spot, BoundingBox(0.05, 0.0, 0.24, 0.3)) == pytest.approx(0.75)
    assert coverage_ratio(spot, BoundingBox(0.5, 0.5, 0.7, 0.7)) == 0.0


def test_convex_intersection_is_orientation_independent() -> None:
    left: NormalizedPolygon = (
        (0.0, 0.0),
        (0.2, 0.0),
        (0.2, 0.2),
        (0.0, 0.2),
    )
    crossing: NormalizedPolygon = (
        (0.1, 0.0),
        (0.3, 0.0),
        (0.3, 0.2),
        (0.1, 0.2),
    )

    assert convex_polygon_intersection_area(left, crossing) == pytest.approx(0.02)
    assert convex_polygon_intersection_area(
        tuple(reversed(left)),
        tuple(reversed(crossing)),
    ) == pytest.approx(0.02)


def test_shared_edge_has_zero_intersection_area() -> None:
    right: NormalizedPolygon = (
        (0.2, 0.0),
        (0.4, 0.0),
        (0.4, 0.2),
        (0.2, 0.2),
    )

    assert convex_polygon_intersection_area(SMALL_SQUARE, right) == 0.0


def test_polygon_overlap_ratio_uses_vehicle_footprint_area() -> None:
    half: NormalizedPolygon = (
        (0.0, 0.0),
        (0.1, 0.0),
        (0.1, 0.2),
        (0.0, 0.2),
    )

    assert polygon_overlap_ratio(half, SMALL_SQUARE) == pytest.approx(0.5)


def test_concave_polygon_is_not_convex() -> None:
    concave: NormalizedPolygon = (
        (0.0, 0.0),
        (0.2, 0.0),
        (0.1, 0.1),
        (0.2, 0.2),
        (0.0, 0.2),
    )

    assert not is_convex_polygon(concave)


def test_self_intersecting_polygon_is_not_convex() -> None:
    star: NormalizedPolygon = (
        (0.50, 0.05),
        (0.79, 0.95),
        (0.03, 0.39),
        (0.97, 0.39),
        (0.21, 0.95),
    )

    assert not is_convex_polygon(star)


def test_small_self_intersecting_polygon_is_not_convex() -> None:
    """교차 판정 epsilon은 polygon 크기를 다시 제곱해 비교하지 않는다."""

    star: NormalizedPolygon = (
        (0.500000, 0.499955),
        (0.500029, 0.500045),
        (0.499953, 0.499989),
        (0.500047, 0.499989),
        (0.499971, 0.500045),
    )

    assert polygon_area(star) > 0.0
    assert not is_convex_polygon(star)

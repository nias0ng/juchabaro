"""정본 tuple polygon과 bounding box 기하 연산의 회귀를 검증한다."""

import pytest

from src.parking.geometry import bbox_area, bbox_center, coverage_ratio, overlap_ratio, polygon_area
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

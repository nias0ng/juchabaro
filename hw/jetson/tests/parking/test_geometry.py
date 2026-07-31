"""구역 폴리곤 기하 계산 테스트. baseline test_tracking_baseline.py:83-120 이관."""

import math

import pytest

from src.parking.geometry import (
    NormalizedPolygon,
    bbox_area,
    bbox_center,
    coverage_ratio,
    overlap_ratio,
    polygon_area,
)
from src.tracking.models import BoundingBox

FULL_FRAME = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
SMALL_SQUARE = ((0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2))


def test_polygon_area_of_square() -> None:
    assert polygon_area(SMALL_SQUARE) == pytest.approx(0.04)


def test_polygon_area_is_orientation_independent() -> None:
    """shoelace + abs()이므로 정점 순서(CW/CCW)가 결과를 바꾸지 않는다."""
    reversed_square = tuple(reversed(SMALL_SQUARE))
    assert polygon_area(reversed_square) == pytest.approx(polygon_area(SMALL_SQUARE))


def test_polygon_area_of_degenerate_is_zero() -> None:
    assert polygon_area(((0.0, 0.0), (0.1, 0.1))) == 0.0


def test_bbox_area_and_center() -> None:
    bbox = BoundingBox(0.2, 0.2, 0.4, 0.6)
    assert bbox_area(bbox) == pytest.approx(0.08)
    assert bbox_center(bbox) == pytest.approx((0.3, 0.4))


def test_overlap_ratio_full_containment() -> None:
    polygon = NormalizedPolygon(FULL_FRAME)
    bbox = BoundingBox(0.2, 0.2, 0.4, 0.4)
    assert overlap_ratio(polygon, bbox) == pytest.approx(1.0)


def test_overlap_ratio_no_overlap() -> None:
    polygon = NormalizedPolygon(SMALL_SQUARE)
    bbox = BoundingBox(0.5, 0.5, 0.7, 0.7)
    assert overlap_ratio(polygon, bbox) == 0.0


def test_overlap_ratio_half_overlap() -> None:
    polygon = NormalizedPolygon(SMALL_SQUARE)
    bbox = BoundingBox(0.1, 0.0, 0.3, 0.2)
    assert overlap_ratio(polygon, bbox) == pytest.approx(0.5)


def test_coverage_ratio_full_containment_regardless_of_bbox_size() -> None:
    """작은 구역을 훨씬 큰 바운딩박스가 덮어도 구역 면적 기준이라 100%가 나온다.

    차체 기준(overlap_ratio)으로는 7.1%밖에 안 되는 상황이다 — 트럭이 오토바이
    스팟을 덮는 경우가 이에 해당한다.
    """
    moto_spot = NormalizedPolygon(((0.10, 0.10), (0.15, 0.10), (0.15, 0.20), (0.10, 0.20)))
    truck_bbox = BoundingBox(0.06, 0.05, 0.40, 0.25)
    assert coverage_ratio(moto_spot, truck_bbox) == pytest.approx(1.0)


def test_coverage_ratio_partial_overlap() -> None:
    spot = NormalizedPolygon(((0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)))
    intruding_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)
    assert coverage_ratio(spot, intruding_bbox) == pytest.approx(0.75)


def test_coverage_ratio_no_overlap() -> None:
    spot = NormalizedPolygon(((0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)))
    far_bbox = BoundingBox(0.50, 0.50, 0.70, 0.70)
    assert coverage_ratio(spot, far_bbox) == 0.0


def test_polygon_rejects_fewer_than_three_points() -> None:
    with pytest.raises(ValueError, match="정점이 3개 이상"):
        NormalizedPolygon(((0.0, 0.0), (0.1, 0.1)))


def test_polygon_rejects_out_of_range_coordinate() -> None:
    with pytest.raises(ValueError, match="0~1 범위"):
        NormalizedPolygon(((0.0, 0.0), (1.5, 0.0), (1.0, 1.0)))


def test_polygon_rejects_non_finite_coordinate() -> None:
    with pytest.raises(ValueError, match="유한한"):
        NormalizedPolygon(((0.0, 0.0), (math.nan, 0.0), (1.0, 1.0)))

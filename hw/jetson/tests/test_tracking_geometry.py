"""tracking/geometry.py 회귀 테스트 (436)."""

import math

import pytest
from src.tracking.geometry import centroid, centroid_distance
from src.tracking.models import BoundingBox


def test_centroid_is_bbox_midpoint():
    bbox = BoundingBox(x1=0.2, y1=0.4, x2=0.6, y2=0.8)

    cx, cy = centroid(bbox)

    assert cx == pytest.approx(0.4)
    assert cy == pytest.approx(0.6)


def test_centroid_distance_between_identical_boxes_is_zero():
    a = BoundingBox(x1=0.1, y1=0.1, x2=0.3, y2=0.3)
    b = BoundingBox(x1=0.1, y1=0.1, x2=0.3, y2=0.3)

    assert centroid_distance(a, b) == 0.0


def test_centroid_distance_matches_euclidean_distance():
    a = BoundingBox(x1=0.0, y1=0.0, x2=0.2, y2=0.2)  # 중심 (0.1, 0.1)
    b = BoundingBox(x1=0.3, y1=0.3, x2=0.5, y2=0.5)  # 중심 (0.4, 0.4)

    assert centroid_distance(a, b) == pytest.approx(math.hypot(0.3, 0.3))

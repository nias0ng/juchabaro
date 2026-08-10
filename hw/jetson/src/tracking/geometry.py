"""트랙 재결합과 이동 관측에 필요한 바운딩박스 기하 계산."""

from __future__ import annotations

import math

from src.tracking.models import BoundingBox


def centroid(bbox: BoundingBox) -> tuple[float, float]:
    """바운딩박스 중심 좌표를 반환한다."""

    return ((bbox.x1 + bbox.x2) / 2.0, (bbox.y1 + bbox.y2) / 2.0)


def centroid_distance(a: BoundingBox, b: BoundingBox) -> float:
    """두 바운딩박스 중심 사이의 유클리드 거리(정규화 좌표 단위)."""

    ax, ay = centroid(a)
    bx, by = centroid(b)
    return math.hypot(ax - bx, ay - by)

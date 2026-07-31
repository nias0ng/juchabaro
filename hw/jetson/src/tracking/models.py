"""추적 계층이 주차 판정 계층에 전달하는 공통 관측 계약.

ByteTrack의 일시적인 트랙, Jetson 내부 물리 차량, Backend 입차 세션을
서로 다른 식별자로 유지한다. 구역 방문·주차·위반 상태는 정의하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import NewType


TrackSegmentId = NewType("TrackSegmentId", int)
PhysicalVehicleId = NewType("PhysicalVehicleId", str)
ParkingSessionId = NewType("ParkingSessionId", int)
VehicleId = NewType("VehicleId", int)


class MotionSignal(str, Enum):
    """이동 판정 구현체가 주차 상태 머신에 전달하는 관측값."""

    MOVING = "MOVING"
    STATIONARY = "STATIONARY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BoundingBox:
    """0~1 정규화 좌표의 차량 바운딩박스."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class TrackObservation:
    """한 프레임에서 차량 트래커가 만든 일시적 관측."""

    track_segment_id: TrackSegmentId
    bbox: BoundingBox
    confidence: float
    observed_at: datetime


@dataclass(frozen=True)
class VehicleContext:
    """Backend 입차 세션에서 얻은 차량 식별 정보와 전용구역 자격."""

    parking_session_id: ParkingSessionId | None
    vehicle_id: VehicleId | None
    is_electric: bool | None
    is_disabled_vehicle: bool | None


@dataclass(frozen=True)
class PhysicalVehicleSnapshot:
    """추적 파이프라인이 확정한 물리 차량의 현재 시점 스냅샷."""

    physical_vehicle_id: PhysicalVehicleId
    track_segment_id: TrackSegmentId
    bbox: BoundingBox
    confidence: float
    motion_signal: MotionSignal
    observed_at: datetime
    context: VehicleContext | None = None

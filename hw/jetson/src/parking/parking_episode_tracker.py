"""10분 연속 정지 정책을 담당하는 주차 에피소드 상태축의 구현 계약.

STATIONARY 관측만 정지 시간에 누적하고 기본 600초에 도달하면 PARKED가 된다.
MOVING은 정지 후보를 초기화하거나 확정된 에피소드를 종료한다. UNKNOWN은
정지 시간에 포함하지 않고 기존 상태도 즉시 종료하지 않는다. 종료 뒤 다시
정지한 차량에는 새로운 parking_episode_id를 발급한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.parking.models import ParkingEpisode
from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleId,
)


class ParkingEpisodeTracker(Protocol):
    """이동 신호를 STOP_PENDING/PARKED/ENDED 에피소드로 변환한다."""

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        parking_session_id: ParkingSessionId | None,
        signal: MotionSignal,
        observed_at: datetime,
    ) -> ParkingEpisode | None:
        """현재 또는 방금 종료된 에피소드를 반환하고 없으면 None을 반환한다."""

        ...

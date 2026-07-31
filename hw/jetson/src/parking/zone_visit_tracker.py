"""구역 방문 상태축의 구현 계약.

상태는 OUTSIDE → ENTERING → INSIDE → EXITING 순으로 전이한다. PRESENT와
ABSENT의 진입·이탈 확인시간은 구현체가 누적하고, UNKNOWN은 시간을 누적하거나
기존 상태를 즉시 초기화하지 않는다. 한 차량은 여러 구역을 동시에 방문할 수
있으므로 상태는 (physical_vehicle_id, zone_id)별로 독립 관리한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.parking.models import PresenceSignal, ZoneId, ZoneVisit
from src.tracking.models import PhysicalVehicleId


class ZoneVisitTracker(Protocol):
    """구역 존재 신호를 연속적인 ZoneVisit 상태로 변환한다."""

    def update(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
        signal: PresenceSignal,
        observed_at: datetime,
    ) -> ZoneVisit | None:
        """현재 방문을 반환하고 활성 방문이 없으면 None을 반환한다."""

        ...

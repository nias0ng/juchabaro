"""독립 위반 규칙 평가기가 공통으로 받는 입력 계약.

규칙(`restricted_zone`, `ev_overstay`, `bad_parking`, `double_parking`)은 상태를
직접 보관하지 않는 순수 판정기다(데이터흐름.md §4) — 이 모듈은 그 입력만
고정하고, 반환값(`IncidentSignal`)은 `parking/models.py`에 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from src.parking.models import ParkingAssignment, ParkingEpisode, ZoneVisit
from src.tracking.models import PhysicalVehicleSnapshot, VehicleContext


@dataclass(frozen=True)
class RuleContext:
    """규칙 평가기 하나를 호출할 때 필요한 모든 입력을 묶은 값.

    `zones`는 구역 정의 목록이다. 실제 타입(`ParkingZone`/`ZoneRegistry`)은
    T-06이 `ai/tracking`에서 이관하기 전까지 확정되지 않아 우선 `Any`로 둔다 —
    이관되면 이 필드의 타입을 갱신해야 한다.
    """

    vehicle: PhysicalVehicleSnapshot
    vehicle_context: VehicleContext | None
    active_zone_visits: tuple[ZoneVisit, ...]
    parking_episode: ParkingEpisode | None
    parking_assignment: ParkingAssignment | None
    zones: Sequence[Any]
    observed_at: datetime

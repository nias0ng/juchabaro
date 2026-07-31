"""독립 위반 규칙 평가기가 공통으로 받는 입력 계약.

규칙(`restricted_zone`, `ev_overstay`, `bad_parking`, `double_parking`)은 상태를
직접 보관하지 않는 순수 판정기다(데이터흐름.md §4) — 이 모듈은 그 입력만
고정하고, 반환값(`IncidentSignal`)은 `parking/models.py`에 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.parking.models import ParkingAssignment, ParkingEpisode, ZoneVisit
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import PhysicalVehicleSnapshot, VehicleContext


@dataclass(frozen=True)
class RuleContext:
    """규칙 평가기 하나를 호출할 때 필요한 모든 입력을 묶은 값."""

    vehicle: PhysicalVehicleSnapshot
    vehicle_context: VehicleContext | None
    active_zone_visits: tuple[ZoneVisit, ...]
    parking_episode: ParkingEpisode | None
    parking_assignment: ParkingAssignment | None
    zones: ZoneRegistry
    observed_at: datetime

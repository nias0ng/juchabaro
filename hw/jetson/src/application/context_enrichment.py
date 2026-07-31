"""추적 배치에 입차 세션·자격 정보를 채워 넣는 조립 지점(383 미해결분, T-16).

`ContextMatcher`는 구역을 모른다(그 이유는 `context_matcher.py` 참고). "이
차량이 지금 ENTRY_EXIT 구역에 있는가"는 여기서 `parking.zone_registry`와
`parking.geometry.overlap_ratio`로 계산한다 — tracking과 parking 양쪽을 동시에
알아도 되는 자리는 조립 담당인 application뿐이다(데이터흐름.md §6).

`PhysicalVehicleSnapshot`은 불변이라 매칭된 `context`를 그 자리에서 바꿀 수
없다 — `dataclasses.replace`로 새 스냅샷을 만들어 교체한다.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from src.parking.geometry import overlap_ratio
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.context_matcher import ContextMatcher
from src.tracking.models import PhysicalVehicleSnapshot, TrackingBatch


class EntryContextEnricher:
    """`TrackingBatch`의 물리 차량마다 `ContextMatcher`가 찾은 자격 정보를 채운다."""

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        matcher: ContextMatcher,
        entry_zone_min_overlap_ratio: float = 0.40,
    ) -> None:
        self._entry_zones: tuple[ParkingZone, ...] = tuple(
            zone for zone in zones.all() if zone.zone_type is ZoneType.ENTRY_EXIT
        )
        self._matcher = matcher
        self._entry_zone_min_overlap_ratio = entry_zone_min_overlap_ratio

    def enrich(self, batch: TrackingBatch) -> TrackingBatch:
        """이번 배치의 각 차량에 대해 아직 없는 `context`를 매칭해 채운다."""

        self._matcher.prune_expired(batch.observed_at)
        for ended_id in batch.ended_vehicle_ids:
            self._matcher.forget(ended_id)

        if not self._entry_zones:
            return batch

        vehicles = tuple(self._enrich_vehicle(vehicle, batch.observed_at) for vehicle in batch.vehicles)
        return dataclasses.replace(batch, vehicles=vehicles)

    def _enrich_vehicle(
        self, vehicle: PhysicalVehicleSnapshot, observed_at: datetime
    ) -> PhysicalVehicleSnapshot:
        if vehicle.context is not None:
            return vehicle

        in_entry_zone = any(
            overlap_ratio(zone.polygon, vehicle.bbox) >= self._entry_zone_min_overlap_ratio
            for zone in self._entry_zones
        )
        context = self._matcher.match(
            physical_vehicle_id=vehicle.physical_vehicle_id,
            in_entry_zone=in_entry_zone,
            now=observed_at,
        )
        if context is None:
            return vehicle
        return dataclasses.replace(vehicle, context=context)

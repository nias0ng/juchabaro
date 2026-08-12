"""ToF 현장 경고가 소비하는 최신 camera monitoring projection.

이 모듈은 frame commit 직후의 차량 관측과 전용구역 ZoneVisit만 process
memory에 latest-only 형태로 보존한다. SQLite, evidence spool, Backend publication은
소유하지 않으며 process가 재시작되면 projection도 함께 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from src.domain.models import (
    ObservationStatus,
    require_aware,
    require_non_negative,
)
from src.parking.models import (
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.tracking.models import PhysicalVehicleId


_TERMINAL_VISIT_STATES = {
    ZoneVisitState.ENDED,
    ZoneVisitState.CANCELED,
}


@dataclass(frozen=True, kw_only=True)
class TofVehicleObservationProjection:
    """한 PhysicalVehicle의 최신 비영속 관측."""

    physical_vehicle_id: PhysicalVehicleId
    observation: ObservationStatus

    def __post_init__(self) -> None:
        if not isinstance(self.observation, ObservationStatus):
            raise TypeError("observation must be ObservationStatus")


@dataclass(frozen=True, kw_only=True)
class TofMonitoringProjectionUpdate:
    """한 monitoring frame commit이 projection에 반영할 delta."""

    camera_id: str
    frame_id: int
    observed_at: datetime
    vehicles: tuple[TofVehicleObservationProjection, ...]
    zone_visits: tuple[ZoneVisit, ...]
    retired_physical_vehicle_ids: tuple[PhysicalVehicleId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.camera_id, str) or not self.camera_id.strip():
            raise ValueError("camera_id must not be empty")
        require_non_negative(self.frame_id, "frame_id")
        require_aware(self.observed_at, "observed_at")
        if not isinstance(self.vehicles, tuple):
            raise TypeError("vehicles must be a tuple")
        if any(
            not isinstance(vehicle, TofVehicleObservationProjection)
            for vehicle in self.vehicles
        ):
            raise TypeError(
                "vehicles must contain TofVehicleObservationProjection values"
            )
        vehicle_ids = tuple(
            vehicle.physical_vehicle_id for vehicle in self.vehicles
        )
        if len(vehicle_ids) != len(set(vehicle_ids)):
            raise ValueError("vehicles must not repeat a PhysicalVehicle id")
        if not isinstance(self.zone_visits, tuple):
            raise TypeError("zone_visits must be a tuple")
        if any(not isinstance(visit, ZoneVisit) for visit in self.zone_visits):
            raise TypeError("zone_visits must contain ZoneVisit values")
        if not isinstance(self.retired_physical_vehicle_ids, tuple):
            raise TypeError("retired_physical_vehicle_ids must be a tuple")


@dataclass(frozen=True, kw_only=True)
class TofMonitoringProjection:
    """ToF authorization이 원자적으로 읽는 immutable latest snapshot."""

    camera_id: str
    frame_id: int
    observed_at: datetime
    vehicles: tuple[TofVehicleObservationProjection, ...]
    zone_visits: tuple[ZoneVisit, ...]

    def visits_for_zone(self, zone_id: ZoneId) -> tuple[ZoneVisit, ...]:
        return tuple(
            visit for visit in self.zone_visits if visit.zone_id == zone_id
        )

    def vehicle_observation(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> ObservationStatus | None:
        for vehicle in self.vehicles:
            if vehicle.physical_vehicle_id == physical_vehicle_id:
                return vehicle.observation
        return None


class LatestTofMonitoringProjectionStore:
    """단일 process에서 최신 projection 하나만 보관하는 thread-safe store."""

    def __init__(self, *, target_zone_ids: tuple[ZoneId, ...]) -> None:
        if not isinstance(target_zone_ids, tuple):
            raise TypeError("target_zone_ids must be a tuple")
        if not target_zone_ids:
            raise ValueError("target_zone_ids must not be empty")
        if any(
            isinstance(zone_id, bool)
            or not isinstance(zone_id, int)
            or zone_id <= 0
            for zone_id in target_zone_ids
        ):
            raise ValueError(
                "target_zone_ids must contain positive integer zone IDs"
            )
        if len(target_zone_ids) != len(set(target_zone_ids)):
            raise ValueError("target_zone_ids must not contain duplicates")

        self._target_zone_ids = frozenset(target_zone_ids)
        self._lock = Lock()
        self._latest_sequence: tuple[datetime, int] | None = None
        self._vehicles: dict[
            PhysicalVehicleId,
            TofVehicleObservationProjection,
        ] = {}
        self._zone_visits: dict[ZoneVisitId, ZoneVisit] = {}
        self._snapshot: TofMonitoringProjection | None = None

    def publish(self, update: TofMonitoringProjectionUpdate) -> bool:
        """최신 frame delta를 반영한다.

        이전 또는 중복 frame은 무시하고 ``False``를 반환한다. 정상 반영은
        durable write 없이 process memory 안에서만 수행된다.
        """

        if not isinstance(update, TofMonitoringProjectionUpdate):
            raise TypeError("update must be TofMonitoringProjectionUpdate")

        sequence = (update.observed_at, update.frame_id)
        with self._lock:
            if (
                self._latest_sequence is not None
                and sequence <= self._latest_sequence
            ):
                return False

            current_vehicle_ids = {
                vehicle.physical_vehicle_id for vehicle in update.vehicles
            }
            for vehicle in update.vehicles:
                self._vehicles[vehicle.physical_vehicle_id] = vehicle

            for visit in update.zone_visits:
                targets_zone = visit.zone_id in self._target_zone_ids
                if (
                    not targets_zone
                    or visit.state in _TERMINAL_VISIT_STATES
                ):
                    self._zone_visits.pop(visit.visit_id, None)
                    continue
                self._zone_visits[visit.visit_id] = visit

            retired_ids = set(update.retired_physical_vehicle_ids)
            if retired_ids:
                for physical_vehicle_id in retired_ids:
                    self._vehicles.pop(physical_vehicle_id, None)
                self._zone_visits = {
                    visit_id: visit
                    for visit_id, visit in self._zone_visits.items()
                    if visit.physical_vehicle_id not in retired_ids
                }

            referenced_vehicle_ids = {
                visit.physical_vehicle_id
                for visit in self._zone_visits.values()
            }
            retained_vehicle_ids = (
                current_vehicle_ids | referenced_vehicle_ids
            ) - retired_ids
            self._vehicles = {
                physical_vehicle_id: vehicle
                for physical_vehicle_id, vehicle in self._vehicles.items()
                if physical_vehicle_id in retained_vehicle_ids
            }

            self._latest_sequence = sequence
            self._snapshot = TofMonitoringProjection(
                camera_id=update.camera_id,
                frame_id=update.frame_id,
                observed_at=update.observed_at,
                vehicles=tuple(
                    sorted(
                        self._vehicles.values(),
                        key=lambda item: str(item.physical_vehicle_id),
                    )
                ),
                zone_visits=tuple(
                    sorted(
                        self._zone_visits.values(),
                        key=lambda item: str(item.visit_id),
                    )
                ),
            )
            return True

    def snapshot(self) -> TofMonitoringProjection | None:
        """현재 immutable projection을 반환한다."""

        with self._lock:
            return self._snapshot

"""ToF 센서 점유 runtime의 domain owner와 worker를 조립한다.

이 모듈은 검증된 ZoneRegistry와 주입된 SensorArray를 점유 Manager 및 Worker로
결속한다. adapter 선택, 하드웨어 접근, worker 시작·종료와 transition 저장은
후속 배포 composition 계층의 책임이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.application.sensor_occupancy import (
    OccupancyPolicy,
    OccupancyStateManager,
    SensorZoneBinding,
)
from src.application.sensor_worker import (
    SensorTransitionConsumer,
    SensorWorker,
)
from src.parking.models import ZoneDefinition, ZoneId, ZoneType
from src.parking.zone_registry import (
    ZoneNotFoundError,
    ZoneRegistry,
)
from src.sensors.adapters.vl53l0x_array import (
    DISABLED_ZONE_SENSOR_ID,
    EV_CHARGING_ZONE_SENSOR_ID,
)
from src.sensors.ports import SensorArray


@dataclass(frozen=True, kw_only=True)
class TofSensorRuntimePolicy:
    """배포 계층이 명시하는 ToF 점유 runtime 설정."""

    disabled_zone_id: ZoneId
    ev_charging_zone_id: ZoneId

    poll_interval_seconds: float

    enter_distance_mm: float
    exit_distance_mm: float
    enter_confirm_seconds: float
    exit_confirm_seconds: float
    trusted_sample_max_gap_seconds: float
    stale_after_seconds: float


@dataclass(frozen=True, kw_only=True)
class TofSensorRuntimeDependencies:
    """배포 계층이 선택해 주입하는 ToF runtime 의존성."""

    sensor_array: SensorArray
    transition_consumer: SensorTransitionConsumer | None = None


def build_tof_sensor_worker(
    *,
    zones: ZoneRegistry,
    policy: TofSensorRuntimePolicy,
    dependencies: TofSensorRuntimeDependencies,
) -> SensorWorker:
    """zone 결속을 검증하고 시작하지 않은 SensorWorker를 반환한다."""

    disabled_zone = _require_zone(
        zones,
        zone_id=policy.disabled_zone_id,
        setting_name="tof_disabled_zone_id",
    )
    _require_zone_type(
        disabled_zone,
        expected_type=ZoneType.DISABLED,
        setting_name="tof_disabled_zone_id",
    )

    ev_charging_zone = _require_zone(
        zones,
        zone_id=policy.ev_charging_zone_id,
        setting_name="tof_ev_charging_zone_id",
    )
    _require_zone_type(
        ev_charging_zone,
        expected_type=ZoneType.EV_CHARGING,
        setting_name="tof_ev_charging_zone_id",
    )

    bindings = (
        SensorZoneBinding(
            sensor_id=DISABLED_ZONE_SENSOR_ID,
            zone_id=policy.disabled_zone_id,
        ),
        SensorZoneBinding(
            sensor_id=EV_CHARGING_ZONE_SENSOR_ID,
            zone_id=policy.ev_charging_zone_id,
        ),
    )
    occupancy_policy = OccupancyPolicy(
        enter_distance_mm=policy.enter_distance_mm,
        exit_distance_mm=policy.exit_distance_mm,
        enter_confirm_seconds=policy.enter_confirm_seconds,
        exit_confirm_seconds=policy.exit_confirm_seconds,
        trusted_sample_max_gap_seconds=(
            policy.trusted_sample_max_gap_seconds
        ),
        stale_after_seconds=policy.stale_after_seconds,
    )
    occupancy_manager = OccupancyStateManager(
        bindings=bindings,
        policy=occupancy_policy,
    )

    return SensorWorker(
        sensor_array=dependencies.sensor_array,
        occupancy_manager=occupancy_manager,
        poll_interval_seconds=policy.poll_interval_seconds,
        transition_consumer=dependencies.transition_consumer,
    )


def _require_zone(
    zones: ZoneRegistry,
    *,
    zone_id: ZoneId,
    setting_name: str,
) -> ZoneDefinition:
    try:
        return zones.get(zone_id)
    except ZoneNotFoundError as exc:
        raise ValueError(
            f"{setting_name}가 등록되지 않은 구역을 가리킵니다: "
            f"zone_id={zone_id}"
        ) from exc


def _require_zone_type(
    zone: ZoneDefinition,
    *,
    expected_type: ZoneType,
    setting_name: str,
) -> None:
    if zone.zone_type is expected_type:
        return

    raise ValueError(
        f"{setting_name}는 {expected_type.value} 구역을 가리켜야 합니다: "
        f"zone_id={zone.zone_id}, actual={zone.zone_type.value}"
    )

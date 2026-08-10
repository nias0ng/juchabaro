"""ToF sensor factory의 zone 검증과 runtime 조립 계약 테스트."""

from __future__ import annotations

import pytest

from src.application.sensor_factory import (
    TofSensorRuntimeDependencies,
    TofSensorRuntimePolicy,
    build_tof_sensor_worker,
)
from src.parking.models import (
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.sensors.adapters.vl53l0x_array import (
    DISABLED_ZONE_SENSOR_ID,
    EV_CHARGING_ZONE_SENSOR_ID,
)


class _SensorArray:
    def __init__(self) -> None:
        self.open_calls = 0
        self.read_calls = 0
        self.close_calls = 0

    def open(self) -> None:
        self.open_calls += 1

    def read_all(self):
        self.read_calls += 1
        raise AssertionError("factory must not read sensors")

    def close(self) -> None:
        self.close_calls += 1


def _zone(
    zone_id: int,
    zone_type: ZoneType,
    *,
    left: float,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=(
            (left, 0.1),
            (left + 0.1, 0.1),
            (left + 0.1, 0.2),
            (left, 0.2),
        ),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="pilot-calibration",
    )


def _zones(
    *,
    disabled_type: ZoneType = ZoneType.DISABLED,
    ev_type: ZoneType = ZoneType.EV_CHARGING,
) -> ZoneRegistry:
    return ZoneRegistry(
        (
            _zone(4, disabled_type, left=0.1),
            _zone(5, ev_type, left=0.3),
            _zone(6, ZoneType.GENERAL, left=0.5),
        )
    )


def _policy(**overrides) -> TofSensorRuntimePolicy:
    values = {
        "disabled_zone_id": ZoneId(4),
        "ev_charging_zone_id": ZoneId(5),
        "poll_interval_seconds": 0.05,
        "enter_distance_mm": 150.0,
        "exit_distance_mm": 220.0,
        "enter_confirm_seconds": 0.0,
        "exit_confirm_seconds": 0.0,
        "trusted_sample_max_gap_seconds": 1.0,
        "stale_after_seconds": 2.0,
    }
    values.update(overrides)
    return TofSensorRuntimePolicy(**values)


def test_factory_builds_unstarted_worker_with_binding_order() -> None:
    sensor_array = _SensorArray()

    worker = build_tof_sensor_worker(
        zones=_zones(),
        policy=_policy(),
        dependencies=TofSensorRuntimeDependencies(
            sensor_array=sensor_array,
        ),
    )

    snapshots = worker.snapshots()
    assert tuple(snapshot.sensor_id for snapshot in snapshots) == (
        DISABLED_ZONE_SENSOR_ID,
        EV_CHARGING_ZONE_SENSOR_ID,
    )
    assert tuple(snapshot.zone_id for snapshot in snapshots) == (
        ZoneId(4),
        ZoneId(5),
    )
    assert worker.is_running is False
    assert worker.failure is None
    assert sensor_array.open_calls == 0
    assert sensor_array.read_calls == 0
    assert sensor_array.close_calls == 0


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        (
            {"disabled_zone_id": ZoneId(99)},
            "tof_disabled_zone_id",
        ),
        (
            {"ev_charging_zone_id": ZoneId(99)},
            "tof_ev_charging_zone_id",
        ),
    ],
)
def test_factory_rejects_missing_zone(
    overrides,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        build_tof_sensor_worker(
            zones=_zones(),
            policy=_policy(**overrides),
            dependencies=TofSensorRuntimeDependencies(
                sensor_array=_SensorArray(),
            ),
        )


@pytest.mark.parametrize(
    ("zones", "expected_message"),
    [
        (
            _zones(disabled_type=ZoneType.GENERAL),
            "tof_disabled_zone_id.*DISABLED",
        ),
        (
            _zones(ev_type=ZoneType.GENERAL),
            "tof_ev_charging_zone_id.*EV_CHARGING",
        ),
    ],
)
def test_factory_rejects_wrong_zone_type(
    zones: ZoneRegistry,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        build_tof_sensor_worker(
            zones=zones,
            policy=_policy(),
            dependencies=TofSensorRuntimeDependencies(
                sensor_array=_SensorArray(),
            ),
        )


def test_factory_rejects_same_zone_configuration() -> None:
    """한 zone은 두 필수 zone type을 동시에 만족할 수 없다."""

    with pytest.raises(
        ValueError,
        match="tof_ev_charging_zone_id.*EV_CHARGING",
    ):
        build_tof_sensor_worker(
            zones=_zones(),
            policy=_policy(ev_charging_zone_id=ZoneId(4)),
            dependencies=TofSensorRuntimeDependencies(
                sensor_array=_SensorArray(),
            ),
        )


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        (
            {
                "enter_distance_mm": 220.0,
                "exit_distance_mm": 220.0,
            },
            "enter_distance_mm",
        ),
        (
            {
                "trusted_sample_max_gap_seconds": 2.0,
                "stale_after_seconds": 1.0,
            },
            "stale_after_seconds",
        ),
        (
            {"poll_interval_seconds": 0.0},
            "poll_interval_seconds",
        ),
    ],
)
def test_factory_delegates_policy_validation_to_owner(
    overrides,
    expected_message: str,
) -> None:
    with pytest.raises(ValueError, match=expected_message):
        build_tof_sensor_worker(
            zones=_zones(),
            policy=_policy(**overrides),
            dependencies=TofSensorRuntimeDependencies(
                sensor_array=_SensorArray(),
            ),
        )


def test_factory_forwards_optional_transition_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_arguments = {}

    class _SensorWorkerDouble:
        def __init__(self, **arguments) -> None:
            captured_arguments.update(arguments)

    def consume(_transitions) -> None:
        raise AssertionError("factory must not invoke consumer")

    monkeypatch.setattr(
        "src.application.sensor_factory.SensorWorker",
        _SensorWorkerDouble,
    )
    sensor_array = _SensorArray()

    worker = build_tof_sensor_worker(
        zones=_zones(),
        policy=_policy(),
        dependencies=TofSensorRuntimeDependencies(
            sensor_array=sensor_array,
            transition_consumer=consume,
        ),
    )

    assert isinstance(worker, _SensorWorkerDouble)
    assert captured_arguments["sensor_array"] is sensor_array
    assert captured_arguments["transition_consumer"] is consume
    assert captured_arguments["poll_interval_seconds"] == 0.05
    assert captured_arguments["occupancy_manager"].snapshots()

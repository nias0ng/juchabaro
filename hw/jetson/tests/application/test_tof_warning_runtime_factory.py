"""ToF 경고 runtime factory의 순수 dependency wiring 계약을 검증한다."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

import src.application.tof_warning_runtime_factory as factory_module
from src.actuators.adapters.jetson_gpio_led import (
    BLINK_ACTION,
    DISABLED_ZONE_WARNING_LED_ID,
    EV_ZONE_WARNING_LED_ID,
)
from src.actuators.adapters.jetson_usb_speaker import (
    DISABLED_ZONE_WARNING_SPEAKER_ID,
    EV_ZONE_WARNING_SPEAKER_ID,
    PLAY_ACTION,
)
from src.actuators.models import ActuatorCommand
from src.application.local_warning_coordinator import (
    LocalWarningCoordinator,
)
from src.application.sensor_factory import TofSensorRuntimePolicy
from src.application.sensor_worker import SensorWorker
from src.application.tof_authorization_worker import (
    TofAuthorizationRequestMailbox,
    TofAuthorizationWorker,
)
from src.application.tof_monitoring_projection import (
    LatestTofMonitoringProjectionStore,
)
from src.application.tof_warning_runtime_factory import (
    TofWarningRuntimeDependencies,
    TofWarningRuntimePolicy,
    build_tof_warning_runtime,
)
from src.application.tof_zone_authorization import (
    TofAuthorizationPolicy,
)
from src.application.tof_zone_authorization_coordinator import (
    TofZoneAuthorizationCoordinator,
)
from src.parking.models import (
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry


DISABLED_ZONE_ID = ZoneId(4)
EV_ZONE_ID = ZoneId(5)


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


@dataclass
class _ActuatorPort:
    calls: list[tuple[ActuatorCommand, ...]] = field(
        default_factory=list
    )

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        self.calls.append(commands)
        raise AssertionError("factory must not apply actuator projection")


class _ConnectionFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("factory must not open a database connection")


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


def _sensor_policy(**overrides) -> TofSensorRuntimePolicy:
    values = {
        "disabled_zone_id": DISABLED_ZONE_ID,
        "ev_charging_zone_id": EV_ZONE_ID,
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


def _policy(**sensor_overrides) -> TofWarningRuntimePolicy:
    return TofWarningRuntimePolicy(
        sensor=_sensor_policy(**sensor_overrides),
        authorization=TofAuthorizationPolicy(
            occupancy_freshness_seconds=5.0,
            monitoring_freshness_seconds=5.0,
            max_pre_occupancy_observation_seconds=2.0,
        ),
    )


def _dependencies(
    *,
    sensor_array: _SensorArray | None = None,
    led_port: _ActuatorPort | None = None,
    speaker_port: _ActuatorPort | None = None,
    connection_factory: _ConnectionFactory | None = None,
) -> TofWarningRuntimeDependencies:
    return TofWarningRuntimeDependencies(
        sensor_array=sensor_array or _SensorArray(),
        led_port=led_port or _ActuatorPort(),
        speaker_port=speaker_port or _ActuatorPort(),
        connection_factory=(
            connection_factory or _ConnectionFactory()
        ),
    )


def test_factory_builds_unstarted_runtime_without_io() -> None:
    sensor_array = _SensorArray()
    led_port = _ActuatorPort()
    speaker_port = _ActuatorPort()
    connection_factory = _ConnectionFactory()

    runtime = build_tof_warning_runtime(
        zones=_zones(),
        policy=_policy(),
        dependencies=_dependencies(
            sensor_array=sensor_array,
            led_port=led_port,
            speaker_port=speaker_port,
            connection_factory=connection_factory,
        ),
    )

    assert not hasattr(runtime, "mailbox")
    assert isinstance(
        runtime._mailbox,
        TofAuthorizationRequestMailbox,
    )
    assert isinstance(runtime.sensor_worker, SensorWorker)
    assert isinstance(
        runtime.authorization_coordinator,
        TofZoneAuthorizationCoordinator,
    )
    assert isinstance(runtime.authorization_worker, TofAuthorizationWorker)
    assert isinstance(
        runtime.local_warning_coordinator,
        LocalWarningCoordinator,
    )

    assert runtime.sensor_worker.is_running is False
    assert runtime.sensor_worker.failure is None
    assert runtime.authorization_worker.is_running is False
    assert runtime.authorization_worker.failure is None
    assert runtime.local_warning_coordinator.active_zone_ids() == ()

    assert sensor_array.open_calls == 0
    assert sensor_array.read_calls == 0
    assert sensor_array.close_calls == 0
    assert led_port.calls == []
    assert speaker_port.calls == []
    assert connection_factory.calls == 0


def test_factory_wires_components_in_required_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    construction_order = []
    captured = {}

    class _MailboxDouble:
        def __init__(self) -> None:
            construction_order.append("mailbox")
            self.monitoring_requests = 0
            self.frame_requests: list[bool] = []

        def request_transitions(self, _transitions) -> None:
            raise AssertionError("factory must not publish transitions")

        def request_after_monitoring_commit(self) -> None:
            self.monitoring_requests += 1

        def request_after_monitoring_frame_commit(
            self,
            *,
            context_changed: bool = False,
        ) -> None:
            self.frame_requests.append(context_changed)

    class _SensorWorkerDouble:
        def __init__(self) -> None:
            self.is_running = False
            self.failure = None
            self.snapshot_value = ()

        def snapshots(self):
            return self.snapshot_value

        def start(self) -> None:
            raise AssertionError("factory must not start sensor worker")

    sensor_worker = _SensorWorkerDouble()

    def build_sensor_worker(**arguments):
        construction_order.append("sensor_worker")
        captured["sensor_worker"] = arguments
        return sensor_worker

    class _LocalWarningCoordinatorDouble:
        def __init__(self, **arguments) -> None:
            construction_order.append("local_warning")
            captured["local_warning"] = arguments

        def consume_assessment(self, _assessment) -> None:
            raise AssertionError("factory must not consume assessments")

    class _QueryDouble:
        def __init__(self, **arguments) -> None:
            construction_order.append("query")
            captured["query"] = arguments

    class _ServiceDouble:
        def __init__(self, **arguments) -> None:
            construction_order.append("service")
            captured["service"] = arguments

    class _CoordinatorDouble:
        def __init__(self, **arguments) -> None:
            construction_order.append("coordinator")
            captured["coordinator"] = arguments
            self.drain_calls = 0

        def drain_pending(self):
            self.drain_calls += 1
            raise AssertionError("factory must not drain authorization")

    class _AuthorizationWorkerDouble:
        def __init__(self, **arguments) -> None:
            construction_order.append("authorization_worker")
            captured["authorization_worker"] = arguments
            self.is_running = False
            self.failure = None

        def start(self) -> None:
            raise AssertionError(
                "factory must not start authorization worker"
            )

    monkeypatch.setattr(
        factory_module,
        "TofAuthorizationRequestMailbox",
        _MailboxDouble,
    )
    monkeypatch.setattr(
        factory_module,
        "build_tof_sensor_worker",
        build_sensor_worker,
    )
    monkeypatch.setattr(
        factory_module,
        "LocalWarningCoordinator",
        _LocalWarningCoordinatorDouble,
    )
    monkeypatch.setattr(
        factory_module,
        "RepositoryTofZoneAuthorizationQuery",
        _QueryDouble,
    )
    monkeypatch.setattr(
        factory_module,
        "TofZoneAuthorizationService",
        _ServiceDouble,
    )
    monkeypatch.setattr(
        factory_module,
        "TofZoneAuthorizationCoordinator",
        _CoordinatorDouble,
    )
    monkeypatch.setattr(
        factory_module,
        "TofAuthorizationWorker",
        _AuthorizationWorkerDouble,
    )

    zones = _zones()
    policy = _policy()
    sensor_array = _SensorArray()
    led_port = _ActuatorPort()
    speaker_port = _ActuatorPort()
    connection_factory = _ConnectionFactory()

    runtime = build_tof_warning_runtime(
        zones=zones,
        policy=policy,
        dependencies=_dependencies(
            sensor_array=sensor_array,
            led_port=led_port,
            speaker_port=speaker_port,
            connection_factory=connection_factory,
        ),
    )

    assert construction_order == [
        "mailbox",
        "sensor_worker",
        "local_warning",
        "query",
        "service",
        "coordinator",
        "authorization_worker",
    ]

    assert not hasattr(runtime, "mailbox")
    assert not hasattr(runtime, "request_after_monitoring_commit")
    mailbox = runtime._mailbox
    sensor_arguments = captured["sensor_worker"]
    assert sensor_arguments["zones"] is zones
    assert sensor_arguments["policy"] is policy.sensor
    assert sensor_arguments["dependencies"].sensor_array is sensor_array
    transition_consumer = (
        sensor_arguments["dependencies"].transition_consumer
    )
    assert transition_consumer.__self__ is mailbox
    assert transition_consumer.__func__ is _MailboxDouble.request_transitions

    local_arguments = captured["local_warning"]
    assert local_arguments["led_port"] is led_port
    assert local_arguments["speaker_port"] is speaker_port
    disabled_binding, ev_binding = local_arguments["bindings"]
    assert (
        disabled_binding.zone_id,
        disabled_binding.zone_type,
        disabled_binding.led_actuator_id,
        disabled_binding.led_action,
        disabled_binding.speaker_actuator_id,
        disabled_binding.speaker_action,
    ) == (
        DISABLED_ZONE_ID,
        ZoneType.DISABLED,
        DISABLED_ZONE_WARNING_LED_ID,
        BLINK_ACTION,
        DISABLED_ZONE_WARNING_SPEAKER_ID,
        PLAY_ACTION,
    )
    assert (
        ev_binding.zone_id,
        ev_binding.zone_type,
        ev_binding.led_actuator_id,
        ev_binding.led_action,
        ev_binding.speaker_actuator_id,
        ev_binding.speaker_action,
    ) == (
        EV_ZONE_ID,
        ZoneType.EV_CHARGING,
        EV_ZONE_WARNING_LED_ID,
        BLINK_ACTION,
        EV_ZONE_WARNING_SPEAKER_ID,
        PLAY_ACTION,
    )

    service_arguments = captured["service"]
    assert service_arguments["zones"] is zones
    assert service_arguments["policy"] is policy.authorization
    assert isinstance(service_arguments["query"], _QueryDouble)
    assert isinstance(
        captured["query"]["projection_store"],
        LatestTofMonitoringProjectionStore,
    )
    assert (
        runtime._monitoring_projection_store
        is captured["query"]["projection_store"]
    )

    coordinator_arguments = captured["coordinator"]
    snapshots = coordinator_arguments["occupancy_snapshots"]
    assert snapshots.__self__ is sensor_worker
    assert snapshots.__func__ is _SensorWorkerDouble.snapshots
    assert snapshots() == ()
    assert coordinator_arguments["connection_factory"] is connection_factory

    availability = coordinator_arguments["sensor_runtime_available"]
    assert availability() is False
    sensor_worker.is_running = True
    assert availability() is True
    sensor_worker.failure = RuntimeError("sensor failed")
    assert availability() is False
    sensor_worker.is_running = False
    sensor_worker.failure = None
    assert availability() is False

    local_coordinator = runtime.local_warning_coordinator
    assessment_consumer = coordinator_arguments["assessment_consumer"]
    assert assessment_consumer.__self__ is local_coordinator
    assert (
        assessment_consumer.__func__
        is _LocalWarningCoordinatorDouble.consume_assessment
    )

    worker_arguments = captured["authorization_worker"]
    assert worker_arguments["coordinator"] is runtime.authorization_coordinator
    assert worker_arguments["mailbox"] is mailbox
    assert worker_arguments["policy"] is policy.reevaluation
    assert (
        worker_arguments["policy"].initial_backoff_seconds
        == 0.25
    )
    assert worker_arguments["policy"].max_backoff_seconds == 2.0
    assert worker_arguments["policy"].backoff_multiplier == 2.0

    calls_before_signal = construction_order.copy()
    assert runtime.request_after_monitoring_context_change() is None
    assert mailbox.monitoring_requests == 1
    assert mailbox.frame_requests == []
    assert runtime.request_after_monitoring_frame_commit() is None
    assert mailbox.monitoring_requests == 1
    assert mailbox.frame_requests == [False]
    assert runtime.request_after_monitoring_frame_commit(
        context_changed=True,
    ) is None
    assert mailbox.monitoring_requests == 1
    assert mailbox.frame_requests == [False, True]
    assert construction_order == calls_before_signal
    assert runtime.authorization_coordinator.drain_calls == 0
    assert connection_factory.calls == 0
    assert runtime.sensor_worker.is_running is False
    assert runtime.authorization_worker.is_running is False
    assert led_port.calls == []
    assert speaker_port.calls == []


@pytest.mark.parametrize(
    ("zones", "sensor_overrides", "expected_message"),
    (
        (
            _zones(),
            {"disabled_zone_id": ZoneId(99)},
            "tof_disabled_zone_id",
        ),
        (
            _zones(disabled_type=ZoneType.GENERAL),
            {},
            "tof_disabled_zone_id.*DISABLED",
        ),
    ),
)
def test_factory_propagates_sensor_factory_zone_validation(
    zones: ZoneRegistry,
    sensor_overrides: dict[str, object],
    expected_message: str,
) -> None:
    sensor_array = _SensorArray()
    led_port = _ActuatorPort()
    speaker_port = _ActuatorPort()
    connection_factory = _ConnectionFactory()

    with pytest.raises(ValueError, match=expected_message):
        build_tof_warning_runtime(
            zones=zones,
            policy=_policy(**sensor_overrides),
            dependencies=_dependencies(
                sensor_array=sensor_array,
                led_port=led_port,
                speaker_port=speaker_port,
                connection_factory=connection_factory,
            ),
        )

    assert sensor_array.open_calls == 0
    assert sensor_array.read_calls == 0
    assert sensor_array.close_calls == 0
    assert led_port.calls == []
    assert speaker_port.calls == []
    assert connection_factory.calls == 0

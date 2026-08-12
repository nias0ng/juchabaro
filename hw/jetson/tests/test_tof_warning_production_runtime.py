"""ToF production hardware와 Worker lifecycle 격리를 검증한다."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.tof_warning_production_runtime as runtime_module
from src.application.tof_warning_runtime_factory import (
    TofWarningRuntimeDependencies,
    TofWarningRuntimePolicy,
)
from src.parking.models import (
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.tof_warning_production_runtime import (
    JetsonTofWarningRuntime,
    TofWarningHardwareFactories,
    build_jetson_tof_warning_runtime,
)


DISABLED_ZONE_ID = ZoneId(4)
EV_ZONE_ID = ZoneId(5)


class _ConnectionFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("builder must not open database connections")


class _SensorArray:
    def __init__(self) -> None:
        self.open_calls = 0
        self.read_calls = 0
        self.close_calls = 0

    def open(self) -> None:
        self.open_calls += 1
        raise AssertionError("production owner must not open SensorArray")

    def read_all(self):
        self.read_calls += 1
        raise AssertionError("builder must not read SensorArray")

    def close(self) -> None:
        self.close_calls += 1


class _ActuatorAdapter:
    def __init__(
        self,
        name: str,
        events: list[object],
    ) -> None:
        self.name = name
        self.events = events
        self.open_error: Exception | None = None
        self.projection_error: Exception | None = None
        self.close_error: Exception | None = None

    def open(self) -> None:
        self.events.append(f"{self.name}.open")
        if self.open_error is not None:
            raise self.open_error

    def apply_projection(self, commands) -> None:
        self.events.append((f"{self.name}.projection", commands))
        if self.projection_error is not None:
            raise self.projection_error

    def close(self) -> None:
        self.events.append(f"{self.name}.close")
        if self.close_error is not None:
            raise self.close_error


class _AudioBackend:
    def __init__(self, events: list[object]) -> None:
        self.events = events
        self.close_error: Exception | None = None

    def close(self) -> None:
        self.events.append("audio.close")
        if self.close_error is not None:
            raise self.close_error


@dataclass(frozen=True)
class _StopOutcome:
    error: Exception | None = None
    remains_running: bool = False


class _Worker:
    def __init__(
        self,
        name: str,
        events: list[object],
    ) -> None:
        self.name = name
        self.events = events
        self.start_error: Exception | None = None
        self.stop_outcomes: list[_StopOutcome] = []
        self.is_running = False
        self.failure = None

    def start(self) -> None:
        self.events.append(f"{self.name}.start")
        if self.start_error is not None:
            raise self.start_error
        self.is_running = True

    def stop(self) -> None:
        self.events.append(f"{self.name}.stop")
        outcome = (
            self.stop_outcomes.pop(0)
            if self.stop_outcomes
            else _StopOutcome()
        )
        self.is_running = outcome.remains_running
        if outcome.error is not None:
            raise outcome.error


class _Coordinator:
    def __init__(self) -> None:
        self.drain_calls = 0

    def drain_pending(self):
        self.drain_calls += 1
        raise AssertionError("production owner must not drain coordinator")


class _PureRuntime:
    def __init__(self, events: list[object]) -> None:
        self.sensor_worker = _Worker("sensor", events)
        self.authorization_worker = _Worker(
            "authorization",
            events,
        )
        self.authorization_coordinator = _Coordinator()
        self.local_warning_coordinator = object()


class _RuntimeBuilder:
    def __init__(self, events: list[object]) -> None:
        self.runtime = _PureRuntime(events)
        self.calls: list[dict[str, object]] = []
        self.error: Exception | None = None

    def __call__(self, **arguments):
        self.calls.append(arguments)
        if self.error is not None:
            raise self.error
        return self.runtime


class _HardwareCapture:
    def __init__(self) -> None:
        self.events: list[object] = []
        self.sensor_array = _SensorArray()
        self.led_adapter = _ActuatorAdapter("led", self.events)
        self.speaker_adapter = _ActuatorAdapter(
            "speaker",
            self.events,
        )
        self.audio_backend = _AudioBackend(self.events)

        self.sensor_factory_calls: list[dict[str, object]] = []
        self.led_factory_calls = 0
        self.audio_factory_calls: list[dict[str, object]] = []
        self.speaker_factory_calls: list[dict[str, object]] = []

        self.sensor_factory_error: Exception | None = None
        self.led_factory_error: Exception | None = None
        self.audio_factory_error: Exception | None = None
        self.speaker_factory_error: Exception | None = None

    def create_sensor_array(self, **arguments):
        self.sensor_factory_calls.append(arguments)
        if self.sensor_factory_error is not None:
            raise self.sensor_factory_error
        return self.sensor_array

    def create_led_adapter(self):
        self.led_factory_calls += 1
        if self.led_factory_error is not None:
            raise self.led_factory_error
        return self.led_adapter

    def create_audio_backend(self, **arguments):
        self.audio_factory_calls.append(arguments)
        if self.audio_factory_error is not None:
            raise self.audio_factory_error
        return self.audio_backend

    def create_speaker_adapter(self, **arguments):
        self.speaker_factory_calls.append(arguments)
        if self.speaker_factory_error is not None:
            raise self.speaker_factory_error
        return self.speaker_adapter

    def factories(self) -> TofWarningHardwareFactories:
        return TofWarningHardwareFactories(
            sensor_array_factory=self.create_sensor_array,
            led_adapter_factory=self.create_led_adapter,
            audio_backend_factory=self.create_audio_backend,
            speaker_adapter_factory=self.create_speaker_adapter,
        )


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
) -> ZoneRegistry:
    return ZoneRegistry(
        (
            _zone(4, disabled_type, left=0.1),
            _zone(5, ZoneType.EV_CHARGING, left=0.3),
        )
    )


def _settings(**overrides):
    values = {
        "tof_enabled": True,
        "tof_i2c_bus": 7,
        "tof_shutdown_settle_seconds": 0.01,
        "tof_boot_settle_seconds": 0.02,
        "tof_io_timeout_seconds": 0.03,
        "tof_disabled_zone_id": 4,
        "tof_ev_charging_zone_id": 5,
        "tof_poll_interval_seconds": 0.05,
        "tof_enter_distance_mm": 150.0,
        "tof_exit_distance_mm": 220.0,
        "tof_enter_confirm_seconds": 0.1,
        "tof_exit_confirm_seconds": 0.2,
        "tof_trusted_sample_max_gap_seconds": 1.0,
        "tof_stale_after_seconds": 2.0,
        "tof_diagnostic_interval_seconds": 5.0,
        "tof_occupancy_freshness_seconds": 5.0,
        "tof_monitoring_freshness_seconds": 6.0,
        "tof_max_pre_occupancy_observation_seconds": 2.0,
        "tof_reevaluation_initial_backoff_seconds": 0.4,
        "tof_reevaluation_max_backoff_seconds": 3.0,
        "tof_reevaluation_backoff_multiplier": 1.5,
        "tof_disabled_zone_warning_wav_path": Path(
            "unverified/disabled.wav"
        ),
        "tof_ev_zone_warning_wav_path": Path(
            "unverified/ev.wav"
        ),
        "tof_warning_audio_device": "plughw:CARD=USB,DEV=0",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _build_with_fake_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    settings=None,
    hardware: _HardwareCapture | None = None,
):
    active_hardware = hardware or _HardwareCapture()
    builder = _RuntimeBuilder(active_hardware.events)
    monkeypatch.setattr(
        runtime_module,
        "build_tof_warning_runtime",
        builder,
    )
    connection_factory = _ConnectionFactory()

    owner = build_jetson_tof_warning_runtime(
        settings=settings or _settings(),
        zones=_zones(),
        connection_factory=connection_factory,
        factories=active_hardware.factories(),
    )
    return owner, active_hardware, builder, connection_factory


def test_disabled_runtime_calls_no_hardware_or_database_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hardware = _HardwareCapture()
    builder = _RuntimeBuilder(hardware.events)
    monkeypatch.setattr(
        runtime_module,
        "build_tof_warning_runtime",
        builder,
    )
    connection_factory = _ConnectionFactory()

    result = build_jetson_tof_warning_runtime(
        settings=_settings(tof_enabled=False),
        zones=_zones(),
        connection_factory=connection_factory,
        factories=hardware.factories(),
    )

    assert result is None
    assert hardware.sensor_factory_calls == []
    assert hardware.led_factory_calls == 0
    assert hardware.audio_factory_calls == []
    assert hardware.speaker_factory_calls == []
    assert builder.calls == []
    assert connection_factory.calls == 0


def test_complete_settings_are_mapped_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, builder, connection_factory = (
        _build_with_fake_runtime(monkeypatch)
    )

    assert isinstance(owner, JetsonTofWarningRuntime)
    assert hardware.sensor_factory_calls == [
        {
            "i2c_bus": 7,
            "shutdown_settle_seconds": 0.01,
            "boot_settle_seconds": 0.02,
            "io_timeout_seconds": 0.03,
        }
    ]
    assert hardware.led_factory_calls == 1
    assert hardware.audio_factory_calls == [
        {"device": "plughw:CARD=USB,DEV=0"}
    ]

    speaker_arguments = hardware.speaker_factory_calls[0]
    assert speaker_arguments["backend"] is hardware.audio_backend
    assert speaker_arguments[
        "disabled_zone_warning_wav_path"
    ] == Path("unverified/disabled.wav")
    assert speaker_arguments[
        "ev_zone_warning_wav_path"
    ] == Path("unverified/ev.wav")

    build_arguments = builder.calls[0]
    policy = build_arguments["policy"]
    assert isinstance(policy, TofWarningRuntimePolicy)
    assert policy.sensor.disabled_zone_id == DISABLED_ZONE_ID
    assert policy.sensor.ev_charging_zone_id == EV_ZONE_ID
    assert policy.sensor.poll_interval_seconds == 0.05
    assert policy.sensor.enter_distance_mm == 150.0
    assert policy.sensor.exit_distance_mm == 220.0
    assert policy.sensor.enter_confirm_seconds == 0.1
    assert policy.sensor.exit_confirm_seconds == 0.2
    assert policy.sensor.trusted_sample_max_gap_seconds == 1.0
    assert policy.sensor.stale_after_seconds == 2.0
    assert policy.sensor.diagnostic_interval_seconds == 5.0
    assert policy.authorization.occupancy_freshness_seconds == 5.0
    assert policy.authorization.monitoring_freshness_seconds == 6.0
    assert (
        policy.authorization.max_pre_occupancy_observation_seconds
        == 2.0
    )
    assert policy.reevaluation.initial_backoff_seconds == 0.4
    assert policy.reevaluation.max_backoff_seconds == 3.0
    assert policy.reevaluation.backoff_multiplier == 1.5

    dependencies = build_arguments["dependencies"]
    assert isinstance(dependencies, TofWarningRuntimeDependencies)
    assert dependencies.sensor_array is hardware.sensor_array
    assert owner.runtime is builder.runtime

    assert hardware.events == []
    assert hardware.sensor_array.open_calls == 0
    assert hardware.sensor_array.read_calls == 0
    assert hardware.sensor_array.close_calls == 0
    assert builder.runtime.authorization_coordinator.drain_calls == 0
    assert connection_factory.calls == 0


def test_missing_core_fields_are_reported_in_deterministic_order(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hardware = _HardwareCapture()
    builder = _RuntimeBuilder(hardware.events)
    monkeypatch.setattr(
        runtime_module,
        "build_tof_warning_runtime",
        builder,
    )

    with caplog.at_level(logging.ERROR):
        result = build_jetson_tof_warning_runtime(
            settings=_settings(
                tof_i2c_bus=None,
                tof_poll_interval_seconds=None,
                tof_occupancy_freshness_seconds=None,
            ),
            zones=_zones(),
            connection_factory=_ConnectionFactory(),
            factories=hardware.factories(),
        )

    assert result is None
    assert (
        "missing=tof_i2c_bus,tof_poll_interval_seconds,"
        "tof_occupancy_freshness_seconds"
    ) in caplog.text
    assert hardware.sensor_factory_calls == []
    assert hardware.led_factory_calls == 0
    assert builder.calls == []


def test_invalid_reevaluation_policy_stops_before_hardware_creation(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    hardware = _HardwareCapture()
    builder = _RuntimeBuilder(hardware.events)
    monkeypatch.setattr(
        runtime_module,
        "build_tof_warning_runtime",
        builder,
    )
    connection_factory = _ConnectionFactory()

    with caplog.at_level(logging.ERROR):
        result = build_jetson_tof_warning_runtime(
            settings=_settings(
                tof_reevaluation_initial_backoff_seconds=2.0,
                tof_reevaluation_max_backoff_seconds=1.0,
            ),
            zones=_zones(),
            connection_factory=connection_factory,
            factories=hardware.factories(),
        )

    assert result is None
    assert hardware.sensor_factory_calls == []
    assert hardware.led_factory_calls == 0
    assert hardware.audio_factory_calls == []
    assert hardware.speaker_factory_calls == []
    assert builder.calls == []
    assert connection_factory.calls == 0
    assert "component=tof_authorization_reevaluation" in caplog.text
    assert "stage=settings_validation" in caplog.text


def test_sensor_array_factory_failure_stops_before_actuator_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hardware = _HardwareCapture()
    hardware.sensor_factory_error = RuntimeError(
        "sensor construction failed"
    )
    builder = _RuntimeBuilder(hardware.events)
    monkeypatch.setattr(
        runtime_module,
        "build_tof_warning_runtime",
        builder,
    )
    connection_factory = _ConnectionFactory()

    result = build_jetson_tof_warning_runtime(
        settings=_settings(),
        zones=_zones(),
        connection_factory=connection_factory,
        factories=hardware.factories(),
    )

    assert result is None
    assert hardware.led_factory_calls == 0
    assert hardware.audio_factory_calls == []
    assert hardware.speaker_factory_calls == []
    assert hardware.events == []
    assert builder.calls == []
    assert connection_factory.calls == 0


def test_real_runtime_factory_zone_validation_opens_no_device() -> None:
    hardware = _HardwareCapture()
    connection_factory = _ConnectionFactory()

    # build_tof_warning_runtime을 monkeypatch하지 않아 실제 sensor factory의
    # zone type 검증과 production builder 연결을 함께 확인한다.
    result = build_jetson_tof_warning_runtime(
        settings=_settings(),
        zones=_zones(disabled_type=ZoneType.GENERAL),
        connection_factory=connection_factory,
        factories=hardware.factories(),
    )

    assert result is None
    assert hardware.events == []
    assert hardware.sensor_array.open_calls == 0
    assert hardware.sensor_array.read_calls == 0
    assert hardware.sensor_array.close_calls == 0
    assert connection_factory.calls == 0


def test_led_factory_failure_keeps_speaker_and_runtime_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hardware = _HardwareCapture()
    led_error = RuntimeError("LED construction failed")
    hardware.led_factory_error = led_error

    owner, _, builder, _ = _build_with_fake_runtime(
        monkeypatch,
        hardware=hardware,
    )
    assert owner is not None

    assert hardware.audio_factory_calls
    assert hardware.speaker_factory_calls
    owner.prepare()
    assert hardware.events == ["speaker.open"]

    owner.start()
    assert builder.runtime.sensor_worker.is_running is True
    assert (
        "led",
        "construction",
        led_error,
    ) in {
        (failure.component, failure.stage, failure.error)
        for failure in owner.failures
    }


def test_audio_backend_factory_failure_isolates_speaker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hardware = _HardwareCapture()
    audio_error = RuntimeError("audio construction failed")
    hardware.audio_factory_error = audio_error

    owner, _, builder, _ = _build_with_fake_runtime(
        monkeypatch,
        hardware=hardware,
    )
    assert owner is not None

    assert hardware.speaker_factory_calls == []
    owner.prepare()
    assert hardware.events == ["led.open"]
    owner.start()
    assert builder.runtime.sensor_worker.is_running is True
    assert (
        "speaker",
        "construction",
        audio_error,
    ) in {
        (failure.component, failure.stage, failure.error)
        for failure in owner.failures
    }


@pytest.mark.parametrize("backend_cleanup_fails", (False, True))
def test_speaker_factory_failure_closes_backend_and_records_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    backend_cleanup_fails: bool,
) -> None:
    hardware = _HardwareCapture()
    speaker_error = RuntimeError("speaker construction failed")
    cleanup_error = RuntimeError("backend cleanup failed")
    hardware.speaker_factory_error = speaker_error
    if backend_cleanup_fails:
        hardware.audio_backend.close_error = cleanup_error

    owner, _, _, _ = _build_with_fake_runtime(
        monkeypatch,
        hardware=hardware,
    )
    assert owner is not None

    assert hardware.events == ["audio.close"]
    failures = {
        (failure.component, failure.stage, failure.error)
        for failure in owner.failures
    }
    assert (
        "speaker",
        "construction",
        speaker_error,
    ) in failures

    if backend_cleanup_fails:
        assert (
            "speaker",
            "construction_rollback",
            cleanup_error,
        ) in failures
    else:
        assert not any(
            stage == "construction_rollback"
            for _, stage, _ in failures
        )


def test_missing_and_partial_speaker_configuration_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    missing_hardware = _HardwareCapture()
    missing_owner, _, missing_builder, _ = _build_with_fake_runtime(
        monkeypatch,
        settings=_settings(
            tof_disabled_zone_warning_wav_path=None,
            tof_ev_zone_warning_wav_path=None,
            tof_warning_audio_device=None,
        ),
        hardware=missing_hardware,
    )
    assert missing_owner is not None
    assert missing_hardware.audio_factory_calls == []
    assert missing_hardware.speaker_factory_calls == []

    missing_owner.prepare()
    assert missing_hardware.events == ["led.open"]
    missing_owner.start()
    assert missing_builder.runtime.sensor_worker.is_running is True

    partial_hardware = _HardwareCapture()
    with caplog.at_level(logging.ERROR):
        partial_owner, _, _, _ = _build_with_fake_runtime(
            monkeypatch,
            settings=_settings(
                tof_ev_zone_warning_wav_path=None,
                tof_warning_audio_device=None,
            ),
            hardware=partial_hardware,
        )

    assert partial_owner is not None
    assert partial_hardware.audio_factory_calls == []
    assert partial_hardware.speaker_factory_calls == []
    assert "부분적으로만 제공" in caplog.text
    assert [
        (failure.component, failure.stage)
        for failure in partial_owner.failures
    ] == [("speaker", "configuration")]


@pytest.mark.parametrize("failed_component", ("led", "speaker"))
def test_actuator_open_failure_isolated_from_other_port_and_sensor(
    monkeypatch: pytest.MonkeyPatch,
    failed_component: str,
) -> None:
    hardware = _HardwareCapture()
    open_error = RuntimeError(f"{failed_component} open failed")
    failed_adapter = (
        hardware.led_adapter
        if failed_component == "led"
        else hardware.speaker_adapter
    )
    failed_adapter.open_error = open_error

    owner, _, builder, _ = _build_with_fake_runtime(
        monkeypatch,
        hardware=hardware,
    )
    assert owner is not None

    owner.prepare()

    assert "led.open" in hardware.events
    assert "speaker.open" in hardware.events

    owner.start()
    assert builder.runtime.authorization_worker.is_running is True
    assert builder.runtime.sensor_worker.is_running is True

    dependencies = builder.calls[0]["dependencies"]
    failed_port = (
        dependencies.led_port
        if failed_component == "led"
        else dependencies.speaker_port
    )
    events_before_projection = list(hardware.events)
    failed_port.apply_projection(())
    assert hardware.events == events_before_projection

    assert (
        failed_component,
        "open",
        open_error,
    ) in {
        (failure.component, failure.stage, failure.error)
        for failure in owner.failures
    }


@pytest.mark.parametrize("failed_component", ("led", "speaker"))
def test_open_rollback_failure_does_not_block_other_port(
    monkeypatch: pytest.MonkeyPatch,
    failed_component: str,
) -> None:
    hardware = _HardwareCapture()
    failed_adapter = (
        hardware.led_adapter
        if failed_component == "led"
        else hardware.speaker_adapter
    )
    failed_adapter.open_error = RuntimeError("open failed")
    rollback_error = RuntimeError("rollback failed")
    failed_adapter.close_error = rollback_error

    owner, _, _, _ = _build_with_fake_runtime(
        monkeypatch,
        hardware=hardware,
    )
    assert owner is not None

    owner.prepare()

    assert "led.open" in hardware.events
    assert "speaker.open" in hardware.events
    assert (
        failed_component,
        "open_rollback",
        rollback_error,
    ) in {
        (failure.component, failure.stage, failure.error)
        for failure in owner.failures
    }


def test_prepare_and_start_lifecycle_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, builder, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None

    with pytest.raises(RuntimeError, match="prepared before start"):
        owner.start()

    owner.prepare()
    events_after_prepare = list(hardware.events)
    owner.prepare()
    assert hardware.events == events_after_prepare

    owner.start()
    assert owner.workers_started is True
    assert owner.both_workers_running is True

    # workers_started는 시작 성공 이력이고 현재 실행 여부와 분리된다.
    builder.runtime.sensor_worker.is_running = False
    assert owner.workers_started is True
    assert owner.both_workers_running is False
    builder.runtime.sensor_worker.is_running = True

    with pytest.raises(RuntimeError, match="only be started once"):
        owner.start()

    owner.stop_workers()
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        owner.start()


def test_authorization_start_failure_does_not_start_sensor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, builder, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None
    owner.prepare()
    hardware.events.clear()

    start_error = RuntimeError("authorization start failed")
    builder.runtime.authorization_worker.start_error = start_error

    owner.start()

    assert hardware.events == ["authorization.start"]
    assert builder.runtime.sensor_worker.is_running is False
    assert owner.workers_started is False
    assert owner.failures[-1].error is start_error


def test_sensor_start_failure_stops_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, builder, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None
    owner.prepare()
    hardware.events.clear()

    start_error = RuntimeError("sensor start failed")
    builder.runtime.sensor_worker.start_error = start_error

    owner.start()

    assert hardware.events == [
        "authorization.start",
        "sensor.start",
        "authorization.stop",
    ]
    assert builder.runtime.authorization_worker.is_running is False
    assert owner.workers_started is False
    assert owner.failures[-1].error is start_error


def test_stop_exception_retries_only_worker_still_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, builder, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None
    owner.prepare()
    owner.start()
    hardware.events.clear()

    stop_error = RuntimeError("sensor stop failed")
    sensor_worker = builder.runtime.sensor_worker
    sensor_worker.stop_outcomes = [
        _StopOutcome(
            error=stop_error,
            remains_running=True,
        ),
        _StopOutcome(),
    ]

    owner.stop_workers()

    assert hardware.events == [
        "sensor.stop",
        "authorization.stop",
    ]
    assert sensor_worker.is_running is True
    assert builder.runtime.authorization_worker.is_running is False

    with pytest.raises(RuntimeError, match="must be stopped"):
        owner.close()

    hardware.events.clear()
    owner.stop_workers()

    assert hardware.events == ["sensor.stop"]
    assert sensor_worker.is_running is False
    assert owner.failures[0].error is stop_error


def test_stop_normal_return_while_running_records_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, builder, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None
    owner.prepare()
    owner.start()
    hardware.events.clear()

    sensor_worker = builder.runtime.sensor_worker
    sensor_worker.stop_outcomes = [
        _StopOutcome(remains_running=True),
        _StopOutcome(),
    ]

    owner.stop_workers()

    assert hardware.events == [
        "sensor.stop",
        "authorization.stop",
    ]
    assert sensor_worker.is_running is True
    assert builder.runtime.authorization_worker.is_running is False

    incomplete_failures = [
        failure
        for failure in owner.failures
        if (
            failure.component == "sensor_worker"
            and failure.stage == "stop_incomplete"
        )
    ]
    assert len(incomplete_failures) == 1

    hardware.events.clear()
    owner.stop_workers()

    assert hardware.events == ["sensor.stop"]
    assert sensor_worker.is_running is False


def test_stop_order_precedes_projection_and_close_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, _, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None
    owner.prepare()
    hardware.events.clear()

    owner.start()
    owner.stop_workers()
    owner.close()

    assert hardware.events == [
        "authorization.start",
        "sensor.start",
        "sensor.stop",
        "authorization.stop",
        ("speaker.projection", ()),
        ("led.projection", ()),
        "speaker.close",
        "led.close",
    ]


def test_cleanup_failures_do_not_block_remaining_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, _, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None
    owner.prepare()
    hardware.events.clear()

    speaker_projection_error = RuntimeError("speaker clear failed")
    speaker_close_error = RuntimeError("speaker close failed")
    led_close_error = RuntimeError("LED close failed")

    hardware.speaker_adapter.projection_error = (
        speaker_projection_error
    )
    hardware.speaker_adapter.close_error = speaker_close_error
    hardware.led_adapter.close_error = led_close_error

    owner.close()

    assert hardware.events == [
        ("speaker.projection", ()),
        ("led.projection", ()),
        "speaker.close",
        "led.close",
    ]
    assert {
        (failure.component, failure.stage, failure.error)
        for failure in owner.failures
    } >= {
        (
            "speaker",
            "projection_clear",
            speaker_projection_error,
        ),
        ("speaker", "close", speaker_close_error),
        ("led", "close", led_close_error),
    }

    events_after_close = list(hardware.events)
    owner.close()
    assert hardware.events == events_after_close


def test_close_rejects_running_workers_and_closed_runtime_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner, hardware, _, _ = _build_with_fake_runtime(monkeypatch)
    assert owner is not None
    owner.prepare()
    owner.start()

    with pytest.raises(RuntimeError, match="must be stopped"):
        owner.close()

    owner.stop_workers()
    owner.close()

    assert hardware.sensor_array.close_calls == 0

    events_after_close = list(hardware.events)
    owner.close()
    assert hardware.events == events_after_close

    with pytest.raises(RuntimeError, match="cannot be prepared"):
        owner.prepare()
    with pytest.raises(RuntimeError, match="cannot be started"):
        owner.start()

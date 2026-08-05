"""실제 하드웨어 없이 VL53L0X 듀얼 센서 배열 계약을 검증한다.

이 파일의 시간 설정값은 단위 테스트용이며 실제 배포 기본값을 의미하지 않는다.
"""

from __future__ import annotations

import builtins
from datetime import datetime, timezone
from typing import Any

import pytest

from src.sensors.adapters import vl53l0x_array as adapter_module
from src.sensors.adapters.vl53l0x_array import Vl53l0xArray
from src.sensors.models import (
    TOF_SENSOR_TYPE,
    SensorReadFailureReason,
)
from src.sensors.ports import (
    SensorArrayCleanupError,
    SensorArrayInitializationError,
    SensorArrayStateError,
)


NOW = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


# [Fakes]


class FakeGPIO:
    BOARD = "BOARD"
    OUT = "OUT"
    IN = "IN"
    LOW = 0
    HIGH = 1

    def __init__(
        self,
        events: list[tuple[Any, ...]],
        *,
        setup_errors: dict[
            tuple[int, str],
            list[Exception | None],
        ]
        | None = None,
        output_errors: dict[
            tuple[int, int],
            list[Exception | None],
        ]
        | None = None,
        cleanup_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.setup_errors = {
            key: list(errors)
            for key, errors in (setup_errors or {}).items()
        }
        self.output_errors = {
            key: list(errors)
            for key, errors in (output_errors or {}).items()
        }
        self.cleanup_error = cleanup_error

    def setmode(self, mode: str) -> None:
        self.events.append(("gpio", "setmode", mode))

    def setup(
        self,
        pin: int,
        direction: str,
        initial: Any = None,
    ) -> None:
        self.events.append(
            ("gpio", "setup", pin, direction, initial)
        )
        errors = self.setup_errors.get((pin, direction))
        if errors:
            error = errors.pop(0)
            if error is not None:
                raise error

    def output(self, pin: int, value: int) -> None:
        self.events.append(("gpio", "output", pin, value))
        errors = self.output_errors.get((pin, value))
        if errors:
            error = errors.pop(0)
            if error is not None:
                raise error

    def cleanup(self, pins: tuple[int, ...]) -> None:
        self.events.append(("gpio", "cleanup", tuple(pins)))
        if self.cleanup_error is not None:
            raise self.cleanup_error


class FakeI2C:
    def __init__(
        self,
        name: str,
        events: list[tuple[Any, ...]],
        *,
        scan_results: list[set[int] | Exception],
        lock_results: list[bool] | None = None,
        default_lock_result: bool = True,
        deinit_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.scan_results = list(scan_results)
        self.lock_results = list(lock_results or [])
        self.default_lock_result = default_lock_result
        self.deinit_error = deinit_error

    def try_lock(self) -> bool:
        self.events.append((self.name, "try_lock"))
        if self.lock_results:
            return self.lock_results.pop(0)
        return self.default_lock_result

    def scan(self) -> list[int]:
        self.events.append((self.name, "scan"))
        result = self.scan_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return list(result)

    def unlock(self) -> None:
        self.events.append((self.name, "unlock"))

    def deinit(self) -> None:
        self.events.append((self.name, "deinit"))
        if self.deinit_error is not None:
            raise self.deinit_error


class FakeSensor:
    def __init__(
        self,
        name: str,
        events: list[tuple[Any, ...]],
        *,
        reading: Any,
        set_address_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.events = events
        self.reading = reading
        self.set_address_error = set_address_error

    def set_address(self, address: int) -> None:
        self.events.append((self.name, "set_address", address))
        if self.set_address_error is not None:
            raise self.set_address_error

    @property
    def range(self) -> Any:
        self.events.append((self.name, "range"))
        if isinstance(self.reading, BaseException):
            raise self.reading
        return self.reading


# [Helpers]


def _make_adapter(**overrides: Any) -> Vl53l0xArray:
    settings = {
        "i2c_bus": 7,
        "shutdown_settle_seconds": 0.01,
        "boot_settle_seconds": 0.02,
        "io_timeout_seconds": 1.0,
    }
    settings.update(overrides)
    return Vl53l0xArray(**settings)


def _install_hardware(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[tuple[Any, ...]],
    gpio: FakeGPIO,
    i2cs: list[FakeI2C],
    sensors: list[FakeSensor],
) -> None:
    i2c_queue = list(i2cs)
    sensor_queue = list(sensors)

    def i2c_factory(bus_number: int) -> FakeI2C:
        events.append(("i2c", "create", bus_number))
        return i2c_queue.pop(0)

    def sensor_factory(
        i2c: FakeI2C,
        *,
        address: int,
        io_timeout_s: float,
    ) -> FakeSensor:
        sensor = sensor_queue.pop(0)
        events.append(
            (
                "sensor",
                "create",
                sensor.name,
                i2c,
                address,
                io_timeout_s,
            )
        )
        return sensor

    def load_dependencies() -> tuple[Any, Any, Any]:
        events.append(("hardware", "load"))
        return gpio, i2c_factory, sensor_factory

    monkeypatch.setattr(
        adapter_module,
        "_load_hardware_dependencies",
        load_dependencies,
    )
    monkeypatch.setattr(
        adapter_module,
        "_sleep",
        lambda seconds: events.append(("sleep", seconds)),
    )
    monkeypatch.setattr(adapter_module, "_utc_now", lambda: NOW)


def _open_adapter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    readings: tuple[Any, Any] = (420, 840),
    events: list[tuple[Any, ...]] | None = None,
    gpio: FakeGPIO | None = None,
    i2c: FakeI2C | None = None,
) -> tuple[
    Vl53l0xArray,
    list[tuple[Any, ...]],
    FakeGPIO,
    FakeI2C,
    tuple[FakeSensor, FakeSensor],
]:
    active_events = events if events is not None else []
    active_gpio = gpio or FakeGPIO(active_events)
    active_i2c = i2c or FakeI2C(
        "i2c-1",
        active_events,
        scan_results=[set(), {0x30, 0x31}],
    )
    sensors = (
        FakeSensor(
            "sensor-1",
            active_events,
            reading=readings[0],
        ),
        FakeSensor(
            "sensor-2",
            active_events,
            reading=readings[1],
        ),
    )
    _install_hardware(
        monkeypatch,
        events=active_events,
        gpio=active_gpio,
        i2cs=[active_i2c],
        sensors=list(sensors),
    )
    adapter = _make_adapter()
    adapter.open()
    return adapter, active_events, active_gpio, active_i2c, sensors


def _assert_occurs_in_order(
    events: list[tuple[Any, ...]],
    expected_events: tuple[tuple[Any, ...], ...],
) -> None:
    position = 0
    for expected_event in expected_events:
        while (
            position < len(events)
            and events[position] != expected_event
        ):
            position += 1
        assert position < len(events), (
            f"이벤트를 순서대로 찾을 수 없습니다: {expected_event!r}; "
            f"전체 이벤트: {events!r}"
        )
        position += 1


def _assert_closed(adapter: Vl53l0xArray) -> None:
    with pytest.raises(SensorArrayStateError):
        adapter.read_all()


# [Constructor]


def test_constructor_accepts_valid_numeric_settings() -> None:
    adapter = Vl53l0xArray(
        i2c_bus=7,
        shutdown_settle_seconds=1,
        boot_settle_seconds=0.02,
        io_timeout_seconds=1.5,
    )

    _assert_closed(adapter)


@pytest.mark.parametrize(
    "i2c_bus",
    [-1, True, 1.5, "7"],
    ids=["negative", "bool", "float", "string"],
)
def test_constructor_rejects_invalid_i2c_bus(i2c_bus: Any) -> None:
    with pytest.raises(ValueError):
        _make_adapter(i2c_bus=i2c_bus)


@pytest.mark.parametrize(
    "setting_name",
    [
        "shutdown_settle_seconds",
        "boot_settle_seconds",
        "io_timeout_seconds",
    ],
)
@pytest.mark.parametrize(
    "invalid_value",
    [
        0,
        -0.1,
        True,
        False,
        "0.1",
        float("nan"),
        float("inf"),
        float("-inf"),
        10**10000,
    ],
    ids=[
        "zero",
        "negative",
        "true",
        "false",
        "numeric-string",
        "nan",
        "positive-infinity",
        "negative-infinity",
        "float-overflow",
    ],
)
def test_constructor_rejects_invalid_time_settings(
    setting_name: str,
    invalid_value: Any,
) -> None:
    with pytest.raises(ValueError):
        _make_adapter(**{setting_name: invalid_value})


# [Initialization]


def test_open_initializes_sensors_in_hardware_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, events, gpio, i2c, sensors = _open_adapter(monkeypatch)

    _assert_occurs_in_order(
        events,
        (
            ("hardware", "load"),
            ("gpio", "setmode", gpio.BOARD),
            ("gpio", "setup", 15, gpio.OUT, gpio.LOW),
            ("gpio", "setup", 29, gpio.OUT, gpio.LOW),
            ("sleep", 0.01),
            ("i2c", "create", 7),
            (i2c.name, "try_lock"),
            (i2c.name, "scan"),
            (i2c.name, "unlock"),
            ("gpio", "output", 15, gpio.HIGH),
            ("sleep", 0.02),
            (
                "sensor",
                "create",
                sensors[0].name,
                i2c,
                0x29,
                1.0,
            ),
            (sensors[0].name, "set_address", 0x30),
            ("gpio", "output", 29, gpio.HIGH),
            ("sleep", 0.02),
            (
                "sensor",
                "create",
                sensors[1].name,
                i2c,
                0x29,
                1.0,
            ),
            (sensors[1].name, "set_address", 0x31),
            (i2c.name, "try_lock"),
            (i2c.name, "scan"),
            (i2c.name, "unlock"),
        ),
    )
    assert not any(
        event[0:2] == ("gpio", "setup") and event[3] == gpio.IN
        for event in events
    )

    result = adapter.read_all()
    assert len(result.observations) == 2


@pytest.mark.parametrize(
    "failing_pin",
    [15, 29],
    ids=["disabled-zone", "ev-zone"],
)
def test_open_recovers_when_xshut_high_output_fails(
    monkeypatch: pytest.MonkeyPatch,
    failing_pin: int,
) -> None:
    events: list[tuple[Any, ...]] = []
    output_error = RuntimeError(
        f"pin {failing_pin} high output failed"
    )
    gpio = FakeGPIO(
        events,
        output_errors={
            (failing_pin, FakeGPIO.HIGH): [output_error],
        },
    )
    failed_i2c = FakeI2C(
        "i2c-failed",
        events,
        scan_results=[set()],
    )
    successful_i2c = FakeI2C(
        "i2c-success",
        events,
        scan_results=[set(), {0x30, 0x31}],
    )
    sensors: list[FakeSensor] = []
    if failing_pin == 29:
        sensors.append(
            FakeSensor(
                "failed-attempt-sensor-1",
                events,
                reading=420,
            )
        )
    sensors.extend(
        [
            FakeSensor("retry-sensor-1", events, reading=420),
            FakeSensor("retry-sensor-2", events, reading=840),
        ]
    )
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[failed_i2c, successful_i2c],
        sensors=sensors,
    )
    adapter = _make_adapter()

    with pytest.raises(
        SensorArrayInitializationError
    ) as exc_info:
        adapter.open()

    assert exc_info.value.__cause__ is output_error
    _assert_occurs_in_order(
        events,
        (
            ("gpio", "output", failing_pin, gpio.HIGH),
            ("gpio", "setup", 15, gpio.OUT, gpio.LOW),
            ("gpio", "setup", 29, gpio.OUT, gpio.LOW),
            (failed_i2c.name, "deinit"),
            ("gpio", "cleanup", (15, 29)),
        ),
    )
    _assert_closed(adapter)

    adapter.open()
    batch = adapter.read_all()

    assert len(batch.observations) == 2
    assert batch.failures == ()
    assert events.count(("i2c", "create", 7)) == 2


def test_open_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, events, _, _, _ = _open_adapter(monkeypatch)
    first_open_events = list(events)

    adapter.open()

    assert events == first_open_events


@pytest.mark.parametrize("conflicting_address", [0x29, 0x30, 0x31])
def test_open_rejects_each_reserved_address_collision(
    monkeypatch: pytest.MonkeyPatch,
    conflicting_address: int,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    i2c = FakeI2C(
        "i2c-1",
        events,
        scan_results=[{conflicting_address}],
    )
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[i2c],
        sensors=[],
    )
    adapter = _make_adapter()

    with pytest.raises(
        SensorArrayInitializationError,
        match=f"0x{conflicting_address:02X}",
    ):
        adapter.open()

    assert not any(event[0] == "sensor" for event in events)
    assert (i2c.name, "deinit") in events
    assert ("gpio", "cleanup", (15, 29)) in events
    assert events.count(
        ("gpio", "setup", 15, gpio.OUT, gpio.LOW)
    ) == 2
    assert events.count(
        ("gpio", "setup", 29, gpio.OUT, gpio.LOW)
    ) == 2
    _assert_closed(adapter)


def test_open_reports_all_reserved_address_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    i2c = FakeI2C(
        "i2c-1",
        events,
        scan_results=[{0x29, 0x30, 0x31}],
    )
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[i2c],
        sensors=[],
    )

    with pytest.raises(SensorArrayInitializationError) as exc_info:
        _make_adapter().open()

    message = str(exc_info.value)
    assert "0x29" in message
    assert "0x30" in message
    assert "0x31" in message


@pytest.mark.parametrize(
    "final_addresses,expected_fragments",
    [
        ({0x31}, ("0x30",)),
        ({0x30}, ("0x31",)),
        (set(), ("0x30", "0x31")),
        ({0x29, 0x30, 0x31}, ("0x29",)),
        ({0x29, 0x30}, ("0x29", "0x31")),
    ],
    ids=[
        "missing-0x30",
        "missing-0x31",
        "missing-both",
        "default-remains",
        "missing-and-default-remains",
    ],
)
def test_open_rejects_invalid_final_address_state(
    monkeypatch: pytest.MonkeyPatch,
    final_addresses: set[int],
    expected_fragments: tuple[str, ...],
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    i2c = FakeI2C(
        "i2c-1",
        events,
        scan_results=[set(), final_addresses],
    )
    sensors = [
        FakeSensor("sensor-1", events, reading=420),
        FakeSensor("sensor-2", events, reading=840),
    ]
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[i2c],
        sensors=sensors,
    )
    adapter = _make_adapter()

    with pytest.raises(SensorArrayInitializationError) as exc_info:
        adapter.open()

    message = str(exc_info.value)
    for fragment in expected_fragments:
        assert fragment in message
    assert (i2c.name, "deinit") in events
    assert ("gpio", "cleanup", (15, 29)) in events
    _assert_closed(adapter)


def test_scan_unlocks_i2c_when_scan_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    i2c = FakeI2C(
        "i2c-1",
        events,
        scan_results=[RuntimeError("scan failed")],
    )
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[i2c],
        sensors=[],
    )

    with pytest.raises(SensorArrayInitializationError):
        _make_adapter().open()

    _assert_occurs_in_order(
        events,
        (
            (i2c.name, "try_lock"),
            (i2c.name, "scan"),
            (i2c.name, "unlock"),
            (i2c.name, "deinit"),
        ),
    )


def test_scan_lock_timeout_does_not_unlock_unacquired_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    i2c = FakeI2C(
        "i2c-1",
        events,
        scan_results=[],
        lock_results=[False, False],
        default_lock_result=False,
    )
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[i2c],
        sensors=[],
    )
    monotonic_values = iter([0.0, 0.5, 1.0])
    monkeypatch.setattr(
        adapter_module,
        "_monotonic",
        lambda: next(monotonic_values),
    )
    adapter = _make_adapter()

    with pytest.raises(SensorArrayInitializationError) as exc_info:
        adapter.open()

    assert "lock" in str(exc_info.value)
    assert (i2c.name, "unlock") not in events
    assert (i2c.name, "deinit") in events
    assert ("gpio", "cleanup", (15, 29)) in events
    _assert_closed(adapter)


def test_failed_open_can_be_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    failed_i2c = FakeI2C(
        "i2c-failed",
        events,
        scan_results=[{0x29}],
    )
    successful_i2c = FakeI2C(
        "i2c-success",
        events,
        scan_results=[set(), {0x30, 0x31}],
    )
    sensors = [
        FakeSensor("sensor-1", events, reading=420),
        FakeSensor("sensor-2", events, reading=840),
    ]
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[failed_i2c, successful_i2c],
        sensors=sensors,
    )
    adapter = _make_adapter()

    with pytest.raises(SensorArrayInitializationError):
        adapter.open()
    _assert_closed(adapter)

    adapter.open()
    batch = adapter.read_all()

    assert len(batch.observations) == 2
    assert events.count(("i2c", "create", 7)) == 2
    assert (
        "sensor",
        "create",
        "sensor-1",
        successful_i2c,
        0x29,
        1.0,
    ) in events


def test_dependency_loading_failure_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__

    def fail_jetson_gpio_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "Jetson.GPIO":
            raise ImportError(
                "simulated missing Jetson.GPIO",
                name="Jetson.GPIO",
            )
        return original_import(
            name,
            globals,
            locals,
            fromlist,
            level,
        )

    monkeypatch.setattr(
        builtins,
        "__import__",
        fail_jetson_gpio_import,
    )
    adapter = _make_adapter()

    with pytest.raises(SensorArrayInitializationError) as exc_info:
        adapter.open()

    assert isinstance(exc_info.value.__cause__, ImportError)
    assert exc_info.value.__cause__.name == "Jetson.GPIO"
    assert "Jetson.GPIO" in str(exc_info.value)
    _assert_closed(adapter)
    adapter.close()


# [Reading]


def test_read_all_before_open_raises() -> None:
    with pytest.raises(SensorArrayStateError):
        _make_adapter().read_all()


def test_read_all_returns_observations_in_sensor_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, events, _, _, _ = _open_adapter(
        monkeypatch,
        readings=(420, 840),
    )

    batch = adapter.read_all()

    assert tuple(
        observation.sensor_id for observation in batch.observations
    ) == (
        "tof_disabled_zone",
        "tof_ev_charging_zone",
    )
    assert tuple(
        observation.value for observation in batch.observations
    ) == (420.0, 840.0)
    assert all(
        observation.sensor_type == TOF_SENSOR_TYPE
        for observation in batch.observations
    )
    assert all(
        observation.quality is None
        for observation in batch.observations
    )
    assert all(
        observation.observed_at == NOW
        for observation in batch.observations
    )
    assert batch.failures == ()
    _assert_occurs_in_order(
        events,
        (
            ("sensor-1", "range"),
            ("sensor-2", "range"),
        ),
    )


@pytest.mark.parametrize(
    "readings,failed_sensor_id,observed_sensor_id",
    [
        (
            (OSError("first failed"), 840),
            "tof_disabled_zone",
            "tof_ev_charging_zone",
        ),
        (
            (420, OSError("second failed")),
            "tof_ev_charging_zone",
            "tof_disabled_zone",
        ),
    ],
)
def test_read_all_preserves_partial_success(
    monkeypatch: pytest.MonkeyPatch,
    readings: tuple[Any, Any],
    failed_sensor_id: str,
    observed_sensor_id: str,
) -> None:
    adapter, events, _, _, _ = _open_adapter(
        monkeypatch,
        readings=readings,
    )

    batch = adapter.read_all()

    assert tuple(
        observation.sensor_id for observation in batch.observations
    ) == (observed_sensor_id,)
    assert tuple(
        failure.sensor_id for failure in batch.failures
    ) == (failed_sensor_id,)
    assert (
        batch.failures[0].reason
        is SensorReadFailureReason.COMMUNICATION_ERROR
    )
    assert {
        observation.sensor_id for observation in batch.observations
    }.isdisjoint(
        failure.sensor_id for failure in batch.failures
    )
    _assert_occurs_in_order(
        events,
        (
            ("sensor-1", "range"),
            ("sensor-2", "range"),
        ),
    )


def test_read_all_returns_all_sensor_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, _, _, _ = _open_adapter(
        monkeypatch,
        readings=(
            TimeoutError("measurement timeout"),
            RuntimeError("driver failed"),
        ),
    )

    batch = adapter.read_all()

    assert batch.observations == ()
    assert tuple(
        failure.sensor_id for failure in batch.failures
    ) == (
        "tof_disabled_zone",
        "tof_ev_charging_zone",
    )
    assert tuple(
        failure.reason for failure in batch.failures
    ) == (
        SensorReadFailureReason.TIMEOUT,
        SensorReadFailureReason.COMMUNICATION_ERROR,
    )


def test_read_all_does_not_hide_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, events, _, _, _ = _open_adapter(
        monkeypatch,
        readings=(KeyError("programming error"), 840),
    )

    with pytest.raises(KeyError, match="programming error"):
        adapter.read_all()

    assert ("sensor-1", "range") in events
    assert ("sensor-2", "range") not in events


@pytest.mark.parametrize(
    "distance_mm",
    [20, 20.0, 2000, 420],
)
def test_read_all_accepts_nominal_distance_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    distance_mm: Any,
) -> None:
    adapter, _, _, _, _ = _open_adapter(
        monkeypatch,
        readings=(distance_mm, 840),
    )

    batch = adapter.read_all()
    disabled_observation = next(
        observation
        for observation in batch.observations
        if observation.sensor_id == "tof_disabled_zone"
    )

    assert disabled_observation.value == float(distance_mm)


@pytest.mark.parametrize(
    "distance_mm",
    [0, 19, 19.999, 2000.001, 2001],
)
def test_read_all_classifies_out_of_range_distances(
    monkeypatch: pytest.MonkeyPatch,
    distance_mm: Any,
) -> None:
    adapter, _, _, _, _ = _open_adapter(
        monkeypatch,
        readings=(distance_mm, 840),
    )

    batch = adapter.read_all()

    assert len(batch.failures) == 1
    assert batch.failures[0].sensor_id == "tof_disabled_zone"
    assert (
        batch.failures[0].reason
        is SensorReadFailureReason.OUT_OF_RANGE
    )
    assert tuple(
        observation.sensor_id for observation in batch.observations
    ) == ("tof_ev_charging_zone",)


@pytest.mark.parametrize(
    "distance_mm",
    [
        True,
        "420",
        -1,
        float("nan"),
        float("inf"),
        float("-inf"),
        10**10000,
    ],
    ids=[
        "bool",
        "string",
        "negative",
        "nan",
        "positive-infinity",
        "negative-infinity",
        "float-overflow",
    ],
)
def test_read_all_classifies_invalid_distances(
    monkeypatch: pytest.MonkeyPatch,
    distance_mm: Any,
) -> None:
    adapter, _, _, _, _ = _open_adapter(
        monkeypatch,
        readings=(distance_mm, 840),
    )

    batch = adapter.read_all()

    assert len(batch.failures) == 1
    assert batch.failures[0].sensor_id == "tof_disabled_zone"
    assert (
        batch.failures[0].reason
        is SensorReadFailureReason.INVALID_READING
    )
    assert tuple(
        observation.sensor_id for observation in batch.observations
    ) == ("tof_ev_charging_zone",)


# [Cleanup]


def test_close_releases_resources_in_order_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, events, gpio, i2c, _ = _open_adapter(monkeypatch)
    events.clear()

    adapter.close()

    _assert_occurs_in_order(
        events,
        (
            ("gpio", "setup", 15, gpio.OUT, gpio.LOW),
            ("gpio", "setup", 29, gpio.OUT, gpio.LOW),
            (i2c.name, "deinit"),
            ("gpio", "cleanup", (15, 29)),
        ),
    )
    _assert_closed(adapter)
    first_close_events = list(events)

    adapter.close()

    assert events == first_close_events


def test_close_before_open_is_safe() -> None:
    adapter = _make_adapter()

    adapter.close()
    adapter.close()


def test_close_collects_errors_and_continues_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(
        events,
        setup_errors={
            (15, FakeGPIO.OUT): [
                None,
                RuntimeError("pin 15 cleanup failed"),
            ],
        },
        cleanup_error=RuntimeError("gpio cleanup failed"),
    )
    i2c = FakeI2C(
        "i2c-1",
        events,
        scan_results=[set(), {0x30, 0x31}],
        deinit_error=RuntimeError("i2c deinit failed"),
    )
    adapter, _, _, _, _ = _open_adapter(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2c=i2c,
    )
    events.clear()

    with pytest.raises(SensorArrayCleanupError) as exc_info:
        adapter.close()

    message = str(exc_info.value)
    assert "pin 15 cleanup failed" in message
    assert "i2c deinit failed" in message
    assert "gpio cleanup failed" in message
    _assert_occurs_in_order(
        events,
        (
            ("gpio", "setup", 15, gpio.OUT, gpio.LOW),
            ("gpio", "setup", 29, gpio.OUT, gpio.LOW),
            (i2c.name, "deinit"),
            ("gpio", "cleanup", (15, 29)),
        ),
    )
    _assert_closed(adapter)


def test_initialization_failure_preserves_cleanup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(
        events,
        setup_errors={
            (29, FakeGPIO.OUT): [
                None,
                RuntimeError("pin 29 cleanup failed"),
            ],
        },
        cleanup_error=RuntimeError("gpio cleanup failed"),
    )
    i2c = FakeI2C(
        "i2c-1",
        events,
        scan_results=[set()],
        deinit_error=RuntimeError("i2c deinit failed"),
    )
    initialization_error = RuntimeError(
        "sensor initialization failed"
    )
    sensors = [
        FakeSensor(
            "sensor-1",
            events,
            reading=420,
            set_address_error=initialization_error,
        ),
        FakeSensor("sensor-2", events, reading=840),
    ]
    _install_hardware(
        monkeypatch,
        events=events,
        gpio=gpio,
        i2cs=[i2c],
        sensors=sensors,
    )
    adapter = _make_adapter()

    with pytest.raises(SensorArrayInitializationError) as exc_info:
        adapter.open()

    assert exc_info.value.__cause__ is initialization_error
    message = str(exc_info.value)
    assert "sensor initialization failed" in message
    assert "pin 29 cleanup failed" in message
    assert "i2c deinit failed" in message
    assert "gpio cleanup failed" in message
    _assert_occurs_in_order(
        events,
        (
            ("sensor-1", "set_address", 0x30),
            ("gpio", "setup", 15, gpio.OUT, gpio.LOW),
            ("gpio", "setup", 29, gpio.OUT, gpio.LOW),
            (i2c.name, "deinit"),
            ("gpio", "cleanup", (15, 29)),
        ),
    )
    _assert_closed(adapter)

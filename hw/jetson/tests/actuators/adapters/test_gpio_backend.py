"""실제 Jetson.GPIO 없이 GPIO backend 경계와 생명주기를 검증한다."""

from __future__ import annotations

import builtins
import importlib
from collections.abc import Callable
from typing import Any

import pytest

from src.actuators.adapters import gpio_backend as backend_module


# [Fakes]


class FakeGPIO:
    BOARD = "BOARD"
    OUT = "OUT"
    LOW = "LOW"
    HIGH = "HIGH"

    def __init__(
        self,
        events: list[tuple[Any, ...]],
        *,
        setmode_error: Exception | None = None,
        setup_error: Exception | None = None,
        output_error: Exception | None = None,
        cleanup_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.setmode_error = setmode_error
        self.setup_error = setup_error
        self.output_error = output_error
        self.cleanup_error = cleanup_error

    def setmode(self, mode: str) -> None:
        self.events.append(("gpio", "setmode", mode))
        if self.setmode_error is not None:
            raise self.setmode_error

    def setup(
        self,
        pin: int,
        direction: str,
        *,
        initial: str,
    ) -> None:
        self.events.append(
            ("gpio", "setup", pin, direction, initial)
        )
        if self.setup_error is not None:
            raise self.setup_error

    def output(self, pin: int, level: str) -> None:
        self.events.append(("gpio", "output", pin, level))
        if self.output_error is not None:
            raise self.output_error

    def cleanup(self, pins: tuple[int, ...]) -> None:
        self.events.append(("gpio", "cleanup", pins))
        if self.cleanup_error is not None:
            raise self.cleanup_error


# [Helpers]


def _install_gpio(
    monkeypatch: pytest.MonkeyPatch,
    *,
    events: list[tuple[Any, ...]],
    gpio: FakeGPIO,
) -> None:
    def load_gpio() -> FakeGPIO:
        events.append(("loader",))
        return gpio

    monkeypatch.setattr(
        backend_module,
        "_load_jetson_gpio",
        load_gpio,
    )


def _open_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gpio: FakeGPIO | None = None,
) -> tuple[
    backend_module.JetsonGpioBackend,
    FakeGPIO,
    list[tuple[Any, ...]],
]:
    if gpio is None:
        events: list[tuple[Any, ...]] = []
        active_gpio = FakeGPIO(events)
    else:
        active_gpio = gpio
        events = active_gpio.events

    _install_gpio(
        monkeypatch,
        events=events,
        gpio=active_gpio,
    )
    backend = backend_module.JetsonGpioBackend()
    backend.open()
    return backend, active_gpio, events


# [Import and constructor]


def test_module_import_does_not_import_jetson_gpio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__
    attempted_imports: list[str] = []

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "Jetson.GPIO":
            attempted_imports.append(name)
            raise AssertionError(
                "module import 중 Jetson.GPIO에 접근했습니다."
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
        guarded_import,
    )

    importlib.reload(backend_module)

    assert attempted_imports == []


def test_constructor_does_not_load_gpio_or_cause_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    _install_gpio(
        monkeypatch,
        events=events,
        gpio=gpio,
    )

    backend_module.JetsonGpioBackend()

    assert events == []


# [Open]


def test_open_loads_gpio_and_sets_board_mode_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    _install_gpio(
        monkeypatch,
        events=events,
        gpio=gpio,
    )
    backend = backend_module.JetsonGpioBackend()

    backend.open()
    backend.open()

    assert events == [
        ("loader",),
        ("gpio", "setmode", gpio.BOARD),
    ]


def test_open_converts_import_error_and_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__
    import_error = ImportError(
        "simulated missing Jetson.GPIO",
        name="Jetson.GPIO",
    )

    def fail_jetson_gpio_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "Jetson.GPIO":
            raise import_error
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
    backend = backend_module.JetsonGpioBackend()

    with pytest.raises(
        backend_module.GpioBackendInitializationError
    ) as exc_info:
        backend.open()

    assert exc_info.value.__cause__ is import_error
    assert "Jetson.GPIO" in str(exc_info.value)
    with pytest.raises(backend_module.GpioBackendStateError):
        backend.write(31, high=True)


def test_open_can_retry_after_dependency_loading_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    gpio = FakeGPIO(events)
    import_error = ImportError(
        "simulated missing Jetson.GPIO",
        name="Jetson.GPIO",
    )
    load_attempts = 0

    def load_gpio() -> FakeGPIO:
        nonlocal load_attempts

        load_attempts += 1
        events.append(("loader",))
        if load_attempts == 1:
            try:
                raise import_error
            except ImportError as exc:
                raise backend_module.GpioBackendInitializationError(
                    "Jetson GPIO 의존성을 import할 수 없습니다: "
                    "Jetson.GPIO"
                ) from exc

        return gpio

    monkeypatch.setattr(
        backend_module,
        "_load_jetson_gpio",
        load_gpio,
    )
    backend = backend_module.JetsonGpioBackend()

    with pytest.raises(
        backend_module.GpioBackendInitializationError
    ) as exc_info:
        backend.open()

    assert exc_info.value.__cause__ is import_error
    with pytest.raises(backend_module.GpioBackendStateError):
        backend.write(31, high=True)

    backend.open()

    assert events == [
        ("loader",),
        ("loader",),
        ("gpio", "setmode", gpio.BOARD),
    ]


def test_setmode_failure_preserves_cause_and_open_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    setmode_error = RuntimeError("setmode failed")
    gpio = FakeGPIO(
        events,
        setmode_error=setmode_error,
    )
    _install_gpio(
        monkeypatch,
        events=events,
        gpio=gpio,
    )
    backend = backend_module.JetsonGpioBackend()

    with pytest.raises(
        backend_module.GpioBackendInitializationError
    ) as exc_info:
        backend.open()

    assert exc_info.value.__cause__ is setmode_error
    with pytest.raises(backend_module.GpioBackendStateError):
        backend.write(31, high=True)

    gpio.setmode_error = None
    backend.open()

    assert events.count(("loader",)) == 2
    assert events.count(
        ("gpio", "setmode", gpio.BOARD)
    ) == 2


# [State]


@pytest.mark.parametrize(
    "operation",
    [
        pytest.param(
            lambda backend: backend.setup_output(
                31,
                initial_high=False,
            ),
            id="setup-output",
        ),
        pytest.param(
            lambda backend: backend.write(31, high=True),
            id="write",
        ),
        pytest.param(
            lambda backend: backend.cleanup((31,)),
            id="cleanup",
        ),
        pytest.param(
            lambda backend: backend.cleanup(()),
            id="empty-cleanup",
        ),
    ],
)
def test_operations_before_open_raise_state_error(
    operation: Callable[
        [backend_module.JetsonGpioBackend],
        None,
    ],
) -> None:
    backend = backend_module.JetsonGpioBackend()

    with pytest.raises(backend_module.GpioBackendStateError):
        operation(backend)


# [Setup]


@pytest.mark.parametrize(
    "initial_high,expected_level",
    [
        (False, FakeGPIO.LOW),
        (True, FakeGPIO.HIGH),
    ],
)
def test_setup_output_converts_bool_to_gpio_level(
    monkeypatch: pytest.MonkeyPatch,
    initial_high: bool,
    expected_level: str,
) -> None:
    backend, gpio, events = _open_backend(monkeypatch)
    events.clear()

    backend.setup_output(
        31,
        initial_high=initial_high,
    )

    assert events == [
        (
            "gpio",
            "setup",
            31,
            gpio.OUT,
            expected_level,
        )
    ]


@pytest.mark.parametrize(
    "pin",
    [True, 0, -1, 41, 31.0, "31", None],
    ids=[
        "bool",
        "zero",
        "negative",
        "over-40",
        "float",
        "string",
        "none",
    ],
)
def test_setup_output_rejects_invalid_pin_without_gpio_call(
    monkeypatch: pytest.MonkeyPatch,
    pin: Any,
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    with pytest.raises(ValueError):
        backend.setup_output(
            pin,
            initial_high=False,
        )

    assert events == []


@pytest.mark.parametrize(
    "initial_high",
    [0, 1, None, "true"],
    ids=["zero", "one", "none", "string"],
)
def test_setup_output_rejects_non_bool_initial_value(
    monkeypatch: pytest.MonkeyPatch,
    initial_high: Any,
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    with pytest.raises(ValueError):
        backend.setup_output(
            31,
            initial_high=initial_high,
        )

    assert events == []


def test_setup_output_propagates_original_gpio_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    setup_error = RuntimeError("setup failed")
    gpio = FakeGPIO(
        events,
        setup_error=setup_error,
    )
    backend, gpio, events = _open_backend(
        monkeypatch,
        gpio=gpio,
    )
    events.clear()

    with pytest.raises(RuntimeError) as exc_info:
        backend.setup_output(
            31,
            initial_high=False,
        )

    assert exc_info.value is setup_error
    assert events == [
        (
            "gpio",
            "setup",
            31,
            gpio.OUT,
            gpio.LOW,
        )
    ]


# [Write]


@pytest.mark.parametrize(
    "high,expected_level",
    [
        (True, FakeGPIO.HIGH),
        (False, FakeGPIO.LOW),
    ],
)
def test_write_converts_bool_to_gpio_level(
    monkeypatch: pytest.MonkeyPatch,
    high: bool,
    expected_level: str,
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    backend.write(33, high=high)

    assert events == [
        ("gpio", "output", 33, expected_level)
    ]


@pytest.mark.parametrize(
    "pin",
    [True, 0, -1, 41, 33.0, "33", None],
    ids=[
        "bool",
        "zero",
        "negative",
        "over-40",
        "float",
        "string",
        "none",
    ],
)
def test_write_rejects_invalid_pin_without_gpio_call(
    monkeypatch: pytest.MonkeyPatch,
    pin: Any,
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    with pytest.raises(ValueError):
        backend.write(pin, high=True)

    assert events == []


@pytest.mark.parametrize(
    "high",
    [0, 1, None, "true"],
    ids=["zero", "one", "none", "string"],
)
def test_write_rejects_non_bool_value_without_gpio_call(
    monkeypatch: pytest.MonkeyPatch,
    high: Any,
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    with pytest.raises(ValueError):
        backend.write(33, high=high)

    assert events == []


def test_write_propagates_original_gpio_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    output_error = RuntimeError("output failed")
    gpio = FakeGPIO(
        events,
        output_error=output_error,
    )
    backend, gpio, events = _open_backend(
        monkeypatch,
        gpio=gpio,
    )
    events.clear()

    with pytest.raises(RuntimeError) as exc_info:
        backend.write(33, high=True)

    assert exc_info.value is output_error
    assert events == [
        ("gpio", "output", 33, gpio.HIGH)
    ]


# [Cleanup]


def test_cleanup_releases_only_requested_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    backend.cleanup((31, 33))

    assert events == [
        ("gpio", "cleanup", (31, 33))
    ]


def test_cleanup_with_empty_tuple_does_not_call_gpio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    backend.cleanup(())

    assert events == []


@pytest.mark.parametrize(
    "pins",
    [
        (31, True),
        (31, 0),
        (31, 41),
        (31, 33.0),
        (31, "33"),
        (31, None),
    ],
    ids=[
        "bool",
        "zero",
        "over-40",
        "float",
        "string",
        "none",
    ],
)
def test_cleanup_rejects_invalid_pin_without_gpio_call(
    monkeypatch: pytest.MonkeyPatch,
    pins: tuple[Any, ...],
) -> None:
    backend, _, events = _open_backend(monkeypatch)
    events.clear()

    with pytest.raises(ValueError):
        backend.cleanup(pins)

    assert events == []


def test_cleanup_propagates_original_gpio_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    cleanup_error = RuntimeError("cleanup failed")
    gpio = FakeGPIO(
        events,
        cleanup_error=cleanup_error,
    )
    backend, _, events = _open_backend(
        monkeypatch,
        gpio=gpio,
    )
    events.clear()

    with pytest.raises(RuntimeError) as exc_info:
        backend.cleanup((31, 33))

    assert exc_info.value is cleanup_error
    assert events == [
        ("gpio", "cleanup", (31, 33))
    ]

"""실제 GPIO와 wall-clock sleep 없이 경고 LED adapter를 검증한다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import (
    Condition,
    Event,
    Thread,
    current_thread,
)
from typing import Any

import pytest

from src.actuators.adapters import jetson_gpio_led as led_module
from src.actuators.adapters.jetson_gpio_led import (
    BLINK_ACTION,
    DEFAULT_BLINK_OFF_SECONDS,
    DEFAULT_BLINK_ON_SECONDS,
    DISABLED_ZONE_WARNING_LED_ID,
    DISABLED_ZONE_WARNING_LED_PIN,
    EV_ZONE_WARNING_LED_ID,
    EV_ZONE_WARNING_LED_PIN,
    InvalidActuatorProjectionError,
    JetsonGpioLedAdapter,
    LedAdapterCleanupError,
    LedAdapterInitializationError,
    LedAdapterRuntimeError,
    LedAdapterStateError,
    _decode_projection,
)
from src.actuators.models import ActuatorCommand


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)


class FakeBackend:
    def __init__(
        self,
        *,
        open_error: Exception | None = None,
        setup_errors: dict[int, Exception] | None = None,
        write_errors: dict[
            tuple[int, bool],
            list[Exception | None],
        ]
        | None = None,
        cleanup_error: Exception | None = None,
        block_open: bool = False,
        block_write: bool = False,
    ) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.open_error = open_error
        self.setup_errors = dict(setup_errors or {})
        self.write_errors = {
            key: list(errors)
            for key, errors in (write_errors or {}).items()
        }
        self.cleanup_error = cleanup_error

        self.block_open = block_open
        self.open_entered = Event()
        self.open_release = Event()

        self.block_write = block_write
        self.write_entered = Event()
        self.write_release = Event()

        self.cleaned = Event()

    def open(self) -> None:
        self.events.append(
            ("backend", "open", current_thread().name)
        )
        self.open_entered.set()
        if self.block_open:
            if not self.open_release.wait(timeout=1.0):
                raise RuntimeError("open test gate timed out")
        if self.open_error is not None:
            raise self.open_error

    def setup_output(
        self,
        pin: int,
        *,
        initial_high: bool,
    ) -> None:
        self.events.append(
            (
                "backend",
                "setup",
                pin,
                initial_high,
                current_thread().name,
            )
        )
        error = self.setup_errors.get(pin)
        if error is not None:
            raise error

    def write(
        self,
        pin: int,
        *,
        high: bool,
    ) -> None:
        self.events.append(
            (
                "backend",
                "write",
                pin,
                high,
                current_thread().name,
            )
        )

        self.write_entered.set()
        if self.block_write:
            if not self.write_release.wait(timeout=1.0):
                raise RuntimeError("write test gate timed out")

        errors = self.write_errors.get((pin, high))
        if errors:
            error = errors.pop(0)
            if error is not None:
                raise error

    def cleanup(
        self,
        pins: tuple[int, ...],
    ) -> None:
        self.events.append(
            (
                "backend",
                "cleanup",
                pins,
                current_thread().name,
            )
        )
        self.cleaned.set()
        if self.cleanup_error is not None:
            raise self.cleanup_error


class FalseyFakeBackend(FakeBackend):
    def __bool__(self) -> bool:
        return False


class FalseyFakeScheduler:
    def __init__(self, delegate: FakeScheduler) -> None:
        self._delegate = delegate

    def __bool__(self) -> bool:
        return False

    def monotonic(self) -> float:
        return self._delegate.monotonic()

    def wait(
        self,
        condition: Condition,
        timeout: float | None,
    ) -> None:
        self._delegate.wait(condition, timeout)


class FakeScheduler:
    def __init__(self) -> None:
        self._control = Condition()
        self._now = 0.0
        self._worker_condition: Condition | None = None
        self.wait_timeouts: list[float | None] = []

    def monotonic(self) -> float:
        with self._control:
            return self._now

    def wait(
        self,
        condition: Condition,
        timeout: float | None,
    ) -> None:
        with self._control:
            self._worker_condition = condition
            self.wait_timeouts.append(timeout)
            self._control.notify_all()

        condition.wait()

    @property
    def wait_count(self) -> int:
        with self._control:
            return len(self.wait_timeouts)

    def wait_until_worker_waits(
        self,
        count: int,
    ) -> None:
        with self._control:
            completed = self._control.wait_for(
                lambda: len(self.wait_timeouts) >= count,
                timeout=1.0,
            )
        assert completed, (
            f"worker wait 횟수가 {count}에 도달하지 않았습니다."
        )

    def advance(self, seconds: float) -> None:
        with self._control:
            self._now += seconds
            condition = self._worker_condition

        assert condition is not None
        with condition:
            condition.notify_all()


def _command(
    actuator_id: str,
    *,
    action: str = BLINK_ACTION,
    reason: str = "TEST",
    requested_at: datetime = NOW,
) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id=actuator_id,
        action=action,
        reason=reason,
        requested_at=requested_at,
    )


def _event_details(
    events: list[tuple[Any, ...]],
) -> list[tuple[Any, ...]]:
    return [event[:-1] for event in events]


def _worker_names(
    events: list[tuple[Any, ...]],
) -> set[str]:
    return {event[-1] for event in events}


def _open_adapter(
    *,
    backend: FakeBackend | None = None,
    scheduler: FakeScheduler | None = None,
    blink_on_seconds: float = 0.3,
    blink_off_seconds: float = 0.3,
) -> tuple[
    JetsonGpioLedAdapter,
    FakeBackend,
    FakeScheduler,
]:
    active_backend = (
        FakeBackend()
        if backend is None
        else backend
    )
    active_scheduler = (
        FakeScheduler()
        if scheduler is None
        else scheduler
    )
    adapter = JetsonGpioLedAdapter(
        backend=active_backend,
        scheduler=active_scheduler,
        blink_on_seconds=blink_on_seconds,
        blink_off_seconds=blink_off_seconds,
    )
    adapter.open()
    active_scheduler.wait_until_worker_waits(1)
    return adapter, active_backend, active_scheduler


def _apply_and_settle(
    adapter: JetsonGpioLedAdapter,
    scheduler: FakeScheduler,
    commands: tuple[ActuatorCommand, ...],
) -> None:
    expected_wait_count = scheduler.wait_count + 1
    adapter.apply_projection(commands)
    scheduler.wait_until_worker_waits(expected_wait_count)


def _advance_and_settle(
    scheduler: FakeScheduler,
    seconds: float,
) -> None:
    expected_wait_count = scheduler.wait_count + 1
    scheduler.advance(seconds)
    scheduler.wait_until_worker_waits(expected_wait_count)


def _capture_error(
    operation: Callable[[], None],
    errors: list[Exception],
) -> None:
    try:
        operation()
    except Exception as error:
        errors.append(error)


# [Constructor and decoder]


def test_constructor_has_no_gpio_or_thread_side_effect() -> None:
    backend = FakeBackend()

    adapter = JetsonGpioLedAdapter(backend=backend)

    assert backend.events == []
    assert adapter.is_running is False


def test_constructor_uses_provisional_default_timing() -> None:
    adapter = JetsonGpioLedAdapter(backend=FakeBackend())

    assert adapter._blink_on_seconds == DEFAULT_BLINK_ON_SECONDS
    assert adapter._blink_off_seconds == DEFAULT_BLINK_OFF_SECONDS


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("blink_on_seconds", True),
        ("blink_on_seconds", 0),
        ("blink_on_seconds", -0.1),
        ("blink_on_seconds", float("nan")),
        ("blink_on_seconds", float("inf")),
        ("blink_on_seconds", "0.3"),
        ("blink_off_seconds", False),
        ("blink_off_seconds", 0),
        ("blink_off_seconds", float("-inf")),
        ("blink_off_seconds", None),
    ],
)
def test_constructor_rejects_invalid_blink_timing(
    field_name: str,
    value: Any,
) -> None:
    arguments = {field_name: value}

    with pytest.raises(ValueError):
        JetsonGpioLedAdapter(
            backend=FakeBackend(),
            **arguments,
        )


@pytest.mark.parametrize(
    "scheduler",
    [
        object(),
        type(
            "MissingWaitScheduler",
            (),
            {"monotonic": lambda self: 0.0},
        )(),
        type(
            "MissingMonotonicScheduler",
            (),
            {"wait": lambda self, condition, timeout: None},
        )(),
    ],
)
def test_constructor_rejects_invalid_scheduler(
    scheduler: Any,
) -> None:
    backend = FakeBackend()

    with pytest.raises(ValueError, match="scheduler"):
        JetsonGpioLedAdapter(
            backend=backend,
            scheduler=scheduler,
        )

    assert backend.events == []


def test_constructor_preserves_falsey_backend_injection() -> None:
    backend = FalseyFakeBackend()
    scheduler = FakeScheduler()

    adapter, active_backend, _ = _open_adapter(
        backend=backend,
        scheduler=scheduler,
    )
    adapter.close()

    assert active_backend is backend
    assert backend.events[0][1] == "open"


def test_constructor_preserves_falsey_scheduler_injection() -> None:
    delegate = FakeScheduler()
    scheduler = FalseyFakeScheduler(delegate)
    adapter = JetsonGpioLedAdapter(
        backend=FakeBackend(),
        scheduler=scheduler,
    )

    adapter.open()
    try:
        delegate.wait_until_worker_waits(1)

        assert delegate.wait_count >= 1
        assert delegate.wait_timeouts[-1] is None
    finally:
        adapter.close()


@pytest.mark.parametrize(
    "commands,expected",
    [
        ((), frozenset()),
        (
            (_command(DISABLED_ZONE_WARNING_LED_ID),),
            frozenset({DISABLED_ZONE_WARNING_LED_ID}),
        ),
        (
            (_command(EV_ZONE_WARNING_LED_ID),),
            frozenset({EV_ZONE_WARNING_LED_ID}),
        ),
        (
            (
                _command(DISABLED_ZONE_WARNING_LED_ID),
                _command(EV_ZONE_WARNING_LED_ID),
            ),
            frozenset(
                {
                    DISABLED_ZONE_WARNING_LED_ID,
                    EV_ZONE_WARNING_LED_ID,
                }
            ),
        ),
        (
            (
                _command(EV_ZONE_WARNING_LED_ID),
                _command(DISABLED_ZONE_WARNING_LED_ID),
            ),
            frozenset(
                {
                    DISABLED_ZONE_WARNING_LED_ID,
                    EV_ZONE_WARNING_LED_ID,
                }
            ),
        ),
    ],
)
def test_decode_projection_returns_target_ids(
    commands: tuple[ActuatorCommand, ...],
    expected: frozenset[str],
) -> None:
    assert _decode_projection(commands) == expected


@pytest.mark.parametrize(
    "commands",
    [
        (_command("speaker"),),
        (_command("unknown"),),
        (_command(DISABLED_ZONE_WARNING_LED_ID, action="ON"),),
        (_command(DISABLED_ZONE_WARNING_LED_ID, action="blink"),),
        (
            _command(DISABLED_ZONE_WARNING_LED_ID),
            _command(DISABLED_ZONE_WARNING_LED_ID),
        ),
        (object(),),
    ],
    ids=[
        "speaker",
        "unknown-id",
        "unsupported-action",
        "lowercase-action",
        "duplicate-id",
        "non-command",
    ],
)
def test_decode_projection_rejects_invalid_projection(
    commands: tuple[Any, ...],
) -> None:
    with pytest.raises(InvalidActuatorProjectionError):
        _decode_projection(commands)


def test_decode_projection_does_not_return_partial_target() -> None:
    commands = (
        _command(DISABLED_ZONE_WARNING_LED_ID),
        _command("speaker"),
    )

    with pytest.raises(InvalidActuatorProjectionError):
        _decode_projection(commands)


# [Open and ownership]


def test_open_initializes_backend_and_pins_in_worker_order() -> None:
    adapter, backend, _ = _open_adapter()

    assert _event_details(backend.events) == [
        ("backend", "open"),
        (
            "backend",
            "setup",
            DISABLED_ZONE_WARNING_LED_PIN,
            False,
        ),
        (
            "backend",
            "setup",
            EV_ZONE_WARNING_LED_PIN,
            False,
        ),
    ]
    assert _worker_names(backend.events) == {
        "jetson-warning-led"
    }

    adapter.close()


def test_open_waits_for_worker_startup() -> None:
    backend = FakeBackend(block_open=True)
    adapter = JetsonGpioLedAdapter(
        backend=backend,
        scheduler=FakeScheduler(),
    )
    errors: list[Exception] = []

    caller = Thread(
        target=lambda: _capture_error(adapter.open, errors)
    )
    caller.start()

    assert backend.open_entered.wait(timeout=1.0)
    assert caller.is_alive()

    backend.open_release.set()
    caller.join(timeout=1.0)

    assert not caller.is_alive()
    assert errors == []
    adapter.close()


def test_repeated_open_is_noop() -> None:
    adapter, backend, _ = _open_adapter()
    events = list(backend.events)

    adapter.open()

    assert backend.events == events
    adapter.close()


def test_apply_before_open_raises_state_error() -> None:
    adapter = JetsonGpioLedAdapter(backend=FakeBackend())

    with pytest.raises(LedAdapterStateError):
        adapter.apply_projection(())


def test_backend_open_failure_is_reported_without_cleanup() -> None:
    open_error = RuntimeError("open failed")
    backend = FakeBackend(open_error=open_error)
    adapter = JetsonGpioLedAdapter(
        backend=backend,
        scheduler=FakeScheduler(),
    )

    with pytest.raises(
        LedAdapterInitializationError
    ) as exc_info:
        adapter.open()

    assert exc_info.value.primary_error is open_error
    assert _event_details(backend.events) == [
        ("backend", "open")
    ]
    assert adapter.failure is exc_info.value
    assert adapter.is_running is False


@pytest.mark.parametrize(
    "failing_pin,expected_events",
    [
        (
            DISABLED_ZONE_WARNING_LED_PIN,
            [
                ("backend", "open"),
                (
                    "backend",
                    "setup",
                    DISABLED_ZONE_WARNING_LED_PIN,
                    False,
                ),
                (
                    "backend",
                    "cleanup",
                    (DISABLED_ZONE_WARNING_LED_PIN,),
                ),
            ],
        ),
        (
            EV_ZONE_WARNING_LED_PIN,
            [
                ("backend", "open"),
                (
                    "backend",
                    "setup",
                    DISABLED_ZONE_WARNING_LED_PIN,
                    False,
                ),
                (
                    "backend",
                    "setup",
                    EV_ZONE_WARNING_LED_PIN,
                    False,
                ),
                (
                    "backend",
                    "write",
                    DISABLED_ZONE_WARNING_LED_PIN,
                    False,
                ),
                (
                    "backend",
                    "cleanup",
                    (
                        DISABLED_ZONE_WARNING_LED_PIN,
                        EV_ZONE_WARNING_LED_PIN,
                    ),
                ),
            ],
        ),
    ],
)
def test_setup_failure_runs_partial_fail_safe_and_cleanup(
    failing_pin: int,
    expected_events: list[tuple[Any, ...]],
) -> None:
    setup_error = RuntimeError("setup failed")
    backend = FakeBackend(
        setup_errors={failing_pin: setup_error}
    )
    adapter = JetsonGpioLedAdapter(
        backend=backend,
        scheduler=FakeScheduler(),
    )

    with pytest.raises(
        LedAdapterInitializationError
    ) as exc_info:
        adapter.open()

    assert exc_info.value.primary_error is setup_error
    assert _event_details(backend.events) == expected_events
    assert adapter.is_running is False
    assert _worker_names(backend.events) == {
        "jetson-warning-led"
    }


def test_thread_start_failure_preserves_cause_without_gpio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_error = RuntimeError("thread start failed")
    backend = FakeBackend()

    class FailingThread:
        def __init__(self, **_arguments: Any) -> None:
            pass

        def start(self) -> None:
            raise start_error

    monkeypatch.setattr(led_module, "Thread", FailingThread)
    adapter = JetsonGpioLedAdapter(backend=backend)

    with pytest.raises(
        LedAdapterInitializationError
    ) as exc_info:
        adapter.open()

    assert exc_info.value.primary_error is start_error
    assert backend.events == []


# [Projection and blink]


def test_empty_projection_keeps_both_leds_off() -> None:
    adapter, backend, scheduler = _open_adapter()
    initial_waits = scheduler.wait_count

    adapter.apply_projection(())

    assert backend.events[-2][1] == "setup"
    assert backend.events[-1][1] == "setup"
    assert scheduler.wait_count == initial_waits
    adapter.close()


@pytest.mark.parametrize(
    "actuator_id,pin",
    [
        (
            DISABLED_ZONE_WARNING_LED_ID,
            DISABLED_ZONE_WARNING_LED_PIN,
        ),
        (
            EV_ZONE_WARNING_LED_ID,
            EV_ZONE_WARNING_LED_PIN,
        ),
    ],
)
def test_single_led_starts_high_and_blinks(
    actuator_id: str,
    pin: int,
) -> None:
    adapter, backend, scheduler = _open_adapter()

    _apply_and_settle(
        adapter,
        scheduler,
        (_command(actuator_id),),
    )
    assert _event_details(backend.events)[-1] == (
        "backend",
        "write",
        pin,
        True,
    )

    _advance_and_settle(scheduler, 0.3)
    assert _event_details(backend.events)[-1] == (
        "backend",
        "write",
        pin,
        False,
    )

    _advance_and_settle(scheduler, 0.3)
    assert _event_details(backend.events)[-1] == (
        "backend",
        "write",
        pin,
        True,
    )
    adapter.close()


def test_two_leds_start_and_blink_in_same_phase() -> None:
    adapter, backend, scheduler = _open_adapter()
    commands = (
        _command(DISABLED_ZONE_WARNING_LED_ID),
        _command(EV_ZONE_WARNING_LED_ID),
    )

    _apply_and_settle(adapter, scheduler, commands)

    assert _event_details(backend.events)[-2:] == [
        (
            "backend",
            "write",
            DISABLED_ZONE_WARNING_LED_PIN,
            True,
        ),
        (
            "backend",
            "write",
            EV_ZONE_WARNING_LED_PIN,
            True,
        ),
    ]

    _advance_and_settle(scheduler, 0.3)
    assert _event_details(backend.events)[-2:] == [
        (
            "backend",
            "write",
            DISABLED_ZONE_WARNING_LED_PIN,
            False,
        ),
        (
            "backend",
            "write",
            EV_ZONE_WARNING_LED_PIN,
            False,
        ),
    ]
    adapter.close()


def test_same_target_does_not_write_notify_or_change_generation() -> None:
    adapter, backend, scheduler = _open_adapter()
    command = _command(DISABLED_ZONE_WARNING_LED_ID)
    _apply_and_settle(adapter, scheduler, (command,))
    events = list(backend.events)
    waits = scheduler.wait_count
    generation = adapter._projection_generation

    adapter.apply_projection(
        (
            replace(
                command,
                reason="CHANGED",
                requested_at=NOW + timedelta(seconds=1),
            ),
        )
    )

    assert backend.events == events
    assert scheduler.wait_count == waits
    assert adapter._projection_generation == generation
    adapter.close()


def test_command_order_change_is_same_target() -> None:
    adapter, backend, scheduler = _open_adapter()
    disabled = _command(DISABLED_ZONE_WARNING_LED_ID)
    ev = _command(EV_ZONE_WARNING_LED_ID)
    _apply_and_settle(
        adapter,
        scheduler,
        (disabled, ev),
    )
    events = list(backend.events)
    generation = adapter._projection_generation

    adapter.apply_projection((ev, disabled))

    assert backend.events == events
    assert adapter._projection_generation == generation
    adapter.close()


def test_removed_led_is_low_without_resetting_remaining_phase() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (
            _command(DISABLED_ZONE_WARNING_LED_ID),
            _command(EV_ZONE_WARNING_LED_ID),
        ),
    )
    events_before = len(backend.events)

    _apply_and_settle(
        adapter,
        scheduler,
        (_command(EV_ZONE_WARNING_LED_ID),),
    )

    assert _event_details(backend.events[events_before:]) == [
        (
            "backend",
            "write",
            DISABLED_ZONE_WARNING_LED_PIN,
            False,
        )
    ]
    adapter.close()


def test_new_led_joins_current_high_phase_and_keeps_deadline() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_LED_ID),),
    )
    timeout_before = scheduler.wait_timeouts[-1]
    events_before = len(backend.events)

    _apply_and_settle(
        adapter,
        scheduler,
        (
            _command(DISABLED_ZONE_WARNING_LED_ID),
            _command(EV_ZONE_WARNING_LED_ID),
        ),
    )

    assert _event_details(backend.events[events_before:]) == [
        (
            "backend",
            "write",
            EV_ZONE_WARNING_LED_PIN,
            True,
        )
    ]
    assert scheduler.wait_timeouts[-1] == timeout_before
    adapter.close()


def test_new_led_joins_current_low_phase_and_keeps_deadline() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_LED_ID),),
    )
    _advance_and_settle(scheduler, 0.3)
    timeout_before = scheduler.wait_timeouts[-1]
    events_before = len(backend.events)

    _apply_and_settle(
        adapter,
        scheduler,
        (
            _command(DISABLED_ZONE_WARNING_LED_ID),
            _command(EV_ZONE_WARNING_LED_ID),
        ),
    )

    assert _event_details(backend.events[events_before:]) == [
        (
            "backend",
            "write",
            EV_ZONE_WARNING_LED_PIN,
            False,
        )
    ]
    assert scheduler.wait_timeouts[-1] == timeout_before
    adapter.close()


def test_empty_projection_turns_active_leds_low_and_waits_without_timer() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (
            _command(DISABLED_ZONE_WARNING_LED_ID),
            _command(EV_ZONE_WARNING_LED_ID),
        ),
    )
    events_before = len(backend.events)

    _apply_and_settle(adapter, scheduler, ())

    assert _event_details(backend.events[events_before:]) == [
        (
            "backend",
            "write",
            DISABLED_ZONE_WARNING_LED_PIN,
            False,
        ),
        (
            "backend",
            "write",
            EV_ZONE_WARNING_LED_PIN,
            False,
        ),
    ]
    assert scheduler.wait_timeouts[-1] is None
    adapter.close()


def test_late_wake_produces_one_tick_without_catch_up_burst() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_LED_ID),),
    )
    events_before = len(backend.events)

    _advance_and_settle(scheduler, 3.0)

    writes = [
        event
        for event in backend.events[events_before:]
        if event[1] == "write"
    ]
    assert len(writes) == 1
    assert writes[0][3] is False
    adapter.close()


def test_apply_returns_while_worker_gpio_write_is_blocked() -> None:
    backend = FakeBackend(block_write=True)
    adapter, _, scheduler = _open_adapter(backend=backend)

    adapter.apply_projection(
        (_command(DISABLED_ZONE_WARNING_LED_ID),)
    )
    assert backend.write_entered.wait(timeout=1.0)

    adapter.apply_projection(
        (_command(EV_ZONE_WARNING_LED_ID),)
    )

    expected_wait_count = scheduler.wait_count + 1
    backend.write_release.set()
    scheduler.wait_until_worker_waits(expected_wait_count)
    adapter.close()


def test_invalid_projection_preserves_existing_target() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_LED_ID),),
    )
    events = list(backend.events)
    generation = adapter._projection_generation

    with pytest.raises(InvalidActuatorProjectionError):
        adapter.apply_projection(
            (
                _command(EV_ZONE_WARNING_LED_ID),
                _command("speaker"),
            )
        )

    assert backend.events == events
    assert adapter._projection_generation == generation
    adapter.close()


# [Runtime failure and close]


def test_runtime_high_failure_runs_fail_safe_and_exposes_failure() -> None:
    write_error = RuntimeError("HIGH failed")
    backend = FakeBackend(
        write_errors={
            (
                DISABLED_ZONE_WARNING_LED_PIN,
                True,
            ): [write_error],
        }
    )
    adapter, _, _ = _open_adapter(backend=backend)

    adapter.apply_projection(
        (_command(DISABLED_ZONE_WARNING_LED_ID),)
    )
    assert backend.cleaned.wait(timeout=1.0)
    adapter.close()

    failure = adapter.failure
    assert isinstance(failure, LedAdapterRuntimeError)
    assert failure.primary_error is write_error
    assert adapter.is_running is False

    details = _event_details(backend.events)
    assert details[-3:] == [
        (
            "backend",
            "write",
            DISABLED_ZONE_WARNING_LED_PIN,
            False,
        ),
        (
            "backend",
            "write",
            EV_ZONE_WARNING_LED_PIN,
            False,
        ),
        (
            "backend",
            "cleanup",
            (
                DISABLED_ZONE_WARNING_LED_PIN,
                EV_ZONE_WARNING_LED_PIN,
            ),
        ),
    ]
    with pytest.raises(LedAdapterStateError):
        adapter.apply_projection(())


def test_runtime_low_failure_preserves_first_error() -> None:
    low_error = RuntimeError("LOW tick failed")
    backend = FakeBackend(
        write_errors={
            (
                DISABLED_ZONE_WARNING_LED_PIN,
                False,
            ): [low_error, None],
        }
    )
    adapter, _, scheduler = _open_adapter(backend=backend)
    _apply_and_settle(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_LED_ID),),
    )

    scheduler.advance(0.3)
    assert backend.cleaned.wait(timeout=1.0)
    adapter.close()

    failure = adapter.failure
    assert isinstance(failure, LedAdapterRuntimeError)
    assert failure.primary_error is low_error
    assert adapter.is_running is False


def test_fail_safe_continues_after_low_and_cleanup_failures() -> None:
    high_error = RuntimeError("HIGH failed")
    low_error = RuntimeError("fail-safe LOW failed")
    cleanup_error = RuntimeError("cleanup failed")
    backend = FakeBackend(
        write_errors={
            (
                DISABLED_ZONE_WARNING_LED_PIN,
                True,
            ): [high_error],
            (
                DISABLED_ZONE_WARNING_LED_PIN,
                False,
            ): [low_error],
        },
        cleanup_error=cleanup_error,
    )
    adapter, _, _ = _open_adapter(backend=backend)

    adapter.apply_projection(
        (_command(DISABLED_ZONE_WARNING_LED_ID),)
    )
    assert backend.cleaned.wait(timeout=1.0)

    with pytest.raises(LedAdapterCleanupError):
        adapter.close()

    failure = adapter.failure
    assert isinstance(failure, LedAdapterRuntimeError)
    assert failure.primary_error is high_error
    assert failure.cleanup_errors == (
        low_error,
        cleanup_error,
    )
    assert adapter.is_running is False

    details = _event_details(backend.events)
    assert (
        "backend",
        "write",
        EV_ZONE_WARNING_LED_PIN,
        False,
    ) in details
    cleanup_index = next(
        index
        for index, event in enumerate(details)
        if event[1] == "cleanup"
    )
    assert not any(
        event[1] == "write"
        for event in details[cleanup_index + 1:]
    )


def test_close_before_open_is_noop() -> None:
    backend = FakeBackend()
    adapter = JetsonGpioLedAdapter(backend=backend)

    adapter.close()

    assert backend.events == []


def test_close_lowers_both_pins_then_cleans_up_and_joins() -> None:
    adapter, backend, _ = _open_adapter()
    adapter.close()

    assert _event_details(backend.events)[-3:] == [
        (
            "backend",
            "write",
            DISABLED_ZONE_WARNING_LED_PIN,
            False,
        ),
        (
            "backend",
            "write",
            EV_ZONE_WARNING_LED_PIN,
            False,
        ),
        (
            "backend",
            "cleanup",
            (
                DISABLED_ZONE_WARNING_LED_PIN,
                EV_ZONE_WARNING_LED_PIN,
            ),
        ),
    ]
    assert adapter.is_running is False
    assert adapter.failure is None

    events = list(backend.events)
    adapter.close()
    assert backend.events == events

    with pytest.raises(LedAdapterStateError):
        adapter.apply_projection(())


def test_close_after_low_phase_does_not_start_new_high_cycle() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_LED_ID),),
    )
    _advance_and_settle(scheduler, 0.3)
    high_writes_before = sum(
        event[1] == "write" and event[3] is True
        for event in backend.events
    )

    adapter.close()

    high_writes_after = sum(
        event[1] == "write" and event[3] is True
        for event in backend.events
    )
    assert high_writes_after == high_writes_before


def test_cleanup_failure_is_stored_and_repeated_close_does_not_retry_gpio() -> None:
    cleanup_failure = RuntimeError("cleanup failed")
    backend = FakeBackend(cleanup_error=cleanup_failure)
    adapter, _, _ = _open_adapter(backend=backend)

    with pytest.raises(
        LedAdapterCleanupError
    ) as first_exc:
        adapter.close()

    events = list(backend.events)
    with pytest.raises(
        LedAdapterCleanupError
    ) as second_exc:
        adapter.close()

    assert second_exc.value is first_exc.value
    assert second_exc.value.primary_error is cleanup_failure
    assert backend.events == events


def test_projection_update_and_close_race_has_no_gpio_after_cleanup() -> None:
    adapter, backend, _ = _open_adapter()
    start = Event()
    errors: list[Exception] = []

    def apply() -> None:
        start.wait(timeout=1.0)
        try:
            adapter.apply_projection(
                (_command(DISABLED_ZONE_WARNING_LED_ID),)
            )
        except LedAdapterStateError as error:
            errors.append(error)

    apply_thread = Thread(target=apply)
    apply_thread.start()
    start.set()
    adapter.close()
    apply_thread.join(timeout=1.0)

    assert not apply_thread.is_alive()
    assert all(
        isinstance(error, LedAdapterStateError)
        for error in errors
    )

    details = _event_details(backend.events)
    cleanup_index = next(
        index
        for index, event in enumerate(details)
        if event[1] == "cleanup"
    )
    assert not any(
        event[1] == "write"
        for event in details[cleanup_index + 1:]
    )


def test_all_backend_calls_have_single_worker_owner() -> None:
    adapter, backend, scheduler = _open_adapter()
    _apply_and_settle(
        adapter,
        scheduler,
        (
            _command(DISABLED_ZONE_WARNING_LED_ID),
            _command(EV_ZONE_WARNING_LED_ID),
        ),
    )
    _advance_and_settle(scheduler, 0.3)
    adapter.close()

    assert _worker_names(backend.events) == {
        "jetson-warning-led"
    }
    assert current_thread().name not in _worker_names(
        backend.events
    )

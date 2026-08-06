"""실제 GPIO와 wall-clock sleep 없이 경고 LED 진단 스크립트를 검증한다."""

from __future__ import annotations

import builtins
import importlib
from collections.abc import Callable
from typing import Any

import pytest

from scripts import check_warning_led as script_module
from src.actuators.adapters import jetson_gpio_led as led_module
from src.actuators.adapters.jetson_gpio_led import (
    BLINK_ACTION,
    DEFAULT_BLINK_OFF_SECONDS,
    DEFAULT_BLINK_ON_SECONDS,
    DISABLED_ZONE_WARNING_LED_ID,
    EV_ZONE_WARNING_LED_ID,
    JetsonGpioLedAdapter,
)
from src.actuators.models import ActuatorCommand


class FakeAdapter:
    def __init__(
        self,
        *,
        events: list[tuple[Any, ...]] | None = None,
        open_error: Exception | None = None,
        apply_error_at: int | None = None,
        apply_error: Exception | None = None,
        close_error: Exception | None = None,
        close_failure: Exception | None = None,
    ) -> None:
        self.events = [] if events is None else events
        self.projections: list[tuple[ActuatorCommand, ...]] = []
        self.open_error = open_error
        self.apply_error_at = apply_error_at
        self.apply_error = apply_error
        self.close_error = close_error
        self.close_failure = close_failure
        self.failure_value: Exception | None = None
        self.apply_count = 0

    @property
    def failure(self) -> Exception | None:
        return self.failure_value

    def open(self) -> None:
        self.events.append(("open",))
        if self.open_error is not None:
            self.failure_value = self.open_error
            raise self.open_error

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        self.apply_count += 1
        self.events.append(("apply", commands))
        self.projections.append(commands)
        if self.apply_count == self.apply_error_at:
            error = self.apply_error or RuntimeError("apply failed")
            raise error

    def close(self) -> None:
        self.events.append(("close",))
        if self.close_failure is not None:
            self.failure_value = self.close_failure
        if self.close_error is not None:
            raise self.close_error


class FakeSleep:
    def __init__(
        self,
        *,
        events: list[tuple[Any, ...]] | None = None,
        error_at: int | None = None,
        error: BaseException | None = None,
        callbacks: dict[int, Callable[[], None]] | None = None,
    ) -> None:
        self.events = [] if events is None else events
        self.calls: list[float] = []
        self.error_at = error_at
        self.error = error
        self.callbacks = dict(callbacks or {})

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.events.append(("sleep", seconds))
        call_number = len(self.calls)

        callback = self.callbacks.get(call_number)
        if callback is not None:
            callback()

        if call_number == self.error_at:
            error = self.error or RuntimeError("sleep failed")
            raise error


def _parse(*arguments: str) -> Any:
    return script_module.build_parser().parse_args(list(arguments))


# [CLI]


def test_parser_uses_manual_diagnostic_defaults() -> None:
    args = _parse()

    assert args.stage_seconds == 3.0
    assert args.off_seconds == 1.0
    assert args.blink_on_seconds == DEFAULT_BLINK_ON_SECONDS
    assert args.blink_off_seconds == DEFAULT_BLINK_OFF_SECONDS


def test_parser_accepts_custom_values() -> None:
    args = _parse(
        "--stage-seconds",
        "4.0",
        "--off-seconds",
        "0",
        "--blink-on-seconds",
        "0.2",
        "--blink-off-seconds",
        "0.4",
    )

    assert args.stage_seconds == 4.0
    assert args.off_seconds == 0.0
    assert args.blink_on_seconds == 0.2
    assert args.blink_off_seconds == 0.4


@pytest.mark.parametrize(
    "option,value",
    [
        ("--stage-seconds", "0"),
        ("--stage-seconds", "-1"),
        ("--stage-seconds", "nan"),
        ("--stage-seconds", "inf"),
        ("--stage-seconds", "-inf"),
        ("--blink-on-seconds", "0"),
        ("--blink-on-seconds", "-0.1"),
        ("--blink-on-seconds", "nan"),
        ("--blink-on-seconds", "inf"),
        ("--blink-off-seconds", "0"),
        ("--blink-off-seconds", "-0.1"),
        ("--blink-off-seconds", "nan"),
        ("--blink-off-seconds", "inf"),
    ],
)
def test_parser_rejects_non_positive_or_non_finite_values(
    option: str,
    value: str,
) -> None:
    with pytest.raises(SystemExit):
        _parse(option, value)


@pytest.mark.parametrize(
    "value",
    ["-1", "nan", "inf", "-inf"],
)
def test_parser_rejects_invalid_off_seconds(value: str) -> None:
    with pytest.raises(SystemExit):
        _parse("--off-seconds", value)


def test_parser_accepts_zero_off_seconds() -> None:
    assert _parse("--off-seconds", "0").off_seconds == 0.0


# [Construction]


def test_module_import_does_not_construct_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_construction(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError(
            "module import 중 adapter가 생성되었습니다."
        )

    try:
        with monkeypatch.context() as context:
            context.setattr(
                led_module,
                "JetsonGpioLedAdapter",
                reject_construction,
            )
            importlib.reload(script_module)
    finally:
        # 검출 대상 회귀로 첫 reload가 실패해도 이후 테스트 상태를 복구한다.
        importlib.reload(script_module)


def test_build_adapter_does_not_import_gpio_or_open_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_import = builtins.__import__
    attempted_gpio_imports: list[str] = []

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "Jetson.GPIO":
            attempted_gpio_imports.append(name)
            raise AssertionError(
                "build_adapter 중 Jetson.GPIO를 import했습니다."
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

    adapter = script_module.build_adapter(
        blink_on_seconds=0.2,
        blink_off_seconds=0.4,
    )

    assert isinstance(adapter, JetsonGpioLedAdapter)
    assert adapter.is_running is False
    assert attempted_gpio_imports == []


def test_build_adapter_passes_blink_timing_by_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_arguments: dict[str, float] = {}
    fake_adapter = FakeAdapter()

    def build_fake_adapter(
        **arguments: float,
    ) -> FakeAdapter:
        captured_arguments.update(arguments)
        return fake_adapter

    monkeypatch.setattr(
        script_module,
        "JetsonGpioLedAdapter",
        build_fake_adapter,
    )

    adapter = script_module.build_adapter(
        blink_on_seconds=0.2,
        blink_off_seconds=0.4,
    )

    assert adapter is fake_adapter
    assert captured_arguments == {
        "blink_on_seconds": 0.2,
        "blink_off_seconds": 0.4,
    }


# [Successful run]


def test_run_applies_full_projections_in_diagnostic_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[tuple[Any, ...]] = []
    adapter = FakeAdapter(events=events)
    sleep = FakeSleep(events=events)

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=3.0,
        off_seconds=1.0,
        sleep=sleep,
    )

    assert exit_code == 0
    assert adapter.events[0] == ("open",)
    assert adapter.events[-1] == ("close",)
    assert [
        tuple(command.actuator_id for command in projection)
        for projection in adapter.projections
    ] == [
        (DISABLED_ZONE_WARNING_LED_ID,),
        (),
        (EV_ZONE_WARNING_LED_ID,),
        (),
        (
            DISABLED_ZONE_WARNING_LED_ID,
            EV_ZONE_WARNING_LED_ID,
        ),
        (),
    ]
    assert sleep.calls == [3.0, 1.0, 3.0, 1.0, 3.0]
    assert events == [
        ("open",),
        ("apply", adapter.projections[0]),
        ("sleep", 3.0),
        ("apply", adapter.projections[1]),
        ("sleep", 1.0),
        ("apply", adapter.projections[2]),
        ("sleep", 3.0),
        ("apply", adapter.projections[3]),
        ("sleep", 1.0),
        ("apply", adapter.projections[4]),
        ("sleep", 3.0),
        ("apply", adapter.projections[5]),
        ("close",),
    ]

    commands = tuple(
        command
        for projection in adapter.projections
        for command in projection
    )
    assert all(command.action == BLINK_ACTION for command in commands)
    assert all(
        command.reason == script_module.DIAGNOSTIC_REASON
        for command in commands
    )
    assert all(
        command.requested_at.tzinfo is not None
        and command.requested_at.utcoffset() is not None
        for command in commands
    )

    captured = capsys.readouterr()
    assert "초기화 성공" in captured.out
    assert "진단 및 GPIO 정리 완료" in captured.out
    assert captured.err == ""


def test_run_skips_zero_off_sleep_and_has_no_final_off_sleep() -> None:
    adapter = FakeAdapter()
    sleep = FakeSleep()

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=2.0,
        off_seconds=0.0,
        sleep=sleep,
    )

    assert exit_code == 0
    assert sleep.calls == [2.0, 2.0, 2.0]
    assert adapter.projections[-1] == ()


# [Failures]


def test_open_failure_still_attempts_close(
    capsys: pytest.CaptureFixture[str],
) -> None:
    open_error = RuntimeError("open failed")
    adapter = FakeAdapter(open_error=open_error)

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    assert adapter.events == [("open",), ("close",)]
    assert "open failed" in capsys.readouterr().err


@pytest.mark.parametrize("apply_error_at", [1, 3, 6])
def test_projection_failure_stops_remaining_stages_and_closes(
    apply_error_at: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    apply_error = RuntimeError("projection failed")
    adapter = FakeAdapter(
        apply_error_at=apply_error_at,
        apply_error=apply_error,
    )

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    assert adapter.apply_count == apply_error_at
    assert adapter.events[-1] == ("close",)
    assert "projection failed" in capsys.readouterr().err


def test_keyboard_interrupt_during_sleep_closes_adapter(
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = FakeAdapter()
    sleep = FakeSleep(
        error_at=1,
        error=KeyboardInterrupt(),
    )

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=1.0,
        off_seconds=0.0,
        sleep=sleep,
    )

    assert exit_code == 1
    assert adapter.events[-1] == ("close",)
    assert "사용자에 의해 중단" in capsys.readouterr().err


def test_background_failure_after_stage_is_reported_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = FakeAdapter()
    background_error = RuntimeError("background write failed")
    sleep = FakeSleep(
        callbacks={
            1: lambda: setattr(
                adapter,
                "failure_value",
                background_error,
            )
        }
    )

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=1.0,
        off_seconds=0.0,
        sleep=sleep,
    )

    assert exit_code == 1
    assert adapter.events[-1] == ("close",)
    stderr = capsys.readouterr().err
    assert stderr.count("background write failed") == 1


def test_background_failure_discovered_after_close_is_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    background_error = RuntimeError("late background failure")
    adapter = FakeAdapter(close_failure=background_error)

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    assert "late background failure" in capsys.readouterr().err


def test_close_failure_returns_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    close_error = RuntimeError("cleanup failed")
    adapter = FakeAdapter(close_error=close_error)

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    assert "cleanup failed" in capsys.readouterr().err


def test_execution_and_close_failures_are_both_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    execution_error = RuntimeError("projection failed")
    close_error = RuntimeError("cleanup failed")
    adapter = FakeAdapter(
        apply_error_at=1,
        apply_error=execution_error,
        close_error=close_error,
    )

    exit_code = script_module.run(
        adapter=adapter,
        stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "projection failed" in stderr
    assert "cleanup failed" in stderr

"""실제 audio 장치와 wall-clock sleep 없이 speaker 진단 스크립트를 검증한다."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from scripts import check_warning_speaker as script_module
from src.actuators.adapters import audio_backend as audio_backend_module
from src.actuators.adapters import jetson_usb_speaker as speaker_module
from src.actuators.adapters.jetson_usb_speaker import (
    DISABLED_ZONE_WARNING_SPEAKER_ID,
    EV_ZONE_WARNING_SPEAKER_ID,
    PLAY_ACTION,
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
        failure_read_error: Exception | None = None,
    ) -> None:
        self.events = [] if events is None else events
        self.projections: list[tuple[ActuatorCommand, ...]] = []
        self.open_error = open_error
        self.apply_error_at = apply_error_at
        self.apply_error = apply_error
        self.close_error = close_error
        self.close_failure = close_failure
        self.failure_read_error = failure_read_error
        self.failure_value: Exception | None = None
        self.apply_count = 0

    @property
    def failure(self) -> Exception | None:
        if self.failure_read_error is not None:
            raise self.failure_read_error
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

    assert args.device == "plughw:CARD=Device,DEV=0"
    assert args.disabled_wav == Path(
        "/home/e202/assets/audio/disabled_zone_warning.wav"
    )
    assert args.ev_wav == Path(
        "/home/e202/assets/audio/ev_zone_warning.wav"
    )
    assert args.single_stage_seconds == 5.0
    assert args.round_robin_stage_seconds == 10.0
    assert args.off_seconds == 1.0


def test_parser_accepts_custom_values() -> None:
    args = _parse(
        "--device",
        "plughw:CARD=Test,DEV=1",
        "--disabled-wav",
        "/tmp/disabled.wav",
        "--ev-wav",
        "/tmp/ev.wav",
        "--single-stage-seconds",
        "2.0",
        "--round-robin-stage-seconds",
        "3.0",
        "--off-seconds",
        "0",
    )

    assert args.device == "plughw:CARD=Test,DEV=1"
    assert args.disabled_wav == Path("/tmp/disabled.wav")
    assert args.ev_wav == Path("/tmp/ev.wav")
    assert args.single_stage_seconds == 2.0
    assert args.round_robin_stage_seconds == 3.0
    assert args.off_seconds == 0.0


@pytest.mark.parametrize("value", ["", " ", "\t"])
def test_parser_rejects_blank_device(value: str) -> None:
    with pytest.raises(SystemExit):
        _parse("--device", value)


def test_parser_strips_device_whitespace() -> None:
    args = _parse(
        "--device",
        "  plughw:CARD=Device,DEV=0  ",
    )

    assert args.device == "plughw:CARD=Device,DEV=0"


@pytest.mark.parametrize(
    "option,value",
    [
        ("--single-stage-seconds", "0"),
        ("--single-stage-seconds", "-1"),
        ("--single-stage-seconds", "nan"),
        ("--single-stage-seconds", "inf"),
        ("--single-stage-seconds", "-inf"),
        ("--round-robin-stage-seconds", "0"),
        ("--round-robin-stage-seconds", "-1"),
        ("--round-robin-stage-seconds", "nan"),
        ("--round-robin-stage-seconds", "inf"),
        ("--round-robin-stage-seconds", "-inf"),
    ],
)
def test_parser_rejects_invalid_positive_times(
    option: str,
    value: str,
) -> None:
    with pytest.raises(SystemExit):
        _parse(option, value)


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "-inf"])
def test_parser_rejects_invalid_off_seconds(value: str) -> None:
    with pytest.raises(SystemExit):
        _parse("--off-seconds", value)


def test_parser_accepts_zero_off_seconds() -> None:
    assert _parse("--off-seconds", "0").off_seconds == 0.0


# [Construction]


def test_module_import_does_not_construct_backend_or_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_construction(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("module import 중 audio 객체가 생성됐습니다.")

    try:
        with monkeypatch.context() as context:
            context.setattr(
                audio_backend_module,
                "AplayAudioBackend",
                reject_construction,
            )
            context.setattr(
                speaker_module,
                "JetsonUsbSpeakerAdapter",
                reject_construction,
            )
            importlib.reload(script_module)
    finally:
        importlib.reload(script_module)


def test_build_adapter_wires_backend_and_wav_paths_without_opening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    fake_backend = object()
    fake_adapter = FakeAdapter()

    def build_fake_backend(**arguments: Any) -> object:
        events.append(("backend_init", arguments))
        return fake_backend

    def build_fake_adapter(**arguments: Any) -> FakeAdapter:
        events.append(("adapter_init", arguments))
        return fake_adapter

    monkeypatch.setattr(
        script_module,
        "AplayAudioBackend",
        build_fake_backend,
    )
    monkeypatch.setattr(
        script_module,
        "JetsonUsbSpeakerAdapter",
        build_fake_adapter,
    )

    adapter = script_module.build_adapter(
        device="plughw:CARD=Test,DEV=2",
        disabled_wav_path=Path("disabled.wav"),
        ev_wav_path=Path("ev.wav"),
    )

    assert adapter is fake_adapter
    assert events == [
        (
            "backend_init",
            {"device": "plughw:CARD=Test,DEV=2"},
        ),
        (
            "adapter_init",
            {
                "backend": fake_backend,
                "disabled_zone_warning_wav_path": Path("disabled.wav"),
                "ev_zone_warning_wav_path": Path("ev.wav"),
            },
        ),
    ]
    assert fake_adapter.events == []


# [Successful run]


def test_run_applies_full_projections_and_sleep_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events: list[tuple[Any, ...]] = []
    adapter = FakeAdapter(events=events)
    sleep = FakeSleep(events=events)

    exit_code = script_module.run(
        adapter=adapter,
        single_stage_seconds=5.0,
        round_robin_stage_seconds=10.0,
        off_seconds=1.0,
        sleep=sleep,
    )

    assert exit_code == 0
    assert [
        tuple(command.actuator_id for command in projection)
        for projection in adapter.projections
    ] == [
        (DISABLED_ZONE_WARNING_SPEAKER_ID,),
        (),
        (EV_ZONE_WARNING_SPEAKER_ID,),
        (),
        (
            EV_ZONE_WARNING_SPEAKER_ID,
            DISABLED_ZONE_WARNING_SPEAKER_ID,
        ),
        (),
    ]
    assert sleep.calls == [5.0, 1.0, 5.0, 1.0, 10.0, 1.0]
    assert events == [
        ("open",),
        ("apply", adapter.projections[0]),
        ("sleep", 5.0),
        ("apply", adapter.projections[1]),
        ("sleep", 1.0),
        ("apply", adapter.projections[2]),
        ("sleep", 5.0),
        ("apply", adapter.projections[3]),
        ("sleep", 1.0),
        ("apply", adapter.projections[4]),
        ("sleep", 10.0),
        ("apply", adapter.projections[5]),
        ("sleep", 1.0),
        ("close",),
    ]

    commands = tuple(
        command
        for projection in adapter.projections
        for command in projection
    )
    assert all(command.action == PLAY_ACTION for command in commands)
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
    assert "adapter 초기화 성공" in captured.out
    assert "disabled → ev" in captured.out
    assert "사용자가 직접 확인" in captured.out
    assert captured.err == ""


def test_run_skips_all_off_sleeps_when_off_seconds_is_zero() -> None:
    adapter = FakeAdapter()
    sleep = FakeSleep()

    exit_code = script_module.run(
        adapter=adapter,
        single_stage_seconds=2.0,
        round_robin_stage_seconds=3.0,
        off_seconds=0.0,
        sleep=sleep,
    )

    assert exit_code == 0
    assert sleep.calls == [2.0, 2.0, 3.0]
    assert adapter.projections[-1] == ()
    assert adapter.events[-1] == ("close",)


# [Failures]


def test_open_failure_still_attempts_close(
    capsys: pytest.CaptureFixture[str],
) -> None:
    open_error = RuntimeError("open failed")
    adapter = FakeAdapter(open_error=open_error)

    exit_code = script_module.run(
        adapter=adapter,
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    assert adapter.events == [("open",), ("close",)]
    assert "open failed" in capsys.readouterr().err


@pytest.mark.parametrize("apply_error_at", [1, 2, 3, 4, 5, 6])
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
        single_stage_seconds=1.0,
        round_robin_stage_seconds=2.0,
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
    sleep = FakeSleep(error_at=1, error=KeyboardInterrupt())

    exit_code = script_module.run(
        adapter=adapter,
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
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
    background_error = RuntimeError("background playback failed")
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
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
        off_seconds=0.0,
        sleep=sleep,
    )

    assert exit_code == 1
    assert adapter.events[-1] == ("close",)
    assert capsys.readouterr().err.count(
        "background playback failed"
    ) == 1


def test_background_failure_discovered_after_close_is_reported(
    capsys: pytest.CaptureFixture[str],
) -> None:
    background_error = RuntimeError("late background failure")
    adapter = FakeAdapter(close_failure=background_error)

    exit_code = script_module.run(
        adapter=adapter,
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
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
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
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
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    stderr = capsys.readouterr().err
    assert "projection failed" in stderr
    assert "cleanup failed" in stderr


def test_same_error_object_is_not_reported_twice(
    capsys: pytest.CaptureFixture[str],
) -> None:
    shared_error = RuntimeError("shared failure")
    adapter = FakeAdapter(
        apply_error_at=1,
        apply_error=shared_error,
        close_error=shared_error,
    )

    exit_code = script_module.run(
        adapter=adapter,
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    assert capsys.readouterr().err.count("shared failure") == 1


def test_failure_property_error_after_close_returns_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    read_error = RuntimeError("failure state unreadable")
    adapter = FakeAdapter(failure_read_error=read_error)

    exit_code = script_module.run(
        adapter=adapter,
        single_stage_seconds=1.0,
        round_robin_stage_seconds=1.0,
        off_seconds=0.0,
        sleep=FakeSleep(),
    )

    assert exit_code == 1
    assert adapter.events[-1] == ("close",)
    assert capsys.readouterr().err.count("failure state unreadable") == 1


# [CLI wiring]


def test_main_passes_parsed_arguments_to_build_and_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_adapter = FakeAdapter()
    build_arguments: dict[str, Any] = {}
    run_arguments: dict[str, Any] = {}

    def fake_build_adapter(**arguments: Any) -> FakeAdapter:
        build_arguments.update(arguments)
        return fake_adapter

    def fake_run(**arguments: Any) -> int:
        run_arguments.update(arguments)
        return 17

    monkeypatch.setattr(
        script_module,
        "build_adapter",
        fake_build_adapter,
    )
    monkeypatch.setattr(script_module, "run", fake_run)

    exit_code = script_module.main(
        [
            "--device",
            "  plughw:CARD=Test,DEV=2  ",
            "--disabled-wav",
            "/tmp/disabled.wav",
            "--ev-wav",
            "/tmp/ev.wav",
            "--single-stage-seconds",
            "2.0",
            "--round-robin-stage-seconds",
            "3.0",
            "--off-seconds",
            "0.5",
        ]
    )

    assert exit_code == 17
    assert build_arguments == {
        "device": "plughw:CARD=Test,DEV=2",
        "disabled_wav_path": Path("/tmp/disabled.wav"),
        "ev_wav_path": Path("/tmp/ev.wav"),
    }
    assert run_arguments == {
        "adapter": fake_adapter,
        "single_stage_seconds": 2.0,
        "round_robin_stage_seconds": 3.0,
        "off_seconds": 0.5,
    }


def test_main_returns_failure_when_adapter_construction_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    construction_error = RuntimeError("construction failed")

    def fail_build_adapter(**_arguments: Any) -> Any:
        raise construction_error

    monkeypatch.setattr(
        script_module,
        "build_adapter",
        fail_build_adapter,
    )

    exit_code = script_module.main([])

    assert exit_code == 1
    assert "construction failed" in capsys.readouterr().err


def test_main_returns_failure_when_preparation_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupt_build_adapter(**_arguments: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        script_module,
        "build_adapter",
        interrupt_build_adapter,
    )

    exit_code = script_module.main([])

    assert exit_code == 1
    assert "사용자에 의해 중단" in capsys.readouterr().err

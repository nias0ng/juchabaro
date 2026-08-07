"""실제 USB speaker와 wall-clock sleep 없이 speaker adapter를 검증한다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Condition, Event, Thread, current_thread
from typing import Any

import pytest

from src.actuators.adapters import jetson_usb_speaker as speaker_module
from src.actuators.adapters.jetson_usb_speaker import (
    DEFAULT_PLAYBACK_POLL_INTERVAL_SECONDS,
    DISABLED_ZONE_WARNING_SPEAKER_ID,
    EV_ZONE_WARNING_SPEAKER_ID,
    PLAY_ACTION,
    InvalidSpeakerProjectionError,
    JetsonUsbSpeakerAdapter,
    SpeakerAdapterCleanupError,
    SpeakerAdapterInitializationError,
    SpeakerAdapterRuntimeError,
    SpeakerAdapterStateError,
    _LifecycleState,
    _WorkerContext,
    _decode_projection,
    _next_playback_id,
)
from src.actuators.models import ActuatorCommand


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)


# [Fakes]


def _raise_next(errors: list[Exception | None]) -> None:
    if not errors:
        return
    error = errors.pop(0)
    if error is not None:
        raise error


class FakeAudioBackend:
    def __init__(
        self,
        *,
        open_errors: list[Exception | None] | None = None,
        start_errors: list[Exception | None] | None = None,
        poll_results: list[bool | Exception] | None = None,
        stop_errors: list[Exception | None] | None = None,
        close_errors: list[Exception | None] | None = None,
        block_start: bool = False,
        block_stop: bool = False,
    ) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.open_errors = list(open_errors or [])
        self.start_errors = list(start_errors or [])
        self.poll_results = list(poll_results or [])
        self.stop_errors = list(stop_errors or [])
        self.close_errors = list(close_errors or [])

        self.block_start = block_start
        self.start_entered = Event()
        self.start_release = Event()
        self.block_stop = block_stop
        self.stop_entered = Event()
        self.stop_release = Event()
        self.closed = Event()

    def open(self) -> None:
        self.events.append(("backend", "open", current_thread().name))
        _raise_next(self.open_errors)

    def start(self, wav_path: Path) -> None:
        self.events.append(
            ("backend", "start", wav_path, current_thread().name)
        )
        self.start_entered.set()
        if self.block_start:
            if not self.start_release.wait(timeout=1.0):
                raise RuntimeError("start test gate timed out")
        _raise_next(self.start_errors)

    def poll(self) -> bool:
        self.events.append(("backend", "poll", current_thread().name))
        if not self.poll_results:
            return False
        result = self.poll_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def stop(self) -> None:
        self.events.append(("backend", "stop", current_thread().name))
        self.stop_entered.set()
        if self.block_stop:
            if not self.stop_release.wait(timeout=1.0):
                raise RuntimeError("stop test gate timed out")
        _raise_next(self.stop_errors)

    def close(self) -> None:
        self.events.append(("backend", "close", current_thread().name))
        _raise_next(self.close_errors)
        self.closed.set()


class FakePlaybackScheduler:
    def __init__(self) -> None:
        self._control = Condition()
        self._worker_condition: Condition | None = None
        self.wait_timeouts: list[float | None] = []

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

    def wait_until_worker_waits(self, count: int) -> None:
        with self._control:
            completed = self._control.wait_for(
                lambda: len(self.wait_timeouts) >= count,
                timeout=1.0,
            )
        assert completed, f"worker wait 횟수가 {count}에 도달하지 않았습니다."

    def wake(self) -> None:
        with self._control:
            condition = self._worker_condition
        assert condition is not None
        with condition:
            condition.notify_all()


class FalseyScheduler(FakePlaybackScheduler):
    def __bool__(self) -> bool:
        return False


# [Helpers]


def _command(
    actuator_id: str,
    *,
    action: str = PLAY_ACTION,
    reason: str = "TEST",
    requested_at: datetime = NOW,
) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id=actuator_id,
        action=action,
        reason=reason,
        requested_at=requested_at,
    )


def _wav_paths(tmp_path: Path) -> tuple[Path, Path]:
    disabled = tmp_path / "disabled.wav"
    ev = tmp_path / "ev.wav"
    disabled.write_bytes(b"RIFF-disabled")
    ev.write_bytes(b"RIFF-ev")
    return disabled, ev


def _adapter(
    *,
    backend: FakeAudioBackend,
    tmp_path: Path,
    scheduler: FakePlaybackScheduler | None = None,
    **arguments: Any,
) -> JetsonUsbSpeakerAdapter:
    disabled, ev = _wav_paths(tmp_path)
    return JetsonUsbSpeakerAdapter(
        backend=backend,
        disabled_zone_warning_wav_path=disabled,
        ev_zone_warning_wav_path=ev,
        scheduler=scheduler,
        **arguments,
    )


def _open_adapter(
    *,
    tmp_path: Path,
    backend: FakeAudioBackend | None = None,
    scheduler: FakePlaybackScheduler | None = None,
) -> tuple[
    JetsonUsbSpeakerAdapter,
    FakeAudioBackend,
    FakePlaybackScheduler,
]:
    active_backend = FakeAudioBackend() if backend is None else backend
    active_scheduler = (
        FakePlaybackScheduler() if scheduler is None else scheduler
    )
    adapter = _adapter(
        backend=active_backend,
        tmp_path=tmp_path,
        scheduler=active_scheduler,
    )
    adapter.open()
    active_scheduler.wait_until_worker_waits(1)
    return adapter, active_backend, active_scheduler


def _apply_and_wait(
    adapter: JetsonUsbSpeakerAdapter,
    scheduler: FakePlaybackScheduler,
    commands: tuple[ActuatorCommand, ...],
) -> None:
    expected_waits = scheduler.wait_count + 1
    adapter.apply_projection(commands)
    scheduler.wait_until_worker_waits(expected_waits)


def _poll_and_wait(scheduler: FakePlaybackScheduler) -> None:
    expected_waits = scheduler.wait_count + 1
    scheduler.wake()
    scheduler.wait_until_worker_waits(expected_waits)


def _operation_names(events: list[tuple[Any, ...]]) -> list[str]:
    return [event[1] for event in events]


def _start_paths(events: list[tuple[Any, ...]]) -> list[Path]:
    return [event[2] for event in events if event[1] == "start"]


def _backend_thread_names(events: list[tuple[Any, ...]]) -> set[str]:
    return {event[-1] for event in events}


# [Constructor and decoder]


def test_constructor_has_no_file_backend_or_thread_side_effect(
    tmp_path: Path,
) -> None:
    backend = FakeAudioBackend()
    missing_disabled = tmp_path / "missing-disabled.wav"
    missing_ev = tmp_path / "missing-ev.wav"

    adapter = JetsonUsbSpeakerAdapter(
        backend=backend,
        disabled_zone_warning_wav_path=missing_disabled,
        ev_zone_warning_wav_path=missing_ev,
    )

    assert backend.events == []
    assert adapter.is_running is False
    assert adapter._playback_poll_interval_seconds == (
        DEFAULT_PLAYBACK_POLL_INTERVAL_SECONDS
    )


@pytest.mark.parametrize(
    "value",
    [True, False, 0, -0.1, float("nan"), float("inf"), "0.05", None],
)
def test_constructor_rejects_invalid_poll_interval(
    tmp_path: Path,
    value: Any,
) -> None:
    disabled, ev = _wav_paths(tmp_path)
    with pytest.raises(ValueError):
        JetsonUsbSpeakerAdapter(
            backend=FakeAudioBackend(),
            disabled_zone_warning_wav_path=disabled,
            ev_zone_warning_wav_path=ev,
            playback_poll_interval_seconds=value,
        )


def test_constructor_preserves_falsey_scheduler(tmp_path: Path) -> None:
    scheduler = FalseyScheduler()
    adapter = _adapter(
        backend=FakeAudioBackend(),
        tmp_path=tmp_path,
        scheduler=scheduler,
    )

    assert adapter._scheduler is scheduler


@pytest.mark.parametrize(
    "commands,expected",
    [
        ((), frozenset()),
        (
            (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
            frozenset({DISABLED_ZONE_WARNING_SPEAKER_ID}),
        ),
        (
            (_command(EV_ZONE_WARNING_SPEAKER_ID),),
            frozenset({EV_ZONE_WARNING_SPEAKER_ID}),
        ),
        (
            (
                _command(EV_ZONE_WARNING_SPEAKER_ID),
                _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
            ),
            frozenset(
                {
                    DISABLED_ZONE_WARNING_SPEAKER_ID,
                    EV_ZONE_WARNING_SPEAKER_ID,
                }
            ),
        ),
    ],
)
def test_decode_projection_returns_speaker_target(
    commands: tuple[ActuatorCommand, ...],
    expected: frozenset[str],
) -> None:
    assert _decode_projection(commands) == expected


@pytest.mark.parametrize(
    "commands",
    [
        (_command("unknown"),),
        (_command("disabled_zone_warning_led"),),
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID, action="play"),),
        (
            _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
            _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
        ),
        (object(),),
    ],
)
def test_decode_projection_rejects_invalid_projection(
    commands: tuple[Any, ...],
) -> None:
    with pytest.raises(InvalidSpeakerProjectionError):
        _decode_projection(commands)


@pytest.mark.parametrize(
    "active,last_completed,expected",
    [
        (
            frozenset(
                {
                    DISABLED_ZONE_WARNING_SPEAKER_ID,
                    EV_ZONE_WARNING_SPEAKER_ID,
                }
            ),
            None,
            DISABLED_ZONE_WARNING_SPEAKER_ID,
        ),
        (
            frozenset(
                {
                    DISABLED_ZONE_WARNING_SPEAKER_ID,
                    EV_ZONE_WARNING_SPEAKER_ID,
                }
            ),
            DISABLED_ZONE_WARNING_SPEAKER_ID,
            EV_ZONE_WARNING_SPEAKER_ID,
        ),
        (
            frozenset({DISABLED_ZONE_WARNING_SPEAKER_ID}),
            EV_ZONE_WARNING_SPEAKER_ID,
            DISABLED_ZONE_WARNING_SPEAKER_ID,
        ),
        (
            frozenset({EV_ZONE_WARNING_SPEAKER_ID}),
            None,
            EV_ZONE_WARNING_SPEAKER_ID,
        ),
        (frozenset(), None, None),
    ],
)
def test_next_playback_id_uses_canonical_round_robin(
    active: frozenset[str],
    last_completed: str | None,
    expected: str | None,
) -> None:
    assert _next_playback_id(active, last_completed) == expected


# [Open and startup]


def test_open_validates_wavs_before_backend_and_does_not_start(
    tmp_path: Path,
) -> None:
    adapter, backend, _ = _open_adapter(tmp_path=tmp_path)

    assert _operation_names(backend.events) == ["open"]
    adapter.close()


@pytest.mark.parametrize("invalid_kind", ["missing", "directory", "non-path"])
def test_invalid_wav_fails_before_backend_open(
    tmp_path: Path,
    invalid_kind: str,
) -> None:
    disabled, ev = _wav_paths(tmp_path)
    invalid: Any
    if invalid_kind == "missing":
        invalid = tmp_path / "missing.wav"
    elif invalid_kind == "directory":
        invalid = tmp_path
    else:
        invalid = str(disabled)
    backend = FakeAudioBackend()
    adapter = JetsonUsbSpeakerAdapter(
        backend=backend,
        disabled_zone_warning_wav_path=invalid,
        ev_zone_warning_wav_path=ev,
    )

    with pytest.raises(SpeakerAdapterInitializationError):
        adapter.open()

    assert backend.events == []
    assert isinstance(adapter.failure, SpeakerAdapterInitializationError)


def test_backend_open_failure_closes_and_preserves_error(
    tmp_path: Path,
) -> None:
    open_error = RuntimeError("open failed")
    backend = FakeAudioBackend(open_errors=[open_error])
    adapter = _adapter(backend=backend, tmp_path=tmp_path)

    with pytest.raises(SpeakerAdapterInitializationError) as exc_info:
        adapter.open()

    assert exc_info.value.primary_error is open_error
    assert _operation_names(backend.events) == ["open", "close"]


def test_unexpected_error_after_backend_open_closes_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    publish_error = RuntimeError("publish failed")
    backend = FakeAudioBackend()
    adapter = _adapter(backend=backend, tmp_path=tmp_path)
    monkeypatch.setattr(
        adapter,
        "_publish_open_state",
        lambda _paths: (_ for _ in ()).throw(publish_error),
    )

    with pytest.raises(SpeakerAdapterInitializationError) as exc_info:
        adapter.open()

    assert exc_info.value.primary_error is publish_error
    assert _operation_names(backend.events) == ["open", "close"]


def test_startup_close_failure_is_combined_and_retried(
    tmp_path: Path,
) -> None:
    open_error = RuntimeError("open failed")
    close_error = RuntimeError("close failed")
    backend = FakeAudioBackend(
        open_errors=[open_error],
        close_errors=[close_error, None],
    )
    adapter = _adapter(backend=backend, tmp_path=tmp_path)

    with pytest.raises(SpeakerAdapterInitializationError) as exc_info:
        adapter.open()

    assert exc_info.value.primary_error is open_error
    assert exc_info.value.cleanup_errors == (close_error,)
    assert _operation_names(backend.events) == ["open", "close", "close"]
    with pytest.raises(SpeakerAdapterCleanupError):
        adapter.close()


def test_repeated_open_is_noop_and_apply_before_open_is_rejected(
    tmp_path: Path,
) -> None:
    disabled, ev = _wav_paths(tmp_path)
    adapter = JetsonUsbSpeakerAdapter(
        backend=FakeAudioBackend(),
        disabled_zone_warning_wav_path=disabled,
        ev_zone_warning_wav_path=ev,
        scheduler=FakePlaybackScheduler(),
    )
    with pytest.raises(SpeakerAdapterStateError):
        adapter.apply_projection(())

    adapter.open()
    adapter.open()
    adapter.close()


def test_thread_start_failure_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    start_error = RuntimeError("thread start failed")

    class FailingThread:
        def __init__(self, **_arguments: Any) -> None:
            pass

        def start(self) -> None:
            raise start_error

    monkeypatch.setattr(speaker_module, "Thread", FailingThread)
    adapter = _adapter(backend=FakeAudioBackend(), tmp_path=tmp_path)

    with pytest.raises(SpeakerAdapterInitializationError) as exc_info:
        adapter.open()

    assert exc_info.value.primary_error is start_error


# [Playback and projection]


@pytest.mark.parametrize(
    "speaker_id,path_index",
    [
        (DISABLED_ZONE_WARNING_SPEAKER_ID, 0),
        (EV_ZONE_WARNING_SPEAKER_ID, 1),
    ],
)
def test_single_projection_starts_matching_wav(
    tmp_path: Path,
    speaker_id: str,
    path_index: int,
) -> None:
    paths = _wav_paths(tmp_path)
    adapter, backend, scheduler = _open_adapter(tmp_path=tmp_path)

    _apply_and_wait(adapter, scheduler, (_command(speaker_id),))

    assert _start_paths(backend.events) == [paths[path_index].resolve()]
    adapter.close()


def test_single_id_repeats_and_two_ids_round_robin_without_gap(
    tmp_path: Path,
) -> None:
    disabled, ev = _wav_paths(tmp_path)
    backend = FakeAudioBackend(poll_results=[True, True, True])
    adapter, _, scheduler = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )
    commands = (
        _command(EV_ZONE_WARNING_SPEAKER_ID),
        _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
    )

    _apply_and_wait(adapter, scheduler, commands)
    _poll_and_wait(scheduler)
    _poll_and_wait(scheduler)
    _poll_and_wait(scheduler)

    assert _start_paths(backend.events)[:4] == [
        disabled.resolve(),
        ev.resolve(),
        disabled.resolve(),
        ev.resolve(),
    ]
    names = _operation_names(backend.events)
    for index, name in enumerate(names[:-1]):
        if name == "poll":
            assert names[index + 1] == "start"
    adapter.close()


def test_same_target_and_command_order_change_are_noops(
    tmp_path: Path,
) -> None:
    adapter, backend, scheduler = _open_adapter(tmp_path=tmp_path)
    disabled = _command(DISABLED_ZONE_WARNING_SPEAKER_ID)
    ev = _command(EV_ZONE_WARNING_SPEAKER_ID)
    _apply_and_wait(adapter, scheduler, (disabled, ev))
    events = list(backend.events)
    generation = adapter._projection_generation

    adapter.apply_projection(
        (
            replace(
                ev,
                reason="CHANGED",
                requested_at=NOW + timedelta(seconds=1),
            ),
            disabled,
        )
    )

    assert backend.events == events
    assert adapter._projection_generation == generation
    adapter.close()


def test_invalid_projection_preserves_existing_target(
    tmp_path: Path,
) -> None:
    adapter, backend, scheduler = _open_adapter(tmp_path=tmp_path)
    _apply_and_wait(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
    )
    events = list(backend.events)
    generation = adapter._projection_generation

    with pytest.raises(InvalidSpeakerProjectionError):
        adapter.apply_projection((_command("unknown"),))

    assert backend.events == events
    assert adapter._projection_generation == generation
    adapter.close()


def test_adding_id_keeps_current_then_uses_next_round_robin_id(
    tmp_path: Path,
) -> None:
    disabled, ev = _wav_paths(tmp_path)
    backend = FakeAudioBackend(poll_results=[True])
    adapter, _, scheduler = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )
    _apply_and_wait(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
    )
    events_before = list(backend.events)

    _apply_and_wait(
        adapter,
        scheduler,
        (
            _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
            _command(EV_ZONE_WARNING_SPEAKER_ID),
        ),
    )
    assert "stop" not in _operation_names(
        backend.events[len(events_before) :]
    )

    _poll_and_wait(scheduler)
    assert _start_paths(backend.events)[-2:] == [
        disabled.resolve(),
        ev.resolve(),
    ]
    adapter.close()


def test_removing_current_stops_but_removing_other_keeps_playback(
    tmp_path: Path,
) -> None:
    adapter, backend, scheduler = _open_adapter(tmp_path=tmp_path)
    both = (
        _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
        _command(EV_ZONE_WARNING_SPEAKER_ID),
    )
    _apply_and_wait(adapter, scheduler, both)

    _apply_and_wait(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
    )
    assert _operation_names(backend.events).count("stop") == 0

    _apply_and_wait(adapter, scheduler, both)
    _apply_and_wait(
        adapter,
        scheduler,
        (_command(EV_ZONE_WARNING_SPEAKER_ID),),
    )
    assert _operation_names(backend.events).count("stop") == 1
    adapter.close()


def test_empty_projection_stops_and_transient_empty_resets_cursor(
    tmp_path: Path,
) -> None:
    disabled, ev = _wav_paths(tmp_path)
    backend = FakeAudioBackend(poll_results=[True])
    adapter, _, scheduler = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )
    both = (
        _command(DISABLED_ZONE_WARNING_SPEAKER_ID),
        _command(EV_ZONE_WARNING_SPEAKER_ID),
    )
    _apply_and_wait(adapter, scheduler, both)
    _poll_and_wait(scheduler)
    assert _start_paths(backend.events)[-1] == ev.resolve()

    expected_waits = scheduler.wait_count + 1
    with adapter._condition:
        adapter.apply_projection(())
        adapter.apply_projection(both)
    scheduler.wait_until_worker_waits(expected_waits)

    assert _start_paths(backend.events)[-1] == disabled.resolve()
    assert _operation_names(backend.events).count("stop") == 1
    adapter.close()


def test_one_wake_polls_once_without_catch_up_burst(
    tmp_path: Path,
) -> None:
    backend = FakeAudioBackend(poll_results=[False])
    adapter, _, scheduler = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )
    _apply_and_wait(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
    )

    _poll_and_wait(scheduler)

    assert _operation_names(backend.events).count("poll") == 1
    assert scheduler.wait_timeouts[-1] == 0.05
    adapter.close()


def test_apply_returns_while_backend_start_is_blocked(tmp_path: Path) -> None:
    backend = FakeAudioBackend(block_start=True)
    adapter, _, scheduler = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )
    adapter.apply_projection(
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),)
    )
    assert backend.start_entered.wait(timeout=1.0)

    adapter.apply_projection((_command(EV_ZONE_WARNING_SPEAKER_ID),))

    expected_waits = scheduler.wait_count + 1
    backend.start_release.set()
    scheduler.wait_until_worker_waits(expected_waits)
    adapter.close()


def test_apply_returns_while_backend_stop_is_blocked(tmp_path: Path) -> None:
    backend = FakeAudioBackend(block_stop=True)
    adapter, _, scheduler = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )
    _apply_and_wait(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
    )
    adapter.apply_projection((_command(EV_ZONE_WARNING_SPEAKER_ID),))
    assert backend.stop_entered.wait(timeout=1.0)

    adapter.apply_projection(
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),)
    )

    expected_waits = scheduler.wait_count + 1
    backend.stop_release.set()
    scheduler.wait_until_worker_waits(expected_waits)
    adapter.close()


# [Failure and close]


@pytest.mark.parametrize("failure_step", ["start", "poll"])
def test_runtime_failure_is_exposed_and_apply_is_rejected(
    tmp_path: Path,
    failure_step: str,
) -> None:
    runtime_error = RuntimeError(f"{failure_step} failed")
    backend = FakeAudioBackend(
        start_errors=[runtime_error] if failure_step == "start" else None,
        poll_results=[runtime_error] if failure_step == "poll" else None,
    )
    adapter, _, scheduler = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )
    if failure_step == "poll":
        expected_waits = scheduler.wait_count + 1
        adapter.apply_projection(
            (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),)
        )
        scheduler.wait_until_worker_waits(expected_waits)
        scheduler.wake()
    else:
        adapter.apply_projection(
            (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),)
        )
    assert backend.closed.wait(timeout=1.0)

    adapter.close()

    assert isinstance(adapter.failure, SpeakerAdapterRuntimeError)
    assert adapter.failure.primary_error is runtime_error
    with pytest.raises(SpeakerAdapterStateError):
        adapter.apply_projection(())


def test_close_active_and_idle_call_stop_then_close_on_worker(
    tmp_path: Path,
) -> None:
    for active in (False, True):
        backend = FakeAudioBackend()
        adapter, _, scheduler = _open_adapter(
            tmp_path=tmp_path,
            backend=backend,
        )
        if active:
            _apply_and_wait(
                adapter,
                scheduler,
                (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
            )

        adapter.close()

        assert _operation_names(backend.events)[-2:] == ["stop", "close"]
        assert _backend_thread_names(backend.events) == {
            "jetson-warning-speaker"
        }
        assert adapter.is_running is False


def test_stop_failure_still_closes_and_repeated_close_rethrows(
    tmp_path: Path,
) -> None:
    stop_error = RuntimeError("stop failed")
    backend = FakeAudioBackend(stop_errors=[stop_error])
    adapter, _, _ = _open_adapter(
        tmp_path=tmp_path,
        backend=backend,
    )

    with pytest.raises(SpeakerAdapterCleanupError) as first_exc:
        adapter.close()

    assert first_exc.value.primary_error is stop_error
    assert _operation_names(backend.events)[-2:] == ["stop", "close"]
    events = list(backend.events)
    with pytest.raises(SpeakerAdapterCleanupError) as second_exc:
        adapter.close()
    assert second_exc.value is first_exc.value
    assert backend.events == events


def test_transient_backend_close_failure_is_preserved_after_retry(
    tmp_path: Path,
) -> None:
    close_error = RuntimeError("first close failed")
    backend = FakeAudioBackend(close_errors=[close_error, None])
    adapter = _adapter(backend=backend, tmp_path=tmp_path)
    context = _WorkerContext(backend_open_attempted=True)

    report = adapter._shutdown_backend(
        context=context,
        stop_before_close=False,
    )

    assert context.close_attempts == 2
    assert context.close_completed is True
    assert report.failed_steps == (
        "audio backend close 실패 (attempt 1)",
    )
    assert tuple(issue.error for issue in report.issues) == (close_error,)
    assert _operation_names(backend.events) == ["close", "close"]


def test_transient_close_failure_still_fails_adapter_close(
    tmp_path: Path,
) -> None:
    close_error = RuntimeError("first close failed")
    backend = FakeAudioBackend(close_errors=[close_error, None])
    adapter, _, _ = _open_adapter(
        backend=backend,
        tmp_path=tmp_path,
    )

    with pytest.raises(SpeakerAdapterCleanupError) as first_exc:
        adapter.close()

    assert first_exc.value.primary_error is close_error
    assert first_exc.value.cleanup_errors == (close_error,)
    assert _operation_names(backend.events) == [
        "open",
        "stop",
        "close",
        "close",
    ]
    assert adapter.failure is first_exc.value
    assert adapter._state is _LifecycleState.FAILED

    events = list(backend.events)
    with pytest.raises(SpeakerAdapterCleanupError) as second_exc:
        adapter.close()
    assert second_exc.value is first_exc.value
    assert backend.events == events


def test_repeated_terminal_close_error_is_recorded_once(
    tmp_path: Path,
) -> None:
    close_error = RuntimeError("terminal close failed")
    backend = FakeAudioBackend(close_errors=[close_error, close_error])
    adapter = _adapter(backend=backend, tmp_path=tmp_path)
    context = _WorkerContext(backend_open_attempted=True)

    report = adapter._shutdown_backend(
        context=context,
        stop_before_close=False,
    )

    assert context.close_attempts == 2
    assert context.close_completed is False
    assert report.failed_steps == (
        "audio backend close 실패 (attempt 1)",
        "audio backend close 실패 (attempt 2)",
    )
    assert tuple(issue.error for issue in report.issues) == (close_error,)


def test_same_runtime_error_from_stop_and_close_is_not_duplicated(
    tmp_path: Path,
) -> None:
    primary_error = RuntimeError("same terminal error")
    backend = FakeAudioBackend(
        poll_results=[primary_error],
        stop_errors=[primary_error],
        close_errors=[primary_error, primary_error],
    )
    adapter, _, scheduler = _open_adapter(
        backend=backend,
        tmp_path=tmp_path,
    )
    _apply_and_wait(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
    )
    scheduler.wake()
    worker = adapter._thread
    assert worker is not None
    worker.join(timeout=1.0)
    assert not worker.is_alive()

    with pytest.raises(SpeakerAdapterCleanupError) as exc_info:
        adapter.close()

    assert isinstance(adapter.failure, SpeakerAdapterRuntimeError)
    assert adapter.failure.primary_error is primary_error
    assert adapter.failure.cleanup_errors == ()
    assert exc_info.value.primary_error is primary_error
    assert exc_info.value.cleanup_errors == ()
    assert _operation_names(backend.events)[-3:] == [
        "stop",
        "close",
        "close",
    ]


def test_close_before_open_and_concurrent_closing_are_safe(
    tmp_path: Path,
) -> None:
    backend = FakeAudioBackend(block_stop=True)
    adapter = _adapter(
        backend=backend,
        tmp_path=tmp_path,
        scheduler=FakePlaybackScheduler(),
    )
    adapter.close()
    adapter.open()

    errors: list[Exception] = []

    def close_adapter() -> None:
        try:
            adapter.close()
        except Exception as error:
            errors.append(error)

    first = Thread(target=close_adapter)
    second = Thread(target=close_adapter)
    first.start()
    assert backend.stop_entered.wait(timeout=1.0)
    second.start()
    backend.stop_release.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert _operation_names(backend.events).count("stop") == 1
    assert _operation_names(backend.events).count("close") == 1


def test_all_backend_calls_have_single_worker_owner(tmp_path: Path) -> None:
    backend = FakeAudioBackend(poll_results=[False])
    adapter, _, scheduler = _open_adapter(
        backend=backend,
        tmp_path=tmp_path,
    )
    _apply_and_wait(
        adapter,
        scheduler,
        (_command(DISABLED_ZONE_WARNING_SPEAKER_ID),),
    )
    _poll_and_wait(scheduler)
    adapter.close()

    assert _backend_thread_names(backend.events) == {
        "jetson-warning-speaker"
    }
    assert current_thread().name not in _backend_thread_names(
        backend.events
    )

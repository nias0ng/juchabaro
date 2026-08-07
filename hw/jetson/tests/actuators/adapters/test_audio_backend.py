"""실제 aplay, USB speaker 또는 wall-clock 대기 없이 audio backend를 검증한다."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from src.actuators.adapters import audio_backend as backend_module


DEVICE = "plughw:CARD=Device,DEV=0"
RESOLVED_APLAY = "/usr/bin/aplay"


# [Fakes]


class FakeStderr:
    def __init__(
        self,
        content: bytes = b"",
        *,
        seek_error: Exception | None = None,
        read_error: Exception | None = None,
        close_errors: list[Exception | None] | None = None,
    ) -> None:
        self.content = content
        self.seek_error = seek_error
        self.read_error = read_error
        self.close_errors = list(close_errors or [])
        self.position = 0
        self.closed = False
        self.seek_calls: list[int] = []
        self.read_calls: list[int] = []
        self.close_calls = 0

    def seek(self, offset: int) -> int:
        self.seek_calls.append(offset)
        if self.seek_error is not None:
            raise self.seek_error
        self.position = offset
        return offset

    def read(self, size: int = -1) -> bytes:
        self.read_calls.append(size)
        if self.read_error is not None:
            raise self.read_error
        if size < 0:
            result = self.content[self.position :]
        else:
            result = self.content[self.position : self.position + size]
        self.position += len(result)
        return result

    def close(self) -> None:
        self.close_calls += 1
        if self.close_errors:
            error = self.close_errors.pop(0)
            if error is not None:
                raise error
        self.closed = True


class FakeProcess:
    def __init__(
        self,
        *,
        poll_results: list[int | None],
        wait_results: list[int | Exception] | None = None,
        terminate_errors: list[Exception | None] | None = None,
        kill_errors: list[Exception | None] | None = None,
    ) -> None:
        self.poll_results = list(poll_results)
        self.wait_results = list(wait_results or [])
        self.terminate_errors = list(terminate_errors or [])
        self.kill_errors = list(kill_errors or [])
        self.events: list[tuple[Any, ...]] = []

    def poll(self) -> int | None:
        self.events.append(("poll",))
        if not self.poll_results:
            raise AssertionError("설정되지 않은 poll() 호출입니다.")
        return self.poll_results.pop(0)

    def terminate(self) -> None:
        self.events.append(("terminate",))
        if self.terminate_errors:
            error = self.terminate_errors.pop(0)
            if error is not None:
                raise error

    def kill(self) -> None:
        self.events.append(("kill",))
        if self.kill_errors:
            error = self.kill_errors.pop(0)
            if error is not None:
                raise error

    def wait(self, timeout: float) -> int:
        self.events.append(("wait", timeout))
        if not self.wait_results:
            raise AssertionError("설정되지 않은 wait() 호출입니다.")
        result = self.wait_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class PopenRecorder:
    def __init__(
        self,
        process: FakeProcess | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.process = process
        self.error = error
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(
        self,
        arguments: list[str],
        **keywords: Any,
    ) -> FakeProcess:
        self.calls.append((arguments, keywords))
        if self.error is not None:
            raise self.error
        assert self.process is not None
        return self.process


# [Helpers]


def _wav_file(tmp_path: Path) -> Path:
    wav_path = tmp_path / "warning.wav"
    wav_path.write_bytes(b"RIFF-test")
    return wav_path


def _install_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    process: FakeProcess | None = None,
    popen_error: Exception | None = None,
    stderr_file: FakeStderr | None = None,
) -> tuple[PopenRecorder, FakeStderr]:
    active_stderr = stderr_file or FakeStderr()
    recorder = PopenRecorder(process, error=popen_error)
    monkeypatch.setattr(
        backend_module.shutil,
        "which",
        lambda _path: RESOLVED_APLAY,
    )
    monkeypatch.setattr(
        backend_module.tempfile,
        "TemporaryFile",
        lambda **_arguments: active_stderr,
    )
    monkeypatch.setattr(
        backend_module.subprocess,
        "Popen",
        recorder,
    )
    return recorder, active_stderr


def _open_backend(
    monkeypatch: pytest.MonkeyPatch,
    *,
    process: FakeProcess | None = None,
    popen_error: Exception | None = None,
    stderr_file: FakeStderr | None = None,
    **arguments: Any,
) -> tuple[
    backend_module.AplayAudioBackend,
    PopenRecorder,
    FakeStderr,
]:
    recorder, active_stderr = _install_runtime(
        monkeypatch,
        process=process,
        popen_error=popen_error,
        stderr_file=stderr_file,
    )
    backend = backend_module.AplayAudioBackend(
        device=DEVICE,
        **arguments,
    )
    backend.open()
    return backend, recorder, active_stderr


# [Constructor and open]


def test_constructor_has_no_external_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        backend_module.shutil,
        "which",
        lambda _path: events.append("which"),
    )
    monkeypatch.setattr(
        backend_module.tempfile,
        "TemporaryFile",
        lambda **_arguments: events.append("tempfile"),
    )
    monkeypatch.setattr(
        backend_module.subprocess,
        "Popen",
        lambda *_arguments, **_keywords: events.append("popen"),
    )

    backend = backend_module.AplayAudioBackend(device=DEVICE)

    assert events == []
    assert backend._device == DEVICE
    assert backend._aplay_path == "aplay"
    assert backend._terminate_timeout_seconds == 1.0
    assert backend._kill_timeout_seconds == 1.0
    assert backend._stderr_max_bytes == 16 * 1024


def test_constructor_preserves_explicit_settings() -> None:
    backend = backend_module.AplayAudioBackend(
        device="custom-device",
        aplay_path="/custom/aplay",
        terminate_timeout_seconds=2,
        kill_timeout_seconds=3.5,
        stderr_max_bytes=128,
    )

    assert backend._device == "custom-device"
    assert backend._aplay_path == "/custom/aplay"
    assert backend._terminate_timeout_seconds == 2.0
    assert backend._kill_timeout_seconds == 3.5
    assert backend._stderr_max_bytes == 128


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("device", ""),
        ("device", "  "),
        ("device", None),
        ("aplay_path", ""),
        ("aplay_path", "\t"),
        ("aplay_path", 1),
    ],
)
def test_constructor_rejects_blank_string_settings(
    field_name: str,
    value: Any,
) -> None:
    arguments = {"device": DEVICE, field_name: value}

    with pytest.raises(ValueError):
        backend_module.AplayAudioBackend(**arguments)


@pytest.mark.parametrize(
    "field_name,value",
    [
        ("terminate_timeout_seconds", True),
        ("terminate_timeout_seconds", 0),
        ("terminate_timeout_seconds", -1),
        ("terminate_timeout_seconds", float("nan")),
        ("terminate_timeout_seconds", float("inf")),
        ("kill_timeout_seconds", False),
        ("kill_timeout_seconds", 0),
        ("kill_timeout_seconds", float("-inf")),
        ("kill_timeout_seconds", "1"),
    ],
)
def test_constructor_rejects_invalid_timeout(
    field_name: str,
    value: Any,
) -> None:
    with pytest.raises(ValueError):
        backend_module.AplayAudioBackend(
            device=DEVICE,
            **{field_name: value},
        )


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "16", None])
def test_constructor_rejects_invalid_stderr_limit(value: Any) -> None:
    with pytest.raises(ValueError):
        backend_module.AplayAudioBackend(
            device=DEVICE,
            stderr_max_bytes=value,
        )


def test_open_resolves_executable_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths: list[str] = []
    monkeypatch.setattr(
        backend_module.shutil,
        "which",
        lambda path: paths.append(path) or RESOLVED_APLAY,
    )
    backend = backend_module.AplayAudioBackend(device=DEVICE)

    backend.open()
    backend.open()

    assert paths == ["aplay"]
    assert backend._resolved_aplay_path == RESOLVED_APLAY


def test_open_reports_missing_executable_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [None, RESOLVED_APLAY]
    monkeypatch.setattr(
        backend_module.shutil,
        "which",
        lambda _path: results.pop(0),
    )
    backend = backend_module.AplayAudioBackend(device=DEVICE)

    with pytest.raises(
        backend_module.AudioBackendInitializationError
    ):
        backend.open()

    backend.open()
    assert backend._resolved_aplay_path == RESOLVED_APLAY


def test_open_preserves_resolver_error_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver_error = OSError("resolver failed")
    results: list[Exception | str] = [resolver_error, RESOLVED_APLAY]

    def resolve(_path: str) -> str:
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(backend_module.shutil, "which", resolve)
    backend = backend_module.AplayAudioBackend(device=DEVICE)

    with pytest.raises(
        backend_module.AudioBackendInitializationError
    ) as exc_info:
        backend.open()

    assert exc_info.value.__cause__ is resolver_error
    backend.open()


# [Start and state]


def test_start_before_open_raises_state_error(tmp_path: Path) -> None:
    backend = backend_module.AplayAudioBackend(device=DEVICE)

    with pytest.raises(backend_module.AudioBackendStateError):
        backend.start(_wav_file(tmp_path))


@pytest.mark.parametrize("kind", ["non-path", "missing", "directory"])
def test_start_rejects_invalid_wav_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
) -> None:
    backend, recorder, _ = _open_backend(monkeypatch)
    wav_path: Any
    if kind == "non-path":
        wav_path = str(tmp_path / "warning.wav")
        expected_error = TypeError
    elif kind == "missing":
        wav_path = tmp_path / "missing.wav"
        expected_error = FileNotFoundError
    else:
        wav_path = tmp_path
        expected_error = ValueError

    with pytest.raises(expected_error):
        backend.start(wav_path)

    assert recorder.calls == []


def test_start_uses_exact_nonblocking_popen_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess(poll_results=[None])
    backend, recorder, stderr_file = _open_backend(
        monkeypatch,
        process=process,
    )
    wav_path = _wav_file(tmp_path)

    backend.start(wav_path)

    assert len(recorder.calls) == 1
    arguments, keywords = recorder.calls[0]
    assert arguments == [
        RESOLVED_APLAY,
        "-q",
        "-D",
        DEVICE,
        str(wav_path.resolve(strict=True)),
    ]
    assert keywords == {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": stderr_file,
        "shell": False,
    }
    assert process.events == []


def test_start_rejects_second_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend, recorder, _ = _open_backend(
        monkeypatch,
        process=FakeProcess(poll_results=[None]),
    )
    wav_path = _wav_file(tmp_path)
    backend.start(wav_path)

    with pytest.raises(backend_module.AudioBackendStateError):
        backend.start(wav_path)

    assert len(recorder.calls) == 1


def test_popen_failure_closes_stderr_and_preserves_cause(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    popen_error = OSError("popen failed")
    backend, _, stderr_file = _open_backend(
        monkeypatch,
        popen_error=popen_error,
    )

    with pytest.raises(
        backend_module.AudioPlaybackStartError
    ) as exc_info:
        backend.start(_wav_file(tmp_path))

    assert exc_info.value.primary_error is popen_error
    assert stderr_file.closed
    assert backend._resources is None


def test_popen_and_stderr_close_failure_cannot_fall_through(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    popen_error = OSError("popen failed")
    close_error = OSError("close failed")
    stderr_file = FakeStderr(close_errors=[close_error, None])
    backend, recorder, _ = _open_backend(
        monkeypatch,
        popen_error=popen_error,
        stderr_file=stderr_file,
    )

    with pytest.raises(
        backend_module.AudioBackendCleanupError
    ) as exc_info:
        backend.start(_wav_file(tmp_path))

    assert isinstance(
        exc_info.value.primary_error,
        backend_module.AudioPlaybackStartError,
    )
    assert exc_info.value.cleanup_errors == (close_error,)
    assert backend._resources is not None
    assert backend._resources.process is None
    assert backend._resources.stderr_file is stderr_file
    assert len(recorder.calls) == 1


# [Poll]


def test_poll_running_returns_false_without_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess(poll_results=[None])
    backend, _, stderr_file = _open_backend(
        monkeypatch,
        process=process,
    )
    backend.start(_wav_file(tmp_path))

    assert backend.poll() is False
    assert stderr_file.close_calls == 0
    assert backend._resources is not None


def test_poll_success_returns_true_and_releases_resources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess(poll_results=[0])
    backend, _, stderr_file = _open_backend(
        monkeypatch,
        process=process,
    )
    backend.start(_wav_file(tmp_path))

    assert backend.poll() is True
    assert stderr_file.closed
    assert stderr_file.read_calls == []
    assert backend._resources is None


def test_nonzero_exit_captures_stderr_once_before_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess(poll_results=[2])
    stderr_file = FakeStderr(b"abcdefghijk")
    backend, _, _ = _open_backend(
        monkeypatch,
        process=process,
        stderr_file=stderr_file,
        stderr_max_bytes=8,
    )
    backend.start(_wav_file(tmp_path))

    with pytest.raises(backend_module.AudioPlaybackError) as exc_info:
        backend.poll()

    assert exc_info.value.exit_code == 2
    assert exc_info.value.stderr == (
        "abcdefgh\nstderr가 8 bytes에서 잘렸습니다."
    )
    assert stderr_file.seek_calls == [0]
    assert stderr_file.read_calls == [9]
    assert stderr_file.close_calls == 1


@pytest.mark.parametrize("failure_step", ["seek", "read"])
def test_stderr_capture_failure_combines_playback_and_cleanup_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_step: str,
) -> None:
    capture_error = OSError(f"{failure_step} failed")
    stderr_file = FakeStderr(
        b"failure",
        seek_error=capture_error if failure_step == "seek" else None,
        read_error=capture_error if failure_step == "read" else None,
    )
    backend, _, _ = _open_backend(
        monkeypatch,
        process=FakeProcess(poll_results=[1]),
        stderr_file=stderr_file,
    )
    backend.start(_wav_file(tmp_path))

    with pytest.raises(
        backend_module.AudioBackendCleanupError
    ) as exc_info:
        backend.poll()

    assert isinstance(
        exc_info.value.primary_error,
        backend_module.AudioPlaybackError,
    )
    assert exc_info.value.primary_error.exit_code == 1
    assert exc_info.value.cleanup_errors == (capture_error,)
    assert stderr_file.closed


def test_poll_without_process_and_cleanup_pending_are_state_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    backend, _, _ = _open_backend(monkeypatch)
    with pytest.raises(backend_module.AudioBackendStateError):
        backend.poll()

    popen_error = OSError("popen failed")
    close_error = OSError("close failed")
    stderr_file = FakeStderr(close_errors=[close_error])
    backend, _, _ = _open_backend(
        monkeypatch,
        popen_error=popen_error,
        stderr_file=stderr_file,
    )
    with pytest.raises(backend_module.AudioBackendCleanupError):
        backend.start(_wav_file(tmp_path))
    with pytest.raises(backend_module.AudioBackendStateError):
        backend.poll()


# [Stop and cleanup retry]


def test_stop_without_active_process_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend, _, _ = _open_backend(monkeypatch)
    backend.stop()


@pytest.mark.parametrize("exit_code", [0, 3, -15])
def test_stop_classifies_process_already_finished(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exit_code: int,
) -> None:
    process = FakeProcess(poll_results=[exit_code])
    backend, _, stderr_file = _open_backend(
        monkeypatch,
        process=process,
        stderr_file=FakeStderr(b"natural failure"),
    )
    backend.start(_wav_file(tmp_path))

    if exit_code == 0:
        backend.stop()
    else:
        with pytest.raises(backend_module.AudioPlaybackError) as exc_info:
            backend.stop()
        assert exc_info.value.exit_code == exit_code

    assert not any(event[0] == "terminate" for event in process.events)
    assert stderr_file.closed


@pytest.mark.parametrize("exit_code", [0, 1, -15])
def test_stop_after_successful_terminate_is_intentional(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    exit_code: int,
) -> None:
    process = FakeProcess(
        poll_results=[None],
        wait_results=[exit_code],
    )
    backend, _, stderr_file = _open_backend(
        monkeypatch,
        process=process,
    )
    backend.start(_wav_file(tmp_path))

    backend.stop()

    assert process.events == [
        ("poll",),
        ("terminate",),
        ("wait", 1.0),
    ]
    assert stderr_file.closed
    assert backend._resources is None


def test_terminate_already_exited_race_uses_natural_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess(
        poll_results=[None, 4],
        terminate_errors=[ProcessLookupError("already exited")],
    )
    backend, _, _ = _open_backend(
        monkeypatch,
        process=process,
        stderr_file=FakeStderr(b"natural failure"),
    )
    backend.start(_wav_file(tmp_path))

    with pytest.raises(backend_module.AudioPlaybackError) as exc_info:
        backend.stop()

    assert exc_info.value.exit_code == 4
    assert process.events == [("poll",), ("terminate",), ("poll",)]


def test_terminate_timeout_uses_kill_and_bounded_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess(
        poll_results=[None],
        wait_results=[
            subprocess.TimeoutExpired("aplay", 2.0),
            -9,
        ],
    )
    backend, _, _ = _open_backend(
        monkeypatch,
        process=process,
        terminate_timeout_seconds=2.0,
        kill_timeout_seconds=3.0,
    )
    backend.start(_wav_file(tmp_path))

    backend.stop()

    assert process.events == [
        ("poll",),
        ("terminate",),
        ("wait", 2.0),
        ("kill",),
        ("wait", 3.0),
    ]


def test_kill_wait_timeout_preserves_intentional_stop_for_retry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    final_timeout = subprocess.TimeoutExpired("aplay", 1.0)
    process = FakeProcess(
        poll_results=[None, -9],
        wait_results=[
            subprocess.TimeoutExpired("aplay", 1.0),
            final_timeout,
        ],
    )
    backend, _, stderr_file = _open_backend(
        monkeypatch,
        process=process,
    )
    backend.start(_wav_file(tmp_path))

    with pytest.raises(backend_module.AudioBackendCleanupError):
        backend.close()

    assert backend._resources is not None
    assert backend._resources.termination_requested is True
    assert backend._resources.process is process

    with pytest.raises(
        backend_module.AudioBackendCleanupError
    ) as exc_info:
        backend.close()

    assert not isinstance(
        exc_info.value.primary_error,
        backend_module.AudioPlaybackError,
    )
    assert exc_info.value.cleanup_errors == (final_timeout,)
    assert stderr_file.closed
    assert backend._resources is None


def test_failed_termination_and_positive_wait_preserve_both_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    terminate_error = OSError("terminate failed")
    kill_error = OSError("kill failed")
    process = FakeProcess(
        poll_results=[None, None],
        wait_results=[1],
        terminate_errors=[terminate_error],
        kill_errors=[kill_error],
    )
    backend, _, _ = _open_backend(
        monkeypatch,
        process=process,
        stderr_file=FakeStderr(b"natural failure"),
    )
    backend.start(_wav_file(tmp_path))

    with pytest.raises(
        backend_module.AudioBackendCleanupError
    ) as exc_info:
        backend.stop()

    assert isinstance(
        exc_info.value.primary_error,
        backend_module.AudioPlaybackError,
    )
    assert exc_info.value.primary_error.exit_code == 1
    assert exc_info.value.cleanup_errors == (
        terminate_error,
        kill_error,
    )


def test_reaped_process_and_failed_stderr_are_retried_independently(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    close_error = OSError("close failed")
    stderr_file = FakeStderr(close_errors=[close_error, None])
    process = FakeProcess(poll_results=[0])
    backend, _, _ = _open_backend(
        monkeypatch,
        process=process,
        stderr_file=stderr_file,
    )
    backend.start(_wav_file(tmp_path))

    with pytest.raises(backend_module.AudioBackendCleanupError):
        backend.poll()

    assert backend._resources is not None
    assert backend._resources.process is None
    assert backend._resources.stderr_file is stderr_file

    with pytest.raises(backend_module.AudioBackendCleanupError):
        backend.close()

    assert process.events == [("poll",)]
    assert stderr_file.close_calls == 2


# [Close]


def test_close_before_open_and_repeated_successful_close_are_noops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = backend_module.AplayAudioBackend(device=DEVICE)
    backend.close()

    backend, _, _ = _open_backend(monkeypatch)
    backend.close()
    backend.close()


def test_close_stops_active_process_and_closes_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess(
        poll_results=[None],
        wait_results=[0],
    )
    backend, _, stderr_file = _open_backend(
        monkeypatch,
        process=process,
    )
    backend.start(_wav_file(tmp_path))

    backend.close()

    assert stderr_file.closed
    with pytest.raises(backend_module.AudioBackendStateError):
        backend.open()
    with pytest.raises(backend_module.AudioBackendStateError):
        backend.start(_wav_file(tmp_path))
    with pytest.raises(backend_module.AudioBackendStateError):
        backend.poll()


def test_terminal_cleanup_error_is_repeated_without_more_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    close_error = OSError("close failed")
    stderr_file = FakeStderr(close_errors=[close_error])
    stderr_file.close = _close_and_raise(stderr_file, close_error)
    backend, _, _ = _open_backend(
        monkeypatch,
        process=FakeProcess(poll_results=[0]),
        stderr_file=stderr_file,
    )
    backend.start(_wav_file(tmp_path))

    with pytest.raises(
        backend_module.AudioBackendCleanupError
    ) as first_exc:
        backend.close()

    close_calls = stderr_file.close_calls
    with pytest.raises(
        backend_module.AudioBackendCleanupError
    ) as second_exc:
        backend.close()

    assert second_exc.value is first_exc.value
    assert stderr_file.close_calls == close_calls


def _close_and_raise(
    stderr_file: FakeStderr,
    error: Exception,
) -> Callable[[], None]:
    def close() -> None:
        stderr_file.close_calls += 1
        stderr_file.closed = True
        raise error

    return close


def test_remaining_resource_without_error_violates_internal_invariant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NonClosingStderr(FakeStderr):
        def close(self) -> None:
            self.close_calls += 1

    resources = backend_module._PlaybackResources(
        process=None,
        stderr_file=NonClosingStderr(),
    )
    backend, _, _ = _open_backend(monkeypatch)
    backend._resources = resources

    with pytest.raises(AssertionError, match="cleanup 원인 없이"):
        backend._finish_resources(resources, closing=False)

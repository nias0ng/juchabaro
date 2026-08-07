"""신뢰 가능한 ``aplay`` process 하나의 재생 생명주기를 관리한다.

이 모듈은 WAV 선택, 반복 순서, 재생 간격 또는 speaker worker를 소유하지
않는다. 호출자는 하나의 owner에서 모든 메서드를 직렬로 호출해야 하며 이
구현은 thread-safe를 보장하지 않는다.

stderr는 pipe deadlock을 피하기 위해 임시 파일로 보낸다. 배포가 선택한
신뢰 가능한 ``aplay``를 ``-q``로 실행한다는 전제에서 파일 크기에 hard cap을
두지 않고, 오류에 포함하는 내용만 제한한다. 별도 drain thread는 만들지 않는다.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum, auto
from numbers import Real
from pathlib import Path
from typing import BinaryIO, NoReturn, Protocol


DEFAULT_TERMINATE_TIMEOUT_SECONDS = 1.0
DEFAULT_KILL_TIMEOUT_SECONDS = 1.0
DEFAULT_STDERR_MAX_BYTES = 16 * 1024


class AudioBackendError(RuntimeError):
    """Audio playback backend 공통 오류."""


class AudioBackendInitializationError(AudioBackendError):
    """``aplay`` 실행 환경 확인 실패."""


class AudioBackendStateError(AudioBackendError):
    """현재 생명주기에서 허용되지 않는 작업."""


class AudioPlaybackStartError(AudioBackendError):
    """``aplay`` process 시작 실패."""

    def __init__(
        self,
        message: str,
        *,
        primary_error: Exception,
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.__cause__ = primary_error


class AudioPlaybackError(AudioBackendError):
    """종료 요청 전에 발생한 ``aplay`` 비정상 종료."""

    def __init__(
        self,
        message: str,
        *,
        exit_code: int,
        stderr: str,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class AudioBackendCleanupError(AudioBackendError):
    """Process 회수 또는 stderr 정리 실패."""

    def __init__(
        self,
        message: str,
        *,
        primary_error: Exception,
        cleanup_errors: tuple[Exception, ...],
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.cleanup_errors = cleanup_errors
        self.__cause__ = primary_error


class AudioPlaybackBackend(Protocol):
    """비동기 WAV 재생 process 하나를 관리하는 최소 계약."""

    def open(self) -> None:
        """재생 실행 환경을 준비한다."""

    def start(self, wav_path: Path) -> None:
        """WAV 재생을 시작하고 즉시 반환한다."""

    def poll(self) -> bool:
        """실행 중이면 ``False``, 정상 완료면 ``True``를 반환한다."""

    def stop(self) -> None:
        """현재 재생을 중단하고 process를 회수한다."""

    def close(self) -> None:
        """현재 재생과 backend 자원을 정리한다."""


class _LifecycleState(Enum):
    NEW = auto()
    OPEN = auto()
    CLOSED = auto()


@dataclass(frozen=True)
class _CleanupIssue:
    description: str
    error: Exception


@dataclass
class _PlaybackResources:
    process: subprocess.Popen[bytes] | None
    stderr_file: BinaryIO | None
    termination_requested: bool = False
    cleanup_pending: bool = False
    primary_error: Exception | None = None
    cleanup_issues: list[_CleanupIssue] = field(default_factory=list)


def _require_non_blank_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name}는 비어 있지 않은 문자열이어야 합니다.")
    return value


def _positive_finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 양수여야 합니다."
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 양수여야 합니다."
        ) from error

    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 양수여야 합니다."
        )
    return normalized


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name}는 bool이 아닌 양의 정수여야 합니다.")
    return value


class AplayAudioBackend:
    """인자 배열로 실행한 ``aplay`` process 하나를 관리한다.

    두 timeout은 재생 시간이 아니라 terminate/kill 이후 child 회수를 제한하는
    bounded cleanup 값이다. ``open()``은 실행 파일만 확인하며 USB PCM의 실제
    사용 가능 여부는 재생 process 결과로 확인된다.
    """

    def __init__(
        self,
        *,
        device: str,
        aplay_path: str = "aplay",
        terminate_timeout_seconds: float = (
            DEFAULT_TERMINATE_TIMEOUT_SECONDS
        ),
        kill_timeout_seconds: float = DEFAULT_KILL_TIMEOUT_SECONDS,
        stderr_max_bytes: int = DEFAULT_STDERR_MAX_BYTES,
    ) -> None:
        self._device = _require_non_blank_string(device, "device")
        self._aplay_path = _require_non_blank_string(
            aplay_path,
            "aplay_path",
        )
        self._terminate_timeout_seconds = _positive_finite_number(
            terminate_timeout_seconds,
            "terminate_timeout_seconds",
        )
        self._kill_timeout_seconds = _positive_finite_number(
            kill_timeout_seconds,
            "kill_timeout_seconds",
        )
        self._stderr_max_bytes = _positive_integer(
            stderr_max_bytes,
            "stderr_max_bytes",
        )

        self._state = _LifecycleState.NEW
        self._resolved_aplay_path: str | None = None
        self._resources: _PlaybackResources | None = None
        self._terminal_cleanup_error: AudioBackendCleanupError | None = None

    def open(self) -> None:
        """``aplay`` executable을 확인하며 실제 음성은 재생하지 않는다."""

        if self._state is _LifecycleState.OPEN:
            return
        if self._state is _LifecycleState.CLOSED:
            raise AudioBackendStateError(
                "닫힌 audio backend는 다시 열 수 없습니다."
            )

        try:
            resolved_path = shutil.which(self._aplay_path)
        except Exception as error:
            initialization_error = AudioBackendInitializationError(
                "aplay executable 확인에 실패했습니다."
            )
            raise initialization_error from error

        if resolved_path is None:
            raise AudioBackendInitializationError(
                "aplay executable을 찾을 수 없습니다: "
                f"{self._aplay_path!r}"
            )

        self._resolved_aplay_path = resolved_path
        self._state = _LifecycleState.OPEN

    def start(self, wav_path: Path) -> None:
        """검증한 WAV를 ``aplay``로 시작하고 완료를 기다리지 않는다."""

        self._require_open()
        if self._resources is not None:
            raise AudioBackendStateError(
                "이전 재생 또는 cleanup이 완료되지 않았습니다."
            )

        absolute_wav_path = self._require_wav_file(wav_path)

        try:
            stderr_file = tempfile.TemporaryFile(mode="w+b")
        except Exception as error:
            start_error = AudioPlaybackStartError(
                "aplay stderr 임시 파일을 만들 수 없습니다.",
                primary_error=error,
            )
            raise start_error from error

        try:
            process = subprocess.Popen(
                [
                    self._require_resolved_aplay_path(),
                    "-q",
                    "-D",
                    self._device,
                    str(absolute_wav_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                shell=False,
            )
        except Exception as error:
            self._raise_start_failure(
                error=error,
                stderr_file=stderr_file,
            )
        else:
            self._resources = _PlaybackResources(
                process=process,
                stderr_file=stderr_file,
            )

    def poll(self) -> bool:
        """실행 상태를 관찰하고 완료된 process와 stderr를 즉시 정리한다."""

        self._require_open()
        resources = self._require_resources()
        if resources.cleanup_pending:
            raise AudioBackendStateError(
                "재생 cleanup이 진행 중입니다. stop() 또는 close()로 "
                "정리를 완료하세요."
            )

        process = resources.process
        if process is None:
            raise AudioBackendStateError("관찰할 활성 process가 없습니다.")

        exit_code = process.poll()
        if exit_code is None:
            return False

        resources.process = None
        self._record_exit_result(resources, exit_code=exit_code)
        self._finish_resources(resources, closing=False)
        return True

    def stop(self) -> None:
        """현재 process를 bounded terminate/kill 순서로 확실히 회수한다."""

        resources = self._resources
        if resources is None:
            return

        if resources.cleanup_pending:
            self._continue_cleanup(resources, closing=False)
            return

        self._stop_resources(resources, closing=False)

    def close(self) -> None:
        """현재 재생을 정리하고 반복 호출 가능한 종료 상태로 전환한다."""

        if self._state is _LifecycleState.NEW:
            return
        if self._state is _LifecycleState.CLOSED:
            if self._terminal_cleanup_error is not None:
                raise self._terminal_cleanup_error
            return

        resources = self._resources
        if resources is None:
            self._state = _LifecycleState.CLOSED
            return

        if resources.cleanup_pending:
            self._continue_cleanup(resources, closing=True)
            return

        self._stop_resources(resources, closing=True)

    def _require_open(self) -> None:
        if self._state is not _LifecycleState.OPEN:
            raise AudioBackendStateError(
                "audio backend가 열리지 않았습니다. open()을 먼저 호출하세요."
            )

    def _require_resolved_aplay_path(self) -> str:
        if self._resolved_aplay_path is None:
            raise AudioBackendStateError(
                "aplay executable이 준비되지 않았습니다."
            )
        return self._resolved_aplay_path

    def _require_resources(self) -> _PlaybackResources:
        if self._resources is None:
            raise AudioBackendStateError("관찰할 활성 process가 없습니다.")
        return self._resources

    def _require_wav_file(self, wav_path: Path) -> Path:
        if not isinstance(wav_path, Path):
            raise TypeError("wav_path는 pathlib.Path여야 합니다.")

        try:
            absolute_path = wav_path.resolve(strict=True)
        except FileNotFoundError:
            raise
        except OSError:
            raise

        if not absolute_path.is_file():
            raise ValueError("wav_path는 존재하는 regular file이어야 합니다.")
        return absolute_path

    def _raise_start_failure(
        self,
        *,
        error: Exception,
        stderr_file: BinaryIO,
    ) -> NoReturn:
        start_error = AudioPlaybackStartError(
            "aplay process를 시작할 수 없습니다.",
            primary_error=error,
        )
        resources = _PlaybackResources(
            process=None,
            stderr_file=stderr_file,
            cleanup_pending=True,
            primary_error=start_error,
        )
        self._resources = resources
        self._finish_resources(resources, closing=False)
        raise AssertionError(
            "_finish_resources()가 start 오류를 전달하지 않았습니다."
        )

    def _stop_resources(
        self,
        resources: _PlaybackResources,
        *,
        closing: bool,
    ) -> None:
        process = resources.process
        if process is None:
            resources.cleanup_pending = True
            self._continue_cleanup(resources, closing=closing)
            return

        exit_code = process.poll()
        if exit_code is not None:
            resources.process = None
            self._record_exit_result(resources, exit_code=exit_code)
            self._finish_resources(resources, closing=closing)
            return

        resources.cleanup_pending = True
        try:
            process.terminate()
        except ProcessLookupError as error:
            exit_code = process.poll()
            if exit_code is not None:
                resources.process = None
                self._record_exit_result(resources, exit_code=exit_code)
                self._finish_resources(resources, closing=closing)
                return

            resources.cleanup_issues.append(
                _CleanupIssue(
                    description=(
                        "aplay terminate 중 process 상태 확인 실패"
                    ),
                    error=error,
                )
            )
        except Exception as error:
            resources.cleanup_issues.append(
                _CleanupIssue(
                    description="aplay terminate 요청 실패",
                    error=error,
                )
            )

            exit_code = process.poll()
            if exit_code is not None:
                resources.process = None
                self._record_exit_result(resources, exit_code=exit_code)
                self._finish_resources(resources, closing=closing)
                return
        else:
            resources.termination_requested = True
            try:
                exit_code = process.wait(
                    timeout=self._terminate_timeout_seconds
                )
            except subprocess.TimeoutExpired:
                pass
            except Exception as error:
                resources.cleanup_issues.append(
                    _CleanupIssue(
                        description="aplay terminate 이후 wait 실패",
                        error=error,
                    )
                )
            else:
                resources.process = None
                self._record_exit_result(resources, exit_code=exit_code)
                self._finish_resources(resources, closing=closing)
                return

        self._kill_and_wait(resources)
        self._finish_resources(resources, closing=closing)

    def _continue_cleanup(
        self,
        resources: _PlaybackResources,
        *,
        closing: bool,
    ) -> None:
        process = resources.process
        if process is not None:
            exit_code = process.poll()
            if exit_code is not None:
                resources.process = None
                self._record_exit_result(resources, exit_code=exit_code)
            else:
                self._kill_and_wait(resources)

        self._finish_resources(resources, closing=closing)

    def _kill_and_wait(self, resources: _PlaybackResources) -> None:
        process = resources.process
        if process is None:
            return

        try:
            process.kill()
        except Exception as error:
            resources.cleanup_issues.append(
                _CleanupIssue(
                    description="aplay kill 요청 실패",
                    error=error,
                )
            )
        else:
            resources.termination_requested = True

        try:
            exit_code = process.wait(timeout=self._kill_timeout_seconds)
        except subprocess.TimeoutExpired as error:
            resources.cleanup_issues.append(
                _CleanupIssue(
                    description="aplay kill 이후 bounded wait timeout",
                    error=error,
                )
            )
        except Exception as error:
            resources.cleanup_issues.append(
                _CleanupIssue(
                    description="aplay kill 이후 wait 실패",
                    error=error,
                )
            )
        else:
            resources.process = None
            self._record_exit_result(resources, exit_code=exit_code)

    def _record_exit_result(
        self,
        resources: _PlaybackResources,
        *,
        exit_code: int,
    ) -> None:
        if (
            exit_code == 0
            or resources.termination_requested
            or resources.primary_error is not None
        ):
            return

        captured_stderr = self._capture_playback_stderr(resources)
        message = f"aplay가 비정상 종료했습니다: exit_code={exit_code}"
        if captured_stderr:
            message += f"; stderr={captured_stderr}"
        resources.primary_error = AudioPlaybackError(
            message,
            exit_code=exit_code,
            stderr=captured_stderr,
        )

    def _capture_playback_stderr(
        self,
        resources: _PlaybackResources,
    ) -> str:
        stderr_file = resources.stderr_file
        if stderr_file is None:
            return ""

        try:
            stderr_file.seek(0)
        except Exception as error:
            resources.cleanup_issues.append(
                _CleanupIssue(
                    description="aplay stderr 임시 파일 seek 실패",
                    error=error,
                )
            )
            return ""

        try:
            captured = stderr_file.read(self._stderr_max_bytes + 1)
        except Exception as error:
            resources.cleanup_issues.append(
                _CleanupIssue(
                    description="aplay stderr 임시 파일 read 실패",
                    error=error,
                )
            )
            return ""

        truncated = len(captured) > self._stderr_max_bytes
        decoded = captured[: self._stderr_max_bytes].decode(
            "utf-8",
            errors="replace",
        ).strip()
        if not truncated:
            return decoded

        truncation_message = (
            f"stderr가 {self._stderr_max_bytes} bytes에서 잘렸습니다."
        )
        if decoded:
            return f"{decoded}\n{truncation_message}"
        return truncation_message

    def _cleanup_stderr(self, resources: _PlaybackResources) -> None:
        stderr_file = resources.stderr_file
        if stderr_file is None:
            return

        try:
            stderr_file.close()
        except Exception as error:
            resources.cleanup_issues.append(
                _CleanupIssue(
                    description="aplay stderr 임시 파일 close 실패",
                    error=error,
                )
            )

        if stderr_file.closed:
            resources.stderr_file = None

    def _finish_resources(
        self,
        resources: _PlaybackResources,
        *,
        closing: bool,
    ) -> None:
        if resources.process is None:
            self._cleanup_stderr(resources)

        resources_remain = (
            resources.process is not None
            or resources.stderr_file is not None
        )
        if resources_remain:
            resources.cleanup_pending = True
            if (
                resources.primary_error is None
                and not resources.cleanup_issues
            ):
                raise AssertionError(
                    "cleanup 원인 없이 playback resource가 남아 있습니다."
                )
            raise self._build_cleanup_error(resources)

        resources.cleanup_pending = False
        resources.termination_requested = False
        self._resources = None

        if resources.cleanup_issues:
            terminal_error = self._build_cleanup_error(resources)
            self._terminal_cleanup_error = terminal_error
            self._state = _LifecycleState.CLOSED
            raise terminal_error from terminal_error.primary_error

        if closing:
            self._state = _LifecycleState.CLOSED

        if resources.primary_error is not None:
            raise resources.primary_error

    def _build_cleanup_error(
        self,
        resources: _PlaybackResources,
    ) -> AudioBackendCleanupError:
        cleanup_errors = tuple(
            issue.error for issue in resources.cleanup_issues
        )
        primary_error = resources.primary_error
        if primary_error is None:
            if not cleanup_errors:
                raise AssertionError(
                    "cleanup error를 만들 원인이 없습니다."
                )
            primary_error = cleanup_errors[0]

        details = "; ".join(
            f"{issue.description}: {issue.error}"
            for issue in resources.cleanup_issues
        )
        message = "aplay process 또는 stderr cleanup에 실패했습니다."
        if details:
            message += f" {details}"

        return AudioBackendCleanupError(
            message,
            primary_error=primary_error,
            cleanup_errors=cleanup_errors,
        )

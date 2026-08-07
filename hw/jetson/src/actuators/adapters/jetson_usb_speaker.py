"""Speaker projection을 단일 USB 경고 speaker의 순차 재생으로 유지한다.

이 모듈은 speaker 전용 projection 검증, 고정 round-robin과 단일 worker의
재생 생명주기만 소유한다. Incident 판단, ALSA subprocess 구현, WAV 선택이나
runtime 조립은 소유하지 않는다. 모든 backend 호출은 하나의 non-daemon worker가
직렬로 수행한다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum, auto
from numbers import Real
from pathlib import Path
from threading import Condition, Event, Thread, current_thread
from typing import Protocol

from src.actuators.adapters.audio_backend import AudioPlaybackBackend
from src.actuators.models import ActuatorCommand


logger = logging.getLogger(__name__)


DISABLED_ZONE_WARNING_SPEAKER_ID = "disabled_zone_warning_speaker"
EV_ZONE_WARNING_SPEAKER_ID = "ev_zone_warning_speaker"
PLAY_ACTION = "PLAY"

# 실제 장치에서 subprocess 완료 감지 지연과 polling 부하를 검증해야 하는 값이다.
DEFAULT_PLAYBACK_POLL_INTERVAL_SECONDS = 0.05

_SPEAKER_IDS = (
    DISABLED_ZONE_WARNING_SPEAKER_ID,
    EV_ZONE_WARNING_SPEAKER_ID,
)

_MAX_BACKEND_STOP_ATTEMPTS = 1
_MAX_BACKEND_CLOSE_ATTEMPTS = 2


class SpeakerAdapterError(RuntimeError):
    """USB 경고 speaker adapter 공통 오류."""


class _TerminalSpeakerAdapterError(SpeakerAdapterError):
    """최초 원인과 후속 cleanup 오류를 함께 보존하는 terminal 오류."""

    def __init__(
        self,
        message: str,
        *,
        primary_error: Exception,
        cleanup_errors: tuple[Exception, ...] = (),
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.cleanup_errors = cleanup_errors
        self.__cause__ = primary_error


class SpeakerAdapterInitializationError(_TerminalSpeakerAdapterError):
    """WAV 또는 backend, worker startup 실패."""


class SpeakerAdapterStateError(SpeakerAdapterError):
    """현재 lifecycle에서 허용되지 않는 작업."""


class InvalidSpeakerProjectionError(SpeakerAdapterError):
    """지원하지 않거나 모호한 speaker command projection."""


class SpeakerAdapterRuntimeError(_TerminalSpeakerAdapterError):
    """Background playback 중 발생한 terminal 오류."""


class SpeakerAdapterCleanupError(_TerminalSpeakerAdapterError):
    """Backend stop 또는 close 실패."""


class PlaybackScheduler(Protocol):
    """Worker의 condition wait 경계."""

    def wait(
        self,
        condition: Condition,
        timeout: float | None,
    ) -> None:
        """Notification 또는 timeout까지 대기한다."""


class ThreadingPlaybackScheduler:
    """``Condition.wait``를 사용하는 production scheduler."""

    def wait(
        self,
        condition: Condition,
        timeout: float | None,
    ) -> None:
        condition.wait(timeout)


class _LifecycleState(Enum):
    NEW = auto()
    OPENING = auto()
    OPEN = auto()
    CLOSING = auto()
    CLOSED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class _CleanupIssue:
    description: str
    error: Exception


@dataclass(frozen=True)
class _CleanupReport:
    failed_steps: tuple[str, ...]
    issues: tuple[_CleanupIssue, ...]

    @property
    def failed(self) -> bool:
        return bool(self.failed_steps)


@dataclass
class _WorkerContext:
    backend_open_attempted: bool = False
    startup_completed: bool = False

    stop_attempts: int = 0
    stop_completed: bool = False

    close_attempts: int = 0
    close_completed: bool = False

    cleanup_failed_steps: list[str] = field(default_factory=list)
    cleanup_issues: list[_CleanupIssue] = field(default_factory=list)
    observed_cleanup_error_ids: set[int] = field(default_factory=set)


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


def _decode_projection(
    commands: tuple[ActuatorCommand, ...],
) -> frozenset[str]:
    desired_ids: set[str] = set()

    for command in commands:
        if not isinstance(command, ActuatorCommand):
            raise InvalidSpeakerProjectionError(
                "projection의 모든 항목은 ActuatorCommand여야 합니다."
            )
        if command.actuator_id not in _SPEAKER_IDS:
            raise InvalidSpeakerProjectionError(
                "지원하지 않는 speaker actuator_id입니다: "
                f"{command.actuator_id!r}"
            )
        if command.action != PLAY_ACTION:
            raise InvalidSpeakerProjectionError(
                "지원하지 않는 speaker action입니다: "
                f"{command.action!r}"
            )
        if command.actuator_id in desired_ids:
            raise InvalidSpeakerProjectionError(
                "동일 speaker actuator_id가 중복됐습니다: "
                f"{command.actuator_id!r}"
            )
        desired_ids.add(command.actuator_id)

    return frozenset(desired_ids)


def _next_playback_id(
    active_ids: frozenset[str],
    last_completed_id: str | None,
) -> str | None:
    if not active_ids:
        return None

    if last_completed_id is None:
        return next(
            speaker_id
            for speaker_id in _SPEAKER_IDS
            if speaker_id in active_ids
        )

    try:
        start_index = _SPEAKER_IDS.index(last_completed_id) + 1
    except ValueError:
        start_index = 0

    for offset in range(len(_SPEAKER_IDS)):
        candidate = _SPEAKER_IDS[
            (start_index + offset) % len(_SPEAKER_IDS)
        ]
        if candidate in active_ids:
            return candidate

    return None


def _cleanup_report(context: _WorkerContext) -> _CleanupReport:
    return _CleanupReport(
        failed_steps=tuple(context.cleanup_failed_steps),
        issues=tuple(context.cleanup_issues),
    )


def _cleanup_message(
    prefix: str,
    report: _CleanupReport,
) -> str:
    if not report.failed_steps:
        return prefix
    return prefix + " " + "; ".join(report.failed_steps)


def _make_cleanup_error(
    report: _CleanupReport,
    *,
    fallback_primary_error: Exception | None = None,
) -> SpeakerAdapterCleanupError | None:
    if not report.failed:
        return None

    cleanup_errors = tuple(issue.error for issue in report.issues)
    if cleanup_errors:
        primary_error = cleanup_errors[0]
    elif fallback_primary_error is not None:
        primary_error = fallback_primary_error
    else:
        primary_error = RuntimeError(
            "speaker cleanup 실패의 고유한 원인 예외가 없습니다."
        )

    return SpeakerAdapterCleanupError(
        _cleanup_message("speaker cleanup에 실패했습니다.", report),
        primary_error=primary_error,
        cleanup_errors=cleanup_errors,
    )


class JetsonUsbSpeakerAdapter:
    """검증한 speaker projection을 고정 round-robin 재생으로 유지한다."""

    def __init__(
        self,
        *,
        backend: AudioPlaybackBackend,
        disabled_zone_warning_wav_path: Path,
        ev_zone_warning_wav_path: Path,
        playback_poll_interval_seconds: float = (
            DEFAULT_PLAYBACK_POLL_INTERVAL_SECONDS
        ),
        scheduler: PlaybackScheduler | None = None,
    ) -> None:
        if backend is None:
            raise ValueError("backend는 필수입니다.")

        self._backend = backend
        self._disabled_zone_warning_wav_path = (
            disabled_zone_warning_wav_path
        )
        self._ev_zone_warning_wav_path = ev_zone_warning_wav_path
        self._playback_poll_interval_seconds = _positive_finite_number(
            playback_poll_interval_seconds,
            "playback_poll_interval_seconds",
        )

        active_scheduler = (
            ThreadingPlaybackScheduler()
            if scheduler is None
            else scheduler
        )
        if not callable(getattr(active_scheduler, "wait", None)):
            raise ValueError("scheduler.wait는 callable이어야 합니다.")
        self._scheduler = active_scheduler

        self._condition = Condition()
        self._state = _LifecycleState.NEW
        self._desired_play_ids: frozenset[str] = frozenset()
        self._projection_generation = 0
        self._cycle_reset_requested = False
        self._stop_requested = False

        self._wav_path_by_speaker_id: dict[str, Path] = {}
        self._thread: Thread | None = None
        self._startup_complete = Event()
        self._startup_succeeded = False
        self._startup_error: SpeakerAdapterInitializationError | None = None
        self._failure: Exception | None = None
        self._cleanup_error: SpeakerAdapterCleanupError | None = None

    @property
    def failure(self) -> Exception | None:
        """최초 startup 또는 background terminal 오류."""

        with self._condition:
            return self._failure

    @property
    def is_running(self) -> bool:
        """Worker thread가 살아 있는지 반환한다."""

        with self._condition:
            return self._thread is not None and self._thread.is_alive()

    def open(self) -> None:
        """Worker에서 WAV와 backend startup을 완료할 때까지 기다린다."""

        with self._condition:
            if self._state is _LifecycleState.OPEN:
                return
            if self._state is not _LifecycleState.NEW:
                raise SpeakerAdapterStateError(
                    "현재 상태에서는 speaker adapter를 열 수 없습니다: "
                    f"{self._state.name}"
                )

            self._state = _LifecycleState.OPENING
            thread = Thread(
                target=self._run,
                name="jetson-warning-speaker",
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception as error:
                initialization_error = SpeakerAdapterInitializationError(
                    "speaker worker를 시작할 수 없습니다.",
                    primary_error=error,
                )
                self._thread = None
                self._startup_error = initialization_error
                self._failure = initialization_error
                self._state = _LifecycleState.FAILED
                self._startup_complete.set()
                raise initialization_error from error

        self._startup_complete.wait()

        with self._condition:
            startup_error = self._startup_error
            startup_succeeded = self._startup_succeeded
            worker = self._thread

            if startup_error is None and not startup_succeeded:
                missing_result = RuntimeError(
                    "speaker worker가 startup 결과를 확정하지 않았습니다."
                )
                startup_error = SpeakerAdapterInitializationError(
                    "speaker worker startup 결과가 유실됐습니다.",
                    primary_error=missing_result,
                )
                self._startup_error = startup_error
                if self._failure is None:
                    self._failure = startup_error
                self._state = _LifecycleState.FAILED
                self._condition.notify_all()

        if startup_error is not None:
            if worker is not None:
                worker.join()
            raise startup_error from startup_error.primary_error

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        """검증한 전체 speaker projection을 worker의 새 목표로 교체한다."""

        with self._condition:
            if self._state is not _LifecycleState.OPEN:
                raise SpeakerAdapterStateError(
                    "열린 speaker adapter에만 projection을 적용할 수 "
                    f"있습니다: {self._state.name}"
                )

        desired_play_ids = _decode_projection(commands)

        with self._condition:
            if self._state is not _LifecycleState.OPEN:
                raise SpeakerAdapterStateError(
                    "projection 검증 중 speaker adapter 상태가 "
                    f"변경됐습니다: {self._state.name}"
                )
            if desired_play_ids == self._desired_play_ids:
                return

            self._desired_play_ids = desired_play_ids
            if not desired_play_ids:
                self._cycle_reset_requested = True
            self._projection_generation += 1
            self._condition.notify_all()

    def close(self) -> None:
        """Worker에 shutdown을 요청하고 동일 worker의 종료를 기다린다."""

        with self._condition:
            state = self._state
            if state is _LifecycleState.NEW:
                return
            if state is _LifecycleState.OPENING:
                raise SpeakerAdapterStateError(
                    "open() 진행 중에는 close()를 호출할 수 없습니다."
                )

            worker = self._thread
            if worker is current_thread():
                raise SpeakerAdapterStateError(
                    "speaker worker thread는 자신을 join할 수 없습니다."
                )

            if state is _LifecycleState.OPEN:
                self._state = _LifecycleState.CLOSING
                self._stop_requested = True
                self._desired_play_ids = frozenset()
                self._cycle_reset_requested = True
                self._projection_generation += 1
                self._condition.notify_all()
            elif state is _LifecycleState.CLOSING:
                pass
            elif state is _LifecycleState.FAILED:
                self._stop_requested = True
                self._condition.notify_all()
            elif state is _LifecycleState.CLOSED:
                pass
            else:
                raise SpeakerAdapterStateError(
                    "지원하지 않는 speaker lifecycle 상태입니다: "
                    f"{state.name}"
                )

        if worker is not None:
            worker.join()

        with self._condition:
            cleanup_error = self._cleanup_error

        if cleanup_error is not None:
            raise cleanup_error from cleanup_error.primary_error

    def _run(self) -> None:
        context = _WorkerContext()
        try:
            self._run_owned_worker(context)
        except Exception as error:
            try:
                self._record_unexpected_worker_failure(
                    error,
                    context=context,
                )
            except Exception:
                logger.exception(
                    "speaker worker의 예상하지 못한 오류를 기록하는 데 "
                    "실패했습니다."
                )
        finally:
            self._startup_complete.set()
            try:
                with self._condition:
                    self._condition.notify_all()
            except Exception:
                logger.exception(
                    "speaker worker 종료 notification에 실패했습니다."
                )

    def _run_owned_worker(self, context: _WorkerContext) -> None:
        try:
            wav_paths = self._resolve_wav_paths()
            context.backend_open_attempted = True
            self._backend.open()
            self._publish_open_state(wav_paths)
            context.startup_completed = True
        except Exception as error:
            context.observed_cleanup_error_ids.add(id(error))
            report = self._shutdown_backend(
                context=context,
                stop_before_close=False,
            )
            self._record_startup_failure(
                primary_error=error,
                cleanup_report=report,
            )
            return

        self._startup_complete.set()

        try:
            self._playback_loop()
        except Exception as error:
            self._record_runtime_failure_and_cleanup(
                error,
                context=context,
            )
            return

        self._finish_requested_close(context)

    def _resolve_wav_paths(self) -> dict[str, Path]:
        return {
            DISABLED_ZONE_WARNING_SPEAKER_ID: self._resolve_wav_path(
                self._disabled_zone_warning_wav_path,
                "disabled_zone_warning_wav_path",
            ),
            EV_ZONE_WARNING_SPEAKER_ID: self._resolve_wav_path(
                self._ev_zone_warning_wav_path,
                "ev_zone_warning_wav_path",
            ),
        }

    def _resolve_wav_path(self, wav_path: object, field_name: str) -> Path:
        if not isinstance(wav_path, Path):
            raise TypeError(f"{field_name}는 pathlib.Path여야 합니다.")
        resolved_path = wav_path.resolve(strict=True)
        if not resolved_path.is_file():
            raise ValueError(f"{field_name}는 regular file이어야 합니다.")
        return resolved_path

    def _publish_open_state(self, wav_paths: dict[str, Path]) -> None:
        with self._condition:
            self._wav_path_by_speaker_id = wav_paths
            self._startup_succeeded = True
            self._state = _LifecycleState.OPEN
            self._condition.notify_all()

    def _playback_loop(self) -> None:
        playing_id: str | None = None
        last_completed_id: str | None = None
        applied_generation = 0

        while True:
            with self._condition:
                if self._stop_requested:
                    return
                desired_ids = self._desired_play_ids
                desired_generation = self._projection_generation
                reset_requested = self._cycle_reset_requested
                if reset_requested:
                    self._cycle_reset_requested = False

            if reset_requested:
                if playing_id is not None:
                    self._backend.stop()
                    playing_id = None
                last_completed_id = None
                applied_generation = desired_generation
                continue

            if applied_generation != desired_generation:
                if playing_id is not None and playing_id not in desired_ids:
                    self._backend.stop()
                    playing_id = None
                applied_generation = desired_generation
                continue

            if playing_id is None:
                next_id = _next_playback_id(
                    desired_ids,
                    last_completed_id,
                )
                if next_id is None:
                    with self._condition:
                        if self._stop_requested:
                            return
                        if (
                            self._cycle_reset_requested
                            or applied_generation
                            != self._projection_generation
                        ):
                            continue
                        self._scheduler.wait(self._condition, None)
                    continue

                self._backend.start(
                    self._wav_path_by_speaker_id[next_id]
                )
                playing_id = next_id
                continue

            with self._condition:
                if self._stop_requested:
                    return
                if (
                    self._cycle_reset_requested
                    or applied_generation != self._projection_generation
                ):
                    continue
                self._scheduler.wait(
                    self._condition,
                    self._playback_poll_interval_seconds,
                )
                if self._stop_requested:
                    return
                if (
                    self._cycle_reset_requested
                    or applied_generation != self._projection_generation
                ):
                    continue

            if self._backend.poll():
                last_completed_id = playing_id
                playing_id = None

    def _record_cleanup_failure(
        self,
        context: _WorkerContext,
        *,
        description: str,
        error: Exception,
    ) -> None:
        context.cleanup_failed_steps.append(description)
        error_identity = id(error)
        if error_identity in context.observed_cleanup_error_ids:
            return
        context.observed_cleanup_error_ids.add(error_identity)
        context.cleanup_issues.append(
            _CleanupIssue(description=description, error=error)
        )

    def _attempt_backend_stop(self, context: _WorkerContext) -> None:
        if context.stop_completed:
            return
        if context.stop_attempts >= _MAX_BACKEND_STOP_ATTEMPTS:
            return

        context.stop_attempts += 1
        attempt = context.stop_attempts
        try:
            self._backend.stop()
        except Exception as error:
            self._record_cleanup_failure(
                context,
                description=(
                    f"speaker playback stop 실패 (attempt {attempt})"
                ),
                error=error,
            )
        else:
            context.stop_completed = True

    def _attempt_backend_close(self, context: _WorkerContext) -> None:
        while (
            not context.close_completed
            and context.close_attempts < _MAX_BACKEND_CLOSE_ATTEMPTS
        ):
            context.close_attempts += 1
            attempt = context.close_attempts
            try:
                self._backend.close()
            except Exception as error:
                self._record_cleanup_failure(
                    context,
                    description=(
                        f"audio backend close 실패 (attempt {attempt})"
                    ),
                    error=error,
                )
            else:
                context.close_completed = True

    def _shutdown_backend(
        self,
        *,
        context: _WorkerContext,
        stop_before_close: bool,
    ) -> _CleanupReport:
        if not context.backend_open_attempted:
            return _cleanup_report(context)
        if stop_before_close:
            self._attempt_backend_stop(context)
        self._attempt_backend_close(context)
        return _cleanup_report(context)

    def _record_startup_failure(
        self,
        *,
        primary_error: Exception,
        cleanup_report: _CleanupReport,
    ) -> None:
        initialization_error = SpeakerAdapterInitializationError(
            _cleanup_message(
                "speaker adapter startup에 실패했습니다.",
                cleanup_report,
            ),
            primary_error=primary_error,
            cleanup_errors=tuple(
                issue.error for issue in cleanup_report.issues
            ),
        )
        cleanup_error = _make_cleanup_error(
            cleanup_report,
            fallback_primary_error=primary_error,
        )
        with self._condition:
            self._startup_error = initialization_error
            if self._failure is None:
                self._failure = initialization_error
            self._cleanup_error = cleanup_error
            self._state = _LifecycleState.FAILED
            self._condition.notify_all()

    def _record_runtime_failure_and_cleanup(
        self,
        primary_error: Exception,
        *,
        context: _WorkerContext,
    ) -> None:
        context.observed_cleanup_error_ids.add(id(primary_error))
        with self._condition:
            self._state = _LifecycleState.FAILED
            self._stop_requested = True
            self._condition.notify_all()

        report = self._shutdown_backend(
            context=context,
            stop_before_close=True,
        )
        runtime_error = SpeakerAdapterRuntimeError(
            _cleanup_message(
                "speaker worker에서 terminal 오류가 발생했습니다.",
                report,
            ),
            primary_error=primary_error,
            cleanup_errors=tuple(issue.error for issue in report.issues),
        )
        cleanup_error = _make_cleanup_error(
            report,
            fallback_primary_error=primary_error,
        )
        with self._condition:
            if self._failure is None:
                self._failure = runtime_error
            if self._cleanup_error is None:
                self._cleanup_error = cleanup_error
            self._state = _LifecycleState.FAILED
            self._condition.notify_all()

    def _finish_requested_close(self, context: _WorkerContext) -> None:
        report = self._shutdown_backend(
            context=context,
            stop_before_close=True,
        )
        cleanup_error = _make_cleanup_error(report)
        with self._condition:
            self._cleanup_error = cleanup_error
            if cleanup_error is None:
                self._state = _LifecycleState.CLOSED
            else:
                self._failure = cleanup_error
                self._state = _LifecycleState.FAILED
            self._condition.notify_all()

    def _record_unexpected_worker_failure(
        self,
        error: Exception,
        *,
        context: _WorkerContext,
    ) -> None:
        startup_failure = not context.startup_completed
        context.observed_cleanup_error_ids.add(id(error))
        report = self._shutdown_backend(
            context=context,
            stop_before_close=not startup_failure,
        )

        if startup_failure:
            unexpected_failure: Exception = (
                SpeakerAdapterInitializationError(
                    _cleanup_message(
                        "speaker startup 중 예상하지 못한 오류가 "
                        "발생했습니다.",
                        report,
                    ),
                    primary_error=error,
                    cleanup_errors=tuple(
                        issue.error for issue in report.issues
                    ),
                )
            )
        else:
            unexpected_failure = SpeakerAdapterRuntimeError(
                _cleanup_message(
                    "speaker worker에서 예상하지 못한 terminal 오류가 "
                    "발생했습니다.",
                    report,
                ),
                primary_error=error,
                cleanup_errors=tuple(
                    issue.error for issue in report.issues
                ),
            )

        cleanup_error = _make_cleanup_error(
            report,
            fallback_primary_error=error,
        )
        with self._condition:
            if startup_failure and self._startup_error is None:
                assert isinstance(
                    unexpected_failure,
                    SpeakerAdapterInitializationError,
                )
                self._startup_error = unexpected_failure
            if self._failure is None:
                self._failure = unexpected_failure
            if self._cleanup_error is None and cleanup_error is not None:
                self._cleanup_error = cleanup_error
            self._state = _LifecycleState.FAILED
            self._stop_requested = True
            self._condition.notify_all()

        logger.error(
            "Jetson USB speaker worker가 예상하지 못한 오류로 종료됐습니다.",
            exc_info=(type(error), error, error.__traceback__),
        )

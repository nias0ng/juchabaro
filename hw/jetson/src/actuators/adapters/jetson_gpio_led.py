"""전체 actuator projection을 두 active-high 로컬 경고 LED로 실행한다.

장애인 전용 구역은 BOARD Pin 31, 전기차 충전 구역은 BOARD Pin 33을 사용한다.
단일 worker thread가 모든 GPIO 작업을 소유하며 ``apply_projection()``은 목표
projection만 교체하고 즉시 반환한다.

각 ID는 하나의 연속된 projection 활성 구간에서 최대 5초 동안만 점멸한다.
이 모듈은 zone, ToF 관측 또는 Incident 판단을 소유하지 않는다. 기본 점멸
주기는 실제 장치 검증 후 재조정해야 하는 provisional 값이다. lifecycle owner는
``open()``과 ``close()``를 직렬로 호출해야 한다.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from enum import Enum, auto
from numbers import Real
from threading import (
    Condition,
    Event,
    Thread,
    current_thread,
)
from typing import Protocol

from src.actuators.adapters.gpio_backend import (
    GpioBackend,
    JetsonGpioBackend,
)
from src.actuators.models import ActuatorCommand


logger = logging.getLogger(__name__)


DISABLED_ZONE_WARNING_LED_ID = "disabled_zone_warning_led"
EV_ZONE_WARNING_LED_ID = "ev_zone_warning_led"

DISABLED_ZONE_WARNING_LED_PIN = 31
EV_ZONE_WARNING_LED_PIN = 33

BLINK_ACTION = "BLINK"

# 실제 LED와 설치 환경에서 시인성을 검증한 뒤 재조정해야 하는 provisional 값이다.
DEFAULT_BLINK_ON_SECONDS = 0.3
DEFAULT_BLINK_OFF_SECONDS = 0.3
DEFAULT_WARNING_DURATION_SECONDS = 5.0

_PIN_BY_ACTUATOR_ID = {
    DISABLED_ZONE_WARNING_LED_ID: DISABLED_ZONE_WARNING_LED_PIN,
    EV_ZONE_WARNING_LED_ID: EV_ZONE_WARNING_LED_PIN,
}

_LED_PINS = (
    DISABLED_ZONE_WARNING_LED_PIN,
    EV_ZONE_WARNING_LED_PIN,
)

_LED_IDS = tuple(_PIN_BY_ACTUATOR_ID)


class LedAdapterError(RuntimeError):
    """경고 LED adapter 공통 오류."""


class _TerminalLedAdapterError(LedAdapterError):
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


class LedAdapterInitializationError(_TerminalLedAdapterError):
    """GPIO 또는 worker 초기화 실패."""


class LedAdapterStateError(LedAdapterError):
    """현재 생명주기에서 허용되지 않는 작업."""


class InvalidActuatorProjectionError(LedAdapterError):
    """지원하지 않거나 모호한 command projection."""


class LedAdapterRuntimeError(_TerminalLedAdapterError):
    """점멸 중 발생한 terminal GPIO 오류."""


class LedAdapterCleanupError(_TerminalLedAdapterError):
    """LOW 또는 GPIO cleanup 실패."""


class BlinkScheduler(Protocol):
    """Worker의 monotonic clock과 condition wait 경계."""

    def monotonic(self) -> float:
        """현재 monotonic 시간을 반환한다."""

    def wait(
        self,
        condition: Condition,
        timeout: float | None,
    ) -> None:
        """notification 또는 timeout까지 대기한다."""


class ThreadingBlinkScheduler:
    """threading과 monotonic clock을 사용하는 production scheduler."""

    def monotonic(self) -> float:
        return time.monotonic()

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


@dataclass
class _ActiveBlink:
    phase_high: bool
    next_toggle_at: float
    expires_at: float


def _positive_finite_number(
    value: object,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 양수여야 합니다."
        )

    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 양수여야 합니다."
        ) from exc

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
            raise InvalidActuatorProjectionError(
                "projection의 모든 항목은 ActuatorCommand여야 합니다."
            )
        if command.actuator_id not in _PIN_BY_ACTUATOR_ID:
            raise InvalidActuatorProjectionError(
                "지원하지 않는 actuator_id입니다: "
                f"{command.actuator_id!r}"
            )
        if command.action != BLINK_ACTION:
            raise InvalidActuatorProjectionError(
                "지원하지 않는 경고 LED action입니다: "
                f"{command.action!r}"
            )
        if command.actuator_id in desired_ids:
            raise InvalidActuatorProjectionError(
                "동일 actuator_id가 projection에 중복되었습니다: "
                f"{command.actuator_id!r}"
            )
        desired_ids.add(command.actuator_id)

    return frozenset(desired_ids)


def _ordered_led_ids(
    actuator_ids: frozenset[str],
) -> tuple[str, ...]:
    return tuple(
        actuator_id
        for actuator_id in _LED_IDS
        if actuator_id in actuator_ids
    )


def _cleanup_message(
    prefix: str,
    issues: tuple[_CleanupIssue, ...],
) -> str:
    if not issues:
        return prefix
    return (
        prefix
        + " "
        + "; ".join(
            f"{issue.description}: {issue.error}"
            for issue in issues
        )
    )


def _make_cleanup_error(
    issues: tuple[_CleanupIssue, ...],
) -> LedAdapterCleanupError | None:
    if not issues:
        return None

    return LedAdapterCleanupError(
        _cleanup_message(
            "경고 LED fail-safe 또는 GPIO cleanup에 실패했습니다.",
            issues,
        ),
        primary_error=issues[0].error,
        cleanup_errors=tuple(issue.error for issue in issues),
    )


class JetsonGpioLedAdapter:
    """각 projection 활성 구간의 경고 LED를 제한 시간 동안 점멸한다."""

    def __init__(
        self,
        *,
        backend: GpioBackend | None = None,
        blink_on_seconds: float = DEFAULT_BLINK_ON_SECONDS,
        blink_off_seconds: float = DEFAULT_BLINK_OFF_SECONDS,
        warning_duration_seconds: float = DEFAULT_WARNING_DURATION_SECONDS,
        scheduler: BlinkScheduler | None = None,
    ) -> None:
        self._blink_on_seconds = _positive_finite_number(
            blink_on_seconds,
            field_name="blink_on_seconds",
        )
        self._blink_off_seconds = _positive_finite_number(
            blink_off_seconds,
            field_name="blink_off_seconds",
        )
        self._warning_duration_seconds = _positive_finite_number(
            warning_duration_seconds,
            field_name="warning_duration_seconds",
        )

        self._backend = (
            JetsonGpioBackend()
            if backend is None
            else backend
        )
        active_scheduler = (
            ThreadingBlinkScheduler()
            if scheduler is None
            else scheduler
        )
        if not callable(
            getattr(active_scheduler, "monotonic", None)
        ):
            raise ValueError(
                "scheduler.monotonic은 callable이어야 합니다."
            )
        if not callable(
            getattr(active_scheduler, "wait", None)
        ):
            raise ValueError(
                "scheduler.wait는 callable이어야 합니다."
            )
        self._scheduler = active_scheduler

        self._condition = Condition()
        self._state = _LifecycleState.NEW

        self._desired_blink_ids: frozenset[str] = frozenset()
        self._activation_generation_by_id = {
            actuator_id: 0 for actuator_id in _LED_IDS
        }
        self._projection_generation = 0

        self._thread: Thread | None = None
        self._startup_complete = Event()
        self._startup_error: LedAdapterInitializationError | None = None

        self._stop_requested = False
        self._failure: Exception | None = None
        self._cleanup_error: LedAdapterCleanupError | None = None

    @property
    def failure(self) -> Exception | None:
        """최초 startup 또는 background terminal 오류."""

        with self._condition:
            return self._failure

    @property
    def is_running(self) -> bool:
        """worker thread가 살아 있는지 반환한다."""

        with self._condition:
            return (
                self._thread is not None
                and self._thread.is_alive()
            )

    def open(self) -> None:
        """Worker에서 GPIO를 초기화하고 startup 결과를 기다린다."""

        with self._condition:
            if self._state is _LifecycleState.OPEN:
                return
            if self._state is not _LifecycleState.NEW:
                raise LedAdapterStateError(
                    "현재 상태에서는 경고 LED adapter를 열 수 없습니다: "
                    f"{self._state.name}"
                )

            self._state = _LifecycleState.OPENING
            thread = Thread(
                target=self._run,
                name="jetson-warning-led",
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception as error:
                initialization_error = LedAdapterInitializationError(
                    "경고 LED worker를 시작할 수 없습니다.",
                    primary_error=error,
                )
                self._thread = None
                self._state = _LifecycleState.FAILED
                self._startup_error = initialization_error
                self._failure = initialization_error
                self._startup_complete.set()
                raise initialization_error from error

        self._startup_complete.wait()

        with self._condition:
            startup_error = self._startup_error
            thread = self._thread

        if startup_error is not None:
            if thread is not None:
                thread.join()
            raise startup_error from startup_error.primary_error

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        """검증된 전체 projection을 worker의 새 목표로 교체한다."""

        with self._condition:
            if self._state is not _LifecycleState.OPEN:
                raise LedAdapterStateError(
                    "열린 경고 LED adapter에만 projection을 "
                    f"적용할 수 있습니다: {self._state.name}"
                )

        desired_blink_ids = _decode_projection(commands)

        with self._condition:
            if self._state is not _LifecycleState.OPEN:
                raise LedAdapterStateError(
                    "projection 검증 중 경고 LED adapter 상태가 "
                    f"변경되었습니다: {self._state.name}"
                )
            if desired_blink_ids == self._desired_blink_ids:
                return

            added_ids = desired_blink_ids - self._desired_blink_ids
            for actuator_id in added_ids:
                self._activation_generation_by_id[actuator_id] += 1
            self._desired_blink_ids = desired_blink_ids
            self._projection_generation += 1
            self._condition.notify_all()

    def close(self) -> None:
        """점멸을 멈추고 LOW, cleanup, worker 종료를 기다린다."""

        with self._condition:
            if self._state is _LifecycleState.NEW:
                return
            if self._state is _LifecycleState.CLOSED:
                return
            if self._state is _LifecycleState.OPENING:
                raise LedAdapterStateError(
                    "open() 진행 중에는 close()를 호출할 수 없습니다."
                )

            thread = self._thread
            if self._state is _LifecycleState.OPEN:
                self._state = _LifecycleState.CLOSING
                self._stop_requested = True
                if self._desired_blink_ids:
                    self._desired_blink_ids = frozenset()
                    self._projection_generation += 1
                self._condition.notify_all()
            elif self._state is _LifecycleState.CLOSING:
                pass
            elif self._state is _LifecycleState.FAILED:
                self._stop_requested = True
                self._condition.notify_all()
            else:
                raise LedAdapterStateError(
                    "현재 상태에서는 close()를 호출할 수 없습니다: "
                    f"{self._state.name}"
                )

        if thread is current_thread():
            raise LedAdapterStateError(
                "경고 LED worker thread는 자신을 join할 수 없습니다."
            )
        if thread is not None:
            thread.join()

        with self._condition:
            cleanup_error = self._cleanup_error

        if cleanup_error is not None:
            raise cleanup_error from cleanup_error.primary_error

    def _run(self) -> None:
        backend_opened = False
        setup_attempted_pins: list[int] = []
        configured_pins: list[int] = []

        try:
            try:
                self._backend.open()
                backend_opened = True

                for pin in _LED_PINS:
                    setup_attempted_pins.append(pin)
                    self._backend.setup_output(
                        pin,
                        initial_high=False,
                    )
                    configured_pins.append(pin)
            except Exception as error:
                issues = self._shutdown_backend(
                    backend_opened=backend_opened,
                    setup_attempted_pins=tuple(
                        setup_attempted_pins
                    ),
                    configured_pins=tuple(configured_pins),
                )
                initialization_error = LedAdapterInitializationError(
                    _cleanup_message(
                        "경고 LED GPIO 초기화에 실패했습니다.",
                        issues,
                    ),
                    primary_error=error,
                    cleanup_errors=tuple(
                        issue.error for issue in issues
                    ),
                )
                cleanup_error = _make_cleanup_error(issues)
                with self._condition:
                    self._startup_error = initialization_error
                    self._failure = initialization_error
                    self._cleanup_error = cleanup_error
                    self._state = _LifecycleState.FAILED
                return

            with self._condition:
                self._state = _LifecycleState.OPEN
            self._startup_complete.set()

            try:
                self._blink_loop()
            except Exception as error:
                issues = self._shutdown_backend(
                    backend_opened=True,
                    setup_attempted_pins=tuple(
                        setup_attempted_pins
                    ),
                    configured_pins=tuple(configured_pins),
                )
                runtime_error = LedAdapterRuntimeError(
                    _cleanup_message(
                        "경고 LED 점멸 중 terminal 오류가 발생했습니다.",
                        issues,
                    ),
                    primary_error=error,
                    cleanup_errors=tuple(
                        issue.error for issue in issues
                    ),
                )
                cleanup_error = _make_cleanup_error(issues)
                with self._condition:
                    self._failure = runtime_error
                    self._cleanup_error = cleanup_error
                    self._state = _LifecycleState.FAILED
                    self._condition.notify_all()
                logger.exception(
                    "Jetson 경고 LED worker가 terminal 오류로 종료됐습니다."
                )
                return

            issues = self._shutdown_backend(
                backend_opened=True,
                setup_attempted_pins=tuple(
                    setup_attempted_pins
                ),
                configured_pins=tuple(configured_pins),
            )
            cleanup_error = _make_cleanup_error(issues)
            with self._condition:
                self._cleanup_error = cleanup_error
                if cleanup_error is None:
                    self._state = _LifecycleState.CLOSED
                else:
                    self._failure = cleanup_error
                    self._state = _LifecycleState.FAILED
                self._condition.notify_all()
        finally:
            self._startup_complete.set()

    def _blink_loop(self) -> None:
        applied_generation = 0
        applied_activation_by_id: dict[str, int] = {}
        active_blinks: dict[str, _ActiveBlink] = {}

        while True:
            with self._condition:
                while True:
                    if self._stop_requested:
                        return

                    if (
                        applied_generation
                        != self._projection_generation
                    ):
                        operation = "reconcile"
                        break

                    next_deadline = min(
                        (
                            min(blink.next_toggle_at, blink.expires_at)
                            for blink in active_blinks.values()
                        ),
                        default=None,
                    )
                    now = self._scheduler.monotonic()
                    if next_deadline is not None and now >= next_deadline:
                        operation = "tick"
                        break

                    timeout = (
                        None
                        if next_deadline is None
                        else max(0.0, next_deadline - now)
                    )
                    self._scheduler.wait(
                        self._condition,
                        timeout,
                    )

                desired_blink_ids = self._desired_blink_ids
                desired_activation_by_id = {
                    actuator_id: self._activation_generation_by_id[actuator_id]
                    for actuator_id in desired_blink_ids
                }
                desired_generation = self._projection_generation

            if operation == "reconcile":
                if self._stop_is_requested():
                    return

                removed_ids = frozenset(
                    actuator_id
                    for actuator_id, activation_generation
                    in applied_activation_by_id.items()
                    if desired_activation_by_id.get(actuator_id)
                    != activation_generation
                )
                added_ids = frozenset(
                    actuator_id
                    for actuator_id, activation_generation
                    in desired_activation_by_id.items()
                    if applied_activation_by_id.get(actuator_id)
                    != activation_generation
                )

                for actuator_id in _ordered_led_ids(removed_ids):
                    self._backend.write(
                        _PIN_BY_ACTUATOR_ID[actuator_id],
                        high=False,
                    )
                    active_blinks.pop(actuator_id, None)

                now = self._scheduler.monotonic()
                for actuator_id in _ordered_led_ids(added_ids):
                    if self._stop_is_requested():
                        return
                    self._backend.write(
                        _PIN_BY_ACTUATOR_ID[actuator_id],
                        high=True,
                    )
                    active_blinks[actuator_id] = _ActiveBlink(
                        phase_high=True,
                        next_toggle_at=now + self._blink_on_seconds,
                        expires_at=now + self._warning_duration_seconds,
                    )

                applied_activation_by_id = desired_activation_by_id
                applied_generation = desired_generation
                continue

            with self._condition:
                if self._stop_requested:
                    return
                if (
                    applied_generation
                    != self._projection_generation
                ):
                    continue

            now = self._scheduler.monotonic()
            for actuator_id in _ordered_led_ids(
                frozenset(active_blinks)
            ):
                blink = active_blinks[actuator_id]
                if now >= blink.expires_at:
                    self._backend.write(
                        _PIN_BY_ACTUATOR_ID[actuator_id],
                        high=False,
                    )
                    del active_blinks[actuator_id]
                    continue
                if now < blink.next_toggle_at:
                    continue

                next_phase_high = not blink.phase_high
                if next_phase_high and self._stop_is_requested():
                    return
                self._backend.write(
                    _PIN_BY_ACTUATOR_ID[actuator_id],
                    high=next_phase_high,
                )
                blink.phase_high = next_phase_high
                blink.next_toggle_at = now + (
                    self._blink_on_seconds
                    if next_phase_high
                    else self._blink_off_seconds
                )

    def _stop_is_requested(self) -> bool:
        with self._condition:
            return self._stop_requested

    def _shutdown_backend(
        self,
        *,
        backend_opened: bool,
        setup_attempted_pins: tuple[int, ...],
        configured_pins: tuple[int, ...],
    ) -> tuple[_CleanupIssue, ...]:
        if not backend_opened:
            return ()

        issues: list[_CleanupIssue] = []

        for pin in configured_pins:
            try:
                self._backend.write(pin, high=False)
            except Exception as error:
                issues.append(
                    _CleanupIssue(
                        description=(
                            f"BOARD Pin {pin} LOW 전환 실패; "
                            "실제 출력 상태가 불확실함"
                        ),
                        error=error,
                    )
                )

        if setup_attempted_pins:
            try:
                self._backend.cleanup(
                    setup_attempted_pins
                )
            except Exception as error:
                issues.append(
                    _CleanupIssue(
                        description="GPIO 지정 핀 cleanup 실패",
                        error=error,
                    )
                )

        return tuple(issues)

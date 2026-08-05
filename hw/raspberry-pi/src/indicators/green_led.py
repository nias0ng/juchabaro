"""
입차 허용 초록 LED의 GPIO 제어와 자원 생명주기를 관리한다.

LED 출력의 논리 극성에 따라 ON과 OFF 레벨을 결정하고, 동기 방식의 허용
표시와 핀 단위 cleanup을 제공한다. Backend 판정과 입차 허용 정책은
담당하지 않는다.
"""

import math
import time
from collections.abc import Callable
from typing import Any

import RPi.GPIO as GPIO

from src.config.settings import (
    GPIO_MODE,
    GREEN_LED_ACTIVE_HIGH,
    GREEN_LED_PIN,
)


class GreenLed:
    """입차 허용 초록 LED를 초기화하고 동기 방식으로 제어한다."""

    def __init__(
        self,
        gpio: Any = GPIO,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._gpio = gpio
        self._sleep = sleep

        self._ready = False
        self._cleanup_required = False
        self._cleaned = False

        self._validate_settings()

        try:
            self._initialize_gpio()
        except BaseException as initialization_error:
            cleanup_failure = self._cleanup_after_initialization_failure()
            if cleanup_failure is not None:
                initialization_error.add_note(
                    "LED 초기화 실패 후 GPIO 자원 정리도 실패했습니다. "
                    f"pin={GREEN_LED_PIN} "
                    f"cleanup_error={cleanup_failure!r}"
                )
            raise

    @staticmethod
    def _validate_settings() -> None:
        """LED GPIO 설정값의 타입과 범위를 검증한다."""

        if GPIO_MODE != "BCM":
            raise ValueError("GPIO_MODE는 BCM이어야 합니다.")

        if (
            isinstance(GREEN_LED_PIN, bool)
            or not isinstance(GREEN_LED_PIN, int)
            or GREEN_LED_PIN < 0
        ):
            raise ValueError(
                "GREEN_LED_PIN은 0 이상의 정수여야 합니다."
            )

        if not isinstance(GREEN_LED_ACTIVE_HIGH, bool):
            raise ValueError(
                "GREEN_LED_ACTIVE_HIGH는 bool이어야 합니다."
            )

    def _initialize_gpio(self) -> None:
        """LED 핀을 출력으로 설정하고 초기 상태를 OFF로 만든다."""

        gpio_mode = getattr(self._gpio, GPIO_MODE, None)
        if gpio_mode is None:
            raise ValueError(
                f"지원하지 않는 GPIO 모드입니다: {GPIO_MODE}"
            )

        if GREEN_LED_ACTIVE_HIGH:
            self._on_level = self._gpio.HIGH
            self._off_level = self._gpio.LOW
        else:
            self._on_level = self._gpio.LOW
            self._off_level = self._gpio.HIGH

        self._gpio.setmode(gpio_mode)

        # setup이 일부만 수행된 경우에도 해당 핀의 cleanup을 시도한다.
        self._cleanup_required = True
        self._gpio.setup(GREEN_LED_PIN, self._gpio.OUT)
        self._gpio.output(GREEN_LED_PIN, self._off_level)
        self._ready = True

    def turn_on(self) -> None:
        """논리 극성에 맞는 출력 레벨로 LED를 켠다."""

        self._require_ready()
        self._gpio.output(GREEN_LED_PIN, self._on_level)

    def turn_off(self) -> None:
        """논리 극성에 맞는 출력 레벨로 LED를 끈다."""

        self._require_ready()
        self._gpio.output(GREEN_LED_PIN, self._off_level)

    def indicate_allow(self, duration_seconds: float) -> None:
        """
        LED를 지정된 시간 동안 동기 방식으로 켰다가 끈다.

        점등 또는 대기 중 예외가 발생하더라도 OFF 출력을 시도한다.
        """

        self._require_ready()
        self._validate_duration(duration_seconds)

        try:
            self.turn_on()
            self._sleep(duration_seconds)
        except BaseException as operation_error:
            try:
                self.turn_off()
            except BaseException as off_error:
                operation_error.add_note(
                    "LED 허용 표시 실패 후 OFF 출력도 실패했습니다: "
                    f"{off_error!r}"
                )
            raise

        self.turn_off()

    @staticmethod
    def _validate_duration(duration_seconds: float) -> None:
        """점등 시간이 양의 유한한 수인지 검증한다."""

        if (
            isinstance(duration_seconds, bool)
            or not isinstance(duration_seconds, (int, float))
            or not math.isfinite(duration_seconds)
            or duration_seconds <= 0
        ):
            raise ValueError(
                "LED 점등 시간은 0보다 큰 유한한 수여야 합니다."
            )

    def _require_ready(self) -> None:
        """현재 객체가 LED를 제어할 수 있는 상태인지 확인한다."""

        if self._cleaned:
            raise RuntimeError(
                "이미 정리된 LED는 다시 사용할 수 없습니다."
            )

        if not self._ready:
            raise RuntimeError(
                "LED가 제어 가능한 상태가 아닙니다."
            )

    def cleanup(self) -> None:
        """
        LED를 끈 뒤 이 객체가 사용하는 GPIO 핀만 해제한다.

        OFF 실패 여부와 관계없이 핀 cleanup을 시도한다. 핀 cleanup이
        실패하면 다음 호출에서 다시 시도하며, 완료된 cleanup은 반복하지
        않는다.
        """

        if self._cleaned:
            return

        self._ready = False

        if not self._cleanup_required:
            self._cleaned = True
            return

        try:
            self._gpio.output(GREEN_LED_PIN, self._off_level)
        finally:
            self._gpio.cleanup(GREEN_LED_PIN)
            self._cleanup_required = False
            self._cleaned = True

    def _cleanup_after_initialization_failure(
        self,
    ) -> BaseException | None:
        """
        부분 초기화된 LED 자원을 정리하고 정리 실패를 반환한다.

        최초 초기화 예외가 cleanup 예외에 의해 가려지지 않게 한다.
        """

        try:
            self.cleanup()
        except BaseException as cleanup_failure:
            return cleanup_failure

        return None

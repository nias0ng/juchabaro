import math
import time
from collections.abc import Callable
from typing import Any

import RPi.GPIO as GPIO

from src.config.settings import (
    ECHO_PIN,
    ECHO_TIMEOUT_SECONDS,
    GPIO_MODE,
    MAX_VALID_DISTANCE_CM,
    MIN_VALID_DISTANCE_CM,
    SOUND_SPEED_CM_PER_SECOND,
    STABILIZATION_SECONDS,
    TRIGGER_PIN,
    TRIGGER_PULSE_SECONDS,
)


class UltrasonicSensor:
    """HC-SR04를 사용해 단일 거리값을 측정한다."""

    def __init__(
        self,
        gpio: Any = GPIO,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._gpio = gpio
        self._monotonic = monotonic
        self._sleep = sleep

        self._validate_settings()
        self._initialize_gpio()

    @staticmethod
    def _validate_settings() -> None:
        if GPIO_MODE != "BCM":
            raise ValueError("GPIO_MODE는 BCM이어야 합니다.")
        if TRIGGER_PIN == ECHO_PIN:
            raise ValueError("Trigger 핀과 Echo 핀은 서로 달라야 합니다.")
        if TRIGGER_PULSE_SECONDS <= 0:
            raise ValueError("Trigger pulse는 0보다 커야 합니다.")
        if STABILIZATION_SECONDS <= 0:
            raise ValueError("안정화 시간은 0보다 커야 합니다.")
        if ECHO_TIMEOUT_SECONDS <= 0:
            raise ValueError("Echo timeout은 0보다 커야 합니다.")
        if SOUND_SPEED_CM_PER_SECOND <= 0:
            raise ValueError("음속은 0보다 커야 합니다.")
        if MIN_VALID_DISTANCE_CM >= MAX_VALID_DISTANCE_CM:
            raise ValueError("최소 유효 거리는 최대 유효 거리보다 작아야 합니다.")

    def _initialize_gpio(self) -> None:
        gpio_mode = getattr(self._gpio, GPIO_MODE, None)
        if gpio_mode is None:
            raise ValueError(f"지원하지 않는 GPIO 모드입니다: {GPIO_MODE}")

        self._gpio.setmode(gpio_mode)
        self._gpio.setup(TRIGGER_PIN, self._gpio.OUT)
        self._gpio.setup(ECHO_PIN, self._gpio.IN)
        self._gpio.output(TRIGGER_PIN, self._gpio.LOW)
        self._sleep(STABILIZATION_SECONDS)

    def measure(self) -> float | None:
        """한 번 측정한 거리(cm)를 반환하고, 측정 실패 시 None을 반환한다."""

        self._send_trigger_pulse()

        echo_started_at = self._wait_for_echo_level(self._gpio.HIGH)
        if echo_started_at is None:
            return None

        echo_ended_at = self._wait_for_echo_level(self._gpio.LOW)
        if echo_ended_at is None:
            return None

        try:
            elapsed_seconds = echo_ended_at - echo_started_at
            distance_cm = elapsed_seconds * SOUND_SPEED_CM_PER_SECOND / 2
        except TypeError:
            return None

        if not math.isfinite(distance_cm):
            return None
        if not MIN_VALID_DISTANCE_CM <= distance_cm <= MAX_VALID_DISTANCE_CM:
            return None

        return distance_cm

    def _send_trigger_pulse(self) -> None:
        self._gpio.output(TRIGGER_PIN, self._gpio.HIGH)
        try:
            self._sleep(TRIGGER_PULSE_SECONDS)
        finally:
            self._gpio.output(TRIGGER_PIN, self._gpio.LOW)

    def _wait_for_echo_level(self, expected_level: int) -> float | None:
        deadline = self._monotonic() + ECHO_TIMEOUT_SECONDS

        while self._gpio.input(ECHO_PIN) != expected_level:
            if self._monotonic() >= deadline:
                return None

        return self._monotonic()

    def cleanup(self) -> None:
        """이 센서가 사용하는 GPIO 자원만 정리한다."""

        self._gpio.cleanup((TRIGGER_PIN, ECHO_PIN))

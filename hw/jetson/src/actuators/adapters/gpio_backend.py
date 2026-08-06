"""BOARD 물리 핀 번호를 사용하는 Jetson GPIO 출력 경계.

Jetson.GPIO는 ``open()``에서 지연 import한다. 이 모듈은 LED 의미,
command projection 또는 점멸 정책을 소유하지 않는다.

이 구현은 thread-safe를 보장하지 않는다. 하나의 owner가 생명주기 메서드와
GPIO 작업을 직렬로 호출해야 한다.
"""

from __future__ import annotations

from typing import Any, Protocol


class GpioBackendError(RuntimeError):
    """GPIO backend 공통 오류."""


class GpioBackendInitializationError(GpioBackendError):
    """GPIO 의존성 로드 또는 numbering mode 설정 실패."""


class GpioBackendStateError(GpioBackendError):
    """open되지 않은 backend 사용 오류."""


class GpioBackend(Protocol):
    """BOARD 물리 핀 번호로 GPIO 출력을 제어하는 최소 계약.

    ``pin``은 BCM 또는 SoC 번호가 아니라 40-pin header의 BOARD 물리 핀
    번호다. 구현은 ``open()`` 전에 setup, write 또는 cleanup을 요청받으면
    ``GpioBackendStateError``를 발생시켜야 한다.
    """

    def open(self) -> None:
        """GPIO 의존성을 준비하고 BOARD numbering mode를 설정한다."""

    def setup_output(
        self,
        pin: int,
        *,
        initial_high: bool,
    ) -> None:
        """지정 BOARD 핀을 초기 출력값과 함께 output으로 설정한다."""

    def write(
        self,
        pin: int,
        *,
        high: bool,
    ) -> None:
        """지정 BOARD 핀에 HIGH 또는 LOW를 출력한다."""

    def cleanup(
        self,
        pins: tuple[int, ...],
    ) -> None:
        """전달받은 BOARD 핀만 정리하며 backend의 열린 상태는 유지한다."""


def _load_jetson_gpio() -> Any:
    try:
        import Jetson.GPIO as GPIO
    except ImportError as exc:
        missing_dependency = getattr(exc, "name", None) or "unknown"
        raise GpioBackendInitializationError(
            "Jetson GPIO 의존성을 import할 수 없습니다: "
            f"{missing_dependency}"
        ) from exc

    return GPIO


def _require_board_pin(pin: object) -> int:
    if (
        isinstance(pin, bool)
        or not isinstance(pin, int)
        or not 1 <= pin <= 40
    ):
        raise ValueError(
            "pin은 1 이상 40 이하의 BOARD 물리 핀 정수여야 합니다."
        )
    return pin


def _require_bool(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name}은 bool이어야 합니다.")
    return value


class JetsonGpioBackend:
    """Jetson.GPIO에 대한 지연 초기화 방식의 얇은 출력 경계.

    ``open()``은 반복 호출에 안전하며 초기화 실패 후 재시도할 수 있다.
    setup, output, cleanup 중 Jetson.GPIO가 발생시킨 예외는 변환하지 않는다.
    cleanup 성공은 backend 전체가 닫혔다는 의미가 아니다.
    """

    def __init__(self) -> None:
        self._gpio: Any | None = None
        self._is_open = False

    def open(self) -> None:
        """Jetson.GPIO를 로드하고 BOARD numbering mode를 설정한다."""

        if self._is_open:
            return

        gpio = _load_jetson_gpio()
        try:
            gpio.setmode(gpio.BOARD)
        except Exception as exc:
            raise GpioBackendInitializationError(
                "Jetson GPIO BOARD numbering mode 설정에 실패했습니다."
            ) from exc

        self._gpio = gpio
        self._is_open = True

    def setup_output(
        self,
        pin: int,
        *,
        initial_high: bool,
    ) -> None:
        """지정 BOARD 핀을 초기 출력값과 함께 output으로 설정한다."""

        gpio = self._require_open_gpio()
        board_pin = _require_board_pin(pin)
        normalized_initial_high = _require_bool(
            initial_high,
            "initial_high",
        )
        level = (
            gpio.HIGH
            if normalized_initial_high
            else gpio.LOW
        )
        gpio.setup(
            board_pin,
            gpio.OUT,
            initial=level,
        )

    def write(
        self,
        pin: int,
        *,
        high: bool,
    ) -> None:
        """지정 BOARD 핀에 HIGH 또는 LOW를 출력한다."""

        gpio = self._require_open_gpio()
        board_pin = _require_board_pin(pin)
        normalized_high = _require_bool(high, "high")
        level = gpio.HIGH if normalized_high else gpio.LOW
        gpio.output(board_pin, level)

    def cleanup(
        self,
        pins: tuple[int, ...],
    ) -> None:
        """전달받은 BOARD 핀만 정리하고 열린 상태를 유지한다."""

        gpio = self._require_open_gpio()
        board_pins = tuple(
            _require_board_pin(pin)
            for pin in pins
        )
        if not board_pins:
            return

        gpio.cleanup(board_pins)

    def _require_open_gpio(self) -> Any:
        if not self._is_open or self._gpio is None:
            raise GpioBackendStateError(
                "GPIO backend가 열리지 않았습니다. "
                "open()을 먼저 호출하세요."
            )
        return self._gpio

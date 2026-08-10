#!/usr/bin/env python3
"""실제 Jetson에서 두 경고 LED의 점멸과 GPIO 정리를 수동 확인한다.

기존 ``JetsonGpioLedAdapter``의 공개 projection API만 사용해 장애인 구역 LED,
전기차 구역 LED 및 두 LED 동시 점멸을 제한된 시간 동안 확인한다. GPIO backend,
점멸 loop, zone·Incident 판단 또는 운영 경고 정책은 소유하지 않는다.

실행 예:

    cd hw/jetson
    python -m scripts.check_warning_led
    python -m scripts.check_warning_led \
        --stage-seconds 3.0 \
        --off-seconds 1.0 \
        --blink-on-seconds 0.3 \
        --blink-off-seconds 0.3

CLI 기본값은 수동 하드웨어 진단 편의값이며 운영 경고 정책이 아니다.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Protocol

from src.actuators.adapters.jetson_gpio_led import (
    BLINK_ACTION,
    DEFAULT_BLINK_OFF_SECONDS,
    DEFAULT_BLINK_ON_SECONDS,
    DISABLED_ZONE_WARNING_LED_ID,
    DISABLED_ZONE_WARNING_LED_PIN,
    EV_ZONE_WARNING_LED_ID,
    EV_ZONE_WARNING_LED_PIN,
    JetsonGpioLedAdapter,
)
from src.actuators.models import ActuatorCommand


DEFAULT_STAGE_SECONDS = 3.0
DEFAULT_OFF_SECONDS = 1.0
DIAGNOSTIC_REASON = "MANUAL_HARDWARE_DIAGNOSTIC"


class WarningLedDiagnosticAdapter(Protocol):
    """진단 스크립트가 사용하는 경고 LED adapter 최소 계약."""

    @property
    def failure(self) -> Exception | None:
        """최초 startup 또는 background terminal 오류."""

    def open(self) -> None:
        """GPIO와 worker를 초기화한다."""

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        """전체 현재 경고 LED projection을 적용한다."""

    def close(self) -> None:
        """LED를 LOW로 전환하고 GPIO를 정리한다."""


class _BackgroundFailureDetected(RuntimeError):
    """Background worker의 terminal 오류가 확인된 진단 실패."""

    def __init__(self, failure: Exception) -> None:
        super().__init__(
            f"경고 LED background worker가 실패했습니다: {failure}"
        )
        self.failure = failure
        self.__cause__ = failure


def _positive_finite_float(value: str) -> float:
    try:
        parsed_value = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "bool이 아닌 유한한 양수여야 합니다."
        ) from exc

    if not math.isfinite(parsed_value) or parsed_value <= 0:
        raise argparse.ArgumentTypeError(
            "bool이 아닌 유한한 양수여야 합니다."
        )
    return parsed_value


def _non_negative_finite_float(value: str) -> float:
    try:
        parsed_value = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "bool이 아닌 유한한 0 이상의 숫자여야 합니다."
        ) from exc

    if not math.isfinite(parsed_value) or parsed_value < 0:
        raise argparse.ArgumentTypeError(
            "bool이 아닌 유한한 0 이상의 숫자여야 합니다."
        )
    return parsed_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--stage-seconds",
        type=_positive_finite_float,
        default=DEFAULT_STAGE_SECONDS,
        help=(
            "각 점멸 단계를 유지하는 시간(초). 기본값 3.0은 "
            "수동 진단 편의값이다."
        ),
    )
    parser.add_argument(
        "--off-seconds",
        type=_non_negative_finite_float,
        default=DEFAULT_OFF_SECONDS,
        help=(
            "점멸 단계 사이 두 LED를 끄고 확인하는 시간(초). "
            "기본값 1.0은 수동 진단 편의값이다."
        ),
    )
    parser.add_argument(
        "--blink-on-seconds",
        type=_positive_finite_float,
        default=DEFAULT_BLINK_ON_SECONDS,
        help=(
            "LED HIGH phase 시간(초). 기본값 0.3은 실제 장치에서 "
            "재조정할 provisional 진단값이다."
        ),
    )
    parser.add_argument(
        "--blink-off-seconds",
        type=_positive_finite_float,
        default=DEFAULT_BLINK_OFF_SECONDS,
        help=(
            "LED LOW phase 시간(초). 기본값 0.3은 실제 장치에서 "
            "재조정할 provisional 진단값이다."
        ),
    )
    return parser


def build_adapter(
    *,
    blink_on_seconds: float,
    blink_off_seconds: float,
) -> WarningLedDiagnosticAdapter:
    """기존 경고 LED adapter를 수동 진단 설정으로 생성한다."""

    return JetsonGpioLedAdapter(
        blink_on_seconds=blink_on_seconds,
        blink_off_seconds=blink_off_seconds,
    )


def _command(actuator_id: str) -> ActuatorCommand:
    return ActuatorCommand(
        actuator_id=actuator_id,
        action=BLINK_ACTION,
        reason=DIAGNOSTIC_REASON,
        requested_at=datetime.now(timezone.utc),
    )


def _raise_if_background_failed(
    adapter: WarningLedDiagnosticAdapter,
) -> None:
    failure = adapter.failure
    if failure is not None:
        raise _BackgroundFailureDetected(failure)


def _sleep_if_positive(
    seconds: float,
    *,
    sleep: Callable[[float], None],
) -> None:
    if seconds > 0:
        sleep(seconds)


def run(
    *,
    adapter: WarningLedDiagnosticAdapter,
    stage_seconds: float,
    off_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """경고 LED 세 단계를 실행하고 background 오류와 cleanup을 확인한다."""

    exit_code = 0
    phase = "초기화"
    reported_errors: list[BaseException] = []

    def was_reported(error: BaseException) -> bool:
        return any(
            error is reported_error
            for reported_error in reported_errors
        )

    try:
        adapter.open()
        print(
            "경고 LED 초기화 성공: "
            f"BOARD Pin {DISABLED_ZONE_WARNING_LED_PIN}·"
            f"{EV_ZONE_WARNING_LED_PIN} LOW"
        )

        phase = "장애인 전용 구역 LED 점멸"
        adapter.apply_projection(
            (_command(DISABLED_ZONE_WARNING_LED_ID),)
        )
        print(
            "[1/3] 장애인 전용 구역 LED 점멸: "
            f"{DISABLED_ZONE_WARNING_LED_ID} / "
            f"BOARD Pin {DISABLED_ZONE_WARNING_LED_PIN}"
        )
        sleep(stage_seconds)
        _raise_if_background_failed(adapter)

        phase = "첫 번째 OFF"
        adapter.apply_projection(())
        print("[OFF] 두 LED LOW")
        _sleep_if_positive(off_seconds, sleep=sleep)
        _raise_if_background_failed(adapter)

        phase = "전기차 충전 구역 LED 점멸"
        adapter.apply_projection(
            (_command(EV_ZONE_WARNING_LED_ID),)
        )
        print(
            "[2/3] 전기차 충전 구역 LED 점멸: "
            f"{EV_ZONE_WARNING_LED_ID} / "
            f"BOARD Pin {EV_ZONE_WARNING_LED_PIN}"
        )
        sleep(stage_seconds)
        _raise_if_background_failed(adapter)

        phase = "두 번째 OFF"
        adapter.apply_projection(())
        print("[OFF] 두 LED LOW")
        _sleep_if_positive(off_seconds, sleep=sleep)
        _raise_if_background_failed(adapter)

        phase = "두 LED 동시 점멸"
        adapter.apply_projection(
            (
                _command(DISABLED_ZONE_WARNING_LED_ID),
                _command(EV_ZONE_WARNING_LED_ID),
            )
        )
        print(
            "[3/3] 두 LED 동시 점멸: "
            f"BOARD Pin {DISABLED_ZONE_WARNING_LED_PIN}·"
            f"{EV_ZONE_WARNING_LED_PIN}"
        )
        sleep(stage_seconds)
        _raise_if_background_failed(adapter)

        phase = "최종 OFF"
        adapter.apply_projection(())
        print("[OFF] 두 LED LOW")
    except KeyboardInterrupt as error:
        reported_errors.append(error)
        print(
            "경고 LED 진단이 사용자에 의해 중단되었습니다.",
            file=sys.stderr,
        )
        exit_code = 1
    except _BackgroundFailureDetected as error:
        reported_errors.append(error.failure)
        print(str(error), file=sys.stderr)
        exit_code = 1
    except Exception as error:
        reported_errors.append(error)
        print(
            f"경고 LED 진단 {phase}에 실패했습니다: {error}",
            file=sys.stderr,
        )
        exit_code = 1
    finally:
        try:
            adapter.close()
        except KeyboardInterrupt as error:
            reported_errors.append(error)
            print(
                "경고 LED GPIO 정리가 사용자에 의해 중단되었습니다.",
                file=sys.stderr,
            )
            exit_code = 1
        except Exception as error:
            reported_errors.append(error)
            print(
                f"경고 LED GPIO 정리에 실패했습니다: {error}",
                file=sys.stderr,
            )
            exit_code = 1

        try:
            final_failure = adapter.failure
        except Exception as error:
            if not was_reported(error):
                reported_errors.append(error)
                print(
                    "경고 LED background failure 상태를 확인할 수 "
                    f"없습니다: {error}",
                    file=sys.stderr,
                )
            exit_code = 1
        else:
            if (
                final_failure is not None
                and not was_reported(final_failure)
            ):
                reported_errors.append(final_failure)
                print(
                    "경고 LED background worker가 실패했습니다: "
                    f"{final_failure}",
                    file=sys.stderr,
                )
                exit_code = 1

    if exit_code == 0:
        print("경고 LED 진단 및 GPIO 정리 완료")

    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        adapter = build_adapter(
            blink_on_seconds=args.blink_on_seconds,
            blink_off_seconds=args.blink_off_seconds,
        )
    except KeyboardInterrupt:
        print(
            "경고 LED 진단 준비가 사용자에 의해 중단되었습니다.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            f"경고 LED 진단 adapter를 준비할 수 없습니다: {error}",
            file=sys.stderr,
        )
        return 1

    return run(
        adapter=adapter,
        stage_seconds=args.stage_seconds,
        off_seconds=args.off_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())

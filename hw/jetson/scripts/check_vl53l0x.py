#!/usr/bin/env python3
"""실제 Jetson에서 듀얼 VL53L0X 초기화와 거리 측정을 수동 확인한다.

`.env`의 ToF 설정으로 기존 `Vl53l0xArray`를 열고 제한된 횟수만큼 측정한 뒤
성공과 개별 센서 실패를 출력한다. GPIO, I²C, 주소 할당 절차는 재구현하지
않으며 점유 판정이나 운영 polling 정책도 소유하지 않는다.

실행 예:

    cd hw/jetson
    python -m scripts.check_vl53l0x
    python -m scripts.check_vl53l0x --count 10 --interval-seconds 0.5

CLI 기본값은 수동 하드웨어 진단 편의를 위한 값이며 운영 polling 설정이 아니다.
"""

from __future__ import annotations

import argparse
import math
import sys
import time

from src.config.settings import Settings, get_settings
from src.sensors.adapters.vl53l0x_array import Vl53l0xArray
from src.sensors.models import (
    SensorObservation,
    SensorReadFailure,
)
from src.sensors.ports import SensorArray


def _positive_int(value: str) -> int:
    try:
        parsed_value = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다.") from exc
    if parsed_value < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 합니다.")
    return parsed_value


def _non_negative_finite_float(value: str) -> float:
    try:
        parsed_value = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "유한한 0 이상의 숫자여야 합니다."
        ) from exc
    if not math.isfinite(parsed_value) or parsed_value < 0:
        raise argparse.ArgumentTypeError(
            "유한한 0 이상의 숫자여야 합니다."
        )
    return parsed_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--count",
        type=_positive_int,
        default=10,
        help="read_all() 호출 횟수. 기본값 10은 수동 진단 편의값이다.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=_non_negative_finite_float,
        default=0.5,
        help="측정 사이 대기 시간(초). 기본값 0.5는 운영 polling 정책이 아니다.",
    )
    return parser


def build_adapter(settings: Settings) -> SensorArray:
    """기존 설정값으로 실제 듀얼 VL53L0X 어댑터를 조립한다."""

    return Vl53l0xArray(
        i2c_bus=settings.tof_i2c_bus,
        shutdown_settle_seconds=settings.tof_shutdown_settle_seconds,
        boot_settle_seconds=settings.tof_boot_settle_seconds,
        io_timeout_seconds=settings.tof_io_timeout_seconds,
    )


def format_observation(observation: SensorObservation) -> str:
    """mm 원시 거리와 사람이 확인하기 위한 cm 환산값을 만든다."""

    return (
        f"{observation.sensor_id}: {observation.value:.1f} mm "
        f"({observation.value / 10.0:.1f} cm)"
    )


def format_failure(failure: SensorReadFailure) -> str:
    """개별 센서 실패의 공개 사유와 메시지를 만든다."""

    return f"{failure.sensor_id}: 실패 {failure.reason.value} - {failure.message}"


def run(
    *,
    sensor_array: SensorArray,
    i2c_bus: int,
    count: int,
    interval_seconds: float,
) -> int:
    """센서 배열을 열어 제한된 횟수만큼 측정하고 반드시 정리한다.

    개별 센서 실패는 남은 측정을 중단하지 않는다. 성공과 실패는 별도 tuple
    계약이므로 observations 내부 순서, failures 내부 순서대로 각각 출력한다.
    초기화 또는 측정 오류와 정리 오류는 각각 출력하며 모두 실패로 처리한다.
    """

    exit_code = 0
    phase = "초기화"

    try:
        sensor_array.open()
        print(f"VL53L0X 배열 초기화 성공: I²C bus {i2c_bus}")
        phase = "측정"

        for measurement_number in range(1, count + 1):
            batch = sensor_array.read_all()
            if not batch.observations and not batch.failures:
                raise RuntimeError("센서 측정 결과가 비어 있습니다.")

            prefix = f"[{measurement_number}/{count}] "

            for observation in batch.observations:
                print(prefix + format_observation(observation))
            for failure in batch.failures:
                print(prefix + format_failure(failure))

            if batch.failures:
                exit_code = 1

            if measurement_number < count:
                time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("VL53L0X 진단이 사용자에 의해 중단되었습니다.", file=sys.stderr)
        exit_code = 1
    except Exception as exc:
        print(
            f"VL53L0X 배열 {phase}에 실패했습니다: {exc}",
            file=sys.stderr,
        )
        exit_code = 1
    finally:
        try:
            sensor_array.close()
        except KeyboardInterrupt:
            print(
                "VL53L0X 배열 정리가 사용자에 의해 중단되었습니다.",
                file=sys.stderr,
            )
            exit_code = 1
        except Exception as exc:
            print(
                f"VL53L0X 배열 정리에 실패했습니다: {exc}",
                file=sys.stderr,
            )
            exit_code = 1

    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = get_settings()
        sensor_array = build_adapter(settings)
    except KeyboardInterrupt:
        print("VL53L0X 진단이 사용자에 의해 중단되었습니다.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(
            f"VL53L0X 진단 설정을 준비할 수 없습니다: {exc}",
            file=sys.stderr,
        )
        return 1

    return run(
        sensor_array=sensor_array,
        i2c_bus=settings.tof_i2c_bus,
        count=args.count,
        interval_seconds=args.interval_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())

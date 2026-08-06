"""XSHUT으로 주소를 할당하는 VL53L0X 듀얼 센서 배열 어댑터.

두 센서를 설정 순서대로 초기화하고 단일 거리값을 mm 단위 관측 계약으로
변환한다. 거리값의 의미 해석, 점유 판정, polling과 상위 파이프라인 조립은
이 모듈의 책임이 아니다.

하드웨어 라이브러리는 ``open()``에서 지연 import하므로 일반 PC에서도
이 모듈 자체를 import할 수 있다. 이 구현은 thread-safe하지 않으며
생명주기 메서드는 하나의 owner가 직렬로 호출해야 한다.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import Any

from src.sensors.models import (
    TOF_SENSOR_TYPE,
    SensorObservation,
    SensorReadBatch,
    SensorReadFailure,
    SensorReadFailureReason,
)
from src.sensors.ports import (
    SensorArrayCleanupError,
    SensorArrayInitializationError,
    SensorArrayStateError,
)


DISABLED_ZONE_SENSOR_ID = "tof_disabled_zone"
EV_CHARGING_ZONE_SENSOR_ID = "tof_ev_charging_zone"

_DEFAULT_I2C_ADDRESS = 0x29
_MIN_DISTANCE_MM = 20.0
_MAX_DISTANCE_MM = 2000.0


@dataclass(frozen=True)
class _SensorDefinition:
    """센서 식별자와 물리 XSHUT 핀 및 실행 주소."""

    sensor_id: str
    shutdown_pin: int
    address: int


_SENSOR_DEFINITIONS = (
    _SensorDefinition(
        sensor_id=DISABLED_ZONE_SENSOR_ID,
        shutdown_pin=15,
        address=0x30,
    ),
    _SensorDefinition(
        sensor_id=EV_CHARGING_ZONE_SENSOR_ID,
        shutdown_pin=29,
        address=0x31,
    ),
)
_ASSIGNED_I2C_ADDRESSES = frozenset(
    definition.address for definition in _SENSOR_DEFINITIONS
)
_RESERVED_I2C_ADDRESSES = frozenset(
    {_DEFAULT_I2C_ADDRESS, *_ASSIGNED_I2C_ADDRESSES}
)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _monotonic() -> float:
    return time.monotonic()


def _load_hardware_dependencies() -> tuple[Any, Any, Any]:
    try:
        import Jetson.GPIO as GPIO
        import adafruit_vl53l0x
        from adafruit_extended_bus import ExtendedI2C
    except ImportError as exc:
        missing_dependency = getattr(exc, "name", None) or "unknown"
        raise SensorArrayInitializationError(
            "VL53L0X 센서 하드웨어 의존성을 import할 수 없습니다: "
            f"{missing_dependency}"
        ) from exc

    return GPIO, ExtendedI2C, adafruit_vl53l0x.VL53L0X


def _open_i2c(i2c_factory: Any, i2c_bus: int) -> Any:
    return i2c_factory(i2c_bus)


def _create_sensor(
    *,
    sensor_factory: Any,
    i2c: Any,
    io_timeout_seconds: float,
) -> Any:
    return sensor_factory(
        i2c,
        address=_DEFAULT_I2C_ADDRESS,
        io_timeout_s=io_timeout_seconds,
    )


def _read_distance_mm(sensor: Any) -> Any:
    return sensor.range


class Vl53l0xArray:
    """두 VL53L0X 센서를 정해진 순서로 관리하는 ``SensorArray`` 구현."""

    def __init__(
        self,
        *,
        i2c_bus: int,
        shutdown_settle_seconds: float,
        boot_settle_seconds: float,
        io_timeout_seconds: float,
    ) -> None:
        if (
            isinstance(i2c_bus, bool)
            or not isinstance(i2c_bus, int)
            or i2c_bus < 0
        ):
            raise ValueError("i2c_bus는 0 이상의 정수여야 합니다.")

        normalized_time_settings: dict[str, float] = {}
        time_settings = (
            ("shutdown_settle_seconds", shutdown_settle_seconds),
            ("boot_settle_seconds", boot_settle_seconds),
            ("io_timeout_seconds", io_timeout_seconds),
        )
        for setting_name, setting_value in time_settings:
            if (
                isinstance(setting_value, bool)
                or not isinstance(setting_value, Real)
            ):
                raise ValueError(
                    f"{setting_name}는 유한한 양수여야 합니다."
                )
            try:
                normalized_value = float(setting_value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError(
                    f"{setting_name}는 유한한 양수여야 합니다."
                ) from exc
            if (
                not math.isfinite(normalized_value)
                or normalized_value <= 0
            ):
                raise ValueError(
                    f"{setting_name}는 유한한 양수여야 합니다."
                )
            normalized_time_settings[setting_name] = normalized_value

        self._i2c_bus = i2c_bus
        self._shutdown_settle_seconds = normalized_time_settings[
            "shutdown_settle_seconds"
        ]
        self._boot_settle_seconds = normalized_time_settings[
            "boot_settle_seconds"
        ]
        self._io_timeout_seconds = normalized_time_settings[
            "io_timeout_seconds"
        ]
        self._gpio: Any | None = None
        self._i2c: Any | None = None
        self._sensors: tuple[tuple[_SensorDefinition, Any], ...] = ()
        self._is_open = False

    def open(self) -> None:
        """두 센서를 종료 상태에서 순차 활성화하고 실행 주소를 할당한다."""

        if self._is_open:
            return

        try:
            gpio, i2c_factory, sensor_factory = (
                _load_hardware_dependencies()
            )
            self._gpio = gpio
            gpio.setmode(gpio.BOARD)

            for definition in _SENSOR_DEFINITIONS:
                gpio.setup(
                    definition.shutdown_pin,
                    gpio.OUT,
                    initial=gpio.LOW,
                )
            _sleep(self._shutdown_settle_seconds)

            self._i2c = _open_i2c(i2c_factory, self._i2c_bus)
            self._verify_reserved_addresses_available()

            initialized_sensors: list[
                tuple[_SensorDefinition, Any]
            ] = []
            for definition in _SENSOR_DEFINITIONS:
                gpio.output(definition.shutdown_pin, gpio.HIGH)
                _sleep(self._boot_settle_seconds)
                sensor = _create_sensor(
                    sensor_factory=sensor_factory,
                    i2c=self._i2c,
                    io_timeout_seconds=self._io_timeout_seconds,
                )
                sensor.set_address(definition.address)
                initialized_sensors.append((definition, sensor))

            self._verify_assigned_addresses()
            self._sensors = tuple(initialized_sensors)
            self._is_open = True
        except Exception as exc:
            cleanup_errors = self._cleanup_resources()
            if (
                isinstance(exc, SensorArrayInitializationError)
                and not cleanup_errors
            ):
                raise

            detail = f"VL53L0X 센서 배열 초기화에 실패했습니다: {exc}"
            if cleanup_errors:
                detail += (
                    " 초기화 실패 후 정리 오류: "
                    + "; ".join(cleanup_errors)
                )
            raise SensorArrayInitializationError(detail) from exc

    def read_all(self) -> SensorReadBatch:
        """두 센서를 설정 순서대로 한 번씩 읽고 부분 결과를 반환한다."""

        if not self._is_open:
            raise SensorArrayStateError(
                "센서 배열이 열리지 않았습니다. open()을 먼저 호출하세요."
            )

        observations: list[SensorObservation] = []
        failures: list[SensorReadFailure] = []

        for definition, sensor in self._sensors:
            try:
                raw_distance_mm = _read_distance_mm(sensor)
            except TimeoutError as exc:
                observed_at = _utc_now()
                failures.append(
                    SensorReadFailure(
                        sensor_id=definition.sensor_id,
                        observed_at=observed_at,
                        reason=SensorReadFailureReason.TIMEOUT,
                        message=(
                            f"{definition.sensor_id} 센서 측정 시간이 "
                            f"초과되었습니다: {exc}"
                        ),
                    )
                )
                continue
            except (OSError, RuntimeError) as exc:
                observed_at = _utc_now()
                failures.append(
                    SensorReadFailure(
                        sensor_id=definition.sensor_id,
                        observed_at=observed_at,
                        reason=(
                            SensorReadFailureReason.COMMUNICATION_ERROR
                        ),
                        message=(
                            f"{definition.sensor_id} 센서 통신에 "
                            f"실패했습니다: {exc}"
                        ),
                    )
                )
                continue

            observed_at = _utc_now()
            result = self._classify_reading(
                definition=definition,
                raw_distance_mm=raw_distance_mm,
                observed_at=observed_at,
            )
            if isinstance(result, SensorObservation):
                observations.append(result)
            else:
                failures.append(result)

        return SensorReadBatch(
            observations=tuple(observations),
            failures=tuple(failures),
        )

    def close(self) -> None:
        """XSHUT을 LOW로 전환한 뒤 획득한 자원을 모두 정리한다."""

        cleanup_errors = self._cleanup_resources()
        if cleanup_errors:
            raise SensorArrayCleanupError(
                "VL53L0X 센서 배열 정리에 실패했습니다: "
                + "; ".join(cleanup_errors)
            )

    def _verify_reserved_addresses_available(self) -> None:
        addresses = self._scan_i2c_addresses()
        conflicting_addresses = addresses & _RESERVED_I2C_ADDRESSES
        if conflicting_addresses:
            formatted_addresses = ", ".join(
                f"0x{address:02X}"
                for address in sorted(conflicting_addresses)
            )
            raise SensorArrayInitializationError(
                "VL53L0X 주소 할당 전에 예약 I²C 주소가 이미 "
                f"사용 중입니다: {formatted_addresses}"
            )

    def _verify_assigned_addresses(self) -> None:
        addresses = self._scan_i2c_addresses()
        missing_addresses = _ASSIGNED_I2C_ADDRESSES - addresses
        default_address_present = _DEFAULT_I2C_ADDRESS in addresses
        if not missing_addresses and not default_address_present:
            return

        problems: list[str] = []
        if missing_addresses:
            formatted_addresses = ", ".join(
                f"0x{address:02X}"
                for address in sorted(missing_addresses)
            )
            problems.append(
                f"실행 주소 응답 없음: {formatted_addresses}"
            )
        if default_address_present:
            problems.append(
                "기본 주소 0x29에서 예상하지 못한 응답 발견"
            )

        raise RuntimeError(
            "VL53L0X 주소 할당 결과가 올바르지 않습니다: "
            + "; ".join(problems)
        )

    def _scan_i2c_addresses(self) -> set[int]:
        if self._i2c is None:
            raise RuntimeError("I²C bus가 열리지 않았습니다.")

        deadline = _monotonic() + self._io_timeout_seconds
        locked = False
        try:
            while not self._i2c.try_lock():
                remaining_seconds = deadline - _monotonic()
                if remaining_seconds <= 0:
                    raise TimeoutError(
                        "주소 확인을 위한 I²C lock 획득 시간이 "
                        "초과되었습니다."
                    )
                _sleep(min(0.001, remaining_seconds))

            locked = True
            return {
                int(address) & 0x7F
                for address in self._i2c.scan()
            }
        finally:
            if locked:
                self._i2c.unlock()

    @staticmethod
    def _classify_reading(
        *,
        definition: _SensorDefinition,
        raw_distance_mm: Any,
        observed_at: datetime,
    ) -> SensorObservation | SensorReadFailure:
        if (
            isinstance(raw_distance_mm, bool)
            or not isinstance(raw_distance_mm, Real)
        ):
            return SensorReadFailure(
                sensor_id=definition.sensor_id,
                observed_at=observed_at,
                reason=SensorReadFailureReason.INVALID_READING,
                message=(
                    f"{definition.sensor_id} 센서가 유효한 거리값을 "
                    f"반환하지 않았습니다: {raw_distance_mm!r}"
                ),
            )

        try:
            distance_mm = float(raw_distance_mm)
        except OverflowError:
            return SensorReadFailure(
                sensor_id=definition.sensor_id,
                observed_at=observed_at,
                reason=SensorReadFailureReason.INVALID_READING,
                message=(
                    f"{definition.sensor_id} 센서 거리값을 유한한 "
                    "숫자로 변환할 수 없습니다."
                ),
            )

        if not math.isfinite(distance_mm) or distance_mm < 0:
            return SensorReadFailure(
                sensor_id=definition.sensor_id,
                observed_at=observed_at,
                reason=SensorReadFailureReason.INVALID_READING,
                message=(
                    f"{definition.sensor_id} 센서가 유효한 거리값을 "
                    f"반환하지 않았습니다: {raw_distance_mm!r}"
                ),
            )

        if not _MIN_DISTANCE_MM <= distance_mm <= _MAX_DISTANCE_MM:
            return SensorReadFailure(
                sensor_id=definition.sensor_id,
                observed_at=observed_at,
                reason=SensorReadFailureReason.OUT_OF_RANGE,
                message=(
                    f"{definition.sensor_id} 센서 거리값이 공칭 범위"
                    f"(20~2000mm)를 벗어났습니다: {distance_mm}mm"
                ),
            )

        return SensorObservation(
            sensor_id=definition.sensor_id,
            sensor_type=TOF_SENSOR_TYPE,
            value=distance_mm,
            observed_at=observed_at,
            quality=None,
        )

    def _cleanup_resources(self) -> list[str]:
        cleanup_errors: list[str] = []
        gpio = self._gpio
        i2c = self._i2c

        try:
            if gpio is not None:
                for definition in _SENSOR_DEFINITIONS:
                    try:
                        gpio.setup(
                            definition.shutdown_pin,
                            gpio.OUT,
                            initial=gpio.LOW,
                        )
                    except Exception as exc:
                        cleanup_errors.append(
                            f"XSHUT pin {definition.shutdown_pin} "
                            f"LOW 전환 실패: {exc}"
                        )

            self._sensors = ()

            if i2c is not None:
                try:
                    i2c.deinit()
                except Exception as exc:
                    cleanup_errors.append(
                        f"I²C 자원 해제 실패: {exc}"
                    )

            if gpio is not None:
                try:
                    gpio.cleanup(
                        tuple(
                            definition.shutdown_pin
                            for definition in _SENSOR_DEFINITIONS
                        )
                    )
                except Exception as exc:
                    cleanup_errors.append(
                        f"GPIO 자원 해제 실패: {exc}"
                    )
        finally:
            self._sensors = ()
            self._i2c = None
            self._gpio = None
            self._is_open = False

        return cleanup_errors

"""ToF 등 물리 센서가 생산하는 관측 계약.

이 패키지는 GPIO, polling, 센서별 해석을 구현하지 않고 하드웨어
담당 어댑터가 Jetson 내부 파이프라인에 넘겨줄 값의 경계만 소유한다.
현재 연결된 센서 파이프라인이 없더라도 후속 하드웨어 계약을 위한
확장 경계이므로 임의로 actuator 또는 parking 계층에 흡수하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


TOF_SENSOR_TYPE = "tof"


@dataclass(frozen=True)
class SensorObservation:
    """센서 하나가 한 시점에 보고한 원시 관측값.

    `quality`는 센서 자체 신뢰도를 나타내며 값 형식은 센서 종류별로
    다를 수 있다. `sensor_type`이 `"tof"`인 경우 `value`는 mm 단위의
    원시 거리다. 이 계약은 센서 입력을 표현할 뿐, 관측값을 점유 여부,
    주차 상태 또는 위반으로 해석하지 않는다.
    """

    sensor_id: str
    sensor_type: str
    value: float
    observed_at: datetime
    quality: float | None = None


class SensorReadFailureReason(str, Enum):
    """센서 읽기가 실패한 이유."""

    TIMEOUT = "TIMEOUT"
    COMMUNICATION_ERROR = "COMMUNICATION_ERROR"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    INVALID_READING = "INVALID_READING"


@dataclass(frozen=True)
class SensorReadFailure:
    """센서 하나에서 발생한 읽기 실패."""

    sensor_id: str
    observed_at: datetime
    reason: SensorReadFailureReason
    message: str


@dataclass(frozen=True)
class SensorReadBatch:
    """동일한 읽기 작업에서 얻은 센서별 성공 및 실패 결과."""

    observations: tuple[SensorObservation, ...]
    failures: tuple[SensorReadFailure, ...]

    def __post_init__(self) -> None:
        observation_sensor_ids: set[str] = set()
        for observation in self.observations:
            if observation.sensor_id in observation_sensor_ids:
                raise ValueError(
                    "observations에 중복된 sensor_id가 있습니다: "
                    f"{observation.sensor_id!r}"
                )
            observation_sensor_ids.add(observation.sensor_id)

        failure_sensor_ids: set[str] = set()
        for failure in self.failures:
            if failure.sensor_id in failure_sensor_ids:
                raise ValueError(
                    "failures에 중복된 sensor_id가 있습니다: "
                    f"{failure.sensor_id!r}"
                )
            failure_sensor_ids.add(failure.sensor_id)

        for failure in self.failures:
            if failure.sensor_id in observation_sensor_ids:
                raise ValueError(
                    "sensor_id가 observations와 failures에 동시에 존재합니다: "
                    f"{failure.sensor_id!r}"
                )

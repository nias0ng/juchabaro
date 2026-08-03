"""물리 센서(초음파 등)가 생산하는 관측 계약.

이 패키지는 GPIO, polling, 센서별 해석을 구현하지 않고 하드웨어
담당 어댑터가 Jetson 내부 파이프라인에 넘겨줄 값의 경계만 소유한다.
현재 연결된 센서 파이프라인이 없더라도 후속 하드웨어 계약을 위한
확장 경계이므로 임의로 actuator 또는 parking 계층에 흡수하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SensorObservation:
    """센서 하나가 한 시점에 보고한 원시 관측값.

    `quality`는 센서 자체 신뢰도(예: 초음파 반사 신호 세기)를 나타내며
    값 형식은 센서 종류별로 다를 수 있다. 이 계약은 센서 입력을 표현할 뿐,
    관측값을 주차 상태나 위반으로 해석하지 않는다.
    """

    sensor_id: str
    sensor_type: str
    value: float
    observed_at: datetime
    quality: float | None = None

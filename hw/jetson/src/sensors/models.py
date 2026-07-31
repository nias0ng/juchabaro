"""물리 센서(초음파 등)가 생산하는 관측 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SensorObservation:
    """센서 하나가 한 시점에 보고한 값.

    `quality`는 센서 자체 신뢰도(예: 초음파 반사 신호 세기)를 나타내며, 값
    형식은 센서 종류별로 다를 수 있다. `parking`은 이 관측을 위반 확정의
    유일한 근거로 쓰지 않고 보조 증거로만 받는다(데이터흐름.md §9).
    """

    sensor_id: str
    sensor_type: str
    value: float
    observed_at: datetime
    quality: float | None = None

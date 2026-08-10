"""Actuator projection 계획과 외부 하드웨어 실행 Port.

이 모듈은 GPIO pin, LED pattern, speaker 음원·반복 시간을 결정하지 않는다.
배포 계약이 제공한 planner가 durable Incident snapshot을 전체 command
projection으로 바꾸고, adapter는 그 projection을 실제 장치에 적용한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from src.actuators.models import ActuatorCommand
from src.parking.models import Incident


class ActuatorCommandPlanner(Protocol):
    """활성 Incident snapshot을 현재 필요한 전체 actuator 명령으로 만든다."""

    def plan(
        self,
        incidents: tuple[Incident, ...],
        *,
        requested_at: datetime,
    ) -> tuple[ActuatorCommand, ...]:
        """CANDIDATE를 공개 경고로 만들지 않는 전체 projection을 반환한다."""


class ActuatorPort(Protocol):
    """전체 actuator command projection을 외부 하드웨어에 적용한다."""

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        """같은 projection의 반복 적용이 안전하도록 장치 상태를 맞춘다.

        빈 tuple은 이 Port가 관리하는 경고 projection이 없다는 뜻이다.
        실제 OFF 명령, GPIO, LED·speaker 실행 방식은 adapter 계약이 소유한다.
        """

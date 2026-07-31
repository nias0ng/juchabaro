"""LED·스피커 등 물리 액추에이터 명령 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ActuatorCommand:
    """`application`/`parking`이 결정한 경고 등을 액추에이터에 지시하는 명령.

    어떤 상황에서 경고할지는 이 모듈이 아니라 호출부가 정한다(데이터흐름.md
    §10) — `actuators`는 명령을 받아 수행만 한다.
    """

    actuator_id: str
    action: str
    reason: str
    requested_at: datetime

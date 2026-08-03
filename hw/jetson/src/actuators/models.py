"""LED·speaker에 전달하는 재구성 가능한 local projection 명령.

명령은 domain owner가 아니며 durable Incident와 현재 projection에서 다시 만들 수
있다. publication retry는 새 경고 domain event를 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.domain.models import require_aware


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

    def __post_init__(self) -> None:
        require_aware(self.requested_at, "requested_at")
        if not self.actuator_id or not self.action or not self.reason:
            raise ValueError("actuator_id, action, and reason must not be empty")

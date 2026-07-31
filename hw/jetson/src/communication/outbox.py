"""판정 루프와 네트워크 장애를 분리하는 사건 전이 보관함.

실제 Backend HTTP 전송(T-15)은 범위 밖이다 — 이 모듈은 사건 전이를 로컬
JSONL 파일에 추가 전용(append-only)으로 durable하게 쌓아두기만 한다.
`vehicleId`/`parkingSessionId` 같은 백엔드 식별자는 `IncidentKey`에 아직
없어(§4.3 이후 반영 예정) 여기서는 직렬화하지 않는다 — 그 보강은 T-15가
Backend DTO로 변환할 때 vehicle_context에서 채운다.

판정 루프가 파일 I/O로 막히면 안 되므로 쓰기 실패는 조용히 삼키지 않고
`OutboxError`로 알린다. 그 실패를 어떻게 다룰지(재시도, 로그만 남기고 계속
등)는 호출부(application)의 몫이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from src.parking.models import IncidentTransition


class OutboxError(RuntimeError):
    """사건 전이를 outbox에 기록하는 데 실패했다."""


def _uuid_to_wire(value: UUID | None) -> str | None:
    """Jetson 내부 UUID를 JSON 계약의 문자열로 변환한다."""

    return None if value is None else str(value)


def transition_to_jsonable(transition: IncidentTransition) -> dict[str, Any]:
    """`IncidentTransition`을 JSON 직렬화 가능한 dict(camelCase)로 변환한다."""

    incident = transition.incident
    key = incident.key
    return {
        "transitionType": transition.transition_type.value,
        "incidentId": _uuid_to_wire(incident.incident_id),
        "revision": incident.revision,
        "state": incident.state.value,
        "ruleCode": key.rule_code,
        "physicalVehicleId": _uuid_to_wire(key.physical_vehicle_id),
        "parkingEpisodeId": _uuid_to_wire(key.parking_episode_id),
        "zoneVisitId": _uuid_to_wire(key.zone_visit_id),
        "zoneId": key.zone_id,
        "victimPhysicalVehicleId": _uuid_to_wire(key.victim_physical_vehicle_id),
        "firstObservedAt": incident.first_observed_at.isoformat(),
        "confirmedAt": None if incident.confirmed_at is None else incident.confirmed_at.isoformat(),
        "resolvedAt": None if incident.resolved_at is None else incident.resolved_at.isoformat(),
    }


class JsonlOutbox:
    """사건 전이를 JSON Lines 파일에 한 줄씩 추가 전용으로 기록한다."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, transition: IncidentTransition) -> None:
        """전이 하나를 파일 끝에 한 줄(JSON)로 덧붙인다."""

        line = json.dumps(transition_to_jsonable(transition), ensure_ascii=False)
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            raise OutboxError(f"outbox 파일에 쓰지 못했습니다({self._path}): {exc}") from exc

"""리플레이 검증 CLI 전용 `PublicationPreparer` 구현(465/T-17).

`FrameObservationWorkflow`는 확정된 도메인 전이를 outbox row로 만들기 전에
`PublicationPreparer`에게 exact wire bytes를 요구한다. 백엔드 wire 계약이
아직 확정되지 않아 프로덕션 구현은 의도적으로 비워 둔 상태다(`src/main.py`
모듈 docstring 참고 — 배포 계층이 주입해야 한다). 이 모듈은 그 빈자리를
**리플레이 검증 도구에 한해서만** 채운다. 프로덕션 배포 경로에서 쓰면 안 된다.

**결정론.** `delivery_id`/`idempotency_key`는 `uuid4()`가 아니라
`(aggregate_type, aggregate_id, transition_type, publication_revision)`을
문자열로 엮어 만든다. 그 네 값은 `_validate_prepared_publication`이 도메인
전이와 정확히 일치하기를 요구하는 값이기도 하므로, 같은 입력을 두 번 흘리면
같은 식별자가 나온다 — `tests/application/test_replay_determinism.py`가
지키려는 성질이다. 이 파일은 새로운 난수원을 도입하지 않는다.

**JSONL 사이드 출력은 SQLite commit과 트랜잭션으로 묶이지 않는다.**
`prepare_*`는 payload를 만들면서 같은 JSON 한 줄을 CLI의 `--out-events`
파일에도 바로 쓴다(옛 `JsonlOutbox.append()`와 같은 사용감). 그런데
`prepare_*`가 불리는 시점은 `UnitOfWork`가 아직 commit되기 전이므로, 그
트랜잭션이 이후에 rollback되면 SQLite outbox에는 없는 줄이 JSONL에 남는다.
리플레이 검증 도구에서는 허용 가능한 절충이다 — 이 파일은 사람이 읽는
산출물이고, 실제 발행 권위는 `OutboxRepository`가 보호하는 DB row에 있다.
프로덕션 구현은 이렇게 만들면 안 된다.
"""

from __future__ import annotations

import json
from typing import Any, TextIO

from src.application.physical_presence_workflow import SessionExitTransition
from src.communication.outbox import PreparedPublication
from src.parking.models import (
    IncidentTransition,
    ParkingAssignment,
    ParkingTransition,
)

# 실제 백엔드 endpoint가 정해지지 않았음을 값 자체로 드러낸다.
# `PreparedPublication`은 빈 문자열을 거부하므로 placeholder가 필요하다.
REPLAY_DESTINATION = "replay-validation-jsonl"


class PublicationPreparerError(RuntimeError):
    """확정 전이를 events 파일에 기록하는 데 실패했다."""


def _isoformat(value: Any) -> str | None:
    return None if value is None else value.isoformat()


def _assignment_to_jsonable(assignment: ParkingAssignment) -> dict[str, Any]:
    """`ParkingAssignment`를 camelCase wire dict로 바꾼다.

    `src/replay/zone_visit_publisher.py`의 `zone_visit_to_jsonable`과 같은
    규칙을 따른다(camelCase, UUID는 문자열, datetime은 ISO 8601).
    """

    return {
        "state": assignment.state.value,
        "zoneId": assignment.zone_id,
        "confidence": assignment.confidence,
        "lastStableAt": _isoformat(assignment.last_stable_at),
        "unassignedReason": assignment.unassigned_reason,
    }


class JsonlPublicationPreparer:
    """확정 전이를 결정론적 envelope + camelCase JSON payload로 바꾼다.

    같은 JSON을 생성자에 주입된 파일 핸들에도 한 줄씩 덧붙인다. 핸들 소유권은
    호출자(CLI)에 있다 — 이 클래스는 열지도 닫지도 않는다.
    """

    def __init__(self, *, events_handle: TextIO | None = None) -> None:
        self._events_handle = events_handle

    def prepare_parking(self, transition: ParkingTransition) -> PreparedPublication:
        return self._prepare(
            aggregate_type="ParkingEpisode",
            aggregate_id=str(transition.parking_episode_id),
            publication_revision=transition.publication_revision,
            transition_type=transition.transition_type.value,
            body={
                "parkingEpisodeId": str(transition.parking_episode_id),
                "physicalVehicleId": str(transition.physical_vehicle_id),
                "parkingSessionId": transition.parking_session_id,
                "occurredAt": _isoformat(transition.occurred_at),
                "assignment": _assignment_to_jsonable(transition.assignment),
            },
        )

    def prepare_incident(self, transition: IncidentTransition) -> PreparedPublication:
        incident = transition.incident
        return self._prepare(
            aggregate_type="Incident",
            aggregate_id=str(incident.incident_id),
            publication_revision=incident.publication_revision,
            transition_type=transition.transition_type.value,
            body={
                "incidentId": str(incident.incident_id),
                "physicalVehicleId": str(incident.physical_vehicle_id),
                "ruleCode": incident.key.rule_code,
                "scopeType": incident.key.scope_type.value,
                "scopeId": str(incident.key.scope_id),
                "state": incident.state.value,
                "zoneId": incident.zone_id,
                "parkingSessionId": incident.parking_session_id,
                "entryAttemptId": (
                    None
                    if incident.entry_attempt_id is None
                    else str(incident.entry_attempt_id)
                ),
                "firstObservedAt": _isoformat(incident.first_observed_at),
                "confirmedAt": _isoformat(incident.confirmed_at),
                "resolvedAt": _isoformat(incident.resolved_at),
            },
        )

    def prepare_session_exit(
        self,
        transition: SessionExitTransition,
    ) -> PreparedPublication:
        return self._prepare(
            aggregate_type="ParkingSession",
            aggregate_id=str(transition.parking_session_id),
            publication_revision=transition.publication_revision,
            # `_enqueue_publications`가 이 문자열을 그대로 기대한다 —
            # SessionExitTransition에는 transition_type 필드가 없다.
            transition_type="SESSION_EXIT",
            body={
                "parkingSessionId": transition.parking_session_id,
                "physicalVehicleId": str(transition.physical_vehicle_id),
                "occurredAt": _isoformat(transition.occurred_at),
                "origin": transition.origin.value,
                "evidence": transition.evidence.value,
            },
        )

    def _prepare(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        publication_revision: int,
        transition_type: str,
        body: dict[str, Any],
    ) -> PreparedPublication:
        """envelope 4-tuple을 도메인 전이와 정확히 일치시켜 payload를 만든다.

        네 값이 하나라도 어긋나면
        `frame_observation_workflow._validate_prepared_publication`이
        `RuntimeError`로 막는다 — 여기서 호출자가 넘긴 값을 재해석하지 않는
        이유다.
        """

        delivery_id = (
            f"{aggregate_type}:{aggregate_id}:{transition_type}:{publication_revision}"
        )
        record = {
            "deliveryId": delivery_id,
            "aggregateType": aggregate_type,
            "aggregateId": aggregate_id,
            "transitionType": transition_type,
            "publicationRevision": publication_revision,
            **body,
        }
        # `sort_keys`는 쓰지 않는다 — dict를 항상 같은 순서로 만들므로 값
        # 자체의 결정론이 이미 순서를 고정한다(zone_visit_publisher.py와 동일).
        line = json.dumps(record, ensure_ascii=False)
        self._append(line)
        return PreparedPublication(
            delivery_id=delivery_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            destination=REPLAY_DESTINATION,
            publication_revision=publication_revision,
            transition_type=transition_type,
            payload=line.encode("utf-8"),
            idempotency_key=delivery_id,
        )

    def _append(self, line: str) -> None:
        if self._events_handle is None:
            return
        try:
            self._events_handle.write(line + "\n")
        except OSError as exc:
            raise PublicationPreparerError(
                f"events 파일에 쓰지 못했습니다: {exc}"
            ) from exc

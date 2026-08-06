"""RPi EntryDecision을 durable EntryMatchAttempt로 접수하는 application 경계.

파싱된 입력을 session domain으로 변환하고 inbound 영수증·EntryMatchAttempt·
초기 ParkingSessionMirror를 같은 SQLite transaction에 저장한다. 차량 매칭은
EntryMatchCoordinator를 사용하는 후속 tracking workflow 책임이다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.communication.models import (
    EntryAccessDecision,
    EntryDecisionInput,
    EntrySessionContextInput,
)
from src.domain.models import ObservationState, ObservationStatus
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.codecs import datetime_from_epoch_microseconds
from src.storage.repositories import (
    AcceptedInputRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import ParkingSessionId, VehicleId


logger = logging.getLogger(__name__)


_ACCEPTED_INPUT_TYPE = "EntryDecision"
_DECISION_STATE_BY_WIRE_VALUE = {
    EntryAccessDecision.ALLOW: EntryDecisionState.ALLOW,
    EntryAccessDecision.DENY: EntryDecisionState.DENY,
    EntryAccessDecision.REVIEW: EntryDecisionState.REVIEW_PENDING,
}


@dataclass(frozen=True, kw_only=True)
class EntryDecisionAcceptance:
    """API 2 성공 응답에 필요한 durable 접수 결과."""

    entry_attempt_id: EntryAttemptId
    decision_revision: int
    created: bool
    accepted_at: datetime
    match_deadline_at: datetime


class EntryEventIntake:
    """입차 결과를 durable matching workflow에 적재한다.

    connection은 요청마다 호출자가 제공한다. intake 인스턴스에 DB
    connection을 보관하지 않으므로 FastAPI worker thread 간에 공유되지 않는다.
    """

    def __init__(
        self,
        coordinator: EntryMatchCoordinator,
        *,
        match_window_seconds: float,
    ) -> None:
        if match_window_seconds <= 0:
            raise ValueError("match_window_seconds must be positive")
        self._coordinator = coordinator
        self._match_window_seconds = match_window_seconds

    def receive(
        self,
        entry_decision: EntryDecisionInput,
        *,
        idempotency_key: str,
        connection: sqlite3.Connection,
    ) -> EntryDecisionAcceptance:
        """신규 접수 또는 동일 domain input retry의 durable 결과를 반환한다.

        domain identity는 ``entryAttemptId + decisionRevision``이다. 동일
        identity가 다른 payload로 재사용되면 ``AcceptedInputConflictError``가
        발생한다. 영수증·attempt·초기 session mirror 삽입 중 하나라도 실패하면
        ``UnitOfWork``가 전체를 rollback한다.
        """

        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")

        entry_attempt_id = EntryAttemptId(entry_decision.entry_attempt_id)
        decision_state = _DECISION_STATE_BY_WIRE_VALUE[entry_decision.access_decision]
        authoritative_context = _authoritative_context(
            entry_decision.session_context,
            decision_state,
        )
        attempt = self._coordinator.open_attempt(
            entry_attempt_id=entry_attempt_id,
            decision_state=decision_state,
            decision_revision=entry_decision.decision_revision,
            created_at=entry_decision.entry_time,
            match_deadline_at=(
                entry_decision.entry_time
                + timedelta(seconds=self._match_window_seconds)
            ),
            authoritative_context=authoritative_context,
        )
        request_payload = _canonical_request_payload(entry_decision)

        # Repository와 connection은 요청 범위에서만 생성·사용한다.
        with UnitOfWork(connection):
            acceptance = AcceptedInputRepository(connection).accept(
                input_type=_ACCEPTED_INPUT_TYPE,
                input_identity=str(entry_attempt_id),
                input_revision=entry_decision.decision_revision,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                workflow_state="ENTRY_MATCH_ATTEMPT_OPENED",
            )
            if acceptance.created:
                EntryMatchAttemptRepository(connection).add(attempt)
                if authoritative_context is not None:
                    ParkingSessionMirrorRepository(connection).add(
                        _initial_session_mirror(
                            entry_attempt_id=entry_attempt_id,
                            decision_revision=entry_decision.decision_revision,
                            context=authoritative_context,
                            received_at=entry_decision.entry_time,
                        )
                    )

        logger.info(
            "입차 결정을 접수했습니다. "
            "entryAttemptId=%s decisionState=%s revision=%d "
            "created=%s matchDeadlineAt=%s",
            entry_attempt_id,
            decision_state.value,
            entry_decision.decision_revision,
            acceptance.created,
            attempt.match_deadline_at.isoformat(),
        )
        return EntryDecisionAcceptance(
            entry_attempt_id=entry_attempt_id,
            decision_revision=entry_decision.decision_revision,
            created=acceptance.created,
            accepted_at=datetime_from_epoch_microseconds(
                acceptance.record.accepted_at_us
            ),
            match_deadline_at=attempt.match_deadline_at,
        )


def _authoritative_context(
    context: EntrySessionContextInput | None,
    decision_state: EntryDecisionState,
) -> SessionContext | None:
    if decision_state is not EntryDecisionState.ALLOW:
        return None
    if context is None:
        raise ValueError("ALLOW EntryDecision requires sessionContext")
    return SessionContext(
        parking_session_id=ParkingSessionId(context.session_id),
        vehicle_id=VehicleId(context.vehicle_id),
        is_electric=context.is_electric,
        is_disabled_vehicle=context.is_disabled_vehicle,
    )


def _canonical_request_payload(entry_decision: EntryDecisionInput) -> bytes:
    """파싱된 EntryDecision을 idempotency 비교용 canonical bytes로 만든다."""

    context = entry_decision.session_context

    return json.dumps(
        {
            "accessDecision": entry_decision.access_decision.value,
            "decisionRevision": entry_decision.decision_revision,
            "entryAttemptId": str(entry_decision.entry_attempt_id),
            "entryTime": entry_decision.entry_time.isoformat(timespec="microseconds"),
            "sessionContext": (
                None
                if context is None
                else {
                    "isDisabledVehicle": context.is_disabled_vehicle,
                    "isElectric": context.is_electric,
                    "sessionId": context.session_id,
                    "vehicleId": context.vehicle_id,
                }
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _initial_session_mirror(
    *,
    entry_attempt_id: EntryAttemptId,
    decision_revision: int,
    context: SessionContext,
    received_at: datetime,
) -> ParkingSessionMirror:
    """ALLOW session을 차량 매칭 전 ``UNCONFIRMED``로 보존한다."""

    return ParkingSessionMirror(
        parking_session_id=context.parking_session_id,
        entry_attempt_id=entry_attempt_id,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
        physical_observation=ObservationStatus(state=ObservationState.UNKNOWN),
        context_revision=decision_revision,
        last_context=context,
        record_version=1,
        publication_revision=0,
        created_at=received_at,
        updated_at=received_at,
    )

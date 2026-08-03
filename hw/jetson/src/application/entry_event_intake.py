"""Legacy 입차 wire를 durable EntryMatchAttempt로 접수하는 application boundary.

현행 ``EntryContext`` 필드명은 후속 API 계약 수정 전까지 보존한다.
이 모듈은 wire 값을 session domain으로 번역하고, inbound 영수증과
``EntryMatchAttempt``를 같은 SQLite transaction에 저장한다. ALLOW로 session을
수신한 경우 아직 차량과 연결되지 않은 ``ParkingSessionMirror``도 같이
저장한다. 차량 매칭은 ``EntryMatchCoordinator``의 후속 tracking
workflow 책임이다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from uuid import UUID

from src.communication.models import EntryContext
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
from src.storage.repositories import (
    AcceptedInputRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import ParkingSessionId, VehicleId


_LEGACY_DECISION_REVISION = 0
_ACCEPTED_INPUT_TYPE = "EntryDecision"
_DECISION_STATE_BY_WIRE_VALUE = {
    "ALLOW": EntryDecisionState.ALLOW,
    "DENY": EntryDecisionState.DENY,
    "REVIEW": EntryDecisionState.REVIEW_PENDING,
}


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
        entry_context: EntryContext,
        *,
        idempotency_key: str,
        connection: sqlite3.Connection,
    ) -> bool:
        """접수 성공 후 True, 동일 domain input retry에 False를 반환한다.

        legacy ``trackingId``를 `entryAttemptId`, revision을 0으로 매핑한
        domain identity가 다른 payload로 재사용되면
        ``AcceptedInputConflictError``가 발생한다. ``Idempotency-Key``는
        현행 transport 호환을 위해 유효성만 검증한다. 영수증·attempt·초기
        session mirror 삽입 중 하나라도 실패하면 ``UnitOfWork``가
        전체를 rollback한다.
        """

        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")

        entry_attempt_id = _parse_entry_attempt_id(entry_context.tracking_id)
        decision_state = _decision_state(entry_context.access_decision)
        authoritative_context = _authoritative_context(entry_context, decision_state)
        attempt = self._coordinator.open_attempt(
            entry_attempt_id=entry_attempt_id,
            decision_state=decision_state,
            decision_revision=_LEGACY_DECISION_REVISION,
            created_at=entry_context.entry_time,
            match_deadline_at=(
                entry_context.entry_time
                + timedelta(seconds=self._match_window_seconds)
            ),
            authoritative_context=authoritative_context,
        )
        request_payload = _canonical_request_payload(entry_context)

        # Repository와 connection은 요청 범위에서만 생성·사용한다.
        with UnitOfWork(connection):
            acceptance = AcceptedInputRepository(connection).accept(
                input_type=_ACCEPTED_INPUT_TYPE,
                # Domain retry identity는 HTTP transport key가 아니라
                # entryAttemptId + decisionRevision이다.
                input_identity=str(entry_attempt_id),
                input_revision=_LEGACY_DECISION_REVISION,
                request_payload=request_payload,
                workflow_state="ENTRY_MATCH_ATTEMPT_OPENED",
            )
            if not acceptance.created:
                return False
            EntryMatchAttemptRepository(connection).add(attempt)
            if authoritative_context is not None:
                ParkingSessionMirrorRepository(connection).add(
                    _initial_session_mirror(
                        entry_attempt_id=entry_attempt_id,
                        context=authoritative_context,
                        received_at=entry_context.entry_time,
                    )
                )

        return True


def _parse_entry_attempt_id(tracking_id: str) -> EntryAttemptId:
    try:
        return EntryAttemptId(UUID(tracking_id))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("trackingId must be a valid UUID entryAttemptId") from error


def _decision_state(access_decision: str) -> EntryDecisionState:
    try:
        return _DECISION_STATE_BY_WIRE_VALUE[access_decision]
    except KeyError as error:
        raise ValueError(
            "legacy accessDecision must be ALLOW, DENY, or REVIEW"
        ) from error


def _authoritative_context(
    entry_context: EntryContext,
    decision_state: EntryDecisionState,
) -> SessionContext | None:
    if decision_state is not EntryDecisionState.ALLOW:
        return None
    if entry_context.session_id is None:
        raise ValueError("ALLOW entry event requires sessionId")
    return SessionContext(
        parking_session_id=ParkingSessionId(entry_context.session_id),
        vehicle_id=(
            None
            if entry_context.vehicle_id is None
            else VehicleId(entry_context.vehicle_id)
        ),
        is_electric=entry_context.is_electric,
        is_disabled_vehicle=entry_context.is_disabled_vehicle,
    )


def _canonical_request_payload(entry_context: EntryContext) -> bytes:
    """Parsed legacy decision을 idempotency 비교용 canonical bytes로 만든다.

    ``duplicateRequest``는 Backend가 같은 decision을 이미 처리했는지
    알리는 transport metadata이다. 재전송에서 값이 바뀌어도 decision과
    authoritative context는 같으므로 durable payload conflict로 보지 않는다.
    """

    return json.dumps(
        {
            "accessDecision": entry_context.access_decision,
            "entryTime": entry_context.entry_time.isoformat(timespec="microseconds"),
            "isDisabledVehicle": entry_context.is_disabled_vehicle,
            "isElectric": entry_context.is_electric,
            "recognizedPlateNumber": entry_context.recognized_plate_number,
            "registered": entry_context.registered,
            "sessionId": entry_context.session_id,
            "trackingId": entry_context.tracking_id,
            "vehicleId": entry_context.vehicle_id,
            "vehicleStatus": entry_context.vehicle_status,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _initial_session_mirror(
    *,
    entry_attempt_id: EntryAttemptId,
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
        context_revision=_LEGACY_DECISION_REVISION,
        last_context=context,
        record_version=1,
        publication_revision=0,
        created_at=received_at,
        updated_at=received_at,
    )

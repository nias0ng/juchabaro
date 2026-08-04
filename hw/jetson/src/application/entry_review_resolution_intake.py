"""API 4 EntryReviewResolution을 기존 입차 시도에 durable하게 적용한다.

REVIEW 해소와 초기 ParkingSessionMirror 생성을 한 transaction에 보존한다.
이미 물리 매칭된 차량의 active binding 또는 historical correlation은 기존
session observation workflow가 이 durable 상태를 이어서 처리한다.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from src.communication.models import (
    EntryReviewResolution,
    EntryReviewResolutionInput,
    EntrySessionContextInput,
    InboundApplicationResult,
)
from src.domain.models import ObservationState, ObservationStatus
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.codecs import datetime_from_epoch_microseconds
from src.storage.repositories import (
    AcceptanceResult,
    AcceptedInputRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import ParkingSessionId, VehicleId


_ACCEPTED_INPUT_TYPE = "EntryReviewResolution"
_DECISION_STATE_BY_RESOLUTION = {
    EntryReviewResolution.REVIEW_ALLOW: EntryDecisionState.REVIEW_ALLOW,
    EntryReviewResolution.REVIEW_DENY: EntryDecisionState.REVIEW_DENY,
    EntryReviewResolution.REVIEW_EXPIRED: EntryDecisionState.REVIEW_EXPIRED,
}


class EntryReviewResolutionNotFoundError(LookupError):
    """해소할 EntryMatchAttempt가 Jetson durable state에 없다."""


@dataclass(frozen=True, kw_only=True)
class EntryReviewResolutionAcceptance:
    """API 4 durable acceptance 응답에 필요한 값."""

    entry_attempt_id: EntryAttemptId
    decision_revision: int
    application_result: InboundApplicationResult
    accepted_at: datetime
    match_state: EntryMatchState
    match_deadline_at: datetime


class EntryReviewResolutionIntake:
    """REVIEW_PENDING attempt의 revisioned 후속 결정을 접수한다."""

    def __init__(self, coordinator: EntryMatchCoordinator) -> None:
        self._coordinator = coordinator

    def receive(
        self,
        resolution: EntryReviewResolutionInput,
        *,
        idempotency_key: str,
        connection: sqlite3.Connection,
    ) -> EntryReviewResolutionAcceptance:
        """같은 domain input은 재적용하지 않고 기존 접수 결과를 반환한다."""

        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")

        entry_attempt_id = EntryAttemptId(resolution.entry_attempt_id)
        request_payload = _canonical_request_payload(resolution)
        attempt_repository = EntryMatchAttemptRepository(connection)

        with UnitOfWork(connection):
            attempt = attempt_repository.get(entry_attempt_id)
            if attempt is None:
                raise EntryReviewResolutionNotFoundError(
                    f"EntryMatchAttempt를 찾을 수 없습니다: {entry_attempt_id}"
                )

            is_stale = resolution.decision_revision < attempt.decision_revision
            acceptance = AcceptedInputRepository(connection).accept(
                input_type=_ACCEPTED_INPUT_TYPE,
                input_identity=str(entry_attempt_id),
                input_revision=resolution.decision_revision,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                workflow_state=(
                    "ENTRY_REVIEW_STALE"
                    if is_stale
                    else "ENTRY_REVIEW_RESOLVED"
                ),
            )
            if acceptance.created and not is_stale:
                context = _authoritative_context(resolution.session_context)
                updated_attempt = self._coordinator.apply_decision(
                    attempt,
                    decision_state=_DECISION_STATE_BY_RESOLUTION[
                        resolution.resolution
                    ],
                    decision_revision=resolution.decision_revision,
                    updated_at=resolution.resolved_at,
                    authoritative_context=context,
                )
                if updated_attempt.record_version != attempt.record_version:
                    attempt_repository.save(
                        updated_attempt,
                        expected_record_version=attempt.record_version,
                    )
                attempt = updated_attempt

                if context is not None:
                    ParkingSessionMirrorRepository(connection).add(
                        _initial_session_mirror(
                            entry_attempt_id=entry_attempt_id,
                            decision_revision=resolution.decision_revision,
                            context=context,
                            received_at=resolution.resolved_at,
                        )
                    )

        return EntryReviewResolutionAcceptance(
            entry_attempt_id=entry_attempt_id,
            decision_revision=resolution.decision_revision,
            application_result=_application_result(acceptance),
            accepted_at=datetime_from_epoch_microseconds(
                acceptance.record.accepted_at_us
            ),
            match_state=attempt.match_state,
            match_deadline_at=attempt.match_deadline_at,
        )


def _authoritative_context(
    context: EntrySessionContextInput | None,
) -> SessionContext | None:
    if context is None:
        return None
    return SessionContext(
        parking_session_id=ParkingSessionId(context.session_id),
        vehicle_id=VehicleId(context.vehicle_id),
        is_electric=context.is_electric,
        is_disabled_vehicle=context.is_disabled_vehicle,
    )


def _application_result(
    acceptance: AcceptanceResult,
) -> InboundApplicationResult:
    if acceptance.record.workflow_state == "ENTRY_REVIEW_STALE":
        return InboundApplicationResult.STALE
    if not acceptance.created:
        return InboundApplicationResult.ALREADY_APPLIED
    return InboundApplicationResult.APPLIED


def _initial_session_mirror(
    *,
    entry_attempt_id: EntryAttemptId,
    decision_revision: int,
    context: SessionContext,
    received_at: datetime,
) -> ParkingSessionMirror:
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


def _canonical_request_payload(
    resolution: EntryReviewResolutionInput,
) -> bytes:
    context = resolution.session_context
    return json.dumps(
        {
            "decisionRevision": resolution.decision_revision,
            "entryAttemptId": str(resolution.entry_attempt_id),
            "resolution": resolution.resolution.value,
            "resolvedAt": resolution.resolved_at.isoformat(timespec="microseconds"),
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

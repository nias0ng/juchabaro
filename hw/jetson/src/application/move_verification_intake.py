"""API 11 MoveVerification command를 durable 재확인 scope로 접수한다.

대상 Incident의 존재와 동일 subject PhysicalVehicle 조건을 확인한 뒤 ACCEPTED
workflow만 저장한다. 실제 재확인 및 API 12 결과 생성은 이 경계의 책임이 아니다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from src.communication.models import (
    InboundApplicationResult,
    MoveRequestId,
    MoveVerificationAttempt,
    MoveVerificationCommandInput,
    MoveVerificationState,
)
from src.parking.models import Incident, IncidentId
from src.storage.aggregate_repositories import IncidentRepository
from src.storage.codecs import datetime_from_epoch_microseconds
from src.storage.repositories import (
    AcceptanceResult,
    AcceptedInputRepository,
    MoveVerificationAttemptRepository,
)
from src.storage.unit_of_work import UnitOfWork


_ACCEPTED_INPUT_TYPE = "MoveVerificationCommand"
VerificationClock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MoveVerificationIncidentNotFoundError(LookupError):
    """command가 지정한 Incident가 Jetson durable state에 없다."""


class MoveVerificationCommandConflictError(RuntimeError):
    """verificationAttempt 순서 또는 target subject가 기존 상태와 충돌한다."""


@dataclass(frozen=True, kw_only=True)
class MoveVerificationAcceptance:
    """API 11 durable acceptance 응답에 필요한 값."""

    request_id: MoveRequestId
    verification_attempt: int
    application_result: InboundApplicationResult
    accepted_at: datetime


class MoveVerificationIntake:
    """같은 PhysicalVehicle의 Incident 재확인 command를 한 번만 적재한다."""

    def __init__(self, *, clock: VerificationClock = _utc_now) -> None:
        self._clock = clock

    def receive(
        self,
        command: MoveVerificationCommandInput,
        *,
        idempotency_key: str,
        connection: sqlite3.Connection,
    ) -> MoveVerificationAcceptance:
        if not idempotency_key or not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")

        request_id = MoveRequestId(command.request_id)
        target_incident_ids = tuple(
            IncidentId(incident_id) for incident_id in command.target_incident_ids
        )
        request_payload = _canonical_request_payload(command)
        attempt_repository = MoveVerificationAttemptRepository(connection)

        with UnitOfWork(connection):
            latest = attempt_repository.get_latest(request_id)
            is_stale = (
                command.deadline_at < self._clock()
                or (
                    latest is not None
                    and command.verification_attempt
                    < latest.verification_attempt
                )
            )
            acceptance = AcceptedInputRepository(connection).accept(
                input_type=_ACCEPTED_INPUT_TYPE,
                input_identity=str(int(request_id)),
                input_revision=command.verification_attempt,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
                workflow_state=(
                    "MOVE_VERIFICATION_STALE"
                    if is_stale
                    else "MOVE_VERIFICATION_ACCEPTED"
                ),
            )
            if acceptance.created and not is_stale:
                if (
                    latest is not None
                    and command.verification_attempt
                    <= latest.verification_attempt
                ):
                    raise MoveVerificationCommandConflictError(
                        "verificationAttempt가 기존 command보다 크지 않습니다."
                    )

                incidents = tuple(
                    _require_incident(incident_id, connection=connection)
                    for incident_id in target_incident_ids
                )
                subject_ids = {
                    incident.physical_vehicle_id for incident in incidents
                }
                if len(subject_ids) != 1:
                    raise MoveVerificationCommandConflictError(
                        "모든 target Incident는 같은 subject PhysicalVehicle이어야 합니다."
                    )

                accepted_at = datetime_from_epoch_microseconds(
                    acceptance.record.accepted_at_us
                )
                attempt_repository.add(
                    MoveVerificationAttempt(
                        request_id=request_id,
                        verification_attempt=command.verification_attempt,
                        subject_physical_vehicle_id=next(iter(subject_ids)),
                        target_incident_ids=target_incident_ids,
                        command_payload_hash=hashlib.sha256(
                            request_payload
                        ).hexdigest(),
                        state=MoveVerificationState.ACCEPTED,
                        deadline_at=command.deadline_at,
                        record_version=1,
                        publication_revision=0,
                        accepted_at=accepted_at,
                        updated_at=accepted_at,
                    )
                )

        return MoveVerificationAcceptance(
            request_id=request_id,
            verification_attempt=command.verification_attempt,
            application_result=_application_result(acceptance),
            accepted_at=datetime_from_epoch_microseconds(
                acceptance.record.accepted_at_us
            ),
    )


def _application_result(
    acceptance: AcceptanceResult,
) -> InboundApplicationResult:
    if acceptance.record.workflow_state == "MOVE_VERIFICATION_STALE":
        return InboundApplicationResult.STALE
    if not acceptance.created:
        return InboundApplicationResult.ALREADY_APPLIED
    return InboundApplicationResult.APPLIED


def _require_incident(
    incident_id: IncidentId,
    *,
    connection: sqlite3.Connection,
) -> Incident:
    incident = IncidentRepository(connection).get(incident_id)
    if incident is None:
        raise MoveVerificationIncidentNotFoundError(
            f"Incident를 찾을 수 없습니다: {incident_id}"
        )
    return incident


def _canonical_request_payload(command: MoveVerificationCommandInput) -> bytes:
    return json.dumps(
        {
            "deadlineAt": command.deadline_at.isoformat(timespec="microseconds"),
            "requestId": command.request_id,
            "requestedAt": command.requested_at.isoformat(timespec="microseconds"),
            "targetIncidentIds": [
                str(incident_id) for incident_id in command.target_incident_ids
            ],
            "verificationAttempt": command.verification_attempt,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

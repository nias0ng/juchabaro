"""RPi EntryDecision 접수와 EntryMatchOutcome 조회 내부 API.

API 2는 ``entryAttemptId + decisionRevision`` identity를 durable storage에
commit한 뒤 202를 반환한다. API 3은 같은 entryAttemptId의 현재 물리 차량
매칭 상태를 읽는다. api 계층은 wire parsing·인증·HTTP 오류 mapping만 맡고,
저장·조회 의미는 application service에 위임한다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.application.entry_event_intake import EntryEventIntake
from src.application.entry_match_query import (
    EntryMatchNotFoundError,
    EntryMatchQuery,
)
from src.communication.models import (
    EntryAccessDecision,
    EntryDecisionInput,
    EntrySessionContextInput,
)
from src.config.settings import get_settings
from src.session.models import EntryMatchState
from src.storage.repositories import (
    AcceptedInputConflictError,
    EntryMatchAttemptConflictError,
    ParkingSessionMirrorConflictError,
)


router = APIRouter(prefix="/internal", tags=["Internal"])
_entry_match_query = EntryMatchQuery()


class EntrySessionContextPayload(BaseModel):
    """ALLOW EntryDecision에 포함되는 Backend authoritative context."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: int = Field(alias="sessionId", strict=True, gt=0)
    vehicle_id: int = Field(alias="vehicleId", strict=True, gt=0)
    is_disabled_vehicle: bool = Field(alias="isDisabledVehicle", strict=True)
    is_electric: bool = Field(alias="isElectric", strict=True)

    def to_input(self) -> EntrySessionContextInput:
        return EntrySessionContextInput(
            session_id=self.session_id,
            vehicle_id=self.vehicle_id,
            is_disabled_vehicle=self.is_disabled_vehicle,
            is_electric=self.is_electric,
        )


class EntryEventPayload(BaseModel):
    """API 2 ``POST /internal/entry-events`` camelCase request."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    entry_attempt_id: UUID = Field(alias="entryAttemptId")
    decision_revision: int = Field(alias="decisionRevision", strict=True, gt=0)
    access_decision: EntryAccessDecision = Field(alias="accessDecision")
    entry_time: datetime = Field(alias="entryTime")
    session_context: EntrySessionContextPayload | None = Field(
        alias="sessionContext"
    )

    @field_validator("entry_time")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("entryTime은 timezone-aware여야 합니다(naive datetime 불가).")
        return value

    @model_validator(mode="after")
    def _validate_session_context(self) -> EntryEventPayload:
        if self.access_decision is EntryAccessDecision.ALLOW:
            if self.session_context is None:
                raise ValueError("ALLOW 요청에는 sessionContext가 필요합니다.")
        elif self.session_context is not None:
            raise ValueError("REVIEW 또는 DENY 요청의 sessionContext는 null이어야 합니다.")
        return self

    def to_input(self) -> EntryDecisionInput:
        return EntryDecisionInput(
            entry_attempt_id=self.entry_attempt_id,
            decision_revision=self.decision_revision,
            access_decision=self.access_decision,
            entry_time=self.entry_time,
            session_context=(
                None
                if self.session_context is None
                else self.session_context.to_input()
            ),
        )


def get_entry_event_intake(request: Request) -> EntryEventIntake:
    """``main.py``가 기동 시 app state에 구성한 intake를 반환한다."""

    return request.app.state.entry_event_intake


def get_entry_match_query() -> EntryMatchQuery:
    """상태 없는 read application service를 반환한다."""

    return _entry_match_query


def verify_internal_api_key(
    x_internal_api_key: str = Header(alias="X-Internal-API-Key"),
) -> None:
    if x_internal_api_key != get_settings().internal_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-API-Key가 올바르지 않습니다.",
        )


def _success_envelope(
    *,
    http_status: str,
    code: int,
    message: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "httpStatus": http_status,
        "isSuccess": True,
        "message": message,
        "code": code,
        "result": result,
    }


@router.post(
    "/entry-events",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_api_key)],
)
def receive_entry_event(
    request: Request,
    payload: EntryEventPayload,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    intake: EntryEventIntake = Depends(get_entry_event_intake),
) -> dict[str, Any]:
    """EntryDecision과 초기 matching workflow를 durable하게 접수한다."""

    connection: sqlite3.Connection | None = None
    try:
        connection = request.app.state.database_connection_factory()
        acceptance = intake.receive(
            payload.to_input(),
            idempotency_key=idempotency_key,
            connection=connection,
        )
    except (
        AcceptedInputConflictError,
        EntryMatchAttemptConflictError,
        ParkingSessionMirrorConflictError,
    ) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except sqlite3.OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jetson durable storage를 일시적으로 사용할 수 없습니다.",
        ) from error
    finally:
        if connection is not None:
            connection.close()

    return _success_envelope(
        http_status="ACCEPTED",
        code=status.HTTP_202_ACCEPTED,
        message="입차 판정이 durable하게 접수되었습니다.",
        result={
            "entryAttemptId": str(acceptance.entry_attempt_id),
            "decisionRevision": acceptance.decision_revision,
            "acceptanceStatus": (
                "ACCEPTED" if acceptance.created else "ALREADY_ACCEPTED"
            ),
            "matchState": EntryMatchState.PENDING.value,
            "acceptedAt": acceptance.accepted_at.isoformat(),
            "matchDeadlineAt": acceptance.match_deadline_at.isoformat(),
        },
    )


@router.get(
    "/entry-events/{entry_attempt_id}",
    dependencies=[Depends(verify_internal_api_key)],
)
def get_entry_match_outcome(
    request: Request,
    entry_attempt_id: UUID,
    query: EntryMatchQuery = Depends(get_entry_match_query),
) -> dict[str, Any]:
    """entryAttemptId와 PhysicalVehicle의 현재 match 상태를 반환한다."""

    connection: sqlite3.Connection | None = None
    try:
        connection = request.app.state.database_connection_factory()
        outcome = query.get(entry_attempt_id, connection=connection)
    except EntryMatchNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except sqlite3.OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jetson durable storage를 일시적으로 사용할 수 없습니다.",
        ) from error
    finally:
        if connection is not None:
            connection.close()

    return _success_envelope(
        http_status="OK",
        code=status.HTTP_200_OK,
        message="입차 차량 매칭 상태입니다.",
        result={
            "entryAttemptId": str(outcome.entry_attempt_id),
            "decisionRevision": outcome.decision_revision,
            "accessDecision": outcome.access_decision.value,
            "matchState": outcome.match_state.value,
            "physicalVehicleId": (
                None
                if outcome.physical_vehicle_id is None
                else str(outcome.physical_vehicle_id)
            ),
            "matchedAt": (
                None if outcome.matched_at is None else outcome.matched_at.isoformat()
            ),
            "terminalReason": outcome.terminal_reason,
            "matchDeadlineAt": outcome.match_deadline_at.isoformat(),
        },
    )

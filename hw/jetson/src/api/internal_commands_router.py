"""Backend가 Jetson으로 보내는 API 4·5·11 내부 command 라우터.

wire parsing·인증·HTTP 오류 mapping만 담당하고 durable workflow 의미는 각
application intake에 위임한다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.api.error_handlers import JetsonApiError
from src.api.entry_events_router import _success_envelope, verify_internal_api_key
from src.application.entry_review_resolution_intake import (
    EntryReviewResolutionIntake,
    EntryReviewResolutionNotFoundError,
)
from src.application.move_verification_intake import (
    MoveVerificationCommandConflictError,
    MoveVerificationIncidentNotFoundError,
    MoveVerificationIntake,
)
from src.application.session_context_update_intake import (
    SessionContextUpdateConflictError,
    SessionContextUpdateIntake,
    SessionContextUpdateNotFoundError,
)
from src.communication.models import (
    EntryReviewResolution,
    EntryReviewResolutionInput,
    EntrySessionContextInput,
    MoveVerificationCommandInput,
    SessionContextUpdateContextInput,
    SessionContextUpdateInput,
)
from src.session.context_binding_coordinator import ContextBindingError
from src.session.entry_match_coordinator import EntryMatchTransitionError
from src.session.models import SessionAdministrativeState
from src.storage.repositories import (
    AcceptedInputConflictError,
    ContextBindingConflictError,
    EntryMatchAttemptConflictError,
    MoveVerificationAttemptConflictError,
    OptimisticConcurrencyError,
    ParkingSessionMirrorConflictError,
)


router = APIRouter(prefix="/internal", tags=["Internal"])


def _require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(
            f"{field_name}은 timezone-aware여야 합니다(naive datetime 불가)."
        )
    return value


class EntryReviewSessionContextPayload(BaseModel):
    """REVIEW_ALLOW에 포함되는 Backend authoritative context."""

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


class EntryReviewResolutionPayload(BaseModel):
    """API 4 camelCase request."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    entry_attempt_id: UUID = Field(alias="entryAttemptId")
    decision_revision: int = Field(alias="decisionRevision", strict=True, gt=0)
    resolution: EntryReviewResolution
    resolved_at: datetime = Field(alias="resolvedAt")
    session_context: EntryReviewSessionContextPayload | None = Field(
        alias="sessionContext"
    )

    @field_validator("resolved_at")
    @classmethod
    def _validate_resolved_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, "resolvedAt")

    @model_validator(mode="after")
    def _validate_session_context(self) -> EntryReviewResolutionPayload:
        if self.resolution is EntryReviewResolution.REVIEW_ALLOW:
            if self.session_context is None:
                raise ValueError("REVIEW_ALLOW에는 sessionContext가 필요합니다.")
        elif self.session_context is not None:
            raise ValueError(
                "REVIEW_DENY 또는 REVIEW_EXPIRED의 sessionContext는 null이어야 합니다."
            )
        return self

    def to_input(self) -> EntryReviewResolutionInput:
        return EntryReviewResolutionInput(
            entry_attempt_id=self.entry_attempt_id,
            decision_revision=self.decision_revision,
            resolution=self.resolution,
            resolved_at=self.resolved_at,
            session_context=(
                None
                if self.session_context is None
                else self.session_context.to_input()
            ),
        )


class SessionContextPayload(BaseModel):
    """API 5 sessionContext wire payload."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    vehicle_id: int = Field(alias="vehicleId", strict=True, gt=0)
    is_disabled_vehicle: bool = Field(alias="isDisabledVehicle", strict=True)
    is_electric: bool = Field(alias="isElectric", strict=True)

    def to_input(self) -> SessionContextUpdateContextInput:
        return SessionContextUpdateContextInput(
            vehicle_id=self.vehicle_id,
            is_disabled_vehicle=self.is_disabled_vehicle,
            is_electric=self.is_electric,
        )


class SessionContextUpdatePayload(BaseModel):
    """API 5 camelCase request."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    session_id: int = Field(alias="sessionId", strict=True, gt=0)
    entry_attempt_id: UUID = Field(alias="entryAttemptId")
    context_revision: int = Field(alias="contextRevision", strict=True, gt=0)
    administrative_state: SessionAdministrativeState = Field(
        alias="administrativeState"
    )
    updated_at: datetime = Field(alias="updatedAt")
    session_context: SessionContextPayload = Field(alias="sessionContext")

    @field_validator("updated_at")
    @classmethod
    def _validate_updated_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, "updatedAt")

    def to_input(self) -> SessionContextUpdateInput:
        return SessionContextUpdateInput(
            session_id=self.session_id,
            entry_attempt_id=self.entry_attempt_id,
            context_revision=self.context_revision,
            administrative_state=self.administrative_state.value,
            updated_at=self.updated_at,
            session_context=self.session_context.to_input(),
        )


class MoveVerificationPayload(BaseModel):
    """API 11 camelCase request."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    request_id: int = Field(alias="requestId", strict=True, gt=0)
    verification_attempt: int = Field(
        alias="verificationAttempt",
        strict=True,
        gt=0,
    )
    target_incident_ids: tuple[UUID, ...] = Field(
        alias="targetIncidentIds",
        min_length=1,
    )
    requested_at: datetime = Field(alias="requestedAt")
    deadline_at: datetime = Field(alias="deadlineAt")

    @field_validator("requested_at")
    @classmethod
    def _validate_requested_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, "requestedAt")

    @field_validator("deadline_at")
    @classmethod
    def _validate_deadline_at(cls, value: datetime) -> datetime:
        return _require_aware_datetime(value, "deadlineAt")

    @model_validator(mode="after")
    def _validate_command(self) -> MoveVerificationPayload:
        if len(set(self.target_incident_ids)) != len(self.target_incident_ids):
            raise ValueError("targetIncidentIds는 중복될 수 없습니다.")
        if self.deadline_at < self.requested_at:
            raise ValueError("deadlineAt은 requestedAt보다 빠를 수 없습니다.")
        return self

    def to_input(self) -> MoveVerificationCommandInput:
        return MoveVerificationCommandInput(
            request_id=self.request_id,
            verification_attempt=self.verification_attempt,
            target_incident_ids=self.target_incident_ids,
            requested_at=self.requested_at,
            deadline_at=self.deadline_at,
        )


def get_entry_review_resolution_intake(
    request: Request,
) -> EntryReviewResolutionIntake:
    return request.app.state.entry_review_resolution_intake


def get_session_context_update_intake(
    request: Request,
) -> SessionContextUpdateIntake:
    return request.app.state.session_context_update_intake


def get_move_verification_intake(request: Request) -> MoveVerificationIntake:
    return request.app.state.move_verification_intake


_CONFLICT_ERRORS = (
    ContextBindingConflictError,
    ContextBindingError,
    EntryMatchAttemptConflictError,
    EntryMatchTransitionError,
    MoveVerificationAttemptConflictError,
    MoveVerificationCommandConflictError,
    OptimisticConcurrencyError,
    ParkingSessionMirrorConflictError,
    SessionContextUpdateConflictError,
)


def _command_ack(
    *,
    aggregate_type: str,
    aggregate_id: str,
    revision: int,
    application_result: str,
    accepted_at: datetime,
) -> dict[str, object]:
    """Backend ``HwPublicationAck``와 대칭인 durable command ACK."""

    return {
        "aggregateType": aggregate_type,
        "aggregateId": aggregate_id,
        "publicationRevision": revision,
        "applicationResult": application_result,
        "backendCorrelation": {
            "acceptedAt": accepted_at.isoformat(),
        },
    }


@router.post(
    "/entry-review-resolutions",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_api_key)],
)
def receive_entry_review_resolution(
    request: Request,
    payload: EntryReviewResolutionPayload,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    intake: EntryReviewResolutionIntake = Depends(
        get_entry_review_resolution_intake
    ),
) -> dict[str, Any]:
    connection: sqlite3.Connection | None = None
    try:
        connection = request.app.state.database_connection_factory()
        acceptance = intake.receive(
            payload.to_input(),
            idempotency_key=idempotency_key,
            connection=connection,
        )
    except EntryReviewResolutionNotFoundError as error:
        raise JetsonApiError(
            status_code=404,
            error_type="TARGET_NOT_FOUND",
            message=str(error),
        ) from error
    except AcceptedInputConflictError as error:
        raise JetsonApiError(
            status_code=409,
            error_type="IDEMPOTENCY_CONFLICT",
            message=str(error),
        ) from error
    except _CONFLICT_ERRORS as error:
        raise JetsonApiError(
            status_code=409,
            error_type="STATE_CONFLICT",
            message=str(error),
        ) from error
    except ValueError as error:
        raise JetsonApiError(
            status_code=422,
            error_type="INVALID_REQUEST",
            message=str(error),
        ) from error
    except sqlite3.OperationalError as error:
        raise JetsonApiError(
            status_code=503,
            error_type="DURABLE_STORAGE_UNAVAILABLE",
            message="Jetson durable storage를 일시적으로 사용할 수 없습니다.",
            retryable=True,
        ) from error
    finally:
        if connection is not None:
            connection.close()

    return _success_envelope(
        http_status="ACCEPTED",
        code=202,
        message="입차 검토 후속 판정이 durable하게 접수되었습니다.",
        result=_command_ack(
            aggregate_type="EntryReviewResolution",
            aggregate_id=str(acceptance.entry_attempt_id),
            revision=acceptance.decision_revision,
            application_result=acceptance.application_result.value,
            accepted_at=acceptance.accepted_at,
        ),
    )


@router.post(
    "/session-context-updates",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_api_key)],
)
def receive_session_context_update(
    request: Request,
    payload: SessionContextUpdatePayload,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    intake: SessionContextUpdateIntake = Depends(
        get_session_context_update_intake
    ),
) -> dict[str, Any]:
    connection: sqlite3.Connection | None = None
    try:
        connection = request.app.state.database_connection_factory()
        acceptance = intake.receive(
            payload.to_input(),
            idempotency_key=idempotency_key,
            connection=connection,
        )
    except SessionContextUpdateNotFoundError as error:
        raise JetsonApiError(
            status_code=404,
            error_type="TARGET_NOT_FOUND",
            message=str(error),
        ) from error
    except AcceptedInputConflictError as error:
        raise JetsonApiError(
            status_code=409,
            error_type="IDEMPOTENCY_CONFLICT",
            message=str(error),
        ) from error
    except _CONFLICT_ERRORS as error:
        raise JetsonApiError(
            status_code=409,
            error_type="STATE_CONFLICT",
            message=str(error),
        ) from error
    except ValueError as error:
        raise JetsonApiError(
            status_code=422,
            error_type="INVALID_REQUEST",
            message=str(error),
        ) from error
    except sqlite3.OperationalError as error:
        raise JetsonApiError(
            status_code=503,
            error_type="DURABLE_STORAGE_UNAVAILABLE",
            message="Jetson durable storage를 일시적으로 사용할 수 없습니다.",
            retryable=True,
        ) from error
    finally:
        if connection is not None:
            connection.close()

    return _success_envelope(
        http_status="ACCEPTED",
        code=202,
        message="세션 문맥 변경이 durable하게 접수되었습니다.",
        result=_command_ack(
            aggregate_type="SessionContextUpdate",
            aggregate_id=str(int(acceptance.session_id)),
            revision=acceptance.context_revision,
            application_result=acceptance.application_result.value,
            accepted_at=acceptance.accepted_at,
        ),
    )


@router.post(
    "/move-verifications",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_internal_api_key)],
)
def receive_move_verification(
    request: Request,
    payload: MoveVerificationPayload,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    intake: MoveVerificationIntake = Depends(get_move_verification_intake),
) -> dict[str, Any]:
    connection: sqlite3.Connection | None = None
    try:
        connection = request.app.state.database_connection_factory()
        acceptance = intake.receive(
            payload.to_input(),
            idempotency_key=idempotency_key,
            connection=connection,
        )
    except MoveVerificationIncidentNotFoundError as error:
        raise JetsonApiError(
            status_code=404,
            error_type="TARGET_NOT_FOUND",
            message=str(error),
        ) from error
    except AcceptedInputConflictError as error:
        raise JetsonApiError(
            status_code=409,
            error_type="IDEMPOTENCY_CONFLICT",
            message=str(error),
        ) from error
    except _CONFLICT_ERRORS as error:
        raise JetsonApiError(
            status_code=409,
            error_type="STATE_CONFLICT",
            message=str(error),
        ) from error
    except ValueError as error:
        raise JetsonApiError(
            status_code=422,
            error_type="INVALID_REQUEST",
            message=str(error),
        ) from error
    except sqlite3.OperationalError as error:
        raise JetsonApiError(
            status_code=503,
            error_type="DURABLE_STORAGE_UNAVAILABLE",
            message="Jetson durable storage를 일시적으로 사용할 수 없습니다.",
            retryable=True,
        ) from error
    finally:
        if connection is not None:
            connection.close()

    return _success_envelope(
        http_status="ACCEPTED",
        code=202,
        message="현장 재확인 명령이 durable하게 접수되었습니다.",
        result=_command_ack(
            aggregate_type="MoveVerification",
            aggregate_id=str(int(acceptance.request_id)),
            revision=acceptance.verification_attempt,
            application_result=acceptance.application_result.value,
            accepted_at=acceptance.accepted_at,
        ),
    )

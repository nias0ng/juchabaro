"""라즈베리파이가 보내는 입차 결과를 받는 내부 라우트(383 미해결분, T-16).

`hw/raspberry-pi/src/communication/jetson_client.py`(`JetsonClient.ENTRY_PATH`)가
이 경로로 `X-Internal-API-Key`·`Idempotency-Key` 헤더와 함께 payload를
보낸다. `X-Internal-API-Key`는 데이터흐름.md §7이 명시한 api 계층의 책임
("인증 헤더 확인")이라 여기서 검증한다 — 라즈베리파이 클라이언트는 이미 이
헤더를 보내도록 구현돼 있다(`test_clients.py`가 고정).

현행 wire 호환을 위해 `Idempotency-Key` 헤더를 요구한다. durable
재전송 identity는 후속 API 계약의 `entryAttemptId + decisionRevision`이며,
현재 legacy wire에서는 `trackingId + revision 0`으로 매핑한다.

api는 wire 파싱·인증·HTTP 오류 mapping만 소유한다. 입차 decision의
domain 변환과 durable transaction은
`application.entry_event_intake.EntryEventIntake`를 거친다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.application.entry_event_intake import EntryEventIntake
from src.communication.models import EntryContext
from src.config.settings import get_settings
from src.storage.repositories import (
    AcceptedInputConflictError,
    EntryMatchAttemptConflictError,
    ParkingSessionMirrorConflictError,
)

router = APIRouter(prefix="/internal", tags=["Internal"])


class EntryEventPayload(BaseModel):
    """`POST /internal/entry-events`의 요청 본문(camelCase wire 계약)."""

    model_config = ConfigDict(populate_by_name=True)

    tracking_id: str = Field(alias="trackingId")
    recognized_plate_number: str = Field(alias="recognizedPlateNumber")
    entry_time: datetime = Field(alias="entryTime")
    access_decision: str = Field(alias="accessDecision")
    registered: bool
    vehicle_id: int | None = Field(default=None, alias="vehicleId")
    is_disabled_vehicle: bool | None = Field(default=None, alias="isDisabledVehicle")
    is_electric: bool | None = Field(default=None, alias="isElectric")
    vehicle_status: str | None = Field(default=None, alias="vehicleStatus")
    session_id: int | None = Field(default=None, alias="sessionId")
    duplicate_request: bool = Field(alias="duplicateRequest")

    @field_validator("entry_time")
    @classmethod
    def _require_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("entryTime은 timezone-aware여야 합니다(naive datetime 불가).")
        return value

    def to_entry_context(self) -> EntryContext:
        return EntryContext(
            tracking_id=self.tracking_id,
            recognized_plate_number=self.recognized_plate_number,
            entry_time=self.entry_time,
            access_decision=self.access_decision,
            registered=self.registered,
            vehicle_id=self.vehicle_id,
            is_disabled_vehicle=self.is_disabled_vehicle,
            is_electric=self.is_electric,
            vehicle_status=self.vehicle_status,
            session_id=self.session_id,
            duplicate_request=self.duplicate_request,
        )


def get_entry_event_intake(request: Request) -> EntryEventIntake:
    """`main.py`가 기동 시 `app.state.entry_event_intake`에 심어 둔 싱글턴을 반환한다."""

    return request.app.state.entry_event_intake


def verify_internal_api_key(x_internal_api_key: str = Header(alias="X-Internal-API-Key")) -> None:
    if x_internal_api_key != get_settings().internal_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-Internal-API-Key가 올바르지 않습니다.")


@router.post("/entry-events", status_code=202, dependencies=[Depends(verify_internal_api_key)])
def receive_entry_event(
    request: Request,
    payload: EntryEventPayload,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    intake: EntryEventIntake = Depends(get_entry_event_intake),
) -> dict[str, bool]:
    # sync yield dependency와 endpoint가 서로 다른 worker thread에서
    # 실행될 수 있다. SQLite connection을 실제 사용하는
    # endpoint 안에서 열고 닫아 check_same_thread 계약을 지킨다.
    connection = request.app.state.database_connection_factory()
    try:
        try:
            accepted = intake.receive(
                payload.to_entry_context(),
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
    finally:
        connection.close()
    return {"accepted": accepted}

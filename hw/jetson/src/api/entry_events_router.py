"""라즈베리파이가 보내는 입차 결과를 받는 내부 라우트(383 미해결분, T-16).

`hw/raspberry-pi/src/communication/schemas.py`의 `JetsonEntryRequest`가 이
경로로 보내는 payload를 파싱해 `ContextMatcher`의 매칭 대기열에 넣는다.
백엔드 호출(ALLOW/DENY 판정)은 라즈베리파이가 이미 끝낸 뒤이므로, 여기서는
그 결과를 받아 적재하기만 한다(383의 `entry_event_intake.py` 설계 그대로).

`Idempotency-Key` 헤더로 재전송 중복을 막는다 — 라즈베리파이는 네트워크
재시도 시 같은 키로 같은 이벤트를 다시 보낼 수 있다.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.communication.models import EntryContext
from src.tracking.context_matcher import ContextMatcher

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


def get_context_matcher(request: Request) -> ContextMatcher:
    """`main.py`가 기동 시 `app.state.context_matcher`에 심어 둔 싱글턴을 반환한다."""

    return request.app.state.context_matcher


@router.post("/entry-events", status_code=202)
def receive_entry_event(
    payload: EntryEventPayload,
    idempotency_key: str = Header(alias="Idempotency-Key"),
    matcher: ContextMatcher = Depends(get_context_matcher),
) -> dict[str, bool]:
    accepted = matcher.add_entry_context(payload.to_entry_context(), idempotency_key=idempotency_key)
    return {"accepted": accepted}

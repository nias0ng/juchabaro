"""외부 API 통신에 사용하는 요청·응답 데이터 계약."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping


class AccessDecision(str, Enum):
    """Backend가 반환하는 최종 출입 판정."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REVIEW = "REVIEW"


def _to_iso8601(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("entry_time은 시간대가 포함된 datetime이어야 합니다.")
    return value.isoformat()


@dataclass(frozen=True, slots=True)
class BackendEntryRequest:
    """Raspberry Pi가 Backend 입차 판정 API로 보내는 데이터."""

    tracking_id: str
    recognized_plate_number: str
    entry_time: datetime
    ocr_confidence: float | None = None

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "trackingId": self.tracking_id,
            "recognizedPlateNumber": self.recognized_plate_number,
            "entryTime": _to_iso8601(self.entry_time),
        }
        if self.ocr_confidence is not None:
            payload["ocrConfidence"] = self.ocr_confidence
        return payload


@dataclass(frozen=True, slots=True)
class BackendEntryResult:
    """Backend 입차 판정 API의 ``result`` 데이터."""

    access_decision: AccessDecision
    registered: bool
    vehicle_id: int | None
    is_disabled_vehicle: bool | None
    is_electric: bool | None
    vehicle_status: str | None
    tracking_id: str
    session_id: int | None
    duplicate_request: bool

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> BackendEntryResult:
        return cls(
            access_decision=AccessDecision(payload["accessDecision"]),
            registered=payload["registered"],
            vehicle_id=payload["vehicleId"],
            is_disabled_vehicle=payload["isDisabledVehicle"],
            is_electric=payload["isElectric"],
            vehicle_status=payload["vehicleStatus"],
            tracking_id=payload["trackingId"],
            session_id=payload["sessionId"],
            duplicate_request=payload["duplicateRequest"],
        )


@dataclass(frozen=True, slots=True)
class JetsonEntryRequest:
    """Raspberry Pi가 Jetson 입차 이벤트 API로 보내는 데이터."""

    tracking_id: str
    recognized_plate_number: str
    entry_time: datetime
    access_decision: AccessDecision
    registered: bool
    vehicle_id: int | None
    is_disabled_vehicle: bool | None
    is_electric: bool | None
    vehicle_status: str | None
    session_id: int | None
    duplicate_request: bool

    @classmethod
    def from_backend(
        cls,
        request: BackendEntryRequest,
        result: BackendEntryResult,
    ) -> JetsonEntryRequest:
        return cls(
            tracking_id=result.tracking_id,
            recognized_plate_number=request.recognized_plate_number,
            entry_time=request.entry_time,
            access_decision=result.access_decision,
            registered=result.registered,
            vehicle_id=result.vehicle_id,
            is_disabled_vehicle=result.is_disabled_vehicle,
            is_electric=result.is_electric,
            vehicle_status=result.vehicle_status,
            session_id=result.session_id,
            duplicate_request=result.duplicate_request,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "trackingId": self.tracking_id,
            "recognizedPlateNumber": self.recognized_plate_number,
            "entryTime": _to_iso8601(self.entry_time),
            "accessDecision": self.access_decision.value,
            "registered": self.registered,
            "vehicleId": self.vehicle_id,
            "isDisabledVehicle": self.is_disabled_vehicle,
            "isElectric": self.is_electric,
            "vehicleStatus": self.vehicle_status,
            "sessionId": self.session_id,
            "duplicateRequest": self.duplicate_request,
        }

"""Backend/Raspberry Pi 통신 전용 요청·응답 DTO 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NewType


ParkingEventId = NewType("ParkingEventId", int)
MoveRequestId = NewType("MoveRequestId", int)


@dataclass(frozen=True)
class EntryContext:
    """라즈베리파이가 `POST /internal/entry-events`로 보내는 입차 결과.

    필드명·의미는 `ai/tracking/entry_event_intake.py`의 `IncomingEntryEvent`
    (383) 및 `hw/raspberry-pi/src/communication/schemas.py`의
    `JetsonEntryRequest`와 반드시 같아야 한다 — 그쪽이 실제 wire 계약의
    출처다. `tracking_id`는 ByteTrack의 정수 `track_id`가 아니라 라즈베리파이가
    입차 건마다 발급하는 UUID다(383).
    """

    tracking_id: str
    recognized_plate_number: str
    entry_time: datetime
    access_decision: str
    registered: bool
    vehicle_id: int | None
    is_disabled_vehicle: bool | None
    is_electric: bool | None
    vehicle_status: str | None
    session_id: int | None
    duplicate_request: bool

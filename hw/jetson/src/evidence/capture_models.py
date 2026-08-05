"""Incident OPEN 뒤 동일 frame에서 수행할 evidence capture 계약.

SQLite transaction은 capture identity만 예약하고 image binary는 commit 뒤에
기록한다. 이 값 객체는 두 경계 사이에서 필요한 최소 정보만 운반하며 frame이나
bbox처럼 큰 비영속 객체를 durable model에 섞지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from src.camera.models import CapturedFrame
from src.domain.models import require_aware
from src.evidence.models import EvidenceId
from src.parking.models import IncidentId, ZoneId
from src.tracking.models import PhysicalVehicleId
from src.tracking.models import TrackingBatch


class EvidenceCropKind(str, Enum):
    """한 Incident 안에서 서로 다른 역할을 갖는 정지 이미지 crop."""

    CONTEXT = "CONTEXT"
    DETAIL = "DETAIL"


@dataclass(frozen=True, kw_only=True)
class EvidenceCaptureIntent:
    """commit된 RESERVED evidence를 현재 frame으로 완성하라는 명령."""

    evidence_id: EvidenceId
    incident_id: IncidentId
    rule_code: str
    physical_vehicle_id: PhysicalVehicleId
    captured_at: datetime
    crop_kind: EvidenceCropKind = EvidenceCropKind.CONTEXT
    victim_physical_vehicle_id: PhysicalVehicleId | None = None
    zone_id: ZoneId | None = None

    def __post_init__(self) -> None:
        require_aware(self.captured_at, "captured_at")
        if not self.rule_code:
            raise ValueError("rule_code must not be empty")


class EvidenceCaptureSink(Protocol):
    """commit 뒤 현재 frame과 예약된 capture identity를 연결하는 port."""

    def capture(
        self,
        frame: CapturedFrame,
        batch: TrackingBatch,
        intents: tuple[EvidenceCaptureIntent, ...],
    ) -> None:
        ...

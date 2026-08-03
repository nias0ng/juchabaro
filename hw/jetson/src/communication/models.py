"""현재 wire 호환 입력과 cross-system command의 내부 의미 모델.

Endpoint, HTTP method와 최종 request/response DTO는 후속 API 계약의 범위다.
현행 Raspberry Pi 입차 요청은 `EntryContext`로 그대로 보존하고, 새 durable
workflow 모델과 섞지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import NewType

from src.domain.models import require_aware, require_non_negative, require_positive
from src.parking.models import IncidentId
from src.tracking.models import PhysicalVehicleId


ParkingEventId = NewType("ParkingEventId", int)
MoveRequestId = NewType("MoveRequestId", int)


@dataclass(frozen=True)
class EntryContext:
    """현행 `POST /internal/entry-events` wire와 동일한 임시 DTO.

    `tracking_id`는 ByteTrack ID가 아니라 입차 upstream이 생성한 UUID 문자열이며
    목표 도메인의 `entryAttemptId` 의미다. 최종 필드명 변경은 API 계약에서 한다.
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

    def __post_init__(self) -> None:
        require_aware(self.entry_time, "entry_time")
        if not self.tracking_id:
            raise ValueError("tracking_id must not be empty")
        if not self.access_decision:
            raise ValueError("access_decision must not be empty")


class MoveVerificationState(str, Enum):
    """한 `(requestId, verificationAttempt)` command의 local workflow."""

    ACCEPTED = "ACCEPTED"
    CHECKING = "CHECKING"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"


class MoveVerificationResult(str, Enum):
    """이동 여부가 아니라 최신 Incident 술어로 정한 확인 결과."""

    RESOLVED = "RESOLVED"
    STILL_ACTIVE = "STILL_ACTIVE"
    UNKNOWN = "UNKNOWN"


class PublicationApplicationResult(str, Enum):
    """Backend가 publication 적용 여부를 확인하는 의미 값."""

    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class MoveVerificationIncidentResult:
    """한 target Incident에 대한 immutable 최종 판단."""

    incident_id: IncidentId
    result: MoveVerificationResult
    incident_publication_revision: int

    def __post_init__(self) -> None:
        require_positive(self.incident_publication_revision, "incident_publication_revision")


@dataclass(frozen=True, kw_only=True)
class MoveVerificationAttempt:
    """하나 이상의 같은-subject Incident를 확인하는 durable command scope."""

    request_id: MoveRequestId
    verification_attempt: int
    subject_physical_vehicle_id: PhysicalVehicleId
    target_incident_ids: tuple[IncidentId, ...]
    command_payload_hash: str
    state: MoveVerificationState
    record_version: int
    publication_revision: int
    accepted_at: datetime
    updated_at: datetime
    deadline_at: datetime | None = None
    result: MoveVerificationResult | None = None
    incident_results: tuple[MoveVerificationIncidentResult, ...] = ()
    completed_at: datetime | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        require_positive(self.verification_attempt, "verification_attempt")
        require_positive(self.record_version, "record_version")
        require_non_negative(self.publication_revision, "publication_revision")
        for name in ("accepted_at", "updated_at", "deadline_at", "completed_at"):
            require_aware(getattr(self, name), name)
        if not self.target_incident_ids:
            raise ValueError("MoveVerificationAttempt requires at least one target Incident")
        if len(set(self.target_incident_ids)) != len(self.target_incident_ids):
            raise ValueError("target_incident_ids must be unique")
        if not self.command_payload_hash:
            raise ValueError("command_payload_hash must not be empty")

        is_terminal = self.state in {
            MoveVerificationState.COMPLETED,
            MoveVerificationState.CANCELED,
            MoveVerificationState.FAILED,
        }
        if is_terminal != (self.completed_at is not None):
            raise ValueError("terminal MoveVerificationAttempt must have completed_at")
        if self.state is MoveVerificationState.COMPLETED:
            if self.result is None or len(self.incident_results) != len(self.target_incident_ids):
                raise ValueError("COMPLETED verification requires overall and per-Incident results")
            result_ids = {item.incident_id for item in self.incident_results}
            if result_ids != set(self.target_incident_ids):
                raise ValueError("incident results must cover target_incident_ids exactly")
            child_results = {item.result for item in self.incident_results}
            derived_result = (
                MoveVerificationResult.STILL_ACTIVE
                if MoveVerificationResult.STILL_ACTIVE in child_results
                else (
                    MoveVerificationResult.UNKNOWN
                    if MoveVerificationResult.UNKNOWN in child_results
                    else MoveVerificationResult.RESOLVED
                )
            )
            if self.result is not derived_result:
                raise ValueError("overall verification result must be derived from per-Incident results")
            if self.publication_revision < 1:
                raise ValueError("COMPLETED verification requires a publication revision")
        elif self.result is not None or self.incident_results:
            raise ValueError("only COMPLETED verification may carry results")
        elif self.publication_revision != 0:
            raise ValueError("non-completed verification has no result publication")
        if self.state in {MoveVerificationState.CANCELED, MoveVerificationState.FAILED}:
            if not self.terminal_reason:
                raise ValueError("canceled or failed verification requires terminal_reason")

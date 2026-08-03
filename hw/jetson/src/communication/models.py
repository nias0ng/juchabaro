"""Cross-system 입력을 application 계층에 전달하는 내부 의미 모델.

HTTP endpoint와 camelCase 파싱은 api 계층이 담당한다. 이 모듈은 파싱이 끝난
RPi EntryDecision과 Backend command를 Python 값으로 보존하며, session domain
aggregate나 FastAPI DTO를 대신하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import NewType
from uuid import UUID

from src.domain.models import require_aware, require_non_negative, require_positive
from src.parking.models import IncidentId
from src.tracking.models import PhysicalVehicleId


ParkingEventId = NewType("ParkingEventId", int)
MoveRequestId = NewType("MoveRequestId", int)


class EntryAccessDecision(str, Enum):
    """RPi가 전달하는 Backend의 초기 출입 판정."""

    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    DENY = "DENY"


class EntryReviewResolution(str, Enum):
    """Backend가 REVIEW_PENDING 입차 시도에 내린 후속 판정."""

    REVIEW_ALLOW = "REVIEW_ALLOW"
    REVIEW_DENY = "REVIEW_DENY"
    REVIEW_EXPIRED = "REVIEW_EXPIRED"


def _require_positive_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class EntrySessionContextInput:
    """Backend가 ALLOW와 함께 제공한 authoritative session snapshot."""

    session_id: int
    vehicle_id: int
    is_disabled_vehicle: bool
    is_electric: bool

    def __post_init__(self) -> None:
        _require_positive_int(self.session_id, "session_id")
        _require_positive_int(self.vehicle_id, "vehicle_id")
        for name in ("is_disabled_vehicle", "is_electric"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")


@dataclass(frozen=True)
class EntryDecisionInput:
    """API 2에서 durable EntryMatchAttempt로 변환할 초기 EntryDecision."""

    entry_attempt_id: UUID
    decision_revision: int
    access_decision: EntryAccessDecision
    entry_time: datetime
    session_context: EntrySessionContextInput | None

    def __post_init__(self) -> None:
        if not isinstance(self.entry_attempt_id, UUID):
            raise ValueError("entry_attempt_id must be UUID")
        _require_positive_int(self.decision_revision, "decision_revision")
        if not isinstance(self.access_decision, EntryAccessDecision):
            raise ValueError("access_decision must be EntryAccessDecision")
        require_aware(self.entry_time, "entry_time")
        if self.access_decision is EntryAccessDecision.ALLOW:
            if self.session_context is None:
                raise ValueError("ALLOW EntryDecision requires session_context")
        elif self.session_context is not None:
            raise ValueError(
                "REVIEW or DENY EntryDecision must not carry session_context"
            )


@dataclass(frozen=True)
class EntryReviewResolutionInput:
    """API 4에서 기존 REVIEW_PENDING attempt에 적용할 후속 판정."""

    entry_attempt_id: UUID
    decision_revision: int
    resolution: EntryReviewResolution
    resolved_at: datetime
    session_context: EntrySessionContextInput | None

    def __post_init__(self) -> None:
        if not isinstance(self.entry_attempt_id, UUID):
            raise ValueError("entry_attempt_id must be UUID")
        _require_positive_int(self.decision_revision, "decision_revision")
        if not isinstance(self.resolution, EntryReviewResolution):
            raise ValueError("resolution must be EntryReviewResolution")
        require_aware(self.resolved_at, "resolved_at")
        if self.resolution is EntryReviewResolution.REVIEW_ALLOW:
            if self.session_context is None:
                raise ValueError("REVIEW_ALLOW requires session_context")
        elif self.session_context is not None:
            raise ValueError(
                "REVIEW_DENY or REVIEW_EXPIRED must not carry session_context"
            )


@dataclass(frozen=True)
class SessionContextUpdateContextInput:
    """API 5가 전달하는 Backend authoritative 자격 snapshot."""

    vehicle_id: int
    is_disabled_vehicle: bool
    is_electric: bool

    def __post_init__(self) -> None:
        _require_positive_int(self.vehicle_id, "vehicle_id")
        for name in ("is_disabled_vehicle", "is_electric"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be boolean")


@dataclass(frozen=True)
class SessionContextUpdateInput:
    """API 5에서 session mirror와 active binding에 적용할 변경."""

    session_id: int
    entry_attempt_id: UUID
    context_revision: int
    administrative_state: str
    updated_at: datetime
    session_context: SessionContextUpdateContextInput

    def __post_init__(self) -> None:
        _require_positive_int(self.session_id, "session_id")
        if not isinstance(self.entry_attempt_id, UUID):
            raise ValueError("entry_attempt_id must be UUID")
        _require_positive_int(self.context_revision, "context_revision")
        if self.administrative_state not in {"ACTIVE", "CLOSED"}:
            raise ValueError("administrative_state must be ACTIVE or CLOSED")
        require_aware(self.updated_at, "updated_at")
        if not isinstance(
            self.session_context,
            SessionContextUpdateContextInput,
        ):
            raise ValueError(
                "session_context must be SessionContextUpdateContextInput"
            )


@dataclass(frozen=True)
class MoveVerificationCommandInput:
    """API 11에서 하나 이상의 Incident 재확인을 요청하는 command."""

    request_id: int
    verification_attempt: int
    target_incident_ids: tuple[UUID, ...]
    requested_at: datetime
    deadline_at: datetime

    def __post_init__(self) -> None:
        _require_positive_int(self.request_id, "request_id")
        _require_positive_int(self.verification_attempt, "verification_attempt")
        if not self.target_incident_ids:
            raise ValueError("target_incident_ids must not be empty")
        if any(
            not isinstance(incident_id, UUID)
            for incident_id in self.target_incident_ids
        ):
            raise ValueError("target_incident_ids must contain UUID values")
        if len(set(self.target_incident_ids)) != len(self.target_incident_ids):
            raise ValueError("target_incident_ids must be unique")
        require_aware(self.requested_at, "requested_at")
        require_aware(self.deadline_at, "deadline_at")
        if self.deadline_at < self.requested_at:
            raise ValueError("deadline_at must not precede requested_at")


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

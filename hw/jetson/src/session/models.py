"""입차 시도와 PhysicalVehicle·Backend session correlation 모델.

Access decision, 현장 매칭 결과, 실제 차량 존재 상태를 서로 다른 축으로 둔다.
Backend의 행정 종료는 물리 EXIT가 아니며 ContextBinding의 identity는 생성 뒤
바꿀 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import NewType
from uuid import UUID

from src.domain.models import ObservationStatus, require_aware, require_non_negative, require_positive
from src.tracking.models import ParkingSessionId, PhysicalVehicleId, VehicleId


EntryAttemptId = NewType("EntryAttemptId", UUID)
ContextBindingId = NewType("ContextBindingId", UUID)


class EntryMatchState(str, Enum):
    """입차 시도와 PhysicalVehicle의 현장 매칭 결과."""

    PENDING = "PENDING"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class EntryDecisionState(str, Enum):
    """Backend access decision의 revisioned mirror."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    REVIEW_PENDING = "REVIEW_PENDING"
    REVIEW_ALLOW = "REVIEW_ALLOW"
    REVIEW_DENY = "REVIEW_DENY"
    REVIEW_EXPIRED = "REVIEW_EXPIRED"


class ContextBindingState(str, Enum):
    """한 번 확정한 immutable correlation의 활성 여부."""

    BOUND = "BOUND"
    ENDED = "ENDED"


class SessionAdministrativeState(str, Enum):
    """Backend가 소유하는 session 업무 상태의 최소 mirror."""

    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class PhysicalPresenceState(str, Enum):
    """Backend 행정 상태와 독립적인 현장 차량 존재 상태."""

    UNCONFIRMED = "UNCONFIRMED"
    INSIDE = "INSIDE"
    EXITED = "EXITED"


class PhysicalTerminationOrigin(str, Enum):
    """Jetson이 실제 출차를 확정한 권위 출처."""

    JETSON_EXIT_CONFIRMED = "JETSON_EXIT_CONFIRMED"


class PhysicalExitEvidence(str, Enum):
    """현재 한-camera 배포에서 사용할 수 있는 실제 출차 근거."""

    ENTRY_EXIT_TRAVERSAL = "ENTRY_EXIT_TRAVERSAL"
    FULL_AREA_ABSENCE = "FULL_AREA_ABSENCE"


@dataclass(frozen=True)
class SessionContext:
    """authoritative ContextBinding이 규칙 평가에 제공하는 session 문맥."""

    parking_session_id: ParkingSessionId
    vehicle_id: VehicleId | None
    is_electric: bool | None
    is_disabled_vehicle: bool | None


@dataclass(frozen=True, kw_only=True)
class EntryMatchAttempt:
    """하나의 entryAttemptId에 대한 매칭과 access decision snapshot."""

    entry_attempt_id: EntryAttemptId
    match_state: EntryMatchState
    decision_state: EntryDecisionState
    decision_revision: int
    record_version: int
    created_at: datetime
    updated_at: datetime
    match_deadline_at: datetime
    matched_physical_vehicle_id: PhysicalVehicleId | None = None
    authoritative_session_id: ParkingSessionId | None = None
    authoritative_context: SessionContext | None = None
    match_terminated_at: datetime | None = None
    terminal_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_negative(self.decision_revision, "decision_revision")
        require_positive(self.record_version, "record_version")
        for name in ("created_at", "updated_at", "match_deadline_at", "match_terminated_at"):
            require_aware(getattr(self, name), name)
        if self.match_deadline_at < self.created_at:
            raise ValueError("match_deadline_at must not precede created_at")

        if (self.match_state is EntryMatchState.MATCHED) != (
            self.matched_physical_vehicle_id is not None
        ):
            raise ValueError("MATCHED entry attempt must identify exactly one PhysicalVehicle")

        decision_has_session = self.decision_state in {
            EntryDecisionState.ALLOW,
            EntryDecisionState.REVIEW_ALLOW,
        }
        if decision_has_session != (self.authoritative_session_id is not None):
            raise ValueError("ALLOW decisions require one authoritative session; other decisions must not carry one")
        if decision_has_session != (self.authoritative_context is not None):
            raise ValueError("ALLOW decisions require authoritative context; other decisions must not carry one")
        if self.authoritative_context is not None and (
            self.authoritative_context.parking_session_id != self.authoritative_session_id
        ):
            raise ValueError("authoritative context must reference the attempt session")

        match_terminal = self.match_state is not EntryMatchState.PENDING
        if match_terminal != (self.match_terminated_at is not None):
            raise ValueError("terminal match state must record match_terminated_at")

        unsuccessful_terminal = self.match_state in {
            EntryMatchState.EXPIRED,
            EntryMatchState.FAILED,
            EntryMatchState.CANCELED,
        }
        if unsuccessful_terminal != (self.terminal_reason is not None):
            raise ValueError("unsuccessful terminal match state must record terminal_reason")


@dataclass(frozen=True, kw_only=True)
class ContextBinding:
    """검증된 entryAttempt·session·PhysicalVehicle의 immutable 연결."""

    context_binding_id: ContextBindingId
    entry_attempt_id: EntryAttemptId
    parking_session_id: ParkingSessionId
    physical_vehicle_id: PhysicalVehicleId
    state: ContextBindingState
    context_revision: int
    context: SessionContext
    record_version: int
    bound_at: datetime
    updated_at: datetime
    ended_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_negative(self.context_revision, "context_revision")
        require_positive(self.record_version, "record_version")
        for name in ("bound_at", "updated_at", "ended_at"):
            require_aware(getattr(self, name), name)
        if self.context.parking_session_id != self.parking_session_id:
            raise ValueError("binding context must reference parking_session_id")
        is_ended = self.state is ContextBindingState.ENDED
        if is_ended != (self.ended_at is not None):
            raise ValueError("ENDED ContextBinding must have ended_at")
        if is_ended != (self.termination_reason is not None):
            raise ValueError("ENDED ContextBinding must have termination_reason")


@dataclass(frozen=True, kw_only=True)
class ParkingSessionMirror:
    """Backend session의 행정 상태와 현장 presence를 분리한 local mirror."""

    parking_session_id: ParkingSessionId
    administrative_state: SessionAdministrativeState
    physical_presence_state: PhysicalPresenceState
    physical_observation: ObservationStatus
    context_revision: int
    record_version: int
    publication_revision: int
    created_at: datetime
    updated_at: datetime
    entry_attempt_id: EntryAttemptId | None = None
    physical_vehicle_id: PhysicalVehicleId | None = None
    last_context: SessionContext | None = None
    physical_termination_origin: PhysicalTerminationOrigin | None = None
    physical_exit_evidence: PhysicalExitEvidence | None = None
    exited_at: datetime | None = None
    exit_correlation_enabled: bool = True
    terminated_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_negative(self.context_revision, "context_revision")
        require_positive(self.record_version, "record_version")
        require_non_negative(self.publication_revision, "publication_revision")
        for name in ("created_at", "updated_at", "exited_at", "terminated_at"):
            require_aware(getattr(self, name), name)
        if self.last_context is not None and self.last_context.parking_session_id != self.parking_session_id:
            raise ValueError("last_context must reference parking_session_id")

        is_exited = self.physical_presence_state is PhysicalPresenceState.EXITED
        exit_fields = (
            self.physical_termination_origin,
            self.physical_exit_evidence,
            self.exited_at,
        )
        if is_exited and any(value is None for value in exit_fields):
            raise ValueError("EXITED mirror requires origin, evidence, and exited_at")
        if not is_exited and any(value is not None for value in exit_fields):
            raise ValueError("non-EXITED mirror must not carry physical exit metadata")
        is_unconfirmed = (
            self.physical_presence_state is PhysicalPresenceState.UNCONFIRMED
        )
        if is_unconfirmed != (self.physical_vehicle_id is None):
            raise ValueError(
                "UNCONFIRMED presence must not reference a PhysicalVehicle; "
                "confirmed presence must reference one"
            )
        if (self.terminated_at is None) != (self.termination_reason is None):
            raise ValueError("mirror storage termination timestamp and reason must appear together")

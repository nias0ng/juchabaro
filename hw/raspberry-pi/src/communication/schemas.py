"""RPi가 Backend·Jetson과 교환하는 입차 API 1~3 계약.

구 ``trackingId`` wire와 평면 Backend 응답은 지원하지 않는다. RPi가 생성한
``entryAttemptId``를 Backend 판정과 Jetson 현장 매칭까지 동일하게 유지한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID


class AccessDecision(str, Enum):
    """Backend가 반환하는 초기 출입 판정."""

    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    DENY = "DENY"


class AcceptanceStatus(str, Enum):
    """Jetson의 durable EntryDecision 접수 결과."""

    ACCEPTED = "ACCEPTED"
    ALREADY_ACCEPTED = "ALREADY_ACCEPTED"


class EntryMatchState(str, Enum):
    """Jetson이 관리하는 입차 시도와 PhysicalVehicle의 매칭 상태."""

    PENDING = "PENDING"
    MATCHED = "MATCHED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


def _require_uuid(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name}은 UUID 문자열이어야 합니다.")
    try:
        UUID(value)
    except ValueError as error:
        raise ValueError(f"{field_name}은 UUID 문자열이어야 합니다.") from error
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name}은 1 이상의 정수여야 합니다.")
    return value


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{field_name}은 boolean이어야 합니다.")
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name}은 datetime이어야 합니다.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name}은 시간대가 포함된 datetime이어야 합니다.")
    return value


def _to_iso8601(value: datetime, field_name: str) -> str:
    return _require_aware(value, field_name).isoformat()


def _from_iso8601(value: object, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field_name}은 ISO 8601 문자열이어야 합니다.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field_name}이 올바른 ISO 8601 형식이 아닙니다.") from error
    return _require_aware(parsed, field_name)


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Backend가 소유하는 authoritative 주차 세션 문맥."""

    session_id: int
    vehicle_id: int
    is_disabled_vehicle: bool
    is_electric: bool

    def __post_init__(self) -> None:
        _require_positive_int(self.session_id, "session_id")
        _require_positive_int(self.vehicle_id, "vehicle_id")
        _require_bool(self.is_disabled_vehicle, "is_disabled_vehicle")
        _require_bool(self.is_electric, "is_electric")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> SessionContext:
        return cls(
            session_id=_require_positive_int(payload["sessionId"], "sessionId"),
            vehicle_id=_require_positive_int(payload["vehicleId"], "vehicleId"),
            is_disabled_vehicle=_require_bool(
                payload["isDisabledVehicle"],
                "isDisabledVehicle",
            ),
            is_electric=_require_bool(payload["isElectric"], "isElectric"),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "sessionId": self.session_id,
            "vehicleId": self.vehicle_id,
            "isDisabledVehicle": self.is_disabled_vehicle,
            "isElectric": self.is_electric,
        }


@dataclass(frozen=True, slots=True)
class BackendEntryRequest:
    """API 1: Raspberry Pi가 Backend에 보내는 입차 판정 요청."""

    entry_attempt_id: str
    recognized_plate_number: str
    confidence: float
    entry_time: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.entry_attempt_id, "entry_attempt_id")
        if not isinstance(self.recognized_plate_number, str):
            raise TypeError("recognized_plate_number는 문자열이어야 합니다.")
        if not self.recognized_plate_number.strip():
            raise ValueError("recognized_plate_number는 비어 있을 수 없습니다.")
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confidence는 0.0~1.0 범위여야 합니다.")
        _require_aware(self.entry_time, "entry_time")

    def to_payload(self) -> dict[str, object]:
        return {
            "entryAttemptId": self.entry_attempt_id,
            "recognizedPlateNumber": self.recognized_plate_number,
            "ocrConfidence": float(self.confidence),
            "entryTime": _to_iso8601(self.entry_time, "entry_time"),
        }


@dataclass(frozen=True, slots=True)
class BackendEntryResult:
    """API 1의 Backend 판정 결과."""

    entry_attempt_id: str
    decision_revision: int
    access_decision: AccessDecision
    session_context: SessionContext | None
    duplicate_request: bool

    def __post_init__(self) -> None:
        _require_uuid(self.entry_attempt_id, "entry_attempt_id")
        _require_positive_int(self.decision_revision, "decision_revision")
        if not isinstance(self.access_decision, AccessDecision):
            raise TypeError("access_decision은 AccessDecision이어야 합니다.")
        _require_bool(self.duplicate_request, "duplicate_request")
        if (
            self.session_context is not None
            and not isinstance(self.session_context, SessionContext)
        ):
            raise TypeError("session_context는 SessionContext여야 합니다.")
        if self.access_decision is AccessDecision.ALLOW:
            if self.session_context is None:
                raise ValueError("ALLOW 응답에는 session_context가 필요합니다.")
        elif self.session_context is not None:
            raise ValueError("REVIEW 또는 DENY의 session_context는 None이어야 합니다.")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> BackendEntryResult:
        access_decision = AccessDecision(payload["accessDecision"])
        raw_context = payload["sessionContext"]
        if raw_context is None:
            session_context = None
        elif isinstance(raw_context, Mapping):
            session_context = SessionContext.from_payload(raw_context)
        else:
            raise TypeError("sessionContext 형식이 올바르지 않습니다.")

        return cls(
            entry_attempt_id=_require_uuid(
                payload["entryAttemptId"],
                "entryAttemptId",
            ),
            decision_revision=_require_positive_int(
                payload["decisionRevision"],
                "decisionRevision",
            ),
            access_decision=access_decision,
            session_context=session_context,
            duplicate_request=_require_bool(
                payload["duplicateRequest"],
                "duplicateRequest",
            ),
        )


@dataclass(frozen=True, slots=True)
class JetsonEntryRequest:
    """API 2: Raspberry Pi가 Jetson에 보내는 EntryDecision."""

    entry_attempt_id: str
    decision_revision: int
    access_decision: AccessDecision
    entry_time: datetime
    session_context: SessionContext | None

    def __post_init__(self) -> None:
        _require_uuid(self.entry_attempt_id, "entry_attempt_id")
        _require_positive_int(self.decision_revision, "decision_revision")
        if not isinstance(self.access_decision, AccessDecision):
            raise TypeError("access_decision은 AccessDecision이어야 합니다.")
        _require_aware(self.entry_time, "entry_time")
        if (
            self.session_context is not None
            and not isinstance(self.session_context, SessionContext)
        ):
            raise TypeError("session_context는 SessionContext여야 합니다.")
        if self.access_decision is AccessDecision.ALLOW:
            if self.session_context is None:
                raise ValueError("ALLOW 요청에는 session_context가 필요합니다.")
        elif self.session_context is not None:
            raise ValueError("REVIEW 또는 DENY의 session_context는 None이어야 합니다.")

    @classmethod
    def from_backend(
        cls,
        request: BackendEntryRequest,
        result: BackendEntryResult,
    ) -> JetsonEntryRequest:
        if request.entry_attempt_id != result.entry_attempt_id:
            raise ValueError("Backend 응답의 entryAttemptId가 요청과 다릅니다.")
        return cls(
            entry_attempt_id=result.entry_attempt_id,
            decision_revision=result.decision_revision,
            access_decision=result.access_decision,
            entry_time=request.entry_time,
            session_context=result.session_context,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "entryAttemptId": self.entry_attempt_id,
            "decisionRevision": self.decision_revision,
            "accessDecision": self.access_decision.value,
            "entryTime": _to_iso8601(self.entry_time, "entry_time"),
            "sessionContext": (
                None
                if self.session_context is None
                else self.session_context.to_payload()
            ),
        }


@dataclass(frozen=True, slots=True)
class JetsonEntryAcceptance:
    """API 2의 durable EntryDecision 접수 결과."""

    entry_attempt_id: str
    decision_revision: int
    acceptance_status: AcceptanceStatus
    match_state: EntryMatchState
    accepted_at: datetime
    match_deadline_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.entry_attempt_id, "entry_attempt_id")
        _require_positive_int(self.decision_revision, "decision_revision")
        if not isinstance(self.acceptance_status, AcceptanceStatus):
            raise TypeError("acceptance_status는 AcceptanceStatus여야 합니다.")
        if self.match_state is not EntryMatchState.PENDING:
            raise ValueError("durable 접수 직후 match_state는 PENDING이어야 합니다.")
        _require_aware(self.accepted_at, "accepted_at")
        _require_aware(self.match_deadline_at, "match_deadline_at")

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
    ) -> JetsonEntryAcceptance:
        return cls(
            entry_attempt_id=_require_uuid(
                payload["entryAttemptId"],
                "entryAttemptId",
            ),
            decision_revision=_require_positive_int(
                payload["decisionRevision"],
                "decisionRevision",
            ),
            acceptance_status=AcceptanceStatus(payload["acceptanceStatus"]),
            match_state=EntryMatchState(payload["matchState"]),
            accepted_at=_from_iso8601(payload["acceptedAt"], "acceptedAt"),
            match_deadline_at=_from_iso8601(
                payload["matchDeadlineAt"],
                "matchDeadlineAt",
            ),
        )


@dataclass(frozen=True, slots=True)
class EntryMatchOutcome:
    """API 3: Jetson의 입차 시도와 PhysicalVehicle 매칭 결과."""

    entry_attempt_id: str
    decision_revision: int
    access_decision: AccessDecision
    match_state: EntryMatchState
    physical_vehicle_id: str | None
    matched_at: datetime | None
    terminal_reason: str | None
    match_deadline_at: datetime

    def __post_init__(self) -> None:
        _require_uuid(self.entry_attempt_id, "entry_attempt_id")
        _require_positive_int(self.decision_revision, "decision_revision")
        if not isinstance(self.access_decision, AccessDecision):
            raise TypeError("access_decision은 AccessDecision이어야 합니다.")
        if not isinstance(self.match_state, EntryMatchState):
            raise TypeError("match_state는 EntryMatchState여야 합니다.")
        if self.terminal_reason is not None and not isinstance(
            self.terminal_reason,
            str,
        ):
            raise TypeError("terminal_reason은 문자열이어야 합니다.")
        if self.matched_at is not None:
            _require_aware(self.matched_at, "matched_at")
        _require_aware(self.match_deadline_at, "match_deadline_at")

        if self.match_state is EntryMatchState.MATCHED:
            if self.physical_vehicle_id is None or self.matched_at is None:
                raise ValueError(
                    "MATCHED 결과에는 physical_vehicle_id와 matched_at이 필요합니다."
                )
            _require_uuid(self.physical_vehicle_id, "physical_vehicle_id")
            if self.terminal_reason is not None:
                raise ValueError("MATCHED 결과에는 terminal_reason이 없어야 합니다.")
            return

        if self.physical_vehicle_id is not None or self.matched_at is not None:
            raise ValueError(
                "MATCHED가 아닌 결과에는 physical_vehicle_id와 matched_at이 없어야 합니다."
            )
        if self.match_state is EntryMatchState.PENDING:
            if self.terminal_reason is not None:
                raise ValueError("PENDING 결과에는 terminal_reason이 없어야 합니다.")
        elif not self.terminal_reason:
            raise ValueError("실패 terminal 결과에는 terminal_reason이 필요합니다.")

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> EntryMatchOutcome:
        matched_at_payload = payload["matchedAt"]
        return cls(
            entry_attempt_id=_require_uuid(
                payload["entryAttemptId"],
                "entryAttemptId",
            ),
            decision_revision=_require_positive_int(
                payload["decisionRevision"],
                "decisionRevision",
            ),
            access_decision=AccessDecision(payload["accessDecision"]),
            match_state=EntryMatchState(payload["matchState"]),
            physical_vehicle_id=payload["physicalVehicleId"],
            matched_at=(
                None
                if matched_at_payload is None
                else _from_iso8601(matched_at_payload, "matchedAt")
            ),
            terminal_reason=payload["terminalReason"],
            match_deadline_at=_from_iso8601(
                payload["matchDeadlineAt"],
                "matchDeadlineAt",
            ),
        )

"""RPi API 3을 위한 durable EntryMatchAttempt 조회 application service."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from src.communication.models import EntryAccessDecision
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchState,
)
from src.storage.repositories import EntryMatchAttemptRepository
from src.tracking.models import PhysicalVehicleId


class EntryMatchNotFoundError(LookupError):
    """요청한 entryAttemptId의 durable match attempt가 없다."""


_ACCESS_DECISION_BY_DOMAIN_STATE = {
    EntryDecisionState.ALLOW: EntryAccessDecision.ALLOW,
    EntryDecisionState.REVIEW_ALLOW: EntryAccessDecision.ALLOW,
    EntryDecisionState.REVIEW_PENDING: EntryAccessDecision.REVIEW,
    EntryDecisionState.DENY: EntryAccessDecision.DENY,
    EntryDecisionState.REVIEW_DENY: EntryAccessDecision.DENY,
    EntryDecisionState.REVIEW_EXPIRED: EntryAccessDecision.DENY,
}


@dataclass(frozen=True, kw_only=True)
class EntryMatchOutcome:
    """API 3 wire로 직렬화할 현재 EntryMatchAttempt snapshot."""

    entry_attempt_id: EntryAttemptId
    decision_revision: int
    access_decision: EntryAccessDecision
    match_state: EntryMatchState
    physical_vehicle_id: PhysicalVehicleId | None
    matched_at: datetime | None
    terminal_reason: str | None
    match_deadline_at: datetime


class EntryMatchQuery:
    """EntryMatchAttemptRepository의 현재 snapshot을 RPi 조회 의미로 변환한다."""

    def get(
        self,
        entry_attempt_id: UUID,
        *,
        connection: sqlite3.Connection,
    ) -> EntryMatchOutcome:
        attempt = EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(entry_attempt_id)
        )
        if attempt is None:
            raise EntryMatchNotFoundError(
                f"entryAttemptId를 찾을 수 없습니다: {entry_attempt_id}"
            )

        return EntryMatchOutcome(
            entry_attempt_id=attempt.entry_attempt_id,
            decision_revision=attempt.decision_revision,
            access_decision=_ACCESS_DECISION_BY_DOMAIN_STATE[attempt.decision_state],
            match_state=attempt.match_state,
            physical_vehicle_id=attempt.matched_physical_vehicle_id,
            matched_at=(
                attempt.match_terminated_at
                if attempt.match_state is EntryMatchState.MATCHED
                else None
            ),
            terminal_reason=attempt.terminal_reason,
            match_deadline_at=attempt.match_deadline_at,
        )

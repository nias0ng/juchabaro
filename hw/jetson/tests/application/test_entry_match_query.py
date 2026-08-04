"""EntryMatchAttempt snapshot의 RPi API 3 조회 의미 변환 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from src.application.entry_match_query import (
    EntryMatchNotFoundError,
    EntryMatchQuery,
)
from src.communication.models import EntryAccessDecision
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    SessionContext,
)
from src.tracking.models import ParkingSessionId, PhysicalVehicleId, VehicleId


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
ENTRY_ATTEMPT_ID = EntryAttemptId(
    UUID("11111111-1111-4111-8111-111111111111")
)
PHYSICAL_VEHICLE_ID = PhysicalVehicleId(
    UUID("22222222-2222-4222-8222-222222222222")
)


def _attempt(
    *,
    match_state: EntryMatchState = EntryMatchState.PENDING,
    decision_state: EntryDecisionState = EntryDecisionState.ALLOW,
    physical_vehicle_id: PhysicalVehicleId | None = None,
    terminated_at: datetime | None = None,
    terminal_reason: str | None = None,
) -> EntryMatchAttempt:
    has_session = decision_state in {
        EntryDecisionState.ALLOW,
        EntryDecisionState.REVIEW_ALLOW,
    }
    context = (
        SessionContext(
            parking_session_id=ParkingSessionId(55),
            vehicle_id=VehicleId(10),
            is_electric=True,
            is_disabled_vehicle=False,
        )
        if has_session
        else None
    )
    return EntryMatchAttempt(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        match_state=match_state,
        decision_state=decision_state,
        decision_revision=1,
        record_version=1,
        created_at=NOW,
        updated_at=terminated_at or NOW,
        match_deadline_at=NOW + timedelta(seconds=10),
        matched_physical_vehicle_id=physical_vehicle_id,
        authoritative_session_id=(ParkingSessionId(55) if has_session else None),
        authoritative_context=context,
        match_terminated_at=terminated_at,
        terminal_reason=terminal_reason,
    )


def _query(attempt: EntryMatchAttempt | None):
    connection = MagicMock()
    with patch(
        "src.application.entry_match_query.EntryMatchAttemptRepository"
    ) as repository_type:
        repository_type.return_value.get.return_value = attempt
        if attempt is None:
            with pytest.raises(EntryMatchNotFoundError):
                EntryMatchQuery().get(UUID(str(ENTRY_ATTEMPT_ID)), connection=connection)
            return None
        return EntryMatchQuery().get(
            UUID(str(ENTRY_ATTEMPT_ID)),
            connection=connection,
        )


@pytest.mark.parametrize(
    ("decision_state", "expected_wire"),
    [
        (EntryDecisionState.ALLOW, EntryAccessDecision.ALLOW),
        (EntryDecisionState.REVIEW_ALLOW, EntryAccessDecision.ALLOW),
        (EntryDecisionState.REVIEW_PENDING, EntryAccessDecision.REVIEW),
        (EntryDecisionState.DENY, EntryAccessDecision.DENY),
        (EntryDecisionState.REVIEW_DENY, EntryAccessDecision.DENY),
        (EntryDecisionState.REVIEW_EXPIRED, EntryAccessDecision.DENY),
    ],
)
def test_maps_domain_decision_to_rpi_access_decision(
    decision_state: EntryDecisionState,
    expected_wire: EntryAccessDecision,
) -> None:
    outcome = _query(_attempt(decision_state=decision_state))

    assert outcome is not None
    assert outcome.access_decision is expected_wire


def test_matched_outcome_exposes_physical_vehicle_and_matched_time() -> None:
    matched_at = NOW + timedelta(seconds=5)

    outcome = _query(
        _attempt(
            match_state=EntryMatchState.MATCHED,
            physical_vehicle_id=PHYSICAL_VEHICLE_ID,
            terminated_at=matched_at,
        )
    )

    assert outcome is not None
    assert outcome.match_state is EntryMatchState.MATCHED
    assert outcome.physical_vehicle_id == PHYSICAL_VEHICLE_ID
    assert outcome.matched_at == matched_at
    assert outcome.terminal_reason is None


def test_expired_outcome_hides_match_fields_and_exposes_reason() -> None:
    outcome = _query(
        _attempt(
            match_state=EntryMatchState.EXPIRED,
            terminated_at=NOW + timedelta(seconds=11),
            terminal_reason="SOURCE_UNAVAILABLE",
        )
    )

    assert outcome is not None
    assert outcome.match_state is EntryMatchState.EXPIRED
    assert outcome.physical_vehicle_id is None
    assert outcome.matched_at is None
    assert outcome.terminal_reason == "SOURCE_UNAVAILABLE"


def test_missing_attempt_is_not_found() -> None:
    assert _query(None) is None

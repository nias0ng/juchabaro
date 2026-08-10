"""EntryMatchAttempt SQLite repository·SessionContext codec 회귀 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    SessionContext,
)
from src.storage.database import open_database
from src.storage.repositories import (
    EntryMatchAttemptConflictError,
    EntryMatchAttemptRepository,
    OptimisticConcurrencyError,
)
from src.storage.unit_of_work import TransactionStateError, UnitOfWork
from src.tracking.models import ParkingSessionId, VehicleId


NOW = datetime(2026, 8, 2, 12, 34, 56, 123456, tzinfo=timezone.utc)
ATTEMPT_ID = EntryAttemptId(UUID("11111111-1111-4111-8111-111111111111"))


def _attempt() -> EntryMatchAttempt:
    context = SessionContext(
        parking_session_id=ParkingSessionId(55),
        vehicle_id=VehicleId(10),
        is_electric=True,
        is_disabled_vehicle=False,
    )
    return EntryMatchAttempt(
        entry_attempt_id=ATTEMPT_ID,
        match_state=EntryMatchState.PENDING,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=0,
        authoritative_session_id=ParkingSessionId(55),
        authoritative_context=context,
        match_deadline_at=NOW + timedelta(seconds=10),
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_add_and_get_round_trip_authoritative_context(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EntryMatchAttemptRepository(connection)
    attempt = _attempt()
    try:
        with UnitOfWork(connection):
            repository.add(attempt)

        assert repository.get(ATTEMPT_ID) == attempt
        row = connection.execute(
            "SELECT authoritative_context_payload FROM entry_match_attempts "
            "WHERE entry_attempt_id = ?",
            (str(ATTEMPT_ID),),
        ).fetchone()
        assert bytes(row[0]).startswith(b'{"isDisabledVehicle":')
    finally:
        connection.close()


def test_add_requires_uow_and_rejects_duplicate_identity(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EntryMatchAttemptRepository(connection)
    attempt = _attempt()
    try:
        with pytest.raises(TransactionStateError):
            repository.add(attempt)

        with UnitOfWork(connection):
            repository.add(attempt)
        with pytest.raises(EntryMatchAttemptConflictError):
            with UnitOfWork(connection):
                repository.add(attempt)

        assert repository.get(ATTEMPT_ID) == attempt
    finally:
        connection.close()


def test_list_pending_is_ordered_and_save_uses_optimistic_version(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EntryMatchAttemptRepository(connection)
    later = _attempt()
    earlier = replace(
        later,
        entry_attempt_id=EntryAttemptId(
            UUID("00000000-0000-4000-8000-000000000002")
        ),
        decision_state=EntryDecisionState.DENY,
        authoritative_session_id=None,
        authoritative_context=None,
        created_at=NOW - timedelta(seconds=1),
        updated_at=NOW - timedelta(seconds=1),
    )
    try:
        with UnitOfWork(connection):
            repository.add(later)
            repository.add(earlier)

        assert repository.list_pending() == (earlier, later)

        expired = replace(
            earlier,
            match_state=EntryMatchState.EXPIRED,
            match_terminated_at=NOW + timedelta(seconds=11),
            terminal_reason="MATCH_DEADLINE_EXCEEDED",
            record_version=2,
            updated_at=NOW + timedelta(seconds=11),
        )
        with UnitOfWork(connection):
            repository.save(expired, expected_record_version=1)

        assert repository.get(earlier.entry_attempt_id) == expired
        assert repository.list_pending() == (later,)

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.save(expired, expected_record_version=1)
    finally:
        connection.close()

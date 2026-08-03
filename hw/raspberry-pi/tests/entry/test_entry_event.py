from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from src.entry.entry_event import EntryEvent


ENTRY_ATTEMPT_ID = "550e8400-e29b-41d4-a716-446655440000"
IDEMPOTENCY_KEY = "c176f427-3e47-4fbd-bb17-12ca2bf46ee9"
ENTRY_TIME_OFFSET = timedelta(hours=9)
ENTRY_TIME = datetime(
    2026,
    7,
    31,
    12,
    34,
    56,
    tzinfo=timezone(ENTRY_TIME_OFFSET),
)


def test_constructor_preserves_values_and_timezone_offset() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )

    assert event.entry_attempt_id == ENTRY_ATTEMPT_ID
    assert event.idempotency_key == IDEMPOTENCY_KEY
    assert event.entry_time == ENTRY_TIME
    assert event.entry_time.utcoffset() == ENTRY_TIME_OFFSET


def test_fields_cannot_be_modified_after_construction() -> None:
    event = EntryEvent(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        idempotency_key=IDEMPOTENCY_KEY,
        entry_time=ENTRY_TIME,
    )

    with pytest.raises(FrozenInstanceError):
        event.entry_attempt_id = "changed-entry-attempt"


@pytest.mark.parametrize(
    "invalid_entry_attempt_id",
    [
        pytest.param("", id="empty"),
        pytest.param(" \t\n", id="whitespace"),
    ],
)
def test_constructor_rejects_invalid_entry_attempt_id(
    invalid_entry_attempt_id: str,
) -> None:
    with pytest.raises(ValueError, match="entry_attempt_id"):
        EntryEvent(
            entry_attempt_id=invalid_entry_attempt_id,
            idempotency_key=IDEMPOTENCY_KEY,
            entry_time=ENTRY_TIME,
        )


@pytest.mark.parametrize(
    "invalid_idempotency_key",
    [
        pytest.param("", id="empty"),
        pytest.param(" \t\n", id="whitespace"),
    ],
)
def test_constructor_rejects_invalid_idempotency_key(
    invalid_idempotency_key: str,
) -> None:
    with pytest.raises(ValueError, match="idempotency_key"):
        EntryEvent(
            entry_attempt_id=ENTRY_ATTEMPT_ID,
            idempotency_key=invalid_idempotency_key,
            entry_time=ENTRY_TIME,
        )


def test_constructor_rejects_naive_entry_time() -> None:
    naive_entry_time = datetime(2026, 7, 31, 12, 34, 56)

    with pytest.raises(ValueError, match="entry_time"):
        EntryEvent(
            entry_attempt_id=ENTRY_ATTEMPT_ID,
            idempotency_key=IDEMPOTENCY_KEY,
            entry_time=naive_entry_time,
        )


def test_constructor_accepts_non_uuid_identifiers() -> None:
    event = EntryEvent(
        entry_attempt_id="entry-attempt",
        idempotency_key="retry-key",
        entry_time=ENTRY_TIME,
    )

    assert event.entry_attempt_id == "entry-attempt"
    assert event.idempotency_key == "retry-key"

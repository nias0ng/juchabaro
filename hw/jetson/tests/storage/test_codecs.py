"""Exact local-store timestamp and identifier representation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.storage.codecs import (
    datetime_from_epoch_microseconds,
    datetime_to_epoch_microseconds,
    uuid_from_text,
    uuid_to_text,
)


def test_timezone_aware_datetime_round_trips_as_exact_utc_microseconds() -> None:
    korea = timezone(timedelta(hours=9))
    local_time = datetime(2026, 8, 2, 12, 34, 56, 789_123, tzinfo=korea)

    encoded = datetime_to_epoch_microseconds(local_time)
    decoded = datetime_from_epoch_microseconds(encoded)

    assert decoded == local_time.astimezone(timezone.utc)
    assert decoded.tzinfo is timezone.utc
    assert decoded.microsecond == 789_123


def test_datetime_codec_rejects_naive_value() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        datetime_to_epoch_microseconds(datetime(2026, 8, 2, 12, 0, 0))


def test_uuid_codec_round_trips_canonical_text() -> None:
    identifier = UUID("12345678-1234-5678-9abc-def012345678")

    encoded = uuid_to_text(identifier)

    assert encoded == "12345678-1234-5678-9abc-def012345678"
    assert uuid_from_text(encoded) == identifier


@pytest.mark.parametrize(
    "value",
    [
        "12345678-1234-5678-9ABC-DEF012345678",
        "12345678123456789abcdef012345678",
        "not-a-uuid",
    ],
)
def test_uuid_codec_rejects_noncanonical_or_invalid_text(value: str) -> None:
    with pytest.raises(ValueError):
        uuid_from_text(value)

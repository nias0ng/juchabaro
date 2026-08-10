"""SQLite domain record의 정본 scalar codec.

local store 표현만 정의하며 Backend wire DTO나 JSON 정수 정책은 결정하지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

_UNIX_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECONDS_PER_SECOND = 1_000_000
_SECONDS_PER_DAY = 86_400


def datetime_to_epoch_microseconds(value: datetime) -> int:
    """timezone-aware instant를 정확한 UTC epoch microseconds로 변환한다."""

    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    delta = value.astimezone(timezone.utc) - _UNIX_EPOCH
    return (
        delta.days * _SECONDS_PER_DAY * _MICROSECONDS_PER_SECOND
        + delta.seconds * _MICROSECONDS_PER_SECOND
        + delta.microseconds
    )


def datetime_from_epoch_microseconds(value: int) -> datetime:
    """epoch microseconds를 timezone-aware UTC datetime으로 복원한다."""

    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("epoch microseconds must be an integer")
    return _UNIX_EPOCH + timedelta(microseconds=value)


def uuid_to_text(value: UUID) -> str:
    """UUID를 소문자 canonical hyphenated text로 변환한다."""

    if not isinstance(value, UUID):
        raise TypeError("value must be a UUID")
    return str(value)


def uuid_from_text(value: str) -> UUID:
    """canonical UUID text만 해석하고 다른 표기나 잘못된 값을 거부한다."""

    if not isinstance(value, str):
        raise TypeError("UUID text must be a string")
    try:
        parsed = UUID(value)
    except (AttributeError, ValueError) as error:
        raise ValueError("invalid UUID text") from error
    if value != str(parsed):
        raise ValueError("UUID text must be lowercase canonical hyphenated form")
    return parsed

"""입차 시각을 기준으로 local aggregate의 publication 범위를 판정한다."""

from __future__ import annotations

from datetime import datetime

from src.domain.models import require_aware


def is_pre_entry_scope(
    *,
    aggregate_started_at: datetime,
    entry_time: datetime,
) -> bool:
    """aggregate 시작 시각이 entryTime보다 이른지 판정한다.

    entryTime과 같은 시각의 사실은 입차 이후 scope에 포함한다.
    """

    require_aware(aggregate_started_at, "aggregate_started_at")
    require_aware(entry_time, "entry_time")
    return aggregate_started_at < entry_time

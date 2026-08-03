"""Backend 입차 등록 요청에 사용되는 입차 이벤트 정보를 정의한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class EntryEvent:
    """감지된 차량 한 건의 입차 등록 처리 정보를 보관한다."""

    entry_attempt_id: str
    idempotency_key: str
    entry_time: datetime

    def __post_init__(self) -> None:
        if not self.entry_attempt_id.strip():
            raise ValueError("entry_attempt_id는 비어 있을 수 없습니다.")

        if not self.idempotency_key.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")

        if (
            self.entry_time.tzinfo is None
            or self.entry_time.utcoffset() is None
        ):
            raise ValueError(
                "entry_time은 시간대가 포함된 datetime이어야 합니다."
            )

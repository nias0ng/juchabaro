"""api 계층이 입차 이벤트를 접수할 때 거치는 조립 지점(383 미해결분, T-16).

api는 `tracking.ContextMatcher`를 직접 부르지 않는다 — 데이터흐름.md §7이
api의 책임을 "application 호출"로 명시하기 때문이다. 이 클래스는 그 사이를
잇는 얇은 창구다. `EntryContextEnricher`(같은 파일들 참고)와 달리
`ZoneRegistry`가 필요 없다 — 대기열에 적재하기만 하고 구역 겹침 판단은
하지 않으므로, `main.py`가 아직 구역을 로딩하지 않는 지금도 구성할 수 있다.
"""

from __future__ import annotations

from src.communication.models import EntryContext
from src.tracking.context_matcher import ContextMatcher


class EntryEventIntake:
    """`ContextMatcher`의 매칭 대기열에 입차 이벤트를 적재한다."""

    def __init__(self, matcher: ContextMatcher) -> None:
        self._matcher = matcher

    def receive(self, entry_context: EntryContext, *, idempotency_key: str) -> bool:
        """입차 이벤트 하나를 접수한다.

        반환값: 실제로 새로 접수했으면 True, 이미 처리한 idempotency_key라
        무시했으면 False.
        """

        return self._matcher.add_entry_context(entry_context, idempotency_key=idempotency_key)

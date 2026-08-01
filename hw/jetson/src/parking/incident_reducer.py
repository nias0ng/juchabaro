"""개별 규칙 결과를 중복 없는 사건 전이로 축약하는 구현 계약.

CANDIDATE는 Jetson 내부에만 유지한다. 최초 EDGE_CONFIRMED에서 OPEN을 한 번
만들고, 같은 IncidentKey의 반복 입력은 중복 발행하지 않는다. 확정 조건이
사라지면 RESOLVED와 RESOLVE를 한 번 만들며, 서로 다른 규칙과 에피소드의
사건은 동시에 독립적으로 유지한다.

**해소는 규칙 재판정 없이 스코프만으로도 가능하다(`resolve_scope`, 446 후속
리뷰).** `reduce()`로 해소하려면 호출부가 `IncidentKey`(특히 `rule_code`)를
다시 만들어야 하는데, `rule_code`는 구역 정의를 다시 조회해야 나온다 —
방문이 닫히는 시점에 그 구역이 이미 삭제돼 있으면(서버 구역 동기화 등)
rule_code를 재구성할 수 없어 해소 자체가 조용히 생략된다. 그런데 "방문이
끝났다"는 사실은 그 방문을 스코프로 삼은 사건이 전부 끝났다는 뜻이지, 규칙을
다시 판정할 문제가 아니다. `resolve_scope`는 이미 기록된 `Incident.key`를
그대로 재사용해 `zone_visit_id`만으로 찾아 닫으므로, 규칙 쪽이 무엇이었는지
다시 알아낼 필요가 없다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import uuid4

from src.parking.models import (
    Incident,
    IncidentId,
    IncidentKey,
    IncidentSignal,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    ZoneVisitId,
)
from src.parking.time_guard import ensure_forward_observation


def _latest_timestamp(incident: Incident) -> datetime:
    """이 사건에 기록된 가장 나중 시각.

    `first_observed_at` ≤ `confirmed_at` ≤ `resolved_at`이 사건의 불변식이므로
    채워진 것 중 가장 늦은 값이 다음 신호가 넘어서야 할 하한이다. 이 하한을
    깨는 신호를 받아들이면 `resolved_at`이 `confirmed_at`보다 앞서 위반
    지속시간이 음수인 채로 백엔드에 나간다.
    """

    return max(
        timestamp
        for timestamp in (
            incident.first_observed_at,
            incident.confirmed_at,
            incident.resolved_at,
        )
        if timestamp is not None
    )


class IncidentReducer(Protocol):
    """규칙 신호 하나를 외부 전송 가능한 사건 전이로 축약한다."""

    def reduce(self, signal: IncidentSignal) -> IncidentTransition | None:
        """OPEN/RESOLVE가 새로 생긴 경우에만 전이를 반환한다."""

        ...

    def resolve_scope(
        self, *, zone_visit_id: ZoneVisitId, observed_at: datetime
    ) -> tuple[IncidentTransition, ...]:
        """이 zone_visit_id를 스코프로 하는 열린 사건을 전부 해소한다.

        rule_code를 몰라도 된다 — 이미 기록된 사건의 rule_code를 그대로 쓴다.
        """

        ...


class InMemoryIncidentReducer:
    """규칙 신호를 중복 없는 사건 전이로 축약한다.

    CANDIDATE는 내부에만 유지하고 전이를 만들지 않는다. 같은 IncidentKey의
    반복 입력은 OPEN을 한 번만 만들고, 확정 조건이 사라지면 RESOLVE를 한 번
    만든다. 서로 다른 규칙·에피소드의 사건은 독립적으로 유지된다.
    """

    def __init__(self) -> None:
        self._incidents: dict[IncidentKey, Incident] = {}

    def reduce(self, signal: IncidentSignal) -> IncidentTransition | None:
        """OPEN/RESOLVE가 새로 생긴 경우에만 전이를 반환한다.

        `signal.observed_at`은 timezone-aware여야 하고 같은 IncidentKey에 이미
        기록된 가장 나중 시각보다 과거일 수 없다. 위반하면 ValueError다
        (`time_guard` 참조).
        """

        current = self._incidents.get(signal.key)
        # 순서 기준은 사건에 이미 기록된 시각에서 유도한다. IncidentKey별로 마지막
        # 관측 시각을 따로 들고 있으면 사건 저장소와 별개로 자라는 두 번째 무한
        # 저장소가 생긴다. 대신 CANDIDATE 구간의 반복 관측은 검사 대상이 아니다 —
        # 실제 피해(음수 지속시간)는 확정·해소 시각에서만 나온다.
        ensure_forward_observation(
            signal.observed_at, None if current is None else _latest_timestamp(current)
        )

        if signal.matched:
            return self._on_match(signal, current)
        return self._on_unmatch(signal, current)

    def resolve_scope(
        self, *, zone_visit_id: ZoneVisitId, observed_at: datetime
    ) -> tuple[IncidentTransition, ...]:
        """이 zone_visit_id를 스코프로 하는 열린 사건을 전부 해소한다.

        규칙(rule_code)을 몰라도 된다 — 이미 기록된 `Incident.key`를 그대로
        재사용해 찾아서 닫는다. 방문이 닫혔다는 사실 자체가 해소 사유이므로,
        판정 시점에 그 구역이 이미 삭제돼 rule_code를 재구성할 수 없어도
        (서버 구역 동기화 등) 사건을 닫을 수 있다.

        이 zone_visit_id로 열린 사건이 없으면(예: 자격이 있어 애초에 사건이
        생기지 않은 방문) 빈 튜플을 반환한다 — 아무 일도 하지 않는다.
        """

        transitions: list[IncidentTransition] = []
        # 순회 중 삭제(CANDIDATE 정리)가 있어 키를 먼저 스냅샷 뜬다.
        scoped_keys = [key for key in self._incidents if key.zone_visit_id == zone_visit_id]
        for key in scoped_keys:
            current = self._incidents[key]
            ensure_forward_observation(observed_at, _latest_timestamp(current))
            transition = self._resolve_incident(key, current, observed_at)
            if transition is not None:
                transitions.append(transition)
        return tuple(transitions)

    def snapshot(self) -> tuple[Incident, ...]:
        """현재 유지 중인 사건을 읽기 전용으로 반환한다. 판정에 영향을 주지 않는다."""

        return tuple(self._incidents.values())

    def _on_match(self, signal: IncidentSignal, current: Incident | None) -> IncidentTransition | None:
        if current is None or current.state is IncidentState.RESOLVED:
            # 해소된 사건과 같은 키로 다시 성립하면 새 사건이다. 재사용하면
            # revision이 계속 자라 백엔드가 두 사건을 구분할 수 없다.
            first_observed_at = signal.observed_at
            incident = Incident(
                incident_id=self._new_incident_id(),
                key=signal.key,
                state=IncidentState.CANDIDATE,
                revision=0,
                first_observed_at=first_observed_at,
            )
        else:
            incident = current

        if incident.state is IncidentState.EDGE_CONFIRMED:
            # 이미 확정해 발행했다. 중복 발행하지 않는다.
            self._incidents[signal.key] = incident
            return None

        if not signal.confirmable:
            # 내부 후보로만 유지한다. Backend로 나가지 않는다.
            self._incidents[signal.key] = incident
            return None

        confirmed = Incident(
            incident_id=incident.incident_id,
            key=incident.key,
            state=IncidentState.EDGE_CONFIRMED,
            revision=incident.revision + 1,
            first_observed_at=incident.first_observed_at,
            confirmed_at=signal.observed_at,
        )
        self._incidents[signal.key] = confirmed
        return IncidentTransition(
            transition_type=IncidentTransitionType.OPEN, incident=confirmed
        )

    def _on_unmatch(self, signal: IncidentSignal, current: Incident | None) -> IncidentTransition | None:
        if current is None:
            return None
        return self._resolve_incident(signal.key, current, signal.observed_at)

    def _resolve_incident(
        self, key: IncidentKey, current: Incident, observed_at: datetime
    ) -> IncidentTransition | None:
        """`current`를 RESOLVED로 전이시킨다. `resolve_scope`와 `_on_unmatch`가 공유한다."""

        if current.state is IncidentState.CANDIDATE:
            # Backend가 본 적 없는 후보다. 조용히 버린다.
            del self._incidents[key]
            return None

        if current.state is IncidentState.RESOLVED:
            # 이미 해소를 알렸다.
            return None

        resolved = Incident(
            incident_id=current.incident_id,
            key=current.key,
            state=IncidentState.RESOLVED,
            revision=current.revision + 1,
            first_observed_at=current.first_observed_at,
            confirmed_at=current.confirmed_at,
            resolved_at=observed_at,
        )
        self._incidents[key] = resolved
        return IncidentTransition(
            transition_type=IncidentTransitionType.RESOLVE, incident=resolved
        )

    @staticmethod
    def _new_incident_id() -> IncidentId:
        """새로 시작한 사건의 불투명한 수명주기 ID를 발급한다."""

        return IncidentId(uuid4())

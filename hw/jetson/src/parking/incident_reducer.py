"""개별 규칙 결과를 중복 없는 사건 전이로 축약하는 구현 계약.

CANDIDATE는 Jetson 내부에만 유지한다. 최초 EDGE_CONFIRMED에서 OPEN을 한 번
만들고, 같은 IncidentKey의 반복 입력은 중복 발행하지 않는다. 확정 조건이
사라지면 RESOLVED와 RESOLVE를 한 번 만들며, 서로 다른 규칙과 에피소드의
사건은 동시에 독립적으로 유지한다.
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

        if current.state is IncidentState.CANDIDATE:
            # Backend가 본 적 없는 후보다. 조용히 버린다.
            del self._incidents[signal.key]
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
            resolved_at=signal.observed_at,
        )
        self._incidents[signal.key] = resolved
        return IncidentTransition(
            transition_type=IncidentTransitionType.RESOLVE, incident=resolved
        )

    @staticmethod
    def _new_incident_id() -> IncidentId:
        """새로 시작한 사건의 불투명한 수명주기 ID를 발급한다."""

        return IncidentId(uuid4())

"""개별 규칙 결과를 중복 없는 사건 전이로 축약하는 구현 계약.

CANDIDATE는 Jetson 내부에만 유지한다. 최초 EDGE_CONFIRMED에서 OPEN을 한 번
만들고, 같은 IncidentKey의 반복 입력은 중복 발행하지 않는다. 확정 조건이
사라지면 RESOLVED와 RESOLVE를 한 번 만들며, 서로 다른 규칙과 에피소드의
사건은 동시에 독립적으로 유지한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

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
                incident_id=self._make_incident_id(signal.key, first_observed_at),
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
    def _make_incident_id(key: IncidentKey, first_observed_at: datetime) -> IncidentId:
        """결정론적 사건 ID. 스펙 §8 와이어 예시는 UUID를 적었지만 결정론
        요구와 충돌한다 — 백엔드는 멱등 upsert만 하므로 형식은 자유다.

        **서로 다른 IncidentKey는 서로 다른 ID를 가져야 한다.** 백엔드가
        incident_id로 멱등 upsert를 하므로 두 키가 한 ID로 합쳐지면 서로 다른 두
        위반이 조용히 한 건이 된다. 그래서 스코프(에피소드/방문)뿐 아니라 키를
        가르는 나머지 필드(`zone_id`, `victim_physical_vehicle_id`)도 전부 넣는다.
        에피소드 스코프인 bad_parking(구역별)과 피해차량별 double_parking이
        들어오면 이 두 필드가 유일한 구분자가 된다.

        `physical_vehicle_id`는 일부러 넣지 않는다. 스펙 4.3이 IncidentKey에서 그
        필드를 없앨 예정이라 ID 유도가 거기 기대면 제거 시점에 모든 ID가 바뀐다.
        제거 뒤 키의 유일성은 스코프 쪽이 책임진다 — 모든 규칙은 방문 또는
        에피소드 스코프를 반드시 채워야 한다.

        선택 필드는 값이 있을 때만 `|` 뒤에 덧붙인다. 둘 다 비어 있는 키의 ID는
        이전과 글자 그대로 같아 불필요한 ID 변경이 생기지 않는다. `|`를 쓰는
        이유는 앞부분이 ISO 시각이라 `:`로 이어 붙이면 경계가 모호해지기
        때문이다.
        """

        scope = key.parking_episode_id or key.zone_visit_id or "no-scope"
        parts = [f"{key.rule_code}:{scope}:{first_observed_at.isoformat()}"]
        if key.zone_id is not None:
            parts.append(f"zone={key.zone_id}")
        if key.victim_physical_vehicle_id is not None:
            parts.append(f"victim={key.victim_physical_vehicle_id}")
        return IncidentId("|".join(parts))

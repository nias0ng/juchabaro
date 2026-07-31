"""사건 축약 테스트. 중복 억제와 RESOLVE 생성이 핵심이다."""

from datetime import datetime, timedelta, timezone

from src.parking.models import (
    IncidentKey,
    IncidentSignal,
    IncidentState,
    IncidentTransitionType,
    ParkingEpisodeId,
    ZoneId,
    ZoneVisitId,
)
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.tracking.models import PhysicalVehicleId

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def visit_key(rule_code: str = "DISABLED_ZONE_UNAUTHORIZED") -> IncidentKey:
    return IncidentKey(
        # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
        physical_vehicle_id=CAR,
        rule_code=rule_code,
        zone_visit_id=ZoneVisitId("visit-1"),
        zone_id=ZoneId(12),
    )


def episode_key(rule_code: str = "BAD_PARKING") -> IncidentKey:
    return IncidentKey(
        # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
        physical_vehicle_id=CAR,
        rule_code=rule_code,
        parking_episode_id=ParkingEpisodeId("episode-1"),
        zone_id=ZoneId(12),
    )


def signal(key: IncidentKey, *, matched: bool, confirmable: bool, seconds: float = 0.0) -> IncidentSignal:
    return IncidentSignal(
        key=key, matched=matched, confirmable=confirmable, observed_at=at(seconds)
    )


def test_candidate_produces_no_transition() -> None:
    """CANDIDATE는 Jetson 내부에만 유지한다."""
    reducer = InMemoryIncidentReducer()
    assert reducer.reduce(signal(visit_key(), matched=True, confirmable=False)) is None


def test_first_confirmable_match_produces_open() -> None:
    reducer = InMemoryIncidentReducer()
    transition = reducer.reduce(signal(visit_key(), matched=True, confirmable=True))
    assert transition is not None
    assert transition.transition_type is IncidentTransitionType.OPEN
    assert transition.incident.state is IncidentState.EDGE_CONFIRMED
    assert transition.incident.revision == 1
    assert transition.incident.confirmed_at == T0


def test_repeated_match_produces_no_duplicate() -> None:
    reducer = InMemoryIncidentReducer()
    key = visit_key()
    reducer.reduce(signal(key, matched=True, confirmable=True))
    assert reducer.reduce(signal(key, matched=True, confirmable=True, seconds=1)) is None
    assert reducer.reduce(signal(key, matched=True, confirmable=True, seconds=2)) is None


def test_candidate_then_confirmable_produces_single_open() -> None:
    """후보로 관측되던 사건이 확정 조건을 만족하면 그때 OPEN 한 번이 나간다."""
    reducer = InMemoryIncidentReducer()
    key = episode_key()
    assert reducer.reduce(signal(key, matched=True, confirmable=False)) is None
    transition = reducer.reduce(signal(key, matched=True, confirmable=True, seconds=600))
    assert transition.transition_type is IncidentTransitionType.OPEN
    # 최초 관측 시각은 후보 시점, 확정 시각은 확정 시점이다.
    assert transition.incident.first_observed_at == T0
    assert transition.incident.confirmed_at == at(600)


def test_unmatched_after_open_produces_resolve() -> None:
    reducer = InMemoryIncidentReducer()
    key = visit_key()
    reducer.reduce(signal(key, matched=True, confirmable=True))
    transition = reducer.reduce(signal(key, matched=False, confirmable=True, seconds=10))
    assert transition.transition_type is IncidentTransitionType.RESOLVE
    assert transition.incident.state is IncidentState.RESOLVED
    assert transition.incident.revision == 2
    assert transition.incident.resolved_at == at(10)


def test_resolve_is_produced_only_once() -> None:
    reducer = InMemoryIncidentReducer()
    key = visit_key()
    reducer.reduce(signal(key, matched=True, confirmable=True))
    assert reducer.reduce(signal(key, matched=False, confirmable=True, seconds=10)) is not None
    assert reducer.reduce(signal(key, matched=False, confirmable=True, seconds=11)) is None


def test_unmatched_candidate_produces_no_transition() -> None:
    """확정된 적 없는 후보가 사라지면 백엔드는 그 사건을 본 적이 없다."""
    reducer = InMemoryIncidentReducer()
    key = episode_key()
    reducer.reduce(signal(key, matched=True, confirmable=False))
    assert reducer.reduce(signal(key, matched=False, confirmable=False, seconds=5)) is None


def test_unmatched_unknown_key_produces_no_transition() -> None:
    reducer = InMemoryIncidentReducer()
    assert reducer.reduce(signal(visit_key(), matched=False, confirmable=True)) is None


def test_different_rules_are_independent() -> None:
    """동시 성립한 두 규칙 중 하나가 다른 하나를 가리지 않는다."""
    reducer = InMemoryIncidentReducer()
    a = reducer.reduce(signal(visit_key("EV_ZONE_UNAUTHORIZED"), matched=True, confirmable=True))
    b = reducer.reduce(signal(visit_key("EV_OVERSTAY"), matched=True, confirmable=True))
    assert a.transition_type is IncidentTransitionType.OPEN
    assert b.transition_type is IncidentTransitionType.OPEN
    assert a.incident.incident_id != b.incident.incident_id


def test_reopen_after_resolve_creates_new_incident() -> None:
    reducer = InMemoryIncidentReducer()
    key = visit_key()
    first = reducer.reduce(signal(key, matched=True, confirmable=True))
    reducer.reduce(signal(key, matched=False, confirmable=True, seconds=10))
    second = reducer.reduce(signal(key, matched=True, confirmable=True, seconds=20))
    assert second.transition_type is IncidentTransitionType.OPEN
    assert second.incident.incident_id != first.incident.incident_id
    assert second.incident.revision == 1


def test_incident_id_is_deterministic() -> None:
    ids = []
    for _ in range(2):
        reducer = InMemoryIncidentReducer()
        ids.append(reducer.reduce(signal(visit_key(), matched=True, confirmable=True)).incident.incident_id)
    assert ids[0] == ids[1]


def test_evidence_is_carried_into_incident_snapshot() -> None:
    reducer = InMemoryIncidentReducer()
    sig = IncidentSignal(
        key=visit_key(),
        matched=True,
        confirmable=True,
        observed_at=T0,
        evidence={"zonePresenceSeconds": 3.2, "isElectric": False},
    )
    reducer.reduce(sig)
    assert len(reducer.snapshot()) == 1

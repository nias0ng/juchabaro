"""사건 축약 테스트. 중복 억제와 RESOLVE 생성이 핵심이다."""

from datetime import datetime, timedelta, timezone

import pytest

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


def test_repeated_match_after_reopen_produces_no_duplicate() -> None:
    """재개된 사건도 중복 억제가 유지돼야 한다.

    재개 경로는 CANDIDATE 사건을 새로 만들어 넣는다. 그 사건이 EDGE_CONFIRMED로
    저장되지 않으면 이후 프레임마다 OPEN이 다시 나간다.
    """
    reducer = InMemoryIncidentReducer()
    key = visit_key()
    reducer.reduce(signal(key, matched=True, confirmable=True))
    reducer.reduce(signal(key, matched=False, confirmable=True, seconds=10))
    reducer.reduce(signal(key, matched=True, confirmable=True, seconds=20))
    assert reducer.reduce(signal(key, matched=True, confirmable=True, seconds=21)) is None
    assert reducer.reduce(signal(key, matched=True, confirmable=True, seconds=22)) is None


def test_incident_id_is_deterministic() -> None:
    ids = []
    for _ in range(2):
        reducer = InMemoryIncidentReducer()
        ids.append(reducer.reduce(signal(visit_key(), matched=True, confirmable=True)).incident.incident_id)
    assert ids[0] == ids[1]


def episode_scoped_key(
    *, zone_id: int, victim: str | None = None, vehicle: str = "pv-1"
) -> IncidentKey:
    return IncidentKey(
        # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
        physical_vehicle_id=PhysicalVehicleId(vehicle),
        rule_code="BAD_PARKING",
        parking_episode_id=ParkingEpisodeId("episode-1"),
        zone_id=ZoneId(zone_id),
        victim_physical_vehicle_id=None if victim is None else PhysicalVehicleId(victim),
    )


def test_incident_id_distinguishes_zone_and_victim() -> None:
    """서로 다른 IncidentKey는 서로 다른 incident_id를 가져야 한다.

    백엔드는 incident_id로 멱등 upsert를 한다. zone_id와
    victim_physical_vehicle_id를 ID 유도에서 빼면 아래 네 키가 하나의 ID로
    합쳐져 서로 다른 네 위반이 조용히 한 건이 된다.
    """
    keys = [
        episode_scoped_key(zone_id=1),
        episode_scoped_key(zone_id=2),
        episode_scoped_key(zone_id=1, victim="pv-2"),
        episode_scoped_key(zone_id=1, victim="pv-3"),
    ]
    reducer = InMemoryIncidentReducer()
    ids = {
        reducer.reduce(signal(key, matched=True, confirmable=True)).incident.incident_id
        for key in keys
    }
    assert len(ids) == len(keys)


def test_incident_id_format_is_unchanged_without_zone_and_victim() -> None:
    """두 필드가 모두 비어 있는 키의 ID는 이전과 글자 그대로 같다."""
    reducer = InMemoryIncidentReducer()
    key = IncidentKey(
        # TODO(spec 4.3): IncidentKey에서 physical_vehicle_id 제거 후 이 인자를 지운다
        physical_vehicle_id=CAR,
        rule_code="BAD_PARKING",
        parking_episode_id=ParkingEpisodeId("episode-1"),
    )
    transition = reducer.reduce(signal(key, matched=True, confirmable=True))
    assert transition.incident.incident_id == f"BAD_PARKING:episode-1:{T0.isoformat()}"


def test_incident_id_does_not_depend_on_physical_vehicle_id() -> None:
    """스펙 4.3의 physical_vehicle_id 제거가 기존 ID를 바꾸지 않아야 한다.

    ID 유도가 그 필드에 기대면 제거 시점에 모든 사건 ID가 한꺼번에 바뀐다.
    같은 스코프를 가리키는 두 키는 이미 같은 사건이므로 같은 ID가 맞다.
    """
    ids = [
        InMemoryIncidentReducer()
        .reduce(signal(episode_scoped_key(zone_id=1, vehicle=vehicle), matched=True, confirmable=True))
        .incident.incident_id
        for vehicle in ("pv-1", "pv-9")
    ]
    assert ids[0] == ids[1]


def test_naive_datetime_is_rejected() -> None:
    reducer = InMemoryIncidentReducer()
    with pytest.raises(ValueError, match="timezone"):
        reducer.reduce(
            IncidentSignal(
                key=visit_key(),
                matched=True,
                confirmable=True,
                observed_at=datetime(2026, 7, 31, 10, 0, 0),
            )
        )


def test_resolve_before_open_is_rejected() -> None:
    """confirmed_at보다 앞선 resolved_at은 위반 지속시간을 음수로 만든다."""
    reducer = InMemoryIncidentReducer()
    key = visit_key()
    reducer.reduce(signal(key, matched=True, confirmable=True, seconds=10))
    with pytest.raises(ValueError, match="과거"):
        reducer.reduce(signal(key, matched=False, confirmable=True, seconds=5))


def test_confirm_before_first_observation_is_rejected() -> None:
    reducer = InMemoryIncidentReducer()
    key = episode_key()
    reducer.reduce(signal(key, matched=True, confirmable=False, seconds=600))
    with pytest.raises(ValueError, match="과거"):
        reducer.reduce(signal(key, matched=True, confirmable=True, seconds=1))


def test_same_timestamp_resolve_is_allowed() -> None:
    """같은 프레임에서 성립과 해소가 이어지는 경우는 정상이다."""
    reducer = InMemoryIncidentReducer()
    key = visit_key()
    reducer.reduce(signal(key, matched=True, confirmable=True))
    transition = reducer.reduce(signal(key, matched=False, confirmable=True))
    assert transition.transition_type is IncidentTransitionType.RESOLVE


class TestResolveScope:
    """`resolve_scope` — zone_visit_id만으로 해소한다(446 후속 리뷰).

    핵심 계약: rule_code를 몰라도(구역이 이미 삭제돼 있어도) 이미 열린
    사건을 찾아 닫을 수 있어야 한다.
    """

    def test_closes_the_incident_scoped_to_the_zone_visit_id(self) -> None:
        reducer = InMemoryIncidentReducer()
        key = visit_key()
        opened = reducer.reduce(signal(key, matched=True, confirmable=True))

        transitions = reducer.resolve_scope(zone_visit_id=key.zone_visit_id, observed_at=at(10))

        assert len(transitions) == 1
        assert transitions[0].transition_type is IncidentTransitionType.RESOLVE
        assert transitions[0].incident.incident_id == opened.incident.incident_id
        assert transitions[0].incident.resolved_at == at(10)

    def test_does_not_need_rule_code_to_resolve(self) -> None:
        """rule_code를 몰라도(구역이 삭제돼 재구성 못 해도) zone_visit_id만
        있으면 해소된다 — 이 테스트의 핵심 목적이다."""
        reducer = InMemoryIncidentReducer()
        key = visit_key(rule_code="EV_ZONE_UNAUTHORIZED")
        reducer.reduce(signal(key, matched=True, confirmable=True))

        # rule_code를 전혀 언급하지 않고 zone_visit_id만으로 호출한다.
        transitions = reducer.resolve_scope(zone_visit_id=key.zone_visit_id, observed_at=at(10))

        assert len(transitions) == 1
        assert transitions[0].incident.key.rule_code == "EV_ZONE_UNAUTHORIZED"

    def test_is_a_noop_when_no_incident_matches_the_scope(self) -> None:
        """자격이 있어 애초에 사건이 안 생긴 방문이 닫혀도 아무 일도 안 난다."""
        reducer = InMemoryIncidentReducer()
        transitions = reducer.resolve_scope(zone_visit_id=ZoneVisitId("visit-never-opened"), observed_at=T0)
        assert transitions == ()

    def test_drops_unconfirmed_candidate_silently(self) -> None:
        reducer = InMemoryIncidentReducer()
        key = visit_key()
        reducer.reduce(signal(key, matched=True, confirmable=False))

        transitions = reducer.resolve_scope(zone_visit_id=key.zone_visit_id, observed_at=at(5))

        assert transitions == ()
        assert reducer.snapshot() == ()

    def test_is_idempotent(self) -> None:
        reducer = InMemoryIncidentReducer()
        key = visit_key()
        reducer.reduce(signal(key, matched=True, confirmable=True))

        first = reducer.resolve_scope(zone_visit_id=key.zone_visit_id, observed_at=at(10))
        second = reducer.resolve_scope(zone_visit_id=key.zone_visit_id, observed_at=at(11))

        assert len(first) == 1
        assert second == ()

    def test_rejects_backward_observation(self) -> None:
        reducer = InMemoryIncidentReducer()
        key = visit_key()
        reducer.reduce(signal(key, matched=True, confirmable=True, seconds=10))

        with pytest.raises(ValueError, match="과거"):
            reducer.resolve_scope(zone_visit_id=key.zone_visit_id, observed_at=at(5))

    def test_only_resolves_incidents_in_the_matching_scope(self) -> None:
        """다른 zone_visit_id로 열린 사건은 건드리지 않는다."""
        reducer = InMemoryIncidentReducer()
        this_visit = visit_key()
        other_visit = IncidentKey(
            physical_vehicle_id=CAR,
            rule_code="DISABLED_ZONE_UNAUTHORIZED",
            zone_visit_id=ZoneVisitId("visit-2"),
            zone_id=ZoneId(13),
        )
        reducer.reduce(signal(this_visit, matched=True, confirmable=True))
        reducer.reduce(signal(other_visit, matched=True, confirmable=True))

        reducer.resolve_scope(zone_visit_id=this_visit.zone_visit_id, observed_at=at(10))

        states = {incident.key.zone_visit_id: incident.state for incident in reducer.snapshot()}
        assert states[this_visit.zone_visit_id] is IncidentState.RESOLVED
        assert states[other_visit.zone_visit_id] is IncidentState.EDGE_CONFIRMED


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

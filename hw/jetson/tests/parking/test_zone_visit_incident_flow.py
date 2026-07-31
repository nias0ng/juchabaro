"""구역 방문 → 전용구역 규칙 → 사건 축약을 한 줄로 이은 통합 테스트.

세 모듈이 한 브랜치에 함께 존재하는 것은 이번이 처음이다. 각자의 단위 테스트는
전부 통과하는데도 이어 붙이면 사건이 영원히 닫히지 않는 결함이 있었다 —
트래커가 닫은 방문을 규칙이 버렸고 `active_visits()`도 내보내지 않아 RESOLVE의
유일한 입력인 `matched=False`가 만들어지지 않았다. 모듈 경계마다 계약이 맞물리는
지점은 여기서만 검증된다.

`Frames`는 조립기가 프레임마다 하는 일을 그대로 흉내 낸다. 판정은 하지 않는다 —
데이터흐름.md에서 application 계층은 조립만 하고 판정하지 않기 때문이다.

1. 관측된 (차량, 구역) 쌍마다 `tracker.update()`
2. **이번 프레임에 관측된 차량만** 돌며 `tracker.active_visits()` → 규칙 →
   `IncidentReducer.reduce()`
3. `tracker.prune(now)` → **반환된 강제 종료 방문도** 규칙 → `reduce()`

2번이 관측된 차량만 도는 것이 핵심이다. 추적이 끊긴 차량에는 `active_visits()`를
부를 이유도 방법도 없다 — 누구를 물어봐야 하는지 모른다. 그 차량의 종료는 3번의
반환값으로만 나온다. 모든 프레임에서 `active_visits(CAR)`를 고정 호출하는 헬퍼는
그 결함을 통과시킨다(실제로 통과시켰다). 여기서는 그렇게 하지 않는다.
"""

from datetime import datetime, timedelta, timezone

from src.parking.geometry import NormalizedPolygon
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.models import (
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    PresenceSignal,
    ZoneId,
    ZoneVisitState,
)
from src.parking.rules.models import RuleContext
from src.parking.rules.restricted_zone import evaluate_open
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    VehicleContext,
)

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")
OTHER_CAR = PhysicalVehicleId("pv-2")
ZONE = ZoneId(1)
SQUARE = NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)))
DISABLED_ZONE = ParkingZone(
    zone_id=ZONE, zone_number="D-01", zone_type=ZoneType.DISABLED, polygon=SQUARE
)
UNAUTHORIZED = VehicleContext(
    parking_session_id=1, vehicle_id=1, is_electric=False, is_disabled_vehicle=False
)
AUTHORIZED = VehicleContext(
    parking_session_id=1, vehicle_id=1, is_electric=False, is_disabled_vehicle=True
)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


class Frames:
    """조립기의 프레임 루프를 재현한다. 규칙 판정이나 상태 해석은 하지 않는다."""

    def __init__(self, *, entry: float = 1.0, exit_: float = 1.0, stale: float = 300.0) -> None:
        self.tracker = InMemoryZoneVisitTracker(
            entry_confirm_seconds=entry,
            exit_confirm_seconds=exit_,
            stale_after_seconds=stale,
        )
        self.reducer = InMemoryIncidentReducer()
        self.zones = ZoneRegistry([DISABLED_ZONE])

    def frame(
        self,
        observations: dict[PhysicalVehicleId, PresenceSignal],
        seconds: float,
        *,
        contexts: dict[PhysicalVehicleId, VehicleContext] | None = None,
    ) -> tuple[IncidentTransition, ...]:
        """프레임 하나를 돌리고 백엔드로 나갈 전이를 반환한다.

        `observations`에는 **이번 프레임에 관측된 차량만** 들어간다. 빠진 차량은
        추적이 끊긴 것이며, 판정 루프도 그 차량을 돌지 않는다.
        """

        now = at(seconds)
        contexts = contexts or {}

        for vehicle, signal in observations.items():
            self.tracker.update(
                physical_vehicle_id=vehicle, zone_id=ZONE, signal=signal, observed_at=now
            )

        transitions: list[IncidentTransition] = []
        # 관측된 차량만 돈다. 조립기가 아는 차량이 그것뿐이기 때문이다.
        for vehicle in observations:
            visits = self.tracker.active_visits(vehicle)
            transitions += self._judge_open(vehicle, visits, now, contexts)
            transitions += self._judge_resolved(visits, now)
        # 강제 종료된 방문은 이 반환값으로만 나온다. 버리면 그 사건은 닫히지 않는다.
        # resolve_scope는 규칙도 스냅샷도 필요 없으므로(446 후속 리뷰),
        # 추적이 끊긴 차량이라도 zone_visit_id만으로 그대로 해소할 수 있다.
        transitions += self._judge_resolved(self.tracker.prune(now), now)
        return tuple(transitions)

    def _judge_open(self, vehicle, visits, now, contexts) -> list[IncidentTransition]:
        if not visits:
            return []
        context = contexts.get(vehicle, UNAUTHORIZED)
        rule_context = RuleContext(
            vehicle=PhysicalVehicleSnapshot(
                physical_vehicle_id=vehicle,
                track_segment_id=TrackSegmentId(1),
                bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
                confidence=0.9,
                motion_signal=MotionSignal.STATIONARY,
                observed_at=now,
                camera_id="cam-1",
                context=context,
            ),
            vehicle_context=context,
            active_zone_visits=tuple(visits),
            parking_episode=None,
            parking_assignment=None,
            zones=self.zones,
            observed_at=now,
        )
        return [
            transition
            for transition in (
                self.reducer.reduce(signal_out) for signal_out in evaluate_open(rule_context)
            )
            if transition is not None
        ]

    def _judge_resolved(self, visits, now) -> list[IncidentTransition]:
        transitions: list[IncidentTransition] = []
        for visit in visits:
            if visit.state is not ZoneVisitState.OUTSIDE:
                continue
            transitions.extend(
                self.reducer.resolve_scope(zone_visit_id=visit.visit_id, observed_at=now)
            )
        return transitions

    def run(
        self,
        signal: PresenceSignal | None,
        seconds: float,
        *,
        context: VehicleContext = UNAUTHORIZED,
    ) -> tuple[IncidentTransition, ...]:
        """차량 한 대짜리 프레임. `signal`이 `None`이면 그 프레임에 관측이 없었다."""

        return self.frame(
            {} if signal is None else {CAR: signal}, seconds, contexts={CAR: context}
        )

    def states(self) -> list[IncidentState]:
        return [incident.state for incident in self.reducer.snapshot()]


def types(transitions: tuple[IncidentTransition, ...]) -> list[IncidentTransitionType]:
    return [transition.transition_type for transition in transitions]


def test_entry_opens_and_exit_resolves_the_incident() -> None:
    """무자격 차량의 진입이 OPEN을, 이탈이 RESOLVE를 만든다.

    이 테스트가 없어서, 세 모듈의 단위 테스트가 모두 통과하는데도 RESOLVE가
    구조적으로 도달 불가능한 상태가 리뷰까지 살아남았다.
    """
    frames = Frames()

    assert frames.run(PresenceSignal.PRESENT, 0) == ()  # ENTERING — 아직 판정 대상 아님
    opened = frames.run(PresenceSignal.PRESENT, 1)  # INSIDE
    assert types(opened) == [IncidentTransitionType.OPEN]
    assert frames.run(PresenceSignal.PRESENT, 2) == ()  # 중복 발행 없음
    assert frames.run(PresenceSignal.ABSENT, 3) == ()  # EXITING — 아직 닫지 않는다

    resolved = frames.run(PresenceSignal.ABSENT, 4)  # 이탈 확인 → 방문 종료
    assert types(resolved) == [IncidentTransitionType.RESOLVE]
    assert resolved[0].incident.incident_id == opened[0].incident.incident_id
    assert resolved[0].incident.resolved_at >= opened[0].incident.confirmed_at
    assert frames.states() == [IncidentState.RESOLVED]


def test_resolve_is_emitted_exactly_once() -> None:
    """종료 슬롯이 여러 프레임에 걸쳐 보이면 RESOLVE가 중복 발행된다."""
    frames = Frames()
    frames.run(PresenceSignal.PRESENT, 0)
    frames.run(PresenceSignal.PRESENT, 1)
    frames.run(PresenceSignal.ABSENT, 2)
    assert types(frames.run(PresenceSignal.ABSENT, 3)) == [IncidentTransitionType.RESOLVE]
    for second in (4, 5, 6):
        assert frames.run(PresenceSignal.ABSENT, float(second)) == ()


def test_reentry_does_not_leave_the_previous_incident_open() -> None:
    """재진입은 새 사건이다. 앞 사건이 EDGE_CONFIRMED로 남으면 드나들 때마다 쌓인다."""
    frames = Frames()
    frames.run(PresenceSignal.PRESENT, 0)
    opened = frames.run(PresenceSignal.PRESENT, 1)
    frames.run(PresenceSignal.ABSENT, 2)
    frames.run(PresenceSignal.ABSENT, 3)

    frames.run(PresenceSignal.PRESENT, 10)
    reopened = frames.run(PresenceSignal.PRESENT, 11)
    assert types(reopened) == [IncidentTransitionType.OPEN]
    assert reopened[0].incident.incident_id != opened[0].incident.incident_id
    # 앞 사건은 해소됐고, 열린 사건은 방금 만든 하나뿐이다.
    assert sorted(frames.states()) == sorted(
        [IncidentState.RESOLVED, IncidentState.EDGE_CONFIRMED]
    )


def test_qualified_vehicle_never_opens_an_incident() -> None:
    frames = Frames()
    frames.run(PresenceSignal.PRESENT, 0, context=AUTHORIZED)
    assert frames.run(PresenceSignal.PRESENT, 1, context=AUTHORIZED) == ()
    assert frames.run(PresenceSignal.ABSENT, 2, context=AUTHORIZED) == ()
    assert frames.run(PresenceSignal.ABSENT, 3, context=AUTHORIZED) == ()
    # 백엔드가 본 적 없는 후보는 조용히 사라진다.
    assert frames.states() == []


def test_lost_track_is_resolved_by_prune() -> None:
    """관측이 아예 끊긴 차량의 사건도 닫혀야 한다.

    조립기가 그 차량에 대한 update()를 멈추면 트래커는 스스로 이탈을 알 수 없고,
    판정 루프는 관측된 차량만 도니 그 차량을 조회하지도 않는다. prune()이 강제
    종료한 방문을 **반환**하고 조립기가 그 반환값을 판정에 넘겨야만 닫힌다.
    """
    frames = Frames(stale=30.0)
    frames.run(PresenceSignal.PRESENT, 0)
    assert types(frames.run(PresenceSignal.PRESENT, 1)) == [IncidentTransitionType.OPEN]

    # 관측 없는 프레임이 이어진다. 유휴 한도를 넘기 전에는 사건을 닫지 않는다.
    assert frames.run(None, 20) == ()
    assert frames.states() == [IncidentState.EDGE_CONFIRMED]

    # 한도를 넘긴 prune()이 방문을 강제 종료해 반환하고, 같은 프레임에서 닫힌다.
    assert types(frames.run(None, 40)) == [IncidentTransitionType.RESOLVE]
    assert frames.states() == [IncidentState.RESOLVED]
    # 재차 확인: 남은 슬롯도, 미해소 사건도 없다.
    assert frames.run(None, 41) == ()
    assert frames.tracker.active_visits(CAR) == ()


def test_lost_track_resolves_while_judging_only_observed_vehicles() -> None:
    """현실적인 조립기 루프의 모양이다. 관측된 차량만 판정하는데도 RESOLVE가 나야 한다.

    pv-1은 계속 추적되고 pv-2는 t=1 이후 추적이 끊긴다. 판정 루프는 pv-2를 한
    번도 돌지 않는다 — 조립기는 pv-2가 아직 구역 안에 방문을 열어 두고 있다는
    사실조차 모른다. 그럼에도 pv-2의 사건은 닫혀야 한다.
    """
    frames = Frames(stale=30.0)
    both = {CAR: PresenceSignal.PRESENT, OTHER_CAR: PresenceSignal.PRESENT}
    frames.frame(both, 0)
    opened = frames.frame(both, 1)
    assert types(opened) == [IncidentTransitionType.OPEN, IncidentTransitionType.OPEN]

    # 여기서부터 pv-2는 관측되지 않는다. 판정 루프에도 들어오지 않는다.
    # pv-2의 마지막 갱신은 t=1이므로 t=31에 유휴 한도 30초를 넘긴다.
    for second in range(2, 31):
        assert frames.frame({CAR: PresenceSignal.PRESENT}, float(second)) == ()

    resolved = frames.frame({CAR: PresenceSignal.PRESENT}, 31)
    assert types(resolved) == [IncidentTransitionType.RESOLVE]
    assert resolved[0].incident.key.physical_vehicle_id == OTHER_CAR

    by_vehicle = {
        incident.key.physical_vehicle_id: incident.state
        for incident in frames.reducer.snapshot()
    }
    # 살아 있는 차량의 위반은 그대로 열려 있고, 사라진 차량의 위반만 닫혔다.
    assert by_vehicle == {
        CAR: IncidentState.EDGE_CONFIRMED,
        OTHER_CAR: IncidentState.RESOLVED,
    }


def test_unknown_qualification_stays_a_candidate_and_is_dropped_on_exit() -> None:
    """자격을 못 얻은 차량은 백엔드로 나가지 않고, 나갈 때도 전이를 만들지 않는다."""
    unknown = VehicleContext(
        parking_session_id=None, vehicle_id=None, is_electric=None, is_disabled_vehicle=None
    )
    frames = Frames()
    frames.run(PresenceSignal.PRESENT, 0, context=unknown)
    assert frames.run(PresenceSignal.PRESENT, 1, context=unknown) == ()
    assert frames.states() == [IncidentState.CANDIDATE]
    frames.run(PresenceSignal.ABSENT, 2, context=unknown)
    assert frames.run(PresenceSignal.ABSENT, 3, context=unknown) == ()
    assert frames.states() == []

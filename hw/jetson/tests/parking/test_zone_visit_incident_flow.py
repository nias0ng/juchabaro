"""구역 방문 → 전용구역 규칙 → 사건 축약을 한 줄로 이은 통합 테스트.

세 모듈이 한 브랜치에 함께 존재하는 것은 이번이 처음이다. 각자의 단위 테스트는
전부 통과하는데도 이어 붙이면 사건이 영원히 닫히지 않는 결함이 있었다 —
트래커가 닫은 방문을 규칙이 버렸고 `active_visits()`도 내보내지 않아 RESOLVE의
유일한 입력인 `matched=False`가 만들어지지 않았다. 모듈 경계마다 계약이 맞물리는
지점은 여기서만 검증된다.

`Frames`는 조립기가 프레임마다 하는 일을 그대로 흉내 낸다. 판정은 하지 않는다 —
데이터흐름.md에서 application 계층은 조립만 하고 판정하지 않기 때문이다.

1. 관측된 (차량, 구역) 쌍마다 `tracker.update()`
2. `tracker.active_visits()` → 규칙 → `IncidentReducer.reduce()`
3. `tracker.prune(now)`
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
)
from src.parking.rules.models import RuleContext
from src.parking.rules.restricted_zone import evaluate
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

    def run(
        self,
        signal: PresenceSignal | None,
        seconds: float,
        *,
        context: VehicleContext = UNAUTHORIZED,
    ) -> tuple[IncidentTransition, ...]:
        """프레임 하나를 돌리고 백엔드로 나갈 전이를 반환한다.

        `signal`이 `None`이면 이 프레임에 그 차량 관측이 아예 없었다는 뜻이다 —
        추적이 끊긴 상황을 재현한다.
        """

        now = at(seconds)
        if signal is not None:
            self.tracker.update(
                physical_vehicle_id=CAR, zone_id=ZONE, signal=signal, observed_at=now
            )
        rule_context = RuleContext(
            vehicle=PhysicalVehicleSnapshot(
                physical_vehicle_id=CAR,
                track_segment_id=TrackSegmentId(1),
                bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
                confidence=0.9,
                motion_signal=MotionSignal.STATIONARY,
                observed_at=now,
                camera_id="cam-1",
                context=context,
            ),
            vehicle_context=context,
            active_zone_visits=self.tracker.active_visits(CAR),
            parking_episode=None,
            parking_assignment=None,
            zones=self.zones,
            observed_at=now,
        )
        transitions = tuple(
            transition
            for transition in (
                self.reducer.reduce(signal_out) for signal_out in evaluate(rule_context)
            )
            if transition is not None
        )
        self.tracker.prune(now)
        return transitions

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

    조립기가 그 차량에 대한 update()를 멈추면 트래커는 스스로 이탈을 알 수 없다.
    prune()의 강제 종료가 없으면 사건이 영원히 EDGE_CONFIRMED로 남는다.
    """
    frames = Frames(stale=30.0)
    frames.run(PresenceSignal.PRESENT, 0)
    assert types(frames.run(PresenceSignal.PRESENT, 1)) == [IncidentTransitionType.OPEN]

    # 관측 없는 프레임이 이어진다. 유휴 한도를 넘기 전에는 사건을 닫지 않는다.
    assert frames.run(None, 20) == ()
    assert frames.states() == [IncidentState.EDGE_CONFIRMED]

    # 한도를 넘긴 prune()이 방문을 강제 종료하고, 그 다음 프레임 판정이 닫는다.
    assert frames.run(None, 40) == ()
    assert types(frames.run(None, 41)) == [IncidentTransitionType.RESOLVE]
    assert frames.states() == [IncidentState.RESOLVED]


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

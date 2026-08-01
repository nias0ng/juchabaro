"""불량 주차(bad_parking) 규칙 테스트 (T-12/463).

핵심 규약(데이터흐름.md §4, `parking_episode_tracker.py`의 상태별 신호 계약표,
463에서 MOVING 행 정정).
- STOP_PENDING은 matched=True, confirmable=False (후보) — bbox가 안정적이라
  재분류가 안전하다
- PARKED는 matched=True, confirmable=True (확정)
- MOVING/ENDED/에피소드 없음은 신호를 아예 안 낸다
  - ENDED는 `IncidentReducer.resolve_episode_scope()`가 규칙을 거치지 않고
    직접 처리한다(463, `resolve_scope`류의 446 교훈을 선제 적용)
  - MOVING은 bbox가 실제로 이동 중이라 재분류하면 에피소드가 끝나기도
    전에 원래 사건이 조기 해소될 위험이 있어, 조립자가 기존 사건을
    그대로 둔다(원래 계약표는 매칭을 계속 내라고 했으나 463에서 정정)
- AISLE 겹침이 최우선이고, 그다음 배정 상태(AMBIGUOUS→BAD_PARKING,
  UNASSIGNED→OUT_OF_ZONE, ASSIGNED→위반 아님)로 분류한다
- 세 rule_code(AISLE_BLOCK/BAD_PARKING/OUT_OF_ZONE)는 STOP_PENDING/PARKED에서
  매 프레임 전부 평가된다 — 선택되지 않은 코드는 matched=False로 나가
  이전에 열렸을 수 있는 다른 코드의 사건을 닫을 기회를 준다
"""

from datetime import datetime, timezone
from uuid import UUID

from src.parking.geometry import NormalizedPolygon
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.models import (
    AssignmentState,
    IncidentTransitionType,
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingState,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.rules.bad_parking import AISLE_BLOCK, BAD_PARKING, OUT_OF_ZONE, evaluate_open
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
)

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")
EPISODE = ParkingEpisodeId(UUID(int=1))
SQUARE = NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)))


def make_episode(state: ParkingState) -> ParkingEpisode:
    return ParkingEpisode(
        episode_id=EPISODE,
        physical_vehicle_id=CAR,
        parking_session_id=None,
        state=state,
        stationary_observed_seconds=600.0,
        last_signal=MotionSignal.STATIONARY,
        last_observed_at=T0,
        parked_at=T0,
    )


def make_assignment(state: AssignmentState, zone_id: int | None = None) -> ParkingAssignment:
    return ParkingAssignment(
        physical_vehicle_id=CAR,
        state=state,
        zone_id=None if zone_id is None else ZoneId(zone_id),
    )


def make_aisle_visit(zone_id: int = 9) -> ZoneVisit:
    return ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=zone_id)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(zone_id),
        state=ZoneVisitState.INSIDE,
        entered_candidate_at=T0,
        entered_at=T0,
    )


AISLE_ZONE = ParkingZone(zone_id=ZoneId(9), zone_number="A-01", zone_type=ZoneType.AISLE, polygon=SQUARE)


def make_context(
    *,
    episode: ParkingEpisode | None,
    assignment: ParkingAssignment | None = None,
    active_zone_visits: tuple[ZoneVisit, ...] = (),
    zones: list[ParkingZone] = (),
) -> RuleContext:
    snapshot = PhysicalVehicleSnapshot(
        physical_vehicle_id=CAR,
        track_segment_id=TrackSegmentId(1),
        bbox=BoundingBox(0.15, 0.15, 0.25, 0.25),
        confidence=0.9,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=T0,
        camera_id="cam-1",
        context=None,
    )
    return RuleContext(
        vehicle=snapshot,
        vehicle_context=None,
        active_zone_visits=active_zone_visits,
        parking_episode=episode,
        parking_assignment=assignment,
        zones=ZoneRegistry(list(zones)),
        observed_at=T0,
    )


def find(signals, rule_code):
    return next(s for s in signals if s.key.rule_code == rule_code)


def test_no_episode_produces_no_signals() -> None:
    """정지한 적 없는(계속 MOVING인) 차량은 평가 대상이 아니다."""
    assert evaluate_open(make_context(episode=None)) == ()


def test_ended_episode_produces_no_signals() -> None:
    """ENDED는 이 규칙을 거치지 않는다 — resolve_episode_scope의 몫이다."""
    context = make_context(episode=make_episode(ParkingState.ENDED))
    assert evaluate_open(context) == ()


def test_stop_pending_with_ambiguous_assignment_is_not_confirmable() -> None:
    context = make_context(
        episode=make_episode(ParkingState.STOP_PENDING),
        assignment=make_assignment(AssignmentState.AMBIGUOUS),
    )
    signal = find(evaluate_open(context), BAD_PARKING)
    assert signal.matched is True
    assert signal.confirmable is False


def test_parked_with_ambiguous_assignment_is_bad_parking() -> None:
    context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.AMBIGUOUS),
    )
    signals = evaluate_open(context)
    assert find(signals, BAD_PARKING).matched is True
    assert find(signals, BAD_PARKING).confirmable is True
    assert find(signals, OUT_OF_ZONE).matched is False
    assert find(signals, AISLE_BLOCK).matched is False


def test_moving_produces_no_signals() -> None:
    """MOVING은 규칙을 아예 거치지 않는다 — bbox가 이동 중이라 재분류하면
    에피소드가 끝나기도 전에 원래 사건이 조기 해소될 위험이 있다. 기존
    EDGE_CONFIRMED 사건은 조립자가 그대로 두고, 나중에 PARKED로 돌아오면
    재평가되거나 ENDED가 되면 resolve_episode_scope가 정리한다."""
    context = make_context(
        episode=make_episode(ParkingState.MOVING),
        assignment=make_assignment(AssignmentState.AMBIGUOUS),
    )
    assert evaluate_open(context) == ()


def test_parked_with_unassigned_is_out_of_zone() -> None:
    context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.UNASSIGNED),
    )
    signals = evaluate_open(context)
    assert find(signals, OUT_OF_ZONE).matched is True
    assert find(signals, BAD_PARKING).matched is False
    assert find(signals, AISLE_BLOCK).matched is False


def test_parked_with_assigned_produces_no_violation() -> None:
    """제대로 배정됐으면 세 코드 모두 matched=False다 — 이전에 열렸을 수
    있는 사건을 닫을 기회는 주되, 새로 여는 것은 없다."""
    context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.ASSIGNED, zone_id=1),
    )
    signals = evaluate_open(context)
    assert all(s.matched is False for s in signals)
    assert {s.key.rule_code for s in signals} == {BAD_PARKING, OUT_OF_ZONE, AISLE_BLOCK}


def test_aisle_overlap_takes_priority_over_ambiguous_assignment() -> None:
    """AISLE을 막고 있으면 배정 상태와 무관하게 AISLE_BLOCK이 우선한다."""
    context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.AMBIGUOUS),
        active_zone_visits=(make_aisle_visit(),),
        zones=[AISLE_ZONE],
    )
    signals = evaluate_open(context)
    assert find(signals, AISLE_BLOCK).matched is True
    assert find(signals, BAD_PARKING).matched is False
    assert find(signals, OUT_OF_ZONE).matched is False


def test_aisle_zone_visit_not_inside_does_not_trigger_aisle_block() -> None:
    """AISLE 구역을 지나가기만 했고(ENTERING/EXITING) 아직 INSIDE가 아니면
    통행 방해로 확정하지 않는다."""
    entering_visit = ZoneVisit(
        visit_id=ZoneVisitId(UUID(int=90)),
        physical_vehicle_id=CAR,
        zone_id=ZoneId(9),
        state=ZoneVisitState.ENTERING,
        entered_candidate_at=T0,
    )
    context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.ASSIGNED, zone_id=1),
        active_zone_visits=(entering_visit,),
        zones=[AISLE_ZONE],
    )
    signals = evaluate_open(context)
    assert find(signals, AISLE_BLOCK).matched is False


def test_missing_assignment_produces_no_violation() -> None:
    """parking_assignment가 아직 안 채워졌으면(배선 전, 방어적 상황) 위반을
    억지로 만들지 않는다."""
    context = make_context(episode=make_episode(ParkingState.PARKED), assignment=None)
    signals = evaluate_open(context)
    assert all(s.matched is False for s in signals)


def test_incident_key_is_scoped_by_episode_not_zone() -> None:
    """키가 parking_episode_id로 스코프되고 zone_id는 항상 None이다 — 어느
    구역이 겹쳤는지에 따라 키가 흔들리면 이후 matched=False가 다른 키로
    나가 원래 사건을 못 닫는다."""
    context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.AMBIGUOUS),
    )
    signal = find(evaluate_open(context), BAD_PARKING)
    assert signal.key.parking_episode_id == EPISODE
    assert signal.key.zone_id is None
    assert signal.key.zone_visit_id is None


def test_evidence_includes_parking_and_assignment_state() -> None:
    context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.UNASSIGNED),
    )
    evidence = find(evaluate_open(context), OUT_OF_ZONE).evidence
    assert evidence["parkingState"] == "PARKED"
    assert evidence["assignmentState"] == "UNASSIGNED"


def test_switching_classification_resolves_the_previous_code() -> None:
    """AI 리뷰 제안(MR !141): 분류가 AISLE_BLOCK에서 BAD_PARKING으로 바뀌면
    이전 코드는 실제로 RESOLVE되고 새 코드가 OPEN된다 — '선택 안 된 코드는
    matched=False로 나간다'는 설계가 IncidentReducer와 함께 실제로
    의도대로 동작하는지 확인한다(단일 evaluate_open() 호출 안에서의
    matched 값만 보는 것과는 다른 검증)."""
    reducer = InMemoryIncidentReducer()

    aisle_context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.ASSIGNED, zone_id=1),
        active_zone_visits=(make_aisle_visit(),),
        zones=[AISLE_ZONE],
    )
    first = [t for t in (reducer.reduce(s) for s in evaluate_open(aisle_context)) if t is not None]
    assert {t.incident.key.rule_code for t in first} == {AISLE_BLOCK}
    assert first[0].transition_type is IncidentTransitionType.OPEN

    # 다음 프레임: 더 이상 AISLE을 막고 있지 않고, 배정이 AMBIGUOUS로 바뀐다.
    ambiguous_context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.AMBIGUOUS),
    )
    second = [t for t in (reducer.reduce(s) for s in evaluate_open(ambiguous_context)) if t is not None]

    resolved = {t.incident.key.rule_code for t in second if t.transition_type is IncidentTransitionType.RESOLVE}
    opened = {t.incident.key.rule_code for t in second if t.transition_type is IncidentTransitionType.OPEN}
    assert resolved == {AISLE_BLOCK}
    assert opened == {BAD_PARKING}


def test_incident_stays_edge_confirmed_while_moving() -> None:
    """AI 리뷰 제안(MR !141): PARKED에서 확정된 사건은 MOVING 프레임을
    거쳐도 RESOLVE되지 않고 EDGE_CONFIRMED로 유지된다 — MOVING이 신호를
    아예 안 내는 설계가 실제로 조기 해소를 막는지 IncidentReducer와
    함께 확인한다."""
    reducer = InMemoryIncidentReducer()

    parked_context = make_context(
        episode=make_episode(ParkingState.PARKED),
        assignment=make_assignment(AssignmentState.AMBIGUOUS),
    )
    for signal in evaluate_open(parked_context):
        reducer.reduce(signal)
    assert {i.state.value for i in reducer.snapshot()} == {"EDGE_CONFIRMED"}

    moving_context = make_context(
        episode=make_episode(ParkingState.MOVING),
        assignment=make_assignment(AssignmentState.UNASSIGNED),  # 실제로 이동해 위치가 바뀌었다고 가정
    )
    transitions = [reducer.reduce(s) for s in evaluate_open(moving_context)]

    assert evaluate_open(moving_context) == ()  # MOVING은 애초에 신호를 안 낸다
    assert all(t is None for t in transitions)
    assert {i.state.value for i in reducer.snapshot()} == {"EDGE_CONFIRMED"}

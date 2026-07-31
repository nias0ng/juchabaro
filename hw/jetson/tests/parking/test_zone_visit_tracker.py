"""구역 방문 상태 머신 테스트. 카메라·모델 없이 도는 순수 상태 머신이다."""

from datetime import datetime, timedelta, timezone

import pytest

from src.parking.models import PresenceSignal, ZoneId, ZoneVisitState
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.tracking.models import PhysicalVehicleId

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")
OTHER_CAR = PhysicalVehicleId("pv-2")
ZONE = ZoneId(12)
OTHER_ZONE = ZoneId(13)


def make_tracker(
    entry: float = 3.0, exit_: float = 3.0, stale: float = 300.0
) -> InMemoryZoneVisitTracker:
    return InMemoryZoneVisitTracker(
        entry_confirm_seconds=entry,
        exit_confirm_seconds=exit_,
        stale_after_seconds=stale,
    )


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def feed(tracker, signal, seconds, *, vehicle=CAR, zone=ZONE):
    return tracker.update(
        physical_vehicle_id=vehicle, zone_id=zone, signal=signal, observed_at=at(seconds)
    )


def test_absent_from_outside_returns_none() -> None:
    tracker = make_tracker()
    assert feed(tracker, PresenceSignal.ABSENT, 0) is None


def test_first_present_enters_entering_state() -> None:
    tracker = make_tracker()
    visit = feed(tracker, PresenceSignal.PRESENT, 0)
    assert visit is not None
    assert visit.state is ZoneVisitState.ENTERING
    assert visit.entered_candidate_at == T0
    assert visit.entered_at is None


def test_present_for_confirm_seconds_becomes_inside() -> None:
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    assert feed(tracker, PresenceSignal.PRESENT, 2.9).state is ZoneVisitState.ENTERING
    visit = feed(tracker, PresenceSignal.PRESENT, 3.0)
    assert visit.state is ZoneVisitState.INSIDE


def test_entered_at_is_candidate_time_not_confirm_time() -> None:
    """점유 시간을 재는 기준이므로 실제 진입 시점으로 잡아야 한다.

    확인 시각으로 잡으면 EV 장기 점유가 확인시간만큼 짧게 측정된다.
    """
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    visit = feed(tracker, PresenceSignal.PRESENT, 3.0)
    assert visit.entered_at == T0


def test_absent_during_entering_discards_candidate() -> None:
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    assert feed(tracker, PresenceSignal.ABSENT, 1.0) is None
    # 다시 PRESENT면 후보 시각이 새로 잡힌다.
    visit = feed(tracker, PresenceSignal.PRESENT, 2.0)
    assert visit.entered_candidate_at == at(2.0)


def test_absent_during_inside_enters_exiting() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    visit = feed(tracker, PresenceSignal.ABSENT, 2.0)
    assert visit.state is ZoneVisitState.EXITING
    assert visit.exit_candidate_at == at(2.0)
    assert visit.exited_at is None


def test_present_during_exiting_returns_to_inside() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    visit = feed(tracker, PresenceSignal.PRESENT, 3.0)
    assert visit.state is ZoneVisitState.INSIDE
    assert visit.exit_candidate_at is None
    assert visit.entered_at == T0


def test_absent_for_exit_confirm_seconds_closes_visit() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    closed = feed(tracker, PresenceSignal.ABSENT, 5.0)
    assert closed.state is ZoneVisitState.OUTSIDE
    assert closed.exited_at == at(2.0)


def test_closed_visit_is_returned_exactly_once() -> None:
    """규칙이 RESOLVE를 만들려면 종료를 한 번은 봐야 하고, 두 번 보면 중복이 된다."""
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    assert feed(tracker, PresenceSignal.ABSENT, 5.0) is not None
    assert feed(tracker, PresenceSignal.ABSENT, 6.0) is None


def test_unknown_does_not_advance_entry_timer() -> None:
    """UNKNOWN 구간은 확인시간에 누적되지 않는다.

    벽시계 차이로 확인시간을 재면 이 테스트가 깨진다 — 카메라가 10초 먹통이었다는
    사실이 진입 확인을 앞당기면 안 된다.
    """
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    visit = feed(tracker, PresenceSignal.UNKNOWN, 10.0)
    assert visit.state is ZoneVisitState.ENTERING
    # 공백 뒤 첫 관측은 누적 사슬을 다시 시작하므로 간격 0을 기여한다.
    assert feed(tracker, PresenceSignal.PRESENT, 10.5).state is ZoneVisitState.ENTERING
    # 여기서부터 다시 3초를 관측해야 확인된다.
    assert feed(tracker, PresenceSignal.PRESENT, 13.5).state is ZoneVisitState.INSIDE


def test_unknown_preserves_already_accumulated_time() -> None:
    """공백이 기존 누적을 초기화하지도 않는다 — 계약은 '누적도 초기화도 안 함'이다."""
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 2.0)  # 누적 2.0
    feed(tracker, PresenceSignal.UNKNOWN, 50.0)  # 사슬만 끊김, 누적 2.0 보존
    # 간격 0 기여, 누적 2.0 — 아직 미확인이어야 한다. 벽시계로 재면 여기서
    # 이미 51초 경과로 확인돼버려 이 assert가 깨진다.
    assert feed(tracker, PresenceSignal.PRESENT, 51.0).state is ZoneVisitState.ENTERING
    assert feed(tracker, PresenceSignal.PRESENT, 52.0).state is ZoneVisitState.INSIDE  # 누적 3.0


def test_unknown_does_not_advance_exit_timer() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    feed(tracker, PresenceSignal.UNKNOWN, 20.0)
    assert feed(tracker, PresenceSignal.ABSENT, 20.5).state is ZoneVisitState.EXITING
    assert feed(tracker, PresenceSignal.ABSENT, 23.5).state is ZoneVisitState.OUTSIDE


def test_unknown_does_not_reset_inside_state() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    visit = feed(tracker, PresenceSignal.UNKNOWN, 100.0)
    assert visit.state is ZoneVisitState.INSIDE
    assert visit.entered_at == T0


def test_unknown_from_outside_returns_none() -> None:
    tracker = make_tracker()
    assert feed(tracker, PresenceSignal.UNKNOWN, 0) is None


def test_one_vehicle_can_visit_two_zones_at_once() -> None:
    tracker = make_tracker(entry=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0, zone=ZONE)
    feed(tracker, PresenceSignal.PRESENT, 0, zone=OTHER_ZONE)
    a = feed(tracker, PresenceSignal.PRESENT, 1.0, zone=ZONE)
    b = feed(tracker, PresenceSignal.PRESENT, 1.0, zone=OTHER_ZONE)
    assert a.state is ZoneVisitState.INSIDE
    assert b.state is ZoneVisitState.INSIDE
    assert a.visit_id != b.visit_id


def test_two_vehicles_in_same_zone_are_independent() -> None:
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0, vehicle=CAR)
    feed(tracker, PresenceSignal.PRESENT, 2.0, vehicle=OTHER_CAR)
    assert feed(tracker, PresenceSignal.PRESENT, 3.0, vehicle=CAR).state is ZoneVisitState.INSIDE
    assert feed(tracker, PresenceSignal.PRESENT, 3.0, vehicle=OTHER_CAR).state is ZoneVisitState.ENTERING


def test_revisit_after_close_gets_new_visit_id() -> None:
    tracker = make_tracker(entry=1.0, exit_=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    first = feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    feed(tracker, PresenceSignal.ABSENT, 4.0)
    feed(tracker, PresenceSignal.PRESENT, 10.0)
    second = feed(tracker, PresenceSignal.PRESENT, 11.0)
    assert second.visit_id != first.visit_id


def test_visit_id_is_deterministic() -> None:
    """같은 입력을 두 번 돌리면 같은 visit_id가 나와야 리플레이 검증이 가능하다."""
    ids = []
    for _ in range(2):
        tracker = make_tracker(entry=1.0)
        feed(tracker, PresenceSignal.PRESENT, 0)
        ids.append(feed(tracker, PresenceSignal.PRESENT, 1.0).visit_id)
    assert ids[0] == ids[1]


def test_active_visits_excludes_entering_visits() -> None:
    tracker = make_tracker(entry=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0, zone=ZONE)
    feed(tracker, PresenceSignal.PRESENT, 1.0, zone=ZONE)
    feed(tracker, PresenceSignal.PRESENT, 1.0, zone=OTHER_ZONE)  # ENTERING
    active = tracker.active_visits(CAR)
    assert [visit.zone_id for visit in active] == [ZONE]


def test_active_visits_excludes_exiting_visits() -> None:
    """이탈 확인 중에 사건을 닫으면 잠깐 가려진 차량이 위반을 지운다."""
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)  # EXITING
    assert tracker.active_visits(CAR) == ()


def test_active_visits_includes_the_visit_closed_this_frame() -> None:
    """규칙이 matched=False를 만들려면 닫힌 방문을 봐야 한다.

    이 방문이 빠지면 이미 열린 사건이 영원히 EDGE_CONFIRMED로 남는다.
    """
    tracker = make_tracker(entry=1.0, exit_=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    feed(tracker, PresenceSignal.ABSENT, 3.0)  # 종료
    active = tracker.active_visits(CAR)
    assert [visit.state for visit in active] == [ZoneVisitState.OUTSIDE]
    assert active[0].exited_at == at(2.0)


def test_active_visits_is_a_pure_read() -> None:
    """같은 프레임에서 몇 번을 불러도 답이 같아야 한다 — 소비하는 읽기가 아니다."""
    tracker = make_tracker(entry=1.0, exit_=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    feed(tracker, PresenceSignal.ABSENT, 3.0)
    assert tracker.active_visits(CAR) == tracker.active_visits(CAR)


def test_prune_removes_the_closed_visit_so_it_is_judged_once() -> None:
    """종료가 규칙에 정확히 한 번 보이게 만드는 장치가 prune()이다."""
    tracker = make_tracker(entry=1.0, exit_=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    feed(tracker, PresenceSignal.ABSENT, 3.0)
    assert len(tracker.active_visits(CAR)) == 1
    tracker.prune(at(3.0))
    assert tracker.active_visits(CAR) == ()


def test_absent_after_close_removes_the_slot_without_prune() -> None:
    """조립기가 prune()을 빠뜨려도 다음 ABSENT가 종료 슬롯을 지운다."""
    tracker = make_tracker(entry=1.0, exit_=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    feed(tracker, PresenceSignal.ABSENT, 3.0)
    assert feed(tracker, PresenceSignal.ABSENT, 4.0) is None
    assert tracker.active_visits(CAR) == ()


def test_prune_force_closes_a_visit_whose_updates_stopped() -> None:
    """추적이 끊겨 update()가 아예 끊긴 차량의 사건도 닫혀야 한다.

    트래커에는 프레임 경계가 없어 차량이 돌아오지 않는다는 사실을 스스로 알 수
    없다. 강제 종료하지 않으면 슬롯과 사건이 함께 영원히 남는다.
    """
    tracker = make_tracker(entry=1.0, exit_=1.0, stale=30.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    tracker.prune(at(20.0))
    assert [v.state for v in tracker.active_visits(CAR)] == [ZoneVisitState.INSIDE]

    tracker.prune(at(40.0))
    closed = tracker.active_visits(CAR)
    # 조용히 사라지지 않는다 — 판정이 RESOLVE를 만들 수 있도록 한 번 실려 나간다.
    assert [v.state for v in closed] == [ZoneVisitState.OUTSIDE]
    # 관측이 끊긴 시점까지만 점유로 인정한다.
    assert closed[0].exited_at == at(1.0)

    tracker.prune(at(41.0))
    assert tracker.active_visits(CAR) == ()


def test_prune_discards_a_stale_entering_candidate() -> None:
    """진입이 확정된 적 없는 후보는 방문이 성립하지 않았으므로 종료로 보고하지 않는다."""
    tracker = make_tracker(entry=3.0, exit_=1.0, stale=30.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    tracker.prune(at(40.0))
    assert tracker.active_visits(CAR) == ()
    # 슬롯이 남지 않았으므로 다시 들어오면 후보 시각이 새로 잡힌다.
    assert feed(tracker, PresenceSignal.PRESENT, 50.0).entered_candidate_at == at(50.0)


def test_prune_keeps_a_visit_that_is_still_being_observed() -> None:
    tracker = make_tracker(entry=1.0, exit_=1.0, stale=30.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    for second in range(2, 100):
        feed(tracker, PresenceSignal.PRESENT, float(second))
        tracker.prune(at(float(second)))
    assert [v.state for v in tracker.active_visits(CAR)] == [ZoneVisitState.INSIDE]


def test_unknown_keeps_a_slot_alive_against_pruning() -> None:
    """UNKNOWN은 '관측이 끊겼다'가 아니라 '이번 프레임엔 모르겠다'이다."""
    tracker = make_tracker(entry=1.0, exit_=1.0, stale=30.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    feed(tracker, PresenceSignal.UNKNOWN, 25.0)
    tracker.prune(at(40.0))
    assert [v.state for v in tracker.active_visits(CAR)] == [ZoneVisitState.INSIDE]


def test_prune_rejects_naive_datetime() -> None:
    tracker = make_tracker()
    with pytest.raises(ValueError, match="timezone"):
        tracker.prune(datetime(2026, 7, 31, 10, 0, 0))


def test_zero_stale_after_seconds_disables_force_close() -> None:
    """0은 '즉시 강제 종료'가 아니라 '안전망 끔'이다. 매 프레임 방문이 닫히면 안 된다."""
    tracker = make_tracker(entry=1.0, exit_=1.0, stale=0.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 1.0)
    tracker.prune(at(9999.0))
    assert [v.state for v in tracker.active_visits(CAR)] == [ZoneVisitState.INSIDE]


def test_negative_stale_after_seconds_is_rejected() -> None:
    with pytest.raises(ValueError, match="stale_after_seconds"):
        InMemoryZoneVisitTracker(
            entry_confirm_seconds=1.0, exit_confirm_seconds=1.0, stale_after_seconds=-1.0
        )


def test_naive_datetime_is_rejected() -> None:
    tracker = make_tracker()
    with pytest.raises(ValueError, match="timezone"):
        tracker.update(
            physical_vehicle_id=CAR,
            zone_id=ZONE,
            signal=PresenceSignal.PRESENT,
            observed_at=datetime(2026, 7, 31, 10, 0, 0),
        )


def test_backwards_observation_is_rejected() -> None:
    """뒤로 간 관측을 받아들이면 누적이 음수가 돼 진입 확정이 조용히 늦어진다."""
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 10.0)
    with pytest.raises(ValueError, match="과거"):
        feed(tracker, PresenceSignal.PRESENT, 5.0)


def test_backwards_observation_does_not_drive_accumulation_negative() -> None:
    """거부가 상태를 망가뜨리지 않는지까지 본다 — 이후 정상 관측은 그대로 동작한다."""
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 10.0)
    with pytest.raises(ValueError):
        feed(tracker, PresenceSignal.PRESENT, 5.0)
    # 5.0초를 되감았다면 누적이 -5.0이 돼 13.0에서 확정되지 못한다.
    assert feed(tracker, PresenceSignal.PRESENT, 13.0).state is ZoneVisitState.INSIDE


def test_same_timestamp_observation_is_allowed() -> None:
    """한 프레임 안의 관측은 같은 observed_at을 공유하므로 동일 시각은 정상이다."""
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 10.0)
    assert feed(tracker, PresenceSignal.PRESENT, 10.0).state is ZoneVisitState.ENTERING


def test_observation_order_is_checked_per_pair() -> None:
    """상태가 (차량, 구역)별로 독립이므로 순서 검사도 쌍별이다.

    전역으로 검사하면 한 프레임 안에서 쌍들을 갱신하는 순서가 판정을 바꾼다.
    """
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 10.0, zone=ZONE)
    assert feed(tracker, PresenceSignal.PRESENT, 5.0, zone=OTHER_ZONE) is not None

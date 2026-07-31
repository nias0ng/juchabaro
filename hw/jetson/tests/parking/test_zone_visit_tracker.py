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


def make_tracker(entry: float = 3.0, exit_: float = 3.0) -> InMemoryZoneVisitTracker:
    return InMemoryZoneVisitTracker(entry_confirm_seconds=entry, exit_confirm_seconds=exit_)


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


def test_active_visits_returns_only_inside_visits() -> None:
    tracker = make_tracker(entry=1.0)
    feed(tracker, PresenceSignal.PRESENT, 0, zone=ZONE)
    feed(tracker, PresenceSignal.PRESENT, 1.0, zone=ZONE)
    feed(tracker, PresenceSignal.PRESENT, 1.0, zone=OTHER_ZONE)  # ENTERING
    active = tracker.active_visits(CAR)
    assert [visit.zone_id for visit in active] == [ZONE]


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

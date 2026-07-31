"""주차 에피소드 상태 머신 테스트. 카메라·모델 없이 도는 순수 상태 머신이다."""

from datetime import datetime, timedelta, timezone

import pytest

from src.parking.models import ParkingState
from src.parking.parking_episode_tracker import InMemoryParkingEpisodeTracker
from src.tracking.models import MotionSignal, ParkingSessionId, PhysicalVehicleId

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId("pv-1")
OTHER_CAR = PhysicalVehicleId("pv-2")
SESSION = ParkingSessionId(77)


def make_tracker(parked: float = 600.0, move: float = 3.0) -> InMemoryParkingEpisodeTracker:
    return InMemoryParkingEpisodeTracker(
        parked_after_seconds=parked, move_confirm_seconds=move
    )


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def feed(tracker, signal, seconds, *, vehicle=CAR, session=SESSION):
    return tracker.update(
        physical_vehicle_id=vehicle,
        parking_session_id=session,
        signal=signal,
        observed_at=at(seconds),
    )


def test_moving_with_no_episode_returns_none() -> None:
    tracker = make_tracker()
    assert feed(tracker, MotionSignal.MOVING, 0) is None


def test_unknown_with_no_episode_returns_none() -> None:
    tracker = make_tracker()
    assert feed(tracker, MotionSignal.UNKNOWN, 0) is None


def test_first_stationary_opens_stop_pending() -> None:
    tracker = make_tracker()
    episode = feed(tracker, MotionSignal.STATIONARY, 0)
    assert episode is not None
    assert episode.state is ParkingState.STOP_PENDING
    assert episode.parked_at is None
    assert episode.stationary_observed_seconds == 0.0
    assert episode.parking_session_id == SESSION


def test_stationary_for_confirm_seconds_becomes_parked() -> None:
    tracker = make_tracker(parked=600.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    assert feed(tracker, MotionSignal.STATIONARY, 599.0).state is ParkingState.STOP_PENDING
    episode = feed(tracker, MotionSignal.STATIONARY, 600.0)
    assert episode.state is ParkingState.PARKED


def test_parked_at_is_the_confirming_observation() -> None:
    """"정지 시작 + 600초"가 아니라 실제로 관측된 확정 시점이다."""
    tracker = make_tracker(parked=600.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    episode = feed(tracker, MotionSignal.STATIONARY, 600.0)
    assert episode.parked_at == at(600.0)


def test_stationary_observed_seconds_is_reported() -> None:
    tracker = make_tracker(parked=600.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    episode = feed(tracker, MotionSignal.STATIONARY, 120.0)
    assert episode.stationary_observed_seconds == pytest.approx(120.0)


def test_moving_during_stop_pending_discards_the_candidate() -> None:
    tracker = make_tracker(parked=600.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    assert feed(tracker, MotionSignal.MOVING, 100.0) is None
    # 다시 정지하면 누적이 0에서 시작한다.
    episode = feed(tracker, MotionSignal.STATIONARY, 200.0)
    assert episode.state is ParkingState.STOP_PENDING
    assert episode.stationary_observed_seconds == 0.0


def test_unknown_does_not_advance_the_parking_timer() -> None:
    """관측 공백이 주차 확정을 앞당기면 안 된다.

    벽시계 차이로 확정 시간을 재면 이 테스트가 깨진다.
    """
    tracker = make_tracker(parked=600.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    episode = feed(tracker, MotionSignal.UNKNOWN, 1000.0)
    assert episode.state is ParkingState.STOP_PENDING
    # 공백 뒤 첫 관측은 사슬을 다시 시작하므로 간격 0을 기여한다.
    assert feed(tracker, MotionSignal.STATIONARY, 1001.0).state is ParkingState.STOP_PENDING
    # 여기서부터 다시 600초를 관측해야 확정된다.
    assert feed(tracker, MotionSignal.STATIONARY, 1601.0).state is ParkingState.PARKED


def test_unknown_preserves_already_accumulated_time() -> None:
    """공백은 누적을 늘리지도 초기화하지도 않는다."""
    tracker = make_tracker(parked=600.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 500.0)  # 누적 500
    feed(tracker, MotionSignal.UNKNOWN, 5000.0)    # 사슬만 끊김
    mid = feed(tracker, MotionSignal.STATIONARY, 5001.0)  # 간격 0 기여
    assert mid.state is ParkingState.STOP_PENDING
    assert mid.stationary_observed_seconds == pytest.approx(500.0)
    assert feed(tracker, MotionSignal.STATIONARY, 5101.0).state is ParkingState.PARKED


def test_two_vehicles_are_independent() -> None:
    tracker = make_tracker(parked=600.0)
    feed(tracker, MotionSignal.STATIONARY, 0, vehicle=CAR)
    feed(tracker, MotionSignal.STATIONARY, 300.0, vehicle=OTHER_CAR)
    assert feed(tracker, MotionSignal.STATIONARY, 600.0, vehicle=CAR).state is ParkingState.PARKED
    assert feed(tracker, MotionSignal.STATIONARY, 600.0, vehicle=OTHER_CAR).state is ParkingState.STOP_PENDING


def test_episode_id_is_deterministic() -> None:
    ids = []
    for _ in range(2):
        tracker = make_tracker(parked=1.0)
        feed(tracker, MotionSignal.STATIONARY, 0)
        ids.append(feed(tracker, MotionSignal.STATIONARY, 1.0).episode_id)
    assert ids[0] == ids[1]


def test_naive_datetime_is_rejected() -> None:
    tracker = make_tracker()
    with pytest.raises(ValueError, match="timezone"):
        tracker.update(
            physical_vehicle_id=CAR,
            parking_session_id=SESSION,
            signal=MotionSignal.STATIONARY,
            observed_at=datetime(2026, 7, 31, 10, 0, 0),
        )


def test_backwards_observation_is_rejected() -> None:
    tracker = make_tracker()
    feed(tracker, MotionSignal.STATIONARY, 100.0)
    with pytest.raises(ValueError, match="과거"):
        feed(tracker, MotionSignal.STATIONARY, 50.0)


def test_negative_thresholds_are_rejected() -> None:
    with pytest.raises(ValueError, match="음수"):
        InMemoryParkingEpisodeTracker(parked_after_seconds=-1.0, move_confirm_seconds=3.0)
    with pytest.raises(ValueError, match="음수"):
        InMemoryParkingEpisodeTracker(parked_after_seconds=600.0, move_confirm_seconds=-1.0)


def test_moving_after_parked_enters_departure_candidate() -> None:
    tracker = make_tracker(parked=1.0, move=3.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    episode = feed(tracker, MotionSignal.MOVING, 2.0)
    assert episode.state is ParkingState.MOVING
    assert episode.ended_at is None
    assert episode.parked_at == at(1.0)


def test_single_moving_frame_does_not_end_the_episode() -> None:
    """motion_estimator에 평활화가 없어 잡음 한 프레임이 MOVING을 낸다.

    즉시 종료하면 장기 주차가 잡음으로 끊기고 사건이 깜빡인다.
    """
    tracker = make_tracker(parked=1.0, move=3.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    episode = feed(tracker, MotionSignal.STATIONARY, 2.5)
    assert episode.state is ParkingState.PARKED
    assert episode.ended_at is None
    # 원래 확정 시각이 보존된다 — 새 에피소드가 아니다.
    assert episode.parked_at == at(1.0)


def test_moving_for_confirm_seconds_ends_the_episode() -> None:
    tracker = make_tracker(parked=1.0, move=3.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    episode = feed(tracker, MotionSignal.MOVING, 5.0)
    assert episode.state is ParkingState.ENDED


def test_ended_at_is_when_movement_started() -> None:
    """확인시간은 판정 지연이지 주차의 일부가 아니다."""
    tracker = make_tracker(parked=1.0, move=3.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    episode = feed(tracker, MotionSignal.MOVING, 5.0)
    assert episode.ended_at == at(2.0)


def test_unknown_during_departure_does_not_advance_the_move_timer() -> None:
    tracker = make_tracker(parked=1.0, move=3.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    feed(tracker, MotionSignal.UNKNOWN, 100.0)
    assert feed(tracker, MotionSignal.MOVING, 100.5).state is ParkingState.MOVING
    assert feed(tracker, MotionSignal.MOVING, 103.5).state is ParkingState.ENDED


def test_unknown_while_parked_does_not_end_the_episode() -> None:
    tracker = make_tracker(parked=1.0, move=3.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    episode = feed(tracker, MotionSignal.UNKNOWN, 10000.0)
    assert episode.state is ParkingState.PARKED
    assert episode.parked_at == at(1.0)


def test_restop_after_end_creates_a_new_episode() -> None:
    tracker = make_tracker(parked=1.0, move=1.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    first = feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    feed(tracker, MotionSignal.MOVING, 3.0)  # ENDED
    feed(tracker, MotionSignal.STATIONARY, 10.0)
    second = feed(tracker, MotionSignal.STATIONARY, 11.0)
    assert second.episode_id != first.episode_id
    assert second.state is ParkingState.PARKED
    assert second.parked_at == at(11.0)


def test_departure_timer_restarts_after_returning_to_parked() -> None:
    """되돌아왔다가 다시 움직이면 이동 확인이 처음부터 다시 쌓인다."""
    tracker = make_tracker(parked=1.0, move=3.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    feed(tracker, MotionSignal.MOVING, 4.0)   # 누적 2.0, 아직 미달
    feed(tracker, MotionSignal.STATIONARY, 5.0)  # PARKED 복귀
    feed(tracker, MotionSignal.MOVING, 6.0)   # 새 후보
    assert feed(tracker, MotionSignal.MOVING, 8.0).state is ParkingState.MOVING
    assert feed(tracker, MotionSignal.MOVING, 9.0).state is ParkingState.ENDED


def test_active_episode_returns_none_when_no_episode() -> None:
    tracker = make_tracker()
    assert tracker.active_episode(CAR) is None


def test_active_episode_returns_the_current_episode() -> None:
    tracker = make_tracker(parked=1.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    episode = tracker.active_episode(CAR)
    assert episode is not None
    assert episode.state is ParkingState.PARKED


def test_active_episode_is_a_pure_read() -> None:
    tracker = make_tracker(parked=1.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    assert tracker.active_episode(CAR) == tracker.active_episode(CAR)


def test_ended_episode_is_visible_until_pruned() -> None:
    """규칙이 matched=False를 내려면 ENDED를 봐야 한다."""
    tracker = make_tracker(parked=1.0, move=1.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    feed(tracker, MotionSignal.MOVING, 3.0)
    assert tracker.active_episode(CAR).state is ParkingState.ENDED
    tracker.prune(at(4.0))
    assert tracker.active_episode(CAR) is None


def test_prune_deletes_ended_slots() -> None:
    tracker = make_tracker(parked=1.0, move=1.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    feed(tracker, MotionSignal.MOVING, 3.0)
    assert tracker.prune(at(4.0)) == ()
    assert tracker.active_episode(CAR) is None


def test_prune_force_ends_a_lost_track_and_returns_it() -> None:
    """추적이 끊긴 차량의 사건이 영원히 열린 채 남으면 안 된다.

    조립자는 이번 프레임에 관측된 차량만 순회하므로, 사라진 차량의 종료는
    prune()의 반환값으로만 판정에 도달할 수 있다.
    """
    tracker = InMemoryParkingEpisodeTracker(
        parked_after_seconds=1.0, move_confirm_seconds=1.0, stale_after_seconds=30.0
    )
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    assert tracker.prune(at(20.0)) == ()          # 아직 방치 아님
    forced = tracker.prune(at(40.0))
    assert len(forced) == 1
    assert forced[0].state is ParkingState.ENDED
    assert forced[0].ended_at == at(1.0)          # 마지막으로 관측된 시각
    assert tracker.active_episode(CAR) is None    # 같은 호출에서 슬롯도 지운다


def test_prune_returns_nothing_when_stale_after_is_zero() -> None:
    tracker = InMemoryParkingEpisodeTracker(
        parked_after_seconds=1.0, move_confirm_seconds=1.0, stale_after_seconds=0.0
    )
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    assert tracker.prune(at(9999.0)) == ()


def test_prune_does_not_touch_a_recently_observed_vehicle() -> None:
    tracker = InMemoryParkingEpisodeTracker(
        parked_after_seconds=1.0, move_confirm_seconds=1.0, stale_after_seconds=30.0
    )
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.STATIONARY, 35.0)
    assert tracker.prune(at(40.0)) == ()
    assert tracker.active_episode(CAR).state is ParkingState.PARKED


def test_closed_slot_self_cleans_on_next_update_without_prune() -> None:
    """prune()을 빠뜨려도 다음 관측이 스스로 슬롯을 정리한다(백스톱).

    ZoneVisitTracker의 동일한 백스톱과 대칭이다 — 놓친 prune() 호출의
    파급 범위가 두 트래커에서 같아야 한다.
    """
    tracker = make_tracker(parked=1.0, move=1.0)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 1.0)
    feed(tracker, MotionSignal.MOVING, 2.0)
    feed(tracker, MotionSignal.MOVING, 3.0)  # ENDED
    assert tracker.active_episode(CAR).state is ParkingState.ENDED
    feed(tracker, MotionSignal.MOVING, 4.0)  # prune() 없이 한 번 더 관측
    assert tracker.active_episode(CAR) is None

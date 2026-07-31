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

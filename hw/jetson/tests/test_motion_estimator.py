"""MotionEstimator의 차량별 3-sample rolling-window 계약."""

from src.tracking.models import BoundingBox, MotionSignal
from src.tracking.motion_estimator import MotionEstimator


def test_first_observation_returns_moving_and_starts_history():
    """새로 나타난 차량은 비교할 관측이 없어 MOVING을 반환한다."""
    estimator = MotionEstimator(movement_epsilon=0.01)

    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.1, 0.1, 0.2, 0.2))

    assert signal == MotionSignal.MOVING


def test_staying_within_epsilon_returns_stationary():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    # 중심이 0.001만큼만 미세하게 흔들림 — epsilon(0.01) 이내.
    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.101, 0.10, 0.201, 0.20))

    assert signal == MotionSignal.STATIONARY


def test_moving_beyond_epsilon_returns_moving():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.50, 0.50, 0.60, 0.60))

    assert signal == MotionSignal.MOVING


def test_micro_drift_outside_recent_window_does_not_accumulate_into_moving():
    """첫 위치가 아닌 최근 3개 관측만 비교한다."""
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    signals = []
    for i in range(1, 9):
        bbox = BoundingBox(0.10 + 0.003 * i, 0.10, 0.20 + 0.003 * i, 0.20)
        signals.append(estimator.update(physical_vehicle_id="veh-1", bbox=bbox))

    assert signals == [MotionSignal.STATIONARY] * 8


def test_continuous_slow_motion_does_not_alternate_after_crossing_window_epsilon():
    """단일 앵커 갱신 방식의 MOVING/STATIONARY 교대 회귀를 막는다."""

    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    signals = [
        estimator.update(
            physical_vehicle_id="veh-1",
            bbox=BoundingBox(0.10 + 0.006 * i, 0.10, 0.20 + 0.006 * i, 0.20),
        )
        for i in range(1, 6)
    ]

    assert signals == [
        MotionSignal.STATIONARY,
        MotionSignal.MOVING,
        MotionSignal.MOVING,
        MotionSignal.MOVING,
        MotionSignal.MOVING,
    ]


def test_different_vehicles_have_independent_histories():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))
    estimator.update(physical_vehicle_id="veh-2", bbox=BoundingBox(0.50, 0.50, 0.60, 0.60))

    # veh-1은 그대로, veh-2만 이동.
    signal_1 = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))
    signal_2 = estimator.update(physical_vehicle_id="veh-2", bbox=BoundingBox(0.90, 0.90, 0.99, 0.99))

    assert signal_1 == MotionSignal.STATIONARY
    assert signal_2 == MotionSignal.MOVING


def test_forget_removes_history_so_next_observation_is_treated_as_new():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    estimator.forget("veh-1")

    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))
    assert signal == MotionSignal.MOVING

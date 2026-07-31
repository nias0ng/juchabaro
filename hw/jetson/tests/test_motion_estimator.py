"""MotionEstimator 회귀 테스트 (436).

핵심 검증: 앵커는 movement_epsilon을 실제로 넘겼을 때만 갱신된다 — 매
프레임 갱신하면 미세한 흔들림이 누적돼도 계속 STATIONARY로 남는다.
"""

from src.tracking.models import BoundingBox, MotionSignal
from src.tracking.motion_estimator import MotionEstimator


def test_first_observation_returns_moving_and_establishes_anchor():
    """새로 나타난 차량은 비교할 앵커가 없어 MOVING을 반환한다."""
    estimator = MotionEstimator(movement_epsilon=0.01)

    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.1, 0.1, 0.2, 0.2))

    assert signal == MotionSignal.MOVING


def test_staying_within_epsilon_returns_stationary():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    # 중심이 0.001만큼만 미세하게 흔들림 — epsilon(0.01) 이내.
    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.101, 0.10, 0.201, 0.20))

    assert signal == MotionSignal.STATIONARY


def test_moving_beyond_epsilon_returns_moving_and_updates_anchor():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.50, 0.50, 0.60, 0.60))

    assert signal == MotionSignal.MOVING


def test_repeated_micro_jitter_does_not_accumulate_into_moving():
    """리뷰 반영과 동일한 이유 — 앵커를 매 프레임 갱신하면 흔들림이 누적돼
    실제로는 안 움직였는데도 언젠가 epsilon을 넘기게 된다. 앵커가 '정차
    시작 위치'로 고정돼야 이 누적이 없다.

    매 프레임 0.003씩 같은 방향으로 흔들리는 것을 3번 반복한다 — 누적
    이동량(0.009)은 epsilon(0.01)에 가깝지만, 앵커가 첫 위치로 고정돼
    있으면 매 프레임 최초 앵커 대비 거리로만 판정하므로 도중에 MOVING이
    섞이면 안 된다(누적이 아니라 절대 위치 비교라는 계약을 고정한다).
    """
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    signals = []
    for i in range(1, 4):
        bbox = BoundingBox(0.10 + 0.003 * i, 0.10, 0.20 + 0.003 * i, 0.20)
        signals.append(estimator.update(physical_vehicle_id="veh-1", bbox=bbox))

    # i=1,2,3의 최초 앵커 대비 이동량은 각각 0.003/0.006/0.009로 전부 epsilon(0.01) 미만.
    assert signals == [MotionSignal.STATIONARY, MotionSignal.STATIONARY, MotionSignal.STATIONARY]


def test_different_vehicles_have_independent_anchors():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))
    estimator.update(physical_vehicle_id="veh-2", bbox=BoundingBox(0.50, 0.50, 0.60, 0.60))

    # veh-1은 그대로, veh-2만 이동.
    signal_1 = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))
    signal_2 = estimator.update(physical_vehicle_id="veh-2", bbox=BoundingBox(0.90, 0.90, 0.99, 0.99))

    assert signal_1 == MotionSignal.STATIONARY
    assert signal_2 == MotionSignal.MOVING


def test_forget_removes_anchor_so_next_observation_is_treated_as_new():
    estimator = MotionEstimator(movement_epsilon=0.01)
    estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))

    estimator.forget("veh-1")

    signal = estimator.update(physical_vehicle_id="veh-1", bbox=BoundingBox(0.10, 0.10, 0.20, 0.20))
    assert signal == MotionSignal.MOVING

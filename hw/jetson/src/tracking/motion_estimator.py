"""차량 관측으로부터 MOVING/STATIONARY 신호를 계산한다.

600초 주차 확정과 이동 확정 시간은 parking 계층의 책임이다.
여기서는 최근 세 관측의 중심 이동만 삼상태 신호로 정규화한다.

UNKNOWN은 TrackingBatch의 관측 축으로 전달하며 이 객체의 관측 이력을
지우지 않는다. TrackSegment 종료 또한 PhysicalVehicle 종료가 아니므로
이력 정리는 상위 owner가 물리 차량 종료를 commit한 뒤에만 호출한다.
"""

from __future__ import annotations

from collections import deque

from src.domain.models import require_positive
from src.tracking.geometry import centroid_distance
from src.tracking.models import BoundingBox, MotionSignal, PhysicalVehicleId


_MOTION_HISTORY_SIZE = 3


class MotionEstimator:
    """물리 차량별 짧은 관측 창의 처음·끝 위치로 이동을 판정한다.

    세 sample 창은 미세 흔들림은 누적하지 않으면서,
    느린 연속 이동이 앵커 갱신 때문에 MOVING/STATIONARY로
    교대하는 것을 막는 최소 hysteresis다.
    """

    def __init__(self, *, movement_epsilon: float = 0.01) -> None:
        require_positive(movement_epsilon, "movement_epsilon")
        self._movement_epsilon = movement_epsilon
        self._history: dict[PhysicalVehicleId, deque[BoundingBox]] = {}

    def update(self, *, physical_vehicle_id: PhysicalVehicleId, bbox: BoundingBox) -> MotionSignal:
        """이번 관측을 rolling window에 추가하고 이동 여부를 판정한다."""

        history = self._history.get(physical_vehicle_id)
        if history is None:
            history = deque(maxlen=_MOTION_HISTORY_SIZE)
            self._history[physical_vehicle_id] = history
            history.append(bbox)
            # 새로 나타난 차량은 비교할 관측이 없다.
            # MOVING을 반환해, parking 계층의 정차 판정이 이번 프레임부터
            # 시작하게 한다([*] --> MOVING 초기 상태와 일치).
            return MotionSignal.MOVING

        history.append(bbox)
        return (
            MotionSignal.MOVING
            if centroid_distance(history[0], history[-1])
            > self._movement_epsilon
            else MotionSignal.STATIONARY
        )

    def forget(self, physical_vehicle_id: PhysicalVehicleId) -> None:
        """PhysicalVehicle 종료가 commit된 뒤 관측 이력을 정리한다."""

        self._history.pop(physical_vehicle_id, None)

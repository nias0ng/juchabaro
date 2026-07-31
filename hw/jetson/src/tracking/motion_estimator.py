"""차량 관측으로부터 MOVING/STATIONARY 신호를 계산하는 모듈(436).

600초 주차 확정은 이 모듈의 책임이 아니다(parking 계층의
ParkingEpisodeTracker, T-09) — 여기서는 프레임 간 이동 여부만 판정한다.
ai/tracking/jetson_vehicle_tracking_baseline.py의 movement_epsilon 앵커
비교 로직(ViolationMonitor.update 안의 moved 판정)에서 이관.

UNKNOWN(관측 공백)은 이번 티켓에서 다루지 않는다 — 지금의 통과 구현
EntityResolver는 grace period 없이 이번 프레임에 없는 트랙을 곧바로
ended로 처리하므로(entity_resolver.py), "관측은 공백이지만 트랙은 아직
살아있다"는 상태 자체가 없다. 그 구분이 필요한 시점(T-13, 실제
EntityResolver)에 여기 UNKNOWN 반환 메서드를 함께 추가한다.
"""

from __future__ import annotations

from src.tracking.geometry import centroid_distance
from src.tracking.models import BoundingBox, MotionSignal, PhysicalVehicleId


class MotionEstimator:
    """물리 차량별 '정차 시작 위치(앵커)' 대비 이동 여부를 판정한다.

    앵커는 실제로 movement_epsilon을 넘겨 이동했을 때만 갱신한다 — 매 프레임
    갱신하면 미세한 흔들림이 누적돼도 계속 STATIONARY로 남는 문제가 생긴다
    (baseline 리뷰 반영과 동일한 이유).
    """

    def __init__(self, *, movement_epsilon: float = 0.01) -> None:
        self._movement_epsilon = movement_epsilon
        self._anchors: dict[PhysicalVehicleId, BoundingBox] = {}

    def update(self, *, physical_vehicle_id: PhysicalVehicleId, bbox: BoundingBox) -> MotionSignal:
        """이번 프레임에 관측된 차량의 이동 여부를 판정하고 앵커를 갱신한다."""

        anchor = self._anchors.get(physical_vehicle_id)
        if anchor is None:
            # 새로 나타난 차량은 비교할 앵커가 없다 — 이번 위치를 앵커로 확정하고
            # MOVING을 반환해, parking 계층의 정차 판정이 이번 프레임부터
            # 시작하게 한다([*] --> MOVING 초기 상태와 일치).
            self._anchors[physical_vehicle_id] = bbox
            return MotionSignal.MOVING

        if centroid_distance(anchor, bbox) > self._movement_epsilon:
            self._anchors[physical_vehicle_id] = bbox
            return MotionSignal.MOVING

        return MotionSignal.STATIONARY

    def forget(self, physical_vehicle_id: PhysicalVehicleId) -> None:
        """차량이 완전히 종료됐을 때(ended_vehicle_ids) 앵커를 정리한다."""

        self._anchors.pop(physical_vehicle_id, None)

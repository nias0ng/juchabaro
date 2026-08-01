"""확정된 주차 에피소드의 대표 주차면 또는 모호성을 결정하는 모듈.

상태를 보관하지 않는 순수 함수다(다른 규칙 평가기와 같은 성격). 한 차량이
여러 스팟형 구역(`SPOT_ZONE_TYPES`)에 동시에 겹칠 때, 겹침 비율이 가장 높은
구역 하나를 대표 주차면으로 정한다. 1등과 2등의 차이가 마진 이내면 억지로
하나를 고르지 않고 `AMBIGUOUS`로 둔다 — 이 결과는 `bad_parking`(T-12) 규칙이
입력으로 쓴다.

`ambiguous_margin`에 기본값을 두지 않는다. 이 개념은 옛 baseline에 아예
없던 것이라 참고할 실측값이 없다 — 호출부(`config`, 실제 배선 담당인
T-12)가 값을 정하고 넘겨야 한다.

AISLE/ENTRY_EXIT처럼 스팟이 아닌 구역은 겹침 비율이 아무리 높아도 후보에서
제외한다 — 통행로에 서 있다고 그 통행로를 "배정"받는 것은 의미가 없다.
"""

from __future__ import annotations

from src.parking.geometry import overlap_ratio
from src.parking.models import AssignmentState, ParkingAssignment
from src.parking.zone_registry import SPOT_ZONE_TYPES, ZoneRegistry
from src.tracking.models import PhysicalVehicleSnapshot


def resolve(
    vehicle: PhysicalVehicleSnapshot,
    zones: ZoneRegistry,
    *,
    min_overlap_ratio: float,
    ambiguous_margin: float,
) -> ParkingAssignment:
    """차량 하나의 현재 위치로 대표 주차면을 정한다.

    `min_overlap_ratio` 미만으로 겹치는 구역은 후보에서 제외한다 — 살짝
    스친 것과 실제로 걸쳐 있는 것을 구분하기 위해서다(`ZoneVisitTracker`의
    존재 판정과 같은 기준을 쓰되, 값은 호출부가 독립적으로 정한다).
    """

    candidates = sorted(
        (
            (zone.zone_id, overlap_ratio(zone.polygon, vehicle.bbox))
            for zone in zones.all()
            if zone.zone_type in SPOT_ZONE_TYPES
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )
    candidates = [pair for pair in candidates if pair[1] >= min_overlap_ratio]

    if not candidates:
        return ParkingAssignment(
            physical_vehicle_id=vehicle.physical_vehicle_id, state=AssignmentState.UNASSIGNED
        )

    top_zone_id, top_ratio = candidates[0]
    if len(candidates) >= 2:
        _, second_ratio = candidates[1]
        if top_ratio - second_ratio <= ambiguous_margin:
            return ParkingAssignment(
                physical_vehicle_id=vehicle.physical_vehicle_id, state=AssignmentState.AMBIGUOUS
            )

    return ParkingAssignment(
        physical_vehicle_id=vehicle.physical_vehicle_id,
        state=AssignmentState.ASSIGNED,
        zone_id=top_zone_id,
    )

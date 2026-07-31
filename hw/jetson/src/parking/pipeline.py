"""차량 스냅샷을 구역 방문·주차 에피소드·사건 전이로 변환하는 파이프라인.

관통 1단계(440)만 다룬다 — `restricted_zone` 규칙 하나, `ZoneVisit` 상태축
하나만으로 프레임이 사건까지 도달하는 경로다. `ParkingEpisode`(600초 확정,
T-09), `ev_overstay`/`bad_parking` 규칙, `assignment_resolver`(T-10)는
범위 밖이다.

프레임 호출 순서는 `zone_visit_tracker.py`가 명시한 조립기 계약을 그대로
따른다:

1. 이번 프레임에 관측된 (차량, 구역) 쌍마다 `update()` (한 쌍에 한 번만)
2. 이번 프레임에 관측된 차량마다 `active_visits()` → 규칙 평가 → `reduce()`
3. 프레임 끝에 `prune()` 한 번. 반환된 강제 종료 방문도 규칙 평가 → `reduce()`

이 순서를 어기면(특히 3번을 빠뜨리거나 2번보다 먼저 부르면) 사건이 영원히
닫히지 않는다 — `test_zone_visit_incident_flow.py`가 그 결함을 고정해 뒀다.
"""

from __future__ import annotations

from src.parking.geometry import overlap_ratio
from src.parking.incident_reducer import IncidentReducer
from src.parking.models import (
    IncidentTransition,
    ParkingPipelineResult,
    PresenceSignal,
    ZoneVisit,
)
from src.parking.rules import restricted_zone
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ParkingZone, ZoneRegistry
from src.parking.zone_visit_tracker import ZoneVisitTracker
from src.tracking.models import MotionSignal, PhysicalVehicleId, PhysicalVehicleSnapshot, TrackingBatch


class ParkingPipeline:
    """`ZoneVisitTracker` + `restricted_zone` 규칙 + `IncidentReducer`를 조립한다."""

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        zone_visit_tracker: ZoneVisitTracker,
        incident_reducer: IncidentReducer,
        min_overlap_ratio: float,
    ) -> None:
        self._zones = zones
        self._zone_visit_tracker = zone_visit_tracker
        self._incident_reducer = incident_reducer
        self._min_overlap_ratio = min_overlap_ratio
        # 추적이 끊긴 차량은 prune()이 반환하는 방문에만 등장하고 그 프레임의
        # TrackingBatch.vehicles에는 없다 — 규칙 평가에 필요한 RuleContext.vehicle을
        # 채우려면 그 차량을 마지막으로 본 스냅샷을 들고 있어야 한다
        # (test_zone_visit_incident_flow.py가 실제 조립기의 요구사항으로 명시).
        self._last_snapshot: dict[PhysicalVehicleId, PhysicalVehicleSnapshot] = {}

    def process(self, batch: TrackingBatch) -> ParkingPipelineResult:
        """한 프레임의 `TrackingBatch`를 처리해 방문 갱신과 사건 전이를 반환한다."""

        for vehicle in batch.vehicles:
            self._last_snapshot[vehicle.physical_vehicle_id] = vehicle

        zone_visit_updates: list[ZoneVisit] = []
        for vehicle in batch.vehicles:
            for zone in self._zones.all():
                visit = self._zone_visit_tracker.update(
                    physical_vehicle_id=vehicle.physical_vehicle_id,
                    zone_id=zone.zone_id,
                    signal=self._presence_signal(vehicle, zone),
                    observed_at=vehicle.observed_at,
                )
                if visit is not None:
                    zone_visit_updates.append(visit)

        incident_transitions: list[IncidentTransition] = []
        for vehicle in batch.vehicles:
            visits = self._zone_visit_tracker.active_visits(vehicle.physical_vehicle_id)
            incident_transitions += self._judge(vehicle, visits)

        for visit in self._zone_visit_tracker.prune(batch.observed_at):
            zone_visit_updates.append(visit)
            snapshot = self._last_snapshot.pop(visit.physical_vehicle_id, None)
            if snapshot is not None:
                incident_transitions += self._judge(snapshot, (visit,))

        for ended_id in batch.ended_vehicle_ids:
            # 구역을 한 번도 밟지 않은 채 사라진 차량은 prune()이 절대 돌려주지
            # 않는다(방문 자체가 없었으므로) — 그대로 두면 이 캐시가 차량이
            # 지나갈 때마다 무한히 커진다. tracking 계층이 이미 "끝났다"고
            # 확정한 신호이므로 여기서 직접 정리한다.
            self._last_snapshot.pop(ended_id, None)

        return ParkingPipelineResult(
            zone_visit_updates=tuple(zone_visit_updates),
            parking_episode_updates=(),
            incident_transitions=tuple(incident_transitions),
        )

    def _presence_signal(self, vehicle: PhysicalVehicleSnapshot, zone: ParkingZone) -> PresenceSignal:
        if vehicle.motion_signal is MotionSignal.UNKNOWN:
            # tracking 계층의 관측 공백을 그대로 구역 방문의 관측 공백으로 전달한다.
            return PresenceSignal.UNKNOWN
        ratio = overlap_ratio(zone.polygon, vehicle.bbox)
        return PresenceSignal.PRESENT if ratio >= self._min_overlap_ratio else PresenceSignal.ABSENT

    def _judge(
        self, vehicle: PhysicalVehicleSnapshot, visits: tuple[ZoneVisit, ...]
    ) -> list[IncidentTransition]:
        if not visits:
            return []
        context = RuleContext(
            vehicle=vehicle,
            vehicle_context=vehicle.context,
            active_zone_visits=visits,
            parking_episode=None,
            parking_assignment=None,
            zones=self._zones,
            observed_at=vehicle.observed_at,
        )
        transitions: list[IncidentTransition] = []
        for signal in restricted_zone.evaluate(context):
            transition = self._incident_reducer.reduce(signal)
            if transition is not None:
                transitions.append(transition)
        return transitions

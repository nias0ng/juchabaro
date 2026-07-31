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

**해소는 규칙을 거치지 않고 `zone_visit_id`로 직접 처리한다(446 후속
리뷰).** 예전엔 두 가지 문제가 있었다. (1) `prune()`이 반환한 강제 종료
방문을 판정하려고 "마지막으로 본 스냅샷" 캐시(`_last_snapshot`)를 들고
있었는데, 추적이 끊긴 차량은 같은 프레임의 `ended_vehicle_ids`가 캐시를
즉시 비워버려서 몇 분 뒤 `prune()`이 그 방문을 반환할 때는 이미 캐시가
비어 판정이 생략됐다. (2) 방문이 닫힐 때도 `restricted_zone` 규칙을 거쳐
`rule_code`를 재계산해야 `IncidentKey`를 만들 수 있었는데, 그 구역이 이미
삭제돼 있으면(서버 구역 동기화 등) 재계산이 안 돼 해소가 조용히 생략됐다.
두 문제 다 "방문이 닫혔다"는 사실 자체가 해소 사유일 뿐 규칙 재판정과는
무관하다는 게 핵심이라, 이제 `IncidentReducer.resolve_scope(zone_visit_id)`가
스냅샷도 구역 조회도 없이 직접 해소한다(`parking/incident_reducer.py` 참고).
"""

from __future__ import annotations

from datetime import datetime

from src.parking.geometry import overlap_ratio
from src.parking.incident_reducer import IncidentReducer
from src.parking.models import (
    IncidentTransition,
    ParkingPipelineResult,
    PresenceSignal,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.rules import restricted_zone
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ParkingZone, ZoneRegistry
from src.parking.zone_visit_tracker import ZoneVisitTracker
from src.tracking.models import MotionSignal, PhysicalVehicleSnapshot, TrackingBatch


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

    def process(self, batch: TrackingBatch) -> ParkingPipelineResult:
        """한 프레임의 `TrackingBatch`를 처리해 방문 갱신과 사건 전이를 반환한다."""

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
            incident_transitions += self._judge_open(vehicle, visits)
            incident_transitions += self._resolve_closed_visits(visits, observed_at=vehicle.observed_at)

        pruned = self._zone_visit_tracker.prune(batch.observed_at)
        zone_visit_updates.extend(pruned)
        incident_transitions += self._resolve_closed_visits(pruned, observed_at=batch.observed_at)

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

    def _judge_open(
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
        for signal in restricted_zone.evaluate_open(context):
            transition = self._incident_reducer.reduce(signal)
            if transition is not None:
                transitions.append(transition)
        return transitions

    def _resolve_closed_visits(
        self, visits: tuple[ZoneVisit, ...], *, observed_at: datetime
    ) -> list[IncidentTransition]:
        """방금 닫힌 방문마다 그 zone_visit_id로 열린 사건을 전부 해소한다.

        규칙을 거치지 않는다 — `restricted_zone`을 다시 부르지 않으므로
        구역 정의가 이미 삭제돼 있어도 해소된다.
        """

        transitions: list[IncidentTransition] = []
        for visit in visits:
            if visit.state is not ZoneVisitState.OUTSIDE:
                continue
            transitions.extend(
                self._incident_reducer.resolve_scope(zone_visit_id=visit.visit_id, observed_at=observed_at)
            )
        return transitions

"""차량 스냅샷을 구역 방문·주차 에피소드·사건 전이로 변환하는 파이프라인.

관통 1단계(440)에서 `restricted_zone` 규칙과 `ZoneVisit` 상태축 하나만으로
시작했고, `ev_overstay`(450)를 병렬로 붙였다. 이 둘은 `ZoneVisit`만 입력으로
받는다. `bad_parking`(463)은 `ParkingEpisode`(600초 확정, T-09)와
`ParkingAssignment`(대표 주차면, T-10)를 함께 입력으로 받는 첫 규칙이라,
이 티켓에서 두 컴포넌트를 처음 배선한다 — 둘 다 이전 티켓에서 이미
구현·검증됐지만 파이프라인에 붙어 있지 않았다.

프레임 호출 순서는 `zone_visit_tracker.py`/`parking_episode_tracker.py`가
명시한 조립기 계약을 그대로 따른다. 두 트래커는 같은 모양의 계약이다:

1. 이번 프레임에 관측된 (차량, 구역) 쌍마다 `zone_visit_tracker.update()`
   (한 쌍에 한 번만), 차량마다 `parking_episode_tracker.update()` (한
   차량에 한 번만)
2. 이번 프레임에 관측된 차량마다 `active_visits()`/`active_episode()` →
   규칙 평가 → `reduce()`
3. 프레임 끝에 두 트래커의 `prune()`을 각각 한 번씩. 반환된 강제 종료
   방문·에피소드도 규칙 평가 없이 직접 해소로 넘긴다

이 순서를 어기면(특히 3번을 빠뜨리거나 2번보다 먼저 부르면) 사건이 영원히
닫히지 않는다 — `test_zone_visit_incident_flow.py`가 그 결함을 고정해 뒀다.

**해소는 규칙을 거치지 않고 스코프 ID로 직접 처리한다(446 후속 리뷰,
463에서 parking_episode_id로 일반화).** 예전엔 두 가지 문제가 있었다.
(1) `prune()`이 반환한 강제 종료 방문·에피소드를 판정하려고 "마지막으로
본 스냅샷" 캐시를 들고 있었는데, 추적이 끊긴 차량은 캐시가 비어 판정이
생략됐다. (2) 방문이 닫힐 때도 규칙을 거쳐 `rule_code`를 재계산해야
`IncidentKey`를 만들 수 있었는데, 그 시점엔 재계산에 필요한 정보(구역
정의, 또는 `bad_parking`의 경우 차량의 원래 위치)가 이미 사라져 있을 수
있었다. 두 문제 다 "방문/에피소드가 끝났다"는 사실 자체가 해소 사유일 뿐
규칙 재판정과는 무관하다는 게 핵심이라, `IncidentReducer.resolve_scope`/
`resolve_episode_scope`가 스냅샷도 재판정도 없이 직접 해소한다
(`parking/incident_reducer.py` 참고).
"""

from __future__ import annotations

from datetime import datetime

from src.parking.assignment_resolver import resolve as resolve_assignment
from src.parking.geometry import overlap_ratio
from src.parking.incident_reducer import IncidentReducer
from src.parking.models import (
    IncidentTransition,
    ParkingEpisode,
    ParkingPipelineResult,
    ParkingState,
    PresenceSignal,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.parking_episode_tracker import ParkingEpisodeTracker
from src.parking.rules import bad_parking, ev_overstay, restricted_zone
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ParkingZone, ZoneRegistry
from src.parking.zone_visit_tracker import ZoneVisitTracker
from src.tracking.models import MotionSignal, PhysicalVehicleSnapshot, TrackingBatch


class ParkingPipeline:
    """`ZoneVisitTracker`/`ParkingEpisodeTracker` + 규칙들 + `IncidentReducer`를 조립한다."""

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        zone_visit_tracker: ZoneVisitTracker,
        parking_episode_tracker: ParkingEpisodeTracker,
        incident_reducer: IncidentReducer,
        min_overlap_ratio: float,
        ambiguous_margin: float,
    ) -> None:
        self._zones = zones
        self._zone_visit_tracker = zone_visit_tracker
        self._parking_episode_tracker = parking_episode_tracker
        self._incident_reducer = incident_reducer
        self._min_overlap_ratio = min_overlap_ratio
        self._ambiguous_margin = ambiguous_margin

    def process(self, batch: TrackingBatch) -> ParkingPipelineResult:
        """한 프레임의 `TrackingBatch`를 처리해 방문·에피소드 갱신과 사건 전이를 반환한다."""

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

        parking_episode_updates: list[ParkingEpisode] = []
        for vehicle in batch.vehicles:
            episode = self._parking_episode_tracker.update(
                physical_vehicle_id=vehicle.physical_vehicle_id,
                parking_session_id=None if vehicle.context is None else vehicle.context.parking_session_id,
                signal=vehicle.motion_signal,
                observed_at=vehicle.observed_at,
            )
            if episode is not None:
                parking_episode_updates.append(episode)

        incident_transitions: list[IncidentTransition] = []
        for vehicle in batch.vehicles:
            visits = self._zone_visit_tracker.active_visits(vehicle.physical_vehicle_id)
            episode = self._parking_episode_tracker.active_episode(vehicle.physical_vehicle_id)
            incident_transitions += self._judge_open(vehicle, visits, episode)
            incident_transitions += self._resolve_closed_visits(visits, observed_at=vehicle.observed_at)
            incident_transitions += self._resolve_ended_episode(episode, observed_at=vehicle.observed_at)

        pruned_visits = self._zone_visit_tracker.prune(batch.observed_at)
        zone_visit_updates.extend(pruned_visits)
        incident_transitions += self._resolve_closed_visits(pruned_visits, observed_at=batch.observed_at)

        pruned_episodes = self._parking_episode_tracker.prune(batch.observed_at)
        parking_episode_updates.extend(pruned_episodes)
        for ended in pruned_episodes:
            incident_transitions += self._resolve_ended_episode(ended, observed_at=batch.observed_at)

        return ParkingPipelineResult(
            zone_visit_updates=tuple(zone_visit_updates),
            parking_episode_updates=tuple(parking_episode_updates),
            incident_transitions=tuple(incident_transitions),
        )

    def _presence_signal(self, vehicle: PhysicalVehicleSnapshot, zone: ParkingZone) -> PresenceSignal:
        if vehicle.motion_signal is MotionSignal.UNKNOWN:
            # tracking 계층의 관측 공백을 그대로 구역 방문의 관측 공백으로 전달한다.
            return PresenceSignal.UNKNOWN
        ratio = overlap_ratio(zone.polygon, vehicle.bbox)
        return PresenceSignal.PRESENT if ratio >= self._min_overlap_ratio else PresenceSignal.ABSENT

    def _judge_open(
        self,
        vehicle: PhysicalVehicleSnapshot,
        visits: tuple[ZoneVisit, ...],
        episode: ParkingEpisode | None,
    ) -> list[IncidentTransition]:
        assignment = resolve_assignment(
            vehicle,
            self._zones,
            min_overlap_ratio=self._min_overlap_ratio,
            ambiguous_margin=self._ambiguous_margin,
        )
        context = RuleContext(
            vehicle=vehicle,
            vehicle_context=vehicle.context,
            active_zone_visits=visits,
            parking_episode=episode,
            parking_assignment=assignment,
            zones=self._zones,
            observed_at=vehicle.observed_at,
        )
        transitions: list[IncidentTransition] = []
        for evaluate in (restricted_zone.evaluate_open, ev_overstay.evaluate_open, bad_parking.evaluate_open):
            for signal in evaluate(context):
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

    def _resolve_ended_episode(
        self, episode: ParkingEpisode | None, *, observed_at: datetime
    ) -> list[IncidentTransition]:
        """방금 끝난 에피소드가 있으면 그 parking_episode_id로 열린 사건을 전부 해소한다.

        `bad_parking`을 다시 부르지 않는다 — 그 시점엔 차량이 이미 이동
        중이거나 추적이 끊겨 현재 위치로 rule_code를 재구성할 수 없다(463).
        """

        if episode is None or episode.state is not ParkingState.ENDED:
            return []
        return list(
            self._incident_reducer.resolve_episode_scope(
                parking_episode_id=episode.episode_id, observed_at=observed_at
            )
        )

"""Tracking 관측을 주차 scope와 Incident 변경 계획으로 조립한다.

이 모듈은 카메라 bbox를 영속 상태에 직접 저장하지 않는다. 한 frame의 정상
관측으로 ZoneVisit과 ParkingEpisode를 갱신하고, 상태 없는 규칙의 삼상태
신호를 IncidentReducer에 전달한다. authoritative SessionContext는 tracking
snapshot이 아니라 호출자가 제공한 mapping에서만 조회한다.

TrackSegment 종료와 PhysicalVehicle 종료는 서로 다른 사실이다.
``ended_track_segment_ids``와 일시 미관측은 어떤 child scope도 끝내지 않으며,
확정된 실제 출차는 상위 ``PhysicalPresenceWorkflow``가 ``physical_exit()``으로
별도 전달해야 한다. 공개 전이는 aggregate와 같은 transaction에서 즉시
기록하고, 공개 전이가 없는 timer snapshot은 04 계약의 dirty checkpoint로
합쳐 기록한다.

현재 ``InMemory*`` owner들은 reference implementation이라 호출 중 상태를
변경한다. application UnitOfWork는 호출 전 checkpoint를 보존하고
commit 실패 시 DB rollback과 함께 runtime owner도 복구해야 한다.

이미 terminal이 된 local-only episode의 늦은 binding은 이 active pipeline이
메모리에 보존하지 않는다. 04 계약의 pending handoff workflow가 durable terminal
snapshot을 조회해 PARKED·UNPARKED를 materialize해야 한다.

BlockingRelation tracker는 아직 이 조립기 범위가 아니다. 따라서 현재
RuleContext와 결과의 relation tuple은 명시적으로 비어 있다.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from datetime import datetime
import math

from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking import assignment_resolver
from src.parking.geometry import overlap_ratio
from src.parking.incident_reducer import IncidentReducer
from src.parking.models import (
    Incident,
    IncidentKeyScope,
    IncidentReduction,
    IncidentTransition,
    ParkingEpisode,
    ParkingPipelineResult,
    ParkingState,
    ParkingTransition,
    ParkingTransitionType,
    PresenceSignal,
    ZoneDefinition,
    ZoneId,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.parking_episode_tracker import MOVEMENT_CONFIRMED, ParkingEpisodeTracker
from src.parking.rules import (
    bad_parking,
    double_parking,
    ev_overstay,
    restricted_zone,
)
from src.parking.rules.models import RuleContext
from src.parking.zone_registry import ZoneRegistry
from src.parking.zone_visit_tracker import ZoneVisitTracker
from src.session.models import EntryAttemptId, SessionContext
from src.tracking.models import (
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackingBatch,
)


_RULE_EVALUATORS = (
    restricted_zone.evaluate,
    ev_overstay.evaluate,
    bad_parking.evaluate,
    double_parking.evaluate,
)


class ParkingPipeline:
    """한 frame 안의 geometry, scope, rule, reducer 호출 순서를 소유한다."""

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        zone_visit_tracker: ZoneVisitTracker,
        parking_episode_tracker: ParkingEpisodeTracker,
        incident_reducer: IncidentReducer,
        min_overlap_ratio: float,
        assignment_min_overlap_ratio: float,
        assignment_ambiguous_margin: float,
    ) -> None:
        _validate_ratio(min_overlap_ratio, "min_overlap_ratio")
        _validate_ratio(
            assignment_min_overlap_ratio,
            "assignment_min_overlap_ratio",
        )
        _validate_ratio(
            assignment_ambiguous_margin,
            "assignment_ambiguous_margin",
        )
        self._zones = zones
        self._zone_visit_tracker = zone_visit_tracker
        self._parking_episode_tracker = parking_episode_tracker
        self._incident_reducer = incident_reducer
        self._min_overlap_ratio = min_overlap_ratio
        self._assignment_min_overlap_ratio = assignment_min_overlap_ratio
        self._assignment_ambiguous_margin = assignment_ambiguous_margin

    def checkpoint_state(self) -> tuple[object, object, object]:
        """frame UnitOfWork 실패 시 복구할 runtime owner state를 반환한다."""

        return (
            self._zone_visit_tracker.checkpoint_state(),
            self._parking_episode_tracker.checkpoint_state(),
            self._incident_reducer.checkpoint_state(),
        )

    def restore_state(
        self,
        checkpoint: tuple[object, object, object],
    ) -> None:
        """DB rollback과 함께 세 owner를 같은 frame 전 시점으로 되돌린다."""

        if len(checkpoint) != 3:
            raise ValueError("invalid ParkingPipeline checkpoint")
        visit_state, episode_state, incident_state = checkpoint
        self._zone_visit_tracker.restore_state(visit_state)
        self._parking_episode_tracker.restore_state(episode_state)
        self._incident_reducer.restore_state(incident_state)

    def restore_active(
        self,
        *,
        zone_visits: tuple[ZoneVisit, ...],
        parking_episodes: tuple[ParkingEpisode, ...],
        incidents: tuple[Incident, ...],
    ) -> None:
        """durable active aggregate를 끊은 timer chain으로 기동 복원한다."""

        self._zone_visit_tracker.restore_active(zone_visits)
        self._parking_episode_tracker.restore_active(parking_episodes)
        self._incident_reducer.restore_active(incidents)

    def process(
        self,
        batch: TrackingBatch,
        *,
        session_contexts: Mapping[PhysicalVehicleId, SessionContext] | None = None,
        entry_attempt_ids: Mapping[PhysicalVehicleId, EntryAttemptId] | None = None,
        skip_unobserved_vehicle_ids: Collection[PhysicalVehicleId] = (),
    ) -> ParkingPipelineResult:
        """한 TrackingBatch를 nonterminal 주차 상태 변경 계획으로 변환한다.

        ``session_contexts``는 active ContextBinding에서 조회한 authoritative
        projection이어야 한다. ``entry_attempt_ids``는 session이 없는 REVIEW/DENY
        차량도 local Incident를 공개할 수 있게 하는 authoritative correlation이다.
        ``not_present_confirmed_vehicle_ids``가 포함돼도
        이 메서드는 scope를 끝내지 않는다. 실제 출차 transaction을 소유한
        상위 workflow가 commit 계획을 만들 때 ``physical_exit()``을 호출한다.
        """

        contexts = {} if session_contexts is None else session_contexts
        attempts = {} if entry_attempt_ids is None else entry_attempt_ids
        zone_visit_updates: list[ZoneVisit] = []
        parking_episode_updates: list[ParkingEpisode] = []
        parking_transitions: list[ParkingTransition] = []
        incident_updates: list[Incident] = []
        incident_transitions: list[IncidentTransition] = []

        for vehicle in batch.vehicles:
            context = contexts.get(vehicle.physical_vehicle_id)
            entry_attempt_id = attempts.get(vehicle.physical_vehicle_id)
            observation = _effective_observation(batch, vehicle)
            assignment = assignment_resolver.resolve(
                vehicle,
                self._zones,
                min_overlap_ratio=self._assignment_min_overlap_ratio,
                ambiguous_margin=self._assignment_ambiguous_margin,
            )

            terminal_visits: list[ZoneVisit] = []
            for zone in self._zones.all():
                visit = self._zone_visit_tracker.update(
                    physical_vehicle_id=vehicle.physical_vehicle_id,
                    zone_id=zone.zone_id,
                    signal=self._presence_signal(vehicle, zone, observation),
                    observation=observation,
                    observed_at=vehicle.observed_at,
                )
                if visit is None:
                    continue
                zone_visit_updates.append(visit)
                if visit.state in {ZoneVisitState.ENDED, ZoneVisitState.CANCELED}:
                    terminal_visits.append(visit)

            previous_episode = self._parking_episode_tracker.active_episode(
                vehicle.physical_vehicle_id
            )
            episode = self._parking_episode_tracker.update(
                physical_vehicle_id=vehicle.physical_vehicle_id,
                parking_session_id=(
                    None if context is None else context.parking_session_id
                ),
                signal=(
                    vehicle.motion_signal
                    if observation.state is ObservationState.OBSERVED
                    else MotionSignal.UNKNOWN
                ),
                observation=observation,
                observed_at=vehicle.observed_at,
                assignment=assignment,
            )
            if episode is not None:
                parking_episode_updates.append(episode)
                parking_transitions.extend(
                    _parking_transitions(previous_episode, episode)
                )

            for visit in terminal_visits:
                self._collect_reductions(
                    self._incident_reducer.terminate_zone_visit(
                        visit.visit_id,
                        observation=visit.observation,
                        observed_at=vehicle.observed_at,
                        reason=visit.termination_reason or "ZONE_VISIT_ENDED",
                    ),
                    incident_updates,
                    incident_transitions,
                )

            active_visits = self._zone_visit_tracker.active_visits(
                vehicle.physical_vehicle_id
            )
            current_episode = (
                episode
                if episode is not None
                else self._parking_episode_tracker.active_episode(
                    vehicle.physical_vehicle_id
                )
            )
            rule_context = RuleContext(
                vehicle=vehicle,
                observation=batch.observation,
                session_context=context,
                active_zone_visits=active_visits,
                parking_episode=current_episode,
                parking_assignment=assignment,
                # BlockingRelation tracker는 후속 범위다.
                blocking_relations=(),
                zones=self._zones,
                observed_at=vehicle.observed_at,
            )
            self._evaluate_rules(
                rule_context,
                observation=observation,
                entry_attempt_id=entry_attempt_id,
                incident_updates=incident_updates,
                incident_transitions=incident_transitions,
            )

        # TrackSegment 종료는 의도적으로 사용하지 않는다. PhysicalVehicle의
        # 일시 미관측만 각 aggregate의 trusted sample chain을 끊는다.
        skipped_unobserved_ids = set(skip_unobserved_vehicle_ids)
        for physical_vehicle_id in batch.unobserved_physical_vehicle_ids:
            if physical_vehicle_id in skipped_unobserved_ids:
                # confirmed departure retry의 immutable occurredAt보다 느린
                # frame 시각으로 child를 먼저 pause하지 않는다.
                continue
            observation = _unobserved_observation(batch.observation)
            zone_visit_updates.extend(
                self._zone_visit_tracker.pause_physical_vehicle(
                    physical_vehicle_id,
                    observation,
                    batch.observed_at,
                )
            )
            parking_episode_updates.extend(
                self._parking_episode_tracker.pause_physical_vehicle(
                    physical_vehicle_id,
                    observation,
                    batch.observed_at,
                )
            )
            self._collect_reductions(
                self._incident_reducer.pause_physical_vehicle(
                    physical_vehicle_id,
                    observation=observation,
                    observed_at=batch.observed_at,
                ),
                incident_updates,
                incident_transitions,
            )

        return ParkingPipelineResult(
            zone_visit_updates=tuple(zone_visit_updates),
            parking_episode_updates=tuple(parking_episode_updates),
            parking_transitions=tuple(parking_transitions),
            incident_updates=tuple(incident_updates),
            incident_transitions=tuple(incident_transitions),
            blocking_relation_updates=(),
        )

    def physical_exit(
        self,
        *,
        physical_vehicle_id: PhysicalVehicleId,
        observed_at: datetime,
        incident_termination_reason: str = "PHYSICAL_VEHICLE_LEFT",
    ) -> ParkingPipelineResult:
        """확정된 실제 출차를 child scope 종료 계획으로 변환한다.

        이 메서드는 ``process()``에서 자동 호출되지 않는다. 상위
        ``PhysicalPresenceWorkflow``가 이 결과를 다른 session·presence 변경과
        함께 commit해야 하며, commit 성공 뒤에만 tracking owner에 forget ACK를
        보내야 한다.
        """

        observation = ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=observed_at,
        )
        visits = self._zone_visit_tracker.physical_exit(
            physical_vehicle_id=physical_vehicle_id,
            observed_at=observed_at,
        )
        episode = self._parking_episode_tracker.physical_exit(
            physical_vehicle_id=physical_vehicle_id,
            observed_at=observed_at,
        )
        incident_updates: list[Incident] = []
        incident_transitions: list[IncidentTransition] = []

        # visit-scope를 먼저 PHYSICAL_EXIT로 닫으면 session correlation이
        # 있는 Incident의 종료 사유를 SESSION_EXITED로 보존할 수 없다.
        # subject/victim 차량 기준으로 한 번만 종료해 상위 owner가
        # 고정한 correlation 사유를 모든 관련 Incident에 적용한다.
        self._collect_reductions(
            self._incident_reducer.terminate_physical_vehicle(
                physical_vehicle_id,
                observation=observation,
                observed_at=observed_at,
                reason=incident_termination_reason,
            ),
            incident_updates,
            incident_transitions,
        )

        return ParkingPipelineResult(
            zone_visit_updates=visits,
            parking_episode_updates=() if episode is None else (episode,),
            incident_updates=tuple(incident_updates),
            incident_transitions=tuple(incident_transitions),
            blocking_relation_updates=(),
        )

    def _presence_signal(
        self,
        vehicle: PhysicalVehicleSnapshot,
        zone: ZoneDefinition,
        observation: ObservationStatus,
    ) -> PresenceSignal:
        if observation.state is not ObservationState.OBSERVED:
            return PresenceSignal.UNKNOWN
        ratio = overlap_ratio(zone.polygon, vehicle.bbox)
        return (
            PresenceSignal.PRESENT
            if ratio >= self._min_overlap_ratio
            else PresenceSignal.ABSENT
        )

    def _evaluate_rules(
        self,
        context: RuleContext,
        *,
        observation: ObservationStatus,
        entry_attempt_id: EntryAttemptId | None,
        incident_updates: list[Incident],
        incident_transitions: list[IncidentTransition],
    ) -> None:
        zone_id_by_visit_id = {
            visit.visit_id: visit.zone_id for visit in context.active_zone_visits
        }
        parking_session_id = (
            None
            if context.session_context is None
            else context.session_context.parking_session_id
        )
        for evaluate in _RULE_EVALUATORS:
            for signal in evaluate(context):
                zone_id: ZoneId | None = None
                if signal.key.scope_type is IncidentKeyScope.ZONE_VISIT:
                    zone_id = zone_id_by_visit_id.get(signal.key.scope_id)
                reduction = self._incident_reducer.reduce(
                    signal,
                    physical_vehicle_id=context.vehicle.physical_vehicle_id,
                    observation=observation,
                    entry_attempt_id=entry_attempt_id,
                    parking_session_id=parking_session_id,
                    zone_id=zone_id,
                )
                if reduction is not None:
                    self._collect_reductions(
                        (reduction,),
                        incident_updates,
                        incident_transitions,
                    )

    @staticmethod
    def _collect_reductions(
        reductions: tuple[IncidentReduction, ...],
        incident_updates: list[Incident],
        incident_transitions: list[IncidentTransition],
    ) -> None:
        for reduction in reductions:
            incident_updates.append(reduction.incident)
            incident_transitions.extend(reduction.transitions)


def _effective_observation(
    batch: TrackingBatch,
    vehicle: PhysicalVehicleSnapshot,
) -> ObservationStatus:
    """batch와 vehicle 중 하나라도 불신이면 trusted timer 입력을 막는다."""

    if batch.observation.state is not ObservationState.OBSERVED:
        return batch.observation
    return vehicle.observation


def _unobserved_observation(
    batch_observation: ObservationStatus,
) -> ObservationStatus:
    """정상 batch의 개별 차량 미관측만 TRACK_LOST로 해석한다."""

    if batch_observation.state is ObservationState.OBSERVED:
        return ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.TRACK_LOST,
        )
    return batch_observation


def _parking_transitions(
    previous: ParkingEpisode | None,
    current: ParkingEpisode,
) -> tuple[ParkingTransition, ...]:
    """Materialize every newly eligible parking publication in revision order."""

    previous_revision = 0 if previous is None else previous.publication_revision
    if current.publication_revision <= previous_revision:
        return ()
    if (
        current.parking_session_id is None
        or current.assignment is None
        or current.parked_at is None
    ):
        raise RuntimeError("publishable ParkingEpisode requires session and assignment")

    transitions: list[ParkingTransition] = []
    if previous_revision < 1 <= current.publication_revision:
        transitions.append(
            ParkingTransition(
                transition_type=ParkingTransitionType.PARKED,
                parking_episode_id=current.episode_id,
                physical_vehicle_id=current.physical_vehicle_id,
                parking_session_id=current.parking_session_id,
                publication_revision=1,
                occurred_at=current.parked_at,
                assignment=current.assignment,
            )
        )

    if previous_revision < 2 <= current.publication_revision:
        if (
            current.state is not ParkingState.ENDED
            or current.termination_reason != MOVEMENT_CONFIRMED
            or current.ended_at is None
        ):
            raise RuntimeError("UNPARKED revision requires MOVEMENT_CONFIRMED ending")
        transitions.append(
            ParkingTransition(
                transition_type=ParkingTransitionType.UNPARKED,
                parking_episode_id=current.episode_id,
                physical_vehicle_id=current.physical_vehicle_id,
                parking_session_id=current.parking_session_id,
                publication_revision=2,
                occurred_at=current.ended_at,
                assignment=current.assignment,
            )
        )
    return tuple(transitions)


def _validate_ratio(value: float, name: str) -> None:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between 0 and 1")

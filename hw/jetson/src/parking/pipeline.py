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

BlockingRelation 후보는 PARKED 차량의 assignment에 연결된 별도
EgressAisleRegistry와 다른 차량 footprint의 overlap으로 계산한다(§11).
이미 non-terminal인
관계는 새 후보 계산과 무관하게 매 frame 계속 재평가해 이동만으로 조용히
멈추지 않게 한다. durable BlockingRelation은 다른 active scope와 같이
trusted timer chain을 끊은 상태로 복원한다.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import datetime
import math

from src.diagnostics import (
    DiagnosticEvent,
    DiagnosticEventType,
    DiagnosticSeverity,
    DiagnosticsSink,
    NullDiagnosticsSink,
    emit_best_effort,
)
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking import assignment_resolver
from src.parking.blocking_relation_tracker import BlockingRelationTracker
from src.parking import egress_blocking_resolver
from src.parking.egress_aisle_registry import EgressAisleRegistry
from src.parking.geometry import bbox_center, overlap_ratio
from src.parking.incident_reducer import IncidentReducer
from src.parking.models import (
    BlockingRelation,
    BlockingRelationId,
    BlockingRelationState,
    EgressAisleId,
    EgressBlockingEvidence,
    ExitTraversalObservation,
    ExitTraversalSide,
    Incident,
    IncidentKeyScope,
    IncidentReduction,
    IncidentSignalDiagnostic,
    IncidentSignal,
    IncidentTransition,
    ParkingAssignment,
    ParkingEpisode,
    ParkingPipelineResult,
    ParkingState,
    ParkingTransition,
    ParkingTransitionType,
    PlacementDiagnostic,
    PlacementEvidence,
    PlacementEvidenceSource,
    PresenceSignal,
    ZoneDefinition,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.parking_eligibility import (
    ParkingEligibilityDecision,
    ParkingEligibilityValue,
    evaluate_parking_eligibility,
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


_BlockingCandidateKey = tuple[PhysicalVehicleId, PhysicalVehicleId, EgressAisleId]


@dataclass
class _VehicleFrame:
    """pass 1이 모은, pass 3의 규칙 평가에 필요한 차량별 중간 결과."""

    vehicle: PhysicalVehicleSnapshot
    context: SessionContext | None
    entry_attempt_id: EntryAttemptId | None
    entry_time: datetime | None
    observation: ObservationStatus
    parking_motion_observation: ObservationStatus
    parking_eligibility: ParkingEligibilityDecision
    assignment: ParkingAssignment
    placement_evidence: PlacementEvidence
    placement_evidence_source: PlacementEvidenceSource
    active_visits: tuple[ZoneVisit, ...]
    episode: ParkingEpisode | None


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
        egress_aisles: EgressAisleRegistry,
        zone_visit_tracker: ZoneVisitTracker,
        parking_episode_tracker: ParkingEpisodeTracker,
        incident_reducer: IncidentReducer,
        blocking_relation_tracker: BlockingRelationTracker,
        min_overlap_ratio: float,
        assignment_min_overlap_ratio: float,
        assignment_ambiguous_margin: float,
        bad_parking_min_primary_overlap_ratio: float,
        bad_parking_min_secondary_overlap_ratio: float,
        out_of_zone_min_spot_overlap_ratio: float,
        blocking_min_subject_overlap_ratio: float,
        blocking_min_egress_coverage_ratio: float,
        diagnostics_sink: DiagnosticsSink | None = None,
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
        _validate_ratio(
            bad_parking_min_primary_overlap_ratio,
            "bad_parking_min_primary_overlap_ratio",
        )
        _validate_ratio(
            bad_parking_min_secondary_overlap_ratio,
            "bad_parking_min_secondary_overlap_ratio",
        )
        _validate_ratio(
            out_of_zone_min_spot_overlap_ratio,
            "out_of_zone_min_spot_overlap_ratio",
        )
        _validate_positive_ratio(
            blocking_min_subject_overlap_ratio,
            "blocking_min_subject_overlap_ratio",
        )
        _validate_positive_ratio(
            blocking_min_egress_coverage_ratio,
            "blocking_min_egress_coverage_ratio",
        )
        self._zones = zones
        self._egress_aisles = egress_aisles
        self._zone_visit_tracker = zone_visit_tracker
        self._parking_episode_tracker = parking_episode_tracker
        self._incident_reducer = incident_reducer
        self._blocking_relation_tracker = blocking_relation_tracker
        self._min_overlap_ratio = min_overlap_ratio
        self._assignment_min_overlap_ratio = assignment_min_overlap_ratio
        self._assignment_ambiguous_margin = assignment_ambiguous_margin
        self._bad_parking_min_primary_overlap_ratio = (
            bad_parking_min_primary_overlap_ratio
        )
        self._bad_parking_min_secondary_overlap_ratio = (
            bad_parking_min_secondary_overlap_ratio
        )
        self._out_of_zone_min_spot_overlap_ratio = (
            out_of_zone_min_spot_overlap_ratio
        )
        self._blocking_min_subject_overlap_ratio = (
            blocking_min_subject_overlap_ratio
        )
        self._blocking_min_egress_coverage_ratio = (
            blocking_min_egress_coverage_ratio
        )
        self._diagnostics_sink = (
            diagnostics_sink
            if diagnostics_sink is not None
            else NullDiagnosticsSink()
        )
        # 구역 asset이 명시한 기준선만 사용한다. 통과 latch의 소유자는 이
        # in-memory pipeline이 아니라 application의 durable checkpoint다.
        self._exit_traversals = zones.exit_traversals()

    def checkpoint_state(self) -> tuple[object, object, object, object]:
        """frame UnitOfWork 실패 시 복구할 runtime owner state를 반환한다."""

        return (
            self._zone_visit_tracker.checkpoint_state(),
            self._parking_episode_tracker.checkpoint_state(),
            self._incident_reducer.checkpoint_state(),
            self._blocking_relation_tracker.checkpoint_state(),
        )

    def restore_state(
        self,
        checkpoint: tuple[object, object, object, object],
    ) -> None:
        """DB rollback과 함께 runtime owner를 같은 frame 전 시점으로 되돌린다."""

        if len(checkpoint) != 4:
            raise ValueError("invalid ParkingPipeline checkpoint")
        (
            visit_state,
            episode_state,
            incident_state,
            relation_state,
        ) = checkpoint
        self._zone_visit_tracker.restore_state(visit_state)
        self._parking_episode_tracker.restore_state(episode_state)
        self._incident_reducer.restore_state(incident_state)
        self._blocking_relation_tracker.restore_state(relation_state)

    def restore_active(
        self,
        *,
        zone_visits: tuple[ZoneVisit, ...],
        parking_episodes: tuple[ParkingEpisode, ...],
        incidents: tuple[Incident, ...],
        blocking_relations: tuple[BlockingRelation, ...] = (),
    ) -> None:
        """durable active aggregate를 끊은 timer chain으로 기동 복원한다.

        재시작 wall-clock은 trusted duration에 더하지 않는다.
        """

        self._validate_restore_parking_assignment_zones(parking_episodes)
        self._validate_restore_blocking_relation_egress(blocking_relations)
        self._zone_visit_tracker.restore_active(zone_visits)
        self._parking_episode_tracker.restore_active(parking_episodes)
        self._incident_reducer.restore_active(incidents)
        self._blocking_relation_tracker.restore_active(blocking_relations)

    def _validate_restore_blocking_relation_egress(
        self,
        relations: tuple[BlockingRelation, ...],
    ) -> None:
        for relation in relations:
            if self._egress_aisles.get_or_none(relation.egress_zone_id) is None:
                raise ValueError(
                    "active BlockingRelation references an egress aisle absent "
                    "from the current registry: "
                    f"{relation.egress_zone_id}"
                )

    def _validate_restore_parking_assignment_zones(
        self,
        parking_episodes: tuple[ParkingEpisode, ...],
    ) -> None:
        """복원 assignment의 zone 참조가 현재 registry에 속하는지 검증한다.

        ZoneVisit은 자신의 versioned scalar를 tracker가 검증하지만,
        ParkingAssignment에는 아직 zone definition version이 없다. 따라서
        조합 owner가 최소한 현재 registry의 zone 존재 여부를 먼저 확인해
        복원 뒤 blocking 계산에서 늦게 실패하는 일을 막는다.
        """

        for episode in parking_episodes:
            assignment = episode.assignment
            if (
                assignment is not None
                and assignment.zone_id is not None
                and self._zones.get_or_none(assignment.zone_id) is None
            ):
                raise ValueError(
                    "active ParkingEpisode assignment references a zone absent "
                    "from the current registry: "
                    f"zoneId={int(assignment.zone_id)}"
                )

    def process(
        self,
        batch: TrackingBatch,
        *,
        session_contexts: Mapping[PhysicalVehicleId, SessionContext] | None = None,
        entry_attempt_ids: Mapping[PhysicalVehicleId, EntryAttemptId] | None = None,
        entry_times: Mapping[PhysicalVehicleId, datetime] | None = None,
        skip_unobserved_vehicle_ids: Collection[PhysicalVehicleId] = (),
    ) -> ParkingPipelineResult:
        """한 TrackingBatch를 nonterminal 주차 상태 변경 계획으로 변환한다.

        ``session_contexts``는 active ContextBinding에서 조회한 authoritative
        projection이어야 한다. ``entry_attempt_ids``는 session이 없는 REVIEW/DENY
        차량도 local Incident를 공개할 수 있게 하는 authoritative correlation이다.
        ``entry_times``는 같은 correlation의 wire entryTime이며, 그보다 먼저
        확정된 Incident가 뒤늦게 OPEN으로 승격되지 않도록 publication 범위를
        제한한다.
        ``not_present_confirmed_vehicle_ids``가 포함돼도
        이 메서드는 scope를 끝내지 않는다. 실제 출차 transaction을 소유한
        상위 workflow가 commit 계획을 만들 때 ``physical_exit()``을 호출한다.
        """

        contexts = {} if session_contexts is None else session_contexts
        attempts = {} if entry_attempt_ids is None else entry_attempt_ids
        correlation_entry_times = {} if entry_times is None else entry_times
        zone_visit_updates: list[ZoneVisit] = []
        parking_episode_updates: list[ParkingEpisode] = []
        parking_transitions: list[ParkingTransition] = []
        incident_updates: list[Incident] = []
        incident_transitions: list[IncidentTransition] = []
        placement_diagnostics: list[PlacementDiagnostic] = []
        incident_signal_diagnostics: list[IncidentSignalDiagnostic] = []
        exit_traversal_observations: list[ExitTraversalObservation] = []
        frames: dict[PhysicalVehicleId, _VehicleFrame] = {}

        # pass 1: 차량별 geometry·scope 갱신. BlockingRelation 후보는 모든
        # 차량의 assignment를 알아야 계산할 수 있어 규칙 평가보다 뒤로 미룬다.
        for vehicle in batch.vehicles:
            context = contexts.get(vehicle.physical_vehicle_id)
            entry_attempt_id = attempts.get(vehicle.physical_vehicle_id)
            entry_time = correlation_entry_times.get(vehicle.physical_vehicle_id)
            observation = _effective_observation(batch, vehicle)
            ephemeral_evidence = assignment_resolver.analyze(
                vehicle,
                self._zones,
            )
            assignment = assignment_resolver.assignment_from_evidence(
                ephemeral_evidence,
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

            active_visits = self._zone_visit_tracker.active_visits(
                vehicle.physical_vehicle_id
            )
            exit_traversal_observations.extend(
                self._exit_traversal_observations(
                    vehicle=vehicle,
                    active_visits=active_visits,
                    observation=observation,
                )
            )
            parking_eligibility = evaluate_parking_eligibility(
                vehicle=vehicle,
                observation=observation,
                active_zone_visits=active_visits,
                zones=self._zones.all(),
                min_overlap_ratio=self._min_overlap_ratio,
            )

            previous_episode = self._parking_episode_tracker.active_episode(
                vehicle.physical_vehicle_id
            )
            motion_signal, motion_observation = _parking_motion_sample(
                vehicle,
                observation,
            )
            episode = self._parking_episode_tracker.update(
                physical_vehicle_id=vehicle.physical_vehicle_id,
                parking_session_id=(
                    None if context is None else context.parking_session_id
                ),
                signal=motion_signal,
                observation=motion_observation,
                observed_at=vehicle.observed_at,
                assignment=assignment,
                eligibility=parking_eligibility,
            )
            if episode is not None:
                parking_episode_updates.append(episode)
                parking_transitions.extend(
                    _parking_transitions(previous_episode, episode)
                )
                episode_state_changed = (
                    previous_episode is None
                    or previous_episode.state is not episode.state
                )
            else:
                episode_state_changed = False
            if (
                episode_state_changed
                or parking_eligibility.value
                is not ParkingEligibilityValue.ELIGIBLE
            ):
                self._observe_parking_eligibility(
                    batch=batch,
                    vehicle=vehicle,
                    previous_episode=previous_episode,
                    episode=episode,
                    eligibility=parking_eligibility,
                    assignment=assignment,
                    evidence=ephemeral_evidence,
                    motion_observation=motion_observation,
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

            current_episode = (
                episode
                if episode is not None
                else self._parking_episode_tracker.active_episode(
                    vehicle.physical_vehicle_id
                )
            )
            effective_assignment = assignment
            effective_evidence = ephemeral_evidence
            evidence_source = PlacementEvidenceSource.EPHEMERAL_FRAME
            if (
                current_episode is not None
                and current_episode.state
                in {ParkingState.PARKED, ParkingState.MOVE_PENDING}
                and current_episode.assignment is not None
            ):
                effective_assignment = current_episode.assignment
                effective_evidence = assignment_resolver.analyze_footprint(
                    current_episode.assignment.representative_footprint,
                    observed_at=current_episode.assignment.last_stable_at,
                    zones=self._zones,
                )
                evidence_source = PlacementEvidenceSource.PARKED_SNAPSHOT
            frames[vehicle.physical_vehicle_id] = _VehicleFrame(
                vehicle=vehicle,
                context=context,
                entry_attempt_id=entry_attempt_id,
                entry_time=entry_time,
                observation=observation,
                parking_motion_observation=motion_observation,
                parking_eligibility=parking_eligibility,
                assignment=effective_assignment,
                placement_evidence=effective_evidence,
                placement_evidence_source=evidence_source,
                active_visits=active_visits,
                episode=current_episode,
            )

        # pass 2: 이번 frame의 BlockingRelation 후보와 이미 non-terminal인
        # 관계를 함께 재평가한다.
        (
            blocking_relation_updates,
            blocking_evidence,
        ) = self._process_blocking_relations(
            batch,
            frames,
            incident_updates=incident_updates,
            incident_transitions=incident_transitions,
        )

        # pass 3: 이제 이번 frame의 BlockingRelation snapshot이 확정됐으니
        # 차량별 규칙을 평가한다.
        for vehicle_id, frame in frames.items():
            rule_context = RuleContext(
                vehicle=frame.vehicle,
                observation=batch.observation,
                parking_motion_observation=frame.parking_motion_observation,
                parking_eligibility=frame.parking_eligibility,
                session_context=frame.context,
                active_zone_visits=frame.active_visits,
                parking_episode=frame.episode,
                parking_assignment=frame.assignment,
                placement_evidence=frame.placement_evidence,
                placement_evidence_source=frame.placement_evidence_source,
                blocking_relations=self._blocking_relation_tracker.active_relations(
                    vehicle_id
                ),
                blocking_evidence=blocking_evidence,
                zones=self._zones,
                bad_parking_min_primary_overlap_ratio=(
                    self._bad_parking_min_primary_overlap_ratio
                ),
                bad_parking_min_secondary_overlap_ratio=(
                    self._bad_parking_min_secondary_overlap_ratio
                ),
                out_of_zone_min_spot_overlap_ratio=(
                    self._out_of_zone_min_spot_overlap_ratio
                ),
                observed_at=frame.vehicle.observed_at,
            )
            signals = self._evaluate_rules(
                rule_context,
                observation=frame.observation,
                entry_attempt_id=frame.entry_attempt_id,
                entry_time=frame.entry_time,
                incident_updates=incident_updates,
                incident_transitions=incident_transitions,
                incident_signal_diagnostics=incident_signal_diagnostics,
            )
            signals_by_code = {signal.key.rule_code: signal for signal in signals}
            placement_diagnostics.append(
                PlacementDiagnostic(
                    physical_vehicle_id=vehicle_id,
                    track_segment_id=frame.vehicle.track_segment_id,
                    source=frame.placement_evidence_source,
                    evidence=frame.placement_evidence,
                    assignment=frame.assignment,
                    parking_state=(
                        None if frame.episode is None else frame.episode.state
                    ),
                    bad_parking_signal=signals_by_code[bad_parking.BAD_PARKING],
                    out_of_zone_signal=signals_by_code[bad_parking.OUT_OF_ZONE],
                )
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

        self._observe_incident_transitions(
            incident_transitions,
            observed_at=batch.observed_at,
            camera_id=batch.camera_id,
            frame_id=batch.frame_id,
            signal_diagnostics=incident_signal_diagnostics,
        )
        return ParkingPipelineResult(
            zone_visit_updates=tuple(zone_visit_updates),
            parking_episode_updates=tuple(parking_episode_updates),
            parking_transitions=tuple(parking_transitions),
            incident_updates=tuple(incident_updates),
            incident_transitions=tuple(incident_transitions),
            blocking_relation_updates=blocking_relation_updates,
            placement_diagnostics=tuple(placement_diagnostics),
            incident_signal_diagnostics=tuple(incident_signal_diagnostics),
            exit_traversal_observations=tuple(exit_traversal_observations),
        )

    def _process_blocking_relations(
        self,
        batch: TrackingBatch,
        frames: Mapping[PhysicalVehicleId, _VehicleFrame],
        *,
        incident_updates: list[Incident],
        incident_transitions: list[IncidentTransition],
    ) -> tuple[
        tuple[BlockingRelation, ...],
        Mapping[BlockingRelationId, EgressBlockingEvidence],
    ]:
        """양쪽 PARKED 차량의 egress 후보와 기존 관계를 함께 갱신한다.

        새 관계는 subject와 victim 모두 PARKED일 때만 만들고, 이미 열린
        관계도 한쪽이 신뢰 가능한 frame에서 PARKED를 벗어나면 ABSENT로
        재평가한다. 이렇게 해야 이동한 차량의 관계가 tracker에 남지 않고
        clear timer를 거쳐 정상적으로 종료된다.
        """

        existing_keys: set[_BlockingCandidateKey] = {
            (
                relation.subject_physical_vehicle_id,
                relation.victim_physical_vehicle_id,
                relation.egress_zone_id,
            )
            for relation in self._blocking_relation_tracker.all_active_relations()
        }

        candidate_keys: set[_BlockingCandidateKey] = set()
        for victim_id, victim_frame in frames.items():
            if (
                victim_frame.episode is None
                or victim_frame.episode.state is not ParkingState.PARKED
                or victim_frame.assignment is None
                or victim_frame.assignment.zone_id is None
            ):
                continue
            for egress_aisle in self._egress_aisles.for_parking_zone(
                victim_frame.assignment.zone_id
            ):
                for subject_id, subject_frame in frames.items():
                    if subject_id == victim_id:
                        continue
                    if (
                        subject_frame.episode is None
                        or subject_frame.episode.state
                        is not ParkingState.PARKED
                    ):
                        continue
                    candidate_keys.add(
                        (subject_id, victim_id, egress_aisle.egress_zone_id)
                    )

        updates: list[BlockingRelation] = []
        evidence_by_relation: dict[
            BlockingRelationId, EgressBlockingEvidence
        ] = {}
        # replay 재현성을 위해 집합 순서가 아니라 key로 정렬해 처리한다.
        ordered_keys = sorted(
            existing_keys | candidate_keys,
            key=lambda key: (str(key[0]), str(key[1]), key[2]),
        )
        for subject_id, victim_id, egress_zone_id in ordered_keys:
            subject_frame = frames.get(subject_id)
            victim_frame = frames.get(victim_id)
            evidence: EgressBlockingEvidence | None = None
            # 관계는 subject·victim 둘 중 하나라도 이번 frame에 없거나 관측이
            # 불확실하면 유지만 하고 timer를 멈춘다(§7 "한쪽 관측 UNKNOWN이면
            # lifecycle 유지"). subject_frame이 있어야만 geometry를 잰다.
            if subject_frame is None or victim_frame is None:
                observation = _unobserved_observation(batch.observation)
                signal = PresenceSignal.UNKNOWN
            else:
                observation = _less_reliable_observation(
                    subject_frame.observation, victim_frame.observation
                )
                if observation.state is not ObservationState.OBSERVED:
                    signal = PresenceSignal.UNKNOWN
                elif (
                    subject_frame.episode is None
                    or subject_frame.episode.state is not ParkingState.PARKED
                    or victim_frame.episode is None
                    or victim_frame.episode.state is not ParkingState.PARKED
                ):
                    signal = PresenceSignal.ABSENT
                else:
                    egress_aisle = self._egress_aisles.get(egress_zone_id)
                    evidence = egress_blocking_resolver.analyze(
                        subject_frame.vehicle.bbox,
                        egress_aisle,
                    )
                    signal = (
                        PresenceSignal.PRESENT
                        if (
                            evidence.subject_overlap_ratio
                            >= self._blocking_min_subject_overlap_ratio
                            or evidence.egress_coverage_ratio
                            >= self._blocking_min_egress_coverage_ratio
                        )
                        else PresenceSignal.ABSENT
                    )

            source_episode_id = None
            if victim_frame is not None and victim_frame.episode is not None:
                source_episode_id = victim_frame.episode.episode_id
            relation = self._blocking_relation_tracker.update(
                subject_physical_vehicle_id=subject_id,
                victim_physical_vehicle_id=victim_id,
                egress_zone_id=egress_zone_id,
                source_parking_episode_id=source_episode_id,
                signal=signal,
                observation=observation,
                observed_at=batch.observed_at,
            )
            if relation is None:
                continue
            updates.append(relation)
            if evidence is not None:
                evidence_by_relation[relation.blocking_relation_id] = evidence
            if relation.state in {
                BlockingRelationState.RESOLVED,
                BlockingRelationState.CANCELED,
            }:
                self._collect_reductions(
                    self._incident_reducer.terminate_blocking_relation(
                        relation.blocking_relation_id,
                        observation=relation.observation,
                        observed_at=batch.observed_at,
                        reason=(
                            relation.termination_reason
                            or "BLOCKING_RELATION_RESOLVED"
                        ),
                    ),
                    incident_updates,
                    incident_transitions,
                )

        return tuple(updates), evidence_by_relation

    def _exit_traversal_observations(
        self,
        *,
        vehicle: PhysicalVehicleSnapshot,
        active_visits: tuple[ZoneVisit, ...],
        observation: ObservationStatus,
    ) -> tuple[ExitTraversalObservation, ...]:
        """active EXIT 방문의 현재 기준선 위치를 ephemeral 신호로 만든다.

        기준선 통과 사실을 이 owner가 보존하지 않는다. 정상 frame에서만
        차량 bbox 중심을 측정하고, application workflow가 반환값을 같은 local
        transaction의 durable checkpoint에 적용한다. ENTERING visit도 포함해
        빠른 차량이 ZoneVisit debounce 전에 기준선을 넘는 경우를 놓치지 않는다.
        """

        if observation.state is not ObservationState.OBSERVED:
            return ()
        center = bbox_center(vehicle.bbox)
        results: list[ExitTraversalObservation] = []
        for visit in active_visits:
            definition = self._exit_traversals.get(visit.zone_id)
            if definition is None:
                continue
            signed_offset = definition.signed_offset(center)
            if signed_offset > definition.hysteresis:
                side = ExitTraversalSide.OUTWARD
            elif signed_offset < -definition.hysteresis:
                side = ExitTraversalSide.INWARD
            else:
                side = ExitTraversalSide.NEUTRAL
            results.append(
                ExitTraversalObservation(
                    physical_vehicle_id=vehicle.physical_vehicle_id,
                    exit_zone_id=visit.zone_id,
                    exit_zone_visit_id=visit.visit_id,
                    zone_definition_version=(
                        visit.zone_definition_version
                    ),
                    observed_at=vehicle.observed_at,
                    side=side,
                    signed_offset=signed_offset,
                )
            )
        return tuple(results)

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
        blocking_relations = self._blocking_relation_tracker.physical_exit(
            physical_vehicle_id=physical_vehicle_id,
            observed_at=observed_at,
        )
        incident_updates: list[Incident] = []
        incident_transitions: list[IncidentTransition] = []

        # visit-scope를 먼저 PHYSICAL_EXIT로 닫으면 session correlation이
        # 있는 Incident의 종료 사유를 SESSION_EXITED로 보존할 수 없다.
        # subject/victim 차량 기준으로 한 번만 종료해 상위 owner가
        # 고정한 correlation 사유를 모든 관련 Incident에 적용한다.
        # terminate_physical_vehicle은 subject/victim 기준으로 이미
        # DOUBLE_PARKING Incident도 함께 끝내므로, BlockingRelation scope로
        # 다시 끝낼 필요가 없다 — 아래는 관계 자체의 상태만 갱신한다.
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

        self._observe_incident_transitions(
            incident_transitions,
            observed_at=observed_at,
            camera_id=None,
            frame_id=None,
            signal_diagnostics=(),
        )

        return ParkingPipelineResult(
            zone_visit_updates=visits,
            parking_episode_updates=() if episode is None else (episode,),
            incident_updates=tuple(incident_updates),
            incident_transitions=tuple(incident_transitions),
            blocking_relation_updates=blocking_relations,
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
        entry_time: datetime | None,
        incident_updates: list[Incident],
        incident_transitions: list[IncidentTransition],
        incident_signal_diagnostics: list[IncidentSignalDiagnostic],
    ) -> tuple[IncidentSignal, ...]:
        zone_id_by_visit_id = {
            visit.visit_id: visit.zone_id for visit in context.active_zone_visits
        }
        victim_id_by_relation_id = {
            relation.blocking_relation_id: relation.victim_physical_vehicle_id
            for relation in context.blocking_relations
        }
        zone_id_by_relation_id = {
            relation.blocking_relation_id: self._egress_aisles.get(
                relation.egress_zone_id
            ).parking_zone_id
            for relation in context.blocking_relations
        }
        parking_session_id = (
            None
            if context.session_context is None
            else context.session_context.parking_session_id
        )
        evaluated_signals: list[IncidentSignal] = []
        for evaluate in _RULE_EVALUATORS:
            for signal in evaluate(context):
                evaluated_signals.append(signal)
                incident_signal_diagnostics.append(
                    IncidentSignalDiagnostic(
                        physical_vehicle_id=(
                            context.vehicle.physical_vehicle_id
                        ),
                        track_segment_id=context.vehicle.track_segment_id,
                        signal=signal,
                        timing=self._incident_reducer.timing_for_rule(
                            signal.key.rule_code
                        ),
                    )
                )
                zone_id: ZoneId | None = None
                victim_physical_vehicle_id: PhysicalVehicleId | None = None
                if signal.key.scope_type is IncidentKeyScope.ZONE_VISIT:
                    zone_id = zone_id_by_visit_id.get(signal.key.scope_id)
                elif signal.key.scope_type is IncidentKeyScope.BLOCKING_RELATION:
                    zone_id = zone_id_by_relation_id.get(signal.key.scope_id)
                    victim_physical_vehicle_id = victim_id_by_relation_id.get(
                        signal.key.scope_id
                    )
                reduction = self._incident_reducer.reduce(
                    signal,
                    physical_vehicle_id=context.vehicle.physical_vehicle_id,
                    observation=observation,
                    entry_attempt_id=entry_attempt_id,
                    entry_time=entry_time,
                    parking_session_id=parking_session_id,
                    zone_id=zone_id,
                    victim_physical_vehicle_id=victim_physical_vehicle_id,
                )
                if reduction is not None:
                    self._collect_reductions(
                        (reduction,),
                        incident_updates,
                        incident_transitions,
                    )
        return tuple(evaluated_signals)

    def _observe_parking_eligibility(
        self,
        *,
        batch: TrackingBatch,
        vehicle: PhysicalVehicleSnapshot,
        previous_episode: ParkingEpisode | None,
        episode: ParkingEpisode | None,
        eligibility: ParkingEligibilityDecision,
        assignment: ParkingAssignment,
        evidence: PlacementEvidence,
        motion_observation: ObservationStatus,
    ) -> None:
        entry_exit_zone = (
            self._zones.get_or_none(eligibility.blocking_zone_id)
            if eligibility.blocking_zone_id is not None
            else None
        )
        result_by_state = {
            ParkingState.STOP_PENDING: "STOP_CANDIDATE_OPENED",
            ParkingState.PARKED: "PARKING_CONFIRMED",
            ParkingState.MOVE_PENDING: "MOVEMENT_CANDIDATE_OPENED",
            ParkingState.ENDED: "PARKING_ENDED",
            ParkingState.CANCELED: "STOP_CANDIDATE_CANCELED",
        }
        if eligibility.value is ParkingEligibilityValue.INELIGIBLE:
            result = "PARKING_REJECTED"
        elif eligibility.value is ParkingEligibilityValue.UNKNOWN:
            result = "PARKING_DEFERRED"
        elif episode is None:
            result = "NO_PARKING_STATE_CHANGE"
        else:
            result = result_by_state[episode.state]
        emit_best_effort(
            self._diagnostics_sink,
            DiagnosticEvent(
                event_type=DiagnosticEventType.PARKING_ELIGIBILITY_EVALUATED,
                occurred_at=vehicle.observed_at,
                severity=(
                    DiagnosticSeverity.WARNING
                    if eligibility.value is ParkingEligibilityValue.INELIGIBLE
                    else DiagnosticSeverity.INFO
                ),
                attributes={
                    "assignmentConfidence": assignment.confidence,
                    "assignmentState": assignment.state.value,
                    "assignmentZoneId": (
                        int(assignment.zone_id)
                        if assignment.zone_id is not None
                        else None
                    ),
                    "cameraId": batch.camera_id,
                    "eligibilityReason": eligibility.reason,
                    "eligibilityValue": eligibility.value.value,
                    "entryExitOverlapRatio": eligibility.overlap_ratio,
                    "entryExitRole": (
                        entry_exit_zone.entry_exit_role.value
                        if entry_exit_zone is not None
                        and entry_exit_zone.entry_exit_role is not None
                        else None
                    ),
                    "entryExitZoneId": (
                        int(entry_exit_zone.zone_id)
                        if entry_exit_zone is not None
                        else None
                    ),
                    "frameId": batch.frame_id,
                    "motionObservationReason": (
                        motion_observation.reason.value
                        if motion_observation.reason is not None
                        else None
                    ),
                    "motionObservationState": motion_observation.state.value,
                    "motionSignal": (
                        episode.last_signal.value
                        if episode is not None
                        else vehicle.motion_signal.value
                    ),
                    "movementConfirmationSeconds": (
                        episode.movement_confirmation_seconds
                        if episode is not None
                        else None
                    ),
                    "movementTrustedSeconds": (
                        episode.movement_trusted_seconds
                        if episode is not None
                        else None
                    ),
                    "parkingEpisodeId": (
                        str(episode.episode_id) if episode is not None else None
                    ),
                    "parkingState": (
                        episode.state.value if episode is not None else None
                    ),
                    "physicalVehicleId": str(vehicle.physical_vehicle_id),
                    "previousParkingState": (
                        previous_episode.state.value
                        if previous_episode is not None
                        else None
                    ),
                    "primaryOverlapRatio": evidence.primary_overlap_ratio,
                    "primaryZoneId": (
                        int(evidence.primary_zone_id)
                        if evidence.primary_zone_id is not None
                        else None
                    ),
                    "result": result,
                    "secondaryOverlapRatio": evidence.secondary_overlap_ratio,
                    "secondaryZoneId": (
                        int(evidence.secondary_zone_id)
                        if evidence.secondary_zone_id is not None
                        else None
                    ),
                    "stationaryConfirmationSeconds": (
                        episode.parking_confirmation_seconds
                        if episode is not None
                        else None
                    ),
                    "stationaryTrustedSeconds": (
                        episode.stationary_trusted_seconds
                        if episode is not None
                        else None
                    ),
                    "terminationReason": (
                        episode.termination_reason
                        if episode is not None
                        else None
                    ),
                    "trackSegmentId": int(vehicle.track_segment_id),
                },
            ),
        )

    def _observe_incident_transitions(
        self,
        transitions: Collection[IncidentTransition],
        *,
        observed_at: datetime,
        camera_id: str | None,
        frame_id: int | None,
        signal_diagnostics: Collection[IncidentSignalDiagnostic],
    ) -> None:
        diagnostic_by_key = {
            item.signal.key: item for item in signal_diagnostics
        }
        for transition in transitions:
            incident = transition.incident
            diagnostic = diagnostic_by_key.get(incident.key)
            signal = None if diagnostic is None else diagnostic.signal
            timing = None if diagnostic is None else diagnostic.timing
            if incident.zone_id is not None:
                zone_provenance = (
                    "ZONE_VISIT"
                    if incident.key.scope_type is IncidentKeyScope.ZONE_VISIT
                    else (
                        "EGRESS_AISLE_PARKING_ZONE"
                        if incident.key.scope_type
                        is IncidentKeyScope.BLOCKING_RELATION
                        else "INCIDENT_CONTEXT"
                    )
                )
            elif incident.key.scope_type is IncidentKeyScope.PHYSICAL_VEHICLE:
                zone_provenance = "NONE_PHYSICAL_VEHICLE_SCOPE"
            elif incident.key.scope_type is IncidentKeyScope.BLOCKING_RELATION:
                zone_provenance = "NONE_BLOCKING_RELATION_SCOPE"
            else:
                zone_provenance = "NONE"
            emit_best_effort(
                self._diagnostics_sink,
                DiagnosticEvent(
                    event_type=(
                        DiagnosticEventType.INCIDENT_PROJECTION_EVALUATED
                    ),
                    occurred_at=observed_at,
                    severity=(
                        DiagnosticSeverity.WARNING
                        if transition.transition_type.value == "OPEN"
                        else DiagnosticSeverity.INFO
                    ),
                    attributes={
                        "cameraId": camera_id,
                        "clearDurationSeconds": (
                            timing.clear_duration_seconds
                            if timing is not None
                            else incident.clear_duration_seconds
                        ),
                        "clearTrustedSeconds": incident.clear_trusted_seconds,
                        "confirmDurationSeconds": (
                            timing.confirm_duration_seconds
                            if timing is not None
                            else incident.confirm_duration_seconds
                        ),
                        "confirmTrustedSeconds": incident.confirm_trusted_seconds,
                        "entryAttemptId": (
                            str(incident.entry_attempt_id)
                            if incident.entry_attempt_id is not None
                            else None
                        ),
                        "frameId": frame_id,
                        "incidentId": str(incident.incident_id),
                        "incidentState": incident.state.value,
                        "parkingSessionId": (
                            int(incident.parking_session_id)
                            if incident.parking_session_id is not None
                            else None
                        ),
                        "physicalVehicleId": str(
                            incident.physical_vehicle_id
                        ),
                        "ruleCode": incident.key.rule_code,
                        "scopeId": str(incident.key.scope_id),
                        "scopeType": incident.key.scope_type.value,
                        "signalConfirmable": (
                            signal.confirmable if signal is not None else None
                        ),
                        "signalValue": (
                            signal.value.value if signal is not None else None
                        ),
                        "transitionType": transition.transition_type.value,
                        "victimPhysicalVehicleId": (
                            str(incident.victim_physical_vehicle_id)
                            if incident.victim_physical_vehicle_id is not None
                            else None
                        ),
                        "zoneId": (
                            int(incident.zone_id)
                            if incident.zone_id is not None
                            else None
                        ),
                        "zoneProvenance": zone_provenance,
                    },
                ),
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


def _parking_motion_sample(
    vehicle: PhysicalVehicleSnapshot,
    physical_observation: ObservationStatus,
) -> tuple[MotionSignal, ObservationStatus]:
    """PhysicalVehicle 관측과 ParkingEpisode motion dependency를 분리한다.

    bbox·identity가 정상이어도 motion history가 부족하거나 상충할 수 있다.
    이 경우 ZoneVisit과 최신 assignment는 현재 geometry로 계속 평가하되,
    ParkingEpisode에만 UNKNOWN/DEPENDENCY_UNAVAILABLE을 전달해 timer chain을
    끊는다. 마지막 신뢰 motion 시각은 tracker가 기존 episode에서 보존한다.
    """

    if physical_observation.state is not ObservationState.OBSERVED:
        return MotionSignal.UNKNOWN, physical_observation
    if vehicle.motion_signal is not MotionSignal.UNKNOWN:
        return vehicle.motion_signal, physical_observation
    return MotionSignal.UNKNOWN, ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
    )


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


_OBSERVATION_SEVERITY = {
    ObservationState.OBSERVED: 0,
    ObservationState.DEGRADED: 1,
    ObservationState.UNKNOWN: 2,
}


def _less_reliable_observation(
    first: ObservationStatus, second: ObservationStatus
) -> ObservationStatus:
    """둘 중 더 신뢰할 수 없는 쪽을 반환한다(동률이면 첫 번째)."""

    if _OBSERVATION_SEVERITY[second.state] > _OBSERVATION_SEVERITY[first.state]:
        return second
    return first


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


def _validate_positive_ratio(value: float, name: str) -> None:
    if not math.isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError(f"{name} must be finite, greater than 0, and at most 1")

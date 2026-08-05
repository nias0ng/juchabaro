"""한 TrackingBatch의 session·parking·outbox 반영을 하나로 commit한다.

Camera·inference는 SQLite transaction 밖에서 수행한다. 이 workflow에
TrackingBatch가 도착한 뒤에는 session correlation, parking aggregate,
physical departure, exact outbox bytes를 하나의 ``BEGIN IMMEDIATE``로
적용한다. Backend endpoint·DTO·idempotency key 형식은 여기서
결정하지 않고 ``PublicationPreparer``에 맡긴다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Protocol
from uuid import uuid4

from src.application.physical_presence_workflow import (
    PhysicalDeparturePlan,
    PhysicalPresenceWorkflow,
    SessionExitTransition,
)
from src.application.pending_handoff_workflow import PendingHandoffWorkflow
from src.application.session_observation_workflow import (
    SessionObservationWorkflow,
)
from src.communication.outbox import PreparedPublication, SQLiteOutboxWriter
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.evidence.capture_models import EvidenceCaptureIntent, EvidenceCropKind
from src.evidence.models import EvidenceArtifact, EvidenceId, EvidenceState
from src.parking.models import (
    Incident,
    IncidentId,
    IncidentTransitionType,
    IncidentTransition,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingPipelineResult,
    ParkingTransition,
    ZoneVisit,
    ZoneVisitId,
)
from src.parking.pipeline import ParkingPipeline
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.storage.aggregate_repositories import (
    IncidentRepository,
    ParkingEpisodeRepository,
    ZoneVisitRepository,
)
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.repositories import (
    OutboxRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import PhysicalVehicle, PhysicalVehicleId, TrackingBatch


_DIRTY_CHECKPOINT_INTERVAL = timedelta(seconds=10)


class PublicationPreparer(Protocol):
    """Domain transition을 한 번 확정한 exact wire bytes로 변환한다."""

    def prepare_parking(
        self,
        transition: ParkingTransition,
    ) -> PreparedPublication:
        ...

    def prepare_incident(
        self,
        transition: IncidentTransition,
    ) -> PreparedPublication:
        ...

    def prepare_session_exit(
        self,
        transition: SessionExitTransition,
    ) -> PreparedPublication:
        ...


@dataclass(frozen=True)
class FrameObservationResult:
    """commit된 frame 결과와 tracking에 ACK할 물리 종료 대상."""

    parking_result: ParkingPipelineResult
    retired_physical_vehicle_ids: tuple[PhysicalVehicleId, ...]
    active_incidents: tuple[Incident, ...] = ()
    evidence_capture_intents: tuple[EvidenceCaptureIntent, ...] = ()


@dataclass(frozen=True)
class RuntimeRecoveryResult:
    """기동 시 읽은 active scope와 복원·출차 처리 결과."""

    zone_visit_count: int
    parking_episode_count: int
    incident_count: int
    recovered_outbox_count: int
    active_physical_vehicles: tuple[PhysicalVehicle, ...]
    completed_departure_count: int
    active_incidents: tuple[Incident, ...]


class FrameObservationWorkflow:
    """TrackingBatch 하나의 최상위 local Unit of Work."""

    def __init__(
        self,
        *,
        session_workflow: SessionObservationWorkflow,
        parking_pipeline: ParkingPipeline,
        context_binding_coordinator: ContextBindingCoordinator,
        publication_preparer: PublicationPreparer,
    ) -> None:
        self._session_workflow = session_workflow
        self._parking_pipeline = parking_pipeline
        self._physical_presence_workflow = PhysicalPresenceWorkflow(
            context_binding_coordinator=context_binding_coordinator,
            parking_pipeline=parking_pipeline,
        )
        self._pending_handoff_workflow = PendingHandoffWorkflow()
        self._publication_preparer = publication_preparer

    def recover_runtime(
        self,
        *,
        connection: sqlite3.Connection,
        recovered_at: datetime | None = None,
    ) -> RuntimeRecoveryResult:
        """camera 시작 전 durable active scope와 IN_FLIGHT outbox를 복원한다.

        trusted timer anchor는 owner에서 ``None``으로 시작하여 process
        downtime을 누적하지 않는다. PhysicalVehicle–track 재식별은
        이 메서드의 책임이 아니며 임의로 absence confirmer를 복원하지
        않는다.
        """

        restart_at = recovered_at or datetime.now(timezone.utc)
        if restart_at.tzinfo is None or restart_at.utcoffset() is None:
            raise ValueError("recovered_at must be timezone-aware")
        checkpoint = self._parking_pipeline.checkpoint_state()
        try:
            with UnitOfWork(connection):
                zone_visits = ZoneVisitRepository(connection).list_active()
                parking_episodes = ParkingEpisodeRepository(
                    connection
                ).list_active()
                incidents = IncidentRepository(connection).list_active()
                physical_vehicles = PhysicalVehicleRepository(
                    connection
                ).list_active()
                self._parking_pipeline.restore_active(
                    zone_visits=zone_visits,
                    parking_episodes=parking_episodes,
                    incidents=incidents,
                )

                # crash 전 이미 durable 확정된 부재는 새 timer로
                # 추정하지 않고 original occurredAt으로 종료한다.
                departure_plans = tuple(
                    self._physical_presence_workflow.plan_departure(
                        vehicle.physical_vehicle_id,
                        connection=connection,
                    )
                    for vehicle in physical_vehicles
                    if vehicle.absence_confirmed_at is not None
                )
                if departure_plans:
                    departure_result = _combine_parking_results(
                        *(plan.parking_result for plan in departure_plans)
                    )
                    _ParkingAggregateWriter(connection).save(departure_result)
                    self._pending_handoff_workflow.capture(
                        departure_result,
                        connection=connection,
                    )
                    for plan in departure_plans:
                        self._physical_presence_workflow.complete_departure(
                            plan,
                            connection=connection,
                        )
                    self._enqueue_publications(
                        connection=connection,
                        parking_result=departure_result,
                        departure_plans=departure_plans,
                        historical_session_exits=(),
                    )

                active_physical_vehicles = self._mark_restart_unknown(
                    connection=connection,
                    recovered_at=restart_at,
                )
                recovered_zone_visits = ZoneVisitRepository(
                    connection
                ).list_active()
                recovered_parking_episodes = ParkingEpisodeRepository(
                    connection
                ).list_active()
                recovered_incidents = IncidentRepository(
                    connection
                ).list_active()
                self._parking_pipeline.restore_active(
                    zone_visits=recovered_zone_visits,
                    parking_episodes=recovered_parking_episodes,
                    incidents=recovered_incidents,
                )
                recovered_outbox_count = OutboxRepository(
                    connection
                ).recover_in_flight()
                self._pending_handoff_workflow.expire_due(
                    now=restart_at,
                    connection=connection,
                )
        except Exception:
            self._parking_pipeline.restore_state(checkpoint)
            raise
        return RuntimeRecoveryResult(
            zone_visit_count=len(zone_visits),
            parking_episode_count=len(parking_episodes),
            incident_count=len(incidents),
            recovered_outbox_count=recovered_outbox_count,
            active_physical_vehicles=active_physical_vehicles,
            completed_departure_count=len(departure_plans),
            active_incidents=recovered_incidents,
        )

    @staticmethod
    def _mark_restart_unknown(
        *,
        connection: sqlite3.Connection,
        recovered_at: datetime,
    ) -> tuple[PhysicalVehicle, ...]:
        """active observation을 UNKNOWN/PROCESS_RESTARTED로 끊어 저장한다."""

        unknown_for = lambda observation: ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.PROCESS_RESTARTED,
            last_reliable_observed_at=observation.last_reliable_observed_at,
        )
        vehicle_repository = PhysicalVehicleRepository(connection)
        vehicles: list[PhysicalVehicle] = []
        for vehicle in vehicle_repository.list_active():
            observation = unknown_for(vehicle.observation)
            if vehicle.observation == observation:
                vehicles.append(vehicle)
                continue
            updated = replace(
                vehicle,
                observation=observation,
                record_version=vehicle.record_version + 1,
                updated_at=max(recovered_at, vehicle.updated_at),
            )
            vehicle_repository.save(
                updated,
                expected_record_version=vehicle.record_version,
            )
            vehicles.append(updated)

        zone_repository = ZoneVisitRepository(connection)
        for visit in zone_repository.list_active():
            observation = unknown_for(visit.observation)
            if visit.observation == observation:
                continue
            zone_repository.save(
                replace(
                    visit,
                    observation=observation,
                    record_version=visit.record_version + 1,
                    updated_at=max(recovered_at, visit.updated_at),
                ),
                expected_record_version=visit.record_version,
            )

        episode_repository = ParkingEpisodeRepository(connection)
        for episode in episode_repository.list_active():
            observation = unknown_for(episode.observation)
            if episode.observation == observation:
                continue
            episode_repository.save(
                replace(
                    episode,
                    observation=observation,
                    record_version=episode.record_version + 1,
                    updated_at=max(recovered_at, episode.updated_at),
                ),
                expected_record_version=episode.record_version,
            )

        incident_repository = IncidentRepository(connection)
        for incident in incident_repository.list_active():
            observation = unknown_for(incident.observation)
            if incident.observation == observation:
                continue
            incident_repository.save(
                replace(
                    incident,
                    observation=observation,
                    record_version=incident.record_version + 1,
                    updated_at=max(recovered_at, incident.updated_at),
                ),
                expected_record_version=incident.record_version,
            )

        mirror_repository = ParkingSessionMirrorRepository(connection)
        for mirror in mirror_repository.list_inside():
            observation = unknown_for(mirror.physical_observation)
            if mirror.physical_observation == observation:
                continue
            mirror_repository.save(
                replace(
                    mirror,
                    physical_observation=observation,
                    record_version=mirror.record_version + 1,
                    updated_at=max(recovered_at, mirror.updated_at),
                ),
                expected_record_version=mirror.record_version,
            )
        return tuple(vehicles)

    def process(
        self,
        batch: TrackingBatch,
        *,
        connection: sqlite3.Connection,
    ) -> FrameObservationResult:
        """frame을 commit하고, commit된 출차 대상만 ACK 대상으로 반환한다."""

        session_checkpoint = self._session_workflow.checkpoint_state()
        parking_checkpoint = self._parking_pipeline.checkpoint_state()
        try:
            with UnitOfWork(connection):
                session_result = self._session_workflow.apply(
                    batch,
                    connection=connection,
                )
                historical_result = (
                    self._pending_handoff_workflow.correlate_historical_sessions(
                        session_result.historical_attempts,
                        observed_at=batch.observed_at,
                        connection=connection,
                    )
                )
                parking_result = self._parking_pipeline.process(
                    batch,
                    session_contexts={
                        **session_result.session_contexts,
                        **historical_result.session_contexts,
                    },
                    entry_attempt_ids={
                        **session_result.entry_attempt_ids,
                        **historical_result.entry_attempt_ids,
                    },
                    skip_unobserved_vehicle_ids=(
                        batch.not_present_confirmed_vehicle_ids
                    ),
                )

                departure_plans = tuple(
                    self._physical_presence_workflow.plan_departure(
                        physical_vehicle_id,
                        connection=connection,
                    )
                    for physical_vehicle_id in (
                        batch.not_present_confirmed_vehicle_ids
                    )
                )
                combined_result = _combine_parking_results(
                    parking_result,
                    *(plan.parking_result for plan in departure_plans),
                )
                newly_opened_incidents = _newly_opened_incidents(
                    combined_result,
                    connection=connection,
                )
                _ParkingAggregateWriter(connection).save(combined_result)
                evidence_capture_intents = self._reserve_evidence_captures(
                    newly_opened_incidents,
                    parking_result=combined_result,
                    captured_at=batch.observed_at,
                    connection=connection,
                )
                self._pending_handoff_workflow.capture(
                    combined_result,
                    connection=connection,
                )
                pending_materialization = (
                    self._pending_handoff_workflow.materialize(
                        session_result,
                        historical_result,
                        materialized_at=batch.observed_at,
                        connection=connection,
                    )
                )
                combined_result = _combine_parking_results(
                    combined_result,
                    pending_materialization.parking_result,
                )

                for plan in departure_plans:
                    self._physical_presence_workflow.complete_departure(
                        plan,
                        connection=connection,
                    )
                self._enqueue_publications(
                    connection=connection,
                    parking_result=combined_result,
                    departure_plans=departure_plans,
                    historical_session_exits=(
                        historical_result.session_exit_transitions
                    ),
                    pending_transitions=(
                        pending_materialization.ordered_transitions
                    ),
                )
                self._pending_handoff_workflow.expire_due(
                    now=batch.observed_at,
                    connection=connection,
                )
                active_incidents = IncidentRepository(
                    connection
                ).list_active()
        except Exception:
            # SQLite rollback만으로는 transaction 안에서 먼저 변경된
            # in-memory timer·reducer state를 되돌릴 수 없다.
            self._session_workflow.restore_state(session_checkpoint)
            self._parking_pipeline.restore_state(parking_checkpoint)
            raise

        return FrameObservationResult(
            parking_result=combined_result,
            retired_physical_vehicle_ids=tuple(
                plan.physical_vehicle_id for plan in departure_plans
            ),
            active_incidents=active_incidents,
            evidence_capture_intents=evidence_capture_intents,
        )

    @staticmethod
    def _reserve_evidence_captures(
        incidents: tuple[Incident, ...],
        *,
        parking_result: ParkingPipelineResult,
        captured_at: datetime,
        connection: sqlite3.Connection,
    ) -> tuple[EvidenceCaptureIntent, ...]:
        """새 OPEN과 같은 transaction에서 capture identity를 먼저 예약한다."""

        repository = EvidenceArtifactRepository(connection)
        open_revisions = {
            transition.incident.incident_id: transition.incident.publication_revision
            for transition in parking_result.incident_transitions
            if transition.transition_type is IncidentTransitionType.OPEN
        }
        intents: list[EvidenceCaptureIntent] = []
        for incident in incidents:
            if repository.count_for_incident(incident.incident_id) > 0:
                continue
            crop_kinds = (
                (EvidenceCropKind.CONTEXT, EvidenceCropKind.DETAIL)
                if incident.key.rule_code == "DOUBLE_PARKING"
                else (EvidenceCropKind.CONTEXT,)
            )
            for crop_kind in crop_kinds:
                evidence_id = EvidenceId(uuid4())
                repository.add(
                    EvidenceArtifact(
                        evidence_id=evidence_id,
                        incident_id=incident.incident_id,
                        publication_revision=open_revisions.get(
                            incident.incident_id
                        ),
                        captured_at=captured_at,
                        image_type="image/jpeg",
                        state=EvidenceState.RESERVED,
                        record_version=1,
                        created_at=captured_at,
                        updated_at=captured_at,
                    )
                )
                intents.append(
                    EvidenceCaptureIntent(
                        evidence_id=evidence_id,
                        incident_id=incident.incident_id,
                        rule_code=incident.key.rule_code,
                        physical_vehicle_id=incident.physical_vehicle_id,
                        victim_physical_vehicle_id=(
                            incident.victim_physical_vehicle_id
                        ),
                        zone_id=incident.zone_id,
                        captured_at=captured_at,
                        crop_kind=crop_kind,
                    )
                )
        return tuple(intents)

    def _enqueue_publications(
        self,
        *,
        connection: sqlite3.Connection,
        parking_result: ParkingPipelineResult,
        departure_plans: tuple[PhysicalDeparturePlan, ...],
        historical_session_exits: tuple[SessionExitTransition, ...],
        pending_transitions: tuple[
            ParkingTransition | IncidentTransition, ...
        ] = (),
    ) -> None:
        """확정 전이를 original occurredAt 순으로 exact outbox row로 만든다."""

        writer = SQLiteOutboxWriter(connection)
        pending_identities = {
            _publication_identity(transition)
            for transition in pending_transitions
        }
        current_transitions: tuple[
            ParkingTransition | IncidentTransition, ...
        ] = (
            *parking_result.parking_transitions,
            *parking_result.incident_transitions,
        )
        domain_transitions = (
            *(
                transition
                for transition in current_transitions
                if _publication_identity(transition)
                not in pending_identities
            ),
            *pending_transitions,
        )
        session_exits = (
            *(
                plan.session_exit_transition
                for plan in departure_plans
                if plan.session_exit_transition is not None
            ),
            *historical_session_exits,
        )
        for transition in sorted(
            (*domain_transitions, *session_exits),
            key=_publication_order,
        ):
            if isinstance(transition, ParkingTransition):
                prepared = _validate_prepared_publication(
                    self._publication_preparer.prepare_parking(transition),
                    aggregate_type="ParkingEpisode",
                    aggregate_id=str(transition.parking_episode_id),
                    publication_revision=transition.publication_revision,
                    transition_type=transition.transition_type.value,
                )
                enqueued = writer.enqueue(prepared)
                self._pending_handoff_workflow.mark_materialized(
                    aggregate_type="ParkingEpisode",
                    aggregate_id=str(transition.parking_episode_id),
                    transition_type=transition.transition_type.value,
                    occurred_at=transition.occurred_at,
                    delivery_id=enqueued.record.delivery_id,
                    updated_at_us=enqueued.record.updated_at_us,
                    connection=connection,
                )
                continue
            if isinstance(transition, IncidentTransition):
                if transition.transition_type is IncidentTransitionType.OPEN:
                    EvidenceArtifactRepository(
                        connection
                    ).bind_publication_revision_for_incident(
                        transition.incident.incident_id,
                        publication_revision=(
                            transition.incident.publication_revision
                        ),
                        bound_at=_incident_transition_occurred_at(transition),
                    )
                prepared = _validate_prepared_publication(
                    self._publication_preparer.prepare_incident(transition),
                    aggregate_type="Incident",
                    aggregate_id=str(transition.incident.incident_id),
                    publication_revision=(
                        transition.incident.publication_revision
                    ),
                    transition_type=transition.transition_type.value,
                )
                enqueued = writer.enqueue(prepared)
                occurred_at = _incident_transition_occurred_at(transition)
                self._pending_handoff_workflow.mark_materialized(
                    aggregate_type="Incident",
                    aggregate_id=str(transition.incident.incident_id),
                    transition_type=transition.transition_type.value,
                    occurred_at=occurred_at,
                    delivery_id=enqueued.record.delivery_id,
                    updated_at_us=enqueued.record.updated_at_us,
                    connection=connection,
                )
                continue
            prepared = _validate_prepared_publication(
                self._publication_preparer.prepare_session_exit(transition),
                aggregate_type="ParkingSession",
                aggregate_id=str(transition.parking_session_id),
                publication_revision=transition.publication_revision,
                transition_type="SESSION_EXIT",
            )
            writer.enqueue(prepared)


class _ParkingAggregateWriter:
    """frame 결과의 aggregate별 최종 snapshot만 optimistic 저장한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._zone_visits = ZoneVisitRepository(connection)
        self._parking_episodes = ParkingEpisodeRepository(connection)
        self._incidents = IncidentRepository(connection)

    def save(self, result: ParkingPipelineResult) -> None:
        if result.blocking_relation_updates:
            raise NotImplementedError(
                "BlockingRelation repository wiring is not implemented"
            )
        forced_episode_ids = {
            transition.parking_episode_id
            for transition in result.parking_transitions
        }
        forced_incident_ids = {
            transition.incident.incident_id
            for transition in result.incident_transitions
        }
        self._save_zone_visits(
            _latest_by_id(result.zone_visit_updates, "visit_id")
        )
        self._save_parking_episodes(
            _latest_by_id(result.parking_episode_updates, "episode_id"),
            forced_ids=forced_episode_ids,
        )
        self._save_incidents(
            _latest_by_id(result.incident_updates, "incident_id"),
            forced_ids=forced_incident_ids,
        )

    def _save_zone_visits(
        self,
        visits: Mapping[ZoneVisitId, ZoneVisit],
    ) -> None:
        for visit in visits.values():
            existing = self._zone_visits.get(visit.visit_id)
            if existing is None:
                self._zone_visits.add(visit)
            elif visit != existing and (
                _scope_change_requires_immediate_save(existing, visit)
                or _dirty_checkpoint_due(existing, visit)
            ):
                self._zone_visits.save(
                    visit,
                    expected_record_version=existing.record_version,
                )

    def _save_parking_episodes(
        self,
        episodes: Mapping[ParkingEpisodeId, ParkingEpisode],
        *,
        forced_ids: set[ParkingEpisodeId],
    ) -> None:
        for episode in episodes.values():
            existing = self._parking_episodes.get(episode.episode_id)
            if existing is None:
                self._parking_episodes.add(episode)
            elif episode != existing and (
                episode.episode_id in forced_ids
                or _scope_change_requires_immediate_save(existing, episode)
                or episode.parking_session_id != existing.parking_session_id
                or episode.publication_revision
                != existing.publication_revision
                or _dirty_checkpoint_due(existing, episode)
            ):
                self._parking_episodes.save(
                    episode,
                    expected_record_version=existing.record_version,
                )

    def _save_incidents(
        self,
        incidents: Mapping[IncidentId, Incident],
        *,
        forced_ids: set[IncidentId],
    ) -> None:
        for incident in incidents.values():
            existing = self._incidents.get(incident.incident_id)
            if existing is None:
                self._incidents.add(incident)
            elif incident != existing and (
                incident.incident_id in forced_ids
                or _scope_change_requires_immediate_save(existing, incident)
                or incident.publication_revision
                != existing.publication_revision
                or incident.entry_attempt_id != existing.entry_attempt_id
                or incident.parking_session_id != existing.parking_session_id
                or incident.zone_id != existing.zone_id
                or incident.victim_physical_vehicle_id
                != existing.victim_physical_vehicle_id
                or _dirty_checkpoint_due(existing, incident)
            ):
                self._incidents.save(
                    incident,
                    expected_record_version=existing.record_version,
                )


def _newly_opened_incidents(
    result: ParkingPipelineResult,
    *,
    connection: sqlite3.Connection,
) -> tuple[Incident, ...]:
    """이번 Unit of Work에서 처음 confirmed 상태가 되는 Incident를 찾는다."""

    repository = IncidentRepository(connection)
    opened = _latest_by_id(
        tuple(
            incident
            for incident in result.incident_updates
            if incident.confirmed_at is not None
        ),
        "incident_id",
    )
    return tuple(
        incident
        for incident in opened.values()
        if (
            (existing := repository.get(incident.incident_id)) is None
            or existing.confirmed_at is None
        )
    )


def _combine_parking_results(
    *results: ParkingPipelineResult,
) -> ParkingPipelineResult:
    return ParkingPipelineResult(
        zone_visit_updates=tuple(
            item for result in results for item in result.zone_visit_updates
        ),
        parking_episode_updates=tuple(
            item
            for result in results
            for item in result.parking_episode_updates
        ),
        parking_transitions=tuple(
            item for result in results for item in result.parking_transitions
        ),
        blocking_relation_updates=tuple(
            item
            for result in results
            for item in result.blocking_relation_updates
        ),
        incident_updates=tuple(
            item for result in results for item in result.incident_updates
        ),
        incident_transitions=tuple(
            item for result in results for item in result.incident_transitions
        ),
    )


def _latest_by_id(items: tuple[object, ...], attribute: str) -> dict:
    latest: dict = {}
    for item in items:
        latest[getattr(item, attribute)] = item
    return latest


def _scope_change_requires_immediate_save(existing, incoming) -> bool:
    return (
        incoming.state is not existing.state
        or incoming.observation.state is not existing.observation.state
        or incoming.observation.reason is not existing.observation.reason
    )


def _dirty_checkpoint_due(existing, incoming) -> bool:
    if incoming.updated_at < existing.updated_at:
        raise RuntimeError("aggregate updated_at cannot move backwards")
    return (
        incoming.updated_at - existing.updated_at
        >= _DIRTY_CHECKPOINT_INTERVAL
    )


def _incident_transition_occurred_at(
    transition: IncidentTransition,
) -> datetime:
    occurred_at = (
        transition.incident.confirmed_at
        if transition.transition_type.value == "OPEN"
        else transition.incident.resolved_at
    )
    if occurred_at is None:
        raise RuntimeError("Incident publication lost occurredAt")
    return occurred_at


def _publication_identity(
    transition: ParkingTransition | IncidentTransition,
) -> tuple[str, str, int]:
    if isinstance(transition, ParkingTransition):
        return (
            "ParkingEpisode",
            str(transition.parking_episode_id),
            transition.publication_revision,
        )
    return (
        "Incident",
        str(transition.incident.incident_id),
        transition.incident.publication_revision,
    )


def _publication_order(
    transition: ParkingTransition | IncidentTransition | SessionExitTransition,
) -> tuple[datetime, int, str, str]:
    """여러 aggregate를 original occurredAt·revision 순으로 결정화한다."""

    if isinstance(transition, ParkingTransition):
        occurred_at = transition.occurred_at
        revision = transition.publication_revision
        aggregate_type = "ParkingEpisode"
        aggregate_id = str(transition.parking_episode_id)
    elif isinstance(transition, IncidentTransition):
        occurred_at = _incident_transition_occurred_at(transition)
        revision = transition.incident.publication_revision
        aggregate_type = "Incident"
        aggregate_id = str(transition.incident.incident_id)
    else:
        occurred_at = transition.occurred_at
        revision = transition.publication_revision
        aggregate_type = "ParkingSession"
        aggregate_id = str(transition.parking_session_id)
    return occurred_at, revision, aggregate_type, aggregate_id


def _validate_prepared_publication(
    prepared: PreparedPublication,
    *,
    aggregate_type: str,
    aggregate_id: str,
    publication_revision: int,
    transition_type: str,
) -> PreparedPublication:
    """Wire adapter가 domain transition identity를 바꾸지 않았는지 확인한다.

    destination·payload·delivery/idempotency identity는 outbound 계약의
    책임이다. 여기서는 pending fact를 완료 처리하기 전에 local aggregate
    identity와 revision·transition만 일치시킨다.
    """

    if not isinstance(prepared, PreparedPublication):
        raise TypeError("publication preparer must return PreparedPublication")
    expected = (
        aggregate_type,
        aggregate_id,
        publication_revision,
        transition_type,
    )
    actual = (
        prepared.aggregate_type,
        prepared.aggregate_id,
        prepared.publication_revision,
        prepared.transition_type,
    )
    if actual != expected:
        raise RuntimeError(
            "prepared publication envelope does not match domain transition: "
            f"expected={expected!r}, actual={actual!r}"
        )
    return prepared

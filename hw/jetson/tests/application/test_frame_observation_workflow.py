"""FrameObservationWorkflow의 Unit of Work·출차 ACK 경계 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.application.frame_observation_workflow import FrameObservationWorkflow
from src.application.pending_handoff_workflow import PendingHandoffWorkflow
from src.application.physical_presence_workflow import (
    ABSENCE_WITHOUT_EXIT_EVIDENCE,
    PHYSICAL_VEHICLE_LEFT,
    SESSION_EXITED,
    UnfinishedPhysicalVehicleScopeError,
)
from src.application.session_observation_workflow import SessionObservationResult
from src.communication.outbox import PreparedPublication
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    AssignmentState,
    BlockingRelation,
    BlockingRelationId,
    BlockingRelationState,
    EgressAisleId,
    Incident,
    IncidentId,
    IncidentKey,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingPipelineResult,
    ParkingState,
    ParkingTransition,
    ParkingTransitionType,
    ZoneId,
)
from src.parking.parking_episode_tracker import MOVEMENT_CONFIRMED
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.models import (
    ContextBinding,
    ContextBindingId,
    ContextBindingState,
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalExitEvidence,
    PhysicalPresenceState,
    PhysicalTerminationOrigin,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.aggregate_repositories import (
    BlockingRelationRepository,
    ParkingEpisodeRepository,
)
from src.storage.database import open_database
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
    PendingHandoffRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleAbsenceProgress,
    PhysicalVehicleId,
    PhysicalVehicleState,
    TrackingBatch,
    VehicleId,
)


T0 = datetime(2026, 8, 2, 16, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(seconds=5)
VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000011")
)
SUBJECT_VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000012")
)
ATTEMPT_ID = EntryAttemptId(
    UUID("20000000-0000-4000-8000-000000000011")
)
BINDING_ID = ContextBindingId(
    UUID("30000000-0000-4000-8000-000000000011")
)
EPISODE_ID = ParkingEpisodeId(
    UUID("40000000-0000-4000-8000-000000000011")
)
SESSION_ID = ParkingSessionId(55)
INCIDENT_ID = IncidentId(
    UUID("50000000-0000-4000-8000-000000000011")
)
BLOCKING_RELATION_ID = BlockingRelationId(
    UUID("60000000-0000-4000-8000-000000000011")
)

OBSERVED_T0 = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=T0,
)
OBSERVED_T1 = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=T1,
)
ABSENT = ObservationStatus(
    state=ObservationState.UNKNOWN,
    reason=ObservationReason.TRACK_LOST,
    last_reliable_observed_at=T0,
)


class _SessionWorkflow:
    def __init__(
        self,
        *,
        ensure_vehicle: bool,
        result: SessionObservationResult | None = None,
    ) -> None:
        self.ensure_vehicle = ensure_vehicle
        self.result = result or SessionObservationResult(
            session_contexts={},
            entry_attempt_ids={},
        )
        self.runtime_revision = 0

    def checkpoint_state(self) -> int:
        return self.runtime_revision

    def restore_state(self, checkpoint: int) -> None:
        self.runtime_revision = checkpoint

    def apply(self, _batch, *, connection) -> SessionObservationResult:
        self.runtime_revision += 1
        if self.ensure_vehicle:
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
        return self.result


class _ParkingPipeline:
    def __init__(
        self,
        *,
        process_result: ParkingPipelineResult,
        exit_result: ParkingPipelineResult | None = None,
    ) -> None:
        self.process_result = process_result
        self.exit_result = exit_result or _empty_result()
        self.runtime_revision = 0
        self.exit_reasons: list[str] = []
        self.exit_zone_traversal = True
        self.restored_episodes: tuple[ParkingEpisode, ...] = ()
        self.restored_relations = ()
        self._terminated_traversal_vehicle_ids: set[PhysicalVehicleId] = set()

    def checkpoint_state(self):
        return (
            self.runtime_revision,
            self.restored_episodes,
            self.restored_relations,
            frozenset(self._terminated_traversal_vehicle_ids),
        )

    def restore_state(self, checkpoint) -> None:
        (
            self.runtime_revision,
            self.restored_episodes,
            self.restored_relations,
            terminated,
        ) = checkpoint
        self._terminated_traversal_vehicle_ids = set(terminated)

    def restore_active(
        self,
        *,
        zone_visits,
        parking_episodes,
        incidents,
        blocking_relations,
    ) -> None:
        assert zone_visits == ()
        assert incidents == ()
        self.restored_episodes = parking_episodes
        self.restored_relations = blocking_relations

    def process(self, _batch, **_correlations) -> ParkingPipelineResult:
        self.runtime_revision += 1
        return self.process_result

    def exit_zone_traversal_observed(self, physical_vehicle_id) -> bool:
        assert physical_vehicle_id == VEHICLE_ID
        if physical_vehicle_id in self._terminated_traversal_vehicle_ids:
            # 실제 ParkingPipeline과 마찬가지로, physical_exit()이 이 차량의
            # zone visit을 이미 종료시켰다면 더 이상 통과를 관측할 수 없다.
            # 프로덕션이 읽기/physical_exit 호출 순서를 뒤집으면 이 double도
            # False를 반환해 회귀를 드러낸다.
            return False
        return self.exit_zone_traversal

    def physical_exit(
        self,
        *,
        physical_vehicle_id,
        observed_at,
        incident_termination_reason,
    ) -> ParkingPipelineResult:
        assert physical_vehicle_id == VEHICLE_ID
        assert observed_at == T1
        self.runtime_revision += 1
        self._terminated_traversal_vehicle_ids.add(physical_vehicle_id)
        self.exit_reasons.append(incident_termination_reason)
        restored = next(
            (
                episode
                for episode in self.restored_episodes
                if episode.physical_vehicle_id == physical_vehicle_id
            ),
            None,
        )
        if restored is not None:
            self.restored_episodes = tuple(
                episode
                for episode in self.restored_episodes
                if episode.episode_id != restored.episode_id
            )
            ended = replace(
                restored,
                state=ParkingState.ENDED,
                record_version=restored.record_version + 1,
                ended_at=observed_at,
                termination_reason="PHYSICAL_EXIT",
                updated_at=observed_at,
            )
            return ParkingPipelineResult(
                zone_visit_updates=(),
                parking_episode_updates=(ended,),
                incident_transitions=(),
            )
        return self.exit_result


class _PublicationPreparer:
    def __init__(
        self,
        *,
        fail: bool = False,
        invalid_envelope: bool = False,
    ) -> None:
        self.fail = fail
        self.invalid_envelope = invalid_envelope

    def prepare_parking(
        self,
        transition: ParkingTransition,
    ) -> PreparedPublication:
        return self._prepare(
            aggregate_type="ParkingEpisode",
            aggregate_id=str(transition.parking_episode_id),
            revision=transition.publication_revision,
            transition_type=transition.transition_type.value,
        )

    def prepare_incident(
        self,
        transition: IncidentTransition,
    ) -> PreparedPublication:
        return self._prepare(
            aggregate_type="Incident",
            aggregate_id=str(transition.incident.incident_id),
            revision=transition.incident.publication_revision,
            transition_type=transition.transition_type.value,
        )

    def prepare_session_exit(self, transition) -> PreparedPublication:
        return self._prepare(
            aggregate_type="ParkingSession",
            aggregate_id=str(transition.parking_session_id),
            revision=transition.publication_revision,
            transition_type="SESSION_EXIT",
        )

    def _prepare(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        revision: int,
        transition_type: str,
    ) -> PreparedPublication:
        if self.fail:
            raise RuntimeError("wire adapter failed")
        if self.invalid_envelope:
            aggregate_id = f"{aggregate_id}-wrong"
        identity = f"{aggregate_type}:{aggregate_id}:{revision}"
        return PreparedPublication(
            delivery_id=identity,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            destination="backend-contract-pending",
            publication_revision=revision,
            transition_type=transition_type,
            payload=identity.encode("utf-8"),
            idempotency_key=identity,
        )


def _active_vehicle() -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED_T0,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
    )


def _confirmed_absent_vehicle() -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=ABSENT,
        absence_trusted_seconds=5.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        absence_confirmed_at=T1,
        record_version=1,
        created_at=T0,
        updated_at=T1,
    )


def _context() -> SessionContext:
    return SessionContext(
        parking_session_id=SESSION_ID,
        vehicle_id=VehicleId(77),
        is_electric=True,
        is_disabled_vehicle=False,
    )


def _parked_result() -> ParkingPipelineResult:
    assignment = ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        zone_id=ZoneId(7),
        representative_footprint=(
            (0.1, 0.1),
            (0.2, 0.1),
            (0.2, 0.2),
            (0.1, 0.2),
        ),
        confidence=0.9,
        last_stable_at=T1,
    )
    episode = ParkingEpisode(
        episode_id=EPISODE_ID,
        physical_vehicle_id=VEHICLE_ID,
        parking_session_id=SESSION_ID,
        state=ParkingState.PARKED,
        observation=OBSERVED_T1,
        stationary_trusted_seconds=5.0,
        movement_trusted_seconds=0.0,
        parking_confirmation_seconds=5.0,
        movement_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=1.0,
        last_signal=MotionSignal.STATIONARY,
        assignment=assignment,
        parked_at=T1,
        record_version=2,
        publication_revision=1,
        created_at=T0,
        updated_at=T1,
    )
    transition = ParkingTransition(
        transition_type=ParkingTransitionType.PARKED,
        parking_episode_id=EPISODE_ID,
        physical_vehicle_id=VEHICLE_ID,
        parking_session_id=SESSION_ID,
        publication_revision=1,
        occurred_at=T1,
        assignment=assignment,
    )
    return ParkingPipelineResult(
        zone_visit_updates=(),
        parking_episode_updates=(episode,),
        parking_transitions=(transition,),
        incident_transitions=(),
    )


def _empty_result() -> ParkingPipelineResult:
    return ParkingPipelineResult(
        zone_visit_updates=(),
        parking_episode_updates=(),
        incident_transitions=(),
    )


def _matched_attempt() -> EntryMatchAttempt:
    return EntryMatchAttempt(
        entry_attempt_id=ATTEMPT_ID,
        match_state=EntryMatchState.MATCHED,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=1,
        matched_physical_vehicle_id=VEHICLE_ID,
        authoritative_session_id=SESSION_ID,
        authoritative_context=_context(),
        match_terminated_at=T1,
        match_deadline_at=T1,
        record_version=2,
        created_at=T0,
        updated_at=T1,
    )


def _blocking_relation_result() -> ParkingPipelineResult:
    relation = BlockingRelation(
        blocking_relation_id=BLOCKING_RELATION_ID,
        subject_physical_vehicle_id=SUBJECT_VEHICLE_ID,
        victim_physical_vehicle_id=VEHICLE_ID,
        egress_zone_id=EgressAisleId(101),
        state=BlockingRelationState.CANDIDATE,
        observation=OBSERVED_T1,
        confirm_trusted_seconds=0.0,
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=2.0,
        clear_duration_seconds=3.0,
        record_version=1,
        created_at=T1,
        updated_at=T1,
    )
    return ParkingPipelineResult(
        zone_visit_updates=(),
        parking_episode_updates=(),
        blocking_relation_updates=(relation,),
        incident_transitions=(),
    )


def _batch(*, departure: bool = False) -> TrackingBatch:
    return TrackingBatch(
        camera_id="camera-1",
        frame_id=1,
        observed_at=T1,
        vehicles=(),
        ended_track_segment_ids=(),
        unobserved_physical_vehicle_ids=(VEHICLE_ID,) if departure else (),
        absence_progress=(
            (
                PhysicalVehicleAbsenceProgress(
                    physical_vehicle_id=VEHICLE_ID,
                    trusted_seconds=5.0,
                    confirmed_at=T1,
                ),
            )
            if departure
            else ()
        ),
        observation=OBSERVED_T1,
        full_area_observed=True,
        all_detections_tracked=True,
        not_present_confirmed_vehicle_ids=(VEHICLE_ID,) if departure else (),
    )


def _workflow(session, parking, preparer) -> FrameObservationWorkflow:
    return FrameObservationWorkflow(
        session_workflow=session,
        parking_pipeline=parking,
        context_binding_coordinator=ContextBindingCoordinator(),
        publication_preparer=preparer,
    )


def _outbox_count(connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])


def test_frame_rolls_back_session_parking_outbox_and_runtime_then_retries(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "frame.db")
    session = _SessionWorkflow(ensure_vehicle=True)
    parking = _ParkingPipeline(process_result=_parked_result())
    preparer = _PublicationPreparer(fail=True)
    workflow = _workflow(session, parking, preparer)
    try:
        with pytest.raises(RuntimeError, match="wire adapter failed"):
            workflow.process(_batch(), connection=connection)

        assert PhysicalVehicleRepository(connection).get(VEHICLE_ID) is None
        assert ParkingEpisodeRepository(connection).get(EPISODE_ID) is None
        assert _outbox_count(connection) == 0
        assert session.runtime_revision == 0
        assert parking.runtime_revision == 0

        preparer.fail = False
        result = workflow.process(_batch(), connection=connection)

        assert result.parking_result.parking_episode_updates
        assert PhysicalVehicleRepository(connection).get(VEHICLE_ID) is not None
        assert ParkingEpisodeRepository(connection).get(EPISODE_ID) is not None
        assert _outbox_count(connection) == 1
        assert session.runtime_revision == 1
        assert parking.runtime_revision == 1
    finally:
        connection.close()


def test_frame_result_exposes_only_committed_entry_match_updates(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "entry-match-result.db")
    matched = _matched_attempt()
    session = _SessionWorkflow(
        ensure_vehicle=True,
        result=SessionObservationResult(
            session_contexts={},
            entry_attempt_ids={VEHICLE_ID: ATTEMPT_ID},
            entry_match_updates=(matched,),
        ),
    )
    workflow = _workflow(
        session,
        _ParkingPipeline(process_result=_empty_result()),
        _PublicationPreparer(),
    )
    try:
        result = workflow.process(_batch(), connection=connection)

        assert result.entry_match_updates == (matched,)
    finally:
        connection.close()


def test_frame_persists_and_restart_restores_active_blocking_relation(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "blocking-relation-frame.db")
    session = _SessionWorkflow(ensure_vehicle=True)
    parking = _ParkingPipeline(process_result=_blocking_relation_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                replace(
                    _active_vehicle(),
                    physical_vehicle_id=SUBJECT_VEHICLE_ID,
                )
            )

        workflow.process(_batch(), connection=connection)

        persisted = BlockingRelationRepository(connection).get(
            BLOCKING_RELATION_ID
        )
        assert persisted is not None
        assert persisted.egress_zone_id == EgressAisleId(101)

        recovery = workflow.recover_runtime(
            connection=connection,
            recovered_at=T1 + timedelta(seconds=1),
        )
        assert recovery.blocking_relation_count == 1
        assert parking.restored_relations == (persisted,)
    finally:
        connection.close()


def test_local_incident_open_reserves_evidence_then_late_publication_binds_it(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "incident-evidence.db")
    local_open = Incident(
        incident_id=INCIDENT_ID,
        key=IncidentKey.for_physical_vehicle(VEHICLE_ID, "AISLE_BLOCK"),
        physical_vehicle_id=VEHICLE_ID,
        state=IncidentState.OPEN,
        observation=OBSERVED_T1,
        confirm_trusted_seconds=5.0,
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=5.0,
        clear_duration_seconds=3.0,
        record_version=1,
        publication_revision=0,
        first_observed_at=T0,
        confirmed_at=T1,
        created_at=T0,
        updated_at=T1,
        trusted_sample_max_gap_seconds=1.0,
    )
    parking = _ParkingPipeline(
        process_result=ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(),
            incident_updates=(local_open,),
            incident_transitions=(),
        )
    )
    workflow = _workflow(
        _SessionWorkflow(ensure_vehicle=True),
        parking,
        _PublicationPreparer(),
    )
    try:
        first_result = workflow.process(_batch(), connection=connection)

        assert len(first_result.evidence_capture_intents) == 1
        artifacts = EvidenceArtifactRepository(connection).list_for_incident(
            INCIDENT_ID
        )
        assert len(artifacts) == 1
        assert artifacts[0].publication_revision is None

        published_open = replace(
            local_open,
            entry_attempt_id=ATTEMPT_ID,
            publication_revision=1,
            record_version=2,
            updated_at=T1 + timedelta(seconds=1),
        )
        parking.process_result = ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(),
            incident_updates=(published_open,),
            incident_transitions=(
                IncidentTransition(
                    transition_type=IncidentTransitionType.OPEN,
                    incident=published_open,
                ),
            ),
        )

        second_result = workflow.process(_batch(), connection=connection)

        rebound = EvidenceArtifactRepository(connection).list_for_incident(
            INCIDENT_ID
        )
        assert second_result.evidence_capture_intents == ()
        assert len(rebound) == 1
        assert rebound[0].evidence_id == artifacts[0].evidence_id
        assert rebound[0].publication_revision == 1
        assert _outbox_count(connection) == 1
    finally:
        connection.close()


def test_timer_only_parking_updates_use_ten_second_dirty_checkpoint(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "dirty-checkpoint.db")
    session = _SessionWorkflow(ensure_vehicle=True)
    parking = _ParkingPipeline(process_result=_parked_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        workflow.process(_batch(), connection=connection)
        initial = ParkingEpisodeRepository(connection).get(EPISODE_ID)
        assert initial is not None

        near_at = T1 + timedelta(seconds=1)
        near = replace(
            initial,
            observation=ObservationStatus(
                state=ObservationState.OBSERVED,
                last_reliable_observed_at=near_at,
            ),
            stationary_trusted_seconds=6.0,
            record_version=initial.record_version + 1,
            updated_at=near_at,
        )
        parking.process_result = ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(near,),
            incident_transitions=(),
        )
        workflow.process(_batch(), connection=connection)
        assert ParkingEpisodeRepository(connection).get(EPISODE_ID) == initial

        due_at = T1 + timedelta(seconds=10)
        due = replace(
            near,
            observation=ObservationStatus(
                state=ObservationState.OBSERVED,
                last_reliable_observed_at=due_at,
            ),
            stationary_trusted_seconds=15.0,
            record_version=near.record_version + 9,
            updated_at=due_at,
        )
        parking.process_result = ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(due,),
            incident_transitions=(),
        )
        workflow.process(_batch(), connection=connection)

        assert ParkingEpisodeRepository(connection).get(EPISODE_ID) == due
        assert _outbox_count(connection) == 1
    finally:
        connection.close()


def test_pending_parking_facts_materialize_with_outbox_in_same_frame_uow(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "pending-frame.db")
    terminal = replace(
        _parked_result().parking_episode_updates[0],
        parking_session_id=None,
        state=ParkingState.ENDED,
        last_signal=MotionSignal.MOVING,
        publication_revision=0,
        record_version=3,
        ended_at=T1,
        termination_reason=MOVEMENT_CONFIRMED,
    )
    session = _SessionWorkflow(
        ensure_vehicle=False,
        result=SessionObservationResult(
            session_contexts={VEHICLE_ID: _context()},
            entry_attempt_ids={},
        ),
    )
    workflow = _workflow(
        session,
        _ParkingPipeline(process_result=_empty_result()),
        _PublicationPreparer(),
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            ParkingEpisodeRepository(connection).add(terminal)
            PendingHandoffWorkflow().capture(
                ParkingPipelineResult(
                    zone_visit_updates=(),
                    parking_episode_updates=(terminal,),
                    incident_transitions=(),
                ),
                connection=connection,
            )

        result = workflow.process(_batch(), connection=connection)

        assert [
            transition.transition_type
            for transition in result.parking_result.parking_transitions
        ] == [
            ParkingTransitionType.PARKED,
            ParkingTransitionType.UNPARKED,
        ]
        assert _outbox_count(connection) == 2
        assert PendingHandoffRepository(connection).list_waiting() == ()
        states = connection.execute(
            "SELECT workflow_state FROM pending_handoffs ORDER BY original_occurred_at_us"
        ).fetchall()
        assert [row[0] for row in states] == ["MATERIALIZED", "MATERIALIZED"]
        persisted = ParkingEpisodeRepository(connection).get(EPISODE_ID)
        assert persisted is not None
        assert persisted.parking_session_id == SESSION_ID
        assert persisted.publication_revision == 2
    finally:
        connection.close()


def test_invalid_prepared_envelope_rolls_back_pending_fact_and_runtime(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "invalid-envelope.db")
    terminal = replace(
        _parked_result().parking_episode_updates[0],
        parking_session_id=None,
        state=ParkingState.ENDED,
        last_signal=MotionSignal.MOVING,
        publication_revision=0,
        record_version=3,
        ended_at=T1,
        termination_reason=MOVEMENT_CONFIRMED,
    )
    session = _SessionWorkflow(
        ensure_vehicle=False,
        result=SessionObservationResult(
            session_contexts={VEHICLE_ID: _context()},
            entry_attempt_ids={},
        ),
    )
    parking = _ParkingPipeline(process_result=_empty_result())
    preparer = _PublicationPreparer(invalid_envelope=True)
    workflow = _workflow(session, parking, preparer)
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            ParkingEpisodeRepository(connection).add(terminal)
            PendingHandoffWorkflow().capture(
                ParkingPipelineResult(
                    zone_visit_updates=(),
                    parking_episode_updates=(terminal,),
                    incident_transitions=(),
                ),
                connection=connection,
            )

        waiting_before = PendingHandoffRepository(connection).list_waiting()
        with pytest.raises(
            RuntimeError,
            match="prepared publication envelope does not match",
        ):
            workflow.process(_batch(), connection=connection)

        assert ParkingEpisodeRepository(connection).get(EPISODE_ID) == terminal
        assert PendingHandoffRepository(connection).list_waiting() == waiting_before
        assert _outbox_count(connection) == 0
        assert session.runtime_revision == 0
        assert parking.runtime_revision == 0

        preparer.invalid_envelope = False
        workflow.process(_batch(), connection=connection)

        assert PendingHandoffRepository(connection).list_waiting() == ()
        assert _outbox_count(connection) == 2
        assert session.runtime_revision == 1
        assert parking.runtime_revision == 1
    finally:
        connection.close()


def test_session_exit_failure_rolls_back_then_commit_is_idempotently_ackable(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "departure.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    preparer = _PublicationPreparer(fail=True)
    workflow = _workflow(session, parking, preparer)
    try:
        _seed_bound_departure(connection)

        with pytest.raises(RuntimeError, match="wire adapter failed"):
            workflow.process(_batch(departure=True), connection=connection)

        assert PhysicalVehicleRepository(connection).get(
            VEHICLE_ID
        ).state is PhysicalVehicleState.ACTIVE
        assert ContextBindingRepository(connection).get(
            BINDING_ID
        ).state is ContextBindingState.BOUND
        assert ParkingSessionMirrorRepository(connection).get(
            SESSION_ID
        ).physical_presence_state is PhysicalPresenceState.INSIDE
        assert _outbox_count(connection) == 0
        assert session.runtime_revision == 0
        assert parking.runtime_revision == 0

        preparer.fail = False
        committed = workflow.process(_batch(departure=True), connection=connection)

        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        binding = ContextBindingRepository(connection).get(BINDING_ID)
        mirror = ParkingSessionMirrorRepository(connection).get(SESSION_ID)
        assert committed.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle.state is PhysicalVehicleState.RETIRED
        assert vehicle.termination_reason == SESSION_EXITED
        assert binding.state is ContextBindingState.ENDED
        assert mirror.physical_presence_state is PhysicalPresenceState.EXITED
        assert (
            mirror.physical_termination_origin
            is PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
        )
        assert mirror.physical_exit_evidence is PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL
        assert mirror.exited_at == T1
        assert _outbox_count(connection) == 1
        assert parking.exit_reasons == [SESSION_EXITED, SESSION_EXITED]

        repeated = workflow.process(_batch(departure=True), connection=connection)
        assert repeated.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert _outbox_count(connection) == 1
        assert parking.exit_reasons == [SESSION_EXITED, SESSION_EXITED]
    finally:
        connection.close()


def test_admin_closed_session_keeps_admin_end_and_still_records_physical_exit(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "admin-closed-departure.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    admin_closed_at = T0 + timedelta(seconds=1)
    try:
        _seed_bound_departure(connection)
        with UnitOfWork(connection):
            binding_repository = ContextBindingRepository(connection)
            mirror_repository = ParkingSessionMirrorRepository(connection)
            binding = binding_repository.get(BINDING_ID)
            mirror = mirror_repository.get(SESSION_ID)
            assert binding is not None and mirror is not None
            ended = ContextBindingCoordinator().end(
                binding,
                ended_at=admin_closed_at,
                reason="ADMIN_CLOSED",
            )
            binding_repository.save(
                ended,
                expected_record_version=binding.record_version,
            )
            closed = replace(
                mirror,
                administrative_state=SessionAdministrativeState.CLOSED,
                record_version=mirror.record_version + 1,
                updated_at=admin_closed_at,
            )
            mirror_repository.save(
                closed,
                expected_record_version=mirror.record_version,
            )

        committed = workflow.process(
            _batch(departure=True),
            connection=connection,
        )

        binding = ContextBindingRepository(connection).get(BINDING_ID)
        mirror = ParkingSessionMirrorRepository(connection).get(SESSION_ID)
        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        assert committed.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle is not None
        assert vehicle.state is PhysicalVehicleState.RETIRED
        assert vehicle.termination_reason == SESSION_EXITED
        assert binding is not None
        assert binding.state is ContextBindingState.ENDED
        assert binding.termination_reason == "ADMIN_CLOSED"
        assert binding.ended_at == admin_closed_at
        assert mirror is not None
        assert mirror.administrative_state is SessionAdministrativeState.CLOSED
        assert mirror.physical_presence_state is PhysicalPresenceState.EXITED
        assert (
            mirror.physical_termination_origin
            is PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
        )
        assert mirror.physical_exit_evidence is PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL
        assert mirror.exited_at == T1
        assert parking.exit_reasons == [SESSION_EXITED]
        assert _outbox_count(connection) == 1

        repeated = workflow.process(
            _batch(departure=True),
            connection=connection,
        )
        assert repeated.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert _outbox_count(connection) == 1
        assert parking.exit_reasons == [SESSION_EXITED]
    finally:
        connection.close()


def test_traversal_read_must_happen_before_physical_exit_terminates_it(
    tmp_path: Path,
) -> None:
    """읽기 순서 회귀 고정(565).

    ``exit_zone_traversal_observed()``는 ``physical_exit()``이 zone visit을
    종료시키기 **전에** 호출돼야 한다. ``_ParkingPipeline`` double은
    ``physical_exit()``이 호출된 차량에 대해 이후 ``exit_zone_traversal_observed``가
    False를 반환하도록 실제 파이프라인의 동작을 그대로 모사한다. 그래서
    ``PhysicalPresenceWorkflow.plan_departure``가 이 순서를 뒤집으면(먼저
    ``physical_exit``을 호출한 뒤 통과 여부를 읽으면) 이 테스트가 실패한다 —
    SessionExit이 전혀 발행되지 않고 mirror가 EXITED로 갱신되지 않는다.
    """

    connection = open_database(tmp_path / "traversal-read-order.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        _seed_bound_departure(connection)

        committed = workflow.process(_batch(departure=True), connection=connection)

        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        mirror = ParkingSessionMirrorRepository(connection).get(SESSION_ID)
        assert committed.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle.termination_reason == SESSION_EXITED
        assert mirror.physical_presence_state is PhysicalPresenceState.EXITED
        assert (
            mirror.physical_exit_evidence is PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL
        )
        assert _outbox_count(connection) == 1
    finally:
        connection.close()


def test_same_batch_late_allow_is_historical_correlation_before_departure(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "same-batch-late-allow.db")
    attempt = EntryMatchAttempt(
        entry_attempt_id=ATTEMPT_ID,
        match_state=EntryMatchState.MATCHED,
        decision_state=EntryDecisionState.REVIEW_ALLOW,
        decision_revision=1,
        matched_physical_vehicle_id=VEHICLE_ID,
        authoritative_session_id=SESSION_ID,
        authoritative_context=_context(),
        match_terminated_at=T0,
        match_deadline_at=T1,
        record_version=2,
        created_at=T0,
        updated_at=T1,
    )
    mirror = ParkingSessionMirror(
        parking_session_id=SESSION_ID,
        entry_attempt_id=ATTEMPT_ID,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
        physical_observation=ABSENT,
        context_revision=1,
        last_context=_context(),
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T1,
    )
    session = _SessionWorkflow(
        ensure_vehicle=False,
        result=SessionObservationResult(
            session_contexts={},
            entry_attempt_ids={VEHICLE_ID: ATTEMPT_ID},
            historical_attempts=(attempt,),
        ),
    )
    parking = _ParkingPipeline(process_result=_empty_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                _confirmed_absent_vehicle()
            )
            EntryMatchAttemptRepository(connection).add(attempt)
            ParkingSessionMirrorRepository(connection).add(mirror)

        committed = workflow.process(
            _batch(departure=True),
            connection=connection,
        )

        persisted_vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        persisted_mirror = ParkingSessionMirrorRepository(connection).get(SESSION_ID)
        assert committed.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert persisted_vehicle is not None
        assert persisted_vehicle.state is PhysicalVehicleState.RETIRED
        assert persisted_vehicle.termination_reason == SESSION_EXITED
        assert persisted_mirror is not None
        assert persisted_mirror.physical_vehicle_id == VEHICLE_ID
        assert persisted_mirror.physical_presence_state is PhysicalPresenceState.EXITED
        assert persisted_mirror.exited_at == T1
        assert ContextBindingRepository(connection).list_active() == ()
        assert parking.exit_reasons == [SESSION_EXITED]
        assert _outbox_count(connection) == 1
    finally:
        connection.close()


def test_unbound_departure_retires_locally_without_session_exit(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "unbound-departure.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                _confirmed_absent_vehicle()
            )

        result = workflow.process(_batch(departure=True), connection=connection)

        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        assert result.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle.state is PhysicalVehicleState.RETIRED
        assert vehicle.termination_reason == PHYSICAL_VEHICLE_LEFT
        assert parking.exit_reasons == [PHYSICAL_VEHICLE_LEFT]
        assert _outbox_count(connection) == 0
    finally:
        connection.close()


def test_bound_absence_without_exit_zone_traversal_does_not_publish_session_exit(
    tmp_path: Path,
) -> None:
    """출차 구역 통과가 관측되지 않은 부재는 백엔드에 발행하지 않는다(565).

    로컬 수명주기는 그대로 닫는다 — 부재 확정 사실은 forget ACK까지 매
    프레임 반복되므로 소비하지 않으면 무한 반복이고, BOUND binding을 남기면
    RETIRE 자체가 UnfinishedPhysicalVehicleScopeError로 실패한다.
    """

    connection = open_database(tmp_path / "departure-no-evidence.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    parking.exit_zone_traversal = False
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        _seed_bound_departure(connection)

        result = workflow.process(_batch(departure=True), connection=connection)

        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        binding = ContextBindingRepository(connection).get(BINDING_ID)
        mirror = ParkingSessionMirrorRepository(connection).get(SESSION_ID)

        # 로컬 수명주기는 현행 그대로 닫힌다.
        assert result.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle.state is PhysicalVehicleState.RETIRED
        assert binding.state is ContextBindingState.ENDED
        # Incident 종료 사유(API 7 wire 노출)는 바뀌지 않는다.
        assert parking.exit_reasons == [SESSION_EXITED]
        # 진단용 차량 종료 사유만 구분된다.
        assert vehicle.termination_reason == ABSENCE_WITHOUT_EXIT_EVIDENCE
        # 백엔드로는 아무것도 나가지 않고 mirror는 손대지 않는다.
        assert _outbox_count(connection) == 0
        assert mirror.physical_presence_state is PhysicalPresenceState.INSIDE
        assert mirror.physical_termination_origin is None
        assert mirror.physical_exit_evidence is None
        assert mirror.exited_at is None
        assert mirror.publication_revision == 0
    finally:
        connection.close()


def test_unbound_absence_without_exit_zone_traversal_records_absence_reason(
    tmp_path: Path,
) -> None:
    """session이 없는 차량도 통과 여부를 평가해 사유로 남긴다(565).

    나중에 세션이 늦게 붙을 수 있으므로, 늦은 correlation이 읽을 수 있도록
    mirror 유무와 무관하게 사유를 영속한다.
    """

    connection = open_database(tmp_path / "unbound-no-evidence.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    parking.exit_zone_traversal = False
    workflow = _workflow(session, parking, _PublicationPreparer())
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                _confirmed_absent_vehicle()
            )

        result = workflow.process(_batch(departure=True), connection=connection)

        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        assert result.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert vehicle.state is PhysicalVehicleState.RETIRED
        assert vehicle.termination_reason == ABSENCE_WITHOUT_EXIT_EVIDENCE
        # Incident 종료 사유는 현행 값을 유지한다.
        assert parking.exit_reasons == [PHYSICAL_VEHICLE_LEFT]
        assert _outbox_count(connection) == 0
    finally:
        connection.close()


def test_departure_does_not_retire_when_durable_child_was_not_hydrated(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "unhydrated-child.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    episode = _parked_result().parking_episode_updates[0]
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                _confirmed_absent_vehicle()
            )
            ParkingEpisodeRepository(connection).add(episode)

        with pytest.raises(
            UnfinishedPhysicalVehicleScopeError,
            match="ParkingEpisode",
        ):
            workflow.process(_batch(departure=True), connection=connection)

        assert PhysicalVehicleRepository(connection).get(
            VEHICLE_ID
        ).state is PhysicalVehicleState.ACTIVE
        assert ParkingEpisodeRepository(connection).get(
            EPISODE_ID
        ).state is ParkingState.PARKED
        assert parking.runtime_revision == 0

        recovery = workflow.recover_runtime(connection=connection)
        assert recovery.parking_episode_count == 1
        assert recovery.completed_departure_count == 1
        assert recovery.active_physical_vehicles == ()
        assert PhysicalVehicleRepository(connection).get(
            VEHICLE_ID
        ).state is PhysicalVehicleState.RETIRED
        assert ParkingEpisodeRepository(connection).get(
            EPISODE_ID
        ).state is ParkingState.ENDED
        committed = workflow.process(
            _batch(departure=True),
            connection=connection,
        )

        assert committed.retired_physical_vehicle_ids == (VEHICLE_ID,)
        assert PhysicalVehicleRepository(connection).get(
            VEHICLE_ID
        ).state is PhysicalVehicleState.RETIRED
        assert ParkingEpisodeRepository(connection).get(
            EPISODE_ID
        ).state is ParkingState.ENDED
    finally:
        connection.close()


def test_restart_marks_remaining_active_observations_unknown_without_timer_gain(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "restart-unknown.db")
    session = _SessionWorkflow(ensure_vehicle=False)
    parking = _ParkingPipeline(process_result=_empty_result())
    workflow = _workflow(session, parking, _PublicationPreparer())
    active_episode = replace(
        _parked_result().parking_episode_updates[0],
        parking_session_id=None,
        publication_revision=0,
    )
    mirror = ParkingSessionMirror(
        parking_session_id=SESSION_ID,
        physical_vehicle_id=VEHICLE_ID,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=OBSERVED_T0,
        context_revision=0,
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T0,
    )
    recovered_at = T1 + timedelta(minutes=5)
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            ParkingEpisodeRepository(connection).add(active_episode)
            ParkingSessionMirrorRepository(connection).add(mirror)

        recovery = workflow.recover_runtime(
            connection=connection,
            recovered_at=recovered_at,
        )

        assert recovery.completed_departure_count == 0
        assert len(recovery.active_physical_vehicles) == 1
        vehicle = PhysicalVehicleRepository(connection).get(VEHICLE_ID)
        episode = ParkingEpisodeRepository(connection).get(EPISODE_ID)
        recovered_mirror = ParkingSessionMirrorRepository(connection).get(
            SESSION_ID
        )
        assert vehicle is not None and episode is not None
        assert recovered_mirror is not None
        assert vehicle.observation.state is ObservationState.UNKNOWN
        assert vehicle.observation.reason is ObservationReason.PROCESS_RESTARTED
        assert episode.observation.state is ObservationState.UNKNOWN
        assert episode.observation.reason is ObservationReason.PROCESS_RESTARTED
        assert recovered_mirror.physical_observation.state is ObservationState.UNKNOWN
        assert (
            recovered_mirror.physical_observation.reason
            is ObservationReason.PROCESS_RESTARTED
        )
        assert vehicle.absence_trusted_seconds == 0.0
        assert episode.stationary_trusted_seconds == active_episode.stationary_trusted_seconds
        assert parking.restored_episodes == (episode,)
    finally:
        connection.close()


def _seed_bound_departure(connection) -> None:
    attempt = EntryMatchAttempt(
        entry_attempt_id=ATTEMPT_ID,
        match_state=EntryMatchState.MATCHED,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=0,
        matched_physical_vehicle_id=VEHICLE_ID,
        authoritative_session_id=SESSION_ID,
        authoritative_context=_context(),
        match_terminated_at=T0,
        match_deadline_at=T1,
        record_version=2,
        created_at=T0,
        updated_at=T0,
    )
    mirror = ParkingSessionMirror(
        parking_session_id=SESSION_ID,
        entry_attempt_id=ATTEMPT_ID,
        physical_vehicle_id=VEHICLE_ID,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=OBSERVED_T0,
        context_revision=0,
        last_context=_context(),
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T0,
    )
    binding = ContextBinding(
        context_binding_id=BINDING_ID,
        entry_attempt_id=ATTEMPT_ID,
        parking_session_id=SESSION_ID,
        physical_vehicle_id=VEHICLE_ID,
        state=ContextBindingState.BOUND,
        context_revision=0,
        context=_context(),
        record_version=1,
        bound_at=T0,
        updated_at=T0,
    )
    with UnitOfWork(connection):
        PhysicalVehicleRepository(connection).ensure(
            _confirmed_absent_vehicle()
        )
        EntryMatchAttemptRepository(connection).add(attempt)
        ParkingSessionMirrorRepository(connection).add(mirror)
        ContextBindingRepository(connection).add(binding)

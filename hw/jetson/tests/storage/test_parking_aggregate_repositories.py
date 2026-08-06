"""Parking aggregate SQLite repository의 round-trip·불변·원자성 회귀 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.domain.models import ObservationState, ObservationStatus
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
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingState,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.session.models import EntryAttemptId
from src.storage.aggregate_repositories import (
    BlockingRelationConflictError,
    BlockingRelationRepository,
    IncidentConflictError,
    IncidentRepository,
    ParkingEpisodeConflictError,
    ParkingEpisodeRepository,
    ZoneVisitConflictError,
    ZoneVisitRepository,
)
from src.storage.database import open_database
from src.storage.repositories import (
    OptimisticConcurrencyError,
    OutboxRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import TransactionStateError, UnitOfWork
from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


NOW = datetime(2026, 8, 2, 15, 0, 0, 123456, tzinfo=timezone.utc)
VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000001")
)
OTHER_VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000002")
)
VISIT_ID = ZoneVisitId(UUID("20000000-0000-4000-8000-000000000001"))
EPISODE_ID = ParkingEpisodeId(
    UUID("30000000-0000-4000-8000-000000000001")
)
INCIDENT_ID = IncidentId(UUID("40000000-0000-4000-8000-000000000001"))
RELATION_ID = BlockingRelationId(
    UUID("35000000-0000-4000-8000-000000000001")
)
ENTRY_ATTEMPT_ID = EntryAttemptId(
    UUID("50000000-0000-4000-8000-000000000001")
)

OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=NOW,
)


def _vehicle(
    physical_vehicle_id: PhysicalVehicleId = VEHICLE_ID,
) -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=physical_vehicle_id,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=4.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _visit() -> ZoneVisit:
    return ZoneVisit(
        visit_id=VISIT_ID,
        physical_vehicle_id=VEHICLE_ID,
        zone_id=ZoneId(7),
        zone_definition_version=ZoneDefinitionVersion(3),
        state=ZoneVisitState.ENTERING,
        observation=OBSERVED,
        entry_trusted_seconds=0.0,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.5,
        exit_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=0.75,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
        entered_candidate_at=NOW,
    )


def _episode() -> ParkingEpisode:
    return ParkingEpisode(
        episode_id=EPISODE_ID,
        physical_vehicle_id=VEHICLE_ID,
        state=ParkingState.STOP_PENDING,
        observation=OBSERVED,
        stationary_trusted_seconds=0.0,
        movement_trusted_seconds=0.0,
        parking_confirmation_seconds=10.0,
        movement_confirmation_seconds=2.0,
        trusted_sample_max_gap_seconds=0.8,
        last_signal=MotionSignal.STATIONARY,
        record_version=1,
        publication_revision=0,
        created_at=NOW,
        updated_at=NOW,
        assignment=_assignment(NOW),
    )


def _assignment(at: datetime) -> ParkingAssignment:
    return ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        zone_id=ZoneId(7),
        representative_footprint=(
            (0.1, 0.2),
            (0.4, 0.2),
            (0.4, 0.6),
            (0.1, 0.6),
        ),
        confidence=0.875,
        last_stable_at=at,
    )


def _incident() -> Incident:
    return Incident(
        incident_id=INCIDENT_ID,
        key=IncidentKey.for_physical_vehicle(VEHICLE_ID, "BAD_PARKING"),
        physical_vehicle_id=VEHICLE_ID,
        state=IncidentState.CANDIDATE,
        observation=OBSERVED,
        confirm_trusted_seconds=0.0,
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=2.0,
        clear_duration_seconds=3.0,
        trusted_sample_max_gap_seconds=0.9,
        record_version=1,
        publication_revision=0,
        first_observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def _blocking_relation() -> BlockingRelation:
    return BlockingRelation(
        blocking_relation_id=RELATION_ID,
        subject_physical_vehicle_id=OTHER_VEHICLE_ID,
        victim_physical_vehicle_id=VEHICLE_ID,
        egress_zone_id=EgressAisleId(101),
        source_parking_episode_id=EPISODE_ID,
        state=BlockingRelationState.CANDIDATE,
        observation=OBSERVED,
        confirm_trusted_seconds=0.0,
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=2.0,
        clear_duration_seconds=3.0,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def test_blocking_relation_round_trip_and_terminal_cardinality(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = BlockingRelationRepository(connection)
    relation = _blocking_relation()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            PhysicalVehicleRepository(connection).ensure(
                _vehicle(OTHER_VEHICLE_ID)
            )
            ParkingEpisodeRepository(connection).add(_episode())
            repository.add(relation)

        assert repository.get(RELATION_ID) == relation
        assert repository.list_active() == (relation,)

        duplicate = replace(
            relation,
            blocking_relation_id=BlockingRelationId(
                UUID("35000000-0000-4000-8000-000000000002")
            ),
        )
        with pytest.raises(BlockingRelationConflictError):
            with UnitOfWork(connection):
                repository.add(duplicate)

        confirmed_at = NOW + timedelta(seconds=2)
        blocking = replace(
            relation,
            state=BlockingRelationState.BLOCKING,
            confirm_trusted_seconds=2.0,
            confirmed_at=confirmed_at,
            record_version=2,
            updated_at=confirmed_at,
        )
        with UnitOfWork(connection):
            repository.save(blocking, expected_record_version=1)
        assert repository.get(RELATION_ID) == blocking

        resolved_at = confirmed_at + timedelta(seconds=3)
        resolved = replace(
            blocking,
            state=BlockingRelationState.RESOLVED,
            clear_trusted_seconds=3.0,
            resolved_at=resolved_at,
            terminated_at=resolved_at,
            termination_reason="BLOCKING_RELATION_CLEAR_CONFIRMED",
            record_version=3,
            updated_at=resolved_at,
        )
        with UnitOfWork(connection):
            repository.save(resolved, expected_record_version=2)
        assert repository.list_active() == ()
        assert repository.get(RELATION_ID) == resolved

        with pytest.raises(BlockingRelationConflictError, match="cannot be reactivated"):
            with UnitOfWork(connection):
                repository.save(
                    replace(
                        resolved,
                        state=BlockingRelationState.BLOCKING,
                        resolved_at=None,
                        terminated_at=None,
                        termination_reason=None,
                        record_version=4,
                        updated_at=resolved_at + timedelta(seconds=1),
                    ),
                    expected_record_version=3,
                )
    finally:
        connection.close()


def test_zone_visit_round_trip_active_cardinality_and_optimistic_save(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = ZoneVisitRepository(connection)
    visit = _visit()
    try:
        with pytest.raises(TransactionStateError):
            repository.add(visit)

        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            repository.add(visit)

        assert repository.get(VISIT_ID) == visit
        assert repository.get_active(VEHICLE_ID, ZoneId(7)) == visit
        assert repository.list_active() == (visit,)
        assert repository.list_active_by_physical_vehicle(VEHICLE_ID) == (visit,)
        assert repository.list_active_by_zone(ZoneId(7)) == (visit,)
        assert repository.list_active_by_zone(ZoneId(999)) == ()

        duplicate = replace(
            visit,
            visit_id=ZoneVisitId(
                UUID("20000000-0000-4000-8000-000000000002")
            ),
        )
        with pytest.raises(ZoneVisitConflictError):
            with UnitOfWork(connection):
                repository.add(duplicate)

        inside = replace(
            visit,
            state=ZoneVisitState.INSIDE,
            entry_trusted_seconds=1.5,
            entered_at=NOW,
            record_version=2,
            updated_at=NOW + timedelta(seconds=2),
        )
        with UnitOfWork(connection):
            repository.save(inside, expected_record_version=1)
        assert repository.get(VISIT_ID) == inside

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.save(inside, expected_record_version=1)

        changed_scalar = replace(
            inside,
            entry_confirmation_seconds=9.0,
            record_version=3,
            updated_at=NOW + timedelta(seconds=3),
        )
        with pytest.raises(ZoneVisitConflictError):
            with UnitOfWork(connection):
                repository.save(changed_scalar, expected_record_version=2)

        changed_gap_policy = replace(
            inside,
            trusted_sample_max_gap_seconds=1.25,
            record_version=3,
            updated_at=NOW + timedelta(seconds=3),
        )
        with pytest.raises(ZoneVisitConflictError):
            with UnitOfWork(connection):
                repository.save(changed_gap_policy, expected_record_version=2)

        ended = replace(
            inside,
            state=ZoneVisitState.ENDED,
            ended_at=NOW + timedelta(seconds=4),
            termination_reason="ZONE_EXIT_CONFIRMED",
            record_version=3,
            updated_at=NOW + timedelta(seconds=4),
        )
        with UnitOfWork(connection):
            repository.save(ended, expected_record_version=2)
        assert repository.get_active(VEHICLE_ID, ZoneId(7)) is None
        assert repository.list_active() == ()
        assert repository.list_active_by_zone(ZoneId(7)) == ()

        reactivated = replace(
            ended,
            state=ZoneVisitState.INSIDE,
            ended_at=None,
            termination_reason=None,
            record_version=4,
            updated_at=NOW + timedelta(seconds=5),
        )
        with pytest.raises(ZoneVisitConflictError, match="cannot be reactivated"):
            with UnitOfWork(connection):
                repository.save(reactivated, expected_record_version=3)

        changed_terminal = replace(
            ended,
            state=ZoneVisitState.CANCELED,
            record_version=4,
            updated_at=NOW + timedelta(seconds=5),
        )
        with pytest.raises(ZoneVisitConflictError, match="change terminal state"):
            with UnitOfWork(connection):
                repository.save(changed_terminal, expected_record_version=3)
    finally:
        connection.close()


def test_zone_visit_list_active_by_zone_filters_state_and_orders_candidates(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = ZoneVisitRepository(connection)
    vehicle_a = PhysicalVehicleId(UUID(int=1))
    vehicle_b = PhysicalVehicleId(UUID(int=2))
    vehicle_c = PhysicalVehicleId(UUID(int=3))
    vehicle_d = PhysicalVehicleId(UUID(int=4))
    vehicle_e = PhysicalVehicleId(UUID(int=5))
    vehicle_f = PhysicalVehicleId(UUID(int=6))

    entering = replace(
        _visit(),
        visit_id=ZoneVisitId(UUID(int=104)),
        physical_vehicle_id=vehicle_a,
        state=ZoneVisitState.ENTERING,
        entered_candidate_at=NOW + timedelta(seconds=2),
        created_at=NOW + timedelta(seconds=2),
        updated_at=NOW + timedelta(seconds=2),
    )
    inside = replace(
        _visit(),
        visit_id=ZoneVisitId(UUID(int=102)),
        physical_vehicle_id=vehicle_b,
        state=ZoneVisitState.INSIDE,
        entered_candidate_at=NOW + timedelta(seconds=1),
        entered_at=NOW + timedelta(seconds=1),
        created_at=NOW + timedelta(seconds=1),
        updated_at=NOW + timedelta(seconds=1),
    )
    exiting = replace(
        _visit(),
        visit_id=ZoneVisitId(UUID(int=103)),
        physical_vehicle_id=vehicle_c,
        state=ZoneVisitState.EXITING,
        entered_candidate_at=NOW + timedelta(seconds=1),
        entered_at=NOW + timedelta(seconds=1),
        exit_candidate_at=NOW + timedelta(seconds=1),
        created_at=NOW + timedelta(seconds=1),
        updated_at=NOW + timedelta(seconds=1),
    )
    other_zone = replace(
        _visit(),
        visit_id=ZoneVisitId(UUID(int=105)),
        physical_vehicle_id=vehicle_d,
        zone_id=ZoneId(8),
        state=ZoneVisitState.INSIDE,
        entered_at=NOW,
    )
    ended = replace(
        _visit(),
        visit_id=ZoneVisitId(UUID(int=106)),
        physical_vehicle_id=vehicle_e,
        state=ZoneVisitState.ENDED,
        entered_at=NOW,
        ended_at=NOW + timedelta(seconds=3),
        termination_reason="ZONE_EXIT_CONFIRMED",
        updated_at=NOW + timedelta(seconds=3),
    )
    canceled = replace(
        _visit(),
        visit_id=ZoneVisitId(UUID(int=107)),
        physical_vehicle_id=vehicle_f,
        state=ZoneVisitState.CANCELED,
        ended_at=NOW + timedelta(seconds=3),
        termination_reason="VISIT_CANCELED",
        updated_at=NOW + timedelta(seconds=3),
    )

    try:
        with UnitOfWork(connection):
            vehicle_repository = PhysicalVehicleRepository(connection)
            for physical_vehicle_id in (
                vehicle_a,
                vehicle_b,
                vehicle_c,
                vehicle_d,
                vehicle_e,
                vehicle_f,
            ):
                vehicle_repository.ensure(
                    replace(
                        _vehicle(),
                        physical_vehicle_id=physical_vehicle_id,
                    )
                )

            # 저장 순서와 반환 순서를 다르게 해 SQL 정렬 계약을 검증한다.
            for visit in (
                entering,
                exiting,
                other_zone,
                ended,
                canceled,
                inside,
            ):
                repository.add(visit)

        assert repository.list_active_by_zone(ZoneId(7)) == (
            inside,
            exiting,
            entering,
        )
        assert repository.list_active_by_zone(ZoneId(8)) == (other_zone,)
        assert repository.list_active_by_zone(ZoneId(999)) == ()
    finally:
        connection.close()


def test_parking_episode_round_trips_assignment_and_guards_session_correlation(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = ParkingEpisodeRepository(connection)
    episode = _episode()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            repository.add(episode)

        assert repository.get(EPISODE_ID) == episode
        assert repository.get_active(VEHICLE_ID).assignment == _assignment(NOW)

        duplicate = replace(
            episode,
            episode_id=ParkingEpisodeId(
                UUID("30000000-0000-4000-8000-000000000002")
            ),
        )
        with pytest.raises(ParkingEpisodeConflictError):
            with UnitOfWork(connection):
                repository.add(duplicate)

        parked_at = NOW + timedelta(seconds=10)
        parked = replace(
            episode,
            state=ParkingState.PARKED,
            stationary_trusted_seconds=10.0,
            parking_session_id=ParkingSessionId(55),
            assignment=_assignment(parked_at),
            parked_at=parked_at,
            record_version=2,
            publication_revision=1,
            updated_at=parked_at,
        )
        with UnitOfWork(connection):
            repository.save(parked, expected_record_version=1)

        assert repository.get(EPISODE_ID) == parked
        assert repository.get_active(VEHICLE_ID) == parked
        assert repository.list_active() == (parked,)
        footprint_payload = connection.execute(
            "SELECT representative_footprint FROM parking_episodes "
            "WHERE parking_episode_id = ?",
            (str(EPISODE_ID),),
        ).fetchone()[0]
        assert bytes(footprint_payload) == (
            b"[[0.1,0.2],[0.4,0.2],[0.4,0.6],[0.1,0.6]]"
        )

        cleared_session = replace(
            parked,
            parking_session_id=None,
            record_version=3,
            updated_at=parked_at + timedelta(seconds=1),
        )
        with pytest.raises(ParkingEpisodeConflictError):
            with UnitOfWork(connection):
                repository.save(cleared_session, expected_record_version=2)

        changed_scalar = replace(
            parked,
            movement_confirmation_seconds=4.0,
            record_version=3,
            updated_at=parked_at + timedelta(seconds=1),
        )
        with pytest.raises(ParkingEpisodeConflictError):
            with UnitOfWork(connection):
                repository.save(changed_scalar, expected_record_version=2)

        changed_gap_policy = replace(
            parked,
            trusted_sample_max_gap_seconds=1.25,
            record_version=3,
            updated_at=parked_at + timedelta(seconds=1),
        )
        with pytest.raises(ParkingEpisodeConflictError):
            with UnitOfWork(connection):
                repository.save(changed_gap_policy, expected_record_version=2)

        ended = replace(
            parked,
            state=ParkingState.ENDED,
            last_signal=MotionSignal.MOVING,
            ended_at=parked_at + timedelta(seconds=2),
            termination_reason="MOVEMENT_CONFIRMED",
            record_version=3,
            publication_revision=2,
            updated_at=parked_at + timedelta(seconds=2),
        )
        with UnitOfWork(connection):
            repository.save(ended, expected_record_version=2)
        assert repository.get(EPISODE_ID) == ended
        assert repository.get_active(VEHICLE_ID) is None

        reactivated = replace(
            ended,
            state=ParkingState.PARKED,
            last_signal=MotionSignal.STATIONARY,
            ended_at=None,
            termination_reason=None,
            record_version=4,
            updated_at=parked_at + timedelta(seconds=3),
        )
        with pytest.raises(ParkingEpisodeConflictError, match="cannot be reactivated"):
            with UnitOfWork(connection):
                repository.save(reactivated, expected_record_version=3)
    finally:
        connection.close()


def test_incident_queries_and_fill_only_correlation(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = IncidentRepository(connection)
    incident = _incident()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            repository.add(incident)

        assert repository.get(INCIDENT_ID) == incident
        assert repository.get_active(incident.key) == incident
        assert repository.get_latest(incident.key) == incident
        assert repository.list_active_by_scope(
            incident.key.scope_type,
            incident.key.scope_id,
        ) == (incident,)
        assert repository.list_active_related_to_physical_vehicle(
            VEHICLE_ID
        ) == (incident,)

        duplicate = replace(
            incident,
            incident_id=IncidentId(
                UUID("40000000-0000-4000-8000-000000000002")
            ),
        )
        with pytest.raises(IncidentConflictError):
            with UnitOfWork(connection):
                repository.add(duplicate)

        opened_at = NOW + timedelta(seconds=2)
        opened = replace(
            incident,
            state=IncidentState.OPEN,
            entry_attempt_id=ENTRY_ATTEMPT_ID,
            parking_session_id=ParkingSessionId(55),
            zone_id=ZoneId(7),
            confirm_trusted_seconds=2.0,
            confirmed_at=opened_at,
            record_version=2,
            publication_revision=1,
            updated_at=opened_at,
        )
        with UnitOfWork(connection):
            repository.save(opened, expected_record_version=1)
        assert repository.get(INCIDENT_ID) == opened

        changed_session = replace(
            opened,
            parking_session_id=ParkingSessionId(99),
            record_version=3,
            updated_at=opened_at + timedelta(seconds=1),
        )
        with pytest.raises(IncidentConflictError):
            with UnitOfWork(connection):
                repository.save(changed_session, expected_record_version=2)

        changed_gap_policy = replace(
            opened,
            trusted_sample_max_gap_seconds=1.25,
            record_version=3,
            updated_at=opened_at + timedelta(seconds=1),
        )
        with pytest.raises(IncidentConflictError):
            with UnitOfWork(connection):
                repository.save(changed_gap_policy, expected_record_version=2)

        resolved_at = opened_at + timedelta(seconds=3)
        resolved = replace(
            opened,
            state=IncidentState.RESOLVED,
            clear_trusted_seconds=3.0,
            resolved_at=resolved_at,
            terminated_at=resolved_at,
            termination_reason="PREDICATE_CLEAR_CONFIRMED",
            record_version=3,
            publication_revision=2,
            updated_at=resolved_at,
        )
        with UnitOfWork(connection):
            repository.save(resolved, expected_record_version=2)
        assert repository.get_active(incident.key) is None
        assert repository.get_latest(incident.key) == resolved

        later = replace(
            incident,
            incident_id=IncidentId(
                UUID("40000000-0000-4000-8000-000000000003")
            ),
            first_observed_at=resolved_at + timedelta(seconds=1),
            created_at=resolved_at + timedelta(seconds=1),
            updated_at=resolved_at + timedelta(seconds=1),
        )
        with UnitOfWork(connection):
            repository.add(later)
        assert repository.get_active(incident.key) == later
        assert repository.get_latest(incident.key) == later

        reactivated = replace(
            resolved,
            state=IncidentState.OPEN,
            resolved_at=None,
            terminated_at=None,
            termination_reason=None,
            record_version=4,
            updated_at=resolved_at + timedelta(seconds=2),
        )
        with pytest.raises(IncidentConflictError, match="cannot be reactivated"):
            with UnitOfWork(connection):
                repository.save(reactivated, expected_record_version=3)
    finally:
        connection.close()


def test_aggregate_checkpoints_allow_monotonic_record_version_jumps(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    visits = ZoneVisitRepository(connection)
    episodes = ParkingEpisodeRepository(connection)
    incidents = IncidentRepository(connection)
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            visits.add(_visit())
            episodes.add(_episode())
            incidents.add(_incident())

        checkpoint_at = NOW + timedelta(seconds=10)
        visit_checkpoint = replace(
            _visit(),
            entry_trusted_seconds=0.5,
            record_version=51,
            updated_at=checkpoint_at,
        )
        episode_checkpoint = replace(
            _episode(),
            stationary_trusted_seconds=0.5,
            record_version=61,
            updated_at=checkpoint_at,
        )
        incident_checkpoint = replace(
            _incident(),
            confirm_trusted_seconds=0.5,
            record_version=71,
            updated_at=checkpoint_at,
        )
        with UnitOfWork(connection):
            visits.save(visit_checkpoint, expected_record_version=1)
            episodes.save(episode_checkpoint, expected_record_version=1)
            incidents.save(incident_checkpoint, expected_record_version=1)

        assert visits.get(VISIT_ID) == visit_checkpoint
        assert episodes.get(EPISODE_ID) == episode_checkpoint
        assert incidents.get(INCIDENT_ID) == incident_checkpoint

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                visits.save(
                    replace(visit_checkpoint, record_version=52),
                    expected_record_version=1,
                )
    finally:
        connection.close()


def test_incident_snapshot_and_outbox_roll_back_together(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    incidents = IncidentRepository(connection)
    outbox = OutboxRepository(connection)
    candidate = _incident()
    opened_at = NOW + timedelta(seconds=2)
    opened = replace(
        candidate,
        state=IncidentState.OPEN,
        parking_session_id=ParkingSessionId(55),
        confirm_trusted_seconds=2.0,
        confirmed_at=opened_at,
        record_version=2,
        publication_revision=1,
        updated_at=opened_at,
    )
    publication = {
        "delivery_id": "incident-4000-revision-1",
        "aggregate_type": "Incident",
        "aggregate_id": str(INCIDENT_ID),
        "destination": "backend",
        "publication_revision": 1,
        "transition_type": "OPEN",
        "payload": b'{"incidentId":"40000000-0000-4000-8000-000000000001"}',
        "idempotency_key": f"Incident:{INCIDENT_ID}:1",
        "created_at_us": 1,
    }
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            incidents.add(candidate)

        with pytest.raises(RuntimeError, match="forced failure"):
            with UnitOfWork(connection):
                incidents.save(opened, expected_record_version=1)
                outbox.enqueue(**publication)
                raise RuntimeError("forced failure")

        assert incidents.get(INCIDENT_ID) == candidate
        assert outbox.get_by_publication(
            aggregate_type="Incident",
            aggregate_id=str(INCIDENT_ID),
            destination="backend",
            publication_revision=1,
        ) is None

        with UnitOfWork(connection):
            incidents.save(opened, expected_record_version=1)
            outbox.enqueue(**publication)
        assert incidents.get(INCIDENT_ID) == opened
        assert outbox.get_by_publication(
            aggregate_type="Incident",
            aggregate_id=str(INCIDENT_ID),
            destination="backend",
            publication_revision=1,
        ) is not None
    finally:
        connection.close()

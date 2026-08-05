"""API 11 실행 판정과 API 12 transactional outbox 연결을 검증한다."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.application.move_verification_executor import MoveVerificationExecutor
from src.communication.backend_publication_preparer import (
    BackendPublicationPreparer,
)
from src.communication.models import (
    MoveRequestId,
    MoveVerificationAttempt,
    MoveVerificationResult,
    MoveVerificationState,
)
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import Incident, IncidentId, IncidentKey, IncidentState
from src.session.models import EntryAttemptId
from src.storage.aggregate_repositories import IncidentRepository
from src.storage.database import connect_database, open_database
from src.storage.repositories import (
    MoveVerificationAttemptRepository,
    OutboxRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


T0 = datetime(2026, 8, 4, 6, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(seconds=1)
DEADLINE = T0 + timedelta(seconds=30)
PHYSICAL_VEHICLE_ID = PhysicalVehicleId(
    UUID("b3a857d1-58ce-47d0-8899-33dc175aa201")
)
INCIDENT_ID = IncidentId(UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91"))
ENTRY_ATTEMPT_ID = EntryAttemptId(
    UUID("d290f1ee-6c54-4b01-90e6-d701748f0852")
)


def test_observed_open_incident_completes_and_enqueues_api_12(tmp_path: Path) -> None:
    database = tmp_path / "jetson.db"
    _seed(database, incident_state=IncidentState.OPEN)
    executor = _executor(database, now=T1)

    assert executor.execute_once() is True
    assert _attempt(database).state is MoveVerificationState.CHECKING
    assert executor.execute_once() is True

    attempt = _attempt(database)
    publication = _publication(database)
    assert attempt.state is MoveVerificationState.COMPLETED
    assert attempt.result is MoveVerificationResult.STILL_ACTIVE
    assert attempt.publication_revision == 1
    assert publication is not None
    assert publication.delivery_id == "MoveVerificationAttempt:201:1:1"
    assert publication.aggregate_id == "201:1"
    assert publication.transition_type == "VERIFICATION_COMPLETED"
    assert publication.idempotency_key == publication.delivery_id
    assert json.loads(publication.payload) == {
        "verificationAttempt": 1,
        "publicationRevision": 1,
        "result": "STILL_ACTIVE",
        "incidentResults": [
            {
                "incidentId": str(INCIDENT_ID),
                "result": "STILL_ACTIVE",
                "incidentPublicationRevision": 1,
            }
        ],
        "completedAt": T1.isoformat(),
    }


def test_uncertain_incident_waits_until_deadline_then_returns_unknown(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    _seed(database, incident_state=IncidentState.CLEAR_PENDING)
    now = [T1]
    executor = MoveVerificationExecutor(
        connection_factory=lambda: connect_database(database),
        publication_preparer=BackendPublicationPreparer(),
        clock=lambda: now[0],
    )

    assert executor.execute_once() is True
    assert executor.execute_once() is False
    assert _attempt(database).state is MoveVerificationState.CHECKING
    assert _publication(database) is None

    now[0] = DEADLINE
    assert executor.execute_once() is True
    assert _attempt(database).result is MoveVerificationResult.UNKNOWN
    assert json.loads(_publication(database).payload)["result"] == "UNKNOWN"


def test_observation_before_command_is_not_accepted_as_recheck_result(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    _seed(
        database,
        incident_state=IncidentState.OPEN,
        accepted_at=T1,
    )
    now = [T1 + timedelta(seconds=1)]
    executor = MoveVerificationExecutor(
        connection_factory=lambda: connect_database(database),
        publication_preparer=BackendPublicationPreparer(),
        clock=lambda: now[0],
    )

    assert executor.execute_once() is True
    assert executor.execute_once() is False

    now[0] = DEADLINE
    assert executor.execute_once() is True
    assert _attempt(database).result is MoveVerificationResult.UNKNOWN


def test_checking_attempt_resumes_after_restart_and_can_resolve_early(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    _seed(
        database,
        incident_state=IncidentState.RESOLVED,
        attempt_state=MoveVerificationState.CHECKING,
    )

    assert _executor(database, now=T1).execute_once() is True

    attempt = _attempt(database)
    assert attempt.state is MoveVerificationState.COMPLETED
    assert attempt.result is MoveVerificationResult.RESOLVED
    assert attempt.incident_results[0].incident_publication_revision == 2
    assert _publication(database) is not None


def test_completion_and_outbox_enqueue_roll_back_together(tmp_path: Path) -> None:
    database = tmp_path / "jetson.db"
    _seed(
        database,
        incident_state=IncidentState.OPEN,
        attempt_state=MoveVerificationState.CHECKING,
    )

    class _FailingPreparer:
        def prepare_move_verification_result(self, attempt):
            del attempt
            raise RuntimeError("serialization failed")

    executor = MoveVerificationExecutor(
        connection_factory=lambda: connect_database(database),
        publication_preparer=_FailingPreparer(),
        clock=lambda: T1,
    )

    with pytest.raises(RuntimeError, match="serialization failed"):
        executor.execute_once()

    assert _attempt(database).state is MoveVerificationState.CHECKING
    assert _publication(database) is None


def _executor(database: Path, *, now: datetime) -> MoveVerificationExecutor:
    return MoveVerificationExecutor(
        connection_factory=lambda: connect_database(database),
        publication_preparer=BackendPublicationPreparer(),
        clock=lambda: now,
    )


def _seed(
    database: Path,
    *,
    incident_state: IncidentState,
    attempt_state: MoveVerificationState = MoveVerificationState.ACCEPTED,
    accepted_at: datetime = T0,
) -> None:
    connection = open_database(database)
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=T0,
    )
    is_resolved = incident_state is IncidentState.RESOLVED
    vehicle = PhysicalVehicle(
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=observation,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
    )
    incident = Incident(
        incident_id=INCIDENT_ID,
        key=IncidentKey.for_physical_vehicle(
            PHYSICAL_VEHICLE_ID,
            "BAD_PARKING",
        ),
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        state=incident_state,
        observation=observation,
        confirm_trusted_seconds=2.0,
        clear_trusted_seconds=(2.0 if incident_state is IncidentState.CLEAR_PENDING else 0.0),
        confirm_duration_seconds=2.0,
        clear_duration_seconds=3.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        publication_revision=2 if is_resolved else 1,
        first_observed_at=T0,
        created_at=T0,
        updated_at=T1,
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        confirmed_at=T0,
        resolved_at=T1 if is_resolved else None,
        terminated_at=T1 if is_resolved else None,
        termination_reason="MOVED" if is_resolved else None,
    )
    attempt = MoveVerificationAttempt(
        request_id=MoveRequestId(201),
        verification_attempt=1,
        subject_physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        target_incident_ids=(INCIDENT_ID,),
        command_payload_hash="a" * 64,
        state=attempt_state,
        record_version=1,
        publication_revision=0,
        accepted_at=accepted_at,
        updated_at=accepted_at,
        deadline_at=DEADLINE,
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(vehicle)
            IncidentRepository(connection).add(incident)
            MoveVerificationAttemptRepository(connection).add(attempt)
    finally:
        connection.close()


def _attempt(database: Path) -> MoveVerificationAttempt:
    connection = connect_database(database)
    try:
        attempt = MoveVerificationAttemptRepository(connection).get(201, 1)
    finally:
        connection.close()
    assert attempt is not None
    return attempt


def _publication(database: Path):
    connection = connect_database(database)
    try:
        return OutboxRepository(connection).get_by_publication(
            aggregate_type="MoveVerificationAttempt",
            aggregate_id="201:1",
            destination="backend",
            publication_revision=1,
        )
    finally:
        connection.close()

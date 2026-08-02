"""Durable input, outbox, and optimistic-concurrency behavior tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.storage import (
    AcceptedInputConflictError,
    AcceptedInputRepository,
    OptimisticConcurrencyError,
    OutboxConflictError,
    OutboxRepository,
    TransactionStateError,
    UnitOfWork,
    open_database,
    optimistic_update,
)


def test_input_acceptance_deduplicates_identical_retry_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = AcceptedInputRepository(connection)
    try:
        with UnitOfWork(connection):
            first = repository.accept(
                input_type="EntryDecision",
                input_identity="entry-1",
                input_revision=2,
                request_payload=b'{"decision":"ALLOW"}',
                workflow_state="ACCEPTED",
                accepted_at_us=10,
            )
        with UnitOfWork(connection):
            retry = repository.accept(
                input_type="EntryDecision",
                input_identity="entry-1",
                input_revision=2,
                request_payload=b'{"decision":"ALLOW"}',
                workflow_state="IGNORED_ON_RETRY",
                accepted_at_us=20,
            )

        assert first.created is True
        assert retry.created is False
        assert retry.record == first.record
        assert retry.record.accepted_at_us == 10

        with pytest.raises(AcceptedInputConflictError):
            with UnitOfWork(connection):
                repository.accept(
                    input_type="EntryDecision",
                    input_identity="entry-1",
                    input_revision=2,
                    request_payload=b'{"decision":"DENY"}',
                    workflow_state="ACCEPTED",
                )

        assert repository.get("EntryDecision", "entry-1", 2) == first.record
    finally:
        connection.close()


def test_repository_writes_require_explicit_unit_of_work(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with pytest.raises(TransactionStateError):
            AcceptedInputRepository(connection).accept(
                input_type="MoveVerificationCommand",
                input_identity="request-1",
                input_revision=1,
                request_payload=b"{}",
                workflow_state="ACCEPTED",
            )
    finally:
        connection.close()


def test_unit_of_work_opens_begin_immediate(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        with UnitOfWork(connection):
            pass
        assert statements[0] == "BEGIN IMMEDIATE"
        assert statements[-1] == "COMMIT"
    finally:
        connection.close()


def test_input_acceptance_and_outbox_roll_back_atomically(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    accepted_inputs = AcceptedInputRepository(connection)
    outbox = OutboxRepository(connection)
    try:
        with pytest.raises(RuntimeError, match="forced failure"):
            with UnitOfWork(connection):
                accepted_inputs.accept(
                    input_type="SessionContextUpdate",
                    input_identity="entry-9",
                    input_revision=3,
                    request_payload=b'{"contextRevision":3}',
                    workflow_state="ACCEPTED",
                )
                outbox.enqueue(
                    delivery_id="delivery-9",
                    aggregate_type="ParkingEpisode",
                    aggregate_id="episode-9",
                    destination="backend",
                    publication_revision=1,
                    transition_type="PARKED",
                    payload=b'{"state":"PARKED"}',
                    idempotency_key="episode-9:1",
                )
                raise RuntimeError("forced failure")

        assert accepted_inputs.get("SessionContextUpdate", "entry-9", 3) is None
        assert outbox.get_by_publication(
            aggregate_type="ParkingEpisode",
            aggregate_id="episode-9",
            destination="backend",
            publication_revision=1,
        ) is None
    finally:
        connection.close()


def test_durable_incident_transition_and_outbox_roll_back_atomically(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    outbox = OutboxRepository(connection)
    try:
        with UnitOfWork(connection):
            connection.execute(
                """
                INSERT INTO physical_vehicles(
                    physical_vehicle_id, domain_state, observation_state,
                    last_reliable_observed_at_us,
                    absence_trusted_duration_us, absence_confirmation_duration_us,
                    trusted_sample_max_gap_duration_us,
                    record_version, created_at_us, updated_at_us
                ) VALUES ('vehicle-incident', 'ACTIVE', 'OBSERVED', 1, 0, 1,
                          1, 1, 1, 1)
                """
            )
            connection.execute(
                """
                INSERT INTO incidents(
                    incident_id, rule_code, key_scope_type, key_scope_id,
                    subject_physical_vehicle_id, entry_attempt_id,
                    domain_state, observation_state, last_reliable_observed_at_us,
                    confirm_trusted_duration_us, clear_trusted_duration_us,
                    confirm_duration_us, clear_duration_us, first_observed_at_us,
                    trusted_sample_max_gap_duration_us, record_version,
                    publication_revision, created_at_us, updated_at_us
                ) VALUES (
                    'incident-atomic', 'BAD_PARKING', 'PHYSICAL_VEHICLE',
                    'vehicle-incident', 'vehicle-incident', 'entry-atomic',
                    'CANDIDATE', 'OBSERVED', 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1
                )
                """
            )

        with pytest.raises(RuntimeError, match="forced failure"):
            with UnitOfWork(connection):
                optimistic_update(
                    connection,
                    table="incidents",
                    key_column="incident_id",
                    key_value="incident-atomic",
                    expected_record_version=1,
                    changes={
                        "domain_state": "OPEN",
                        "confirmed_at_us": 2,
                        "publication_revision": 1,
                        "updated_at_us": 2,
                    },
                )
                outbox.enqueue(
                    delivery_id="delivery-atomic",
                    aggregate_type="Incident",
                    aggregate_id="incident-atomic",
                    destination="backend",
                    publication_revision=1,
                    transition_type="OPEN",
                    payload=b'{"incidentId":"incident-atomic","state":"OPEN"}',
                    idempotency_key="incident-atomic:1",
                )
                raise RuntimeError("forced failure")

        incident = connection.execute(
            """
            SELECT domain_state, confirmed_at_us, publication_revision, record_version
            FROM incidents WHERE incident_id = 'incident-atomic'
            """
        ).fetchone()
        assert tuple(incident) == ("CANDIDATE", None, 0, 1)
        assert outbox.get_by_publication(
            aggregate_type="Incident",
            aggregate_id="incident-atomic",
            destination="backend",
            publication_revision=1,
        ) is None
    finally:
        connection.close()


def test_outbox_retry_is_idempotent_but_publication_payload_is_immutable(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    publication = {
        "delivery_id": "delivery-1",
        "aggregate_type": "Incident",
        "aggregate_id": "incident-1",
        "destination": "backend",
        "publication_revision": 1,
        "transition_type": "OPEN",
        "payload": b'{"state":"OPEN"}',
        "idempotency_key": "incident-1:1",
        "created_at_us": 100,
    }
    try:
        with UnitOfWork(connection):
            first = repository.enqueue(**publication)
        with UnitOfWork(connection):
            retry = repository.enqueue(**publication)

        assert first.created is True
        assert retry.created is False
        assert retry.record == first.record

        with pytest.raises(OutboxConflictError):
            with UnitOfWork(connection):
                repository.enqueue(**{**publication, "payload": b'{"state":"RESOLVED"}'})

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            with UnitOfWork(connection):
                connection.execute(
                    "UPDATE outbox SET payload = ? WHERE delivery_id = ?",
                    (b"changed", "delivery-1"),
                )
    finally:
        connection.close()


def test_optimistic_update_increments_version_and_rejects_stale_writer(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with UnitOfWork(connection):
            connection.execute(
                """
                INSERT INTO physical_vehicles(
                    physical_vehicle_id, domain_state, observation_state,
                    last_reliable_observed_at_us,
                    absence_trusted_duration_us, absence_confirmation_duration_us,
                    trusted_sample_max_gap_duration_us,
                    record_version, created_at_us, updated_at_us
                ) VALUES ('vehicle-1', 'CANDIDATE', 'OBSERVED', 1, 0, 1, 1, 1, 1, 1)
                """
            )

        with UnitOfWork(connection):
            assert optimistic_update(
                connection,
                table="physical_vehicles",
                key_column="physical_vehicle_id",
                key_value="vehicle-1",
                expected_record_version=1,
                changes={"domain_state": "ACTIVE", "updated_at_us": 2},
            ) == 2

        with UnitOfWork(connection):
            assert optimistic_update(
                connection,
                table="physical_vehicles",
                key_column="physical_vehicle_id",
                key_value="vehicle-1",
                expected_record_version=2,
                next_record_version=10,
                changes={"updated_at_us": 3},
            ) == 10

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                optimistic_update(
                    connection,
                    table="physical_vehicles",
                    key_column="physical_vehicle_id",
                    key_value="vehicle-1",
                    expected_record_version=1,
                    changes={"updated_at_us": 3},
                )

        row = connection.execute(
            "SELECT domain_state, record_version, updated_at_us "
            "FROM physical_vehicles WHERE physical_vehicle_id = 'vehicle-1'"
        ).fetchone()
        assert tuple(row) == ("ACTIVE", 10, 3)
    finally:
        connection.close()

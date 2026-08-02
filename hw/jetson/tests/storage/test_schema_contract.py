"""Schema tests for lifecycle cardinality and deliberate non-persistence."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.storage import UnitOfWork, open_database


EXPECTED_DURABLE_TABLES = {
    "accepted_inputs",
    "blocking_relations",
    "context_bindings",
    "delivery_receipts",
    "deployment_metadata",
    "entry_match_attempts",
    "evidence_artifacts",
    "incidents",
    "move_verification_attempts",
    "outbox",
    "parking_episodes",
    "parking_session_mirrors",
    "pending_handoffs",
    "physical_vehicles",
    "schema_migrations",
    "tombstones",
    "zone_visits",
}


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
    }


def _insert_vehicle(connection: sqlite3.Connection, vehicle_id: str) -> None:
    connection.execute(
        """
        INSERT INTO physical_vehicles(
            physical_vehicle_id, domain_state, observation_state,
            last_reliable_observed_at_us,
            absence_trusted_duration_us, absence_confirmation_duration_us,
            trusted_sample_max_gap_duration_us,
            record_version, created_at_us, updated_at_us
        ) VALUES (?, 'ACTIVE', 'OBSERVED', 1, 0, 1, 1, 1, 1, 1)
        """,
        (vehicle_id,),
    )


def test_schema_contains_only_durable_boundaries_not_vision_stream_data(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        tables = _table_names(connection)
        assert tables == EXPECTED_DURABLE_TABLES
        assert tables.isdisjoint(
            {
                "raw_frames",
                "frames",
                "bounding_boxes",
                "detections",
                "track_segments",
                "incident_signals",
            }
        )
    finally:
        connection.close()


def test_no_lifecycle_foreign_key_uses_delete_cascade(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        foreign_keys = [
            row
            for table in _table_names(connection)
            for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
        ]
        assert foreign_keys, "schema should still enforce selected direct references"
        assert {str(row[6]).upper() for row in foreign_keys} == {"NO ACTION"}
    finally:
        connection.close()


def test_schema_keeps_each_restart_critical_accumulator_and_fact_timestamp(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    expected_columns = {
        "physical_vehicles": {
            "absence_trusted_duration_us",
            "absence_confirmation_duration_us",
            "trusted_sample_max_gap_duration_us",
            "absence_confirmed_at_us",
            "terminated_at_us",
        },
        "parking_session_mirrors": {
            "entry_attempt_id",
            "physical_observation_state",
            "exited_at_us",
        },
        "zone_visits": {
            "entry_trusted_duration_us",
            "exit_trusted_duration_us",
            "trusted_sample_max_gap_duration_us",
            "entered_candidate_at_us",
            "entered_at_us",
            "exit_candidate_at_us",
            "ended_at_us",
        },
        "parking_episodes": {
            "stationary_trusted_duration_us",
            "movement_trusted_duration_us",
            "trusted_sample_max_gap_duration_us",
            "session_id",
            "assignment_state",
            "parked_at_us",
            "movement_candidate_at_us",
            "ended_at_us",
        },
        "blocking_relations": {
            "confirm_trusted_duration_us",
            "clear_trusted_duration_us",
            "confirmed_at_us",
            "resolved_at_us",
        },
        "incidents": {
            "subject_physical_vehicle_id",
            "confirm_trusted_duration_us",
            "clear_trusted_duration_us",
            "trusted_sample_max_gap_duration_us",
            "first_observed_at_us",
            "confirmed_at_us",
            "resolved_at_us",
        },
    }
    try:
        for table, columns in expected_columns.items():
            assert columns <= _column_names(connection, table)
    finally:
        connection.close()


def test_partial_unique_indexes_enforce_nonterminal_scope_cardinality(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with UnitOfWork(connection):
            _insert_vehicle(connection, "vehicle-a")
            _insert_vehicle(connection, "vehicle-b")
            connection.execute(
                """
                INSERT INTO zone_visits(
                    zone_visit_id, physical_vehicle_id, zone_id,
                    zone_definition_version, domain_state, observation_state,
                    last_reliable_observed_at_us, entered_at_us,
                    entry_trusted_duration_us, exit_trusted_duration_us,
                    entry_confirmation_duration_us,
                    exit_confirmation_duration_us,
                    trusted_sample_max_gap_duration_us, record_version,
                    created_at_us, updated_at_us
                ) VALUES ('visit-1', 'vehicle-a', 10, 1, 'INSIDE', 'OBSERVED',
                          1, 1, 0, 0, 1, 1, 1, 1, 1, 1)
                """
            )

        with pytest.raises(sqlite3.IntegrityError):
            with UnitOfWork(connection):
                connection.execute(
                    """
                    INSERT INTO zone_visits(
                        zone_visit_id, physical_vehicle_id, zone_id,
                        zone_definition_version, domain_state, observation_state,
                        last_reliable_observed_at_us, entered_candidate_at_us,
                        entry_trusted_duration_us, exit_trusted_duration_us,
                        entry_confirmation_duration_us,
                        exit_confirmation_duration_us,
                        trusted_sample_max_gap_duration_us, record_version,
                        created_at_us, updated_at_us
                    ) VALUES ('visit-2', 'vehicle-a', 10, 1, 'ENTERING',
                              'OBSERVED', 2, 2, 0, 0, 1, 1, 1, 1, 2, 2)
                    """
                )

        with UnitOfWork(connection):
            connection.execute(
                "UPDATE zone_visits SET domain_state = 'ENDED', "
                "termination_reason = 'EXIT_CONFIRMED', ended_at_us = 2 "
                "WHERE zone_visit_id = 'visit-1'"
            )
            connection.execute(
                """
                INSERT INTO zone_visits(
                    zone_visit_id, physical_vehicle_id, zone_id,
                    zone_definition_version, domain_state, observation_state,
                    last_reliable_observed_at_us, entered_candidate_at_us,
                    entry_trusted_duration_us, exit_trusted_duration_us,
                    entry_confirmation_duration_us,
                    exit_confirmation_duration_us,
                    trusted_sample_max_gap_duration_us, record_version,
                    created_at_us, updated_at_us
                ) VALUES ('visit-2', 'vehicle-a', 10, 1, 'ENTERING',
                          'OBSERVED', 2, 2, 0, 0, 1, 1, 1, 1, 2, 2)
                """
            )
    finally:
        connection.close()


def test_allow_input_requires_authoritative_context_in_schema(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            with UnitOfWork(connection):
                connection.execute(
                    """
                    INSERT INTO entry_match_attempts(
                        entry_attempt_id, match_state, decision_state,
                        decision_revision, session_id, record_version,
                        created_at_us, updated_at_us
                    ) VALUES ('entry-1', 'PENDING', 'ALLOW', 1, 10, 1, 1, 1)
                    """
                )
    finally:
        connection.close()


def test_tracking_session_migration_enforces_new_lifecycle_invariants(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            with UnitOfWork(connection):
                connection.execute(
                    """
                    INSERT INTO physical_vehicles(
                        physical_vehicle_id, domain_state, observation_state,
                        absence_trusted_duration_us,
                        absence_confirmation_duration_us,
                        trusted_sample_max_gap_duration_us,
                        record_version, created_at_us, updated_at_us
                    ) VALUES ('confirmed-without-time', 'ACTIVE', 'UNKNOWN',
                              1, 1, 1, 1, 1, 1)
                    """
                )

        with pytest.raises(sqlite3.IntegrityError):
            with UnitOfWork(connection):
                connection.execute(
                    """
                    INSERT INTO entry_match_attempts(
                        entry_attempt_id, match_state, decision_state,
                        decision_revision, record_version,
                        created_at_us, updated_at_us
                    ) VALUES ('missing-deadline', 'PENDING', 'DENY', 0, 1, 1, 1)
                    """
                )

        with UnitOfWork(connection):
            _insert_vehicle(connection, "vehicle-for-invalid-mirror")
        with pytest.raises(sqlite3.IntegrityError):
            with UnitOfWork(connection):
                connection.execute(
                    """
                    INSERT INTO parking_session_mirrors(
                        session_id, physical_vehicle_id,
                        administrative_state, physical_presence_state,
                        physical_observation_state, context_revision,
                        record_version, publication_revision,
                        created_at_us, updated_at_us
                    ) VALUES (1, 'vehicle-for-invalid-mirror', 'ACTIVE',
                              'UNCONFIRMED', 'UNKNOWN', 0, 1, 0, 1, 1)
                    """
                )
    finally:
        connection.close()


def test_local_only_open_incident_does_not_require_publication_revision(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with UnitOfWork(connection):
            _insert_vehicle(connection, "vehicle-local")
            connection.execute(
                """
                INSERT INTO incidents(
                    incident_id, rule_code, key_scope_type, key_scope_id,
                    subject_physical_vehicle_id, domain_state, observation_state,
                    last_reliable_observed_at_us,
                    confirm_trusted_duration_us, clear_trusted_duration_us,
                    confirm_duration_us, clear_duration_us, first_observed_at_us,
                    confirmed_at_us, trusted_sample_max_gap_duration_us,
                    record_version, publication_revision,
                    created_at_us, updated_at_us
                ) VALUES (
                    'incident-local', 'BAD_PARKING', 'PHYSICAL_VEHICLE',
                    'vehicle-local', 'vehicle-local', 'OPEN', 'OBSERVED', 1,
                    0, 0, 0, 0, 1, 1, 1, 1, 0, 1, 1
                )
                """
            )

        row = connection.execute(
            "SELECT domain_state, publication_revision FROM incidents "
            "WHERE incident_id = 'incident-local'"
        ).fetchone()
        assert tuple(row) == ("OPEN", 0)

        with pytest.raises(sqlite3.IntegrityError):
            with UnitOfWork(connection):
                connection.execute(
                    "UPDATE incidents SET publication_revision = 1 "
                    "WHERE incident_id = 'incident-local'"
                )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("index_name", "table_name"),
    [
        ("uq_active_context_binding_session", "context_bindings"),
        ("uq_active_context_binding_physical_vehicle", "context_bindings"),
        ("uq_exit_enabled_mirror_per_physical_vehicle", "parking_session_mirrors"),
        ("uq_nonterminal_zone_visit", "zone_visits"),
        ("uq_nonterminal_parking_episode", "parking_episodes"),
        ("uq_nonterminal_blocking_relation", "blocking_relations"),
        ("uq_nonterminal_incident_key", "incidents"),
    ],
)
def test_all_documented_cardinality_indexes_are_partial(
    tmp_path: Path, index_name: str, table_name: str
) -> None:
    connection = open_database(tmp_path / f"{index_name}.db")
    try:
        row = connection.execute(
            "SELECT tbl_name, sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (index_name,),
        ).fetchone()
        assert row is not None
        assert row["tbl_name"] == table_name
        assert "WHERE" in str(row["sql"]).upper()
    finally:
        connection.close()

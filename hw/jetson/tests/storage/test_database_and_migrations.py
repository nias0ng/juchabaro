"""Connection durability and immutable migration-history tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from src.domain.models import DeliveryState
from src.evidence.models import EvidenceId, EvidencePublicationKind
from src.storage.database import connect_database, open_database, quick_check
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.migration_runner import (
    MigrationApplyError,
    MigrationChecksumMismatch,
    MigrationRunner,
    default_migrations_directory,
)


def test_open_database_applies_required_pragmas_and_quick_check(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db", busy_timeout_ms=3_210)
    try:
        assert connection.isolation_level is None
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 3_210
        assert quick_check(connection) == ("ok",)
    finally:
        connection.close()


def test_migrations_are_fresh_then_safe_to_rerun(tmp_path: Path) -> None:
    connection = connect_database(tmp_path / "jetson.db")
    runner = MigrationRunner(connection)
    try:
        assert runner.apply() == (1, 2, 3, 4, 5, 6, 7, 8, 9)
        assert runner.apply() == ()
        history = connection.execute(
            "SELECT version, name FROM schema_migrations"
        ).fetchall()
        assert [(row["version"], row["name"]) for row in history] == [
            (1, "0001_initial"),
            (2, "0002_tracking_session_lifecycle"),
            (3, "0003_parking_timer_policy_snapshots"),
            (4, "0004_inbound_idempotency_keys"),
            (5, "0005_evidence_delivery_state"),
            (6, "0006_exit_traversal_checkpoint"),
            (7, "0007_evidence_parent_ack_ordering"),
            (8, "0008_evidence_publication_kind"),
            (9, "0009_incident_related_zones"),
        ]
    finally:
        connection.close()


def test_tracking_session_migration_upgrades_an_applied_initial_schema(
    tmp_path: Path,
) -> None:
    source = default_migrations_directory()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_initial.sql").write_text(
        (source / "0001_initial.sql").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == (1,)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO physical_vehicles(
                physical_vehicle_id, domain_state, observation_state,
                last_reliable_observed_at_us, absence_trusted_duration_us,
                absence_confirmation_duration_us, record_version,
                created_at_us, updated_at_us
            ) VALUES ('legacy-vehicle', 'ACTIVE', 'UNKNOWN', NULL,
                      5000000, 5000000, 1, 1, 123)
            """
        )
        connection.commit()

        (migrations / "0002_tracking_session_lifecycle.sql").write_text(
            (source / "0002_tracking_session_lifecycle.sql").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )

        assert MigrationRunner(connection, migrations).apply() == (2,)
        row = connection.execute(
            """
            SELECT trusted_sample_max_gap_duration_us, absence_confirmed_at_us
            FROM physical_vehicles
            WHERE physical_vehicle_id = 'legacy-vehicle'
            """
        ).fetchone()
        assert tuple(row) == (1_000_000, 123)
    finally:
        connection.close()


def test_parking_timer_policy_migration_backfills_existing_snapshots(
    tmp_path: Path,
) -> None:
    source = default_migrations_directory()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in ("0001_initial.sql", "0002_tracking_session_lifecycle.sql"):
        (migrations / version).write_text(
            (source / version).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == (1, 2)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO physical_vehicles(
                physical_vehicle_id, domain_state, observation_state,
                last_reliable_observed_at_us, absence_trusted_duration_us,
                absence_confirmation_duration_us,
                trusted_sample_max_gap_duration_us, absence_confirmed_at_us,
                record_version, created_at_us, updated_at_us
            ) VALUES ('legacy-parking-vehicle', 'ACTIVE', 'OBSERVED', 10,
                      0, 5000000, 1000000, NULL, 7, 1, 10)
            """
        )
        connection.execute(
            """
            INSERT INTO zone_visits(
                zone_visit_id, physical_vehicle_id, zone_id,
                zone_definition_version, domain_state, observation_state,
                last_reliable_observed_at_us, entry_trusted_duration_us,
                exit_trusted_duration_us, entry_confirmation_duration_us,
                exit_confirmation_duration_us, entered_candidate_at_us,
                record_version, created_at_us, updated_at_us
            ) VALUES ('legacy-visit', 'legacy-parking-vehicle', 3, 4,
                      'ENTERING', 'OBSERVED', 10, 123, 45, 2000000,
                      3000000, 1, 9, 1, 10)
            """
        )
        connection.execute(
            """
            INSERT INTO parking_episodes(
                parking_episode_id, physical_vehicle_id, domain_state,
                observation_state, last_reliable_observed_at_us,
                stationary_trusted_duration_us, movement_trusted_duration_us,
                parking_confirmation_duration_us,
                movement_confirmation_duration_us, last_motion_signal,
                record_version, publication_revision, created_at_us, updated_at_us
            ) VALUES ('legacy-episode', 'legacy-parking-vehicle',
                      'STOP_PENDING', 'OBSERVED', 10, 321, 54, 600000000,
                      2000000, 'STATIONARY', 11, 0, 1, 10)
            """
        )
        connection.execute(
            """
            INSERT INTO incidents(
                incident_id, rule_code, key_scope_type, key_scope_id,
                subject_physical_vehicle_id, domain_state, observation_state,
                last_reliable_observed_at_us, confirm_trusted_duration_us,
                clear_trusted_duration_us, confirm_duration_us,
                clear_duration_us, first_observed_at_us, record_version,
                publication_revision, created_at_us, updated_at_us
            ) VALUES ('legacy-incident', 'BAD_PARKING', 'PHYSICAL_VEHICLE',
                      'legacy-parking-vehicle', 'legacy-parking-vehicle',
                      'CANDIDATE', 'OBSERVED', 10, 222, 33, 2000000,
                      3000000, 1, 13, 0, 1, 10)
            """
        )
        connection.commit()

        migration = "0003_parking_timer_policy_snapshots.sql"
        (migrations / migration).write_text(
            (source / migration).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert MigrationRunner(connection, migrations).apply() == (3,)

        assert tuple(
            connection.execute(
                "SELECT entry_trusted_duration_us, record_version, "
                "trusted_sample_max_gap_duration_us FROM zone_visits "
                "WHERE zone_visit_id = 'legacy-visit'"
            ).fetchone()
        ) == (123, 9, 1_000_000)
        assert tuple(
            connection.execute(
                "SELECT stationary_trusted_duration_us, record_version, "
                "trusted_sample_max_gap_duration_us FROM parking_episodes "
                "WHERE parking_episode_id = 'legacy-episode'"
            ).fetchone()
        ) == (321, 11, 1_000_000)
        assert tuple(
            connection.execute(
                "SELECT confirm_trusted_duration_us, record_version, "
                "trusted_sample_max_gap_duration_us FROM incidents "
                "WHERE incident_id = 'legacy-incident'"
            ).fetchone()
        ) == (222, 13, 1_000_000)

        for table in ("zone_visits", "parking_episodes", "incidents"):
            with pytest.raises(sqlite3.IntegrityError, match="trusted sample gap"):
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        f"UPDATE {table} "
                        "SET trusted_sample_max_gap_duration_us = NULL"
                    )
                finally:
                    connection.rollback()
    finally:
        connection.close()


def test_evidence_delivery_migration_preserves_existing_artifacts(
    tmp_path: Path,
) -> None:
    source = default_migrations_directory()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in (
        "0001_initial.sql",
        "0002_tracking_session_lifecycle.sql",
        "0003_parking_timer_policy_snapshots.sql",
        "0004_inbound_idempotency_keys.sql",
    ):
        (migrations / version).write_text(
            (source / version).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == (1, 2, 3, 4)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO evidence_artifacts(
                evidence_id, incident_id, publication_revision,
                captured_at_us, image_type, workflow_state,
                record_version, created_at_us, updated_at_us
            ) VALUES (
                '1f21d60c-c077-4fb4-a092-7cbdb5fc5a91',
                '2f21d60c-c077-4fb4-a092-7cbdb5fc5a92',
                1, 1, 'image/jpeg', 'RESERVED', 1, 1, 1
            )
            """
        )
        connection.commit()

        migration = "0005_evidence_delivery_state.sql"
        (migrations / migration).write_text(
            (source / migration).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert MigrationRunner(connection, migrations).apply() == (5,)

        row = connection.execute(
            """
            SELECT delivery_state, delivery_attempt_count,
                   next_delivery_attempt_at_us, last_delivery_error
            FROM evidence_artifacts
            """
        ).fetchone()
        assert tuple(row) == (None, 0, None, None)
    finally:
        connection.close()


def test_evidence_parent_ack_migration_repairs_only_legacy_ordering_404(
    tmp_path: Path,
) -> None:
    source = default_migrations_directory()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in (
        "0001_initial.sql",
        "0002_tracking_session_lifecycle.sql",
        "0003_parking_timer_policy_snapshots.sql",
        "0004_inbound_idempotency_keys.sql",
        "0005_evidence_delivery_state.sql",
        "0006_exit_traversal_checkpoint.sql",
    ):
        (migrations / version).write_text(
            (source / version).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    ordering_error = (
        "TerminalBackendPublicationError: Backend returned HTTP 404"
    )
    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == (
            1,
            2,
            3,
            4,
            5,
            6,
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """
            INSERT INTO evidence_artifacts(
                evidence_id, incident_id, publication_revision,
                captured_at_us, image_type, workflow_state,
                backend_acked_at_us, delivery_state,
                delivery_attempt_count, next_delivery_attempt_at_us,
                last_delivery_error, record_version,
                created_at_us, updated_at_us
            ) VALUES (?, ?, ?, 10, 'image/jpeg', ?, ?, 'FAILED_TERMINAL',
                      3, NULL, ?, 5, 10, ?)
            """,
            (
                (
                    "legacy-ordering-404",
                    "incident-ordering",
                    1,
                    "READY",
                    None,
                    ordering_error,
                    100,
                ),
                (
                    "legacy-unavailable-404",
                    "incident-unavailable",
                    1,
                    "FAILED",
                    None,
                    ordering_error,
                    101,
                ),
                (
                    "legacy-evicted-404",
                    "incident-evicted",
                    1,
                    "EVICTED",
                    None,
                    ordering_error,
                    102,
                ),
                (
                    "terminal-contract-error",
                    "incident-contract",
                    1,
                    "READY",
                    None,
                    "TerminalBackendPublicationError: Backend returned HTTP 422",
                    110,
                ),
                (
                    "local-only-ordering-404",
                    "incident-local-only",
                    None,
                    "READY",
                    None,
                    ordering_error,
                    120,
                ),
                (
                    "acked-ordering-404",
                    "incident-acked",
                    1,
                    "READY",
                    125,
                    ordering_error,
                    130,
                ),
                (
                    "reserved-ordering-404",
                    "incident-reserved",
                    1,
                    "RESERVED",
                    None,
                    ordering_error,
                    140,
                ),
            ),
        )
        connection.commit()

        migration = "0007_evidence_parent_ack_ordering.sql"
        (migrations / migration).write_text(
            (source / migration).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert MigrationRunner(connection, migrations).apply() == (7,)

        rows = {
            str(row["evidence_id"]): row
            for row in connection.execute(
                """
                SELECT evidence_id, workflow_state, delivery_state,
                       delivery_attempt_count, next_delivery_attempt_at_us,
                       last_delivery_error, record_version, updated_at_us
                FROM evidence_artifacts
                """
            )
        }
        for repaired_id, workflow_state, updated_at_us in (
            ("legacy-ordering-404", "READY", 100),
            ("legacy-unavailable-404", "FAILED", 101),
            ("legacy-evicted-404", "EVICTED", 102),
        ):
            repaired = rows[repaired_id]
            assert tuple(repaired) == (
                repaired_id,
                workflow_state,
                "RETRY_WAIT",
                3,
                updated_at_us,
                ordering_error,
                6,
                updated_at_us,
            )
        for untouched_id in (
            "terminal-contract-error",
            "local-only-ordering-404",
            "acked-ordering-404",
            "reserved-ordering-404",
        ):
            untouched = rows[untouched_id]
            assert untouched["delivery_state"] == "FAILED_TERMINAL"
            assert untouched["next_delivery_attempt_at_us"] is None
            assert untouched["record_version"] == 5
    finally:
        connection.close()


def test_evidence_publication_kind_migration_backfills_active_delivery_mode(
    tmp_path: Path,
) -> None:
    source = default_migrations_directory()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in (
        "0001_initial.sql",
        "0002_tracking_session_lifecycle.sql",
        "0003_parking_timer_policy_snapshots.sql",
        "0004_inbound_idempotency_keys.sql",
        "0005_evidence_delivery_state.sql",
        "0006_exit_traversal_checkpoint.sql",
        "0007_evidence_parent_ack_ordering.sql",
    ):
        (migrations / version).write_text(
            (source / version).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == tuple(
            range(1, 8)
        )
        connection.execute("BEGIN IMMEDIATE")
        ambiguous_id = "10000000-0000-4000-8000-000000000001"
        connection.executemany(
            """
            INSERT INTO evidence_artifacts(
                evidence_id, incident_id, publication_revision,
                captured_at_us, image_type, workflow_state,
                backend_acked_at_us, delivery_state,
                delivery_attempt_count, record_version,
                created_at_us, updated_at_us
            ) VALUES (
                ?, '20000000-0000-4000-8000-000000000001',
                1, 1, 'image/jpeg', ?, ?, ?, ?, 1, 1, 1
            )
            """,
            (
                ("ready-upload", "READY", None, "RETRY_WAIT", 1),
                ("uploading", "UPLOADING", None, "IN_FLIGHT", 1),
                (
                    "eviction-pending-upload",
                    "EVICTION_PENDING",
                    None,
                    "RETRY_WAIT",
                    2,
                ),
                (ambiguous_id, "FAILED", None, "RETRY_WAIT", 1),
                ("evicted-unavailable", "EVICTED", None, "PENDING", 1),
                ("never-attempted", "READY", None, None, 0),
                ("already-acked", "EVICTED", 2, "DELIVERED", 1),
            ),
        )
        connection.execute(
            """
            UPDATE evidence_artifacts
            SET last_error = 'legacy binary unavailable',
                retention_disposition = 'LOST_OR_CORRUPTED',
                next_delivery_attempt_at_us = 2,
                last_delivery_error = 'offline'
            WHERE evidence_id = ?
            """,
            (ambiguous_id,),
        )
        connection.commit()

        migration = "0008_evidence_publication_kind.sql"
        (migrations / migration).write_text(
            (source / migration).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert MigrationRunner(connection, migrations).apply() == (8,)

        modes = {
            str(row["evidence_id"]): row["publication_kind"]
            for row in connection.execute(
                "SELECT evidence_id, publication_kind FROM evidence_artifacts"
            )
        }
        assert modes == {
            "ready-upload": "UPLOAD",
            "uploading": "UPLOAD",
            "eviction-pending-upload": "UPLOAD",
            ambiguous_id: "AMBIGUOUS",
            "evicted-unavailable": "AMBIGUOUS",
            "never-attempted": None,
            "already-acked": None,
        }
        ambiguous = EvidenceArtifactRepository(connection).get(
            EvidenceId(UUID(ambiguous_id))
        )
        assert ambiguous is not None
        assert ambiguous.publication_kind is EvidencePublicationKind.AMBIGUOUS
        assert ambiguous.delivery_state is DeliveryState.FAILED_TERMINAL
        assert ambiguous.next_delivery_attempt_at is None
        assert ambiguous.last_delivery_error == (
            "LEGACY_PUBLICATION_OUTCOME_UNKNOWN"
        )
        assert EvidenceArtifactRepository(
            connection
        ).list_unavailable_candidates() == ()
        with pytest.raises(sqlite3.IntegrityError, match="kind is immutable"):
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    UPDATE evidence_artifacts
                    SET publication_kind = 'UNAVAILABLE'
                    WHERE evidence_id = 'ready-upload'
                    """
                )
            finally:
                connection.rollback()
    finally:
        connection.close()


def test_incident_related_zones_migration_backfills_legacy_incidents(
    tmp_path: Path,
) -> None:
    source = default_migrations_directory()
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in (
        "0001_initial.sql",
        "0002_tracking_session_lifecycle.sql",
        "0003_parking_timer_policy_snapshots.sql",
        "0004_inbound_idempotency_keys.sql",
        "0005_evidence_delivery_state.sql",
        "0006_exit_traversal_checkpoint.sql",
        "0007_evidence_parent_ack_ordering.sql",
        "0008_evidence_publication_kind.sql",
    ):
        (migrations / version).write_text(
            (source / version).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == tuple(
            range(1, 9)
        )
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO physical_vehicles(
                physical_vehicle_id, domain_state, observation_state,
                last_reliable_observed_at_us, absence_trusted_duration_us,
                absence_confirmation_duration_us,
                trusted_sample_max_gap_duration_us,
                record_version, created_at_us, updated_at_us
            ) VALUES ('legacy-related-zone-vehicle', 'ACTIVE', 'OBSERVED',
                      1, 0, 1, 1, 1, 1, 1)
            """
        )
        connection.execute(
            """
            INSERT INTO incidents(
                incident_id, rule_code, key_scope_type, key_scope_id,
                subject_physical_vehicle_id, domain_state, observation_state,
                last_reliable_observed_at_us,
                confirm_trusted_duration_us, clear_trusted_duration_us,
                confirm_duration_us, clear_duration_us,
                trusted_sample_max_gap_duration_us,
                first_observed_at_us, record_version,
                publication_revision, created_at_us, updated_at_us
            ) VALUES (
                'legacy-related-zone-incident', 'BAD_PARKING',
                'PHYSICAL_VEHICLE', 'legacy-related-zone-vehicle',
                'legacy-related-zone-vehicle', 'CANDIDATE', 'OBSERVED',
                1, 0, 0, 0, 0, 1, 1, 1, 0, 1, 1
            )
            """
        )
        connection.commit()

        migration = "0009_incident_related_zones.sql"
        (migrations / migration).write_text(
            (source / migration).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert MigrationRunner(connection, migrations).apply() == (9,)
        row = connection.execute(
            "SELECT related_zone_ids_payload, record_version FROM incidents "
            "WHERE incident_id = 'legacy-related-zone-incident'"
        ).fetchone()
        assert tuple(row) == ("[]", 1)
    finally:
        connection.close()


def test_applied_migration_checksum_change_is_rejected(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    migration = migrations / "0001_create_widget.sql"
    migration.write_text("CREATE TABLE widget(id INTEGER PRIMARY KEY);\n", encoding="utf-8")
    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == (1,)
        migration.write_text(
            "CREATE TABLE widget(id INTEGER PRIMARY KEY, name TEXT);\n",
            encoding="utf-8",
        )

        with pytest.raises(MigrationChecksumMismatch):
            MigrationRunner(connection, migrations).apply()
    finally:
        connection.close()


def test_failed_migration_rolls_back_every_statement(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_base.sql").write_text(
        "CREATE TABLE base(id INTEGER PRIMARY KEY);\n", encoding="utf-8"
    )
    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == (1,)
        (migrations / "0002_broken.sql").write_text(
            """
            CREATE TABLE should_be_rolled_back(id INTEGER PRIMARY KEY);
            INSERT INTO table_that_does_not_exist(id) VALUES (1);
            """,
            encoding="utf-8",
        )

        with pytest.raises(MigrationApplyError):
            MigrationRunner(connection, migrations).apply()

        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'should_be_rolled_back'"
        ).fetchone() is None
        assert [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )
        ] == [1]
        assert not connection.in_transaction
    finally:
        connection.close()


def test_runner_splits_multiple_statements_on_one_line(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "0001_two_tables.sql").write_text(
        "CREATE TABLE first_table(id INTEGER); CREATE TABLE second_table(id INTEGER);",
        encoding="utf-8",
    )
    connection = connect_database(tmp_path / "jetson.db")
    try:
        assert MigrationRunner(connection, migrations).apply() == (1,)
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {"first_table", "second_table"} <= names
    finally:
        connection.close()


def test_foreign_key_enforcement_is_effective(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.IntegrityError):
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
                ) VALUES ('visit', 'missing-vehicle', 1, 1, 'ENTERING',
                          'OBSERVED', 1, 1, 0, 0, 1, 1, 1, 1, 1, 1)
                """
            )
        connection.rollback()
    finally:
        connection.close()

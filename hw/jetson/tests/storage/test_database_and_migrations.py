"""Connection durability and immutable migration-history tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.storage.database import connect_database, open_database, quick_check
from src.storage.migration_runner import (
    MigrationApplyError,
    MigrationChecksumMismatch,
    MigrationRunner,
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
        assert runner.apply() == (1,)
        assert runner.apply() == ()
        history = connection.execute(
            "SELECT version, name FROM schema_migrations"
        ).fetchall()
        assert [(row["version"], row["name"]) for row in history] == [
            (1, "0001_initial")
        ]
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
                    exit_confirmation_duration_us, record_version,
                    created_at_us, updated_at_us
                ) VALUES ('visit', 'missing-vehicle', 1, 1, 'ENTERING',
                          'OBSERVED', 1, 1, 0, 0, 1, 1, 1, 1, 1)
                """
            )
        connection.rollback()
    finally:
        connection.close()

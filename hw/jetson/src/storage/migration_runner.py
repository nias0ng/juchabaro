"""checksum으로 변경을 감지하는 순차 SQLite schema migration."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{4})_[a-z0-9][a-z0-9_]*\.sql$")


class MigrationError(RuntimeError):
    """migration 탐색·history·적용 실패의 공통 오류."""


class MigrationHistoryError(MigrationError):
    """disk migration과 적용 history를 일치시킬 수 없다."""


class MigrationChecksumMismatch(MigrationHistoryError):
    """이미 적용한 migration 파일이 수정됐다."""


class MigrationApplyError(MigrationError):
    """migration 적용 transaction이 실패해 rollback됐다."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    sql: str


def default_migrations_directory() -> Path:
    return Path(__file__).with_name("migrations")


def _utc_now_microseconds() -> int:
    return time.time_ns() // 1_000


def _contains_executable_sql(fragment: str) -> bool:
    without_line_comments = re.sub(r"--[^\n]*(?:\n|$)", "", fragment)
    without_block_comments = re.sub(r"/\*.*?\*/", "", without_line_comments, flags=re.S)
    return bool(without_block_comments.strip())


def _iter_statements(sql: str) -> Iterator[str]:
    """``executescript``의 implicit commit 없이 migration statement를 나눈다."""

    buffer = ""
    for character in sql:
        buffer += character
        if character == ";" and sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            buffer = ""
            if _contains_executable_sql(statement):
                yield statement

    if _contains_executable_sql(buffer):
        raise MigrationHistoryError("migration contains an incomplete SQL statement")


class MigrationRunner:
    """immutable migration 파일을 빈틈없는 version 순서로 적용한다."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        migrations_directory: str | Path | None = None,
    ) -> None:
        self._connection = connection
        self._directory = (
            Path(migrations_directory)
            if migrations_directory is not None
            else default_migrations_directory()
        )

    def _discover(self) -> list[Migration]:
        if not self._directory.is_dir():
            raise MigrationHistoryError(
                f"migration directory does not exist: {self._directory}"
            )

        migrations: list[Migration] = []
        for path in sorted(self._directory.glob("*.sql")):
            match = _MIGRATION_NAME.fullmatch(path.name)
            if match is None:
                raise MigrationHistoryError(f"invalid migration filename: {path.name}")
            raw = path.read_bytes()
            try:
                sql = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                raise MigrationHistoryError(
                    f"migration is not UTF-8: {path.name}"
                ) from error
            migrations.append(
                Migration(
                    version=int(match.group("version")),
                    name=path.stem,
                    checksum=hashlib.sha256(raw).hexdigest(),
                    sql=sql,
                )
            )

        expected = list(range(1, len(migrations) + 1))
        actual = [migration.version for migration in migrations]
        if actual != expected:
            raise MigrationHistoryError(
                f"migration versions must be contiguous from 0001: {actual!r}"
            )
        return migrations

    def _ensure_history_table(self) -> None:
        if self._connection.in_transaction:
            raise MigrationHistoryError("migrations cannot start inside a transaction")
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    checksum TEXT NOT NULL,
                    applied_at_us INTEGER NOT NULL
                )
                """
            )
            self._connection.commit()
        except Exception:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def _applied(self) -> dict[int, sqlite3.Row]:
        rows = self._connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        return {int(row["version"]): row for row in rows}

    @staticmethod
    def _validate_history(
        migrations: Iterable[Migration], applied: dict[int, sqlite3.Row]
    ) -> None:
        by_version = {migration.version: migration for migration in migrations}
        if applied:
            applied_versions = sorted(applied)
            expected_versions = list(range(1, applied_versions[-1] + 1))
            if applied_versions != expected_versions:
                raise MigrationHistoryError(
                    f"applied migration history has a gap: {applied_versions!r}"
                )
        missing_files = sorted(set(applied) - set(by_version))
        if missing_files:
            raise MigrationHistoryError(
                f"applied migration files are missing: {missing_files!r}"
            )

        for version, row in applied.items():
            migration = by_version[version]
            if str(row["name"]) != migration.name:
                raise MigrationHistoryError(
                    f"applied migration {version:04d} was renamed: "
                    f"{row['name']!r} != {migration.name!r}"
                )
            if str(row["checksum"]) != migration.checksum:
                raise MigrationChecksumMismatch(
                    f"applied migration changed: {migration.name}"
                )

    def _apply_one(self, migration: Migration) -> None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            for statement in _iter_statements(migration.sql):
                self._connection.execute(statement)
            self._connection.execute(
                """
                INSERT INTO schema_migrations(version, name, checksum, applied_at_us)
                VALUES (?, ?, ?, ?)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    _utc_now_microseconds(),
                ),
            )
            self._connection.commit()
        except Exception as error:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise MigrationApplyError(
                f"failed to apply migration {migration.name}"
            ) from error

    def apply(self) -> tuple[int, ...]:
        """미적용 migration을 실행하고 이번 호출에서 적용한 version을 반환한다."""

        migrations = self._discover()
        self._ensure_history_table()
        applied = self._applied()
        self._validate_history(migrations, applied)

        applied_now: list[int] = []
        for migration in migrations:
            if migration.version in applied:
                continue
            self._apply_one(migration)
            applied_now.append(migration.version)
        return tuple(applied_now)

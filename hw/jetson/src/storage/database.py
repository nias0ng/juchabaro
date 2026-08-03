"""SQLite 연결과 기동 시 storage health 정책.

모든 write transaction을 :class:`UnitOfWork`가 명시적으로 열도록 autocommit
mode를 사용한다. connection은 thread 사이에 공유하지 않고 worker가 하나씩
생성해 소유한다.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Union

DatabasePath = Union[str, Path]

DEFAULT_BUSY_TIMEOUT_MS = 5_000


class StorageConfigurationError(RuntimeError):
    """SQLite가 필수 durability 정책을 적용하지 못했다."""


class StorageIntegrityError(RuntimeError):
    """SQLite integrity check가 실패했다."""


def _is_memory_database(database: str) -> bool:
    return database == ":memory:" or database.startswith("file::memory:")


def connect_database(
    database: DatabasePath,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    uri: bool = False,
) -> sqlite3.Connection:
    """Jetson durability pragma를 적용한 connection 하나를 연다.

    반환 connection은 ``isolation_level=None``이다. write는 반드시
    :class:`src.storage.unit_of_work.UnitOfWork`로 감싸며 implicit transaction은
    사용하지 않는다.
    """

    if busy_timeout_ms < 0:
        raise ValueError("busy_timeout_ms must be non-negative")

    database_name = str(database)
    connection = sqlite3.connect(
        database_name,
        timeout=busy_timeout_ms / 1_000,
        isolation_level=None,
        uri=uri,
    )
    connection.row_factory = sqlite3.Row

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
        journal_mode = str(connection.execute("PRAGMA journal_mode = WAL").fetchone()[0])
        connection.execute("PRAGMA synchronous = FULL")

        if not _is_memory_database(database_name) and journal_mode.lower() != "wal":
            raise StorageConfigurationError(
                f"SQLite refused WAL mode for {database_name!r}: {journal_mode!r}"
            )
        if int(connection.execute("PRAGMA foreign_keys").fetchone()[0]) != 1:
            raise StorageConfigurationError("SQLite foreign-key enforcement is disabled")
        # SQLite는 FULL synchronous level을 정수 2로 노출한다.
        if int(connection.execute("PRAGMA synchronous").fetchone()[0]) != 2:
            raise StorageConfigurationError("SQLite synchronous=FULL was not applied")
    except Exception:
        connection.close()
        raise

    return connection


def quick_check(connection: sqlite3.Connection) -> tuple[str, ...]:
    """SQLite ``quick_check``를 실행하고 결과가 정확히 ``ok``인지 확인한다."""

    messages = tuple(str(row[0]) for row in connection.execute("PRAGMA quick_check"))
    if messages != ("ok",):
        details = "; ".join(messages) if messages else "no result"
        raise StorageIntegrityError(f"SQLite quick_check failed: {details}")
    return messages


def open_database(
    database: DatabasePath,
    *,
    busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    migrations_directory: DatabasePath | None = None,
) -> sqlite3.Connection:
    """local durable DB를 열고 migration과 integrity check를 수행한다."""

    # migration runner는 설정된 connection만 필요하므로 module cycle을 피하기 위해
    # 여기서 import한다.
    from .migration_runner import MigrationRunner

    connection = connect_database(database, busy_timeout_ms=busy_timeout_ms)
    try:
        MigrationRunner(connection, migrations_directory).apply()
        quick_check(connection)
    except Exception:
        connection.close()
        raise
    return connection

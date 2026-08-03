"""Jetson API가 durable input을 접수할 수 있는지 확인한다."""

import sqlite3

from fastapi import APIRouter, HTTPException, Request, status

router = APIRouter(
    prefix="/health",
    tags=["Health"],
)


@router.get("")
def health_check(request: Request) -> dict[str, str]:
    """SQLite admission이 불가하면 성공 상태를 보고하지 않는다."""

    connection: sqlite3.Connection | None = None
    try:
        connection = request.app.state.database_connection_factory()
        _check_durable_admission(connection)
    except sqlite3.OperationalError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jetson durable storage를 일시적으로 사용할 수 없습니다.",
        ) from error
    finally:
        if connection is not None:
            connection.close()
    return {
        "status": "ok",
        "component": "jetson",
    }


def _check_durable_admission(connection: sqlite3.Connection) -> None:
    """필수 schema와 write reservation을 부작용 없는 rollback으로 확인한다."""

    try:
        connection.execute("BEGIN IMMEDIATE")
        migration_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
        )
        if migration_count < 1:
            raise sqlite3.OperationalError("database schema is not initialized")
        for table in (
            "accepted_inputs",
            "entry_match_attempts",
            "parking_session_mirrors",
            "outbox",
        ):
            connection.execute(f"SELECT 1 FROM {table} LIMIT 0")
        # 실제 값은 바꾸지 않지만 main DB에 write statement를
        # 실행해 read-only·writer lock 상태를 감지한다.
        connection.execute(
            """UPDATE schema_migrations
               SET applied_at_us = applied_at_us
               WHERE version = (SELECT MAX(version) FROM schema_migrations)"""
        )
    finally:
        # health probe는 DB의 논리 내용을 변경하지 않는다.
        if connection.in_transaction:
            connection.rollback()

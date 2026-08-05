"""GET /health의 durable storage readiness 경계 테스트."""

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.error_handlers import register_error_handlers
from src.api.health_router import router
from src.storage.database import connect_database, open_database


def _client(connection_factory) -> TestClient:
    application = FastAPI()
    register_error_handlers(application)
    application.include_router(router)
    application.state.database_connection_factory = connection_factory
    return TestClient(application)


def test_health_is_ok_when_durable_admission_is_available(tmp_path) -> None:
    database_path = tmp_path / "jetson.db"
    connection = open_database(database_path)
    connection.close()
    client = _client(lambda: connect_database(database_path))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "component": "jetson"}


def test_health_is_unavailable_when_schema_is_not_initialized() -> None:
    response = _client(lambda: sqlite3.connect(":memory:")).get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "httpStatus": "SERVICE_UNAVAILABLE",
        "isSuccess": False,
        "message": "Jetson durable storage를 일시적으로 사용할 수 없습니다.",
        "code": 503,
        "result": {
            "errorType": "DURABLE_STORAGE_UNAVAILABLE",
            "retryable": True,
        },
    }


def test_health_is_unavailable_when_write_reservation_is_blocked(tmp_path) -> None:
    database_path = tmp_path / "jetson.db"
    blocker = open_database(database_path, busy_timeout_ms=0)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        client = _client(
            lambda: connect_database(database_path, busy_timeout_ms=0)
        )

        response = client.get("/health")

        assert response.status_code == 503
        assert response.json() == {
            "httpStatus": "SERVICE_UNAVAILABLE",
            "isSuccess": False,
            "message": "Jetson durable storage를 일시적으로 사용할 수 없습니다.",
            "code": 503,
            "result": {
                "errorType": "DURABLE_STORAGE_UNAVAILABLE",
                "retryable": True,
            },
        }
    finally:
        blocker.rollback()
        blocker.close()


def test_health_is_unavailable_when_storage_cannot_open() -> None:
    def unavailable():
        raise sqlite3.OperationalError("database is locked")

    response = _client(unavailable).get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "httpStatus": "SERVICE_UNAVAILABLE",
        "isSuccess": False,
        "message": "Jetson durable storage를 일시적으로 사용할 수 없습니다.",
        "code": 503,
        "result": {
            "errorType": "DURABLE_STORAGE_UNAVAILABLE",
            "retryable": True,
        },
    }

"""RPi API 2 EntryDecision 접수와 API 3 EntryMatchOutcome 조회 테스트."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.entry_events_router import (
    get_entry_match_query,
    router,
)
from src.application.entry_event_intake import EntryEventIntake
from src.application.entry_match_query import EntryMatchOutcome
from src.communication.models import EntryAccessDecision
from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchState,
    PhysicalPresenceState,
)
from src.storage.database import connect_database, open_database
from src.storage.repositories import (
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
)
from src.tracking.models import ParkingSessionId, PhysicalVehicleId


TEST_INTERNAL_API_KEY = "test-internal-key"
ENTRY_ATTEMPT_ID = UUID("d290f1ee-6c54-4b01-90e6-d701748f0851")
PHYSICAL_VEHICLE_ID = PhysicalVehicleId(
    UUID("b3a857d1-58ce-47d0-8899-33dc175aa201")
)
ENTRY_TIME = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
MATCH_DEADLINE_AT = ENTRY_TIME + timedelta(seconds=10)
VALID_HEADERS = {
    "Idempotency-Key": "req-1",
    "X-Internal-API-Key": TEST_INTERNAL_API_KEY,
}


@pytest.fixture(autouse=True)
def _internal_api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTERNAL_API_KEY", TEST_INTERNAL_API_KEY)
    from src.config.settings import get_settings

    get_settings.cache_clear()


def _entry_match_coordinator() -> EntryMatchCoordinator:
    entry_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="camera-1:v1",
        entry_exit_role=EntryExitRole.ENTRY,
    )
    return EntryMatchCoordinator(zones=ZoneRegistry([entry_zone]))


def make_client(tmp_path: Path) -> tuple[TestClient, Path]:
    database_path = tmp_path / "jetson.db"
    connection = open_database(database_path)
    connection.close()

    app = FastAPI()
    app.include_router(router)
    app.state.entry_event_intake = EntryEventIntake(
        _entry_match_coordinator(),
        match_window_seconds=10.0,
    )
    app.state.database_connection_factory = lambda: connect_database(database_path)
    return TestClient(app), database_path


def make_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "entryAttemptId": str(ENTRY_ATTEMPT_ID),
        "decisionRevision": 1,
        "accessDecision": "ALLOW",
        "entryTime": ENTRY_TIME.isoformat(),
        "sessionContext": {
            "sessionId": 55,
            "vehicleId": 10,
            "isDisabledVehicle": False,
            "isElectric": True,
        },
    }
    payload.update(overrides)
    return payload


def result_of(response) -> dict[str, object]:
    body = response.json()
    assert body["isSuccess"] is True
    return body["result"]


def test_api_2_accepts_only_after_attempt_and_session_mirror_are_durable(
    tmp_path: Path,
) -> None:
    client, database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 202
    assert response.json()["httpStatus"] == "ACCEPTED"
    assert response.json()["code"] == 202
    assert result_of(response) == {
        "entryAttemptId": str(ENTRY_ATTEMPT_ID),
        "decisionRevision": 1,
        "acceptanceStatus": "ACCEPTED",
        "matchState": "PENDING",
        "acceptedAt": result_of(response)["acceptedAt"],
        "matchDeadlineAt": MATCH_DEADLINE_AT.isoformat(),
    }

    connection = connect_database(database_path)
    try:
        attempt = EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(ENTRY_ATTEMPT_ID)
        )
        mirror = ParkingSessionMirrorRepository(connection).get(
            ParkingSessionId(55)
        )
    finally:
        connection.close()
    assert attempt is not None
    assert attempt.decision_state is EntryDecisionState.ALLOW
    assert attempt.decision_revision == 1
    assert attempt.authoritative_context is not None
    assert attempt.authoritative_context.vehicle_id == 10
    assert mirror is not None
    assert mirror.entry_attempt_id == EntryAttemptId(ENTRY_ATTEMPT_ID)
    assert mirror.context_revision == 1
    assert mirror.physical_presence_state is PhysicalPresenceState.UNCONFIRMED


def test_api_2_same_domain_input_returns_already_accepted(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    first = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers=VALID_HEADERS,
    )
    second = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers={**VALID_HEADERS, "Idempotency-Key": "req-2"},
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert result_of(first)["acceptanceStatus"] == "ACCEPTED"
    assert result_of(second)["acceptanceStatus"] == "ALREADY_ACCEPTED"
    assert result_of(second)["acceptedAt"] == result_of(first)["acceptedAt"]


def test_api_2_same_identity_and_revision_with_different_payload_conflicts(
    tmp_path: Path,
) -> None:
    client, _database_path = make_client(tmp_path)
    client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers=VALID_HEADERS,
    )

    response = client.post(
        "/internal/entry-events",
        json=make_payload(entryTime=(ENTRY_TIME + timedelta(seconds=1)).isoformat()),
        headers={**VALID_HEADERS, "Idempotency-Key": "req-2"},
    )

    assert response.status_code == 409


def test_api_2_deny_and_review_are_accepted_without_session_context(
    tmp_path: Path,
) -> None:
    client, _database_path = make_client(tmp_path)
    deny = make_payload(
        entryAttemptId="d290f1ee-6c54-4b01-90e6-d701748f0852",
        accessDecision="DENY",
        sessionContext=None,
    )
    review = make_payload(
        entryAttemptId="d290f1ee-6c54-4b01-90e6-d701748f0853",
        accessDecision="REVIEW",
        sessionContext=None,
    )

    deny_response = client.post(
        "/internal/entry-events",
        json=deny,
        headers=VALID_HEADERS,
    )
    review_response = client.post(
        "/internal/entry-events",
        json=review,
        headers={**VALID_HEADERS, "Idempotency-Key": "req-2"},
    )

    assert deny_response.status_code == 202
    assert review_response.status_code == 202


@pytest.mark.parametrize(
    "overrides",
    [
        {"entryAttemptId": "not-a-uuid"},
        {"decisionRevision": 0},
        {"accessDecision": "UNKNOWN"},
        {"sessionContext": None},
        {"accessDecision": "DENY"},
    ],
)
def test_api_2_invalid_wire_contract_is_unprocessable(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(**overrides),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 422


def test_api_2_rejects_legacy_extra_fields(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(trackingId=str(ENTRY_ATTEMPT_ID)),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 422


def test_api_2_naive_entry_time_is_rejected(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(entryTime="2026-07-31T12:00:00"),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 422


def test_api_2_missing_idempotency_key_is_rejected(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers={"X-Internal-API-Key": TEST_INTERNAL_API_KEY},
    )

    assert response.status_code == 422


def test_api_2_wrong_internal_api_key_is_unauthorized(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers={"Idempotency-Key": "req-1", "X-Internal-API-Key": "wrong"},
    )

    assert response.status_code == 401


def test_api_2_storage_failure_is_service_unavailable(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    def unavailable_connection() -> sqlite3.Connection:
        raise sqlite3.OperationalError("database is unavailable")

    client.app.state.database_connection_factory = unavailable_connection

    response = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 503


def test_api_3_returns_durable_pending_attempt(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)
    client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers=VALID_HEADERS,
    )

    response = client.get(
        f"/internal/entry-events/{ENTRY_ATTEMPT_ID}",
        headers={"X-Internal-API-Key": TEST_INTERNAL_API_KEY},
    )

    assert response.status_code == 200
    assert response.json()["httpStatus"] == "OK"
    assert result_of(response) == {
        "entryAttemptId": str(ENTRY_ATTEMPT_ID),
        "decisionRevision": 1,
        "accessDecision": "ALLOW",
        "matchState": "PENDING",
        "physicalVehicleId": None,
        "matchedAt": None,
        "terminalReason": None,
        "matchDeadlineAt": MATCH_DEADLINE_AT.isoformat(),
    }


class StaticEntryMatchQuery:
    def __init__(self, outcome: EntryMatchOutcome) -> None:
        self._outcome = outcome

    def get(self, entry_attempt_id: UUID, *, connection) -> EntryMatchOutcome:
        assert entry_attempt_id == ENTRY_ATTEMPT_ID
        return self._outcome


@pytest.mark.parametrize(
    ("match_state", "physical_vehicle_id", "matched_at", "terminal_reason"),
    [
        (
            EntryMatchState.MATCHED,
            PHYSICAL_VEHICLE_ID,
            ENTRY_TIME + timedelta(seconds=5),
            None,
        ),
        (
            EntryMatchState.EXPIRED,
            None,
            None,
            "SOURCE_UNAVAILABLE",
        ),
    ],
)
def test_api_3_serializes_terminal_outcomes(
    tmp_path: Path,
    match_state: EntryMatchState,
    physical_vehicle_id: PhysicalVehicleId | None,
    matched_at: datetime | None,
    terminal_reason: str | None,
) -> None:
    client, _database_path = make_client(tmp_path)
    outcome = EntryMatchOutcome(
        entry_attempt_id=EntryAttemptId(ENTRY_ATTEMPT_ID),
        decision_revision=1,
        access_decision=EntryAccessDecision.ALLOW,
        match_state=match_state,
        physical_vehicle_id=physical_vehicle_id,
        matched_at=matched_at,
        terminal_reason=terminal_reason,
        match_deadline_at=MATCH_DEADLINE_AT,
    )
    client.app.dependency_overrides[get_entry_match_query] = (
        lambda: StaticEntryMatchQuery(outcome)
    )

    response = client.get(
        f"/internal/entry-events/{ENTRY_ATTEMPT_ID}",
        headers={"X-Internal-API-Key": TEST_INTERNAL_API_KEY},
    )

    assert response.status_code == 200
    result = result_of(response)
    assert result["matchState"] == match_state.value
    assert result["physicalVehicleId"] == (
        None if physical_vehicle_id is None else str(physical_vehicle_id)
    )
    assert result["matchedAt"] == (
        None if matched_at is None else matched_at.isoformat()
    )
    assert result["terminalReason"] == terminal_reason


def test_api_3_unknown_entry_attempt_is_not_found(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.get(
        f"/internal/entry-events/{ENTRY_ATTEMPT_ID}",
        headers={"X-Internal-API-Key": TEST_INTERNAL_API_KEY},
    )

    assert response.status_code == 404


def test_api_3_wrong_internal_api_key_is_unauthorized(tmp_path: Path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.get(
        f"/internal/entry-events/{ENTRY_ATTEMPT_ID}",
        headers={"X-Internal-API-Key": "wrong"},
    )

    assert response.status_code == 401

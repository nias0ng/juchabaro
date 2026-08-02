"""POST /internal/entry-events의 legacy wire·durable intake 경계 테스트."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.entry_events_router import router
from src.application.entry_event_intake import EntryEventIntake
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
    PhysicalPresenceState,
)
from src.storage.database import connect_database, open_database
from src.storage.repositories import (
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
)
from src.tracking.models import ParkingSessionId


TEST_INTERNAL_API_KEY = "test-internal-key"
ENTRY_ATTEMPT_ID = UUID("d290f1ee-6c54-4b01-90e6-d701748f0851")
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


def make_payload(**overrides) -> dict:
    payload = {
        "trackingId": str(ENTRY_ATTEMPT_ID),
        "recognizedPlateNumber": "12가3456",
        "entryTime": "2026-07-31T12:00:00+00:00",
        "accessDecision": "ALLOW",
        "registered": True,
        "vehicleId": 10,
        "isDisabledVehicle": False,
        "isElectric": True,
        "vehicleStatus": "ACTIVE",
        "sessionId": 55,
        "duplicateRequest": False,
    }
    payload.update(overrides)
    return payload


def test_accepts_payload_only_after_attempt_and_session_mirror_are_durable(
    tmp_path,
) -> None:
    client, database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 202
    assert response.json() == {"accepted": True}
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
    assert attempt.authoritative_context is not None
    assert attempt.authoritative_context.vehicle_id == 10
    assert mirror is not None
    assert mirror.entry_attempt_id == EntryAttemptId(ENTRY_ATTEMPT_ID)
    assert mirror.physical_presence_state is PhysicalPresenceState.UNCONFIRMED


def test_same_domain_identity_and_payload_is_retry_with_a_new_transport_key(
    tmp_path,
) -> None:
    client, _database_path = make_client(tmp_path)

    first = client.post(
        "/internal/entry-events", json=make_payload(), headers=VALID_HEADERS
    )
    second = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers={**VALID_HEADERS, "Idempotency-Key": "req-2"},
    )

    assert first.json() == {"accepted": True}
    assert second.json() == {"accepted": False}


def test_same_domain_identity_with_different_payload_is_conflict(tmp_path) -> None:
    client, _database_path = make_client(tmp_path)
    client.post("/internal/entry-events", json=make_payload(), headers=VALID_HEADERS)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(recognizedPlateNumber="99나9999"),
        headers={**VALID_HEADERS, "Idempotency-Key": "req-2"},
    )

    assert response.status_code == 409


def test_deny_and_review_are_accepted_without_authoritative_session(tmp_path) -> None:
    client, _database_path = make_client(tmp_path)
    deny = make_payload(
        trackingId="d290f1ee-6c54-4b01-90e6-d701748f0852",
        accessDecision="DENY",
        registered=False,
        vehicleId=None,
        isDisabledVehicle=None,
        isElectric=None,
        vehicleStatus=None,
        sessionId=None,
    )
    review = make_payload(
        trackingId="d290f1ee-6c54-4b01-90e6-d701748f0853",
        accessDecision="REVIEW",
        registered=False,
        vehicleId=None,
        isDisabledVehicle=None,
        isElectric=None,
        vehicleStatus=None,
        sessionId=None,
    )

    deny_response = client.post(
        "/internal/entry-events", json=deny, headers=VALID_HEADERS
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
        {"trackingId": "not-a-uuid"},
        {"accessDecision": "UNKNOWN"},
        {"sessionId": None},
    ],
)
def test_invalid_domain_mapping_is_unprocessable(tmp_path, overrides) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(**overrides),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 422


def test_naive_entry_time_is_rejected_by_wire_validation(tmp_path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(entryTime="2026-07-31T12:00:00"),
        headers=VALID_HEADERS,
    )

    assert response.status_code == 422


def test_missing_idempotency_key_header_is_rejected(tmp_path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers={"X-Internal-API-Key": TEST_INTERNAL_API_KEY},
    )

    assert response.status_code == 422


def test_wrong_internal_api_key_is_unauthorized(tmp_path) -> None:
    client, _database_path = make_client(tmp_path)

    response = client.post(
        "/internal/entry-events",
        json=make_payload(),
        headers={"Idempotency-Key": "req-1", "X-Internal-API-Key": "wrong"},
    )

    assert response.status_code == 401

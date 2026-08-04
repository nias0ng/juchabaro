"""Backend → Jetson API 4·5·11 durable command 경계 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.error_handlers import register_error_handlers
from src.api.entry_events_router import router as entry_events_router
from src.api.internal_commands_router import router as internal_commands_router
from src.application.entry_event_intake import EntryEventIntake
from src.application.entry_review_resolution_intake import (
    EntryReviewResolutionIntake,
)
from src.application.move_verification_intake import MoveVerificationIntake
from src.application.session_context_update_intake import (
    SessionContextUpdateIntake,
)
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    EntryExitRole,
    Incident,
    IncidentId,
    IncidentKey,
    IncidentState,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.session.context_binding_coordinator import ContextBindingCoordinator
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    ContextBinding,
    ContextBindingId,
    ContextBindingState,
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchState,
    PhysicalPresenceState,
    SessionAdministrativeState,
)
from src.storage.aggregate_repositories import IncidentRepository
from src.storage.database import connect_database, open_database
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    MoveVerificationAttemptRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


TEST_INTERNAL_API_KEY = "test-internal-key"
ENTRY_ATTEMPT_ID = UUID("d290f1ee-6c54-4b01-90e6-d701748f0852")
PHYSICAL_VEHICLE_ID = PhysicalVehicleId(
    UUID("b3a857d1-58ce-47d0-8899-33dc175aa201")
)
ENTRY_TIME = datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc)
AUTH_HEADERS = {"X-Internal-API-Key": TEST_INTERNAL_API_KEY}


def _headers(idempotency_key: str) -> dict[str, str]:
    return {
        **AUTH_HEADERS,
        "Idempotency-Key": idempotency_key,
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

    coordinator = _entry_match_coordinator()
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(entry_events_router)
    app.include_router(internal_commands_router)
    app.state.entry_event_intake = EntryEventIntake(
        coordinator,
        match_window_seconds=10.0,
    )
    app.state.entry_review_resolution_intake = EntryReviewResolutionIntake(
        coordinator
    )
    app.state.session_context_update_intake = SessionContextUpdateIntake(
        ContextBindingCoordinator()
    )
    app.state.move_verification_intake = MoveVerificationIntake(
        clock=lambda: ENTRY_TIME
    )
    app.state.database_connection_factory = lambda: connect_database(
        database_path
    )
    return TestClient(app), database_path


def _post_initial_decision(
    client: TestClient,
    *,
    access_decision: str,
    session_context: dict[str, object] | None,
) -> None:
    response = client.post(
        "/internal/entry-events",
        headers=_headers(f"EntryDecision:{ENTRY_ATTEMPT_ID}:1"),
        json={
            "entryAttemptId": str(ENTRY_ATTEMPT_ID),
            "decisionRevision": 1,
            "accessDecision": access_decision,
            "entryTime": ENTRY_TIME.isoformat(),
            "sessionContext": session_context,
        },
    )
    assert response.status_code == 202


def _session_context() -> dict[str, object]:
    return {
        "sessionId": 55,
        "vehicleId": 10,
        "isDisabledVehicle": False,
        "isElectric": True,
    }


def test_api_4_resolves_review_and_returns_existing_acceptance_on_retry(
    tmp_path: Path,
) -> None:
    client, database_path = make_client(tmp_path)
    _post_initial_decision(
        client,
        access_decision="REVIEW",
        session_context=None,
    )
    payload = {
        "entryAttemptId": str(ENTRY_ATTEMPT_ID),
        "decisionRevision": 2,
        "resolution": "REVIEW_ALLOW",
        "resolvedAt": (ENTRY_TIME + timedelta(seconds=2)).isoformat(),
        "sessionContext": _session_context(),
    }

    first = client.post(
        "/internal/entry-review-resolutions",
        headers=_headers(f"EntryReviewResolution:{ENTRY_ATTEMPT_ID}:2"),
        json=payload,
    )
    retry = client.post(
        "/internal/entry-review-resolutions",
        headers=_headers(f"EntryReviewResolution:{ENTRY_ATTEMPT_ID}:2"),
        json=payload,
    )

    assert first.status_code == 202
    assert retry.status_code == 202
    assert first.json()["result"] == {
        "aggregateType": "EntryReviewResolution",
        "aggregateId": str(ENTRY_ATTEMPT_ID),
        "publicationRevision": 2,
        "applicationResult": "APPLIED",
        "backendCorrelation": {
            "acceptedAt": first.json()["result"]["backendCorrelation"][
                "acceptedAt"
            ]
        },
    }
    assert retry.json()["result"]["applicationResult"] == "ALREADY_APPLIED"
    assert retry.json()["result"]["backendCorrelation"] == first.json()[
        "result"
    ]["backendCorrelation"]

    conflicting = client.post(
        "/internal/entry-review-resolutions",
        headers=_headers(f"EntryReviewResolution:{ENTRY_ATTEMPT_ID}:2"),
        json={**payload, "resolvedAt": (ENTRY_TIME + timedelta(seconds=3)).isoformat()},
    )
    assert conflicting.status_code == 409
    assert conflicting.json()["result"] == {
        "errorType": "IDEMPOTENCY_CONFLICT",
        "retryable": False,
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
    assert attempt.decision_state is EntryDecisionState.REVIEW_ALLOW
    assert attempt.decision_revision == 2
    assert mirror is not None
    assert mirror.entry_attempt_id == EntryAttemptId(ENTRY_ATTEMPT_ID)


def test_api_4_returns_stale_for_an_unseen_older_decision(
    tmp_path: Path,
) -> None:
    client, _database_path = make_client(tmp_path)
    _post_initial_decision(
        client,
        access_decision="REVIEW",
        session_context=None,
    )
    latest = {
        "entryAttemptId": str(ENTRY_ATTEMPT_ID),
        "decisionRevision": 3,
        "resolution": "REVIEW_DENY",
        "resolvedAt": (ENTRY_TIME + timedelta(seconds=3)).isoformat(),
        "sessionContext": None,
    }
    applied = client.post(
        "/internal/entry-review-resolutions",
        headers=_headers(f"EntryReviewResolution:{ENTRY_ATTEMPT_ID}:3"),
        json=latest,
    )
    stale_payload = {
        **latest,
        "decisionRevision": 2,
        "resolvedAt": (ENTRY_TIME + timedelta(seconds=2)).isoformat(),
    }
    stale_headers = _headers(
        f"EntryReviewResolution:{ENTRY_ATTEMPT_ID}:2"
    )
    stale = client.post(
        "/internal/entry-review-resolutions",
        headers=stale_headers,
        json=stale_payload,
    )
    stale_retry = client.post(
        "/internal/entry-review-resolutions",
        headers=stale_headers,
        json=stale_payload,
    )

    assert applied.status_code == 202
    assert applied.json()["result"]["applicationResult"] == "APPLIED"
    assert stale.status_code == 202
    assert stale.json()["result"]["applicationResult"] == "STALE"

    assert stale_retry.json()["result"]["applicationResult"] == "STALE"


def test_api_5_closed_ends_binding_without_creating_a_physical_exit(
    tmp_path: Path,
) -> None:
    client, database_path = make_client(tmp_path)
    _post_initial_decision(
        client,
        access_decision="ALLOW",
        session_context=_session_context(),
    )
    observed_at = ENTRY_TIME + timedelta(seconds=1)
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=observed_at,
    )
    vehicle = PhysicalVehicle(
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=observation,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=observed_at,
        updated_at=observed_at,
    )

    connection = connect_database(database_path)
    try:
        attempt_repository = EntryMatchAttemptRepository(connection)
        mirror_repository = ParkingSessionMirrorRepository(connection)
        attempt = attempt_repository.get(EntryAttemptId(ENTRY_ATTEMPT_ID))
        mirror = mirror_repository.get(ParkingSessionId(55))
        assert attempt is not None and mirror is not None
        matched_attempt = replace(
            attempt,
            match_state=EntryMatchState.MATCHED,
            matched_physical_vehicle_id=PHYSICAL_VEHICLE_ID,
            match_terminated_at=observed_at,
            record_version=attempt.record_version + 1,
            updated_at=observed_at,
        )
        inside_mirror = replace(
            mirror,
            physical_vehicle_id=PHYSICAL_VEHICLE_ID,
            physical_presence_state=PhysicalPresenceState.INSIDE,
            physical_observation=observation,
            record_version=mirror.record_version + 1,
            updated_at=observed_at,
        )
        binding = ContextBinding(
            context_binding_id=ContextBindingId(
                UUID("a3a857d1-58ce-47d0-8899-33dc175aa202")
            ),
            entry_attempt_id=EntryAttemptId(ENTRY_ATTEMPT_ID),
            parking_session_id=ParkingSessionId(55),
            physical_vehicle_id=PHYSICAL_VEHICLE_ID,
            state=ContextBindingState.BOUND,
            context_revision=1,
            context=inside_mirror.last_context,
            record_version=1,
            bound_at=observed_at,
            updated_at=observed_at,
        )
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(vehicle)
            attempt_repository.save(
                matched_attempt,
                expected_record_version=attempt.record_version,
            )
            mirror_repository.save(
                inside_mirror,
                expected_record_version=mirror.record_version,
            )
            ContextBindingRepository(connection).add(binding)
    finally:
        connection.close()

    updated_at = ENTRY_TIME + timedelta(seconds=3)
    response = client.post(
        "/internal/session-context-updates",
        headers=_headers("SessionContextUpdate:55:2"),
        json={
            "sessionId": 55,
            "entryAttemptId": str(ENTRY_ATTEMPT_ID),
            "contextRevision": 2,
            "administrativeState": "CLOSED",
            "updatedAt": updated_at.isoformat(),
            "sessionContext": {
                "vehicleId": 10,
                "isDisabledVehicle": True,
                "isElectric": True,
            },
        },
    )

    assert response.status_code == 202
    connection = connect_database(database_path)
    try:
        persisted_mirror = ParkingSessionMirrorRepository(connection).get(
            ParkingSessionId(55)
        )
        persisted_binding = ContextBindingRepository(
            connection
        ).get_by_entry_attempt_id(EntryAttemptId(ENTRY_ATTEMPT_ID))
        persisted_vehicle = PhysicalVehicleRepository(connection).get(
            PHYSICAL_VEHICLE_ID
        )
    finally:
        connection.close()
    assert persisted_mirror is not None
    assert persisted_mirror.administrative_state is SessionAdministrativeState.CLOSED
    assert persisted_mirror.physical_presence_state is PhysicalPresenceState.INSIDE
    assert persisted_mirror.exited_at is None
    assert persisted_binding is not None
    assert persisted_binding.state is ContextBindingState.ENDED
    assert persisted_binding.termination_reason == "ADMIN_CLOSED"
    assert persisted_binding.context.is_disabled_vehicle is True
    assert persisted_vehicle is not None
    assert persisted_vehicle.state is PhysicalVehicleState.ACTIVE


def test_api_5_returns_stale_without_overwriting_newer_context(
    tmp_path: Path,
) -> None:
    client, database_path = make_client(tmp_path)
    _post_initial_decision(
        client,
        access_decision="ALLOW",
        session_context=_session_context(),
    )
    latest = {
        "sessionId": 55,
        "entryAttemptId": str(ENTRY_ATTEMPT_ID),
        "contextRevision": 3,
        "administrativeState": "ACTIVE",
        "updatedAt": (ENTRY_TIME + timedelta(seconds=3)).isoformat(),
        "sessionContext": {
            "vehicleId": 10,
            "isDisabledVehicle": True,
            "isElectric": True,
        },
    }
    applied = client.post(
        "/internal/session-context-updates",
        headers=_headers("SessionContextUpdate:55:3"),
        json=latest,
    )
    stale = client.post(
        "/internal/session-context-updates",
        headers=_headers("SessionContextUpdate:55:2"),
        json={
            **latest,
            "contextRevision": 2,
            "updatedAt": (ENTRY_TIME + timedelta(seconds=2)).isoformat(),
            "sessionContext": {
                **latest["sessionContext"],
                "isDisabledVehicle": False,
            },
        },
    )

    assert applied.status_code == 202
    assert applied.json()["result"]["applicationResult"] == "APPLIED"
    assert stale.status_code == 202
    assert stale.json()["result"]["applicationResult"] == "STALE"

    connection = connect_database(database_path)
    try:
        mirror = ParkingSessionMirrorRepository(connection).get(
            ParkingSessionId(55)
        )
    finally:
        connection.close()
    assert mirror is not None
    assert mirror.context_revision == 3
    assert mirror.last_context is not None
    assert mirror.last_context.is_disabled_vehicle is True


def test_api_11_persists_one_command_scope_and_does_not_return_a_result(
    tmp_path: Path,
) -> None:
    client, database_path = make_client(tmp_path)
    incident_id = IncidentId(UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91"))
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=ENTRY_TIME,
    )
    vehicle = PhysicalVehicle(
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=observation,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=ENTRY_TIME,
        updated_at=ENTRY_TIME,
    )
    incident = Incident(
        incident_id=incident_id,
        key=IncidentKey.for_physical_vehicle(
            PHYSICAL_VEHICLE_ID,
            "BAD_PARKING",
        ),
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        state=IncidentState.CANDIDATE,
        observation=observation,
        confirm_trusted_seconds=0.0,
        clear_trusted_seconds=0.0,
        confirm_duration_seconds=2.0,
        clear_duration_seconds=3.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        publication_revision=0,
        first_observed_at=ENTRY_TIME,
        created_at=ENTRY_TIME,
        updated_at=ENTRY_TIME,
    )
    connection = connect_database(database_path)
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(vehicle)
            IncidentRepository(connection).add(incident)
    finally:
        connection.close()

    payload = {
        "requestId": 201,
        "verificationAttempt": 2,
        "targetIncidentIds": [str(incident_id)],
        "requestedAt": (ENTRY_TIME + timedelta(seconds=5)).isoformat(),
        "deadlineAt": (ENTRY_TIME + timedelta(seconds=35)).isoformat(),
    }
    first = client.post(
        "/internal/move-verifications",
        headers=_headers("MoveVerification:201:2"),
        json=payload,
    )
    retry = client.post(
        "/internal/move-verifications",
        headers=_headers("MoveVerification:201:2"),
        json=payload,
    )

    assert first.status_code == 202
    assert retry.status_code == 202
    assert first.json()["result"].keys() == {
        "aggregateType",
        "aggregateId",
        "publicationRevision",
        "applicationResult",
        "backendCorrelation",
    }
    assert first.json()["result"]["aggregateType"] == "MoveVerification"
    assert first.json()["result"]["aggregateId"] == "201"
    assert first.json()["result"]["publicationRevision"] == 2
    assert first.json()["result"]["applicationResult"] == "APPLIED"
    assert retry.json()["result"]["applicationResult"] == "ALREADY_APPLIED"

    stale = client.post(
        "/internal/move-verifications",
        headers=_headers("MoveVerification:201:1"),
        json={**payload, "verificationAttempt": 1},
    )
    assert stale.status_code == 202
    assert stale.json()["result"]["applicationResult"] == "STALE"

    expired = client.post(
        "/internal/move-verifications",
        headers=_headers("MoveVerification:201:3"),
        json={
            **payload,
            "verificationAttempt": 3,
            "requestedAt": (ENTRY_TIME - timedelta(seconds=10)).isoformat(),
            "deadlineAt": (ENTRY_TIME - timedelta(seconds=1)).isoformat(),
        },
    )
    assert expired.status_code == 202
    assert expired.json()["result"]["applicationResult"] == "STALE"

    connection = connect_database(database_path)
    try:
        attempt = MoveVerificationAttemptRepository(connection).get(
            201,
            2,
        )
        expired_attempt = MoveVerificationAttemptRepository(connection).get(
            201,
            3,
        )
    finally:
        connection.close()
    assert attempt is not None
    assert attempt.target_incident_ids == (incident_id,)
    assert attempt.result is None
    assert expired_attempt is None

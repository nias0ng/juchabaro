"""가짜 API 11 command부터 API 12 HTTP publication까지의 로컬 통합 테스트."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx
from fastapi.testclient import TestClient

from src.api.entry_events_router import verify_internal_api_key
from src.application.outbox_publisher import OutboxPublisher
from src.communication.backend_client import BackendClient
from src.config.settings import Settings
from src.domain.models import DeliveryState, ObservationState, ObservationStatus
from src.parking.models import Incident, IncidentId, IncidentKey, IncidentState
from src.session.models import EntryAttemptId
from src.storage.aggregate_repositories import IncidentRepository
from src.storage.database import connect_database, open_database
from src.storage.repositories import OutboxRepository, PhysicalVehicleRepository
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


PHYSICAL_VEHICLE_ID = PhysicalVehicleId(
    UUID("b3a857d1-58ce-47d0-8899-33dc175aa201")
)
INCIDENT_ID = IncidentId(UUID("1f21d60c-c077-4fb4-a092-7cbdb5fc5a91"))
ENTRY_ATTEMPT_ID = EntryAttemptId(
    UUID("d290f1ee-6c54-4b01-90e6-d701748f0852")
)


def test_fake_api_11_command_is_published_to_fake_api_12_backend(
    tmp_path: Path,
) -> None:
    from src.main import create_app

    settings = _settings(tmp_path)
    requested_at = datetime.now(timezone.utc)
    _seed_open_incident(
        settings.database_path,
        observed_at=requested_at + timedelta(seconds=1),
    )
    application = create_app(settings=settings)
    application.dependency_overrides[verify_internal_api_key] = lambda: None

    with TestClient(application) as client:
        response = client.post(
            "/internal/move-verifications",
            headers={"Idempotency-Key": "MoveVerification:201:1"},
            json={
                "requestId": 201,
                "verificationAttempt": 1,
                "targetIncidentIds": [str(INCIDENT_ID)],
                "requestedAt": requested_at.isoformat(),
                "deadlineAt": (
                    requested_at + timedelta(seconds=30)
                ).isoformat(),
            },
        )
        assert response.status_code == 202
        assert response.json()["result"]["applicationResult"] == "APPLIED"
        publication = _wait_for_publication(settings.database_path)

    captured: list[httpx.Request] = []

    def handle_backend(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "httpStatus": "OK",
                "isSuccess": True,
                "message": "적용되었습니다.",
                "code": 200,
                "result": {
                    "aggregateType": "MoveVerificationAttempt",
                    "aggregateId": "201:1",
                    "publicationRevision": 1,
                    "applicationResult": "APPLIED",
                    "payloadHash": f"sha256:{publication.payload_hash}",
                    "backendCorrelation": {"requestId": 201},
                },
            },
        )

    publisher = OutboxPublisher(
        connection_factory=lambda: connect_database(settings.database_path),
        client=BackendClient(
            base_url="http://fake-backend:8080",
            hw_api_key="fake-hw-key",
            transport=httpx.MockTransport(handle_backend),
        ),
    )
    try:
        assert publisher.publish_once() is True
    finally:
        publisher.close()

    assert captured[0].url.path == "/api/hw/move-requests/201/verification"
    assert captured[0].headers["idempotency-key"] == (
        "MoveVerificationAttempt:201:1:1"
    )
    assert json.loads(captured[0].content)["result"] == "STILL_ACTIVE"
    connection = connect_database(settings.database_path)
    try:
        delivered = OutboxRepository(connection).get_by_delivery_id(
            publication.delivery_id
        )
    finally:
        connection.close()
    assert delivered is not None
    assert delivered.delivery_state is DeliveryState.DELIVERED


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "runtime.db",
        evidence_spool_path=tmp_path / "evidence",
        evidence_spool_cap_bytes=8 * 1024 * 1024,
        zone_definition_path=(
            Path(__file__).parents[2]
            / "config"
            / "zone_definition.json"
        ),
        egress_aisle_path=(
            Path(__file__).parents[2]
            / "config"
            / "egress_aisle.json"
        ),
        zone_entry_confirm_seconds=3.0,
        zone_exit_confirm_seconds=3.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        parking_confirm_seconds=600.0,
        parking_move_confirm_seconds=3.0,
    )


def _seed_open_incident(database: Path, *, observed_at: datetime) -> None:
    connection = open_database(database)
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=observed_at,
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                PhysicalVehicle(
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
            )
            IncidentRepository(connection).add(
                Incident(
                    incident_id=INCIDENT_ID,
                    key=IncidentKey.for_physical_vehicle(
                        PHYSICAL_VEHICLE_ID,
                        "BAD_PARKING",
                    ),
                    physical_vehicle_id=PHYSICAL_VEHICLE_ID,
                    state=IncidentState.OPEN,
                    observation=observation,
                    confirm_trusted_seconds=2.0,
                    clear_trusted_seconds=0.0,
                    confirm_duration_seconds=2.0,
                    clear_duration_seconds=3.0,
                    trusted_sample_max_gap_seconds=1.0,
                    record_version=1,
                    publication_revision=1,
                    first_observed_at=observed_at,
                    created_at=observed_at,
                    updated_at=observed_at,
                    entry_attempt_id=ENTRY_ATTEMPT_ID,
                    confirmed_at=observed_at,
                )
            )
    finally:
        connection.close()


def _wait_for_publication(database: Path):
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        connection = connect_database(database)
        try:
            publication = OutboxRepository(connection).get_by_publication(
                aggregate_type="MoveVerificationAttempt",
                aggregate_id="201:1",
                destination="backend",
                publication_revision=1,
            )
        finally:
            connection.close()
        if publication is not None:
            return publication
        time.sleep(0.05)
    raise AssertionError("API 12 outbox publication was not created")

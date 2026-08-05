"""API 8·9 evidence publication의 성공·retry·fallback·restart를 검증한다."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from src.application.evidence_publication_worker import (
    EvidencePublicationPublisher,
)
from src.communication.backend_client import (
    PublicationConfirmation,
    RetryableBackendPublicationError,
    TerminalBackendPublicationError,
)
from src.domain.models import DeliveryState
from src.evidence.models import (
    EvidenceArtifact,
    EvidenceId,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.evidence.spool import EvidenceSpool
from src.parking.models import IncidentId
from src.storage.database import connect_database, open_database
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.models import PublicationApplicationStatus
from src.storage.unit_of_work import UnitOfWork


NOW = datetime(2026, 8, 4, 6, 0, tzinfo=timezone.utc)
JPEG = b"\xff\xd8" + b"evidence" * 32 + b"\xff\xd9"


class _Client:
    def __init__(self, *, upload_results=(), unavailable_results=()) -> None:
        self.upload_results = list(upload_results)
        self.unavailable_results = list(unavailable_results)
        self.uploads = []
        self.unavailable = []
        self.closed = False

    def upload_evidence(self, request, *, idempotency_key):
        self.uploads.append((request, idempotency_key))
        return _next_result(self.upload_results)

    def publish_evidence_unavailable(self, request, *, idempotency_key):
        self.unavailable.append((request, idempotency_key))
        return _next_result(self.unavailable_results)

    def close(self) -> None:
        self.closed = True


def _next_result(results):
    result = results.pop(0) if results else _confirmation()
    if isinstance(result, Exception):
        raise result
    return result


def _confirmation() -> PublicationConfirmation:
    return PublicationConfirmation(
        application_status=PublicationApplicationStatus.APPLIED,
        payload_hash=None,
        backend_correlation={"imageId": 301},
    )


def test_ready_binary_is_uploaded_by_api_8_and_acknowledged(tmp_path: Path) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    client = _Client()
    publisher = _publisher(database, root, client, now=lambda: NOW)

    assert publisher.recover() == 0
    assert publisher.publish_once() is True

    delivered = _artifact(database, ready.evidence_id)
    request, key = client.uploads[0]
    assert request.content == JPEG
    assert request.incident_id == ready.incident_id
    assert key == f"EvidenceArtifact:{ready.evidence_id}:1"
    assert delivered.state is EvidenceState.ACKNOWLEDGED
    assert delivered.delivery_state is DeliveryState.DELIVERED
    assert delivered.delivery_attempt_count == 1
    assert delivered.backend_acked_at == NOW
    connection = connect_database(database)
    try:
        ack_payload = connection.execute(
            "SELECT backend_ack_payload FROM evidence_artifacts WHERE evidence_id = ?",
            (str(ready.evidence_id),),
        ).fetchone()[0]
    finally:
        connection.close()
    assert json.loads(bytes(ack_payload))["backendCorrelation"] == {
        "imageId": 301
    }


def test_retryable_api_8_failure_uses_durable_exponential_backoff(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    now = [NOW]
    client = _Client(
        upload_results=(
            RetryableBackendPublicationError("offline"),
            _confirmation(),
        )
    )
    publisher = _publisher(database, root, client, now=lambda: now[0])
    publisher.recover()

    assert publisher.publish_once() is True
    waiting = _artifact(database, ready.evidence_id)
    assert waiting.state is EvidenceState.READY
    assert waiting.delivery_state is DeliveryState.RETRY_WAIT
    assert waiting.next_delivery_attempt_at == NOW + timedelta(seconds=1)
    assert "offline" in waiting.last_delivery_error
    assert publisher.publish_once() is False

    now[0] = NOW + timedelta(seconds=1)
    assert publisher.publish_once() is True
    delivered = _artifact(database, ready.evidence_id)
    assert delivered.delivery_state is DeliveryState.DELIVERED
    assert delivered.delivery_attempt_count == 2
    assert [key for _, key in client.uploads] == [
        f"EvidenceArtifact:{ready.evidence_id}:1",
        f"EvidenceArtifact:{ready.evidence_id}:1",
    ]


def test_failed_capture_is_reported_by_api_9(tmp_path: Path) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    failed = _seed_failed(database)
    client = _Client()
    publisher = _publisher(database, root, client, now=lambda: NOW)

    publisher.recover()
    assert publisher.publish_once() is True

    delivered = _artifact(database, failed.evidence_id)
    request, key = client.unavailable[0]
    assert request.reason.value == "RESOURCE_LIMIT"
    assert request.unavailable_at == failed.updated_at
    assert key == f"EvidenceUnavailable:{failed.evidence_id}:1"
    assert delivered.state is EvidenceState.FAILED
    assert delivered.delivery_state is DeliveryState.DELIVERED
    assert delivered.backend_acked_at == NOW


def test_retryable_api_9_failure_reuses_the_same_publication_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    failed = _seed_failed(database)
    now = [NOW]
    client = _Client(
        unavailable_results=(
            RetryableBackendPublicationError("offline"),
            _confirmation(),
        )
    )
    publisher = _publisher(database, root, client, now=lambda: now[0])
    publisher.recover()

    assert publisher.publish_once() is True
    waiting = _artifact(database, failed.evidence_id)
    assert waiting.delivery_state is DeliveryState.RETRY_WAIT
    assert waiting.next_delivery_attempt_at == NOW + timedelta(seconds=1)

    now[0] = NOW + timedelta(seconds=1)
    assert publisher.publish_once() is True
    assert _artifact(database, failed.evidence_id).delivery_state is (
        DeliveryState.DELIVERED
    )
    assert [key for _, key in client.unavailable] == [
        f"EvidenceUnavailable:{failed.evidence_id}:1",
        f"EvidenceUnavailable:{failed.evidence_id}:1",
    ]
    assert client.unavailable[0][0] == client.unavailable[1][0]


def test_corrupted_api_8_binary_falls_back_to_retryable_api_9(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    publisher = _publisher(database, root, _Client(), now=lambda: NOW)
    publisher.recover()
    assert ready.local_path is not None
    ready.local_path.write_bytes(b"corrupted")

    assert publisher.publish_once() is True
    unavailable = _artifact(database, ready.evidence_id)
    assert unavailable.state is EvidenceState.FAILED
    assert unavailable.delivery_state is DeliveryState.PENDING
    assert (
        unavailable.retention_disposition
        is EvidenceRetentionDisposition.LOST_OR_CORRUPTED
    )
    assert publisher.publish_once() is True
    assert _artifact(database, ready.evidence_id).delivery_state is (
        DeliveryState.DELIVERED
    )


def test_restart_recovers_in_flight_upload_and_retries_same_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    connection = connect_database(database)
    try:
        with UnitOfWork(connection):
            claimed = EvidenceArtifactRepository(
                connection
            ).claim_next_delivery(now=NOW)
    finally:
        connection.close()
    assert claimed is not None
    assert claimed.state is EvidenceState.UPLOADING

    client = _Client()
    publisher = _publisher(database, root, client, now=lambda: NOW)
    assert publisher.recover() == 1
    recovered = _artifact(database, ready.evidence_id)
    assert recovered.state is EvidenceState.READY
    assert recovered.delivery_state is DeliveryState.RETRY_WAIT
    assert recovered.next_delivery_attempt_at == NOW

    assert publisher.publish_once() is True
    assert client.uploads[0][1] == f"EvidenceArtifact:{ready.evidence_id}:1"


def test_terminal_api_9_failure_is_not_automatically_retried(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    failed = _seed_failed(database)
    client = _Client(
        unavailable_results=(TerminalBackendPublicationError("invalid"),)
    )
    publisher = _publisher(database, root, client, now=lambda: NOW)
    publisher.recover()

    assert publisher.publish_once() is True
    terminal = _artifact(database, failed.evidence_id)
    assert terminal.delivery_state is DeliveryState.FAILED_TERMINAL
    assert publisher.publish_once() is False


def _publisher(database, root, client, *, now) -> EvidencePublicationPublisher:
    return EvidencePublicationPublisher(
        connection_factory=lambda: connect_database(database),
        client=client,
        spool_path=root,
        spool_cap_bytes=1_000_000,
        filesystem_floor_ratio=0.0,
        capture_stop_free_ratio=0.0,
        retry_initial_seconds=1.0,
        retry_max_seconds=8.0,
        clock=now,
    )


def _reserved(*, now: datetime = NOW) -> EvidenceArtifact:
    return EvidenceArtifact(
        evidence_id=EvidenceId(uuid4()),
        incident_id=IncidentId(uuid4()),
        publication_revision=1,
        captured_at=now,
        image_type="image/jpeg",
        state=EvidenceState.RESERVED,
        record_version=1,
        created_at=now,
        updated_at=now,
    )


def _seed_ready(database: Path, root: Path) -> EvidenceArtifact:
    connection = open_database(database)
    artifact = _reserved()
    try:
        with UnitOfWork(connection):
            EvidenceArtifactRepository(connection).add(artifact)
        return EvidenceSpool(
            connection=connection,
            root=root,
            spool_cap_bytes=1_000_000,
            filesystem_floor_ratio=0.0,
            capture_stop_free_ratio=0.0,
        ).store_jpeg(artifact.evidence_id, JPEG, now=NOW)
    finally:
        connection.close()


def _seed_failed(database: Path) -> EvidenceArtifact:
    connection = open_database(database)
    artifact = _reserved()
    failed = replace(
        artifact,
        state=EvidenceState.FAILED,
        last_error="capture exceeded resource limit",
        retention_disposition=EvidenceRetentionDisposition.RESOURCE_LIMIT,
        updated_at=NOW + timedelta(seconds=1),
        record_version=2,
    )
    try:
        with UnitOfWork(connection):
            repository = EvidenceArtifactRepository(connection)
            repository.add(artifact)
            repository.save(failed, expected_record_version=1)
        return failed
    finally:
        connection.close()


def _artifact(database: Path, evidence_id: EvidenceId) -> EvidenceArtifact:
    connection = connect_database(database)
    try:
        artifact = EvidenceArtifactRepository(connection).get(evidence_id)
    finally:
        connection.close()
    assert artifact is not None
    return artifact

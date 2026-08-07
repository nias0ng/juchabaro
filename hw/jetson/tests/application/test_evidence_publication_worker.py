"""API 8·9 evidence publication의 성공·retry·fallback·restart를 검증한다."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

from src.application.evidence_publication_worker import (
    EvidencePublicationPublisher,
    EvidencePublicationWorker,
)
from src.communication.backend_client import (
    PublicationConfirmation,
    RetryableBackendPublicationError,
    TerminalBackendPublicationError,
)
from src.domain.models import DeliveryState
from src.diagnostics import DiagnosticEvent, DiagnosticEventType
from src.evidence.models import (
    EvidenceArtifact,
    EvidenceId,
    EvidencePublicationKind,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.evidence.spool import EvidenceSpool
from src.parking.models import IncidentId
from src.storage.database import connect_database, open_database
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.models import PublicationApplicationStatus
from src.storage.repositories import OutboxRepository
from src.storage.unit_of_work import UnitOfWork


NOW = datetime(2026, 8, 4, 6, 0, tzinfo=timezone.utc)
JPEG = b"\xff\xd8" + b"evidence" * 32 + b"\xff\xd9"


class RecordingDiagnosticsSink:
    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)


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


class _WorkerPublisher:
    def __init__(self, *, fail_recovery: bool = False) -> None:
        self.fail_recovery = fail_recovery
        self.recover_count = 0
        self.recover_in_flight_count = 0
        self.publish_count = 0
        self.closed_count = 0
        self.entered_publish = Event()

    def recover(self) -> int:
        self.recover_count += 1
        if self.fail_recovery:
            raise RuntimeError("evidence recovery failed")
        return 0

    def publish_once(self) -> bool:
        self.publish_count += 1
        self.entered_publish.set()
        return False

    def recover_in_flight(self) -> int:
        self.recover_in_flight_count += 1
        return 0

    def close(self) -> None:
        self.closed_count += 1


class _RecoveringWorkerPublisher(_WorkerPublisher):
    def __init__(self, *, fail_first_runtime_recovery: bool = False) -> None:
        super().__init__()
        self.fail_first_runtime_recovery = fail_first_runtime_recovery
        self.resumed = Event()

    def recover_in_flight(self) -> int:
        self.recover_in_flight_count += 1
        if (
            self.fail_first_runtime_recovery
            and self.recover_in_flight_count == 1
        ):
            raise RuntimeError("recovery storage busy")
        return 0

    def publish_once(self) -> bool:
        self.publish_count += 1
        if self.publish_count == 1:
            raise RuntimeError("local ACK persistence failed")
        self.resumed.set()
        return False


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


def test_worker_prepare_recovers_once_without_starting_http_loop() -> None:
    publisher = _WorkerPublisher()
    worker = EvidencePublicationWorker(
        publisher,
        poll_interval_seconds=0.01,
    )

    worker.prepare()
    worker.prepare()

    assert publisher.recover_count == 1
    assert publisher.publish_count == 0
    assert worker.is_running is False

    worker.start()
    assert publisher.entered_publish.wait(timeout=1.0)
    worker.stop()

    assert publisher.recover_count == 1
    assert publisher.closed_count == 1


def test_worker_start_without_prepare_keeps_compatibility() -> None:
    publisher = _WorkerPublisher()
    worker = EvidencePublicationWorker(
        publisher,
        poll_interval_seconds=0.01,
    )

    worker.start()
    assert publisher.entered_publish.wait(timeout=1.0)
    worker.stop()

    assert publisher.recover_count == 1
    assert publisher.closed_count == 1


def test_worker_stop_closes_publisher_when_only_prepare_completed() -> None:
    publisher = _WorkerPublisher()
    worker = EvidencePublicationWorker(publisher)

    worker.prepare()
    worker.stop()

    assert publisher.recover_count == 1
    assert publisher.publish_count == 0
    assert publisher.closed_count == 1


def test_worker_prepare_failure_does_not_start_http_loop() -> None:
    publisher = _WorkerPublisher(fail_recovery=True)
    worker = EvidencePublicationWorker(publisher)

    with pytest.raises(RuntimeError, match="evidence recovery failed"):
        worker.prepare()

    assert worker.is_running is False
    assert publisher.publish_count == 0


def test_worker_recovers_in_flight_and_continues_after_item_failure() -> None:
    publisher = _RecoveringWorkerPublisher(
        fail_first_runtime_recovery=True
    )
    worker = EvidencePublicationWorker(
        publisher,
        poll_interval_seconds=0.01,
    )

    worker.start()
    assert publisher.resumed.wait(timeout=1.0)
    assert worker.is_running is True
    worker.stop()

    assert publisher.recover_count == 1
    assert publisher.recover_in_flight_count == 2
    assert publisher.closed_count == 1
    assert worker.failure is None


def test_ready_binary_is_uploaded_by_api_8_and_acknowledged(
    tmp_path: Path,
    caplog,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    client = _Client()
    diagnostics = RecordingDiagnosticsSink()
    publisher = _publisher(
        database,
        root,
        client,
        now=lambda: NOW,
        diagnostics_sink=diagnostics,
    )

    assert publisher.recover() == 0
    with caplog.at_level(
        logging.INFO,
        logger="src.application.evidence_publication_worker",
    ):
        assert publisher.publish_once() is True

    assert "Backend evidence publication 전송이 완료됐습니다." in caplog.text
    assert "publicationType=UPLOAD" in caplog.text
    assert "applicationStatus=APPLIED" in caplog.text
    assert "imageId" not in caplog.text

    delivered = _artifact(database, ready.evidence_id)
    request, key = client.uploads[0]
    assert request.content == JPEG
    assert request.incident_id == ready.incident_id
    assert key == f"EvidenceArtifact:{ready.evidence_id}:1"
    assert delivered.state is EvidenceState.ACKNOWLEDGED
    assert delivered.publication_kind is EvidencePublicationKind.UPLOAD
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
    assert [event.attributes["result"] for event in diagnostics.events] == [
        "DELIVERY_ATTEMPTED",
        "DELIVERY_SUCCEEDED",
    ]
    assert all(
        event.event_type
        is DiagnosticEventType.EVIDENCE_PUBLICATION_EVALUATED
        for event in diagnostics.events
    )


def test_ack_persistence_failure_retries_exact_api_8_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    client = _Client()
    publisher = _publisher(database, root, client, now=lambda: NOW)
    publisher.recover()
    real_mark_delivered = publisher._mark_delivered
    failures = [RuntimeError("local ACK commit failed")]

    def fail_once(artifact, confirmation) -> None:
        if failures:
            raise failures.pop()
        real_mark_delivered(artifact, confirmation)

    monkeypatch.setattr(publisher, "_mark_delivered", fail_once)

    with pytest.raises(RuntimeError, match="local ACK commit failed"):
        publisher.publish_once()
    assert publisher.recover_in_flight() == 1
    assert publisher.publish_once() is True

    assert len(client.uploads) == 2
    first_request, first_key = client.uploads[0]
    second_request, second_key = client.uploads[1]
    assert first_request == second_request
    assert first_key == second_key == (
        f"EvidenceArtifact:{ready.evidence_id}:1"
    )
    delivered = _artifact(database, ready.evidence_id)
    assert delivered.publication_kind is EvidencePublicationKind.UPLOAD
    assert delivered.delivery_state is DeliveryState.DELIVERED
    assert delivered.delivery_attempt_count == 2


def test_evidence_waits_for_incident_ack_then_publishes_without_identity_change(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root, parent_delivered=False)
    client = _Client()
    publisher = _publisher(database, root, client, now=lambda: NOW)

    assert publisher.recover() == 0
    assert publisher.publish_once() is False
    waiting = _artifact(database, ready.evidence_id)
    assert waiting.delivery_state is None
    assert waiting.delivery_attempt_count == 0
    assert client.uploads == []

    connection = connect_database(database)
    try:
        _deliver_parent_open(connection, ready)
    finally:
        connection.close()

    assert publisher.publish_once() is True
    assert [key for _, key in client.uploads] == [
        f"EvidenceArtifact:{ready.evidence_id}:1"
    ]


def test_evidence_unavailable_also_waits_for_incident_ack(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    failed = _seed_failed(database, parent_delivered=False)
    client = _Client()
    publisher = _publisher(database, root, client, now=lambda: NOW)

    assert publisher.recover() == 0
    assert publisher.publish_once() is False
    assert client.unavailable == []

    connection = connect_database(database)
    try:
        _deliver_parent_open(connection, failed)
    finally:
        connection.close()

    assert publisher.publish_once() is True
    assert [key for _, key in client.unavailable] == [
        f"EvidenceUnavailable:{failed.evidence_id}:1"
    ]


def test_retryable_api_8_failure_uses_durable_exponential_backoff(
    tmp_path: Path,
    caplog,
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

    with caplog.at_level(
        logging.WARNING,
        logger="src.application.evidence_publication_worker",
    ):
        assert publisher.publish_once() is True
    assert "Backend evidence publication 재시도가 예약됐습니다." in caplog.text
    assert "publicationType=UPLOAD" in caplog.text
    assert "attempt=1" in caplog.text
    assert "RetryableBackendPublicationError: offline" in caplog.text
    waiting = _artifact(database, ready.evidence_id)
    assert waiting.state is EvidenceState.READY
    assert waiting.publication_kind is EvidencePublicationKind.UPLOAD
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
    assert delivered.publication_kind is EvidencePublicationKind.UNAVAILABLE
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
    assert waiting.publication_kind is EvidencePublicationKind.UNAVAILABLE
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
    assert unavailable.publication_kind is None
    assert unavailable.delivery_state is DeliveryState.PENDING
    assert (
        unavailable.retention_disposition
        is EvidenceRetentionDisposition.LOST_OR_CORRUPTED
    )
    assert publisher.publish_once() is True
    assert _artifact(database, ready.evidence_id).delivery_state is (
        DeliveryState.DELIVERED
    )
    assert _artifact(database, ready.evidence_id).publication_kind is (
        EvidencePublicationKind.UNAVAILABLE
    )


def test_dispatched_api_8_never_switches_to_api_9_after_binary_loss(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    now = [NOW]
    client = _Client(
        upload_results=(RetryableBackendPublicationError("ACK lost"),)
    )
    publisher = _publisher(database, root, client, now=lambda: now[0])
    publisher.recover()

    assert publisher.publish_once() is True
    waiting = _artifact(database, ready.evidence_id)
    assert waiting.publication_kind is EvidencePublicationKind.UPLOAD
    assert waiting.delivery_state is DeliveryState.RETRY_WAIT
    assert ready.local_path is not None
    ready.local_path.write_bytes(b"corrupted after dispatch")

    now[0] = NOW + timedelta(seconds=1)
    assert publisher.publish_once() is True
    terminal = _artifact(database, ready.evidence_id)
    assert terminal.state is EvidenceState.FAILED
    assert terminal.publication_kind is EvidencePublicationKind.UPLOAD
    assert terminal.delivery_state is DeliveryState.FAILED_TERMINAL
    assert terminal.local_path is None
    assert terminal.last_delivery_error is not None
    assert terminal.last_delivery_error.startswith("UPLOAD_OUTCOME_UNKNOWN:")
    assert publisher.publish_once() is False
    assert [key for _, key in client.uploads] == [
        f"EvidenceArtifact:{ready.evidence_id}:1"
    ]
    assert client.unavailable == []


def test_restart_with_dispatched_upload_and_missing_binary_does_not_send_api_9(
    tmp_path: Path,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    ready = _seed_ready(database, root)
    connection = connect_database(database)
    try:
        with UnitOfWork(connection):
            repository = EvidenceArtifactRepository(connection)
            claimed = repository.claim_next_delivery(now=NOW)
            assert claimed is not None
            dispatched = repository.mark_upload_dispatch_started(
                claimed.evidence_id,
                expected_record_version=claimed.record_version,
                started_at=NOW,
            )
    finally:
        connection.close()
    assert dispatched.publication_kind is EvidencePublicationKind.UPLOAD
    assert ready.local_path is not None
    ready.local_path.unlink()

    client = _Client()
    restarted = _publisher(database, root, client, now=lambda: NOW)
    assert restarted.recover() == 0
    terminal = _artifact(database, ready.evidence_id)
    assert terminal.delivery_state is DeliveryState.FAILED_TERMINAL
    assert terminal.publication_kind is EvidencePublicationKind.UPLOAD
    assert restarted.publish_once() is False
    assert client.uploads == []
    assert client.unavailable == []


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
    caplog,
) -> None:
    database = tmp_path / "jetson.db"
    root = tmp_path / "evidence"
    failed = _seed_failed(database)
    client = _Client(
        unavailable_results=(TerminalBackendPublicationError("invalid"),)
    )
    publisher = _publisher(database, root, client, now=lambda: NOW)
    publisher.recover()

    with caplog.at_level(
        logging.ERROR,
        logger="src.application.evidence_publication_worker",
    ):
        assert publisher.publish_once() is True
    assert (
        "Backend evidence publication이 영구 실패로 격리됐습니다."
        in caplog.text
    )
    assert "publicationType=UNAVAILABLE" in caplog.text
    assert "attempt=1" in caplog.text
    assert "TerminalBackendPublicationError: invalid" in caplog.text
    terminal = _artifact(database, failed.evidence_id)
    assert terminal.delivery_state is DeliveryState.FAILED_TERMINAL
    assert publisher.publish_once() is False


def _publisher(
    database,
    root,
    client,
    *,
    now,
    diagnostics_sink=None,
) -> EvidencePublicationPublisher:
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
        diagnostics_sink=diagnostics_sink,
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


def _seed_ready(
    database: Path,
    root: Path,
    *,
    parent_delivered: bool = True,
) -> EvidenceArtifact:
    connection = open_database(database)
    artifact = _reserved()
    try:
        with UnitOfWork(connection):
            EvidenceArtifactRepository(connection).add(artifact)
            _enqueue_parent_open(connection, artifact)
        ready = EvidenceSpool(
            connection=connection,
            root=root,
            spool_cap_bytes=1_000_000,
            filesystem_floor_ratio=0.0,
            capture_stop_free_ratio=0.0,
        ).store_jpeg(artifact.evidence_id, JPEG, now=NOW)
        if parent_delivered:
            _deliver_parent_open(connection, artifact)
        return ready
    finally:
        connection.close()


def _seed_failed(
    database: Path,
    *,
    parent_delivered: bool = True,
) -> EvidenceArtifact:
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
            _enqueue_parent_open(connection, artifact)
        if parent_delivered:
            _deliver_parent_open(connection, artifact)
        return failed
    finally:
        connection.close()


def _enqueue_parent_open(
    connection,
    artifact: EvidenceArtifact,
) -> None:
    revision = artifact.publication_revision
    assert revision is not None
    OutboxRepository(connection).enqueue(
        delivery_id=f"incident:{artifact.incident_id}:{revision}",
        aggregate_type="Incident",
        aggregate_id=str(artifact.incident_id),
        destination="backend",
        publication_revision=revision,
        transition_type="OPEN",
        payload=f'{{"incidentId":"{artifact.incident_id}"}}'.encode(),
        idempotency_key=f"Incident:{artifact.incident_id}:{revision}",
        created_at_us=1,
    )


def _deliver_parent_open(
    connection,
    artifact: EvidenceArtifact,
) -> None:
    repository = OutboxRepository(connection)
    with UnitOfWork(connection):
        claimed = repository.claim_next(destination="backend", now_us=2)
    assert claimed is not None
    assert claimed.aggregate_id == str(artifact.incident_id)
    with UnitOfWork(connection):
        repository.mark_delivered(
            claimed.delivery_id,
            expected_record_version=claimed.record_version,
            application_status=PublicationApplicationStatus.APPLIED,
            confirmed_payload_hash=claimed.payload_hash,
            confirmed_at_us=3,
            receipt_expires_at_us=1_000,
        )


def _artifact(database: Path, evidence_id: EvidenceId) -> EvidenceArtifact:
    connection = connect_database(database)
    try:
        artifact = EvidenceArtifactRepository(connection).get(evidence_id)
    finally:
        connection.close()
    assert artifact is not None
    return artifact

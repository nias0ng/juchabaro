"""Evidence metadata repository의 UoW·optimistic state·retention 계약."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from src.domain.models import DeliveryState
from src.evidence.models import EvidenceArtifact, EvidenceId, EvidenceState
from src.parking.models import IncidentId
from src.storage.database import open_database
from src.storage.evidence_repository import (
    EvidenceArtifactConflictError,
    EvidenceArtifactRepository,
)
from src.storage.models import PublicationApplicationStatus
from src.storage.repositories import OptimisticConcurrencyError, OutboxRepository
from src.storage.unit_of_work import TransactionStateError, UnitOfWork


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _reserved(
    *,
    incident_id: IncidentId | None = None,
    captured_at: datetime = NOW,
) -> EvidenceArtifact:
    return EvidenceArtifact(
        evidence_id=EvidenceId(uuid4()),
        incident_id=incident_id or IncidentId(uuid4()),
        publication_revision=1,
        captured_at=captured_at,
        image_type="image/jpeg",
        state=EvidenceState.RESERVED,
        record_version=1,
        created_at=captured_at,
        updated_at=captured_at,
    )


def _save(
    connection,
    repository: EvidenceArtifactRepository,
    current: EvidenceArtifact,
    **changes,
) -> EvidenceArtifact:
    updated = replace(
        current,
        record_version=current.record_version + 1,
        updated_at=changes.pop("updated_at", current.updated_at + timedelta(seconds=1)),
        **changes,
    )
    with UnitOfWork(connection):
        repository.save(updated, expected_record_version=current.record_version)
    return updated


def _ready(
    connection,
    repository: EvidenceArtifactRepository,
    artifact: EvidenceArtifact,
    path: Path,
) -> EvidenceArtifact:
    writing = _save(
        connection,
        repository,
        artifact,
        state=EvidenceState.WRITING,
        local_path=path,
        byte_size=100,
        checksum="sha256:" + "a" * 64,
    )
    return _save(
        connection,
        repository,
        writing,
        state=EvidenceState.READY,
    )


def _enqueue_parent_open(connection, artifact: EvidenceArtifact):
    revision = artifact.publication_revision
    assert revision is not None
    repository = OutboxRepository(connection)
    with UnitOfWork(connection):
        return repository.enqueue(
            delivery_id=f"incident:{artifact.incident_id}:{revision}",
            aggregate_type="Incident",
            aggregate_id=str(artifact.incident_id),
            destination="backend",
            publication_revision=revision,
            transition_type="OPEN",
            payload=f'{{"incidentId":"{artifact.incident_id}"}}'.encode(),
            idempotency_key=f"Incident:{artifact.incident_id}:{revision}",
            created_at_us=10,
        ).record


def _set_parent_state(
    connection,
    artifact: EvidenceArtifact,
    state: DeliveryState,
):
    repository = OutboxRepository(connection)
    record = _enqueue_parent_open(connection, artifact)
    if state is DeliveryState.PENDING:
        return record

    with UnitOfWork(connection):
        claimed = repository.claim_next(destination="backend", now_us=100)
    assert claimed is not None and claimed.delivery_id == record.delivery_id
    if state is DeliveryState.IN_FLIGHT:
        return claimed

    with UnitOfWork(connection):
        if state is DeliveryState.RETRY_WAIT:
            return repository.schedule_retry(
                claimed.delivery_id,
                expected_record_version=claimed.record_version,
                next_attempt_at_us=300,
                error="offline",
                updated_at_us=200,
            )
        if state is DeliveryState.FAILED_TERMINAL:
            return repository.mark_failed_terminal(
                claimed.delivery_id,
                expected_record_version=claimed.record_version,
                error="invalid parent",
                updated_at_us=200,
            )
        assert state is DeliveryState.DELIVERED
        return repository.mark_delivered(
            claimed.delivery_id,
            expected_record_version=claimed.record_version,
            application_status=PublicationApplicationStatus.APPLIED,
            confirmed_payload_hash=claimed.payload_hash,
            confirmed_at_us=200,
            receipt_expires_at_us=2_000,
        )


def test_repository_requires_uow_round_trips_and_rejects_stale_updates(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EvidenceArtifactRepository(connection)
    artifact = _reserved()
    try:
        with pytest.raises(TransactionStateError):
            repository.add(artifact)

        with UnitOfWork(connection):
            repository.add(artifact)
        assert repository.get(artifact.evidence_id) == artifact

        ready = _ready(
            connection,
            repository,
            artifact,
            tmp_path / f"{artifact.evidence_id}.jpg",
        )
        uploading = _save(
            connection,
            repository,
            ready,
            state=EvidenceState.UPLOADING,
        )
        assert repository.get(artifact.evidence_id) == uploading

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.save(uploading, expected_record_version=ready.record_version)

        redirected = replace(
            uploading,
            local_path=tmp_path / "different.jpg",
            record_version=uploading.record_version + 1,
            updated_at=uploading.updated_at + timedelta(seconds=1),
        )
        with pytest.raises(EvidenceArtifactConflictError, match="redirected"):
            with UnitOfWork(connection):
                repository.save(
                    redirected,
                    expected_record_version=uploading.record_version,
                )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "parent_state",
    (
        None,
        DeliveryState.PENDING,
        DeliveryState.IN_FLIGHT,
        DeliveryState.RETRY_WAIT,
        DeliveryState.FAILED_TERMINAL,
    ),
    ids=("missing", "pending", "in-flight", "retry-wait", "terminal"),
)
def test_delivery_claim_waits_for_incident_open_ack(
    tmp_path: Path,
    parent_state: DeliveryState | None,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EvidenceArtifactRepository(connection)
    artifact = _reserved()
    try:
        with UnitOfWork(connection):
            repository.add(artifact)
        ready = _ready(
            connection,
            repository,
            artifact,
            tmp_path / f"{artifact.evidence_id}.jpg",
        )
        if parent_state is not None:
            _set_parent_state(connection, ready, parent_state)

        before = repository.get(ready.evidence_id)
        with UnitOfWork(connection):
            claimed = repository.claim_next_delivery(now=NOW)

        assert claimed is None
        assert repository.get(ready.evidence_id) == before
    finally:
        connection.close()


@pytest.mark.parametrize("receipt_only", (False, True))
def test_delivery_claim_accepts_delivered_parent_or_retained_receipt(
    tmp_path: Path,
    receipt_only: bool,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EvidenceArtifactRepository(connection)
    artifact = _reserved()
    try:
        with UnitOfWork(connection):
            repository.add(artifact)
        ready = _ready(
            connection,
            repository,
            artifact,
            tmp_path / f"{artifact.evidence_id}.jpg",
        )
        parent = _set_parent_state(connection, ready, DeliveryState.DELIVERED)
        if receipt_only:
            with UnitOfWork(connection):
                connection.execute(
                    "DELETE FROM outbox WHERE delivery_id = ?",
                    (parent.delivery_id,),
                )

        with UnitOfWork(connection):
            claimed = repository.claim_next_delivery(now=NOW)

        assert claimed is not None
        assert claimed.evidence_id == ready.evidence_id
        assert claimed.state is EvidenceState.UPLOADING
        assert claimed.delivery_state is DeliveryState.IN_FLIGHT
    finally:
        connection.close()


def test_blocked_oldest_evidence_does_not_starve_an_eligible_incident(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EvidenceArtifactRepository(connection)
    blocked = _reserved(captured_at=NOW - timedelta(days=1))
    eligible = _reserved(captured_at=NOW)
    try:
        with UnitOfWork(connection):
            repository.add(blocked)
            repository.add(eligible)
        blocked_ready = _ready(
            connection,
            repository,
            blocked,
            tmp_path / f"{blocked.evidence_id}.jpg",
        )
        eligible_ready = _ready(
            connection,
            repository,
            eligible,
            tmp_path / f"{eligible.evidence_id}.jpg",
        )
        _set_parent_state(
            connection,
            eligible_ready,
            DeliveryState.DELIVERED,
        )
        _set_parent_state(
            connection,
            blocked_ready,
            DeliveryState.PENDING,
        )

        with UnitOfWork(connection):
            claimed = repository.claim_next_delivery(now=NOW)

        assert claimed is not None
        assert claimed.evidence_id == eligible.evidence_id
        assert repository.get(blocked.evidence_id) == blocked_ready
    finally:
        connection.close()


def test_repository_counts_logical_reservations_and_orders_retention_candidates(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EvidenceArtifactRepository(connection)
    incident_id = IncidentId(uuid4())
    acknowledged = _reserved(
        incident_id=incident_id,
        captured_at=NOW - timedelta(days=10),
    )
    old_ready = _reserved(
        incident_id=incident_id,
        captured_at=NOW - timedelta(days=8),
    )
    recent_ready = _reserved(
        incident_id=IncidentId(uuid4()),
        captured_at=NOW - timedelta(hours=1),
    )
    try:
        with UnitOfWork(connection):
            repository.add(acknowledged)
            repository.add(old_ready)
            repository.add(recent_ready)

        acknowledged_ready = _ready(
            connection,
            repository,
            acknowledged,
            tmp_path / f"{acknowledged.evidence_id}.jpg",
        )
        acknowledged_artifact = _save(
            connection,
            repository,
            acknowledged_ready,
            state=EvidenceState.ACKNOWLEDGED,
            backend_acked_at=NOW - timedelta(days=2),
        )
        old_ready_artifact = _ready(
            connection,
            repository,
            old_ready,
            tmp_path / f"{old_ready.evidence_id}.jpg",
        )
        _ready(
            connection,
            repository,
            recent_ready,
            tmp_path / f"{recent_ready.evidence_id}.jpg",
        )

        assert repository.count_for_incident(incident_id) == 2
        assert repository.byte_size_for_incident(incident_id) == 200
        assert repository.byte_size_for_incident(
            incident_id,
            excluding=old_ready.evidence_id,
        ) == 100

        candidates = repository.list_retention_candidates(
            acknowledged_before=NOW - timedelta(hours=24),
            unacknowledged_before=NOW - timedelta(days=7),
        )
        assert candidates == (acknowledged_artifact, old_ready_artifact)
        assert repository.list_pressure_candidates()[0] == acknowledged_artifact
    finally:
        connection.close()


def test_repository_preserves_storage_only_backend_ack_payload(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = EvidenceArtifactRepository(connection)
    artifact = _reserved()
    try:
        with UnitOfWork(connection):
            repository.add(artifact)
            connection.execute(
                "UPDATE evidence_artifacts SET backend_ack_payload = ? WHERE evidence_id = ?",
                (b"opaque-confirmation", str(artifact.evidence_id)),
            )
        _save(
            connection,
            repository,
            artifact,
            state=EvidenceState.WRITING,
            local_path=tmp_path / f"{artifact.evidence_id}.jpg",
            byte_size=100,
            checksum="sha256:" + "a" * 64,
        )

        row = connection.execute(
            "SELECT backend_ack_payload FROM evidence_artifacts WHERE evidence_id = ?",
            (str(artifact.evidence_id),),
        ).fetchone()
        assert bytes(row[0]) == b"opaque-confirmation"
    finally:
        connection.close()

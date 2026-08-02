"""Evidence metadata repository의 UoW·optimistic state·retention 계약."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from src.evidence.models import EvidenceArtifact, EvidenceId, EvidenceState
from src.parking.models import IncidentId
from src.storage.database import open_database
from src.storage.evidence_repository import (
    EvidenceArtifactConflictError,
    EvidenceArtifactRepository,
)
from src.storage.repositories import OptimisticConcurrencyError
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

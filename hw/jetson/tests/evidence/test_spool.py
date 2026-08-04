"""Evidence spool의 atomic write, cap, recovery, durable retention 계약."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.evidence.models import (
    EvidenceArtifact,
    EvidenceId,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.evidence.spool import (
    DEFAULT_ARTIFACT_MAX_BYTES,
    EvidenceIntegrityError,
    EvidenceResourceLimitError,
    EvidenceSpool,
)
import src.evidence.spool as spool_module
from src.parking.models import IncidentId
from src.storage.database import open_database
from src.storage.evidence_repository import (
    EvidenceArtifactConflictError,
    EvidenceArtifactRepository,
)
from src.storage.unit_of_work import UnitOfWork


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
JPEG = b"\xff\xd8" + b"evidence" * 32 + b"\xff\xd9"


def _checksum(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _ample_disk(_path: Path):
    return SimpleNamespace(total=10_000_000, used=0, free=9_000_000)


def _reserved(
    connection,
    *,
    incident_id: IncidentId | None = None,
    captured_at: datetime = NOW,
    publication_revision: int | None = 1,
    image_type: str = "image/jpeg",
) -> EvidenceArtifact:
    artifact = EvidenceArtifact(
        evidence_id=EvidenceId(uuid4()),
        incident_id=incident_id or IncidentId(uuid4()),
        publication_revision=publication_revision,
        captured_at=captured_at,
        image_type=image_type,
        state=EvidenceState.RESERVED,
        record_version=1,
        created_at=captured_at,
        updated_at=captured_at,
    )
    with UnitOfWork(connection):
        EvidenceArtifactRepository(connection).add(artifact)
    return artifact


def _transition(connection, artifact: EvidenceArtifact, **changes) -> EvidenceArtifact:
    updated = replace(
        artifact,
        record_version=artifact.record_version + 1,
        updated_at=changes.pop("updated_at", artifact.updated_at + timedelta(seconds=1)),
        **changes,
    )
    with UnitOfWork(connection):
        EvidenceArtifactRepository(connection).save(
            updated,
            expected_record_version=artifact.record_version,
        )
    return updated


def _spool(connection, root: Path, *, cap: int = 100_000, **kwargs) -> EvidenceSpool:
    return EvidenceSpool(
        connection=connection,
        root=root,
        spool_cap_bytes=cap,
        filesystem_floor_ratio=kwargs.pop("filesystem_floor_ratio", 0.0),
        disk_usage=kwargs.pop("disk_usage", _ample_disk),
        **kwargs,
    )


def test_store_jpeg_fsyncs_file_then_renames_and_fsyncs_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    root = tmp_path / "evidence"
    artifact = _reserved(connection)
    events: list[str] = []
    real_fsync = spool_module.os.fsync
    real_replace = spool_module.os.replace
    spool = _spool(connection, root)

    def tracked_fsync(descriptor: int) -> None:
        events.append("fsync")
        real_fsync(descriptor)

    def tracked_replace(source, destination) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(spool_module.os, "fsync", tracked_fsync)
    monkeypatch.setattr(spool_module.os, "replace", tracked_replace)
    try:
        ready = spool.store_jpeg(artifact.evidence_id, JPEG, now=NOW)

        assert ready.state is EvidenceState.READY
        assert ready.local_path == root.resolve() / f"{artifact.evidence_id}.jpg"
        assert ready.local_path.read_bytes() == JPEG
        assert ready.byte_size == len(JPEG)
        assert ready.checksum is not None and ready.checksum.startswith("sha256:")
        assert not (root / f"{artifact.evidence_id}.jpg.part").exists()
        assert events == (
            ["fsync", "replace"]
            if os.name == "nt"
            else ["fsync", "replace", "fsync"]
        )
        assert EvidenceArtifactRepository(connection).get(artifact.evidence_id) == ready

        # An exact command retry reuses the immutable file and does not rewrite it.
        assert spool.store_jpeg(
            artifact.evidence_id,
            JPEG,
            now=NOW,
        ) == ready
        with pytest.raises(EvidenceIntegrityError, match="already owns different bytes"):
            spool.store_jpeg(
                artifact.evidence_id,
                b"different bytes are rejected after READY",
                now=NOW,
            )
        assert ready.local_path.read_bytes() == JPEG
        assert EvidenceArtifactRepository(connection).get(artifact.evidence_id) == ready
    finally:
        connection.close()


def test_store_enforces_artifact_incident_spool_and_filesystem_limits(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        invalid_payload = _reserved(connection)
        with pytest.raises(TypeError, match="bytes-like"):
            _spool(connection, tmp_path / "invalid-payload").store_jpeg(
                invalid_payload.evidence_id,
                1,  # type: ignore[arg-type]
                now=NOW,
            )
        assert (
            EvidenceArtifactRepository(connection).get(invalid_payload.evidence_id)
            == invalid_payload
        )

        oversized = _reserved(connection)
        with pytest.raises(EvidenceResourceLimitError) as oversized_error:
            _spool(connection, tmp_path / "oversized").store_jpeg(
                oversized.evidence_id,
                b"\xff\xd8" + b"x" * DEFAULT_ARTIFACT_MAX_BYTES + b"\xff\xd9",
                now=NOW,
            )
        assert oversized_error.value.artifact.state is EvidenceState.FAILED
        assert (
            oversized_error.value.artifact.retention_disposition
            is EvidenceRetentionDisposition.RESOURCE_LIMIT
        )

        incident_id = IncidentId(uuid4())
        first = _reserved(connection, incident_id=incident_id)
        second = _reserved(connection, incident_id=incident_id)
        # BEGIN IMMEDIATE makes the logical two-artifact reservation limit atomic.
        with pytest.raises(EvidenceArtifactConflictError, match="at most two"):
            _reserved(connection, incident_id=incident_id)
        assert EvidenceArtifactRepository(connection).count_for_incident(incident_id) == 2
        assert first.state is EvidenceState.RESERVED and second.state is EvidenceState.RESERVED

        quota = _reserved(connection)
        quota_root = tmp_path / "quota"
        quota_root.mkdir()
        (quota_root / "operator-owned.dat").write_bytes(b"x" * 32)
        with pytest.raises(EvidenceIntegrityError, match="non-empty directory"):
            _spool(connection, quota_root, cap=32 + len(JPEG) - 1)

        safe_quota_root = tmp_path / "safe-quota"
        quota_spool = _spool(
            connection,
            safe_quota_root,
            cap=32 + len(JPEG) - 1,
        )
        (safe_quota_root / "operator-owned.dat").write_bytes(b"x" * 32)
        with pytest.raises(EvidenceResourceLimitError, match="configured cap"):
            quota_spool.store_jpeg(
                quota.evidence_id,
                JPEG,
                now=NOW,
            )
        assert (safe_quota_root / "operator-owned.dat").exists()

        floor = _reserved(connection)
        floor_usage = lambda _path: SimpleNamespace(total=1_000, used=750, free=250)
        with pytest.raises(EvidenceResourceLimitError, match="free-space floor"):
            _spool(
                connection,
                tmp_path / "floor",
                cap=10_000,
                filesystem_floor_ratio=0.30,
                disk_usage=floor_usage,
            ).store_jpeg(floor.evidence_id, JPEG, now=NOW)

        capture_stop = _reserved(connection)
        capture_stop_usage = lambda _path: SimpleNamespace(
            total=1_000,
            used=400,
            free=600,
        )
        with pytest.raises(EvidenceResourceLimitError, match="capture-stop"):
            _spool(
                connection,
                tmp_path / "capture-stop",
                cap=10_000,
                filesystem_floor_ratio=0.30,
                capture_stop_free_ratio=0.35,
                disk_usage=capture_stop_usage,
            ).store_jpeg(capture_stop.evidence_id, JPEG, now=NOW)

        with pytest.raises(ValueError, match="capture_stop_free_ratio"):
            _spool(
                connection,
                tmp_path / "invalid-ratios",
                filesystem_floor_ratio=0.40,
                capture_stop_free_ratio=0.35,
            )
        with pytest.raises(ValueError, match="2MiB"):
            _spool(
                connection,
                tmp_path / "invalid-artifact-limit",
                artifact_max_bytes=DEFAULT_ARTIFACT_MAX_BYTES + 1,
            )

        wrong_type = _reserved(connection, image_type="image/png")
        with pytest.raises(EvidenceIntegrityError, match="image/jpeg"):
            _spool(connection, tmp_path / "wrong-type").store_jpeg(
                wrong_type.evidence_id,
                JPEG,
                now=NOW,
            )
        failed_type = EvidenceArtifactRepository(connection).get(wrong_type.evidence_id)
        assert failed_type is not None
        assert failed_type.state is EvidenceState.FAILED
        assert (
            failed_type.retention_disposition
            is EvidenceRetentionDisposition.LOST_OR_CORRUPTED
        )
    finally:
        connection.close()


def test_recovery_reconciles_interrupted_files_uploads_evictions_and_corruption(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    root = tmp_path / "evidence"
    spool = _spool(connection, root, cap=1_000_000)
    repository = EvidenceArtifactRepository(connection)
    try:
        corrupted = spool.store_jpeg(_reserved(connection).evidence_id, JPEG, now=NOW)
        assert corrupted.local_path is not None
        corrupted.local_path.write_bytes(b"corrupted")

        writing = _reserved(connection)
        writing_path = root / f"{writing.evidence_id}.jpg"
        writing = _transition(
            connection,
            writing,
            state=EvidenceState.WRITING,
            local_path=writing_path,
            byte_size=len(JPEG),
            checksum=_checksum(JPEG),
        )
        writing_path.write_bytes(JPEG)

        uploading = spool.store_jpeg(_reserved(connection).evidence_id, JPEG, now=NOW)
        uploading = _transition(
            connection,
            uploading,
            state=EvidenceState.UPLOADING,
        )

        pending = spool.store_jpeg(_reserved(connection).evidence_id, JPEG, now=NOW)
        pending = _transition(
            connection,
            pending,
            state=EvidenceState.EVICTION_PENDING,
            retention_disposition=EvidenceRetentionDisposition.STORAGE_PRESSURE,
        )

        interrupted_reservation = _reserved(connection)
        external = tmp_path / "must-not-delete.jpg"
        external.write_bytes(JPEG)
        unsafe = _reserved(connection)
        unsafe = _transition(
            connection,
            unsafe,
            state=EvidenceState.WRITING,
            local_path=external,
            byte_size=len(JPEG),
            checksum="sha256:" + "0" * 64,
        )
        unsafe = _transition(
            connection,
            unsafe,
            state=EvidenceState.READY,
        )

        orphan_id = uuid4()
        (root / f"{orphan_id}.jpg").write_bytes(JPEG)
        part_id = uuid4()
        (root / f"{part_id}.jpg.part").write_bytes(b"partial")

        report = spool.recover(now=NOW + timedelta(minutes=1))

        assert report.removed_part_files == 1
        assert report.removed_orphan_files == 1
        assert report.restored_ready_files == 1
        assert report.reset_uploads == 1
        assert report.completed_evictions == 1
        assert report.failed_artifacts == 3
        # Corruption, interrupted reservation, unsafe external path, and the
        # completed pressure eviction are all already bound to publication 1.
        assert len(report.externally_bound_losses) == 4
        assert repository.get(corrupted.evidence_id).state is EvidenceState.FAILED
        assert repository.get(writing.evidence_id).state is EvidenceState.READY
        assert repository.get(uploading.evidence_id).state is EvidenceState.READY
        assert repository.get(pending.evidence_id).state is EvidenceState.EVICTED
        assert (
            repository.get(interrupted_reservation.evidence_id).state
            is EvidenceState.FAILED
        )
        assert repository.get(unsafe.evidence_id).state is EvidenceState.FAILED
        assert external.exists(), "stored paths outside the managed spool must never be unlinked"
        assert len(spool.list_unavailable_candidates()) == 4
        # The recovery report is one-run telemetry, while DB candidates remain durable for
        # idempotent outbox materialization after another crash.
        assert spool.recover(now=NOW + timedelta(minutes=2)).externally_bound_losses == ()
        assert len(spool.list_unavailable_candidates()) == 4
    finally:
        connection.close()


def test_recovery_rejects_writing_file_that_differs_from_intended_payload(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    root = tmp_path / "evidence"
    spool = _spool(connection, root, cap=1_000_000)
    repository = EvidenceArtifactRepository(connection)
    try:
        artifact = _reserved(connection)
        final_path = root / f"{artifact.evidence_id}.jpg"
        writing = _transition(
            connection,
            artifact,
            state=EvidenceState.WRITING,
            local_path=final_path,
            byte_size=len(JPEG),
            checksum=_checksum(JPEG),
        )
        different_jpeg = b"\xff\xd8" + b"different" * 32 + b"\xff\xd9"
        final_path.write_bytes(different_jpeg)

        report = spool.recover(now=NOW + timedelta(minutes=1))

        assert report.restored_ready_files == 0
        assert report.failed_artifacts == 1
        failed = repository.get(writing.evidence_id)
        assert failed is not None
        assert failed.state is EvidenceState.FAILED
        assert failed.byte_size == len(JPEG)
        assert failed.checksum == _checksum(JPEG)
        assert not final_path.exists()
    finally:
        connection.close()


def test_pressure_eviction_continues_after_corrupted_candidate(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    root = tmp_path / "evidence"
    spool = _spool(connection, root, cap=1_000_000)
    repository = EvidenceArtifactRepository(connection)
    try:
        corrupted = spool.store_jpeg(
            _reserved(connection, captured_at=NOW - timedelta(hours=4)).evidence_id,
            JPEG,
            now=NOW - timedelta(hours=4),
        )
        corrupted = _transition(
            connection,
            corrupted,
            state=EvidenceState.ACKNOWLEDGED,
            backend_acked_at=NOW - timedelta(hours=3),
            updated_at=NOW - timedelta(hours=3),
        )
        valid = spool.store_jpeg(
            _reserved(connection, captured_at=NOW - timedelta(hours=2)).evidence_id,
            JPEG,
            now=NOW - timedelta(hours=2),
        )
        valid = _transition(
            connection,
            valid,
            state=EvidenceState.ACKNOWLEDGED,
            backend_acked_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
        assert corrupted.local_path is not None
        corrupted.local_path.write_bytes(b"corrupted")

        evicted = spool.evict_for_pressure(len(JPEG) + 1, now=NOW)

        assert [item.evidence_id for item in evicted] == [valid.evidence_id]
        failed = repository.get(corrupted.evidence_id)
        assert failed is not None
        assert failed.state is EvidenceState.FAILED
        assert (
            failed.retention_disposition
            is EvidenceRetentionDisposition.LOST_OR_CORRUPTED
        )
        assert not (root / f"{corrupted.evidence_id}.jpg").exists()
        assert repository.get(valid.evidence_id).state is EvidenceState.EVICTED
    finally:
        connection.close()


def test_retention_and_pressure_eviction_are_durable_and_ack_first(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    root = tmp_path / "evidence"
    spool = _spool(connection, root, cap=1_000_000)
    repository = EvidenceArtifactRepository(connection)
    try:
        ack = _reserved(connection, captured_at=NOW - timedelta(days=10))
        ack = spool.store_jpeg(ack.evidence_id, JPEG, now=NOW - timedelta(days=3))
        ack = _transition(
            connection,
            ack,
            state=EvidenceState.ACKNOWLEDGED,
            backend_acked_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(days=2),
        )
        unacked = _reserved(connection, captured_at=NOW - timedelta(days=8))
        unacked = spool.store_jpeg(
            unacked.evidence_id,
            JPEG,
            now=NOW - timedelta(days=7),
        )
        recent_ack = _reserved(connection, captured_at=NOW - timedelta(hours=3))
        recent_ack = spool.store_jpeg(
            recent_ack.evidence_id,
            JPEG,
            now=NOW - timedelta(hours=2),
        )
        recent_ack = _transition(
            connection,
            recent_ack,
            state=EvidenceState.ACKNOWLEDGED,
            backend_acked_at=NOW - timedelta(hours=1),
            updated_at=NOW - timedelta(hours=1),
        )
        recent_ready = _reserved(connection, captured_at=NOW - timedelta(hours=2))
        recent_ready = spool.store_jpeg(
            recent_ready.evidence_id,
            JPEG,
            now=NOW - timedelta(hours=1),
        )

        expired = spool.evict_expired(now=NOW)
        assert [item.evidence_id for item in expired] == [
            ack.evidence_id,
            unacked.evidence_id,
        ]
        for artifact in expired:
            assert artifact.state is EvidenceState.EVICTED
            assert artifact.local_path is None
            assert artifact.byte_size == len(JPEG)
            assert artifact.checksum is not None
            assert (
                artifact.retention_disposition
                is EvidenceRetentionDisposition.RETENTION_EXPIRED
            )
            assert not (root / f"{artifact.evidence_id}.jpg").exists()

        pressure = spool.evict_for_pressure(1, now=NOW)
        assert [item.evidence_id for item in pressure] == [recent_ack.evidence_id]
        assert (
            repository.get(recent_ready.evidence_id).state is EvidenceState.READY
        )
        assert (
            pressure[0].retention_disposition
            is EvidenceRetentionDisposition.STORAGE_PRESSURE
        )
        assert [item.evidence_id for item in spool.list_unavailable_candidates()] == [
            unacked.evidence_id
        ]
    finally:
        connection.close()

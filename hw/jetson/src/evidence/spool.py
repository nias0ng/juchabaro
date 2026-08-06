"""Bounded, crash-consistent still-image evidence file spool.

SQLite는 capture identity와 workflow state를 소유하고 JPEG binary는 이
spool에 둔다. 파일과 DB를 하나의 transaction으로 묶을 수 없으므로
``.part``·fsync·atomic rename 순서와 startup reconciliation으로 crash
window를 닫는다. Backend wire payload·upload scheduler는 이 모듈의 책임이 아니다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
from typing import Any
from uuid import UUID

from src.evidence.models import (
    EvidenceArtifact,
    EvidenceId,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.storage.evidence_repository import (
    MAX_EVIDENCE_ARTIFACTS_PER_INCIDENT,
    EvidenceArtifactConflictError,
    EvidenceArtifactRepository,
)
from src.storage.unit_of_work import UnitOfWork


MEBIBYTE = 1024 * 1024
GIBIBYTE = 1024 * MEBIBYTE
MAX_SPOOL_CAP_BYTES = 8 * GIBIBYTE
DEFAULT_ARTIFACT_MAX_BYTES = 2 * MEBIBYTE
DEFAULT_INCIDENT_MAX_ARTIFACTS = 2
DEFAULT_INCIDENT_MAX_BYTES = 4 * MEBIBYTE
DEFAULT_FILESYSTEM_FLOOR_RATIO = 0.30
DEFAULT_CAPTURE_STOP_FREE_RATIO = 0.35
DEFAULT_ACKNOWLEDGED_RETENTION = timedelta(hours=24)
DEFAULT_UNACKNOWLEDGED_RETENTION = timedelta(days=7)

_JPEG_START = b"\xff\xd8"
_JPEG_END = b"\xff\xd9"
_FINAL_NAME = re.compile(
    r"^(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jpg$"
)
_PART_NAME = re.compile(
    r"^(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jpg\.part$"
)
_SPOOL_MARKER_NAME = ".evidence-spool"
_SPOOL_MARKER_CONTENT = b"jetson-evidence-spool-v1\n"


class EvidenceSpoolError(RuntimeError):
    """Evidence binary workflow를 완료하지 못했다."""


class EvidenceStateError(EvidenceSpoolError):
    """현재 durable state에서 요청한 파일 작업을 할 수 없다."""


class EvidenceIntegrityError(EvidenceSpoolError):
    """Metadata와 binary path·size·checksum이 일치하지 않는다."""


class EvidenceResourceLimitError(EvidenceSpoolError):
    """Artifact·Incident·spool·filesystem 상한으로 capture를 거부했다."""

    def __init__(self, message: str, *, artifact: EvidenceArtifact) -> None:
        super().__init__(message)
        self.artifact = artifact


@dataclass(frozen=True)
class EvidenceCapacitySnapshot:
    spool_bytes: int
    spool_cap_bytes: int
    filesystem_total_bytes: int
    filesystem_free_bytes: int
    protected_floor_bytes: int
    capture_stop_free_bytes: int


@dataclass(frozen=True)
class EvidenceRecoveryReport:
    removed_part_files: int = 0
    removed_orphan_files: int = 0
    restored_ready_files: int = 0
    reset_uploads: int = 0
    completed_evictions: int = 0
    failed_artifacts: int = 0
    externally_bound_losses: tuple[EvidenceArtifact, ...] = ()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _checksum(payload: bytes) -> str:
    # Local integrity format. Backend wire checksum encoding remains a separate contract.
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class EvidenceSpool:
    """Single-process evidence writer, recovery scanner, and binary retention owner."""

    def __init__(
        self,
        *,
        connection: sqlite3.Connection,
        root: Path,
        spool_cap_bytes: int,
        filesystem_floor_ratio: float = DEFAULT_FILESYSTEM_FLOOR_RATIO,
        capture_stop_free_ratio: float = DEFAULT_CAPTURE_STOP_FREE_RATIO,
        artifact_max_bytes: int = DEFAULT_ARTIFACT_MAX_BYTES,
        incident_max_artifacts: int = DEFAULT_INCIDENT_MAX_ARTIFACTS,
        incident_max_bytes: int = DEFAULT_INCIDENT_MAX_BYTES,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        if not 0 <= spool_cap_bytes <= MAX_SPOOL_CAP_BYTES:
            raise ValueError(
                f"spool_cap_bytes must be between 0 and {MAX_SPOOL_CAP_BYTES}"
            )
        if not 0.0 <= filesystem_floor_ratio < 1.0:
            raise ValueError("filesystem_floor_ratio must be in [0, 1)")
        if not filesystem_floor_ratio <= capture_stop_free_ratio < 1.0:
            raise ValueError(
                "capture_stop_free_ratio must be in "
                "[filesystem_floor_ratio, 1)"
            )
        if not 0 < artifact_max_bytes <= DEFAULT_ARTIFACT_MAX_BYTES:
            raise ValueError(
                "artifact_max_bytes must be positive and cannot exceed 2MiB"
            )
        if incident_max_artifacts <= 0:
            raise ValueError("incident_max_artifacts must be positive")
        if incident_max_artifacts > MAX_EVIDENCE_ARTIFACTS_PER_INCIDENT:
            raise ValueError(
                "incident_max_artifacts cannot exceed the durable reservation limit"
            )
        if not 0 < incident_max_bytes <= DEFAULT_INCIDENT_MAX_BYTES:
            raise ValueError(
                "incident_max_bytes must be positive and cannot exceed 4MiB"
            )

        self._connection = connection
        self._repository = EvidenceArtifactRepository(connection)
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._initialize_or_validate_root()
        self._spool_cap_bytes = spool_cap_bytes
        self._filesystem_floor_ratio = filesystem_floor_ratio
        self._capture_stop_free_ratio = capture_stop_free_ratio
        self._artifact_max_bytes = artifact_max_bytes
        self._incident_max_artifacts = incident_max_artifacts
        self._incident_max_bytes = incident_max_bytes
        self._disk_usage = disk_usage
        self._lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    def capacity_snapshot(self) -> EvidenceCapacitySnapshot:
        """Filesystem의 현재 값과 configured cap을 재계산한다."""

        usage = self._disk_usage(self._root)
        total = int(usage.total)
        free = int(usage.free)
        return EvidenceCapacitySnapshot(
            spool_bytes=self._spool_usage_bytes(),
            spool_cap_bytes=self._spool_cap_bytes,
            filesystem_total_bytes=total,
            filesystem_free_bytes=free,
            protected_floor_bytes=math.ceil(total * self._filesystem_floor_ratio),
            capture_stop_free_bytes=math.ceil(
                total * self._capture_stop_free_ratio
            ),
        )

    def store_jpeg(
        self,
        evidence_id: EvidenceId,
        payload: bytes | bytearray | memoryview,
        *,
        now: datetime | None = None,
    ) -> EvidenceArtifact:
        """RESERVED capture를 bounded JPEG final file과 READY metadata로 만든다."""

        at = now or _utc_now()
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise TypeError("evidence payload must be bytes-like")
        immutable_payload = bytes(payload)
        checksum = _checksum(immutable_payload)
        with self._lock:
            artifact = self._require_artifact(evidence_id)
            if artifact.state in {
                EvidenceState.READY,
                EvidenceState.UPLOADING,
                EvidenceState.ACKNOWLEDGED,
            }:
                if (
                    artifact.byte_size == len(immutable_payload)
                    and artifact.checksum == checksum
                    and self._binary_matches(artifact)
                ):
                    # Same command retry reuses the immutable durable binary.
                    return artifact
                raise EvidenceIntegrityError(
                    f"evidence identity {evidence_id} already owns different bytes"
                )
            if artifact.state is not EvidenceState.RESERVED:
                raise EvidenceStateError(
                    f"evidence {evidence_id} is {artifact.state.value}, not RESERVED"
                )

            content_error = self._jpeg_content_error(artifact, immutable_payload)
            if content_error is not None:
                self._mark_failed(
                    artifact,
                    at=at,
                    error=content_error,
                    disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
                    byte_size=len(immutable_payload),
                    checksum=checksum,
                )
                raise EvidenceIntegrityError(content_error)

            resource_error = self._resource_limit_error(artifact, immutable_payload)
            if resource_error is not None:
                failed = self._mark_failed(
                    artifact,
                    at=at,
                    error=resource_error,
                    disposition=EvidenceRetentionDisposition.RESOURCE_LIMIT,
                    byte_size=len(immutable_payload),
                    checksum=checksum,
                )
                raise EvidenceResourceLimitError(resource_error, artifact=failed)

            capacity_error = self._capacity_error(len(immutable_payload))
            if capacity_error is not None:
                failed = self._mark_failed(
                    artifact,
                    at=at,
                    error=capacity_error,
                    disposition=EvidenceRetentionDisposition.RESOURCE_LIMIT,
                    byte_size=len(immutable_payload),
                    checksum=checksum,
                )
                raise EvidenceResourceLimitError(capacity_error, artifact=failed)

            part_path = self._part_path(evidence_id)
            final_path = self._final_path(evidence_id)
            writing = replace(
                artifact,
                state=EvidenceState.WRITING,
                local_path=final_path,
                byte_size=len(immutable_payload),
                checksum=checksum,
                record_version=artifact.record_version + 1,
                updated_at=at,
            )
            self._save(writing, expected_record_version=artifact.record_version)

            renamed = False
            try:
                with part_path.open("xb") as handle:
                    handle.write(immutable_payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(part_path, final_path)
                renamed = True
                self._fsync_directory()
            except OSError as error:
                if not renamed:
                    self._unlink_managed(part_path)
                    current = self._require_artifact(evidence_id)
                    self._mark_failed(
                        current,
                        at=at,
                        error=f"binary write failed: {error}",
                        disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
                        byte_size=len(immutable_payload),
                        checksum=checksum,
                    )
                # If rename already happened, leave WRITING + final for startup recovery.
                raise EvidenceSpoolError(
                    f"could not durably store evidence {evidence_id}"
                ) from error

            ready = replace(
                writing,
                state=EvidenceState.READY,
                record_version=writing.record_version + 1,
                updated_at=at,
            )
            # A DB failure here deliberately leaves WRITING + final. recover() verifies and
            # promotes that exact managed file rather than guessing from an arbitrary path.
            self._save(ready, expected_record_version=writing.record_version)
            return ready

    def fail_reservation(
        self,
        evidence_id: EvidenceId,
        *,
        error: str,
        disposition: EvidenceRetentionDisposition = (
            EvidenceRetentionDisposition.LOST_OR_CORRUPTED
        ),
        now: datetime | None = None,
    ) -> EvidenceArtifact:
        """JPEG 생성 전에 실패한 RESERVED capture를 durable loss로 남긴다."""

        if not error:
            raise ValueError("error must not be empty")
        at = now or _utc_now()
        with self._lock:
            try:
                with UnitOfWork(self._connection):
                    return self._repository.mark_capture_failed(
                        evidence_id,
                        failed_at=at,
                        error=error,
                        disposition=disposition,
                    )
            except EvidenceArtifactConflictError as conflict:
                raise EvidenceStateError(str(conflict)) from conflict

    def reconcile_interrupted_write(
        self,
        evidence_id: EvidenceId,
        *,
        now: datetime | None = None,
    ) -> EvidenceArtifact:
        """단일 WRITING artifact를 현재 final file 기준 READY/FAILED로 종결한다."""

        at = now or _utc_now()
        with self._lock:
            artifact = self._require_artifact(evidence_id)
            if artifact.state is not EvidenceState.WRITING:
                raise EvidenceStateError(
                    f"evidence {evidence_id} is {artifact.state.value}, not WRITING"
                )
            # rename 뒤 directory fsync가 실패한 경우 file이 현재 보인다는 사실만으로
            # READY를 선언할 수 없다. directory entry를 다시 durable하게 만든 뒤
            # 기존 startup recovery와 동일한 binary 검증을 수행한다.
            self._fsync_directory()
            return self._recover_writing(
                artifact,
                final_path=self._final_path(evidence_id),
                at=at,
            )

    def recover(self, *, now: datetime | None = None) -> EvidenceRecoveryReport:
        """Worker start 전에 interrupted write·upload·eviction을 reconciliation한다."""

        at = now or _utc_now()
        with self._lock:
            removed_parts = 0
            removed_orphans = 0
            restored = 0
            reset_uploads = 0
            completed_evictions = 0
            failed = 0
            losses: list[EvidenceArtifact] = []

            for path in tuple(self._root.iterdir()):
                if _PART_NAME.fullmatch(path.name) is not None:
                    self._unlink_managed(path)
                    removed_parts += 1

            artifacts = {
                artifact.evidence_id: artifact for artifact in self._repository.list_all()
            }
            for evidence_id, artifact in artifacts.items():
                final_path = self._final_path(evidence_id)

                if artifact.state is EvidenceState.EVICTION_PENDING:
                    evicted = self._complete_eviction(artifact, at=at)
                    completed_evictions += 1
                    if self._requires_unavailable(evicted):
                        losses.append(evicted)
                    continue

                if artifact.state is EvidenceState.RESERVED:
                    if final_path.exists() or final_path.is_symlink():
                        self._unlink_managed(final_path)
                        removed_orphans += 1
                    failed_artifact = self._mark_failed(
                        artifact,
                        at=at,
                        error="capture interrupted before binary write",
                        disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
                    )
                    failed += 1
                    if self._requires_unavailable(failed_artifact):
                        losses.append(failed_artifact)
                    continue

                if artifact.state is EvidenceState.WRITING:
                    recovered = self._recover_writing(artifact, final_path=final_path, at=at)
                    if recovered.state is EvidenceState.READY:
                        restored += 1
                    else:
                        failed += 1
                        if self._requires_unavailable(recovered):
                            losses.append(recovered)
                    continue

                if artifact.state in {
                    EvidenceState.READY,
                    EvidenceState.UPLOADING,
                    EvidenceState.ACKNOWLEDGED,
                }:
                    if not self._binary_matches(artifact):
                        self._unlink_managed(final_path)
                        failed_artifact = self._mark_failed(
                            artifact,
                            at=at,
                            error="READY evidence file is missing or corrupted",
                            disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
                        )
                        failed += 1
                        if self._requires_unavailable(failed_artifact):
                            losses.append(failed_artifact)
                    elif artifact.state is EvidenceState.UPLOADING:
                        ready = replace(
                            artifact,
                            state=EvidenceState.READY,
                            record_version=artifact.record_version + 1,
                            updated_at=at,
                        )
                        self._save(ready, expected_record_version=artifact.record_version)
                        reset_uploads += 1
                    continue

                # FAILED/EVICTED metadata must never regain a managed binary implicitly.
                if final_path.exists() or final_path.is_symlink():
                    self._unlink_managed(final_path)
                    removed_orphans += 1

            known_ids = set(artifacts)
            for path in tuple(self._root.iterdir()):
                matched = _FINAL_NAME.fullmatch(path.name)
                if matched is None:
                    continue
                evidence_id = EvidenceId(UUID(matched.group("id")))
                if evidence_id not in known_ids:
                    self._unlink_managed(path)
                    removed_orphans += 1

            return EvidenceRecoveryReport(
                removed_part_files=removed_parts,
                removed_orphan_files=removed_orphans,
                restored_ready_files=restored,
                reset_uploads=reset_uploads,
                completed_evictions=completed_evictions,
                failed_artifacts=failed,
                externally_bound_losses=tuple(losses),
            )

    def evict(
        self,
        evidence_id: EvidenceId,
        disposition: EvidenceRetentionDisposition,
        *,
        now: datetime | None = None,
    ) -> EvidenceArtifact:
        """EVICTION_PENDING commit 후 binary를 지우고 EVICTED를 commit한다."""

        if disposition not in {
            EvidenceRetentionDisposition.RETENTION_EXPIRED,
            EvidenceRetentionDisposition.STORAGE_PRESSURE,
        }:
            raise ValueError("eviction disposition must describe retention or pressure")
        at = now or _utc_now()
        with self._lock:
            artifact = self._require_artifact(evidence_id)
            if artifact.state not in {
                EvidenceState.READY,
                EvidenceState.ACKNOWLEDGED,
            }:
                raise EvidenceStateError(
                    f"cannot evict evidence in {artifact.state.value} state"
                )
            if not self._binary_matches(artifact):
                failed = self._mark_failed(
                    artifact,
                    at=at,
                    error="evidence file is missing or corrupted before eviction",
                    disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
                )
                final_path = self._final_path(artifact.evidence_id)
                try:
                    self._unlink_managed(final_path)
                except OSError as error:
                    raise EvidenceIntegrityError(
                        "corrupted evidence was marked FAILED but its managed "
                        f"file could not be removed: {failed.evidence_id}"
                    ) from error
                raise EvidenceIntegrityError(
                    "corrupted evidence was marked FAILED and its managed file "
                    f"was removed: {failed.evidence_id}"
                )

            pending = replace(
                artifact,
                state=EvidenceState.EVICTION_PENDING,
                retention_disposition=disposition,
                record_version=artifact.record_version + 1,
                updated_at=at,
            )
            self._save(pending, expected_record_version=artifact.record_version)
            return self._complete_eviction(pending, at=at)

    def evict_expired(
        self,
        *,
        now: datetime | None = None,
        acknowledged_retention: timedelta = DEFAULT_ACKNOWLEDGED_RETENTION,
        unacknowledged_retention: timedelta = DEFAULT_UNACKNOWLEDGED_RETENTION,
    ) -> tuple[EvidenceArtifact, ...]:
        """Configured retention을 넘긴 binary를 ACK-first 순서로 정리한다."""

        if acknowledged_retention < timedelta(0) or unacknowledged_retention < timedelta(0):
            raise ValueError("retention durations must be non-negative")
        at = now or _utc_now()
        with self._lock:
            candidates = self._repository.list_retention_candidates(
                acknowledged_before=at - acknowledged_retention,
                unacknowledged_before=at - unacknowledged_retention,
            )
            evicted: list[EvidenceArtifact] = []
            for artifact in candidates:
                try:
                    evicted.append(
                        self.evict(
                            artifact.evidence_id,
                            EvidenceRetentionDisposition.RETENTION_EXPIRED,
                            now=at,
                        )
                    )
                except EvidenceIntegrityError:
                    # evict() has already persisted FAILED and attempted managed
                    # file cleanup. One corrupt artifact must not block the batch.
                    continue
            return tuple(evicted)

    def evict_for_pressure(
        self,
        minimum_bytes_to_free: int,
        *,
        now: datetime | None = None,
    ) -> tuple[EvidenceArtifact, ...]:
        """Caller-controlled pressure cleanup.

        ACK를 먼저 지우고 실제 해제량을 추적한다.
        """

        if minimum_bytes_to_free < 0:
            raise ValueError("minimum_bytes_to_free must be non-negative")
        if minimum_bytes_to_free == 0:
            return ()
        at = now or _utc_now()
        with self._lock:
            evicted: list[EvidenceArtifact] = []
            freed = 0
            for artifact in self._repository.list_pressure_candidates():
                final_path = self._final_path(artifact.evidence_id)
                managed_file_existed = final_path.exists() or final_path.is_symlink()
                try:
                    managed_file_size = (
                        final_path.lstat().st_size if managed_file_existed else 0
                    )
                except OSError:
                    managed_file_size = 0
                try:
                    evicted_artifact = self.evict(
                        artifact.evidence_id,
                        EvidenceRetentionDisposition.STORAGE_PRESSURE,
                        now=at,
                    )
                except EvidenceIntegrityError:
                    if (
                        managed_file_existed
                        and not final_path.exists()
                        and not final_path.is_symlink()
                    ):
                        freed += managed_file_size
                else:
                    evicted.append(evicted_artifact)
                    freed += managed_file_size
                if freed >= minimum_bytes_to_free:
                    break
            return tuple(evicted)

    def list_unavailable_candidates(self) -> tuple[EvidenceArtifact, ...]:
        """Return durable loss intents for later idempotent outbox materialization."""

        return self._repository.list_unavailable_candidates()

    @staticmethod
    def _jpeg_content_error(
        artifact: EvidenceArtifact,
        payload: bytes,
    ) -> str | None:
        if artifact.image_type != "image/jpeg":
            return "evidence metadata image_type must be image/jpeg"
        if not payload.startswith(_JPEG_START) or not payload.endswith(_JPEG_END):
            return "evidence payload is not a complete JPEG byte sequence"
        return None

    def _resource_limit_error(
        self,
        artifact: EvidenceArtifact,
        payload: bytes,
    ) -> str | None:
        if len(payload) > self._artifact_max_bytes:
            return (
                f"artifact is {len(payload)} bytes; hard limit is "
                f"{self._artifact_max_bytes} bytes"
            )
        if self._repository.count_for_incident(artifact.incident_id) > (
            self._incident_max_artifacts
        ):
            return (
                f"incident has more than {self._incident_max_artifacts} "
                "evidence reservations"
            )
        existing_bytes = self._repository.byte_size_for_incident(
            artifact.incident_id,
            excluding=artifact.evidence_id,
        )
        if existing_bytes + len(payload) > self._incident_max_bytes:
            return (
                f"incident evidence set would exceed {self._incident_max_bytes} bytes"
            )
        return None

    def _capacity_error(self, additional_bytes: int) -> str | None:
        capacity = self.capacity_snapshot()
        if capacity.spool_bytes + additional_bytes > capacity.spool_cap_bytes:
            return (
                f"evidence spool would exceed configured cap "
                f"{capacity.spool_cap_bytes} bytes"
            )
        if (
            capacity.filesystem_free_bytes - additional_bytes
            < capacity.protected_floor_bytes
        ):
            return "evidence write would cross the configured filesystem free-space floor"
        if (
            capacity.filesystem_free_bytes - additional_bytes
            < capacity.capture_stop_free_bytes
        ):
            return "filesystem free space is below the evidence capture-stop threshold"
        return None

    def _recover_writing(
        self,
        artifact: EvidenceArtifact,
        *,
        final_path: Path,
        at: datetime,
    ) -> EvidenceArtifact:
        if self._binary_matches(artifact):
            ready = replace(
                artifact,
                state=EvidenceState.READY,
                record_version=artifact.record_version + 1,
                updated_at=at,
            )
            self._save(ready, expected_record_version=artifact.record_version)
            return ready
        self._unlink_managed(final_path)
        return self._mark_failed(
            artifact,
            at=at,
            error="interrupted evidence write has no durable final JPEG",
            disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
        )

    def _complete_eviction(
        self,
        pending: EvidenceArtifact,
        *,
        at: datetime,
    ) -> EvidenceArtifact:
        if pending.state is not EvidenceState.EVICTION_PENDING:
            raise EvidenceStateError("eviction completion requires EVICTION_PENDING")
        if pending.retention_disposition is None:
            return self._mark_failed(
                pending,
                at=at,
                error="eviction intent has no durable disposition",
                disposition=EvidenceRetentionDisposition.LOST_OR_CORRUPTED,
            )

        final_path = self._final_path(pending.evidence_id)
        self._unlink_managed(final_path)
        evicted = replace(
            pending,
            state=EvidenceState.EVICTED,
            local_path=None,
            evicted_at=at,
            record_version=pending.record_version + 1,
            updated_at=at,
        )
        self._save(evicted, expected_record_version=pending.record_version)
        return evicted

    def _mark_failed(
        self,
        artifact: EvidenceArtifact,
        *,
        at: datetime,
        error: str,
        disposition: EvidenceRetentionDisposition,
        byte_size: int | None = None,
        checksum: str | None = None,
    ) -> EvidenceArtifact:
        failed = replace(
            artifact,
            state=EvidenceState.FAILED,
            local_path=None,
            byte_size=artifact.byte_size if byte_size is None else byte_size,
            checksum=artifact.checksum if checksum is None else checksum,
            last_error=error,
            retention_disposition=disposition,
            record_version=artifact.record_version + 1,
            updated_at=at,
        )
        self._save(failed, expected_record_version=artifact.record_version)
        return failed

    def _binary_matches(self, artifact: EvidenceArtifact) -> bool:
        expected = self._final_path(artifact.evidence_id)
        if artifact.local_path is None:
            return False
        if artifact.local_path.resolve(strict=False) != expected:
            return False
        if artifact.byte_size is None or artifact.checksum is None:
            return False
        try:
            if expected.is_symlink() or not expected.is_file():
                return False
            if expected.stat().st_size != artifact.byte_size:
                return False
            payload = expected.read_bytes()
        except OSError:
            return False
        return len(payload) == artifact.byte_size and _checksum(payload) == artifact.checksum

    @staticmethod
    def _requires_unavailable(artifact: EvidenceArtifact) -> bool:
        """Only externally bound, not-yet-ACKed loss needs later publication wiring."""

        return (
            artifact.publication_revision is not None
            and artifact.backend_acked_at is None
        )

    def _save(self, artifact: EvidenceArtifact, *, expected_record_version: int) -> None:
        with UnitOfWork(self._connection):
            self._repository.save(
                artifact,
                expected_record_version=expected_record_version,
            )

    def _require_artifact(self, evidence_id: EvidenceId) -> EvidenceArtifact:
        artifact = self._repository.get(evidence_id)
        if artifact is None:
            raise EvidenceStateError(f"unknown evidence identity: {evidence_id}")
        return artifact

    def _final_path(self, evidence_id: EvidenceId) -> Path:
        return self._root / f"{evidence_id}.jpg"

    def _part_path(self, evidence_id: EvidenceId) -> Path:
        return self._root / f"{evidence_id}.jpg.part"

    def _spool_usage_bytes(self) -> int:
        total = 0
        for path in self._root.iterdir():
            if path.name == _SPOOL_MARKER_NAME:
                continue
            try:
                # Count unknown files too, but never delete them automatically.
                if path.is_file() or path.is_symlink():
                    total += path.lstat().st_size
            except OSError:
                continue
        return total

    def _initialize_or_validate_root(self) -> None:
        """Require an explicit ownership marker before any orphan deletion.

        A non-empty unmarked directory is probably a shared or overly broad path;
        refusing it is safer than inferring ownership from UUID-shaped filenames.
        """

        marker = self._root / _SPOOL_MARKER_NAME
        if marker.exists() or marker.is_symlink():
            try:
                if marker.is_symlink() or not marker.is_file():
                    raise EvidenceIntegrityError(
                        "evidence spool marker must be a regular file"
                    )
                if marker.read_bytes() != _SPOOL_MARKER_CONTENT:
                    raise EvidenceIntegrityError(
                        "evidence spool marker has unexpected content"
                    )
            except OSError as error:
                raise EvidenceIntegrityError(
                    "could not validate evidence spool ownership marker"
                ) from error
            return

        if any(self._root.iterdir()):
            raise EvidenceIntegrityError(
                "refusing to use a non-empty directory without an evidence spool marker"
            )
        try:
            with marker.open("xb") as handle:
                handle.write(_SPOOL_MARKER_CONTENT)
                handle.flush()
                os.fsync(handle.fileno())
            self._fsync_directory()
        except OSError as error:
            raise EvidenceIntegrityError(
                "could not create evidence spool ownership marker"
            ) from error

    def _unlink_managed(self, path: Path) -> None:
        if path.parent.resolve() != self._root:
            raise EvidenceIntegrityError("refusing to unlink outside the evidence spool")
        if _FINAL_NAME.fullmatch(path.name) is None and _PART_NAME.fullmatch(path.name) is None:
            raise EvidenceIntegrityError("refusing to unlink an unmanaged spool file")
        try:
            path.unlink()
        except FileNotFoundError:
            return
        self._fsync_directory()

    def _fsync_directory(self) -> None:
        # Windows는 directory descriptor open/fsync를 지원하지 않는다. 배포 대상인
        # Jetson Linux에서는 아래 fsync를 그대로 수행한다.
        if os.name == "nt":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        descriptor = os.open(self._root, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

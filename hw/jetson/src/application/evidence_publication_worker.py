"""API 8 이미지 업로드와 API 9 제공 불가 publication을 한 큐로 실행한다.

Evidence binary는 file spool에, 전송 시도와 backoff는 EvidenceArtifact metadata에
보존한다. HTTP 중에는 SQLite write transaction을 잡지 않으며, process 중단으로
남은 ``IN_FLIGHT`` 전송은 기동 시 동일 identity로 재시도한다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Protocol

from src.communication.backend_client import (
    PublicationConfirmation,
    RetryableBackendPublicationError,
    TerminalBackendPublicationError,
)
from src.communication.backend_requests import (
    EvidenceUnavailableReason,
    EvidenceUnavailableRequest,
    EvidenceUploadRequest,
)
from src.diagnostics import (
    DiagnosticEvent,
    DiagnosticEventType,
    DiagnosticSeverity,
    DiagnosticsSink,
    NullDiagnosticsSink,
    emit_best_effort,
)
from src.evidence.models import EvidenceArtifact, EvidenceState
from src.evidence.spool import EvidenceSpool
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.unit_of_work import UnitOfWork


logger = logging.getLogger(__name__)

ConnectionFactory = Callable[[], sqlite3.Connection]
EvidenceClock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EvidencePublicationClient(Protocol):
    def upload_evidence(
        self,
        request: EvidenceUploadRequest,
        *,
        idempotency_key: str,
    ) -> PublicationConfirmation:
        ...

    def publish_evidence_unavailable(
        self,
        request: EvidenceUnavailableRequest,
        *,
        idempotency_key: str,
    ) -> PublicationConfirmation:
        ...

    def close(self) -> None:
        ...


class EvidencePublicationPreparationError(RuntimeError):
    """API 8 exact binary를 더 이상 안전하게 구성할 수 없다."""


class EvidencePublicationPublisher:
    """due EvidenceArtifact 하나를 API 8 또는 API 9로 전달한다."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        client: EvidencePublicationClient,
        spool_path: Path,
        spool_cap_bytes: int,
        filesystem_floor_ratio: float,
        capture_stop_free_ratio: float,
        retry_initial_seconds: float = 1.0,
        retry_max_seconds: float = 300.0,
        clock: EvidenceClock = _utc_now,
        diagnostics_sink: DiagnosticsSink | None = None,
    ) -> None:
        if retry_initial_seconds <= 0:
            raise ValueError("retry_initial_seconds must be positive")
        if retry_max_seconds < retry_initial_seconds:
            raise ValueError(
                "retry_max_seconds must not be smaller than retry_initial_seconds"
            )
        self._connection_factory = connection_factory
        self._client = client
        self._spool_path = spool_path.resolve()
        self._spool_cap_bytes = spool_cap_bytes
        self._filesystem_floor_ratio = filesystem_floor_ratio
        self._capture_stop_free_ratio = capture_stop_free_ratio
        self._retry_initial_seconds = retry_initial_seconds
        self._retry_max_seconds = retry_max_seconds
        self._clock = clock
        self._diagnostics_sink = (
            diagnostics_sink
            if diagnostics_sink is not None
            else NullDiagnosticsSink()
        )

    def recover(self) -> int:
        """spool을 먼저 복구하고 중단된 HTTP 전송을 retry 대기로 되돌린다."""

        now = self._now()
        connection = self._connection_factory()
        try:
            EvidenceSpool(
                connection=connection,
                root=self._spool_path,
                spool_cap_bytes=self._spool_cap_bytes,
                filesystem_floor_ratio=self._filesystem_floor_ratio,
                capture_stop_free_ratio=self._capture_stop_free_ratio,
            ).recover(now=now)
        finally:
            connection.close()

        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                return EvidenceArtifactRepository(connection).recover_in_flight(
                    now=now
                )
        finally:
            connection.close()

    def publish_once(self) -> bool:
        """due evidence가 있으면 하나를 처리하고 없으면 ``False``를 반환한다."""

        artifact = self._claim_next()
        if artifact is None:
            return False
        self._observe_publication(
            artifact,
            result="DELIVERY_ATTEMPTED",
        )
        try:
            if artifact.state is EvidenceState.UPLOADING:
                confirmation = self._publish_upload(artifact)
            elif artifact.state in {EvidenceState.FAILED, EvidenceState.EVICTED}:
                confirmation = self._publish_unavailable(artifact)
            else:  # pragma: no cover - repository claim query owns this invariant.
                raise TerminalBackendPublicationError(
                    f"unsupported evidence publication state: {artifact.state.value}"
                )
        except EvidencePublicationPreparationError as error:
            self._mark_upload_unavailable(artifact, error)
        except RetryableBackendPublicationError as error:
            self._schedule_retry(artifact, error)
        except TerminalBackendPublicationError as error:
            self._mark_failed_terminal(artifact, error)
        else:
            self._mark_delivered(artifact, confirmation)
        return True

    def close(self) -> None:
        self._client.close()

    def _claim_next(self) -> EvidenceArtifact | None:
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                return EvidenceArtifactRepository(
                    connection
                ).claim_next_delivery(now=self._now())
        finally:
            connection.close()

    def _publish_upload(
        self,
        artifact: EvidenceArtifact,
    ) -> PublicationConfirmation:
        if artifact.publication_revision is None:
            raise EvidencePublicationPreparationError(
                "evidence upload has no publication revision"
            )
        content = self._read_upload_content(artifact)
        return self._client.upload_evidence(
            EvidenceUploadRequest(
                incident_id=artifact.incident_id,
                evidence_id=artifact.evidence_id,
                publication_revision=artifact.publication_revision,
                content=content,
                captured_at=artifact.captured_at,
                mime_type=artifact.image_type,
                byte_size=artifact.byte_size,
                checksum=artifact.checksum,
            ),
            idempotency_key=(
                f"EvidenceArtifact:{artifact.evidence_id}:"
                f"{artifact.publication_revision}"
            ),
        )

    def _publish_unavailable(
        self,
        artifact: EvidenceArtifact,
    ) -> PublicationConfirmation:
        if artifact.publication_revision is None:
            raise TerminalBackendPublicationError(
                "unavailable evidence has no publication revision"
            )
        if artifact.retention_disposition is None:
            raise TerminalBackendPublicationError(
                "unavailable evidence has no retention disposition"
            )
        try:
            reason = EvidenceUnavailableReason(
                artifact.retention_disposition.value
            )
        except ValueError as error:  # pragma: no cover - enums currently match.
            raise TerminalBackendPublicationError(
                "unsupported evidence unavailable reason: "
                f"{artifact.retention_disposition.value}"
            ) from error
        return self._client.publish_evidence_unavailable(
            EvidenceUnavailableRequest(
                incident_id=artifact.incident_id,
                evidence_id=artifact.evidence_id,
                publication_revision=artifact.publication_revision,
                reason=reason,
                unavailable_at=artifact.evicted_at or artifact.updated_at,
                byte_size=artifact.byte_size,
                checksum=artifact.checksum,
            ),
            idempotency_key=(
                f"EvidenceUnavailable:{artifact.evidence_id}:"
                f"{artifact.publication_revision}"
            ),
        )

    def _read_upload_content(self, artifact: EvidenceArtifact) -> bytes:
        expected_path = self._spool_path / f"{artifact.evidence_id}.jpg"
        if artifact.local_path is None or (
            artifact.local_path.resolve(strict=False) != expected_path
        ):
            raise EvidencePublicationPreparationError(
                "evidence path is outside its managed spool identity"
            )
        try:
            if expected_path.is_symlink() or not expected_path.is_file():
                raise EvidencePublicationPreparationError(
                    "evidence file is missing or is not a regular file"
                )
            content = expected_path.read_bytes()
        except OSError as error:
            raise EvidencePublicationPreparationError(
                f"evidence file could not be read: {type(error).__name__}"
            ) from error
        checksum = f"sha256:{hashlib.sha256(content).hexdigest()}"
        if len(content) != artifact.byte_size or checksum != artifact.checksum:
            raise EvidencePublicationPreparationError(
                "evidence file size or checksum differs from durable metadata"
            )
        return content

    def _schedule_retry(
        self,
        artifact: EvidenceArtifact,
        error: Exception,
    ) -> None:
        exponent = min(max(artifact.delivery_attempt_count - 1, 0), 30)
        delay_seconds = min(
            self._retry_max_seconds,
            self._retry_initial_seconds * (2**exponent),
        )
        next_attempt_at = self._now() + timedelta(seconds=delay_seconds)
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                EvidenceArtifactRepository(connection).schedule_retry(
                    artifact.evidence_id,
                    expected_record_version=artifact.record_version,
                    next_attempt_at=next_attempt_at,
                    error=_error_text(error),
                )
        finally:
            connection.close()
        logger.warning(
            "Backend evidence publication 재시도가 예약됐습니다. "
            "publicationType=%s evidenceId=%s incidentId=%s "
            "attempt=%d nextAttemptAt=%s error=%s",
            _publication_type(artifact),
            artifact.evidence_id,
            artifact.incident_id,
            artifact.delivery_attempt_count,
            next_attempt_at.isoformat(),
            _error_text(error),
        )
        self._observe_publication(
            artifact,
            result="DELIVERY_RETRY_SCHEDULED",
            severity=DiagnosticSeverity.WARNING,
            error=error,
            next_attempt_at=next_attempt_at,
        )

    def _mark_delivered(
        self,
        artifact: EvidenceArtifact,
        confirmation: PublicationConfirmation,
    ) -> None:
        ack_payload = json.dumps(
            {
                "applicationStatus": confirmation.application_status.value,
                "payloadHash": confirmation.payload_hash,
                "backendCorrelation": dict(confirmation.backend_correlation),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                EvidenceArtifactRepository(connection).mark_delivered(
                    artifact.evidence_id,
                    expected_record_version=artifact.record_version,
                    acknowledged_at=self._now(),
                    backend_ack_payload=ack_payload,
                )
        finally:
            connection.close()
        logger.info(
            "Backend evidence publication 전송이 완료됐습니다. "
            "publicationType=%s evidenceId=%s incidentId=%s "
            "attempt=%d applicationStatus=%s",
            _publication_type(artifact),
            artifact.evidence_id,
            artifact.incident_id,
            artifact.delivery_attempt_count,
            confirmation.application_status.value,
        )
        self._observe_publication(
            artifact,
            result="DELIVERY_SUCCEEDED",
            application_status=confirmation.application_status.value,
        )

    def _mark_failed_terminal(
        self,
        artifact: EvidenceArtifact,
        error: Exception,
    ) -> None:
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                EvidenceArtifactRepository(connection).mark_failed_terminal(
                    artifact.evidence_id,
                    expected_record_version=artifact.record_version,
                    error=_error_text(error),
                )
        finally:
            connection.close()
        logger.error(
            "Backend evidence publication이 영구 실패로 격리됐습니다. "
            "publicationType=%s evidenceId=%s incidentId=%s "
            "attempt=%d error=%s",
            _publication_type(artifact),
            artifact.evidence_id,
            artifact.incident_id,
            artifact.delivery_attempt_count,
            _error_text(error),
        )
        self._observe_publication(
            artifact,
            result="DELIVERY_FAILED_TERMINAL",
            severity=DiagnosticSeverity.ERROR,
            error=error,
        )

    def _mark_upload_unavailable(
        self,
        artifact: EvidenceArtifact,
        error: Exception,
    ) -> None:
        expected_path = self._spool_path / f"{artifact.evidence_id}.jpg"
        if artifact.local_path is not None and (
            artifact.local_path.resolve(strict=False) == expected_path
        ):
            try:
                if expected_path.exists() or expected_path.is_symlink():
                    expected_path.unlink()
            except OSError:
                logger.exception(
                    "손상된 evidence managed file을 제거하지 못했습니다: %s",
                    artifact.evidence_id,
                )
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                EvidenceArtifactRepository(connection).mark_upload_unavailable(
                    artifact.evidence_id,
                    expected_record_version=artifact.record_version,
                    failed_at=self._now(),
                    error=_error_text(error),
                )
        finally:
            connection.close()
        self._observe_publication(
            artifact,
            result="UPLOAD_MARKED_UNAVAILABLE",
            severity=DiagnosticSeverity.WARNING,
            error=error,
        )

    def _observe_publication(
        self,
        artifact: EvidenceArtifact,
        *,
        result: str,
        severity: DiagnosticSeverity = DiagnosticSeverity.INFO,
        error: Exception | None = None,
        next_attempt_at: datetime | None = None,
        application_status: str | None = None,
    ) -> None:
        emit_best_effort(
            self._diagnostics_sink,
            DiagnosticEvent(
                event_type=(
                    DiagnosticEventType.EVIDENCE_PUBLICATION_EVALUATED
                ),
                occurred_at=self._now(),
                severity=severity,
                attributes={
                    "applicationStatus": application_status,
                    "attempt": artifact.delivery_attempt_count,
                    "claimedDeliveryState": artifact.delivery_state.value,
                    "errorType": (
                        type(error).__name__ if error is not None else None
                    ),
                    "evidenceId": str(artifact.evidence_id),
                    "incidentId": str(artifact.incident_id),
                    "nextAttemptAt": (
                        next_attempt_at.isoformat()
                        if next_attempt_at is not None
                        else None
                    ),
                    "phase": "BACKEND_PUBLICATION",
                    "publicationRevision": artifact.publication_revision,
                    "publicationType": _publication_type(artifact),
                    "result": result,
                },
            ),
        )

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Evidence clock must return timezone-aware datetime")
        return now


class EvidencePublicationWorker:
    """EvidencePublicationPublisher를 background thread에서 실행한다."""

    def __init__(
        self,
        publisher: EvidencePublicationPublisher,
        *,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._publisher = publisher
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._failure: Exception | None = None

    @property
    def failure(self) -> Exception | None:
        return self._failure

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("evidence publication worker may only be started once")
        self._publisher.recover()
        thread = Thread(
            target=self._run,
            name="jetson-evidence-publication",
            daemon=False,
        )
        self._thread = thread
        try:
            thread.start()
        except Exception:
            self._publisher.close()
            raise

    def stop(self) -> None:
        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join()
        self._publisher.close()

    def _run(self) -> None:
        try:
            while not self._stop_requested.is_set():
                processed = self._publisher.publish_once()
                if not processed:
                    self._stop_requested.wait(self._poll_interval_seconds)
        except Exception as error:
            self._failure = error
            logger.exception("Jetson evidence publication worker가 종료됐습니다.")


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:1_000]


def _publication_type(artifact: EvidenceArtifact) -> str:
    """민감한 HTTP payload 없이 evidence publication 종류만 식별한다."""

    if artifact.state is EvidenceState.UPLOADING:
        return "UPLOAD"
    return "UNAVAILABLE"

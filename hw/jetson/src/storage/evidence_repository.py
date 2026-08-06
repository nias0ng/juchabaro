"""Evidence file spool과 SQLite metadata를 연결하는 repository.

Binary는 파일시스템에 두고 이 repository는 immutable capture identity와
crash recovery에 필요한 workflow state만 보존한다. 쓰기는 반드시
``UnitOfWork`` 안에서 호출해야 한다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from src.domain.models import DeliveryState, require_aware
from src.evidence.models import (
    EvidenceArtifact,
    EvidenceId,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.parking.models import IncidentId

from .codecs import (
    datetime_from_epoch_microseconds,
    datetime_to_epoch_microseconds,
    uuid_from_text,
    uuid_to_text,
)
from .repositories import OptimisticConcurrencyError, optimistic_update
from .unit_of_work import require_write_transaction


class EvidenceArtifactConflictError(RuntimeError):
    """Evidence identity·immutable metadata 재사용 충돌."""


MAX_EVIDENCE_ARTIFACTS_PER_INCIDENT = 2


_ALLOWED_STATE_TRANSITIONS: dict[EvidenceState, frozenset[EvidenceState]] = {
    EvidenceState.RESERVED: frozenset({EvidenceState.WRITING, EvidenceState.FAILED}),
    EvidenceState.WRITING: frozenset({EvidenceState.READY, EvidenceState.FAILED}),
    EvidenceState.READY: frozenset(
        {
            EvidenceState.UPLOADING,
            EvidenceState.ACKNOWLEDGED,
            EvidenceState.EVICTION_PENDING,
            EvidenceState.FAILED,
        }
    ),
    # 단일 publisher가 restart되면 persisted UPLOADING을 READY로 되돌린다.
    EvidenceState.UPLOADING: frozenset(
        {EvidenceState.READY, EvidenceState.ACKNOWLEDGED, EvidenceState.FAILED}
    ),
    EvidenceState.ACKNOWLEDGED: frozenset(
        {EvidenceState.EVICTION_PENDING, EvidenceState.FAILED}
    ),
    EvidenceState.EVICTION_PENDING: frozenset(
        {EvidenceState.EVICTED, EvidenceState.FAILED}
    ),
    EvidenceState.EVICTED: frozenset(),
    EvidenceState.FAILED: frozenset(),
}


def _optional_datetime(value: object) -> datetime | None:
    return (
        datetime_from_epoch_microseconds(int(value))
        if value is not None
        else None
    )


def _artifact_from_row(row: sqlite3.Row) -> EvidenceArtifact:
    disposition = row["retention_disposition"]
    delivery_state = row["delivery_state"]
    return EvidenceArtifact(
        evidence_id=EvidenceId(uuid_from_text(str(row["evidence_id"]))),
        incident_id=IncidentId(uuid_from_text(str(row["incident_id"]))),
        publication_revision=(
            int(row["publication_revision"])
            if row["publication_revision"] is not None
            else None
        ),
        captured_at=datetime_from_epoch_microseconds(int(row["captured_at_us"])),
        image_type=str(row["image_type"]),
        local_path=(
            Path(str(row["local_path"])) if row["local_path"] is not None else None
        ),
        byte_size=(int(row["byte_size"]) if row["byte_size"] is not None else None),
        checksum=(str(row["checksum"]) if row["checksum"] is not None else None),
        state=EvidenceState(str(row["workflow_state"])),
        last_error=(
            str(row["last_error"]) if row["last_error"] is not None else None
        ),
        backend_acked_at=_optional_datetime(row["backend_acked_at_us"]),
        retention_disposition=(
            EvidenceRetentionDisposition(str(disposition))
            if disposition is not None
            else None
        ),
        evicted_at=_optional_datetime(row["evicted_at_us"]),
        delivery_state=(
            DeliveryState(str(delivery_state))
            if delivery_state is not None
            else None
        ),
        delivery_attempt_count=int(row["delivery_attempt_count"]),
        next_delivery_attempt_at=_optional_datetime(
            row["next_delivery_attempt_at_us"]
        ),
        last_delivery_error=(
            str(row["last_delivery_error"])
            if row["last_delivery_error"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


class EvidenceArtifactRepository:
    """Evidence metadata의 identity, state, retention 조회를 소유한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, evidence_id: EvidenceId) -> EvidenceArtifact | None:
        row = self._connection.execute(
            "SELECT * FROM evidence_artifacts WHERE evidence_id = ?",
            (uuid_to_text(evidence_id),),
        ).fetchone()
        return _artifact_from_row(row) if row is not None else None

    def list_all(self) -> tuple[EvidenceArtifact, ...]:
        """Startup reconciliation을 위해 모든 metadata를 결정적 순서로 반환한다."""

        rows = self._connection.execute(
            "SELECT * FROM evidence_artifacts ORDER BY captured_at_us, evidence_id"
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def list_by_states(
        self,
        states: set[EvidenceState] | frozenset[EvidenceState],
    ) -> tuple[EvidenceArtifact, ...]:
        if not states:
            return ()
        ordered_states = sorted(state.value for state in states)
        placeholders = ", ".join("?" for _ in ordered_states)
        rows = self._connection.execute(
            f"""
            SELECT * FROM evidence_artifacts
            WHERE workflow_state IN ({placeholders})
            ORDER BY captured_at_us, evidence_id
            """,
            ordered_states,
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def count_for_incident(self, incident_id: IncidentId) -> int:
        """Terminal metadata를 포함한 logical capture reservation 수를 반환한다."""

        row = self._connection.execute(
            "SELECT COUNT(*) FROM evidence_artifacts WHERE incident_id = ?",
            (uuid_to_text(incident_id),),
        ).fetchone()
        return int(row[0])

    def list_for_incident(
        self,
        incident_id: IncidentId,
    ) -> tuple[EvidenceArtifact, ...]:
        """한 Incident에 예약된 artifact를 capture 순서로 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM evidence_artifacts
            WHERE incident_id = ?
            ORDER BY captured_at_us, evidence_id
            """,
            (uuid_to_text(incident_id),),
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def bind_publication_revision_for_incident(
        self,
        incident_id: IncidentId,
        *,
        publication_revision: int,
        bound_at: datetime,
    ) -> int:
        """아직 local-only인 evidence를 Incident OPEN revision에 결속한다.

        correlation이 늦은 Incident는 정지 이미지를 먼저 보관하고 API 7 OPEN이
        materialize되는 transaction에서 revision을 확정한다. 이미 결속된 artifact는
        같은 호출을 반복해도 변경하지 않는다.
        """

        require_write_transaction(self._connection)
        if publication_revision < 1:
            raise ValueError("publication_revision must be positive")
        require_aware(bound_at, "bound_at")

        bound = 0
        for artifact in self.list_for_incident(incident_id):
            if artifact.publication_revision is not None:
                if artifact.publication_revision != publication_revision:
                    raise EvidenceArtifactConflictError(
                        "Incident evidence is already bound to another publication revision"
                    )
                continue
            replacement = replace(
                artifact,
                publication_revision=publication_revision,
                record_version=artifact.record_version + 1,
                updated_at=max(artifact.updated_at, bound_at),
            )
            self.save(
                replacement,
                expected_record_version=artifact.record_version,
            )
            bound += 1
        return bound

    def byte_size_for_incident(
        self,
        incident_id: IncidentId,
        *,
        excluding: EvidenceId | None = None,
    ) -> int:
        query = "SELECT COALESCE(SUM(byte_size), 0) FROM evidence_artifacts WHERE incident_id = ?"
        parameters: list[object] = [uuid_to_text(incident_id)]
        if excluding is not None:
            query += " AND evidence_id <> ?"
            parameters.append(uuid_to_text(excluding))
        row = self._connection.execute(query, parameters).fetchone()
        return int(row[0])

    def list_retention_candidates(
        self,
        *,
        acknowledged_before: datetime,
        unacknowledged_before: datetime,
    ) -> tuple[EvidenceArtifact, ...]:
        """ACK binary를 먼저, 그 다음 미ACK READY binary를 반환한다."""

        acknowledged_us = datetime_to_epoch_microseconds(acknowledged_before)
        unacknowledged_us = datetime_to_epoch_microseconds(unacknowledged_before)
        rows = self._connection.execute(
            """
            SELECT * FROM evidence_artifacts
            WHERE (
                    workflow_state = 'ACKNOWLEDGED'
                    AND backend_acked_at_us <= ?
                )
                OR (
                    workflow_state = 'READY'
                    AND captured_at_us <= ?
                )
            ORDER BY
                CASE workflow_state WHEN 'ACKNOWLEDGED' THEN 0 ELSE 1 END,
                COALESCE(backend_acked_at_us, captured_at_us),
                evidence_id
            """,
            (acknowledged_us, unacknowledged_us),
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def list_pressure_candidates(self) -> tuple[EvidenceArtifact, ...]:
        """Upload 중인 파일을 건드리지 않고 ACK→READY 순으로 정리한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM evidence_artifacts
            WHERE workflow_state IN ('ACKNOWLEDGED', 'READY')
            ORDER BY
                CASE workflow_state WHEN 'ACKNOWLEDGED' THEN 0 ELSE 1 END,
                COALESCE(backend_acked_at_us, captured_at_us),
                evidence_id
            """
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def list_unavailable_candidates(self) -> tuple[EvidenceArtifact, ...]:
        """Wire를 만들지 않고 durable EvidenceUnavailable 대상만 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM evidence_artifacts
            WHERE publication_revision IS NOT NULL
              AND backend_acked_at_us IS NULL
              AND workflow_state IN ('FAILED', 'EVICTED')
            ORDER BY updated_at_us, evidence_id
            """
        ).fetchall()
        return tuple(_artifact_from_row(row) for row in rows)

    def claim_next_delivery(self, *, now: datetime) -> EvidenceArtifact | None:
        """Incident OPEN ACK가 확인된 API 8·9 대상 하나를 claim한다."""

        require_write_transaction(self._connection)
        now_us = datetime_to_epoch_microseconds(now)
        row = self._connection.execute(
            """
            SELECT evidence.*
            FROM evidence_artifacts AS evidence
            WHERE evidence.publication_revision IS NOT NULL
              AND evidence.backend_acked_at_us IS NULL
              AND evidence.workflow_state IN ('READY', 'FAILED', 'EVICTED')
              AND (
                    evidence.delivery_state IS NULL
                    OR evidence.delivery_state IN ('PENDING', 'RETRY_WAIT')
              )
              AND (
                    evidence.next_delivery_attempt_at_us IS NULL
                    OR evidence.next_delivery_attempt_at_us <= ?
              )
              AND (
                    EXISTS (
                        SELECT 1
                        FROM outbox AS parent
                        WHERE parent.aggregate_type = 'Incident'
                          AND parent.aggregate_id = evidence.incident_id
                          AND parent.destination = 'backend'
                          AND parent.publication_revision =
                              evidence.publication_revision
                          AND parent.transition_type = 'OPEN'
                          AND parent.delivery_state = 'DELIVERED'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM delivery_receipts AS receipt
                        WHERE receipt.aggregate_type = 'Incident'
                          AND receipt.aggregate_id = evidence.incident_id
                          AND receipt.destination = 'backend'
                          AND receipt.publication_revision =
                              evidence.publication_revision
                    )
              )
            ORDER BY
                COALESCE(
                    evidence.next_delivery_attempt_at_us,
                    evidence.updated_at_us
                ),
                evidence.updated_at_us,
                evidence.evidence_id
            LIMIT 1
            """,
            (now_us,),
        ).fetchone()
        if row is None:
            return None

        current = _artifact_from_row(row)
        claimed = replace(
            current,
            state=(
                EvidenceState.UPLOADING
                if current.state is EvidenceState.READY
                else current.state
            ),
            delivery_state=DeliveryState.IN_FLIGHT,
            delivery_attempt_count=current.delivery_attempt_count + 1,
            next_delivery_attempt_at=None,
            record_version=current.record_version + 1,
        )
        self.save(claimed, expected_record_version=current.record_version)
        persisted = self.get(current.evidence_id)
        if persisted is None:  # pragma: no cover
            raise RuntimeError("claimed EvidenceArtifact disappeared")
        return persisted

    def recover_in_flight(self, *, now: datetime) -> int:
        """process 중단 시 남은 API 8·9 전송을 즉시 재시도 가능하게 만든다."""

        require_write_transaction(self._connection)
        rows = self._connection.execute(
            """
            SELECT * FROM evidence_artifacts
            WHERE delivery_state = 'IN_FLIGHT'
            ORDER BY updated_at_us, evidence_id
            """
        ).fetchall()
        for row in rows:
            current = _artifact_from_row(row)
            recovered = replace(
                current,
                state=(
                    EvidenceState.READY
                    if current.state is EvidenceState.UPLOADING
                    else current.state
                ),
                delivery_state=DeliveryState.RETRY_WAIT,
                next_delivery_attempt_at=now,
                last_delivery_error="PROCESS_RESTARTED",
                record_version=current.record_version + 1,
            )
            self.save(
                recovered,
                expected_record_version=current.record_version,
            )
        return len(rows)

    def schedule_retry(
        self,
        evidence_id: EvidenceId,
        *,
        expected_record_version: int,
        next_attempt_at: datetime,
        error: str,
    ) -> EvidenceArtifact:
        """일시적 실패를 기록하고 동일 API publication을 재시도 대기시킨다."""

        require_write_transaction(self._connection)
        current = self._require_in_flight(
            evidence_id,
            expected_record_version=expected_record_version,
        )
        retried = replace(
            current,
            state=(
                EvidenceState.READY
                if current.state is EvidenceState.UPLOADING
                else current.state
            ),
            delivery_state=DeliveryState.RETRY_WAIT,
            next_delivery_attempt_at=next_attempt_at,
            last_delivery_error=error,
            record_version=current.record_version + 1,
        )
        self.save(retried, expected_record_version=current.record_version)
        return retried

    def mark_delivered(
        self,
        evidence_id: EvidenceId,
        *,
        expected_record_version: int,
        acknowledged_at: datetime,
        backend_ack_payload: bytes,
    ) -> EvidenceArtifact:
        """Backend ACK를 API 8·9 공통 terminal delivery 상태로 기록한다."""

        require_write_transaction(self._connection)
        current = self._require_in_flight(
            evidence_id,
            expected_record_version=expected_record_version,
        )
        delivered = replace(
            current,
            state=(
                EvidenceState.ACKNOWLEDGED
                if current.state is EvidenceState.UPLOADING
                else current.state
            ),
            backend_acked_at=acknowledged_at,
            delivery_state=DeliveryState.DELIVERED,
            next_delivery_attempt_at=None,
            record_version=current.record_version + 1,
        )
        self.save(delivered, expected_record_version=current.record_version)
        self._connection.execute(
            """
            UPDATE evidence_artifacts
            SET backend_ack_payload = ?
            WHERE evidence_id = ? AND record_version = ?
            """,
            (
                backend_ack_payload,
                uuid_to_text(evidence_id),
                delivered.record_version,
            ),
        )
        return delivered

    def mark_failed_terminal(
        self,
        evidence_id: EvidenceId,
        *,
        expected_record_version: int,
        error: str,
    ) -> EvidenceArtifact:
        """4xx·계약 오류를 자동 재시도하지 않는 상태로 격리한다."""

        require_write_transaction(self._connection)
        current = self._require_in_flight(
            evidence_id,
            expected_record_version=expected_record_version,
        )
        failed = replace(
            current,
            state=(
                EvidenceState.READY
                if current.state is EvidenceState.UPLOADING
                else current.state
            ),
            delivery_state=DeliveryState.FAILED_TERMINAL,
            next_delivery_attempt_at=None,
            last_delivery_error=error,
            record_version=current.record_version + 1,
        )
        self.save(failed, expected_record_version=current.record_version)
        return failed

    def mark_upload_unavailable(
        self,
        evidence_id: EvidenceId,
        *,
        expected_record_version: int,
        failed_at: datetime,
        error: str,
    ) -> EvidenceArtifact:
        """읽을 수 없는 API 8 binary를 API 9 제공 불가 대상으로 전환한다."""

        require_write_transaction(self._connection)
        current = self._require_in_flight(
            evidence_id,
            expected_record_version=expected_record_version,
        )
        if current.state is not EvidenceState.UPLOADING:
            raise EvidenceArtifactConflictError(
                "only UPLOADING evidence can become unavailable"
            )
        failed = replace(
            current,
            state=EvidenceState.FAILED,
            local_path=None,
            last_error=error,
            retention_disposition=(
                EvidenceRetentionDisposition.LOST_OR_CORRUPTED
            ),
            delivery_state=DeliveryState.PENDING,
            next_delivery_attempt_at=None,
            last_delivery_error=error,
            updated_at=failed_at,
            record_version=current.record_version + 1,
        )
        self.save(failed, expected_record_version=current.record_version)
        return failed

    def _require_in_flight(
        self,
        evidence_id: EvidenceId,
        *,
        expected_record_version: int,
    ) -> EvidenceArtifact:
        current = self.get(evidence_id)
        if current is None or current.record_version != expected_record_version:
            raise OptimisticConcurrencyError(
                f"EvidenceArtifact is missing or stale: {evidence_id}"
            )
        if current.delivery_state is not DeliveryState.IN_FLIGHT:
            raise EvidenceArtifactConflictError(
                f"evidence delivery is not IN_FLIGHT: {evidence_id}"
            )
        return current

    def add(self, artifact: EvidenceArtifact) -> None:
        """Capture identity를 추가한다. 초기 state는 RESERVED여야 한다."""

        require_write_transaction(self._connection)
        if artifact.record_version != 1:
            raise ValueError("new evidence record_version must be 1")
        if artifact.state is not EvidenceState.RESERVED:
            raise ValueError("new evidence must start in RESERVED state")
        if any(
            value is not None
            for value in (
                artifact.local_path,
                artifact.byte_size,
                artifact.checksum,
                artifact.last_error,
                artifact.backend_acked_at,
                artifact.retention_disposition,
                artifact.evicted_at,
            )
        ):
            raise ValueError("RESERVED evidence cannot already carry binary or terminal metadata")
        if self.count_for_incident(artifact.incident_id) >= (
            MAX_EVIDENCE_ARTIFACTS_PER_INCIDENT
        ):
            raise EvidenceArtifactConflictError(
                "an Incident may reserve at most two evidence artifacts"
            )
        try:
            self._connection.execute(
                """
                INSERT INTO evidence_artifacts(
                    evidence_id, incident_id, publication_revision,
                    captured_at_us, image_type, local_path, byte_size, checksum,
                    workflow_state, last_error, backend_ack_payload,
                    backend_acked_at_us, retention_disposition, evicted_at_us,
                    delivery_state, delivery_attempt_count,
                    next_delivery_attempt_at_us, last_delivery_error,
                    record_version, created_at_us, updated_at_us
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    uuid_to_text(artifact.evidence_id),
                    uuid_to_text(artifact.incident_id),
                    artifact.publication_revision,
                    datetime_to_epoch_microseconds(artifact.captured_at),
                    artifact.image_type,
                    str(artifact.local_path) if artifact.local_path is not None else None,
                    artifact.byte_size,
                    artifact.checksum,
                    artifact.state.value,
                    artifact.last_error,
                    (
                        datetime_to_epoch_microseconds(artifact.backend_acked_at)
                        if artifact.backend_acked_at is not None
                        else None
                    ),
                    (
                        artifact.retention_disposition.value
                        if artifact.retention_disposition is not None
                        else None
                    ),
                    (
                        datetime_to_epoch_microseconds(artifact.evicted_at)
                        if artifact.evicted_at is not None
                        else None
                    ),
                    (
                        artifact.delivery_state.value
                        if artifact.delivery_state is not None
                        else None
                    ),
                    artifact.delivery_attempt_count,
                    (
                        datetime_to_epoch_microseconds(
                            artifact.next_delivery_attempt_at
                        )
                        if artifact.next_delivery_attempt_at is not None
                        else None
                    ),
                    artifact.last_delivery_error,
                    artifact.record_version,
                    datetime_to_epoch_microseconds(artifact.created_at),
                    datetime_to_epoch_microseconds(artifact.updated_at),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise EvidenceArtifactConflictError(
                "EvidenceArtifact violates the durable metadata contract"
            ) from error

    def save(
        self,
        artifact: EvidenceArtifact,
        *,
        expected_record_version: int,
    ) -> None:
        """Workflow state와 mutable delivery/retention metadata를 optimistic update한다."""

        require_write_transaction(self._connection)
        if artifact.record_version != expected_record_version + 1:
            raise ValueError(
                "artifact.record_version must be exactly one greater than "
                "expected_record_version"
            )
        existing = self.get(artifact.evidence_id)
        if existing is None:
            raise OptimisticConcurrencyError("EvidenceArtifact is missing")
        self._validate_update(existing, artifact)

        try:
            new_version = optimistic_update(
                self._connection,
                table="evidence_artifacts",
                key_column="evidence_id",
                key_value=uuid_to_text(artifact.evidence_id),
                expected_record_version=expected_record_version,
                changes={
                    "publication_revision": artifact.publication_revision,
                    "local_path": (
                        str(artifact.local_path)
                        if artifact.local_path is not None
                        else None
                    ),
                    "byte_size": artifact.byte_size,
                    "checksum": artifact.checksum,
                    "workflow_state": artifact.state.value,
                    "last_error": artifact.last_error,
                    "backend_acked_at_us": (
                        datetime_to_epoch_microseconds(artifact.backend_acked_at)
                        if artifact.backend_acked_at is not None
                        else None
                    ),
                    "retention_disposition": (
                        artifact.retention_disposition.value
                        if artifact.retention_disposition is not None
                        else None
                    ),
                    "evicted_at_us": (
                        datetime_to_epoch_microseconds(artifact.evicted_at)
                        if artifact.evicted_at is not None
                        else None
                    ),
                    "delivery_state": (
                        artifact.delivery_state.value
                        if artifact.delivery_state is not None
                        else None
                    ),
                    "delivery_attempt_count": artifact.delivery_attempt_count,
                    "next_delivery_attempt_at_us": (
                        datetime_to_epoch_microseconds(
                            artifact.next_delivery_attempt_at
                        )
                        if artifact.next_delivery_attempt_at is not None
                        else None
                    ),
                    "last_delivery_error": artifact.last_delivery_error,
                    "updated_at_us": datetime_to_epoch_microseconds(
                        artifact.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise EvidenceArtifactConflictError(
                "EvidenceArtifact update violates the durable metadata contract"
            ) from error
        if new_version != artifact.record_version:  # pragma: no cover
            raise RuntimeError("optimistic update returned an unexpected record version")

    @staticmethod
    def _validate_update(
        existing: EvidenceArtifact,
        replacement: EvidenceArtifact,
    ) -> None:
        immutable_identity = (
            existing.incident_id,
            existing.captured_at,
            existing.image_type,
            existing.created_at,
        )
        requested_identity = (
            replacement.incident_id,
            replacement.captured_at,
            replacement.image_type,
            replacement.created_at,
        )
        if immutable_identity != requested_identity:
            raise EvidenceArtifactConflictError(
                "Evidence capture identity and creation metadata are immutable"
            )

        if existing.state is not replacement.state and replacement.state not in (
            _ALLOWED_STATE_TRANSITIONS[existing.state]
        ):
            raise EvidenceArtifactConflictError(
                f"invalid evidence state transition: "
                f"{existing.state.value} -> {replacement.state.value}"
            )
        if replacement.updated_at < existing.updated_at:
            raise EvidenceArtifactConflictError("updated_at must be monotonic")

        if existing.publication_revision is not None and (
            replacement.publication_revision != existing.publication_revision
        ):
            raise EvidenceArtifactConflictError("publication_revision is immutable once bound")
        if existing.byte_size is not None and replacement.byte_size != existing.byte_size:
            raise EvidenceArtifactConflictError("byte_size is immutable once recorded")
        if existing.checksum is not None and replacement.checksum != existing.checksum:
            raise EvidenceArtifactConflictError("checksum is immutable once recorded")
        if existing.backend_acked_at is not None and (
            replacement.backend_acked_at != existing.backend_acked_at
        ):
            raise EvidenceArtifactConflictError("backend_acked_at is immutable once recorded")
        if existing.evicted_at is not None and replacement.evicted_at != existing.evicted_at:
            raise EvidenceArtifactConflictError("evicted_at is immutable once recorded")
        if existing.last_error is not None and replacement.last_error != existing.last_error:
            raise EvidenceArtifactConflictError("last_error is immutable once recorded")
        if existing.retention_disposition is not None and (
            replacement.retention_disposition != existing.retention_disposition
        ):
            raise EvidenceArtifactConflictError(
                "retention_disposition is immutable once selected"
            )
        if replacement.delivery_attempt_count < existing.delivery_attempt_count:
            raise EvidenceArtifactConflictError(
                "delivery_attempt_count cannot decrease"
            )
        terminal_delivery_states = {
            DeliveryState.DELIVERED,
            DeliveryState.FAILED_TERMINAL,
        }
        if (
            existing.delivery_state in terminal_delivery_states
            and replacement.delivery_state is not existing.delivery_state
        ):
            raise EvidenceArtifactConflictError(
                "terminal evidence delivery state cannot change"
            )

        if existing.local_path is not None and replacement.local_path not in {
            existing.local_path,
            None,
        }:
            raise EvidenceArtifactConflictError("local_path cannot be redirected")
        if existing.local_path is not None and replacement.local_path is None and (
            replacement.state not in {EvidenceState.EVICTED, EvidenceState.FAILED}
        ):
            raise EvidenceArtifactConflictError(
                "only terminal loss or eviction may clear local_path"
            )

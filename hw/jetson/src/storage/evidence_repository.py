"""Evidence file spool과 SQLite metadata를 연결하는 repository.

Binary는 파일시스템에 두고 이 repository는 immutable capture identity와
crash recovery에 필요한 workflow state만 보존한다. 쓰기는 반드시
``UnitOfWork`` 안에서 호출해야 한다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

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
                    record_version, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
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

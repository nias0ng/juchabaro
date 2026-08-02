"""durable input 접수와 transactional outbox를 위한 최소 repository."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Mapping

from src.domain.models import DeliveryState

from .models import AcceptedInputRecord, OutboxRecord
from .unit_of_work import require_write_transaction

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AcceptedInputConflictError(RuntimeError):
    """같은 input identity·revision이 다른 payload로 재사용됐다."""


class OutboxConflictError(RuntimeError):
    """outbox publication identity가 다른 immutable data로 재사용됐다."""


class OptimisticConcurrencyError(RuntimeError):
    """저장 record가 호출자가 기대한 version에서 이미 변경됐다."""


@dataclass(frozen=True)
class AcceptanceResult:
    record: AcceptedInputRecord
    created: bool


@dataclass(frozen=True)
class OutboxEnqueueResult:
    record: OutboxRecord
    created: bool


def _utc_now_microseconds() -> int:
    return time.time_ns() // 1_000


def _payload_bytes(payload: bytes | bytearray | memoryview) -> bytes:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("immutable serialized payload must be bytes-like")
    return bytes(payload)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _accepted_input_from_row(row: sqlite3.Row) -> AcceptedInputRecord:
    return AcceptedInputRecord(
        input_type=str(row["input_type"]),
        input_identity=str(row["input_identity"]),
        input_revision=int(row["input_revision"]),
        payload_hash=str(row["payload_hash"]),
        request_payload=bytes(row["request_payload"]),
        workflow_state=str(row["workflow_state"]),
        result_payload=(
            bytes(row["result_payload"]) if row["result_payload"] is not None else None
        ),
        accepted_at_us=int(row["accepted_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
        record_version=int(row["record_version"]),
    )


def _outbox_from_row(row: sqlite3.Row) -> OutboxRecord:
    return OutboxRecord(
        delivery_id=str(row["delivery_id"]),
        aggregate_type=str(row["aggregate_type"]),
        aggregate_id=str(row["aggregate_id"]),
        destination=str(row["destination"]),
        publication_revision=int(row["publication_revision"]),
        transition_type=str(row["transition_type"]),
        payload=bytes(row["payload"]),
        payload_hash=str(row["payload_hash"]),
        idempotency_key=str(row["idempotency_key"]),
        delivery_state=DeliveryState(str(row["delivery_state"])),
        attempt_count=int(row["attempt_count"]),
        next_attempt_at_us=(
            int(row["next_attempt_at_us"])
            if row["next_attempt_at_us"] is not None
            else None
        ),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
        confirmed_at_us=(
            int(row["confirmed_at_us"])
            if row["confirmed_at_us"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
    )


class AcceptedInputRepository:
    """성공 응답 전에 inbound idempotency identity를 영속한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, input_type: str, input_identity: str, input_revision: int
    ) -> AcceptedInputRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM accepted_inputs
            WHERE input_type = ? AND input_identity = ? AND input_revision = ?
            """,
            (input_type, input_identity, input_revision),
        ).fetchone()
        return _accepted_input_from_row(row) if row is not None else None

    def accept(
        self,
        *,
        input_type: str,
        input_identity: str,
        input_revision: int,
        request_payload: bytes | bytearray | memoryview,
        workflow_state: str,
        accepted_at_us: int | None = None,
    ) -> AcceptanceResult:
        """한 번만 삽입하고 byte가 같은 retry에는 기존 record를 반환한다."""

        require_write_transaction(self._connection)
        if input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        payload = _payload_bytes(request_payload)
        payload_hash = _sha256(payload)

        existing = self.get(input_type, input_identity, input_revision)
        if existing is not None:
            if existing.payload_hash != payload_hash or existing.request_payload != payload:
                raise AcceptedInputConflictError(
                    "input identity and revision were reused with a different payload"
                )
            return AcceptanceResult(record=existing, created=False)

        now = accepted_at_us if accepted_at_us is not None else _utc_now_microseconds()
        try:
            self._connection.execute(
                """
                INSERT INTO accepted_inputs(
                    input_type, input_identity, input_revision, payload_hash,
                    request_payload, workflow_state, result_payload,
                    accepted_at_us, updated_at_us, record_version
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)
                """,
                (
                    input_type,
                    input_identity,
                    input_revision,
                    payload_hash,
                    payload,
                    workflow_state,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AcceptedInputConflictError(
                "input identity conflicts with an existing durable record"
            ) from error

        record = self.get(input_type, input_identity, input_revision)
        if record is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("accepted input disappeared during its transaction")
        return AcceptanceResult(record=record, created=True)


class OutboxRepository:
    """aggregate publication revision마다 immutable payload 하나를 만든다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_publication(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        destination: str,
        publication_revision: int,
    ) -> OutboxRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM outbox
            WHERE aggregate_type = ? AND aggregate_id = ?
              AND destination = ? AND publication_revision = ?
            """,
            (aggregate_type, aggregate_id, destination, publication_revision),
        ).fetchone()
        return _outbox_from_row(row) if row is not None else None

    def enqueue(
        self,
        *,
        delivery_id: str,
        aggregate_type: str,
        aggregate_id: str,
        destination: str,
        publication_revision: int,
        transition_type: str,
        payload: bytes | bytearray | memoryview,
        idempotency_key: str,
        created_at_us: int | None = None,
    ) -> OutboxEnqueueResult:
        require_write_transaction(self._connection)
        if publication_revision < 1:
            raise ValueError("publication_revision must be positive")
        immutable_payload = _payload_bytes(payload)
        payload_hash = _sha256(immutable_payload)

        existing = self.get_by_publication(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            destination=destination,
            publication_revision=publication_revision,
        )
        if existing is not None:
            immutable_identity = (
                existing.delivery_id,
                existing.transition_type,
                existing.payload,
                existing.payload_hash,
                existing.idempotency_key,
            )
            requested_identity = (
                delivery_id,
                transition_type,
                immutable_payload,
                payload_hash,
                idempotency_key,
            )
            if immutable_identity != requested_identity:
                raise OutboxConflictError(
                    "publication identity was reused with different immutable data"
                )
            return OutboxEnqueueResult(record=existing, created=False)

        now = created_at_us if created_at_us is not None else _utc_now_microseconds()
        try:
            self._connection.execute(
                """
                INSERT INTO outbox(
                    delivery_id, aggregate_type, aggregate_id, destination,
                    publication_revision, transition_type, payload, payload_hash,
                    idempotency_key, delivery_state, attempt_count,
                    next_attempt_at_us, last_error, created_at_us, updated_at_us,
                    confirmed_at_us, record_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0,
                          NULL, NULL, ?, ?, NULL, 1)
                """,
                (
                    delivery_id,
                    aggregate_type,
                    aggregate_id,
                    destination,
                    publication_revision,
                    transition_type,
                    immutable_payload,
                    payload_hash,
                    idempotency_key,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise OutboxConflictError(
                "delivery or idempotency identity conflicts with an existing outbox row"
            ) from error

        record = self.get_by_publication(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            destination=destination,
            publication_revision=publication_revision,
        )
        if record is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("outbox record disappeared during its transaction")
        return OutboxEnqueueResult(record=record, created=True)


def _quoted_identifier(identifier: str) -> str:
    if _SQL_IDENTIFIER.fullmatch(identifier) is None:
        raise ValueError(f"unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def optimistic_update(
    connection: sqlite3.Connection,
    *,
    table: str,
    key_column: str,
    key_value: Any,
    expected_record_version: int,
    changes: Mapping[str, Any],
) -> int:
    """field 변경과 ``record_version`` 증가를 원자적으로 수행한다.

    새 version을 반환한다. 누락 record와 stale version은 어느 쪽도 안전하게
    덮어쓸 수 없으므로 같은 오류로 처리한다.
    """

    require_write_transaction(connection)
    if expected_record_version < 1:
        raise ValueError("expected_record_version must be positive")
    if not changes:
        raise ValueError("optimistic update requires at least one field")
    if "record_version" in changes:
        raise ValueError("record_version is managed by optimistic_update")

    table_sql = _quoted_identifier(table)
    key_sql = _quoted_identifier(key_column)
    ordered_changes = sorted(changes.items())
    assignments = ", ".join(
        f"{_quoted_identifier(column)} = ?" for column, _ in ordered_changes
    )
    values = [value for _, value in ordered_changes]
    values.extend((key_value, expected_record_version))
    cursor = connection.execute(
        f"""
        UPDATE {table_sql}
        SET {assignments}, record_version = record_version + 1
        WHERE {key_sql} = ? AND record_version = ?
        """,
        values,
    )
    if cursor.rowcount != 1:
        raise OptimisticConcurrencyError(
            f"{table}.{key_column}={key_value!r} is missing or has a newer version"
        )
    return expected_record_version + 1

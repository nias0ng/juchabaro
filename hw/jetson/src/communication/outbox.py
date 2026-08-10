"""API adapter가 준비한 publication을 SQLite outbox에 보존한다.

Endpoint, DTO, serializer, ``delivery_id``와 ``Idempotency-Key`` 형식은 후속
cross-system 계약의 책임이다. 이 local facade는 그 adapter가 확정한
opaque identity와 exact payload bytes를 변경·재직렬화하지 않고, 호출자의
현재 SQLite transaction에 enqueue하는 책임만 가진다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.storage.repositories import OutboxEnqueueResult, OutboxRepository


@dataclass(frozen=True, kw_only=True)
class PreparedPublication:
    """Wire adapter가 한 번 확정한 immutable publication."""

    delivery_id: str
    aggregate_type: str
    aggregate_id: str
    destination: str
    publication_revision: int
    transition_type: str
    payload: bytes
    idempotency_key: str

    def __post_init__(self) -> None:
        for field_name in (
            "delivery_id",
            "aggregate_type",
            "aggregate_id",
            "destination",
            "transition_type",
            "idempotency_key",
        ):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if self.publication_revision < 1:
            raise ValueError("publication_revision must be positive")
        if not isinstance(self.payload, bytes):
            raise TypeError("prepared publication payload must be exact bytes")


class SQLiteOutboxWriter:
    """호출자의 활성 SQLite ``UnitOfWork``에 prepared row를 enqueue한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._repository = OutboxRepository(connection)

    def enqueue(
        self,
        prepared: PreparedPublication,
        *,
        created_at_us: int | None = None,
    ) -> OutboxEnqueueResult:
        """Prepared identity·bytes를 해석하지 않고 그대로 보존한다."""

        if not isinstance(prepared, PreparedPublication):
            raise TypeError("prepared must be a PreparedPublication")
        return self._repository.enqueue(
            delivery_id=prepared.delivery_id,
            aggregate_type=prepared.aggregate_type,
            aggregate_id=prepared.aggregate_id,
            destination=prepared.destination,
            publication_revision=prepared.publication_revision,
            transition_type=prepared.transition_type,
            payload=prepared.payload,
            idempotency_key=prepared.idempotency_key,
            created_at_us=created_at_us,
        )

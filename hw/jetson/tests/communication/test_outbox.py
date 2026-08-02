"""Prepared publication을 해석하지 않는 SQLite outbox facade 테스트."""

from __future__ import annotations

import hashlib

import pytest

from src.communication import outbox as outbox_module
from src.communication.outbox import PreparedPublication, SQLiteOutboxWriter
from src.storage.database import open_database
from src.storage.repositories import OutboxConflictError
from src.storage.unit_of_work import TransactionStateError, UnitOfWork


RAW_PAYLOAD = b"\x00\xffadapter-owned-wire-bytes\n"


def _prepared(*, payload: bytes = RAW_PAYLOAD) -> PreparedPublication:
    return PreparedPublication(
        delivery_id="opaque-delivery-id/from-adapter",
        aggregate_type="adapter-owned-aggregate-type",
        aggregate_id="opaque aggregate identity",
        destination="adapter-owned-destination",
        publication_revision=7,
        transition_type="adapter-owned-transition",
        payload=payload,
        idempotency_key="opaque Idempotency-Key from adapter",
    )


def test_writer_preserves_adapter_identity_and_exact_payload_bytes(tmp_path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    writer = SQLiteOutboxWriter(connection)
    prepared = _prepared()
    try:
        with UnitOfWork(connection):
            result = writer.enqueue(prepared, created_at_us=100)

        assert result.created is True
        assert result.record.delivery_id == prepared.delivery_id
        assert result.record.aggregate_type == prepared.aggregate_type
        assert result.record.aggregate_id == prepared.aggregate_id
        assert result.record.destination == prepared.destination
        assert result.record.publication_revision == prepared.publication_revision
        assert result.record.transition_type == prepared.transition_type
        assert result.record.payload == RAW_PAYLOAD
        assert result.record.payload_hash == hashlib.sha256(RAW_PAYLOAD).hexdigest()
        assert result.record.idempotency_key == prepared.idempotency_key
    finally:
        connection.close()


def test_identical_prepared_retry_reuses_the_existing_row(tmp_path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    writer = SQLiteOutboxWriter(connection)
    prepared = _prepared()
    try:
        with UnitOfWork(connection):
            first = writer.enqueue(prepared, created_at_us=100)
        with UnitOfWork(connection):
            retry = writer.enqueue(prepared, created_at_us=200)

        assert first.created is True
        assert retry.created is False
        assert retry.record == first.record
        assert retry.record.created_at_us == 100
    finally:
        connection.close()


def test_writer_requires_the_callers_existing_unit_of_work(tmp_path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with pytest.raises(TransactionStateError, match="UnitOfWork"):
            SQLiteOutboxWriter(connection).enqueue(_prepared())
    finally:
        connection.close()


def test_same_publication_with_different_prepared_bytes_is_a_conflict(
    tmp_path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    writer = SQLiteOutboxWriter(connection)
    try:
        with UnitOfWork(connection):
            original = writer.enqueue(_prepared(), created_at_us=100)

        with pytest.raises(OutboxConflictError, match="immutable data"):
            with UnitOfWork(connection):
                writer.enqueue(_prepared(payload=b"different adapter bytes"))

        row = connection.execute(
            "SELECT payload FROM outbox WHERE delivery_id = ?",
            (original.record.delivery_id,),
        ).fetchone()
        assert bytes(row["payload"]) == RAW_PAYLOAD
    finally:
        connection.close()


def test_local_facade_exposes_no_jsonl_or_wire_serializer_policy() -> None:
    assert not hasattr(outbox_module, "JsonlOutbox")
    assert not hasattr(outbox_module, "transition_to_jsonable")
    assert not hasattr(outbox_module, "publication_idempotency_key")

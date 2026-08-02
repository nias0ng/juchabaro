"""SQLite transactional outbox claim·retry·confirmation state machine 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domain.models import DeliveryState
from src.storage.database import open_database
from src.storage.models import PublicationApplicationStatus
from src.storage.repositories import (
    OutboxAlreadyDeliveredError,
    OutboxConflictError,
    OutboxRepository,
)
from src.storage.unit_of_work import UnitOfWork


def _enqueue(
    repository: OutboxRepository,
    connection,
    *,
    aggregate_id: str,
    revision: int,
    created_at_us: int,
):
    with UnitOfWork(connection):
        return repository.enqueue(
            delivery_id=f"delivery:{aggregate_id}:{revision}",
            aggregate_type="Incident",
            aggregate_id=aggregate_id,
            destination="backend",
            publication_revision=revision,
            transition_type="OPEN" if revision == 1 else "RESOLVE",
            payload=f'{{"aggregate":"{aggregate_id}","revision":{revision}}}'.encode(),
            idempotency_key=f"publication:{aggregate_id}:{revision}",
            created_at_us=created_at_us,
        ).record


def _claim(repository: OutboxRepository, connection, *, now_us: int):
    with UnitOfWork(connection):
        return repository.claim_next(destination="backend", now_us=now_us)


def _deliver(
    repository: OutboxRepository,
    connection,
    record,
    *,
    confirmed_at_us: int,
):
    with UnitOfWork(connection):
        return repository.mark_delivered(
            record.delivery_id,
            expected_record_version=record.record_version,
            application_status=PublicationApplicationStatus.APPLIED,
            confirmed_payload_hash=record.payload_hash,
            confirmed_at_us=confirmed_at_us,
            receipt_expires_at_us=confirmed_at_us + 1_000,
        )


def test_claim_blocks_revision_gap_but_does_not_block_another_aggregate(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    try:
        _enqueue(
            repository,
            connection,
            aggregate_id="with-gap",
            revision=2,
            created_at_us=10,
        )
        _enqueue(
            repository,
            connection,
            aggregate_id="independent",
            revision=1,
            created_at_us=20,
        )

        independent = _claim(repository, connection, now_us=100)
        assert independent is not None
        assert independent.aggregate_id == "independent"
        _deliver(repository, connection, independent, confirmed_at_us=110)
        assert _claim(repository, connection, now_us=120) is None

        _enqueue(
            repository,
            connection,
            aggregate_id="with-gap",
            revision=1,
            created_at_us=30,
        )
        first = _claim(repository, connection, now_us=130)
        assert first is not None
        assert (first.aggregate_id, first.publication_revision) == ("with-gap", 1)
        delivered = _deliver(repository, connection, first, confirmed_at_us=140)
        assert delivered.delivery_state is DeliveryState.DELIVERED

        second = _claim(repository, connection, now_us=150)
        assert second is not None
        assert (second.aggregate_id, second.publication_revision) == ("with-gap", 2)
    finally:
        connection.close()


def test_retry_keeps_payload_and_key_and_only_becomes_due_at_scheduled_time(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    try:
        original = _enqueue(
            repository,
            connection,
            aggregate_id="retry",
            revision=1,
            created_at_us=10,
        )
        claimed = _claim(repository, connection, now_us=100)
        assert claimed is not None and claimed.attempt_count == 1

        with UnitOfWork(connection):
            waiting = repository.schedule_retry(
                claimed.delivery_id,
                expected_record_version=claimed.record_version,
                next_attempt_at_us=200,
                error="network unavailable",
                updated_at_us=110,
            )

        assert waiting.delivery_state is DeliveryState.RETRY_WAIT
        assert _claim(repository, connection, now_us=199) is None
        retried = _claim(repository, connection, now_us=200)
        assert retried is not None
        assert retried.attempt_count == 2
        assert retried.payload == original.payload
        assert retried.payload_hash == original.payload_hash
        assert retried.idempotency_key == original.idempotency_key
    finally:
        connection.close()


def test_restart_recovers_in_flight_without_changing_immutable_publication(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    try:
        original = _enqueue(
            repository,
            connection,
            aggregate_id="restart",
            revision=1,
            created_at_us=10,
        )
        claimed = _claim(repository, connection, now_us=100)
        assert claimed is not None

        with UnitOfWork(connection):
            assert repository.recover_in_flight(now_us=200) == 1
        recovered = repository.get_by_delivery_id(original.delivery_id)
        assert recovered is not None
        assert recovered.delivery_state is DeliveryState.RETRY_WAIT
        assert recovered.next_attempt_at_us == 200
        assert recovered.attempt_count == 1

        reclaimed = _claim(repository, connection, now_us=200)
        assert reclaimed is not None
        assert reclaimed.attempt_count == 2
        assert reclaimed.payload == original.payload
        assert reclaimed.idempotency_key == original.idempotency_key
    finally:
        connection.close()


def test_terminal_failure_blocks_successor_until_explicit_retry(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    try:
        _enqueue(
            repository,
            connection,
            aggregate_id="terminal",
            revision=1,
            created_at_us=10,
        )
        _enqueue(
            repository,
            connection,
            aggregate_id="terminal",
            revision=2,
            created_at_us=20,
        )
        first = _claim(repository, connection, now_us=100)
        assert first is not None
        with UnitOfWork(connection):
            failed = repository.mark_failed_terminal(
                first.delivery_id,
                expected_record_version=first.record_version,
                error="schema rejected",
                updated_at_us=110,
            )
        assert failed.delivery_state is DeliveryState.FAILED_TERMINAL
        assert _claim(repository, connection, now_us=120) is None

        with UnitOfWork(connection):
            waiting = repository.retry_failed_terminal(
                failed.delivery_id,
                expected_record_version=failed.record_version,
                next_attempt_at_us=200,
                updated_at_us=130,
            )
        assert waiting.delivery_state is DeliveryState.RETRY_WAIT
        assert _claim(repository, connection, now_us=199) is None

        retried = _claim(repository, connection, now_us=200)
        assert retried is not None and retried.publication_revision == 1
        _deliver(repository, connection, retried, confirmed_at_us=210)
        successor = _claim(repository, connection, now_us=220)
        assert successor is not None and successor.publication_revision == 2
    finally:
        connection.close()


def test_confirmation_hash_must_match_and_receipt_is_committed_with_delivery(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    try:
        _enqueue(
            repository,
            connection,
            aggregate_id="confirmation",
            revision=1,
            created_at_us=10,
        )
        claimed = _claim(repository, connection, now_us=100)
        assert claimed is not None

        with pytest.raises(OutboxConflictError, match="payload hash"):
            with UnitOfWork(connection):
                repository.mark_delivered(
                    claimed.delivery_id,
                    expected_record_version=claimed.record_version,
                    application_status=PublicationApplicationStatus.APPLIED,
                    confirmed_payload_hash="different",
                    confirmed_at_us=110,
                    receipt_expires_at_us=1_110,
                )
        unchanged = repository.get_by_delivery_id(claimed.delivery_id)
        assert unchanged is not None
        assert unchanged.delivery_state is DeliveryState.IN_FLIGHT

        delivered = _deliver(repository, connection, claimed, confirmed_at_us=120)
        receipt = connection.execute(
            """
            SELECT delivery_id, payload_hash, application_status, confirmed_at_us
            FROM delivery_receipts WHERE delivery_id = ?
            """,
            (claimed.delivery_id,),
        ).fetchone()
        assert delivered.delivery_state is DeliveryState.DELIVERED
        assert tuple(receipt) == (
            claimed.delivery_id,
            claimed.payload_hash,
            "APPLIED",
            120,
        )
    finally:
        connection.close()


def test_mark_delivered_savepoint_prevents_partial_commit_when_error_is_caught(
    tmp_path: Path,
) -> None:
    """Caller가 UoW 안에서 예외를 잡아도 state update만 남지 않는다."""

    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    try:
        _enqueue(
            repository,
            connection,
            aggregate_id="savepoint",
            revision=1,
            created_at_us=10,
        )
        claimed = _claim(repository, connection, now_us=100)
        assert claimed is not None

        with UnitOfWork(connection):
            # mark_delivered의 update 뒤 receipt INSERT만 실패하도록 선점한다.
            connection.execute(
                """
                INSERT INTO delivery_receipts(
                    delivery_id, aggregate_type, aggregate_id, destination,
                    publication_revision, payload_hash, application_status,
                    confirmed_at_us, expires_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, 'APPLIED', ?, ?)
                """,
                (
                    "preexisting-receipt",
                    claimed.aggregate_type,
                    claimed.aggregate_id,
                    claimed.destination,
                    claimed.publication_revision,
                    claimed.payload_hash,
                    90,
                    1_090,
                ),
            )
            try:
                repository.mark_delivered(
                    claimed.delivery_id,
                    expected_record_version=claimed.record_version,
                    application_status=PublicationApplicationStatus.APPLIED,
                    confirmed_payload_hash=claimed.payload_hash,
                    confirmed_at_us=110,
                    receipt_expires_at_us=1_110,
                )
            except OutboxConflictError:
                pass
            else:  # pragma: no cover - regression guard.
                raise AssertionError("conflicting receipt must reject confirmation")

        unchanged = repository.get_by_delivery_id(claimed.delivery_id)
        assert unchanged is not None
        assert unchanged.delivery_state is DeliveryState.IN_FLIGHT
        assert unchanged.record_version == claimed.record_version
        assert unchanged.confirmed_at_us is None
    finally:
        connection.close()


def test_enqueue_rejects_a_publication_already_compacted_to_receipt(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = OutboxRepository(connection)
    try:
        original = _enqueue(
            repository,
            connection,
            aggregate_id="receipt-only",
            revision=1,
            created_at_us=10,
        )
        claimed = _claim(repository, connection, now_us=100)
        assert claimed is not None
        _deliver(repository, connection, claimed, confirmed_at_us=110)
        with UnitOfWork(connection):
            connection.execute(
                "DELETE FROM outbox WHERE delivery_id = ?",
                (original.delivery_id,),
            )

        with pytest.raises(OutboxAlreadyDeliveredError, match="already confirmed"):
            with UnitOfWork(connection):
                repository.enqueue(
                    delivery_id=original.delivery_id,
                    aggregate_type=original.aggregate_type,
                    aggregate_id=original.aggregate_id,
                    destination=original.destination,
                    publication_revision=original.publication_revision,
                    transition_type=original.transition_type,
                    payload=original.payload,
                    idempotency_key=original.idempotency_key,
                    created_at_us=200,
                )

        with pytest.raises(OutboxConflictError, match="different payload"):
            with UnitOfWork(connection):
                repository.enqueue(
                    delivery_id=original.delivery_id,
                    aggregate_type=original.aggregate_type,
                    aggregate_id=original.aggregate_id,
                    destination=original.destination,
                    publication_revision=original.publication_revision,
                    transition_type=original.transition_type,
                    payload=b"different payload after delivery",
                    idempotency_key=original.idempotency_key,
                    created_at_us=200,
                )

        assert repository.get_by_delivery_id(original.delivery_id) is None
        receipt_count = connection.execute(
            "SELECT COUNT(*) FROM delivery_receipts WHERE delivery_id = ?",
            (original.delivery_id,),
        ).fetchone()[0]
        assert receipt_count == 1
    finally:
        connection.close()

"""Outbox publisher의 성공·retry·terminal·restart 상태 전이를 검증한다."""

from __future__ import annotations

import hashlib

from src.application.outbox_publisher import OutboxPublisher
from src.communication.backend_client import (
    PublicationConfirmation,
    RetryableBackendPublicationError,
    TerminalBackendPublicationError,
)
from src.communication.outbox import PreparedPublication, SQLiteOutboxWriter
from src.domain.models import DeliveryState
from src.storage.database import connect_database, open_database
from src.storage.models import PublicationApplicationStatus
from src.storage.repositories import OutboxRepository
from src.storage.unit_of_work import UnitOfWork


NOW_US = 10_000_000


class _Client:
    def __init__(self, result) -> None:
        self.result = result
        self.published = []
        self.closed = False

    def publish(self, publication):
        self.published.append(publication)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def close(self) -> None:
        self.closed = True


def test_publish_once_marks_applied_row_delivered_and_keeps_receipt(tmp_path) -> None:
    database = tmp_path / "jetson.db"
    prepared = _seed(database)
    payload_hash = hashlib.sha256(prepared.payload).hexdigest()
    client = _Client(
        PublicationConfirmation(
            application_status=PublicationApplicationStatus.APPLIED,
            payload_hash=payload_hash,
            backend_correlation={"eventId": 301},
        )
    )
    publisher = _publisher(database, client)

    assert publisher.publish_once() is True

    connection = connect_database(database)
    try:
        record = OutboxRepository(connection).get_by_delivery_id(
            prepared.delivery_id
        )
        receipt = connection.execute(
            "SELECT * FROM delivery_receipts WHERE delivery_id = ?",
            (prepared.delivery_id,),
        ).fetchone()
        assert record is not None
        assert record.delivery_state is DeliveryState.DELIVERED
        assert record.attempt_count == 1
        assert receipt["application_status"] == "APPLIED"
        assert bytes(receipt["backend_correlation_payload"]) == b'{"eventId":301}'
        assert receipt["expires_at_us"] - receipt["confirmed_at_us"] == (
            14 * 24 * 60 * 60 * 1_000_000
        )
    finally:
        connection.close()


def test_publish_once_schedules_only_retryable_failure(tmp_path) -> None:
    database = tmp_path / "jetson.db"
    prepared = _seed(database)
    publisher = _publisher(
        database,
        _Client(RetryableBackendPublicationError("offline")),
    )

    assert publisher.publish_once() is True

    connection = connect_database(database)
    try:
        record = OutboxRepository(connection).get_by_delivery_id(
            prepared.delivery_id
        )
        assert record is not None
        assert record.delivery_state is DeliveryState.RETRY_WAIT
        assert record.next_attempt_at_us == NOW_US + 1_000_000
        assert "offline" in record.last_error
    finally:
        connection.close()


def test_publish_once_quarantines_terminal_failure(tmp_path) -> None:
    database = tmp_path / "jetson.db"
    prepared = _seed(database)
    publisher = _publisher(
        database,
        _Client(TerminalBackendPublicationError("invalid contract")),
    )

    assert publisher.publish_once() is True

    connection = connect_database(database)
    try:
        record = OutboxRepository(connection).get_by_delivery_id(
            prepared.delivery_id
        )
        assert record is not None
        assert record.delivery_state is DeliveryState.FAILED_TERMINAL
        assert record.next_attempt_at_us is None
        assert "invalid contract" in record.last_error
    finally:
        connection.close()


def test_recover_in_flight_makes_interrupted_publication_due(tmp_path) -> None:
    database = tmp_path / "jetson.db"
    prepared = _seed(database)
    connection = connect_database(database)
    try:
        with UnitOfWork(connection):
            claimed = OutboxRepository(connection).claim_next(
                destination="backend",
                now_us=NOW_US,
            )
        assert claimed is not None
    finally:
        connection.close()

    publisher = _publisher(database, _Client(None))
    assert publisher.recover_in_flight() == 1

    connection = connect_database(database)
    try:
        record = OutboxRepository(connection).get_by_delivery_id(
            prepared.delivery_id
        )
        assert record is not None
        assert record.delivery_state is DeliveryState.RETRY_WAIT
        assert record.next_attempt_at_us == NOW_US
        assert record.last_error == "PROCESS_RESTARTED"
    finally:
        connection.close()


def _publisher(database, client: _Client) -> OutboxPublisher:
    return OutboxPublisher(
        connection_factory=lambda: connect_database(database),
        client=client,
        retry_initial_seconds=1.0,
        retry_max_seconds=8.0,
        clock_us=lambda: NOW_US,
    )


def _seed(database) -> PreparedPublication:
    connection = open_database(database)
    prepared = PreparedPublication(
        delivery_id="Incident:1f21d60c-c077-4fb4-a092-7cbdb5fc5a91:1",
        aggregate_type="Incident",
        aggregate_id="1f21d60c-c077-4fb4-a092-7cbdb5fc5a91",
        destination="backend",
        publication_revision=1,
        transition_type="OPEN",
        payload=b'{"incidentId":"1f21d60c-c077-4fb4-a092-7cbdb5fc5a91"}',
        idempotency_key="Incident:1f21d60c-c077-4fb4-a092-7cbdb5fc5a91:1",
    )
    try:
        with UnitOfWork(connection):
            SQLiteOutboxWriter(connection).enqueue(
                prepared,
                created_at_us=1,
            )
    finally:
        connection.close()
    return prepared

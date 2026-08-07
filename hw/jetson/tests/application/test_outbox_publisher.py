"""Outbox publisher의 성공·retry·terminal·restart 상태 전이를 검증한다."""

from __future__ import annotations

import hashlib
import logging
from threading import Event

import pytest

from src.application.outbox_publisher import (
    OutboxPublisher,
    OutboxPublisherWorker,
)
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


class _RecoveringWorkerPublisher:
    def __init__(self) -> None:
        self.recover_count = 0
        self.publish_count = 0
        self.closed_count = 0
        self.resumed = Event()

    def recover_in_flight(self) -> int:
        self.recover_count += 1
        if self.recover_count == 2:
            raise RuntimeError("recovery storage busy")
        return 1

    def publish_once(self) -> bool:
        self.publish_count += 1
        if self.publish_count == 1:
            raise RuntimeError("local ACK persistence failed")
        self.resumed.set()
        return False

    def close(self) -> None:
        self.closed_count += 1


def test_worker_recovers_in_flight_and_continues_after_item_failure() -> None:
    publisher = _RecoveringWorkerPublisher()
    worker = OutboxPublisherWorker(
        publisher,
        poll_interval_seconds=0.01,
    )

    worker.start()
    assert publisher.resumed.wait(timeout=1.0)
    assert worker.is_running is True
    worker.stop()

    assert publisher.recover_count == 3
    assert publisher.closed_count == 1
    assert worker.failure is None


def test_worker_cannot_start_after_it_has_closed_the_publisher() -> None:
    publisher = _RecoveringWorkerPublisher()
    worker = OutboxPublisherWorker(publisher)

    worker.stop()
    with pytest.raises(RuntimeError, match="already closed"):
        worker.start()

    assert publisher.recover_count == 0
    assert publisher.publish_count == 0
    assert publisher.closed_count == 1


def test_publish_once_marks_applied_row_delivered_and_keeps_receipt(
    tmp_path,
    caplog,
) -> None:
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

    with caplog.at_level(
        logging.INFO,
        logger="src.application.outbox_publisher",
    ):
        assert publisher.publish_once() is True

    assert "Backend publication 전송이 완료됐습니다." in caplog.text
    assert "aggregateType=Incident" in caplog.text
    assert "transitionType=OPEN" in caplog.text
    assert "applicationStatus=APPLIED" in caplog.text
    assert prepared.payload.decode("utf-8") not in caplog.text

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


def test_ack_persistence_failure_retries_exact_outbox_publication(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "jetson.db"
    prepared = _seed(database)
    client = _Client(
        PublicationConfirmation(
            application_status=PublicationApplicationStatus.APPLIED,
            payload_hash=hashlib.sha256(prepared.payload).hexdigest(),
            backend_correlation={"eventId": 301},
        )
    )
    publisher = _publisher(database, client)
    real_mark_delivered = publisher._mark_delivered
    failures = [RuntimeError("local ACK commit failed")]

    def fail_once(publication, confirmation) -> None:
        if failures:
            raise failures.pop()
        real_mark_delivered(publication, confirmation)

    monkeypatch.setattr(publisher, "_mark_delivered", fail_once)

    with pytest.raises(RuntimeError, match="local ACK commit failed"):
        publisher.publish_once()
    assert publisher.recover_in_flight() == 1
    assert publisher.publish_once() is True

    assert len(client.published) == 2
    assert client.published[0].payload == client.published[1].payload
    assert (
        client.published[0].idempotency_key
        == client.published[1].idempotency_key
        == prepared.idempotency_key
    )
    connection = connect_database(database)
    try:
        delivered = OutboxRepository(connection).get_by_delivery_id(
            prepared.delivery_id
        )
        assert delivered is not None
        assert delivered.delivery_state is DeliveryState.DELIVERED
        assert delivered.attempt_count == 2
    finally:
        connection.close()


def test_publish_once_schedules_only_retryable_failure(tmp_path, caplog) -> None:
    database = tmp_path / "jetson.db"
    prepared = _seed(database)
    publisher = _publisher(
        database,
        _Client(RetryableBackendPublicationError("offline")),
    )

    with caplog.at_level(
        logging.WARNING,
        logger="src.application.outbox_publisher",
    ):
        assert publisher.publish_once() is True

    assert "Backend publication 재시도가 예약됐습니다." in caplog.text
    assert "attempt=1" in caplog.text
    assert "RetryableBackendPublicationError: offline" in caplog.text

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


def test_publish_once_quarantines_terminal_failure(tmp_path, caplog) -> None:
    database = tmp_path / "jetson.db"
    prepared = _seed(database)
    publisher = _publisher(
        database,
        _Client(TerminalBackendPublicationError("invalid contract")),
    )

    with caplog.at_level(
        logging.ERROR,
        logger="src.application.outbox_publisher",
    ):
        assert publisher.publish_once() is True

    assert "Backend publication이 영구 실패로 격리됐습니다." in caplog.text
    assert "attempt=1" in caplog.text
    assert "TerminalBackendPublicationError: invalid contract" in caplog.text

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

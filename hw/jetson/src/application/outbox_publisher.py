"""SQLite outbox의 API 6·7·10 publication을 Backend로 전달한다.

claim, HTTP, 결과 저장을 서로 다른 경계로 둔다. 따라서 느린 네트워크 동안
SQLite write transaction을 잡지 않으며, process 중단으로 남은 IN_FLIGHT row는
다음 기동에서 RETRY_WAIT으로 복구된다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from threading import Event, Thread
from typing import Protocol

from src.communication.backend_client import (
    PublicationConfirmation,
    RetryableBackendPublicationError,
    TerminalBackendPublicationError,
)
from src.communication.backend_publication_preparer import BACKEND_DESTINATION
from src.storage.models import OutboxRecord
from src.storage.repositories import OutboxRepository
from src.storage.unit_of_work import UnitOfWork


logger = logging.getLogger(__name__)

_RECEIPT_RETENTION_US = 14 * 24 * 60 * 60 * 1_000_000


class PublicationClient(Protocol):
    """OutboxPublisher가 요구하는 Backend 전송 경계."""

    def publish(self, publication: OutboxRecord) -> PublicationConfirmation:
        ...

    def close(self) -> None:
        ...


ConnectionFactory = Callable[[], sqlite3.Connection]
ClockMicroseconds = Callable[[], int]


class OutboxPublisher:
    """due publication 하나씩 claim하고 전달 결과를 durable하게 반영한다."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        client: PublicationClient,
        retry_initial_seconds: float = 1.0,
        retry_max_seconds: float = 300.0,
        clock_us: ClockMicroseconds | None = None,
    ) -> None:
        if retry_initial_seconds <= 0:
            raise ValueError("retry_initial_seconds must be positive")
        if retry_max_seconds < retry_initial_seconds:
            raise ValueError(
                "retry_max_seconds must not be smaller than retry_initial_seconds"
            )
        self._connection_factory = connection_factory
        self._client = client
        self._retry_initial_seconds = retry_initial_seconds
        self._retry_max_seconds = retry_max_seconds
        self._clock_us = clock_us or (lambda: time.time_ns() // 1_000)

    def recover_in_flight(self) -> int:
        """이전 process가 HTTP 결과를 기록하기 전에 중단된 row를 복구한다."""

        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                return OutboxRepository(connection).recover_in_flight(
                    now_us=self._clock_us()
                )
        finally:
            connection.close()

    def publish_once(self) -> bool:
        """due row가 있으면 하나를 처리하고, 없으면 ``False``를 반환한다."""

        publication = self._claim_next()
        if publication is None:
            return False
        try:
            confirmation = self._client.publish(publication)
        except RetryableBackendPublicationError as error:
            self._schedule_retry(publication, error)
        except TerminalBackendPublicationError as error:
            self._mark_failed_terminal(publication, error)
        else:
            self._mark_delivered(publication, confirmation)
        return True

    def close(self) -> None:
        """Backend client의 connection pool을 닫는다."""

        self._client.close()

    def _claim_next(self) -> OutboxRecord | None:
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                return OutboxRepository(connection).claim_next(
                    destination=BACKEND_DESTINATION,
                    now_us=self._clock_us(),
                )
        finally:
            connection.close()

    def _schedule_retry(
        self,
        publication: OutboxRecord,
        error: Exception,
    ) -> None:
        now_us = self._clock_us()
        exponent = min(max(publication.attempt_count - 1, 0), 30)
        delay_seconds = min(
            self._retry_max_seconds,
            self._retry_initial_seconds * (2**exponent),
        )
        next_attempt_at_us = now_us + round(delay_seconds * 1_000_000)
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                OutboxRepository(connection).schedule_retry(
                    publication.delivery_id,
                    expected_record_version=publication.record_version,
                    next_attempt_at_us=next_attempt_at_us,
                    error=_error_text(error),
                    updated_at_us=now_us,
                )
        finally:
            connection.close()
        logger.warning(
            "Backend publication 재시도가 예약됐습니다. "
            "aggregateType=%s transitionType=%s deliveryId=%s "
            "attempt=%d nextAttemptAtUs=%d error=%s",
            publication.aggregate_type,
            publication.transition_type,
            publication.delivery_id,
            publication.attempt_count,
            next_attempt_at_us,
            _error_text(error),
        )

    def _mark_failed_terminal(
        self,
        publication: OutboxRecord,
        error: Exception,
    ) -> None:
        now_us = self._clock_us()
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                OutboxRepository(connection).mark_failed_terminal(
                    publication.delivery_id,
                    expected_record_version=publication.record_version,
                    error=_error_text(error),
                    updated_at_us=now_us,
                )
        finally:
            connection.close()
        logger.error(
            "Backend publication이 영구 실패로 격리됐습니다. "
            "aggregateType=%s transitionType=%s deliveryId=%s "
            "attempt=%d error=%s",
            publication.aggregate_type,
            publication.transition_type,
            publication.delivery_id,
            publication.attempt_count,
            _error_text(error),
        )

    def _mark_delivered(
        self,
        publication: OutboxRecord,
        confirmation: PublicationConfirmation,
    ) -> None:
        confirmed_at_us = self._clock_us()
        correlation_payload = json.dumps(
            dict(confirmation.backend_correlation),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                OutboxRepository(connection).mark_delivered(
                    publication.delivery_id,
                    expected_record_version=publication.record_version,
                    application_status=confirmation.application_status,
                    confirmed_payload_hash=confirmation.payload_hash,
                    confirmed_at_us=confirmed_at_us,
                    receipt_expires_at_us=(
                        confirmed_at_us + _RECEIPT_RETENTION_US
                    ),
                    backend_correlation_payload=correlation_payload,
                )
        finally:
            connection.close()
        logger.info(
            "Backend publication 전송이 완료됐습니다. "
            "aggregateType=%s transitionType=%s deliveryId=%s "
            "attempt=%d applicationStatus=%s",
            publication.aggregate_type,
            publication.transition_type,
            publication.delivery_id,
            publication.attempt_count,
            confirmation.application_status.value,
        )


class OutboxPublisherWorker:
    """OutboxPublisher를 하나의 process-local background thread에서 실행한다."""

    def __init__(
        self,
        publisher: OutboxPublisher,
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
        self._publisher_closed = False

    @property
    def failure(self) -> Exception | None:
        return self._failure

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """crash recovery를 마친 뒤 publisher loop를 시작한다."""

        if self._thread is not None:
            raise RuntimeError("outbox publisher worker may only be started once")
        if self._publisher_closed:
            raise RuntimeError("outbox publisher worker is already closed")
        self._publisher.recover_in_flight()
        thread = Thread(
            target=self._run,
            name="jetson-outbox-publisher",
            daemon=False,
        )
        self._thread = thread
        try:
            thread.start()
        except Exception:
            self._thread = None
            self._close_publisher()
            raise

    def stop(self) -> None:
        """polling을 깨우고 진행 중인 제한시간 HTTP 요청까지 회수한다."""

        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join()
        self._close_publisher()

    def _close_publisher(self) -> None:
        if self._publisher_closed:
            return
        try:
            self._publisher.close()
        finally:
            self._publisher_closed = True

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            try:
                processed = self._publisher.publish_once()
            except Exception as error:
                self._failure = error
                logger.exception(
                    "Jetson outbox publication 항목 처리가 중단되어 "
                    "IN_FLIGHT를 복구합니다."
                )
                if not self._recover_until_ready():
                    break
                self._stop_requested.wait(self._poll_interval_seconds)
                continue
            self._failure = None
            if not processed:
                self._stop_requested.wait(self._poll_interval_seconds)

    def _recover_until_ready(self) -> bool:
        while not self._stop_requested.is_set():
            try:
                self._publisher.recover_in_flight()
            except Exception as error:
                self._failure = error
                logger.exception(
                    "Jetson outbox IN_FLIGHT 복구 전에 publication을 "
                    "재개하지 않습니다."
                )
                self._stop_requested.wait(self._poll_interval_seconds)
                continue
            return True
        return False


def _error_text(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"[:1_000]

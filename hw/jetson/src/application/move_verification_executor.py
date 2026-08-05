"""API 11 command를 실행하고 API 12 결과 publication을 원자적으로 만든다.

워커는 durable ``ACCEPTED`` command를 ``CHECKING``으로 전이한 뒤 최신 Incident
snapshot을 판정한다. 결과가 확정되면 attempt 완료와 outbox enqueue를 같은 SQLite
transaction에 기록하므로 process 재시작과 Backend 장애에도 결과가 유실되지 않는다.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event, Thread

from src.communication.backend_publication_preparer import (
    BackendPublicationPreparer,
)
from src.communication.models import (
    MoveVerificationAttempt,
    MoveVerificationIncidentResult,
    MoveVerificationResult,
    MoveVerificationState,
)
from src.communication.outbox import SQLiteOutboxWriter
from src.domain.models import ObservationState
from src.parking.models import Incident, IncidentId, IncidentState
from src.storage.aggregate_repositories import IncidentRepository
from src.storage.codecs import datetime_to_epoch_microseconds
from src.storage.repositories import MoveVerificationAttemptRepository
from src.storage.unit_of_work import UnitOfWork


logger = logging.getLogger(__name__)

ConnectionFactory = Callable[[], sqlite3.Connection]
VerificationClock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MoveVerificationExecutionInvariantError(RuntimeError):
    """접수 후 사라진 target처럼 durable state 계약이 깨진 경우다."""


class MoveVerificationExecutor:
    """대기 중인 MoveVerificationAttempt 하나의 상태를 전진시킨다."""

    def __init__(
        self,
        *,
        connection_factory: ConnectionFactory,
        publication_preparer: BackendPublicationPreparer,
        clock: VerificationClock = _utc_now,
    ) -> None:
        self._connection_factory = connection_factory
        self._publication_preparer = publication_preparer
        self._clock = clock

    def execute_once(self) -> bool:
        """상태를 전진시켰으면 ``True``, 아직 판단 대기 중이면 ``False``다."""

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("MoveVerification clock must return timezone-aware datetime")

        connection = self._connection_factory()
        try:
            with UnitOfWork(connection):
                attempts = MoveVerificationAttemptRepository(
                    connection
                ).list_non_terminal()
                for attempt in attempts:
                    if attempt.state is MoveVerificationState.ACCEPTED:
                        self._mark_checking(
                            attempt,
                            now=now,
                            connection=connection,
                        )
                        return True
                    if self._try_complete(
                        attempt,
                        now=now,
                        connection=connection,
                    ):
                        return True
                return False
        finally:
            connection.close()

    def _mark_checking(
        self,
        attempt: MoveVerificationAttempt,
        *,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> None:
        checking = replace(
            attempt,
            state=MoveVerificationState.CHECKING,
            record_version=attempt.record_version + 1,
            updated_at=now,
        )
        MoveVerificationAttemptRepository(connection).save(
            checking,
            expected_record_version=attempt.record_version,
        )

    def _try_complete(
        self,
        attempt: MoveVerificationAttempt,
        *,
        now: datetime,
        connection: sqlite3.Connection,
    ) -> bool:
        incident_repository = IncidentRepository(connection)
        incident_results = tuple(
            _incident_result(
                _require_incident(
                    incident_repository,
                    incident_id,
                    attempt=attempt,
                ),
                observed_not_before=attempt.accepted_at,
            )
            for incident_id in attempt.target_incident_ids
        )
        has_unknown = any(
            item.result is MoveVerificationResult.UNKNOWN
            for item in incident_results
        )
        if (
            has_unknown
            and attempt.deadline_at is not None
            and now < attempt.deadline_at
        ):
            return False

        overall_result = _overall_result(incident_results)
        completed = replace(
            attempt,
            state=MoveVerificationState.COMPLETED,
            result=overall_result,
            incident_results=incident_results,
            publication_revision=1,
            completed_at=now,
            updated_at=now,
            record_version=attempt.record_version + 1,
        )
        MoveVerificationAttemptRepository(connection).save(
            completed,
            expected_record_version=attempt.record_version,
        )
        SQLiteOutboxWriter(connection).enqueue(
            self._publication_preparer.prepare_move_verification_result(
                completed
            ),
            created_at_us=datetime_to_epoch_microseconds(now),
        )
        return True


class MoveVerificationExecutorWorker:
    """MoveVerificationExecutor를 process-local background thread에서 실행한다."""

    def __init__(
        self,
        executor: MoveVerificationExecutor,
        *,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self._executor = executor
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
            raise RuntimeError("MoveVerification worker may only be started once")
        thread = Thread(
            target=self._run,
            name="jetson-move-verification",
            daemon=False,
        )
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join()

    def _run(self) -> None:
        try:
            while not self._stop_requested.is_set():
                progressed = self._executor.execute_once()
                if not progressed:
                    self._stop_requested.wait(self._poll_interval_seconds)
        except Exception as error:
            self._failure = error
            logger.exception("Jetson MoveVerification worker가 종료됐습니다.")


def _require_incident(
    repository: IncidentRepository,
    incident_id: IncidentId,
    *,
    attempt: MoveVerificationAttempt,
) -> Incident:
    incident = repository.get(incident_id)
    if incident is None:
        raise MoveVerificationExecutionInvariantError(
            "접수된 MoveVerification target Incident가 사라졌습니다: "
            f"{attempt.request_id}:{attempt.verification_attempt}/{incident_id}"
        )
    if incident.physical_vehicle_id != attempt.subject_physical_vehicle_id:
        raise MoveVerificationExecutionInvariantError(
            "MoveVerification target Incident의 subject가 변경됐습니다: "
            f"{incident_id}"
        )
    if incident.publication_revision < 1:
        raise MoveVerificationExecutionInvariantError(
            f"공개되지 않은 Incident는 재확인할 수 없습니다: {incident_id}"
        )
    return incident


def _incident_result(
    incident: Incident,
    *,
    observed_not_before: datetime,
) -> MoveVerificationIncidentResult:
    if incident.state is IncidentState.RESOLVED:
        result = MoveVerificationResult.RESOLVED
    elif (
        incident.state is IncidentState.OPEN
        and incident.observation.state is ObservationState.OBSERVED
        and incident.observation.last_reliable_observed_at is not None
        and incident.observation.last_reliable_observed_at
        >= observed_not_before
    ):
        result = MoveVerificationResult.STILL_ACTIVE
    elif incident.state in {IncidentState.OPEN, IncidentState.CLEAR_PENDING}:
        result = MoveVerificationResult.UNKNOWN
    else:
        raise MoveVerificationExecutionInvariantError(
            "재확인 대상 Incident가 허용되지 않은 상태입니다: "
            f"{incident.incident_id}/{incident.state.value}"
        )
    return MoveVerificationIncidentResult(
        incident_id=incident.incident_id,
        result=result,
        incident_publication_revision=incident.publication_revision,
    )


def _overall_result(
    incident_results: tuple[MoveVerificationIncidentResult, ...],
) -> MoveVerificationResult:
    results = {item.result for item in incident_results}
    if MoveVerificationResult.STILL_ACTIVE in results:
        return MoveVerificationResult.STILL_ACTIVE
    if MoveVerificationResult.UNKNOWN in results:
        return MoveVerificationResult.UNKNOWN
    return MoveVerificationResult.RESOLVED

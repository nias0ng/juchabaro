"""ToF 권한 재평가 요청을 병합하고 별도 worker thread에서 처리한다.

이 모듈은 sensor transition과 monitoring commit 신호의 병합, shutdown ingress
차단 및 coordinator 실행을 담당한다. 센서 polling, monitoring 처리,
authorization business rule, 액추에이터 제어, Incident·outbox·Backend 연동,
runtime composition과 lifespan 관리는 담당하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import math
from threading import Condition, Event, Lock, Thread, current_thread

from src.application.sensor_occupancy import OccupancyTransition
from src.application.tof_zone_authorization_coordinator import (
    TofAuthorizationCoordinatorRun,
    TofZoneAuthorizationCoordinator,
)
from src.parking.models import ZoneId


logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class _TofAuthorizationRequestBatch:
    """한 번의 coordinator drain으로 처리할 병합 요청."""

    zone_revisions: tuple[tuple[ZoneId, int], ...]
    monitoring_commit_requested: bool


class _TofAuthorizationMailboxWakeReason(str, Enum):
    """Mailbox consumer가 깨어난 원인."""

    REQUEST = "REQUEST"
    TIMEOUT = "TIMEOUT"
    CLOSED = "CLOSED"


@dataclass(frozen=True, kw_only=True)
class _TofAuthorizationMailboxWake:
    """Mailbox 대기의 요청, timeout 및 종료 결과."""

    reason: _TofAuthorizationMailboxWakeReason
    batch: _TofAuthorizationRequestBatch | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.reason,
            _TofAuthorizationMailboxWakeReason,
        ):
            raise ValueError(
                "reason은 _TofAuthorizationMailboxWakeReason이어야 합니다."
            )

        if self.reason is _TofAuthorizationMailboxWakeReason.REQUEST:
            if not isinstance(
                self.batch,
                _TofAuthorizationRequestBatch,
            ):
                raise ValueError(
                    "REQUEST wake에는 request batch가 필요합니다."
                )
            return

        if self.batch is not None:
            raise ValueError(
                "TIMEOUT 또는 CLOSED wake에는 batch가 없어야 합니다."
            )


def _normalize_timeout_seconds(
    timeout_seconds: float | None,
) -> float | None:
    if timeout_seconds is None:
        return None

    if isinstance(timeout_seconds, bool) or not isinstance(
        timeout_seconds,
        (int, float),
    ):
        raise ValueError(
            "timeout_seconds는 None 또는 finite 숫자여야 합니다."
        )

    try:
        normalized = float(timeout_seconds)
    except (OverflowError, ValueError) as error:
        raise ValueError(
            "timeout_seconds는 finite 숫자여야 합니다."
        ) from error

    if not math.isfinite(normalized):
        raise ValueError(
            "timeout_seconds는 finite 숫자여야 합니다."
        )
    if normalized < 0:
        raise ValueError(
            "timeout_seconds는 0 이상이어야 합니다."
        )
    return normalized


class TofAuthorizationRequestMailbox:
    """생산자 callback의 ToF 권한 재평가 요청을 thread-safe하게 병합한다."""

    def __init__(self) -> None:
        self._condition = Condition()
        self._pending_revisions: dict[ZoneId, int] = {}
        self._monitoring_commit_pending = False
        self._closed = False

    def request_transitions(
        self,
        transitions: tuple[OccupancyTransition, ...],
    ) -> None:
        """구역별 최신 occupancy revision만 보존한다."""

        with self._condition:
            # 종료 중 남아 있는 producer callback을 실패시키지 않는다.
            if self._closed:
                return

            if not isinstance(transitions, tuple):
                raise ValueError("transitions는 tuple이어야 합니다.")
            if any(
                not isinstance(transition, OccupancyTransition)
                for transition in transitions
            ):
                raise ValueError(
                    "transitions의 모든 항목은 OccupancyTransition이어야 합니다."
                )

            for transition in transitions:
                current = self._pending_revisions.get(transition.zone_id)
                if current is None or transition.revision > current:
                    self._pending_revisions[transition.zone_id] = (
                        transition.revision
                    )

            if transitions:
                self._condition.notify()

    def request_after_monitoring_commit(self) -> None:
        """전체 OCCUPIED zone 재평가 신호 하나를 pending 상태로 보존한다."""

        with self._condition:
            if self._closed:
                return

            self._monitoring_commit_pending = True
            self._condition.notify()

    def close(self) -> None:
        """신규 ingress를 차단하고 pending 요청을 폐기한 뒤 소비자를 깨운다."""

        with self._condition:
            if self._closed:
                return

            self._closed = True
            self._pending_revisions.clear()
            self._monitoring_commit_pending = False
            self._condition.notify_all()

    def _wait_and_take(
        self,
        timeout_seconds: float | None = None,
    ) -> _TofAuthorizationMailboxWake:
        """다음 batch, timeout 또는 mailbox 종료를 구분해 반환한다."""

        normalized_timeout = _normalize_timeout_seconds(timeout_seconds)
        with self._condition:
            self._condition.wait_for(
                lambda: (
                    self._closed
                    or bool(self._pending_revisions)
                    or self._monitoring_commit_pending
                ),
                timeout=normalized_timeout,
            )

            if self._closed:
                self._pending_revisions.clear()
                self._monitoring_commit_pending = False
                return _TofAuthorizationMailboxWake(
                    reason=_TofAuthorizationMailboxWakeReason.CLOSED,
                )

            if (
                self._pending_revisions
                or self._monitoring_commit_pending
            ):
                batch = _TofAuthorizationRequestBatch(
                    zone_revisions=tuple(
                        sorted(self._pending_revisions.items())
                    ),
                    monitoring_commit_requested=(
                        self._monitoring_commit_pending
                    ),
                )
                self._pending_revisions = {}
                self._monitoring_commit_pending = False
                return _TofAuthorizationMailboxWake(
                    reason=_TofAuthorizationMailboxWakeReason.REQUEST,
                    batch=batch,
                )

            return _TofAuthorizationMailboxWake(
                reason=_TofAuthorizationMailboxWakeReason.TIMEOUT,
            )


class TofAuthorizationWorker:
    """Mailbox 요청을 전용 thread에서 ToF authorization으로 처리한다."""

    def __init__(
        self,
        *,
        coordinator: TofZoneAuthorizationCoordinator,
        mailbox: TofAuthorizationRequestMailbox,
    ) -> None:
        self._coordinator = coordinator
        self._mailbox = mailbox

        self._state_lock = Lock()
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._start_attempted = False
        self._failure: Exception | None = None

    def start(self) -> None:
        """Authorization worker thread를 한 번만 시작한다."""

        with self._state_lock:
            if self._start_attempted:
                raise RuntimeError(
                    "tof authorization worker may only be started once"
                )
            if self._stop_requested.is_set():
                raise RuntimeError(
                    "tof authorization worker is already stopped"
                )

            self._start_attempted = True
            thread = Thread(
                target=self._run,
                name="jetson-tof-authorization",
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception as error:
                self._thread = None
                if self._failure is None:
                    self._failure = error
                self._stop_requested.set()
                self._mailbox.close()
                raise

    def stop(self) -> None:
        """신규 요청을 차단하고 진행 중인 coordinator 호출 완료를 기다린다."""

        self._mailbox.close()
        self._stop_requested.set()

        with self._state_lock:
            thread = self._thread

        if thread is None or current_thread() is thread:
            return

        thread.join()

    @property
    def is_running(self) -> bool:
        """Authorization worker thread가 현재 실행 중인지 반환한다."""

        with self._state_lock:
            thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def failure(self) -> Exception | None:
        """예상하지 못한 terminal exception의 원본을 반환한다."""

        with self._state_lock:
            return self._failure

    def _run(self) -> None:
        try:
            while True:
                wake = self._mailbox._wait_and_take(
                    timeout_seconds=None,
                )
                if (
                    wake.reason
                    is _TofAuthorizationMailboxWakeReason.CLOSED
                ):
                    return

                if (
                    wake.reason
                    is _TofAuthorizationMailboxWakeReason.TIMEOUT
                ):
                    continue

                batch = wake.batch
                if batch is None:
                    raise RuntimeError(
                        "REQUEST mailbox wake에 batch가 없습니다."
                    )
                self._process_batch(batch)
        except Exception as error:
            self._record_failure(error)
            self._stop_requested.set()
            self._mailbox.close()
            logger.exception(
                "Jetson ToF authorization worker가 종료됐습니다."
            )
        finally:
            self._mailbox.close()

    def _process_batch(
        self,
        batch: _TofAuthorizationRequestBatch,
    ) -> None:
        for zone_id, revision in batch.zone_revisions:
            if self._stop_requested.is_set():
                return

            self._coordinator.request_zone(
                zone_id,
                minimum_occupancy_revision=revision,
            )

        if batch.monitoring_commit_requested:
            if self._stop_requested.is_set():
                return
            self._coordinator.request_occupied_zones()

        if self._stop_requested.is_set():
            return

        run = self._coordinator.drain_pending()
        self._log_failures(run)

    def _log_failures(
        self,
        run: TofAuthorizationCoordinatorRun,
    ) -> None:
        for failure in run.failures:
            logger.error(
                "ToF authorization 구역 재평가에 실패했습니다. "
                "zoneId=%d stage=%s errorType=%s error=%s",
                int(failure.zone_id),
                failure.stage.value,
                type(failure.error).__name__,
                failure.error,
            )

    def _record_failure(self, error: Exception) -> None:
        with self._state_lock:
            if self._failure is None:
                self._failure = error

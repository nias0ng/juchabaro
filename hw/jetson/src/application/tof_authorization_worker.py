"""ToF 권한 재평가 요청을 병합하고 별도 worker thread에서 처리한다.

이 모듈은 sensor transition과 monitoring commit 신호의 병합, zone별 자동
재평가 backoff, shutdown ingress 차단 및 coordinator 실행을 담당한다. 센서
polling, monitoring 처리, authorization business rule, 액추에이터 제어,
Incident·outbox·Backend 연동, runtime composition과 lifespan 관리는 담당하지
않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
import logging
import math
from threading import Condition, Event, Lock, Thread, current_thread
from time import monotonic

from src.application.sensor_occupancy import (
    OccupancyState,
    OccupancyTransition,
)
from src.application.tof_zone_authorization import (
    TofAuthorizationDecision,
)
from src.application.tof_zone_authorization_coordinator import (
    TofAuthorizationCoordinatorRun,
    TofZoneAuthorizationCoordinator,
)
from src.parking.models import ZoneId


logger = logging.getLogger(__name__)

MonotonicClock = Callable[[], float]


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


def _finite_policy_number(
    value: object,
    *,
    field_name: str,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}은 finite 숫자여야 합니다.")

    try:
        normalized = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(
            f"{field_name}은 finite 숫자여야 합니다."
        ) from error

    if not math.isfinite(normalized):
        raise ValueError(f"{field_name}은 finite 숫자여야 합니다.")
    return normalized


def _merge_minimum_revision(
    current: int | None,
    incoming: int | None,
) -> int | None:
    if current is None:
        return incoming
    if incoming is None:
        return current
    return max(current, incoming)


@dataclass(frozen=True, kw_only=True)
class TofAuthorizationReevaluationPolicy:
    """OCCUPIED zone 자동 재평가의 잠정 backoff 정책.

    기본값은 production 측정으로 확정된 운영값이 아니며 후속 Settings
    wiring과 현장 검증에서 재조정해야 한다.
    """

    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0
    backoff_multiplier: float = 2.0

    def __post_init__(self) -> None:
        initial = _finite_policy_number(
            self.initial_backoff_seconds,
            field_name="initial_backoff_seconds",
        )
        maximum = _finite_policy_number(
            self.max_backoff_seconds,
            field_name="max_backoff_seconds",
        )
        multiplier = _finite_policy_number(
            self.backoff_multiplier,
            field_name="backoff_multiplier",
        )

        if initial <= 0:
            raise ValueError(
                "initial_backoff_seconds는 0보다 커야 합니다."
            )
        if maximum < initial:
            raise ValueError(
                "max_backoff_seconds는 initial 이상이어야 합니다."
            )
        if multiplier < 1:
            raise ValueError(
                "backoff_multiplier는 1 이상이어야 합니다."
            )

        object.__setattr__(self, "initial_backoff_seconds", initial)
        object.__setattr__(self, "max_backoff_seconds", maximum)
        object.__setattr__(self, "backoff_multiplier", multiplier)


class _ZoneReevaluationKind(str, Enum):
    OCCUPIED_UNRESOLVED = "OCCUPIED_UNRESOLVED"
    OCCUPIED_RESOLVED = "OCCUPIED_RESOLVED"
    COMPLETION_RETRY = "COMPLETION_RETRY"


@dataclass(frozen=True, kw_only=True)
class _ZoneReevaluationState:
    next_due_at: float
    backoff_seconds: float
    minimum_occupancy_revision: int | None
    kind: _ZoneReevaluationKind

    def __post_init__(self) -> None:
        if (
            self.kind is not _ZoneReevaluationKind.COMPLETION_RETRY
            and self.minimum_occupancy_revision is not None
        ):
            raise ValueError(
                "OCCUPIED periodic schedule에는 retry minimum을 "
                "보존할 수 없습니다."
            )


_DEFAULT_REEVALUATION_POLICY = TofAuthorizationReevaluationPolicy()


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
    """Mailbox 요청과 due 재평가를 전용 thread에서 처리한다.

    Snapshot supplier의 정상 sensor read failure는 snapshot 상태로 표현돼야
    한다. supplier 예외나 malformed snapshot은 terminal contract 위반이다.
    """

    def __init__(
        self,
        *,
        coordinator: TofZoneAuthorizationCoordinator,
        mailbox: TofAuthorizationRequestMailbox,
        policy: TofAuthorizationReevaluationPolicy = (
            _DEFAULT_REEVALUATION_POLICY
        ),
        monotonic_clock: MonotonicClock = monotonic,
    ) -> None:
        if not isinstance(policy, TofAuthorizationReevaluationPolicy):
            raise ValueError(
                "policy는 TofAuthorizationReevaluationPolicy여야 합니다."
            )
        if not callable(monotonic_clock):
            raise ValueError("monotonic_clock은 callable이어야 합니다.")

        self._coordinator = coordinator
        self._mailbox = mailbox
        self._policy = policy
        self._monotonic_clock = monotonic_clock
        self._reevaluation_states: dict[
            ZoneId,
            _ZoneReevaluationState,
        ] = {}

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
                    timeout_seconds=self._next_wait_timeout_seconds(),
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
                    self._process_due_reevaluations()
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
        requested_revisions: dict[ZoneId, int | None] = {}

        for zone_id, revision in batch.zone_revisions:
            if self._stop_requested.is_set():
                return

            self._coordinator.request_zone(
                zone_id,
                minimum_occupancy_revision=revision,
            )
            requested_revisions[zone_id] = _merge_minimum_revision(
                requested_revisions.get(zone_id),
                revision,
            )

        if batch.monitoring_commit_requested:
            if self._stop_requested.is_set():
                return
            self._coordinator.request_occupied_zones()

        if self._stop_requested.is_set():
            return

        run = self._coordinator.drain_pending()
        self._log_failures(run)
        self._update_reevaluation_states(
            run,
            requested_revisions=requested_revisions,
        )

    def _monotonic_now(self) -> float:
        value = self._monotonic_clock()
        if isinstance(value, bool) or not isinstance(
            value,
            (int, float),
        ):
            raise ValueError(
                "monotonic_clock은 finite 숫자를 반환해야 합니다."
            )

        try:
            normalized = float(value)
        except (OverflowError, ValueError) as error:
            raise ValueError(
                "monotonic_clock은 finite 숫자를 반환해야 합니다."
            ) from error

        if not math.isfinite(normalized):
            raise ValueError(
                "monotonic_clock은 finite 숫자를 반환해야 합니다."
            )
        return normalized

    def _next_wait_timeout_seconds(self) -> float | None:
        if not self._reevaluation_states:
            return None

        now = self._monotonic_now()
        next_due_at = min(
            state.next_due_at
            for state in self._reevaluation_states.values()
        )
        return max(0.0, next_due_at - now)

    def _process_due_reevaluations(self) -> None:
        if self._stop_requested.is_set():
            return

        snapshot_states = {
            zone_id: (revision, state)
            for zone_id, revision, state
            in self._coordinator.zone_occupancy_revisions()
        }
        now = self._monotonic_now()
        due_states = tuple(
            sorted(
                (
                    (zone_id, schedule)
                    for zone_id, schedule
                    in self._reevaluation_states.items()
                    if schedule.next_due_at <= now
                ),
                key=lambda item: item[0],
            )
        )

        requested_revisions: dict[ZoneId, int | None] = {}
        for zone_id, schedule in due_states:
            current = snapshot_states.get(zone_id)
            if current is None:
                if (
                    schedule.kind
                    is _ZoneReevaluationKind.COMPLETION_RETRY
                ):
                    logger.error(
                        "Completion retry 대상 zone snapshot이 없어 "
                        "미래 deadline으로 재예약합니다. "
                        "zoneId=%d stage=snapshot_lookup",
                        int(zone_id),
                    )
                    self._schedule_without_outcome(
                        zone_id,
                        now=now,
                        minimum_occupancy_revision=(
                            schedule.minimum_occupancy_revision
                        ),
                    )
                else:
                    self._reevaluation_states.pop(zone_id, None)
                continue

            current_revision, current_state = current
            if (
                schedule.kind
                is not _ZoneReevaluationKind.COMPLETION_RETRY
                and current_state is not OccupancyState.OCCUPIED
            ):
                self._reevaluation_states.pop(zone_id, None)
                continue

            if self._stop_requested.is_set():
                return

            minimum_revision = _merge_minimum_revision(
                current_revision,
                schedule.minimum_occupancy_revision,
            )
            self._coordinator.request_zone(
                zone_id,
                minimum_occupancy_revision=minimum_revision,
            )
            requested_revisions[zone_id] = minimum_revision

        if not requested_revisions or self._stop_requested.is_set():
            return

        run = self._coordinator.drain_pending()
        self._log_failures(run)
        self._update_reevaluation_states(
            run,
            requested_revisions=requested_revisions,
        )

    def _update_reevaluation_states(
        self,
        run: TofAuthorizationCoordinatorRun,
        *,
        requested_revisions: dict[ZoneId, int | None],
    ) -> None:
        now = self._monotonic_now()
        retry_by_zone = {
            request.zone_id: request
            for request in run.retry_requests
        }
        published_zone_ids = {
            assessment.zone_id
            for assessment in run.published_assessments
        }
        failure_zone_ids = {
            failure.zone_id
            for failure in run.failures
        }
        deferred_zone_ids = set(run.deferred_zone_ids)
        reported_zone_ids = (
            published_zone_ids
            | set(run.unchanged_zone_ids)
            | failure_zone_ids
            | deferred_zone_ids
            | set(retry_by_zone)
        )
        missing_retry_zone_ids = (
            failure_zone_ids | deferred_zone_ids
        ) - set(retry_by_zone)
        missing_outcome_zone_ids = (
            set(requested_revisions) - reported_zone_ids
        )
        fallback_zone_ids = (
            missing_retry_zone_ids | missing_outcome_zone_ids
        )

        for zone_id in sorted(fallback_zone_ids):
            logger.error(
                "ToF authorization coordinator 결과가 완전하지 않아 "
                "completion retry로 재예약합니다. "
                "zoneId=%d stage=schedule_update",
                int(zone_id),
            )
            self._schedule_without_outcome(
                zone_id,
                now=now,
                minimum_occupancy_revision=(
                    requested_revisions.get(zone_id)
                ),
            )

        for zone_id, retry in sorted(retry_by_zone.items()):
            if zone_id in fallback_zone_ids:
                continue
            self._schedule_completion_retry(
                zone_id,
                now=now,
                minimum_occupancy_revision=(
                    retry.minimum_occupancy_revision
                ),
            )

        successful_zone_ids = (
            published_zone_ids | set(run.unchanged_zone_ids)
        ) - set(retry_by_zone) - fallback_zone_ids
        for zone_id in sorted(successful_zone_ids):
            assessment = self._coordinator.latest_assessment(zone_id)
            if assessment is None:
                logger.error(
                    "성공 outcome의 최신 assessment가 없어 completion "
                    "retry로 재예약합니다. "
                    "zoneId=%d stage=schedule_update",
                    int(zone_id),
                )
                self._schedule_without_outcome(
                    zone_id,
                    now=now,
                    minimum_occupancy_revision=(
                        requested_revisions.get(zone_id)
                    ),
                )
                continue

            if assessment.occupancy_state is not OccupancyState.OCCUPIED:
                self._reevaluation_states.pop(zone_id, None)
                continue

            if assessment.decision is TofAuthorizationDecision.UNKNOWN:
                self._schedule_occupied_unresolved(
                    zone_id,
                    now=now,
                )
                continue

            if assessment.decision in {
                TofAuthorizationDecision.AUTHORIZED,
                TofAuthorizationDecision.UNAUTHORIZED,
            }:
                self._schedule_occupied_resolved(
                    zone_id,
                    now=now,
                )
                continue

            raise RuntimeError(
                "OCCUPIED assessment에 지원하지 않는 decision이 있습니다: "
                f"zone_id={zone_id!r}, decision={assessment.decision!r}"
            )

    def _schedule_completion_retry(
        self,
        zone_id: ZoneId,
        *,
        now: float,
        minimum_occupancy_revision: int | None,
    ) -> None:
        current = self._reevaluation_states.get(zone_id)
        if current is not None and current.kind in {
            _ZoneReevaluationKind.OCCUPIED_UNRESOLVED,
            _ZoneReevaluationKind.COMPLETION_RETRY,
        }:
            backoff = min(
                current.backoff_seconds
                * self._policy.backoff_multiplier,
                self._policy.max_backoff_seconds,
            )
        else:
            backoff = self._policy.initial_backoff_seconds

        effective_minimum = _merge_minimum_revision(
            (
                current.minimum_occupancy_revision
                if current is not None
                and current.kind
                is _ZoneReevaluationKind.COMPLETION_RETRY
                else None
            ),
            minimum_occupancy_revision,
        )
        self._reevaluation_states[zone_id] = _ZoneReevaluationState(
            next_due_at=now + backoff,
            backoff_seconds=backoff,
            minimum_occupancy_revision=effective_minimum,
            kind=_ZoneReevaluationKind.COMPLETION_RETRY,
        )

    def _schedule_occupied_unresolved(
        self,
        zone_id: ZoneId,
        *,
        now: float,
    ) -> None:
        current = self._reevaluation_states.get(zone_id)
        if current is not None and current.kind in {
            _ZoneReevaluationKind.OCCUPIED_UNRESOLVED,
            _ZoneReevaluationKind.COMPLETION_RETRY,
        }:
            backoff = min(
                current.backoff_seconds
                * self._policy.backoff_multiplier,
                self._policy.max_backoff_seconds,
            )
        else:
            backoff = self._policy.initial_backoff_seconds

        self._reevaluation_states[zone_id] = _ZoneReevaluationState(
            next_due_at=now + backoff,
            backoff_seconds=backoff,
            minimum_occupancy_revision=None,
            kind=_ZoneReevaluationKind.OCCUPIED_UNRESOLVED,
        )

    def _schedule_occupied_resolved(
        self,
        zone_id: ZoneId,
        *,
        now: float,
    ) -> None:
        self._reevaluation_states[zone_id] = _ZoneReevaluationState(
            next_due_at=now + self._policy.max_backoff_seconds,
            backoff_seconds=self._policy.max_backoff_seconds,
            minimum_occupancy_revision=None,
            kind=_ZoneReevaluationKind.OCCUPIED_RESOLVED,
        )

    def _schedule_without_outcome(
        self,
        zone_id: ZoneId,
        *,
        now: float,
        minimum_occupancy_revision: int | None,
    ) -> None:
        current = self._reevaluation_states.get(zone_id)
        backoff = (
            self._policy.initial_backoff_seconds
            if current is None
            else current.backoff_seconds
        )
        effective_minimum = _merge_minimum_revision(
            (
                None
                if current is None
                else current.minimum_occupancy_revision
            ),
            minimum_occupancy_revision,
        )
        self._reevaluation_states[zone_id] = _ZoneReevaluationState(
            next_due_at=now + backoff,
            backoff_seconds=backoff,
            minimum_occupancy_revision=effective_minimum,
            kind=_ZoneReevaluationKind.COMPLETION_RETRY,
        )

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

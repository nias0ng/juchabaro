"""ToF authorization mailbox와 worker의 병합·격리·종료 계약을 검증한다."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from threading import (
    Condition,
    Event,
    Lock,
    Thread,
    current_thread,
    get_ident,
)

import pytest

import src.application.tof_authorization_worker as worker_module
from src.application.sensor_occupancy import (
    OccupancyState,
    OccupancyTransition,
)
from src.application.tof_authorization_worker import (
    _TofAuthorizationMailboxWake,
    _TofAuthorizationMailboxWakeReason,
    _TofAuthorizationRequestBatch,
    _ZoneReevaluationKind,
    TofAuthorizationRequestMailbox,
    TofAuthorizationReevaluationPolicy,
    TofAuthorizationWorker,
)
from src.application.tof_zone_authorization import (
    TofAuthorizationDecision,
)
from src.application.tof_zone_authorization_coordinator import (
    TofAuthorizationCoordinatorFailure,
    TofAuthorizationCoordinatorRun,
    TofAuthorizationCoordinatorStage,
    TofAuthorizationRetryRequest,
)
from src.parking.models import ZoneId


NOW = datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
ZONE_1 = ZoneId(1)
ZONE_2 = ZoneId(2)

EMPTY_RUN = TofAuthorizationCoordinatorRun(
    published_assessments=(),
    unchanged_zone_ids=(),
    deferred_zone_ids=(),
    failures=(),
)


def _transition(
    zone_id: ZoneId,
    *,
    revision: int,
) -> OccupancyTransition:
    return OccupancyTransition(
        sensor_id=f"tof-zone-{int(zone_id)}",
        zone_id=zone_id,
        previous_state=OccupancyState.VACANT,
        current_state=OccupancyState.OCCUPIED,
        candidate_started_at=NOW - timedelta(seconds=1),
        confirmed_at=NOW,
        confirming_distance_mm=100.0,
        revision=revision,
    )


def _run_with_failure(
    error: Exception,
) -> TofAuthorizationCoordinatorRun:
    return TofAuthorizationCoordinatorRun(
        published_assessments=(),
        unchanged_zone_ids=(),
        deferred_zone_ids=(),
        failures=(
            TofAuthorizationCoordinatorFailure(
                zone_id=ZONE_1,
                stage=TofAuthorizationCoordinatorStage.EVALUATION,
                error=error,
            ),
        ),
        retry_requests=(
            TofAuthorizationRetryRequest(
                zone_id=ZONE_1,
                minimum_occupancy_revision=1,
            ),
        ),
    )


class _WaitObservedCondition(Condition):
    """Consumer가 Condition wait에 진입한 시점을 테스트에 공개한다."""

    def __init__(self) -> None:
        super().__init__()
        self.wait_entered = Event()

    def wait_for(
        self,
        predicate: Callable[[], bool],
        timeout: float | None = None,
    ) -> bool:
        # Condition lock을 보유한 상태에서 Event를 설정한다. producer는
        # super().wait_for()가 lock을 놓고 대기하기 전까지 진입할 수 없다.
        self.wait_entered.set()
        return super().wait_for(predicate, timeout)


class _ObservedMailbox(TofAuthorizationRequestMailbox):
    """Worker의 대기 및 close 완료 시점을 테스트에 공개한다."""

    def __init__(self) -> None:
        super().__init__()
        self._wait_count_lock = Lock()
        self._wait_count = 0
        self.wait_timeouts: list[float | None] = []
        self.second_wait_entered = Event()
        self.close_completed = Event()

    def _wait_and_take(
        self,
        timeout_seconds: float | None = None,
    ) -> _TofAuthorizationMailboxWake:
        with self._wait_count_lock:
            self._wait_count += 1
            self.wait_timeouts.append(timeout_seconds)
            if self._wait_count == 2:
                self.second_wait_entered.set()
        return super()._wait_and_take(
            timeout_seconds=timeout_seconds,
        )

    def close(self) -> None:
        super().close()
        self.close_completed.set()


class _FakeCoordinator:
    def __init__(
        self,
        *,
        runs: tuple[TofAuthorizationCoordinatorRun, ...] = (),
        drain_error: Exception | None = None,
        drain_gate: Event | None = None,
        current_zone_states: tuple[
            tuple[ZoneId, int, OccupancyState],
            ...,
        ] = (),
    ) -> None:
        self._condition = Condition()
        self._calls: list[tuple[object, ...]] = []
        self._call_threads: list[
            tuple[str, int, str, bool]
        ] = []

        self._runs = list(runs)
        self._drain_error = drain_error
        self._drain_gate = drain_gate
        self._current_zone_states = current_zone_states
        self.drain_raised = Event()
        self.on_request_zone = None

    @property
    def calls(self) -> tuple[tuple[object, ...], ...]:
        with self._condition:
            return tuple(self._calls)

    @property
    def call_threads(
        self,
    ) -> tuple[tuple[str, int, str, bool], ...]:
        with self._condition:
            return tuple(self._call_threads)

    def call_count(self, name: str) -> int:
        with self._condition:
            return sum(call[0] == name for call in self._calls)

    def wait_for_call_count(
        self,
        name: str,
        count: int,
    ) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: sum(
                    call[0] == name for call in self._calls
                )
                >= count,
                timeout=1.0,
            )

    def request_zone(
        self,
        zone_id: ZoneId,
        *,
        minimum_occupancy_revision: int | None = None,
    ) -> None:
        self._record(
            (
                "request_zone",
                zone_id,
                minimum_occupancy_revision,
            )
        )

        callback = self.on_request_zone
        if callback is not None:
            callback()

    def request_occupied_zones(self) -> None:
        self._record(("request_occupied_zones",))

    def zone_occupancy_revisions(
        self,
    ) -> tuple[tuple[ZoneId, int, OccupancyState], ...]:
        self._record(("zone_occupancy_revisions",))
        return self._current_zone_states

    def drain_pending(self) -> TofAuthorizationCoordinatorRun:
        self._record(("drain_pending",))

        if self._drain_gate is not None:
            if not self._drain_gate.wait(timeout=1.0):
                raise AssertionError("drain gate가 해제되지 않았습니다.")

        if self._drain_error is not None:
            self.drain_raised.set()
            raise self._drain_error

        if self._runs:
            return self._runs.pop(0)
        return EMPTY_RUN

    def _record(self, call: tuple[object, ...]) -> None:
        thread = current_thread()
        with self._condition:
            self._calls.append(call)
            self._call_threads.append(
                (
                    str(call[0]),
                    get_ident(),
                    thread.name,
                    thread.daemon,
                )
            )
            self._condition.notify_all()


@dataclass(frozen=True, kw_only=True)
class _AssessmentView:
    zone_id: ZoneId
    occupancy_state: OccupancyState
    decision: TofAuthorizationDecision | None


class _FakeMonotonicClock:
    def __init__(self, now: float = 100.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _ScriptedMailbox(TofAuthorizationRequestMailbox):
    def __init__(
        self,
        *,
        clock: _FakeMonotonicClock,
        wakes: list[_TofAuthorizationMailboxWake],
    ) -> None:
        super().__init__()
        self._clock = clock
        self._wakes = wakes
        self.wait_timeouts: list[float | None] = []
        self.script_completed = Event()

    def _wait_and_take(
        self,
        timeout_seconds: float | None = None,
    ) -> _TofAuthorizationMailboxWake:
        self.wait_timeouts.append(timeout_seconds)
        if not self._wakes:
            raise AssertionError(
                "scripted mailbox wake가 모두 소비됐습니다."
            )

        wake = self._wakes.pop(0)
        if wake.reason is _TofAuthorizationMailboxWakeReason.TIMEOUT:
            if timeout_seconds is None:
                raise AssertionError(
                    "TIMEOUT wake에는 유한한 timeout이 필요합니다."
                )
            self._clock.advance(timeout_seconds)
        elif wake.reason is _TofAuthorizationMailboxWakeReason.CLOSED:
            self.script_completed.set()
        return wake


class _ScheduledFakeCoordinator(_FakeCoordinator):
    def __init__(
        self,
        *,
        runs: tuple[TofAuthorizationCoordinatorRun, ...],
        zone_states: tuple[
            tuple[tuple[ZoneId, int, OccupancyState], ...],
            ...,
        ] = (),
    ) -> None:
        super().__init__(runs=runs)
        self._zone_states = list(zone_states)
        self._latest: dict[ZoneId, _AssessmentView] = {}

    @property
    def zone_requests(self) -> list[tuple[ZoneId, int | None]]:
        return [
            (call[1], call[2])
            for call in self.calls
            if call[0] == "request_zone"
        ]

    def drain_pending(self) -> TofAuthorizationCoordinatorRun:
        run = super().drain_pending()
        for assessment in run.published_assessments:
            self._latest[assessment.zone_id] = assessment
        return run

    def latest_assessment(
        self,
        zone_id: ZoneId,
    ) -> _AssessmentView | None:
        return self._latest.get(zone_id)

    def zone_occupancy_revisions(
        self,
    ) -> tuple[tuple[ZoneId, int, OccupancyState], ...]:
        self._record(("zone_occupancy_revisions",))
        if not self._zone_states:
            raise AssertionError("zone state script가 모두 소비됐습니다.")
        return self._zone_states.pop(0)


_TEST_POLICY = TofAuthorizationReevaluationPolicy(
    initial_backoff_seconds=0.25,
    max_backoff_seconds=1.0,
    backoff_multiplier=2.0,
)


def _request_wake(
    zone_id: ZoneId,
    *,
    revision: int,
) -> _TofAuthorizationMailboxWake:
    return _TofAuthorizationMailboxWake(
        reason=_TofAuthorizationMailboxWakeReason.REQUEST,
        batch=_TofAuthorizationRequestBatch(
            zone_revisions=((zone_id, revision),),
            monitoring_commit_requested=False,
        ),
    )


def _frame_wake(
    *,
    context_changed: bool = False,
) -> _TofAuthorizationMailboxWake:
    return _TofAuthorizationMailboxWake(
        reason=_TofAuthorizationMailboxWakeReason.REQUEST,
        batch=_TofAuthorizationRequestBatch(
            zone_revisions=(),
            monitoring_commit_requested=context_changed,
            monitoring_frame_commit_requested=True,
        ),
    )


def _timeout_wake() -> _TofAuthorizationMailboxWake:
    return _TofAuthorizationMailboxWake(
        reason=_TofAuthorizationMailboxWakeReason.TIMEOUT,
    )


def _closed_wake() -> _TofAuthorizationMailboxWake:
    return _TofAuthorizationMailboxWake(
        reason=_TofAuthorizationMailboxWakeReason.CLOSED,
    )


def _run_with_retry(
    request: TofAuthorizationRetryRequest,
) -> TofAuthorizationCoordinatorRun:
    return TofAuthorizationCoordinatorRun(
        published_assessments=(),
        unchanged_zone_ids=(),
        deferred_zone_ids=(),
        failures=(),
        retry_requests=(request,),
    )


def _run_with_assessment(
    assessment: _AssessmentView,
) -> TofAuthorizationCoordinatorRun:
    return TofAuthorizationCoordinatorRun(
        published_assessments=(assessment,),  # type: ignore[arg-type]
        unchanged_zone_ids=(),
        deferred_zone_ids=(),
        failures=(),
    )


def _run_scripted_worker(
    worker: TofAuthorizationWorker,
    mailbox: _ScriptedMailbox,
) -> None:
    worker.start()
    try:
        assert mailbox.script_completed.wait(timeout=1.0)
    finally:
        worker.stop()

    assert worker.is_running is False
    assert worker.failure is None


def test_mailbox_preserves_maximum_revision_and_merges_monitoring_signal(
) -> None:
    mailbox = TofAuthorizationRequestMailbox()

    assert mailbox.request_transitions(
        (
            _transition(ZONE_2, revision=3),
            _transition(ZONE_1, revision=2),
            _transition(ZONE_2, revision=3),
            _transition(ZONE_2, revision=1),
        )
    ) is None
    assert mailbox.request_after_monitoring_commit() is None
    assert mailbox.request_after_monitoring_commit() is None
    assert mailbox.request_after_monitoring_frame_commit() is None
    assert mailbox.request_after_monitoring_frame_commit(
        context_changed=True,
    ) is None

    wake = mailbox._wait_and_take(timeout_seconds=0)

    assert wake.reason is _TofAuthorizationMailboxWakeReason.REQUEST
    assert wake.batch is not None
    assert wake.batch.zone_revisions == (
        (ZONE_1, 2),
        (ZONE_2, 3),
    )
    assert wake.batch.monitoring_commit_requested is True
    assert wake.batch.monitoring_frame_commit_requested is True


def test_mailbox_zero_timeout_preserves_open_ingress() -> None:
    mailbox = TofAuthorizationRequestMailbox()

    timed_out = mailbox._wait_and_take(timeout_seconds=0)

    assert (
        timed_out.reason
        is _TofAuthorizationMailboxWakeReason.TIMEOUT
    )
    assert timed_out.batch is None

    mailbox.request_transitions((_transition(ZONE_1, revision=2),))
    requested = mailbox._wait_and_take(timeout_seconds=0)

    assert (
        requested.reason
        is _TofAuthorizationMailboxWakeReason.REQUEST
    )
    assert requested.batch == _TofAuthorizationRequestBatch(
        zone_revisions=((ZONE_1, 2),),
        monitoring_commit_requested=False,
    )


@pytest.mark.parametrize(
    ("reason", "batch"),
    (
        (_TofAuthorizationMailboxWakeReason.REQUEST, None),
        (
            _TofAuthorizationMailboxWakeReason.TIMEOUT,
            _TofAuthorizationRequestBatch(
                zone_revisions=(),
                monitoring_commit_requested=True,
            ),
        ),
        (
            _TofAuthorizationMailboxWakeReason.CLOSED,
            _TofAuthorizationRequestBatch(
                zone_revisions=((ZONE_1, 1),),
                monitoring_commit_requested=False,
            ),
        ),
    ),
)
def test_mailbox_wake_rejects_invalid_reason_batch_combination(
    reason: _TofAuthorizationMailboxWakeReason,
    batch: _TofAuthorizationRequestBatch | None,
) -> None:
    with pytest.raises(ValueError):
        _TofAuthorizationMailboxWake(
            reason=reason,
            batch=batch,
        )


def test_mailbox_wake_rejects_invalid_reason() -> None:
    with pytest.raises(ValueError, match="reason"):
        _TofAuthorizationMailboxWake(
            reason="REQUEST",
            batch=_TofAuthorizationRequestBatch(
                zone_revisions=(),
                monitoring_commit_requested=True,
            ),
        )


@pytest.mark.parametrize(
    "timeout_seconds",
    (
        -0.001,
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        "1",
        object(),
    ),
)
def test_mailbox_rejects_invalid_timeout(
    timeout_seconds: object,
) -> None:
    mailbox = TofAuthorizationRequestMailbox()

    with pytest.raises(ValueError, match="timeout_seconds"):
        mailbox._wait_and_take(
            timeout_seconds=timeout_seconds,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("signal_kind", "expected_batch"),
    (
        pytest.param(
            "transition",
            _TofAuthorizationRequestBatch(
                zone_revisions=((ZONE_1, 1),),
                monitoring_commit_requested=False,
            ),
            id="transition",
        ),
        pytest.param(
            "monitoring",
            _TofAuthorizationRequestBatch(
                zone_revisions=(),
                monitoring_commit_requested=True,
            ),
            id="monitoring",
        ),
        pytest.param(
            "monitoring-frame",
            _TofAuthorizationRequestBatch(
                zone_revisions=(),
                monitoring_commit_requested=False,
                monitoring_frame_commit_requested=True,
            ),
            id="monitoring-frame",
        ),
    ),
)
def test_mailbox_signal_wakes_timed_waiting_consumer(
    signal_kind: str,
    expected_batch: _TofAuthorizationRequestBatch,
) -> None:
    mailbox = TofAuthorizationRequestMailbox()
    observed_condition = _WaitObservedCondition()
    mailbox._condition = observed_condition

    consumer_finished = Event()
    results: list[_TofAuthorizationMailboxWake] = []

    def consume() -> None:
        results.append(
            mailbox._wait_and_take(timeout_seconds=60.0)
        )
        consumer_finished.set()

    consumer = Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert observed_condition.wait_entered.wait(timeout=1.0)

        if signal_kind == "transition":
            mailbox.request_transitions(
                (_transition(ZONE_1, revision=1),)
            )
        elif signal_kind == "monitoring-frame":
            mailbox.request_after_monitoring_frame_commit()
        else:
            mailbox.request_after_monitoring_commit()

        assert consumer_finished.wait(timeout=1.0)
    finally:
        mailbox.close()
        consumer.join(timeout=1.0)

    assert consumer.is_alive() is False
    assert len(results) == 1
    assert (
        results[0].reason
        is _TofAuthorizationMailboxWakeReason.REQUEST
    )
    assert results[0].batch == expected_batch


def test_mailbox_rejects_invalid_input_while_open() -> None:
    mailbox = TofAuthorizationRequestMailbox()

    with pytest.raises(ValueError, match="tuple"):
        mailbox.request_transitions([])

    with pytest.raises(
        ValueError,
        match="모든 항목은 OccupancyTransition",
    ):
        mailbox.request_transitions((object(),))


def test_mailbox_close_wakes_waiting_consumer() -> None:
    mailbox = TofAuthorizationRequestMailbox()
    consumer_started = Event()
    consumer_finished = Event()
    results: list[_TofAuthorizationMailboxWake] = []

    def consume() -> None:
        consumer_started.set()
        results.append(
            mailbox._wait_and_take(timeout_seconds=60.0)
        )
        consumer_finished.set()

    consumer = Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert consumer_started.wait(timeout=1.0)
        mailbox.close()
        assert consumer_finished.wait(timeout=1.0)
    finally:
        mailbox.close()
        consumer.join(timeout=1.0)

    assert consumer.is_alive() is False
    assert len(results) == 1
    assert (
        results[0].reason
        is _TofAuthorizationMailboxWakeReason.CLOSED
    )
    assert results[0].batch is None


def test_mailbox_close_discards_pending_and_is_idempotent() -> None:
    mailbox = TofAuthorizationRequestMailbox()
    mailbox.request_transitions((_transition(ZONE_1, revision=1),))
    mailbox.request_after_monitoring_commit()
    mailbox.request_after_monitoring_frame_commit()

    mailbox.close()
    mailbox.close()

    wake = mailbox._wait_and_take(timeout_seconds=0)

    assert wake.reason is _TofAuthorizationMailboxWakeReason.CLOSED
    assert wake.batch is None


def test_mailbox_requests_are_noop_after_close_before_validation() -> None:
    mailbox = TofAuthorizationRequestMailbox()
    mailbox.close()

    assert mailbox.request_transitions([]) is None
    assert mailbox.request_transitions((object(),)) is None
    assert mailbox.request_after_monitoring_commit() is None
    assert mailbox.request_after_monitoring_frame_commit() is None
    wake = mailbox._wait_and_take(timeout_seconds=0)
    assert wake.reason is _TofAuthorizationMailboxWakeReason.CLOSED
    assert wake.batch is None


@pytest.mark.parametrize(
    "updates",
    (
        {"initial_backoff_seconds": True},
        {"initial_backoff_seconds": 0},
        {"initial_backoff_seconds": float("nan")},
        {"max_backoff_seconds": 0.1},
        {"max_backoff_seconds": float("inf")},
        {"backoff_multiplier": 0.99},
        {"backoff_multiplier": "2"},
    ),
)
def test_reevaluation_policy_rejects_invalid_values(
    updates: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "initial_backoff_seconds": 0.25,
        "max_backoff_seconds": 2.0,
        "backoff_multiplier": 2.0,
    }
    values.update(updates)

    with pytest.raises(ValueError):
        TofAuthorizationReevaluationPolicy(
            **values,  # type: ignore[arg-type]
        )


def test_reevaluation_policy_normalizes_integer_values() -> None:
    policy = TofAuthorizationReevaluationPolicy(
        initial_backoff_seconds=1,
        max_backoff_seconds=2,
        backoff_multiplier=1,
    )

    assert policy.initial_backoff_seconds == 1.0
    assert policy.max_backoff_seconds == 2.0
    assert policy.backoff_multiplier == 1.0


def test_vacant_failure_uses_completion_retry_until_success() -> None:
    clock = _FakeMonotonicClock()
    retry = TofAuthorizationRetryRequest(
        zone_id=ZONE_1,
        minimum_occupancy_revision=2,
    )
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=TofAuthorizationDecision.UNAUTHORIZED,
                )
            ),
            _run_with_retry(retry),
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.VACANT,
                    decision=None,
                )
            ),
        ),
        zone_states=(
            ((ZONE_1, 2, OccupancyState.VACANT),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=1),
            _request_wake(ZONE_1, revision=2),
            _timeout_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.zone_requests == [
        (ZONE_1, 1),
        (ZONE_1, 2),
        (ZONE_1, 2),
    ]
    assert coordinator.call_count("drain_pending") == 3
    assert mailbox.wait_timeouts == [None, 1.0, 0.25, None]
    assert ZONE_1 not in worker._reevaluation_states


def test_periodic_schedule_is_removed_when_zone_becomes_vacant() -> None:
    clock = _FakeMonotonicClock()
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=TofAuthorizationDecision.AUTHORIZED,
                )
            ),
        ),
        zone_states=(
            ((ZONE_1, 2, OccupancyState.VACANT),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=1),
            _timeout_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.zone_requests == [(ZONE_1, 1)]
    assert coordinator.call_count("drain_pending") == 1
    assert mailbox.wait_timeouts == [None, 1.0, None]
    assert ZONE_1 not in worker._reevaluation_states


def test_completion_retry_preserves_minimum_until_vacant_catches_up(
) -> None:
    clock = _FakeMonotonicClock()
    retry = TofAuthorizationRetryRequest(
        zone_id=ZONE_1,
        minimum_occupancy_revision=5,
    )
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_retry(retry),
            _run_with_retry(retry),
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.VACANT,
                    decision=None,
                )
            ),
        ),
        zone_states=(
            ((ZONE_1, 4, OccupancyState.VACANT),),
            ((ZONE_1, 5, OccupancyState.VACANT),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=5),
            _timeout_wake(),
            _timeout_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.zone_requests == [
        (ZONE_1, 5),
        (ZONE_1, 5),
        (ZONE_1, 5),
    ]
    assert mailbox.wait_timeouts == [None, 0.25, 0.5, None]


@pytest.mark.parametrize(
    ("decision", "expected_kind", "expected_timeout"),
    (
        (
            TofAuthorizationDecision.UNKNOWN,
            _ZoneReevaluationKind.OCCUPIED_UNRESOLVED,
            0.5,
        ),
        (
            TofAuthorizationDecision.AUTHORIZED,
            _ZoneReevaluationKind.OCCUPIED_RESOLVED,
            1.0,
        ),
        (
            TofAuthorizationDecision.UNAUTHORIZED,
            _ZoneReevaluationKind.OCCUPIED_RESOLVED,
            1.0,
        ),
    ),
)
def test_completion_retry_success_transitions_to_periodic_schedule(
    decision: TofAuthorizationDecision,
    expected_kind: _ZoneReevaluationKind,
    expected_timeout: float,
) -> None:
    clock = _FakeMonotonicClock()
    retry = TofAuthorizationRetryRequest(
        zone_id=ZONE_1,
        minimum_occupancy_revision=1,
    )
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_retry(retry),
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=decision,
                )
            ),
        ),
        zone_states=(
            ((ZONE_1, 1, OccupancyState.OCCUPIED),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=1),
            _timeout_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    state = worker._reevaluation_states[ZONE_1]
    assert state.kind is expected_kind
    assert state.minimum_occupancy_revision is None
    assert mailbox.wait_timeouts == [None, 0.25, expected_timeout]


def test_missing_due_outcome_preserves_resolved_backoff() -> None:
    clock = _FakeMonotonicClock()
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=TofAuthorizationDecision.AUTHORIZED,
                )
            ),
            EMPTY_RUN,
        ),
        zone_states=(
            ((ZONE_1, 1, OccupancyState.OCCUPIED),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=1),
            _timeout_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert mailbox.wait_timeouts == [None, 1.0, 1.0]
    assert (
        worker._reevaluation_states[ZONE_1].kind
        is _ZoneReevaluationKind.COMPLETION_RETRY
    )


def test_completion_retry_backoff_is_capped() -> None:
    clock = _FakeMonotonicClock()
    retry = TofAuthorizationRetryRequest(
        zone_id=ZONE_1,
        minimum_occupancy_revision=1,
    )
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_retry(retry),
            _run_with_retry(retry),
            _run_with_retry(retry),
            _run_with_retry(retry),
        ),
        zone_states=(
            ((ZONE_1, 1, OccupancyState.OCCUPIED),),
            ((ZONE_1, 1, OccupancyState.OCCUPIED),),
            ((ZONE_1, 1, OccupancyState.OCCUPIED),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=1),
            _timeout_wake(),
            _timeout_wake(),
            _timeout_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert mailbox.wait_timeouts == [None, 0.25, 0.5, 1.0, 1.0]
    assert coordinator.call_count("drain_pending") == 4


def test_two_due_completion_retries_share_one_drain() -> None:
    clock = _FakeMonotonicClock()
    first_run = TofAuthorizationCoordinatorRun(
        published_assessments=(),
        unchanged_zone_ids=(),
        deferred_zone_ids=(),
        failures=(),
        retry_requests=(
            TofAuthorizationRetryRequest(
                zone_id=ZONE_1,
                minimum_occupancy_revision=1,
            ),
            TofAuthorizationRetryRequest(
                zone_id=ZONE_2,
                minimum_occupancy_revision=2,
            ),
        ),
    )
    coordinator = _ScheduledFakeCoordinator(
        runs=(first_run, EMPTY_RUN),
        zone_states=(
            (
                (ZONE_1, 1, OccupancyState.OCCUPIED),
                (ZONE_2, 2, OccupancyState.VACANT),
            ),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _TofAuthorizationMailboxWake(
                reason=_TofAuthorizationMailboxWakeReason.REQUEST,
                batch=_TofAuthorizationRequestBatch(
                    zone_revisions=(
                        (ZONE_1, 1),
                        (ZONE_2, 2),
                    ),
                    monitoring_commit_requested=False,
                ),
            ),
            _timeout_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.zone_requests == [
        (ZONE_1, 1),
        (ZONE_2, 2),
        (ZONE_1, 1),
        (ZONE_2, 2),
    ]
    assert coordinator.call_count("drain_pending") == 2
    assert mailbox.wait_timeouts == [None, 0.25, 0.25]


def test_unknown_is_reevaluated_once_on_next_frame() -> None:
    clock = _FakeMonotonicClock()
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=TofAuthorizationDecision.UNKNOWN,
                )
            ),
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=TofAuthorizationDecision.UNKNOWN,
                )
            ),
        ),
        zone_states=(
            ((ZONE_1, 1, OccupancyState.OCCUPIED),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=1),
            _frame_wake(),
            _frame_wake(),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.zone_requests == [
        (ZONE_1, 1),
        (ZONE_1, 1),
    ]
    assert coordinator.call_count("zone_occupancy_revisions") == 1
    assert coordinator.call_count("drain_pending") == 2
    assert (
        worker._reevaluation_states[ZONE_1].next_frame_armed
        is False
    )


def test_context_and_frame_commit_share_one_drain_and_arm_next_frame(
) -> None:
    clock = _FakeMonotonicClock()
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=TofAuthorizationDecision.UNKNOWN,
                )
            ),
        ),
        zone_states=(
            ((ZONE_1, 4, OccupancyState.OCCUPIED),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _frame_wake(context_changed=True),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.call_count("request_occupied_zones") == 0
    assert coordinator.call_count("zone_occupancy_revisions") == 1
    assert coordinator.zone_requests == [(ZONE_1, 4)]
    assert coordinator.call_count("drain_pending") == 1
    assert (
        worker._reevaluation_states[ZONE_1].next_frame_armed
        is True
    )


def test_vacant_zone_is_not_evaluated_by_frame_or_context_signal(
) -> None:
    clock = _FakeMonotonicClock()
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_assessment(
                _AssessmentView(
                    zone_id=ZONE_1,
                    occupancy_state=OccupancyState.OCCUPIED,
                    decision=TofAuthorizationDecision.UNKNOWN,
                )
            ),
        ),
        zone_states=(
            ((ZONE_1, 2, OccupancyState.VACANT),),
            ((ZONE_1, 2, OccupancyState.VACANT),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=1),
            _frame_wake(),
            _TofAuthorizationMailboxWake(
                reason=_TofAuthorizationMailboxWakeReason.REQUEST,
                batch=_TofAuthorizationRequestBatch(
                    zone_revisions=(),
                    monitoring_commit_requested=True,
                ),
            ),
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.zone_requests == [(ZONE_1, 1)]
    assert coordinator.call_count("request_occupied_zones") == 0
    assert coordinator.call_count("zone_occupancy_revisions") == 2
    assert coordinator.call_count("drain_pending") == 1
    assert ZONE_1 not in worker._reevaluation_states


@pytest.mark.parametrize(
    "trigger_wake",
    (
        pytest.param(
            _frame_wake(),
            id="monitoring-frame",
        ),
        pytest.param(
            _TofAuthorizationMailboxWake(
                reason=_TofAuthorizationMailboxWakeReason.REQUEST,
                batch=_TofAuthorizationRequestBatch(
                    zone_revisions=(),
                    monitoring_commit_requested=True,
                ),
            ),
            id="monitoring-context",
        ),
    ),
)
def test_early_monitoring_trigger_preserves_completion_minimum_revision(
    trigger_wake: _TofAuthorizationMailboxWake,
) -> None:
    clock = _FakeMonotonicClock()
    retry = TofAuthorizationRetryRequest(
        zone_id=ZONE_1,
        minimum_occupancy_revision=5,
    )
    coordinator = _ScheduledFakeCoordinator(
        runs=(
            _run_with_retry(retry),
            EMPTY_RUN,
        ),
        zone_states=(
            ((ZONE_1, 4, OccupancyState.OCCUPIED),),
        ),
    )
    mailbox = _ScriptedMailbox(
        clock=clock,
        wakes=[
            _request_wake(ZONE_1, revision=5),
            trigger_wake,
            _closed_wake(),
        ],
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=_TEST_POLICY,
        monotonic_clock=clock,
    )

    _run_scripted_worker(worker, mailbox)

    assert coordinator.zone_requests == [
        (ZONE_1, 5),
        (ZONE_1, 5),
    ]
    assert coordinator.call_count("zone_occupancy_revisions") == 1
    assert coordinator.call_count("request_occupied_zones") == 0
    assert coordinator.call_count("drain_pending") == 2


def test_worker_processes_prestart_combined_batch_on_dedicated_thread(
) -> None:
    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator()
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )
    producer_thread_id = get_ident()

    assert mailbox.request_transitions(
        (
            _transition(ZONE_2, revision=2),
            _transition(ZONE_1, revision=1),
        )
    ) is None
    assert mailbox.request_after_monitoring_commit() is None

    worker.start()
    try:
        assert coordinator.wait_for_call_count("drain_pending", 1)

        assert coordinator.calls == (
            ("zone_occupancy_revisions",),
            ("request_zone", ZONE_1, 1),
            ("request_zone", ZONE_2, 2),
            ("drain_pending",),
        )
        assert coordinator.call_count("request_occupied_zones") == 0
        assert all(
            thread_id != producer_thread_id
            for _name, thread_id, _thread_name, _daemon
            in coordinator.call_threads
        )
        assert {
            thread_name
            for _name, _thread_id, thread_name, _daemon
            in coordinator.call_threads
        } == {"jetson-tof-authorization"}
        assert all(
            daemon is False
            for _name, _thread_id, _thread_name, daemon
            in coordinator.call_threads
        )
        assert worker.is_running is True
    finally:
        worker.stop()

    assert worker.is_running is False
    assert worker.failure is None


def test_blocked_coordinator_does_not_block_producer_and_uses_next_batch(
) -> None:
    drain_gate = Event()
    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator(drain_gate=drain_gate)
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )
    producer: Thread | None = None
    producer_finished = Event()

    mailbox.request_transitions((_transition(ZONE_1, revision=1),))
    worker.start()
    try:
        assert coordinator.wait_for_call_count("drain_pending", 1)

        def produce() -> None:
            mailbox.request_transitions(
                (_transition(ZONE_2, revision=2),)
            )
            mailbox.request_after_monitoring_commit()
            producer_finished.set()

        producer = Thread(target=produce, daemon=True)
        producer.start()

        assert producer_finished.wait(timeout=1.0)
        assert coordinator.call_count("request_zone") == 1
        assert coordinator.call_count("request_occupied_zones") == 0

        drain_gate.set()
        assert coordinator.wait_for_call_count("drain_pending", 2)

        assert ("zone_occupancy_revisions",) in coordinator.calls
        assert ("request_zone", ZONE_2, 2) in coordinator.calls
        assert coordinator.call_count("request_occupied_zones") == 0
        assert coordinator.call_count("zone_occupancy_revisions") == 1
        assert coordinator.call_count("drain_pending") == 2
    finally:
        drain_gate.set()
        worker.stop()
        if producer is not None:
            producer.join(timeout=1.0)

    assert producer is not None
    assert producer.is_alive() is False
    assert worker.failure is None


def test_recoverable_failure_is_logged_and_waits_for_external_signal(
    caplog,
) -> None:
    recoverable_error = RuntimeError("database temporarily unavailable")
    mailbox = _ObservedMailbox()
    coordinator = _FakeCoordinator(
        runs=(
            _run_with_failure(recoverable_error),
            EMPTY_RUN,
        ),
        current_zone_states=(
            (ZONE_1, 1, OccupancyState.OCCUPIED),
        ),
    )
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
        policy=TofAuthorizationReevaluationPolicy(
            initial_backoff_seconds=60.0,
            max_backoff_seconds=60.0,
            backoff_multiplier=1.0,
        ),
    )
    mailbox.request_transitions((_transition(ZONE_1, revision=1),))

    with caplog.at_level(
        logging.ERROR,
        logger="src.application.tof_authorization_worker",
    ):
        worker.start()
        try:
            assert mailbox.second_wait_entered.wait(timeout=1.0)
            assert mailbox.wait_timeouts[:2] == [None, 60.0]
            assert coordinator.call_count("drain_pending") == 1
            assert worker.failure is None
            assert worker.is_running is True
            assert "zoneId=1" in caplog.text
            assert "stage=EVALUATION" in caplog.text
            assert "errorType=RuntimeError" in caplog.text
            assert "database temporarily unavailable" in caplog.text

            mailbox.request_after_monitoring_commit()
            assert coordinator.wait_for_call_count("drain_pending", 2)
            assert coordinator.call_count("drain_pending") == 2
            assert coordinator.call_count("request_occupied_zones") == 0
            assert (
                coordinator.call_count("zone_occupancy_revisions")
                == 1
            )
            assert ("request_zone", ZONE_1, 1) in coordinator.calls
        finally:
            worker.stop()

    assert worker.failure is None


def test_terminal_coordinator_exception_is_preserved_and_stops_worker(
    caplog,
) -> None:
    terminal_error = RuntimeError("unexpected coordinator failure")
    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator(drain_error=terminal_error)
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )
    mailbox.request_transitions((_transition(ZONE_1, revision=1),))

    with caplog.at_level(
        logging.ERROR,
        logger="src.application.tof_authorization_worker",
    ):
        worker.start()
        try:
            assert coordinator.drain_raised.wait(timeout=1.0)
        finally:
            worker.stop()

    assert worker.failure is terminal_error
    assert worker.is_running is False
    assert "Jetson ToF authorization worker가 종료됐습니다." in caplog.text

    calls_after_failure = coordinator.calls
    assert mailbox.request_transitions(
        (_transition(ZONE_2, revision=2),)
    ) is None
    assert mailbox.request_after_monitoring_commit() is None
    assert coordinator.calls == calls_after_failure


def test_thread_start_failure_rolls_back_worker_and_mailbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_error = RuntimeError("thread start failed")

    class _StartFailingThread:
        def __init__(self, **_kwargs) -> None:
            pass

        def start(self) -> None:
            raise start_error

    monkeypatch.setattr(worker_module, "Thread", _StartFailingThread)

    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator()
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )

    with pytest.raises(RuntimeError) as exc_info:
        worker.start()

    assert exc_info.value is start_error
    assert worker.failure is start_error
    assert worker.is_running is False

    assert mailbox.request_transitions(
        (_transition(ZONE_1, revision=1),)
    ) is None
    assert mailbox.request_after_monitoring_commit() is None
    wake = mailbox._wait_and_take(timeout_seconds=0)
    assert wake.reason is _TofAuthorizationMailboxWakeReason.CLOSED

    with pytest.raises(RuntimeError, match="only be started once"):
        worker.start()

    assert coordinator.calls == ()


def test_stop_wakes_waiting_worker_and_is_idempotent() -> None:
    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator()
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )

    worker.start()
    try:
        assert worker.is_running is True
    finally:
        worker.stop()

    worker.stop()

    assert worker.is_running is False
    assert worker.failure is None
    assert coordinator.calls == ()

    assert mailbox.request_after_monitoring_commit() is None
    assert coordinator.calls == ()


def test_stop_before_start_closes_ingress_and_prevents_start() -> None:
    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator()
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )

    worker.stop()
    worker.stop()

    assert worker.is_running is False
    assert worker.failure is None
    assert mailbox.request_transitions(
        (_transition(ZONE_1, revision=1),)
    ) is None

    with pytest.raises(RuntimeError, match="already stopped"):
        worker.start()

    assert coordinator.calls == ()


def test_duplicate_start_and_restart_after_stop_are_rejected() -> None:
    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator()
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )

    worker.start()
    try:
        with pytest.raises(RuntimeError, match="only be started once"):
            worker.start()
    finally:
        worker.stop()

    with pytest.raises(RuntimeError, match="only be started once"):
        worker.start()

    assert worker.failure is None


def test_stop_from_worker_thread_does_not_self_join_or_continue_batch(
) -> None:
    mailbox = TofAuthorizationRequestMailbox()
    coordinator = _FakeCoordinator()
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )
    stop_returned = Event()

    def stop_from_worker() -> None:
        worker.stop()
        stop_returned.set()

    coordinator.on_request_zone = stop_from_worker
    mailbox.request_transitions((_transition(ZONE_1, revision=1),))

    worker.start()
    try:
        assert stop_returned.wait(timeout=1.0)
    finally:
        worker.stop()

    assert coordinator.calls == (
        ("request_zone", ZONE_1, 1),
    )
    assert worker.is_running is False
    assert worker.failure is None


def test_external_stop_waits_for_active_coordinator_and_closes_ingress(
) -> None:
    drain_gate = Event()
    mailbox = _ObservedMailbox()
    coordinator = _FakeCoordinator(drain_gate=drain_gate)
    worker = TofAuthorizationWorker(
        coordinator=coordinator,
        mailbox=mailbox,
    )
    mailbox.request_transitions((_transition(ZONE_1, revision=1),))

    stop_returned = Event()
    stopper: Thread | None = None

    worker.start()
    try:
        assert coordinator.wait_for_call_count("drain_pending", 1)

        def stop_worker() -> None:
            worker.stop()
            stop_returned.set()

        stopper = Thread(target=stop_worker, daemon=True)
        stopper.start()

        assert mailbox.close_completed.wait(timeout=1.0)
        assert stop_returned.is_set() is False

        calls_after_close = coordinator.calls
        assert mailbox.request_transitions(
            (_transition(ZONE_2, revision=2),)
        ) is None
        assert mailbox.request_after_monitoring_commit() is None
        assert coordinator.calls == calls_after_close

        drain_gate.set()
        assert stop_returned.wait(timeout=1.0)
    finally:
        drain_gate.set()
        worker.stop()
        if stopper is not None:
            stopper.join(timeout=1.0)

    assert stopper is not None
    assert stopper.is_alive() is False
    assert worker.is_running is False
    assert worker.failure is None

    calls_after_stop = coordinator.calls
    assert mailbox.request_after_monitoring_commit() is None
    assert coordinator.calls == calls_after_stop

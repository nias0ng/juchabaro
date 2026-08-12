"""ToF SensorWorker의 thread 소유권, polling 및 공개 계약 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
import math
from threading import Condition, Event, Thread, get_ident

import pytest

from src.application.sensor_occupancy import (
    OccupancyPolicy,
    OccupancyStateManager,
    SensorZoneBinding,
)
from src.application.sensor_worker import (
    SensorBatchContractError,
    SensorWorker,
    _next_poll_deadline,
)
from src.domain.models import ObservationState
from src.parking.models import ZoneId
from src.sensors.models import (
    TOF_SENSOR_TYPE,
    SensorObservation,
    SensorReadBatch,
    SensorReadFailure,
    SensorReadFailureReason,
)


T0 = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
DISABLED_SENSOR_ID = "tof_disabled_zone"
EV_SENSOR_ID = "tof_ev_charging_zone"


def _manager() -> OccupancyStateManager:
    return OccupancyStateManager(
        bindings=(
            SensorZoneBinding(
                sensor_id=DISABLED_SENSOR_ID,
                zone_id=ZoneId(1),
            ),
            SensorZoneBinding(
                sensor_id=EV_SENSOR_ID,
                zone_id=ZoneId(2),
            ),
        ),
        policy=OccupancyPolicy(
            enter_distance_mm=150.0,
            exit_distance_mm=220.0,
            enter_confirm_seconds=0.0,
            exit_confirm_seconds=0.0,
            trusted_sample_max_gap_seconds=1.0,
            stale_after_seconds=2.0,
        ),
    )


def _observation(
    sensor_id: str,
    distance_mm: float,
    *,
    seconds: float = 0.0,
) -> SensorObservation:
    return SensorObservation(
        sensor_id=sensor_id,
        sensor_type=TOF_SENSOR_TYPE,
        value=distance_mm,
        observed_at=T0 + timedelta(seconds=seconds),
    )


def _failure(
    sensor_id: str,
    *,
    seconds: float = 0.0,
) -> SensorReadFailure:
    return SensorReadFailure(
        sensor_id=sensor_id,
        observed_at=T0 + timedelta(seconds=seconds),
        reason=SensorReadFailureReason.TIMEOUT,
        message="timeout",
    )


def _observed_batch(*, seconds: float = 0.0) -> SensorReadBatch:
    return SensorReadBatch(
        observations=(
            _observation(
                DISABLED_SENSOR_ID,
                100.0,
                seconds=seconds,
            ),
            _observation(
                EV_SENSOR_ID,
                250.0,
                seconds=seconds,
            ),
        ),
        failures=(),
    )


def _all_failure_batch(*, seconds: float = 0.0) -> SensorReadBatch:
    return SensorReadBatch(
        observations=(),
        failures=(
            _failure(DISABLED_SENSOR_ID, seconds=seconds),
            _failure(EV_SENSOR_ID, seconds=seconds),
        ),
    )


class _FakeSensorArray:
    def __init__(
        self,
        outcomes,
        *,
        open_error: Exception | None = None,
        close_error: Exception | None = None,
        block_open: bool = False,
        block_read: bool = False,
        block_close: bool = False,
    ) -> None:
        self._outcomes = tuple(outcomes)
        self.open_error = open_error
        self.close_error = close_error

        self.open_entered = Event()
        self.open_release = Event()
        self.close_entered = Event()
        self.close_release = Event()
        self.closed = Event()
        self.read_release = Event()

        if not block_open:
            self.open_release.set()
        if not block_read:
            self.read_release.set()
        if not block_close:
            self.close_release.set()

        self.open_thread_id: int | None = None
        self.close_thread_id: int | None = None
        self.read_thread_ids: list[int] = []
        self.read_count = 0
        self.returned_count = 0
        self._condition = Condition()

    def open(self) -> None:
        self.open_thread_id = get_ident()
        self.open_entered.set()
        if not self.open_release.wait(timeout=1.0):
            raise RuntimeError("test did not release open")
        if self.open_error is not None:
            raise self.open_error

    def read_all(self):
        with self._condition:
            index = self.read_count
            self.read_count += 1
            self.read_thread_ids.append(get_ident())
            self._condition.notify_all()

        if not self.read_release.wait(timeout=1.0):
            raise RuntimeError("test did not release read")

        if not self._outcomes:
            outcome = SensorReadBatch(observations=(), failures=())
        elif index < len(self._outcomes):
            outcome = self._outcomes[index]
        else:
            outcome = self._outcomes[-1]

        with self._condition:
            self.returned_count += 1
            self._condition.notify_all()

        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def close(self) -> None:
        self.close_thread_id = get_ident()
        self.close_entered.set()
        if not self.close_release.wait(timeout=1.0):
            raise RuntimeError("test did not release close")
        self.closed.set()
        if self.close_error is not None:
            raise self.close_error

    def wait_for_reads(self, expected: int) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: self.read_count >= expected,
                timeout=1.0,
            )

    def wait_for_returns(self, expected: int) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: self.returned_count >= expected,
                timeout=1.0,
            )


def _worker(
    sensor_array,
    *,
    manager=None,
    poll_interval_seconds: float = 60.0,
    transition_consumer=None,
    monotonic_clock=None,
    diagnostic_interval_seconds: float = 5.0,
) -> SensorWorker:
    arguments = {
        "sensor_array": sensor_array,
        "occupancy_manager": manager or _manager(),
        "poll_interval_seconds": poll_interval_seconds,
        "transition_consumer": transition_consumer,
        "diagnostic_interval_seconds": diagnostic_interval_seconds,
    }
    if monotonic_clock is not None:
        arguments["monotonic_clock"] = monotonic_clock
    return SensorWorker(**arguments)


@pytest.mark.parametrize(
    "interval",
    [0.0, -0.1, math.nan, math.inf, -math.inf, True],
)
def test_constructor_rejects_invalid_poll_interval(interval) -> None:
    with pytest.raises(ValueError, match="poll_interval_seconds"):
        _worker(
            _FakeSensorArray((_observed_batch(),)),
            poll_interval_seconds=interval,
        )


def test_constructor_accepts_positive_poll_interval() -> None:
    worker = _worker(
        _FakeSensorArray((_observed_batch(),)),
        poll_interval_seconds=0.5,
    )

    assert worker.snapshots()[0].revision == 0


@pytest.mark.parametrize(
    "interval",
    [0.0, -0.1, math.nan, math.inf, -math.inf, True],
)
def test_constructor_rejects_invalid_diagnostic_interval(interval) -> None:
    with pytest.raises(ValueError, match="diagnostic_interval_seconds"):
        _worker(
            _FakeSensorArray((_observed_batch(),)),
            diagnostic_interval_seconds=interval,
        )


def test_logs_transitions_immediately_and_heartbeat_at_configured_interval(
    caplog: pytest.LogCaptureFixture,
) -> None:
    worker = _worker(
        _FakeSensorArray((_observed_batch(),)),
        diagnostic_interval_seconds=5.0,
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.application.sensor_worker",
    ):
        worker._process_batch(
            _observed_batch(seconds=0.0),
            completed_monotonic=10.0,
        )
        worker._process_batch(
            _observed_batch(seconds=1.0),
            completed_monotonic=11.0,
        )
        worker._process_batch(
            _observed_batch(seconds=5.0),
            completed_monotonic=15.0,
        )

    transition_messages = [
        record.getMessage()
        for record in caplog.records
        if "Jetson ToF occupancy transition." in record.getMessage()
    ]
    heartbeat_messages = [
        record.getMessage()
        for record in caplog.records
        if "Jetson ToF sensor heartbeat." in record.getMessage()
    ]

    assert len(transition_messages) == 2
    assert len(heartbeat_messages) == 4
    assert any(
        "sensorId=tof_disabled_zone" in message
        and "distanceMm=100.0" in message
        for message in heartbeat_messages
    )


def test_constructor_rejects_non_callable_dependencies() -> None:
    array = _FakeSensorArray((_observed_batch(),))

    with pytest.raises(ValueError, match="transition_consumer"):
        _worker(array, transition_consumer=object())
    with pytest.raises(ValueError, match="monotonic_clock"):
        SensorWorker(
            sensor_array=array,
            occupancy_manager=_manager(),
            poll_interval_seconds=1.0,
            monotonic_clock=object(),
        )


class _SnapshotManager:
    def __init__(self, snapshots) -> None:
        self._snapshots = snapshots

    def snapshots(self):
        return self._snapshots


@pytest.mark.parametrize("duplicate_field", ["sensor", "zone"])
def test_constructor_rejects_duplicate_initial_snapshot_identity(
    duplicate_field: str,
) -> None:
    snapshots = _manager().snapshots()
    if duplicate_field == "sensor":
        second = replace(snapshots[1], sensor_id=snapshots[0].sensor_id)
    else:
        second = replace(snapshots[1], zone_id=snapshots[0].zone_id)

    with pytest.raises(ValueError, match=f"{duplicate_field}_id"):
        _worker(
            _FakeSensorArray((_observed_batch(),)),
            manager=_SnapshotManager((snapshots[0], second)),
        )


def test_constructor_rejects_empty_initial_snapshots() -> None:
    with pytest.raises(ValueError, match="하나 이상"):
        _worker(
            _FakeSensorArray((_observed_batch(),)),
            manager=_SnapshotManager(()),
        )


def test_open_read_and_close_run_on_same_dedicated_thread() -> None:
    caller_thread_id = get_ident()
    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array)

    worker.start()
    assert array.wait_for_reads(1)
    worker.stop()

    assert array.closed.is_set()
    assert array.open_thread_id is not None
    assert array.open_thread_id != caller_thread_id
    assert array.read_thread_ids == [array.open_thread_id]
    assert array.close_thread_id == array.open_thread_id
    assert worker.is_running is False
    assert worker.failure is None


def test_start_waits_until_worker_thread_open_completes() -> None:
    array = _FakeSensorArray((_observed_batch(),), block_open=True)
    worker = _worker(array)
    start_finished = Event()

    def start_worker() -> None:
        worker.start()
        start_finished.set()

    thread = Thread(target=start_worker)
    thread.start()
    assert array.open_entered.wait(timeout=1.0)
    assert not start_finished.is_set()

    array.open_release.set()

    assert start_finished.wait(timeout=1.0)
    assert array.wait_for_reads(1)
    worker.stop()
    thread.join()


def test_stop_during_open_skips_first_read_and_waits_for_close() -> None:
    array = _FakeSensorArray(
        (_observed_batch(),),
        block_open=True,
    )
    worker = _worker(array)
    start_finished = Event()
    stop_finished = Event()
    start_errors: list[Exception] = []

    def start_worker() -> None:
        try:
            worker.start()
        except Exception as error:
            start_errors.append(error)
        finally:
            start_finished.set()

    def stop_worker() -> None:
        worker.stop()
        stop_finished.set()

    start_thread = Thread(target=start_worker)
    start_thread.start()
    assert array.open_entered.wait(timeout=1.0)

    stop_thread = Thread(target=stop_worker)
    stop_thread.start()

    # stop 요청이 실제 게시된 뒤 open을 완료시켜야 race 없이
    # "종료 요청 이후 새 read를 시작하지 않는다"는 계약을 검증한다.
    assert worker._stop_requested.wait(timeout=1.0)
    assert not stop_finished.is_set()
    assert not array.close_entered.is_set()
    assert array.read_count == 0

    array.open_release.set()

    assert start_finished.wait(timeout=1.0)
    assert stop_finished.wait(timeout=1.0)
    start_thread.join()
    stop_thread.join()

    assert start_errors == []
    assert array.read_count == 0
    assert array.close_entered.is_set()
    assert array.closed.is_set()
    assert worker.failure is None
    assert worker.is_running is False


def test_open_failure_is_raised_only_after_close_finishes() -> None:
    open_error = RuntimeError("open failed")
    array = _FakeSensorArray(
        (_observed_batch(),),
        open_error=open_error,
        block_close=True,
    )
    worker = _worker(array)
    start_finished = Event()
    caught: list[Exception] = []

    def start_worker() -> None:
        try:
            worker.start()
        except Exception as error:
            caught.append(error)
        finally:
            start_finished.set()

    thread = Thread(target=start_worker)
    thread.start()

    assert array.close_entered.wait(timeout=1.0)
    assert not start_finished.is_set()

    array.close_release.set()

    assert start_finished.wait(timeout=1.0)
    thread.join()
    assert caught == [open_error]
    assert array.closed.is_set()
    assert worker.failure is open_error
    # start()의 예외 반환 시점에는 startup worker가 완전히 종료돼야 한다.
    assert worker.is_running is False


def test_worker_cannot_be_restarted_after_stop() -> None:
    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array)

    worker.start()
    assert array.wait_for_reads(1)
    worker.stop()

    with pytest.raises(RuntimeError, match="only be started once"):
        worker.start()


def test_stop_before_start_is_noop_and_does_not_prevent_start() -> None:
    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array)

    worker.stop()
    worker.start()
    assert array.wait_for_reads(1)
    worker.stop()

    assert array.closed.is_set()


def test_repeated_stop_is_safe() -> None:
    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array)

    worker.start()
    assert array.wait_for_reads(1)
    worker.stop()
    worker.stop()

    assert worker.is_running is False


def test_partial_failure_is_isolated_and_next_batch_is_processed() -> None:
    first = SensorReadBatch(
        observations=(
            _observation(DISABLED_SENSOR_ID, 100.0),
        ),
        failures=(
            _failure(EV_SENSOR_ID),
        ),
    )
    second = _observed_batch(seconds=1.0)
    consumer_calls = []
    second_transition = Event()

    def consume(transitions) -> None:
        consumer_calls.append(transitions)
        if len(consumer_calls) == 2:
            second_transition.set()

    array = _FakeSensorArray((first, second))
    worker = _worker(
        array,
        poll_interval_seconds=0.001,
        transition_consumer=consume,
    )

    worker.start()
    assert second_transition.wait(timeout=1.0)
    worker.stop()

    disabled = worker.snapshot_for_sensor(DISABLED_SENSOR_ID)
    ev = worker.snapshot_for_sensor(EV_SENSOR_ID)
    assert disabled.revision >= 2
    assert disabled.observation.state is ObservationState.OBSERVED
    assert ev.revision >= 2
    assert ev.observation.state is ObservationState.OBSERVED
    assert worker.failure is None


def test_all_failure_batch_does_not_stop_polling() -> None:
    continued = Event()

    def consume(transitions) -> None:
        if transitions:
            continued.set()

    array = _FakeSensorArray(
        (
            _all_failure_batch(),
            _observed_batch(seconds=1.0),
        )
    )
    worker = _worker(
        array,
        poll_interval_seconds=0.001,
        transition_consumer=consume,
    )

    worker.start()
    assert continued.wait(timeout=1.0)
    worker.stop()

    snapshots = worker.snapshots()
    assert array.read_count >= 2
    assert all(snapshot.revision >= 2 for snapshot in snapshots)
    assert all(snapshot.last_failure is not None for snapshot in snapshots)
    assert all(
        snapshot.observation.state is ObservationState.OBSERVED
        for snapshot in snapshots
    )
    assert worker.failure is None


@pytest.mark.parametrize(
    "invalid_batch",
    [
        object(),
        SensorReadBatch(observations=(), failures=()),
        SensorReadBatch(
            observations=(
                _observation(DISABLED_SENSOR_ID, 100.0),
            ),
            failures=(),
        ),
        SensorReadBatch(
            observations=(
                _observation(DISABLED_SENSOR_ID, 100.0),
                _observation(EV_SENSOR_ID, 250.0),
                _observation("unknown", 100.0),
            ),
            failures=(),
        ),
    ],
)
def test_invalid_batch_is_terminal_without_partial_snapshot_publication(
    invalid_batch,
) -> None:
    array = _FakeSensorArray((invalid_batch,))
    worker = _worker(array)
    initial = worker.snapshots()

    worker.start()
    assert array.closed.wait(timeout=1.0)

    assert isinstance(worker.failure, SensorBatchContractError)
    assert worker.snapshots() == initial
    assert all(snapshot.revision == 0 for snapshot in worker.snapshots())
    assert worker.is_running is False


def test_first_read_starts_immediately_after_open() -> None:
    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array, poll_interval_seconds=60.0)

    worker.start()

    assert array.wait_for_reads(1)
    worker.stop()


def test_stop_interrupts_poll_wait_without_starting_another_read() -> None:
    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array, poll_interval_seconds=60.0)
    worker.start()
    assert array.wait_for_returns(1)

    stop_finished = Event()
    stop_thread = Thread(
        target=lambda: (worker.stop(), stop_finished.set())
    )
    stop_thread.start()

    assert stop_finished.wait(timeout=1.0)
    stop_thread.join()
    assert array.read_count == 1
    assert array.closed.is_set()


def test_stop_during_read_waits_and_processes_completed_batch() -> None:
    array = _FakeSensorArray((_observed_batch(),), block_read=True)
    worker = _worker(array)
    worker.start()
    assert array.wait_for_reads(1)

    stop_finished = Event()
    stop_thread = Thread(
        target=lambda: (worker.stop(), stop_finished.set())
    )
    stop_thread.start()

    assert not array.close_entered.is_set()
    assert not stop_finished.is_set()

    array.read_release.set()

    assert stop_finished.wait(timeout=1.0)
    stop_thread.join()
    assert array.closed.is_set()
    assert worker.snapshot_for_sensor(DISABLED_SENSOR_ID).revision == 1
    assert worker.snapshot_for_sensor(EV_SENSOR_ID).revision == 1
    assert array.read_count == 1


def test_overrun_deadline_skips_catch_up_burst() -> None:
    assert _next_poll_deadline(
        previous_deadline=10.0,
        poll_interval_seconds=1.0,
        now=12.5,
    ) == 13.5
    assert _next_poll_deadline(
        previous_deadline=10.0,
        poll_interval_seconds=1.0,
        now=11.0,
    ) == 12.0
    assert _next_poll_deadline(
        previous_deadline=10.0,
        poll_interval_seconds=1.0,
        now=10.5,
    ) == 11.0


def test_read_failure_is_recorded_and_array_is_closed() -> None:
    read_error = RuntimeError("read failed")
    array = _FakeSensorArray((read_error,))
    worker = _worker(array)

    worker.start()
    assert array.closed.wait(timeout=1.0)

    assert worker.failure is read_error
    assert worker.is_running is False


def test_first_loop_failure_wins_over_close_failure() -> None:
    read_error = RuntimeError("read failed")
    close_error = RuntimeError("close failed")
    array = _FakeSensorArray(
        (read_error,),
        close_error=close_error,
    )
    worker = _worker(array)

    worker.start()
    assert array.closed.wait(timeout=1.0)

    assert worker.failure is read_error


def test_close_failure_during_normal_stop_is_recorded() -> None:
    close_error = RuntimeError("close failed")
    array = _FakeSensorArray(
        (_observed_batch(),),
        close_error=close_error,
    )
    worker = _worker(array)

    worker.start()
    assert array.wait_for_returns(1)
    worker.stop()

    assert worker.failure is close_error
    assert worker.is_running is False


def test_transition_consumer_receives_binding_order_after_snapshot_publish() -> None:
    batch = SensorReadBatch(
        observations=(
            _observation(EV_SENSOR_ID, 250.0),
            _observation(DISABLED_SENSOR_ID, 100.0),
        ),
        failures=(),
    )
    calls = []
    called = Event()
    worker: SensorWorker

    def consume(transitions) -> None:
        calls.append(transitions)
        snapshots = worker.snapshots()
        assert all(snapshot.revision == 1 for snapshot in snapshots)
        called.set()

    array = _FakeSensorArray((batch,))
    worker = _worker(array, transition_consumer=consume)

    worker.start()
    assert called.wait(timeout=1.0)
    worker.stop()

    assert [
        transition.sensor_id for transition in calls[0]
    ] == [
        DISABLED_SENSOR_ID,
        EV_SENSOR_ID,
    ]


def test_consumer_is_not_called_without_transition() -> None:
    batch = SensorReadBatch(
        observations=(
            _observation(DISABLED_SENSOR_ID, 180.0),
            _observation(EV_SENSOR_ID, 180.0),
        ),
        failures=(),
    )
    calls = []
    array = _FakeSensorArray((batch,))
    worker = _worker(array, transition_consumer=calls.append)

    worker.start()
    assert array.wait_for_returns(1)
    worker.stop()

    assert calls == []


def test_consumer_error_is_terminal_after_snapshot_publication() -> None:
    consumer_error = RuntimeError("consumer failed")
    callback_snapshot = []

    def consume(transitions) -> None:
        del transitions
        callback_snapshot.extend(worker.snapshots())
        raise consumer_error

    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array, transition_consumer=consume)

    worker.start()
    assert array.closed.wait(timeout=1.0)

    assert worker.failure is consumer_error
    assert all(snapshot.revision == 1 for snapshot in callback_snapshot)
    assert all(snapshot.revision == 1 for snapshot in worker.snapshots())


def test_consumer_can_request_stop_without_self_join() -> None:
    callback_returned = Event()
    worker: SensorWorker

    def consume(transitions) -> None:
        del transitions
        worker.stop()
        callback_returned.set()

    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array, transition_consumer=consume)

    worker.start()

    assert callback_returned.wait(timeout=1.0)
    assert array.closed.wait(timeout=1.0)
    assert worker.failure is None
    assert worker.is_running is False


def test_snapshots_can_be_queried_from_another_thread() -> None:
    published = Event()

    def consume(transitions) -> None:
        del transitions
        published.set()

    array = _FakeSensorArray((_observed_batch(),))
    worker = _worker(array, transition_consumer=consume)
    worker.start()
    assert published.wait(timeout=1.0)

    result = []
    query_finished = Event()

    def query() -> None:
        result.append(
            (
                worker.snapshots(),
                worker.snapshot_for_sensor(DISABLED_SENSOR_ID),
                worker.snapshot_for_zone(ZoneId(1)),
            )
        )
        query_finished.set()

    query_thread = Thread(target=query)
    query_thread.start()
    assert query_finished.wait(timeout=1.0)
    query_thread.join()
    worker.stop()

    snapshots, by_sensor, by_zone = result[0]
    assert [snapshot.sensor_id for snapshot in snapshots] == [
        DISABLED_SENSOR_ID,
        EV_SENSOR_ID,
    ]
    assert by_sensor.revision == by_zone.revision == 1
    assert by_sensor == by_zone


def test_unknown_snapshot_identity_is_rejected_explicitly() -> None:
    worker = _worker(_FakeSensorArray((_observed_batch(),)))

    with pytest.raises(ValueError, match="sensor_id"):
        worker.snapshot_for_sensor("unknown")
    with pytest.raises(ValueError, match="zone_id"):
        worker.snapshot_for_zone(ZoneId(999))

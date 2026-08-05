"""SensorArray polling과 점유 snapshot 공개 생명주기를 관리한다.

하나의 전용 thread가 SensorArray의 open, read_all, close를 모두 소유한다.
점유 상태 계산은 OccupancyStateManager에 위임하고, 다른 thread에는 Manager가
아닌 immutable snapshot cache만 공개한다.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from numbers import Real
from threading import Event, Lock, Thread, current_thread

from src.application.sensor_occupancy import (
    OccupancyStateManager,
    OccupancyTransition,
    ZoneOccupancySnapshot,
)
from src.parking.models import ZoneId
from src.sensors.models import (
    SensorObservation,
    SensorReadBatch,
    SensorReadFailure,
)
from src.sensors.ports import SensorArray


logger = logging.getLogger(__name__)

SensorTransitionConsumer = Callable[
    [tuple[OccupancyTransition, ...]],
    None,
]
MonotonicClock = Callable[[], float]


class SensorBatchContractError(RuntimeError):
    """SensorArray 결과가 Worker의 구성 센서 계약과 일치하지 않는 오류."""


def _positive_finite_number(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name}는 bool이 아닌 유한한 양수여야 합니다.")

    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 양수여야 합니다."
        ) from exc

    if not math.isfinite(normalized) or normalized <= 0:
        raise ValueError(
            f"{field_name}는 bool이 아닌 유한한 양수여야 합니다."
        )
    return normalized


def _next_poll_deadline(
    *,
    previous_deadline: float,
    poll_interval_seconds: float,
    now: float,
) -> float:
    """다음 polling deadline을 계산하되 지난 주기를 따라잡지 않는다."""

    next_deadline = previous_deadline + poll_interval_seconds
    if next_deadline <= now:
        return now + poll_interval_seconds
    return next_deadline


class SensorWorker:
    """SensorArray를 전용 thread에서 polling하고 점유 상태를 공개한다.

    ``start()``는 worker thread의 ``sensor_array.open()`` 결과가 확정될
    때까지 대기한다. open 실패 시 같은 thread의 close 완료와 worker thread
    종료 후 원래 예외를 호출자에게 전달한다.

    외부 조회는 atomic하게 교체되는 immutable snapshot cache만 사용한다.
    Manager와 SensorArray는 worker thread 밖으로 노출하지 않는다.

    terminal worker failure는 마지막으로 공개된 occupancy snapshot을
    변경하지 않는다. 현재 센서 기능의 사용 가능 여부를 판단하는 소비자는
    snapshot과 함께 ``failure`` 및 ``is_running``을 확인해야 한다.
    """

    def __init__(
        self,
        *,
        sensor_array: SensorArray,
        occupancy_manager: OccupancyStateManager,
        poll_interval_seconds: float,
        transition_consumer: SensorTransitionConsumer | None = None,
        monotonic_clock: MonotonicClock = time.monotonic,
    ) -> None:
        normalized_interval = _positive_finite_number(
            poll_interval_seconds,
            field_name="poll_interval_seconds",
        )
        if not callable(monotonic_clock):
            raise ValueError("monotonic_clock은 callable이어야 합니다.")
        if (
            transition_consumer is not None
            and not callable(transition_consumer)
        ):
            raise ValueError(
                "transition_consumer는 None 또는 callable이어야 합니다."
            )

        initial_snapshots = occupancy_manager.snapshots()
        if not initial_snapshots:
            raise ValueError(
                "occupancy_manager는 하나 이상의 초기 snapshot을 가져야 합니다."
            )

        sensor_ids = tuple(
            snapshot.sensor_id for snapshot in initial_snapshots
        )
        zone_ids = tuple(snapshot.zone_id for snapshot in initial_snapshots)
        if len(sensor_ids) != len(set(sensor_ids)):
            raise ValueError(
                "초기 snapshot에 중복된 sensor_id가 있습니다."
            )
        if len(zone_ids) != len(set(zone_ids)):
            raise ValueError(
                "초기 snapshot에 중복된 zone_id가 있습니다."
            )

        self._sensor_array = sensor_array
        self._occupancy_manager = occupancy_manager
        self._poll_interval_seconds = normalized_interval
        self._transition_consumer = transition_consumer
        self._monotonic_clock = monotonic_clock

        self._expected_sensor_order = sensor_ids
        self._expected_sensor_ids = frozenset(sensor_ids)

        self._state_lock = Lock()
        self._snapshots = initial_snapshots
        self._snapshot_by_sensor = {
            snapshot.sensor_id: snapshot
            for snapshot in initial_snapshots
        }
        self._sensor_id_by_zone = {
            snapshot.zone_id: snapshot.sensor_id
            for snapshot in initial_snapshots
        }

        self._stop_requested = Event()
        self._startup_complete = Event()
        self._startup_error: Exception | None = None
        self._failure: Exception | None = None
        self._thread: Thread | None = None
        self._start_attempted = False

    def start(self) -> None:
        """SensorArray open 결과가 확정될 때까지 기다린다."""

        with self._state_lock:
            if self._start_attempted:
                raise RuntimeError(
                    "sensor worker may only be started once"
                )

            self._start_attempted = True
            thread = Thread(
                target=self._run,
                name="jetson-tof-sensor",
                daemon=False,
            )
            self._thread = thread
            try:
                thread.start()
            except Exception as error:
                self._thread = None
                if self._failure is None:
                    self._failure = error
                raise

        self._startup_complete.wait()
        with self._state_lock:
            startup_error = self._startup_error
            thread = self._thread

        if startup_error is not None:
            # close 완료 event와 thread의 _run() 반환은 동일한 사건이 아니므로
            # startup 예외 반환 시점의 완전 종료를 별도로 확정한다.
            if thread is not None:
                thread.join()
            raise startup_error

    def stop(self) -> None:
        """신규 polling을 막고 worker thread의 자원 정리를 기다린다.

        시작 전에 호출하면 아무 상태도 변경하지 않는다. transition consumer가
        worker thread에서 호출해도 self-join하지 않는다.
        """

        with self._state_lock:
            thread = self._thread

        if thread is None:
            return

        self._stop_requested.set()
        if current_thread() is thread:
            return

        thread.join()

    @property
    def is_running(self) -> bool:
        """Worker thread가 현재 실행 중인지 반환한다."""

        with self._state_lock:
            thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def failure(self) -> Exception | None:
        """최초 startup, loop 또는 close 오류를 반환한다.

        terminal 오류는 마지막 공개 snapshot을 synthetic failure 상태로
        변경하지 않는다. 운영 상태 판단에는 ``is_running``도 함께 사용해야
        한다.
        """

        with self._state_lock:
            return self._failure

    def snapshot_for_sensor(
        self,
        sensor_id: str,
    ) -> ZoneOccupancySnapshot:
        """sensor ID에 해당하는 현재 공개 snapshot을 반환한다."""

        with self._state_lock:
            try:
                return self._snapshot_by_sensor[sensor_id]
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"알 수 없는 sensor_id입니다: {sensor_id!r}"
                ) from exc

    def snapshot_for_zone(
        self,
        zone_id: ZoneId,
    ) -> ZoneOccupancySnapshot:
        """zone ID에 해당하는 현재 공개 snapshot을 반환한다."""

        with self._state_lock:
            try:
                sensor_id = self._sensor_id_by_zone[zone_id]
                return self._snapshot_by_sensor[sensor_id]
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"알 수 없는 zone_id입니다: {zone_id!r}"
                ) from exc

    def snapshots(self) -> tuple[ZoneOccupancySnapshot, ...]:
        """Manager binding 순서의 현재 공개 snapshot을 반환한다."""

        with self._state_lock:
            return self._snapshots

    def _run(self) -> None:
        try:
            try:
                self._sensor_array.open()
            except Exception as error:
                with self._state_lock:
                    self._startup_error = error
                self._record_failure(error)
                logger.exception(
                    "Jetson ToF 센서 배열 초기화에 실패했습니다."
                )
                return

            # 이 시점부터 발생하는 첫 read 오류는 background failure다.
            self._startup_complete.set()

            if not self._stop_requested.is_set():
                try:
                    self._poll_loop()
                except Exception as error:
                    self._record_failure(error)
                    logger.exception(
                        "Jetson ToF sensor polling loop가 종료됐습니다."
                    )
        finally:
            try:
                self._sensor_array.close()
            except Exception as error:
                self._record_failure(error)
                logger.exception(
                    "Jetson ToF 센서 배열 정리에 실패했습니다."
                )
            finally:
                # open 실패 시 close 완료 이후에만 start()를 깨운다.
                self._startup_complete.set()

    def _poll_loop(self) -> None:
        next_deadline: float | None = None

        while not self._stop_requested.is_set():
            batch = self._sensor_array.read_all()
            completed_monotonic = self._monotonic_clock()
            self._process_batch(
                batch,
                completed_monotonic=completed_monotonic,
            )

            # 진행 중이던 read의 결과와 transition까지 반영한 뒤 종료한다.
            if self._stop_requested.is_set():
                break

            if next_deadline is None:
                next_deadline = completed_monotonic

            now = self._monotonic_clock()
            next_deadline = _next_poll_deadline(
                previous_deadline=next_deadline,
                poll_interval_seconds=self._poll_interval_seconds,
                now=now,
            )
            timeout = max(0.0, next_deadline - now)
            if self._stop_requested.wait(timeout):
                break

    def _validate_batch(
        self,
        batch: object,
    ) -> SensorReadBatch:
        if not isinstance(batch, SensorReadBatch):
            raise SensorBatchContractError(
                "SensorArray.read_all()은 SensorReadBatch를 반환해야 합니다."
            )

        actual_sensor_ids = {
            observation.sensor_id for observation in batch.observations
        }
        actual_sensor_ids.update(
            failure.sensor_id for failure in batch.failures
        )
        if actual_sensor_ids == self._expected_sensor_ids:
            return batch

        missing = sorted(self._expected_sensor_ids - actual_sensor_ids)
        unexpected = sorted(actual_sensor_ids - self._expected_sensor_ids)
        details: list[str] = []
        if missing:
            details.append(f"누락 sensor ID: {missing!r}")
        if unexpected:
            details.append(f"알 수 없는 sensor ID: {unexpected!r}")

        raise SensorBatchContractError(
            "SensorArray batch가 구성 센서 계약과 일치하지 않습니다: "
            + "; ".join(details)
        )

    def _process_batch(
        self,
        batch: object,
        *,
        completed_monotonic: float,
    ) -> None:
        validated = self._validate_batch(batch)
        observations = {
            observation.sensor_id: observation
            for observation in validated.observations
        }
        failures = {
            failure.sensor_id: failure
            for failure in validated.failures
        }

        transitions: list[OccupancyTransition] = []
        for sensor_id in self._expected_sensor_order:
            observation: SensorObservation | None = observations.get(sensor_id)
            if observation is not None:
                update = self._occupancy_manager.apply_observation(
                    observation,
                    monotonic_now=completed_monotonic,
                )
            else:
                failure: SensorReadFailure = failures[sensor_id]
                update = self._occupancy_manager.apply_failure(
                    failure,
                    monotonic_now=completed_monotonic,
                )

            if update.transition is not None:
                transitions.append(update.transition)

        self._publish_snapshots()

        if transitions and self._transition_consumer is not None:
            # callback은 최신 cache를 조회할 수 있고 lock 밖에서 실행된다.
            self._transition_consumer(tuple(transitions))

    def _publish_snapshots(self) -> None:
        snapshots = self._occupancy_manager.snapshots()
        snapshot_by_sensor = {
            snapshot.sensor_id: snapshot
            for snapshot in snapshots
        }

        with self._state_lock:
            self._snapshots = snapshots
            self._snapshot_by_sensor = snapshot_by_sensor

    def _record_failure(self, error: Exception) -> None:
        with self._state_lock:
            if self._failure is None:
                self._failure = error

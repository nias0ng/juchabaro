"""MonitoringPipeline의 process-local 시작·종료 생명주기를 관리한다.

FastAPI request worker와 camera·model owner를 한 process에서 함께 실행하되,
model owner는 딱 하나의 thread만 가진다. 이 모듈은 pipeline을 조립하거나
실패를 domain 상태로 바꾸지 않고, 자원 생명주기와 운영 진단만 소유한다.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from numbers import Real
from threading import Event, Thread

from src.application.frame_observation_workflow import FrameObservationResult
from src.application.monitoring_pipeline import FrameObserver, MonitoringPipeline
from src.camera.models import CapturedFrame
from src.parking.models import IncidentTransitionType
from src.session.models import EntryMatchState
from src.tracking.models import TrackingBatch


logger = logging.getLogger(__name__)

MonotonicClock = Callable[[], float]


class MonitoringWorker:
    """카메라·model pipeline을 하나의 background thread에서 실행한다.

    ``start()``는 model·camera open이 성공한 후에만 복귀하므로 기동
    실패를 API readiness로 숨기지 않는다. ``stop()``은 새 frame 시작을
    막고 진행 중인 frame의 transaction이 끝난 뒤 자원 정리를 기다린다.

    ``frame_observer``는 worker의 운영 로그 observer와 합성되어 매 frame
    호출된다. 콜백이 예외를 던지면 ``_run()``이 이를 치명 오류로 처리해
    카메라·모델을 닫으므로, 예외 흡수 책임은 콜백 구현체에 있다.
    """

    def __init__(
        self,
        pipeline: MonitoringPipeline,
        *,
        frame_observer: FrameObserver | None = None,
        heartbeat_interval_seconds: float = 10.0,
        monotonic_clock: MonotonicClock = time.monotonic,
    ) -> None:
        if (
            isinstance(heartbeat_interval_seconds, bool)
            or not isinstance(heartbeat_interval_seconds, Real)
            or not math.isfinite(heartbeat_interval_seconds)
            or heartbeat_interval_seconds <= 0
        ):
            raise ValueError(
                "heartbeat_interval_seconds must be a finite positive number"
            )
        if not callable(monotonic_clock):
            raise ValueError("monotonic_clock must be callable")
        self._pipeline = pipeline
        self._frame_observer = frame_observer
        self._heartbeat_interval_seconds = heartbeat_interval_seconds
        self._monotonic_clock = monotonic_clock
        self._last_heartbeat_at: float | None = None
        self._stop_requested = Event()
        self._thread: Thread | None = None
        self._failure: Exception | None = None
        self._prepared = False
        self._pipeline_open = False
        self._closed = False

    @property
    def failure(self) -> Exception | None:
        """Background loop가 예기치 않게 종료된 원인을 반환한다."""

        return self._failure

    @property
    def is_running(self) -> bool:
        """Monitoring loop thread가 현재 실행 중인지 반환한다."""

        return self._thread is not None and self._thread.is_alive()

    def prepare(self) -> None:
        """Durable 복구·camera·model open을 loop 시작과 분리한다.

        Composition root는 이 동기 장벽이 완료된 뒤 publication
        worker를 기동하고, 그 다음 ``start()``로 첫 frame을 허용한다.
        ``start()`` 단독 호출 호환성을 위해 준비되지 않았으면 스스로
        이 단계를 실행한다.
        """

        if self._thread is not None:
            raise RuntimeError("running monitoring worker cannot be prepared")
        if self._closed:
            raise RuntimeError("monitoring worker is already closed")
        if self._prepared:
            return

        self._pipeline.open()
        self._prepared = True
        self._pipeline_open = True
        logger.info("Jetson monitoring pipeline 자원 초기화가 완료됐습니다.")

    def start(self) -> None:
        """준비된 pipeline의 loop thread를 시작한다."""

        if self._thread is not None:
            raise RuntimeError("monitoring worker may only be started once")

        self.prepare()
        thread = Thread(
            target=self._run,
            name="jetson-monitoring",
            daemon=False,
        )
        self._thread = thread
        try:
            thread.start()
        except Exception:
            self._thread = None
            self._close_pipeline()
            raise
        logger.info(
            "Jetson monitoring worker가 시작됐습니다. "
            "heartbeatIntervalSeconds=%.1f",
            self._heartbeat_interval_seconds,
        )

    def stop(self) -> None:
        """신규 frame 처리를 멈추고 worker의 자원 정리까지 기다린다."""

        self._stop_requested.set()
        if self._thread is not None:
            self._thread.join()
        else:
            try:
                self._close_pipeline()
            finally:
                self._closed = True

    def _run(self) -> None:
        try:
            processed_frames = self._pipeline.run(
                frame_observer=self._observe_frame,
                stop_requested=self._stop_requested.is_set,
            )
            logger.info(
                "Jetson monitoring loop가 정상 종료됐습니다. "
                "processedFrames=%d",
                processed_frames,
            )
        except Exception as error:
            self._failure = error
            logger.exception("Jetson monitoring loop가 종료됐습니다.")
        finally:
            try:
                self._close_pipeline()
            except Exception as error:
                if self._failure is None:
                    self._failure = error
                logger.exception("Jetson monitoring 자원 정리에 실패했습니다.")

    def _close_pipeline(self) -> None:
        """prepare만 완료된 startup 실패에서도 자원을 한 번만 닫는다."""

        if not self._pipeline_open:
            return
        try:
            self._pipeline.close()
        finally:
            self._pipeline_open = False
            self._prepared = False
            self._closed = True

    def _observe_frame(
        self,
        frame: CapturedFrame,
        batch: TrackingBatch,
        result: FrameObservationResult,
    ) -> None:
        """commit된 상태 전이와 제한된 주기의 frame heartbeat를 기록한다."""

        for attempt in result.entry_match_updates:
            log_level = (
                logging.INFO
                if attempt.match_state is EntryMatchState.MATCHED
                else logging.WARNING
            )
            logger.log(
                log_level,
                "입차 차량 매치 결과가 확정됐습니다. "
                "entryAttemptId=%s decisionState=%s matchState=%s "
                "physicalVehicleId=%s terminalReason=%s",
                attempt.entry_attempt_id,
                attempt.decision_state.value,
                attempt.match_state.value,
                attempt.matched_physical_vehicle_id,
                attempt.terminal_reason or "-",
            )

        for transition in result.parking_result.parking_transitions:
            logger.info(
                "주차 상태 전이가 확정됐습니다. "
                "transitionType=%s parkingEpisodeId=%s "
                "physicalVehicleId=%s zoneId=%s revision=%d",
                transition.transition_type.value,
                transition.parking_episode_id,
                transition.physical_vehicle_id,
                transition.assignment.zone_id,
                transition.publication_revision,
            )

        for transition in result.parking_result.incident_transitions:
            incident = transition.incident
            log_level = (
                logging.WARNING
                if transition.transition_type is IncidentTransitionType.OPEN
                else logging.INFO
            )
            logger.log(
                log_level,
                "주차 Incident 상태 전이가 확정됐습니다. "
                "transitionType=%s ruleCode=%s incidentId=%s "
                "physicalVehicleId=%s zoneId=%s revision=%d",
                transition.transition_type.value,
                incident.key.rule_code,
                incident.incident_id,
                incident.physical_vehicle_id,
                incident.zone_id,
                incident.publication_revision,
            )

        for physical_vehicle_id in result.retired_physical_vehicle_ids:
            logger.info(
                "차량 출차 처리가 확정됐습니다. physicalVehicleId=%s",
                physical_vehicle_id,
            )

        if self._frame_observer is not None:
            self._frame_observer(frame, batch, result)

        now = self._monotonic_clock()
        if (
            self._last_heartbeat_at is not None
            and now - self._last_heartbeat_at
            < self._heartbeat_interval_seconds
        ):
            return
        self._last_heartbeat_at = now
        detection_count = (
            batch.detection_count
            if batch.detection_count is not None
            else "unknown"
        )
        logger.info(
            "Jetson monitoring heartbeat. "
            "cameraId=%s frameId=%d detections=%s trackedVehicles=%d "
            "observation=%s allDetectionsTracked=%s "
            "allIdentitiesResolved=%s",
            batch.camera_id,
            batch.frame_id,
            detection_count,
            len(batch.vehicles),
            batch.observation.state.value,
            batch.all_detections_tracked,
            batch.all_identities_resolved,
        )

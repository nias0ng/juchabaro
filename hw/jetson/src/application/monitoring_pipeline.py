"""카메라·추적·durable frame workflow를 조립하는 실행 파이프라인.

실행 순서와 오류 경계만 관리하며 bbox 기하 계산이나
위반 조건 판단은 각 domain 계층에 맡긴다.

`TrackingPipeline`은 임시 TrackSegment와 PhysicalVehicle 관측 신호만
만든다. ``FrameObservationWorkflow``가 SessionContext 매칭, parking
aggregate, physical departure, outbox를 하나의 SQLite UnitOfWork로
commit한다. 같은 frame의 Evidence adapter는 commit 직후 호출하며, 정상
경로에서는 READY/FAILED 종결 뒤에만 tracker retire·actuator
projection·observer를 실행한다. local storage 장애는 adapter가 명시적인
재조정 대상으로 보존한다.

프레임 캡처나 추론이 실패하면 부재 누적 연속성을 먼저 끊고
원래 예외를 전파한다. 그렇지 않으면 다음 정상 frame이 장애 구간의
wall-clock을 NOT_PRESENT 확정 시간에 포함한다. `EndOfVideo`는 리플레이
정상 종료이므로 `run()`에서만 조용히 멈춘다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import logging
import sqlite3
from time import perf_counter

from src.actuators.ports import ActuatorCommandPlanner, ActuatorPort
from src.application.frame_observation_workflow import (
    FrameObservationResult,
    FrameObservationWorkflow,
)
from src.camera.frame_source import EndOfVideo, FrameSource, FrameSourceError
from src.camera.models import CapturedFrame
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.evidence.capture_models import EvidenceCaptureSink
from src.parking.models import Incident
from src.tracking.models import TrackingBatch
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import TrackingError

FrameObserver = Callable[[CapturedFrame, TrackingBatch, FrameObservationResult], None]
LOGGER = logging.getLogger(__name__)


class MonitoringPipeline:
    """camera → tracking → local Unit of Work를 조립한다."""

    def __init__(
        self,
        *,
        frame_source: FrameSource,
        tracking_pipeline: TrackingPipeline,
        frame_workflow: FrameObservationWorkflow,
        connection_factory: Callable[[], sqlite3.Connection],
        calibration_reference: str,
        actuator_command_planner: ActuatorCommandPlanner | None = None,
        actuator_port: ActuatorPort | None = None,
        evidence_capture_sink: EvidenceCaptureSink | None = None,
        warm_up_on_open: bool = False,
    ) -> None:
        if not calibration_reference:
            raise ValueError("calibration_reference must not be empty")
        if (actuator_command_planner is None) != (actuator_port is None):
            raise ValueError(
                "actuator_command_planner and actuator_port must be provided together"
            )
        if not isinstance(warm_up_on_open, bool):
            raise TypeError("warm_up_on_open must be bool")
        self._frame_source = frame_source
        self._tracking_pipeline = tracking_pipeline
        self._frame_workflow = frame_workflow
        self._connection_factory = connection_factory
        self._calibration_reference = calibration_reference
        self._actuator_command_planner = actuator_command_planner
        self._actuator_port = actuator_port
        self._evidence_capture_sink = evidence_capture_sink
        self._warm_up_on_open = warm_up_on_open

    @property
    def has_evidence_capture_sink(self) -> bool:
        """Composition root가 evidence 배선 중복을 피할 수 있게 한다."""

        return self._evidence_capture_sink is not None

    def bind_evidence_capture_sink(self, sink: EvidenceCaptureSink) -> None:
        """Pipeline 기동 전에 process-local capture adapter를 한 번 결속한다."""

        if self._evidence_capture_sink is not None:
            raise RuntimeError("evidence capture sink is already configured")
        self._evidence_capture_sink = sink

    def open(self) -> None:
        """durable runtime을 복원하고 운영 자원과 선택적 warm-up을 완료한다."""

        connection = self._connection_factory()
        try:
            recovery = self._frame_workflow.recover_runtime(
                connection=connection
            )
        finally:
            connection.close()
        self._tracking_pipeline.restore_active_checkpoints(
            recovery.active_physical_vehicles
        )
        self._apply_actuator_projection(
            recovery.active_incidents,
            requested_at=datetime.now(timezone.utc),
        )
        try:
            self._frame_source.open()
        except FrameSourceError as error:
            self._commit_interruption(
                observed_at=error.observed_at,
                observation=error.observation,
            )
            self._frame_source.close()
            raise
        try:
            self._tracking_pipeline.open()
            if self._warm_up_on_open:
                self._warm_up_runtime()
        except FrameSourceError as error:
            self._commit_interruption(
                observed_at=error.observed_at,
                observation=error.observation,
            )
            self._close_startup_resources_best_effort()
            raise
        except TrackingError:
            self._commit_interruption(
                observed_at=datetime.now(timezone.utc),
                observation=ObservationStatus(
                    state=ObservationState.UNKNOWN,
                    reason=ObservationReason.PIPELINE_STALLED,
                ),
            )
            self._close_startup_resources_best_effort()
            raise
        except Exception:
            # frame source를 먼저 연 뒤 model load·warm-up이 실패해도
            # 자원을 남기지 않고 원래 기동 예외를 유지한다.
            self._close_startup_resources_best_effort()
            raise

    def _warm_up_runtime(self) -> None:
        """실제 frame을 한 장 소비해 camera/remap과 detector를 준비한다.

        warm-up frame은 tracking resolver나 durable workflow에 전달하지 않는다.
        따라서 frame ID 하나만 소비하며 차량 ID·부재·주차 상태에는 관여하지 않는다.
        """

        started_at = perf_counter()
        frame = self._frame_source.capture()
        self._tracking_pipeline.warm_up(frame)
        LOGGER.info(
            "Jetson monitoring pipeline warm-up이 완료됐습니다. "
            "frameId=%s frame=%sx%s elapsedMs=%.1f",
            frame.frame_id,
            frame.width,
            frame.height,
            (perf_counter() - started_at) * 1000.0,
        )

    def _close_startup_resources_best_effort(self) -> None:
        """startup 원인 예외를 보존하면서 부분 초기화 자원을 역순으로 닫는다."""

        for name, resource in (
            ("tracking pipeline", self._tracking_pipeline),
            ("frame source", self._frame_source),
        ):
            try:
                resource.close()
            except Exception:
                LOGGER.exception("Startup 실패 후 %s 정리에 실패했습니다.", name)

    def process_next_frame(
        self, *, frame_observer: FrameObserver | None = None
    ) -> FrameObservationResult:
        """프레임 한 장을 캡처·추적하고 durable commit 결과를 반환한다.

        프레임 소진 시 `EndOfVideo`가, 그 외 캡처·추적 실패 시 각 계층의
        오류(`FrameSourceError`/`TrackingError`)가 그대로 전파된다 — 호출부가
        판단할 문제다.

        `frame_observer`는 commit과 Evidence capture 시도, process-local
        projection 뒤에만 `(frame, tracking_batch, result)`로 호출되는 선택적
        telemetry·overlay 훅이다(`result_consumer`와 같은 정책 — 예외를 숨기지
        않고, durable 저장 책임을 갖지 않는다).
        `_commit_interruption` 경로(카메라·추적 장애)는 신뢰할 수 있는
        frame/tracking_batch가 없으므로 호출하지 않는다.
        """

        capture_started_at = perf_counter()
        try:
            frame = self._frame_source.capture()
        except EndOfVideo:
            raise
        except FrameSourceError as error:
            self._commit_interruption(
                observed_at=error.observed_at,
                observation=error.observation,
            )
            raise
        timing = getattr(frame, "performance_timing", None)
        if timing is not None:
            timing.record_seconds(
                "captureTotal",
                perf_counter() - capture_started_at,
            )

        tracking_started_at = perf_counter()
        try:
            tracking_batch = self._tracking_pipeline.process(
                frame,
                # 현재 고정 camera 파일럿은 FrameSource가 full frame을
                # 생성한다는 전제에서 calibration 좌표계를 최종
                # 인증한다. crop·camera health 검증은 기동 계층의 책임이다.
                full_area_observed=(
                    frame.calibration_id == self._calibration_reference
                ),
            )
        except TrackingError:
            self._commit_interruption(
                observed_at=frame.captured_at,
                observation=ObservationStatus(
                    state=ObservationState.UNKNOWN,
                    reason=ObservationReason.PIPELINE_STALLED,
                ),
            )
            raise
        if timing is not None:
            tracking_seconds = perf_counter() - tracking_started_at
            detector_ms = timing.duration_ms("detector") or 0.0
            timing.record_seconds(
                "trackingPostprocess",
                max(tracking_seconds - detector_ms / 1_000.0, 0.0),
            )

        commit_started_at = perf_counter()
        result = self._commit_batch(tracking_batch)
        if timing is not None:
            timing.record_seconds(
                "commit",
                perf_counter() - commit_started_at,
            )
        evidence_started_at = perf_counter()
        if self._evidence_capture_sink is not None:
            self._evidence_capture_sink.capture(
                frame,
                tracking_batch,
                result.evidence_capture_intents,
            )
        if timing is not None:
            timing.record_seconds(
                "evidence",
                perf_counter() - evidence_started_at,
            )
        self._apply_post_commit_effects(
            result,
            observed_at=tracking_batch.observed_at,
        )
        if frame_observer is not None:
            frame_observer(frame, tracking_batch, result)
        return result

    def _commit_interruption(
        self,
        *,
        observed_at: datetime,
        observation: ObservationStatus,
    ) -> FrameObservationResult:
        """비신뢰 관측을 같은 frame UoW에 반영해 timer chain을 끊는다."""

        batch = self._tracking_pipeline.interrupt_observation(
            observed_at=observed_at,
            observation=observation,
        )
        result = self._commit_batch(batch)
        self._apply_post_commit_effects(result, observed_at=batch.observed_at)
        return result

    def _commit_batch(
        self,
        tracking_batch: TrackingBatch,
    ) -> FrameObservationResult:
        """TrackingBatch의 local transaction만 commit한다."""

        connection = self._connection_factory()
        try:
            return self._frame_workflow.process(
                tracking_batch,
                connection=connection,
            )
        finally:
            connection.close()

    def _apply_post_commit_effects(
        self,
        result: FrameObservationResult,
        *,
        observed_at: datetime,
    ) -> None:
        """Evidence adapter 호출 뒤 commit 결과를 process-local projection에
        반영한다.
        """

        for physical_vehicle_id in result.retired_physical_vehicle_ids:
            self._tracking_pipeline.forget_physical_vehicle(
                physical_vehicle_id
            )
        self._apply_actuator_projection(
            result.active_incidents,
            requested_at=observed_at,
        )

    def _apply_actuator_projection(
        self,
        incidents: tuple[Incident, ...],
        *,
        requested_at: datetime,
    ) -> None:
        """commit된 전체 Incident projection만 외부 adapter에 전달한다."""

        if self._actuator_command_planner is None:
            return
        assert self._actuator_port is not None
        commands = self._actuator_command_planner.plan(
            incidents,
            requested_at=requested_at,
        )
        self._actuator_port.apply_projection(commands)

    def run(
        self,
        *,
        result_consumer: Callable[[FrameObservationResult], None] | None = None,
        frame_observer: FrameObserver | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        """durable frame을 소스 소진 또는 종료 요청까지 처리한다.

        optional consumer는 commit 후 telemetry·overlay용이며 durable
        저장 책임을 갖지 않는다. consumer 예외는 숨기지 않는다.
        종료 요청은 frame 경계에서만 확인해 capture·model을 다른
        thread에서 동시에 close하지 않는다.

        `frame_observer`는 매 `process_next_frame()` 호출에 그대로
        전달된다 — `process_next_frame`의 `frame_observer` docstring과
        같은 정책(정상 커밋 후에만 호출, 예외 비은닉)을 따른다.
        """

        frames = 0
        should_stop = stop_requested or (lambda: False)
        while not should_stop():
            try:
                result = self.process_next_frame(frame_observer=frame_observer)
            except EndOfVideo:
                break
            if result_consumer is not None:
                result_consumer(result)
            frames += 1
        return frames

    def close(self) -> None:
        """보류 Evidence를 재조정한 뒤 프레임 소스와 추적 자원을 해제한다."""

        try:
            if self._evidence_capture_sink is not None:
                flush_pending = getattr(
                    self._evidence_capture_sink,
                    "flush_pending",
                    None,
                )
                if callable(flush_pending):
                    flush_pending()
        finally:
            try:
                self._tracking_pipeline.close()
            finally:
                self._frame_source.close()

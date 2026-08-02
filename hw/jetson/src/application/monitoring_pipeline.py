"""카메라·추적·durable frame workflow를 조립하는 실행 파이프라인.

실행 순서와 오류 경계만 관리하며 bbox 기하 계산이나
위반 조건 판단은 각 domain 계층에 맡긴다.

`TrackingPipeline`은 임시 TrackSegment와 PhysicalVehicle 관측 신호만
만든다. ``FrameObservationWorkflow``가 SessionContext 매칭, parking
aggregate, physical departure, outbox를 하나의 SQLite UnitOfWork로
commit한다. NOT_PRESENT ACK는 그 commit이 성공한 뒤에만 전달한다.

프레임 캡처나 추론이 실패하면 부재 누적 연속성을 먼저 끊고
원래 예외를 전파한다. 그렇지 않으면 다음 정상 frame이 장애 구간의
wall-clock을 NOT_PRESENT 확정 시간에 포함한다. `EndOfVideo`는 리플레이
정상 종료이므로 `run()`에서만 조용히 멈춘다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import sqlite3

from src.actuators.ports import ActuatorCommandPlanner, ActuatorPort
from src.application.frame_observation_workflow import (
    FrameObservationResult,
    FrameObservationWorkflow,
)
from src.camera.frame_source import EndOfVideo, FrameSource, FrameSourceError
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.models import Incident
from src.tracking.models import TrackingBatch
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import TrackingError


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
    ) -> None:
        if not calibration_reference:
            raise ValueError("calibration_reference must not be empty")
        if (actuator_command_planner is None) != (actuator_port is None):
            raise ValueError(
                "actuator_command_planner and actuator_port must be provided together"
            )
        self._frame_source = frame_source
        self._tracking_pipeline = tracking_pipeline
        self._frame_workflow = frame_workflow
        self._connection_factory = connection_factory
        self._calibration_reference = calibration_reference
        self._actuator_command_planner = actuator_command_planner
        self._actuator_port = actuator_port

    def open(self) -> None:
        """durable runtime을 복원한 뒤 프레임 소스와 추적을 연다."""

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
        except TrackingError:
            self._commit_interruption(
                observed_at=datetime.now(timezone.utc),
                observation=ObservationStatus(
                    state=ObservationState.UNKNOWN,
                    reason=ObservationReason.PIPELINE_STALLED,
                ),
            )
            self._frame_source.close()
            raise
        except Exception:
            # frame source를 먼저 연 뒤 model 로드가 실패해도
            # camera handle을 남기지 않는다. 원래 기동 예외는 유지한다.
            self._frame_source.close()
            raise

    def process_next_frame(self) -> FrameObservationResult:
        """프레임 한 장을 캡처·추적하고 durable commit 결과를 반환한다.

        프레임 소진 시 `EndOfVideo`가, 그 외 캡처·추적 실패 시 각 계층의
        오류(`FrameSourceError`/`TrackingError`)가 그대로 전파된다 — 호출부가
        판단할 문제다.
        """

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

        return self._commit_batch(tracking_batch)

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
        return self._commit_batch(batch)

    def _commit_batch(
        self,
        tracking_batch: TrackingBatch,
    ) -> FrameObservationResult:
        """TrackingBatch를 commit하고 그 이후의 projection side effect를 적용한다."""

        connection = self._connection_factory()
        try:
            result = self._frame_workflow.process(
                tracking_batch,
                connection=connection,
            )
        finally:
            connection.close()
        for physical_vehicle_id in result.retired_physical_vehicle_ids:
            self._tracking_pipeline.forget_physical_vehicle(
                physical_vehicle_id
            )
        self._apply_actuator_projection(
            result.active_incidents,
            requested_at=tracking_batch.observed_at,
        )
        return result

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
        stop_requested: Callable[[], bool] | None = None,
    ) -> int:
        """durable frame을 소스 소진 또는 종료 요청까지 처리한다.

        optional consumer는 commit 후 telemetry·overlay용이며 durable
        저장 책임을 갖지 않는다. consumer 예외는 숨기지 않는다.
        종료 요청은 frame 경계에서만 확인해 capture·model을 다른
        thread에서 동시에 close하지 않는다.
        """

        frames = 0
        should_stop = stop_requested or (lambda: False)
        while not should_stop():
            try:
                result = self.process_next_frame()
            except EndOfVideo:
                break
            if result_consumer is not None:
                result_consumer(result)
            frames += 1
        return frames

    def close(self) -> None:
        """프레임 소스와 추적 모델 자원을 해제한다."""

        try:
            self._frame_source.close()
        finally:
            self._tracking_pipeline.close()

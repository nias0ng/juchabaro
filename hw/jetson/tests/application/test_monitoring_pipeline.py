"""MonitoringPipeline의 frame 결과 인계와 capture 오류 경계 테스트."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

# frame_source의 calibration helper가 numpy를 사용한다. Jetson runtime 또는
# full dev 환경에서는 실행하고, storage 전용 경량 환경에서는 module 단위로 건너뛴다.
pytest.importorskip("numpy")

from src.application.frame_observation_workflow import FrameObservationResult
from src.application.monitoring_pipeline import MonitoringPipeline
from src.camera.frame_source import EndOfVideo, FrameSourceError
from src.parking.models import ParkingPipelineResult
from src.tracking.models import PhysicalVehicleId

VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000099")
)


def _result(*, retired=()) -> FrameObservationResult:
    return FrameObservationResult(
        parking_result=ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(),
            incident_transitions=(),
        ),
        retired_physical_vehicle_ids=retired,
    )


class _FrameSource:
    def __init__(self, frames: list[object]) -> None:
        self._frames = iter(frames)
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def capture(self):
        try:
            return next(self._frames)
        except StopIteration as error:
            raise EndOfVideo("source exhausted") from error

    def close(self) -> None:
        self.closed = True


class _FailingFrameSource(_FrameSource):
    def capture(self):
        raise FrameSourceError("camera unavailable")


class _TrackingPipeline:
    def __init__(self, *, open_error: Exception | None = None) -> None:
        self.opened = False
        self.closed = False
        self.open_error = open_error
        self.pause_count = 0
        self.full_area_flags: list[bool] = []
        self.forgotten: list[PhysicalVehicleId] = []
        self.restored_checkpoints: list[tuple] = []

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    def process(self, frame, *, full_area_observed: bool):
        self.full_area_flags.append(full_area_observed)
        return frame

    def pause_absence_confirmation(self) -> None:
        self.pause_count += 1

    def forget_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> None:
        self.forgotten.append(physical_vehicle_id)

    def restore_active_checkpoints(self, vehicles: tuple) -> None:
        self.restored_checkpoints.append(vehicles)

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FrameWorkflow:
    def __init__(self, *, retired=()) -> None:
        self.results: list[FrameObservationResult] = []
        self.retired = retired
        self.connections: list[_Connection] = []
        self.recovery_connections: list[_Connection] = []

    def recover_runtime(self, *, connection):
        self.recovery_connections.append(connection)
        return SimpleNamespace(active_physical_vehicles=())

    def process(self, _batch, *, connection) -> FrameObservationResult:
        self.connections.append(connection)
        result = _result(retired=self.retired)
        self.results.append(result)
        return result


def _pipeline(frame_source, tracking, workflow) -> MonitoringPipeline:
    return MonitoringPipeline(
        frame_source=frame_source,
        tracking_pipeline=tracking,
        frame_workflow=workflow,
        connection_factory=_Connection,
        calibration_reference="pilot-v1",
    )


def test_run_hands_every_frame_result_to_consumer_before_counting_it() -> None:
    frames = [
        SimpleNamespace(calibration_id="pilot-v1"),
        SimpleNamespace(calibration_id="other"),
    ]
    frame_source = _FrameSource(frames)
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow(retired=(VEHICLE_ID,))
    pipeline = _pipeline(frame_source, tracking, workflow)
    consumed: list[FrameObservationResult] = []

    assert pipeline.run(result_consumer=consumed.append) == 2

    assert consumed == workflow.results
    assert tracking.full_area_flags == [True, False]
    assert tracking.forgotten == [VEHICLE_ID, VEHICLE_ID]
    assert all(connection.closed for connection in workflow.connections)


def test_run_does_not_count_result_when_consumer_fails() -> None:
    frame_source = _FrameSource([SimpleNamespace(calibration_id="pilot-v1")])
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)

    def reject(_result: FrameObservationResult) -> None:
        raise RuntimeError("transaction failed")

    with pytest.raises(RuntimeError, match="transaction failed"):
        pipeline.run(result_consumer=reject)

    assert len(workflow.results) == 1


def test_capture_failure_pauses_absence_confirmation_and_propagates() -> None:
    tracking = _TrackingPipeline()
    pipeline = _pipeline(_FailingFrameSource([]), tracking, _FrameWorkflow())

    with pytest.raises(FrameSourceError, match="camera unavailable"):
        pipeline.process_next_frame()

    assert tracking.pause_count == 1


def test_open_and_close_delegate_resource_lifecycle() -> None:
    frame_source = _FrameSource([])
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)

    pipeline.open()
    pipeline.close()

    assert frame_source.opened and frame_source.closed
    assert tracking.opened and tracking.closed
    assert len(workflow.recovery_connections) == 1
    assert workflow.recovery_connections[0].closed
    assert tracking.restored_checkpoints == [()]


def test_open_closes_frame_source_when_tracking_model_fails() -> None:
    frame_source = _FrameSource([])
    tracking = _TrackingPipeline(open_error=RuntimeError("model load failed"))
    pipeline = _pipeline(frame_source, tracking, _FrameWorkflow())

    with pytest.raises(RuntimeError, match="model load failed"):
        pipeline.open()

    assert frame_source.opened is True
    assert frame_source.closed is True
    assert tracking.opened is False

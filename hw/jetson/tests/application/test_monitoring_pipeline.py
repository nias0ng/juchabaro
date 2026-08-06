"""MonitoringPipeline의 frame 결과 인계와 capture 오류 경계 테스트."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

# frame_source의 calibration helper가 numpy를 사용한다. Jetson runtime 또는
# full dev 환경에서는 실행하고, storage 전용 경량 환경에서는 module 단위로 건너뛴다.
pytest.importorskip("numpy")

from src.application.frame_observation_workflow import FrameObservationResult
from src.application.monitoring_pipeline import MonitoringPipeline
from src.actuators.models import ActuatorCommand
from src.camera.frame_source import EndOfVideo, FrameSourceError
from src.domain.models import ObservationReason, ObservationState
from src.parking.models import ParkingPipelineResult
from src.storage.database import connect_database, open_database
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import PhysicalVehicleId
from src.tracking.protocols import TrackingError

VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000099")
)
OBSERVED_AT = datetime(2026, 8, 2, tzinfo=timezone.utc)


def _result(
    *,
    retired=(),
    active_incidents=(),
    evidence_capture_intents=(),
) -> FrameObservationResult:
    return FrameObservationResult(
        parking_result=ParkingPipelineResult(
            zone_visit_updates=(),
            parking_episode_updates=(),
            incident_transitions=(),
        ),
        retired_physical_vehicle_ids=retired,
        active_incidents=active_incidents,
        evidence_capture_intents=evidence_capture_intents,
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


class _OpenFailingFrameSource(_FrameSource):
    def open(self) -> None:
        raise FrameSourceError("camera open failed")


class _TrackingPipeline:
    def __init__(
        self,
        *,
        open_error: Exception | None = None,
        process_error: Exception | None = None,
    ) -> None:
        self.opened = False
        self.closed = False
        self.open_error = open_error
        self.process_error = process_error
        self.pause_count = 0
        self.full_area_flags: list[bool] = []
        self.forgotten: list[PhysicalVehicleId] = []
        self.restored_checkpoints: list[tuple] = []
        self.interruptions: list[SimpleNamespace] = []

    def open(self) -> None:
        if self.open_error is not None:
            raise self.open_error
        self.opened = True

    def process(self, frame, *, full_area_observed: bool):
        if self.process_error is not None:
            raise self.process_error
        self.full_area_flags.append(full_area_observed)
        return SimpleNamespace(
            observed_at=getattr(frame, "captured_at", OBSERVED_AT)
        )

    def pause_absence_confirmation(self) -> None:
        self.pause_count += 1

    def interrupt_observation(self, *, observed_at, observation):
        self.pause_absence_confirmation()
        batch = SimpleNamespace(
            observed_at=observed_at,
            observation=observation,
        )
        self.interruptions.append(batch)
        return batch

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
    def __init__(
        self,
        *,
        retired=(),
        active_incidents=(),
        evidence_capture_intents=(),
    ) -> None:
        self.results: list[FrameObservationResult] = []
        self.retired = retired
        self.active_incidents = active_incidents
        self.evidence_capture_intents = evidence_capture_intents
        self.batches: list[object] = []
        self.connections: list[_Connection] = []
        self.recovery_connections: list[_Connection] = []

    def recover_runtime(self, *, connection):
        self.recovery_connections.append(connection)
        return SimpleNamespace(
            active_physical_vehicles=(),
            active_incidents=self.active_incidents,
        )

    def process(self, batch, *, connection) -> FrameObservationResult:
        self.connections.append(connection)
        self.batches.append(batch)
        result = _result(
            retired=self.retired,
            active_incidents=self.active_incidents,
            evidence_capture_intents=self.evidence_capture_intents,
        )
        self.results.append(result)
        return result


def _pipeline(
    frame_source,
    tracking,
    workflow,
    *,
    actuator_command_planner=None,
    actuator_port=None,
    evidence_capture_sink=None,
    connection_factory=_Connection,
) -> MonitoringPipeline:
    return MonitoringPipeline(
        frame_source=frame_source,
        tracking_pipeline=tracking,
        frame_workflow=workflow,
        connection_factory=connection_factory,
        calibration_reference="pilot-v1",
        actuator_command_planner=actuator_command_planner,
        actuator_port=actuator_port,
        evidence_capture_sink=evidence_capture_sink,
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


def test_run_honors_stop_request_before_capturing_next_frame() -> None:
    frame_source = _FrameSource(
        [SimpleNamespace(calibration_id="pilot-v1")]
    )
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)

    assert pipeline.run(stop_requested=lambda: True) == 0

    assert workflow.results == []
    assert tracking.full_area_flags == []


def test_capture_failure_pauses_absence_confirmation_and_propagates() -> None:
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(_FailingFrameSource([]), tracking, workflow)

    with pytest.raises(FrameSourceError, match="camera unavailable"):
        pipeline.process_next_frame()

    assert tracking.pause_count == 1
    assert len(workflow.batches) == 1
    assert (
        workflow.batches[0].observation.state
        is ObservationState.UNKNOWN
    )
    assert (
        workflow.batches[0].observation.reason
        is ObservationReason.CAMERA_UNAVAILABLE
    )
    assert workflow.connections[0].closed is True


def test_tracking_failure_commits_pipeline_stalled_observation() -> None:
    frame = SimpleNamespace(
        calibration_id="pilot-v1",
        captured_at=OBSERVED_AT,
    )
    tracking = _TrackingPipeline(
        process_error=TrackingError("inference failed")
    )
    workflow = _FrameWorkflow()
    pipeline = _pipeline(_FrameSource([frame]), tracking, workflow)

    with pytest.raises(TrackingError, match="inference failed"):
        pipeline.process_next_frame()

    assert len(workflow.batches) == 1
    assert (
        workflow.batches[0].observation.reason
        is ObservationReason.PIPELINE_STALLED
    )


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


def test_close_flushes_pending_evidence_before_releasing_frame_resources() -> None:
    frame_source = _FrameSource([])
    tracking = _TrackingPipeline()
    flushed: list[str] = []

    class _CaptureSink:
        def capture(self, *_args) -> None:
            return

        def flush_pending(self) -> None:
            assert frame_source.closed is False
            assert tracking.closed is False
            flushed.append("evidence")

    pipeline = _pipeline(
        frame_source,
        tracking,
        _FrameWorkflow(),
        evidence_capture_sink=_CaptureSink(),
    )

    pipeline.close()

    assert flushed == ["evidence"]
    assert frame_source.closed is True
    assert tracking.closed is True


def test_camera_open_failure_commits_unknown_observation_before_propagating() -> None:
    frame_source = _OpenFailingFrameSource([])
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)

    with pytest.raises(FrameSourceError, match="camera open failed"):
        pipeline.open()

    assert frame_source.closed is True
    assert len(workflow.batches) == 1
    assert (
        workflow.batches[0].observation.reason
        is ObservationReason.CAMERA_UNAVAILABLE
    )


def test_open_closes_frame_source_when_tracking_model_fails() -> None:
    frame_source = _FrameSource([])
    tracking = _TrackingPipeline(open_error=RuntimeError("model load failed"))
    pipeline = _pipeline(frame_source, tracking, _FrameWorkflow())

    with pytest.raises(RuntimeError, match="model load failed"):
        pipeline.open()

    assert frame_source.opened is True
    assert frame_source.closed is True
    assert tracking.opened is False


class _ActuatorPlanner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, datetime]] = []

    def plan(self, incidents, *, requested_at):
        self.calls.append((incidents, requested_at))
        return (
            ActuatorCommand(
                actuator_id="warning-led",
                action="ACTIVE",
                reason="ACTIVE_INCIDENT_PROJECTION",
                requested_at=requested_at,
            ),
        )


class _ActuatorPort:
    def __init__(self) -> None:
        self.projections: list[tuple[ActuatorCommand, ...]] = []

    def apply_projection(self, commands) -> None:
        self.projections.append(commands)


def test_actuator_receives_full_projection_after_recovery_and_frame_commit() -> None:
    incident = SimpleNamespace(incident_id="incident-1")
    workflow = _FrameWorkflow(active_incidents=(incident,))
    planner = _ActuatorPlanner()
    port = _ActuatorPort()
    pipeline = _pipeline(
        _FrameSource([SimpleNamespace(calibration_id="pilot-v1")]),
        _TrackingPipeline(),
        workflow,
        actuator_command_planner=planner,
        actuator_port=port,
    )

    pipeline.open()
    pipeline.process_next_frame()

    assert [call[0] for call in planner.calls] == [
        (incident,),
        (incident,),
    ]
    assert len(port.projections) == 2
    assert all(
        projection[0].actuator_id == "warning-led"
        for projection in port.projections
    )


def test_actuator_planner_and_port_must_be_injected_together() -> None:
    with pytest.raises(ValueError, match="must be provided together"):
        _pipeline(
            _FrameSource([]),
            _TrackingPipeline(),
            _FrameWorkflow(),
            actuator_command_planner=_ActuatorPlanner(),
        )


def test_process_next_frame_calls_frame_observer_after_commit() -> None:
    frame = SimpleNamespace(calibration_id="pilot-v1")
    frame_source = _FrameSource([frame])
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)
    observed: list[tuple] = []

    result = pipeline.process_next_frame(
        frame_observer=lambda f, batch, r: observed.append((f, batch, r))
    )

    assert len(observed) == 1
    observed_frame, observed_batch, observed_result = observed[0]
    assert observed_frame is frame
    assert observed_batch in workflow.batches
    assert observed_result is result
    assert observed_result is workflow.results[0]


def test_process_next_frame_orders_commit_evidence_and_post_commit_effects() -> None:
    frame = SimpleNamespace(calibration_id="pilot-v1")
    order: list[str] = []
    incident = SimpleNamespace(incident_id="incident-1")

    class _OrderedWorkflow(_FrameWorkflow):
        def process(self, batch, *, connection) -> FrameObservationResult:
            result = super().process(batch, connection=connection)
            order.append("commit")
            return result

    class _OrderedTracking(_TrackingPipeline):
        def forget_physical_vehicle(self, physical_vehicle_id) -> None:
            order.append("retire")
            super().forget_physical_vehicle(physical_vehicle_id)

    class _OrderedPlanner(_ActuatorPlanner):
        def plan(self, incidents, *, requested_at):
            order.append("actuator-plan")
            return super().plan(incidents, requested_at=requested_at)

    class _OrderedPort(_ActuatorPort):
        def apply_projection(self, commands) -> None:
            order.append("actuator-apply")
            super().apply_projection(commands)

    workflow = _OrderedWorkflow(
        retired=(VEHICLE_ID,),
        active_incidents=(incident,),
        evidence_capture_intents=("capture-intent",),
    )
    tracking = _OrderedTracking()

    class _CaptureSink:
        def capture(self, captured_frame, batch, intents) -> None:
            assert captured_frame is frame
            assert batch in workflow.batches
            assert all(connection.closed for connection in workflow.connections)
            assert intents == ("capture-intent",)
            order.append("capture")

    pipeline = _pipeline(
        _FrameSource([frame]),
        tracking,
        workflow,
        actuator_command_planner=_OrderedPlanner(),
        actuator_port=_OrderedPort(),
        evidence_capture_sink=_CaptureSink(),
    )

    pipeline.process_next_frame(
        frame_observer=lambda *_args: order.append("observer")
    )

    assert order == [
        "commit",
        "capture",
        "retire",
        "actuator-plan",
        "actuator-apply",
        "observer",
    ]
    assert tracking.forgotten == [VEHICLE_ID]


def test_evidence_sink_reads_committed_state_from_separate_connection(
    tmp_path,
) -> None:
    database_path = tmp_path / "monitoring.db"
    connection = open_database(database_path)
    try:
        connection.execute(
            "CREATE TABLE phase_two_commit_probe (probe_id INTEGER PRIMARY KEY)"
        )
    finally:
        connection.close()

    class _DurableWorkflow:
        def process(self, _batch, *, connection) -> FrameObservationResult:
            with UnitOfWork(connection):
                connection.execute(
                    "INSERT INTO phase_two_commit_probe(probe_id) VALUES (1)"
                )
            return _result(evidence_capture_intents=("capture-intent",))

    class _CaptureSink:
        def capture(self, _frame, _batch, _intents) -> None:
            reader = connect_database(database_path)
            try:
                row = reader.execute(
                    "SELECT probe_id FROM phase_two_commit_probe"
                ).fetchone()
            finally:
                reader.close()
            assert row is not None and int(row[0]) == 1

    pipeline = _pipeline(
        _FrameSource([SimpleNamespace(calibration_id="pilot-v1")]),
        _TrackingPipeline(),
        _DurableWorkflow(),
        evidence_capture_sink=_CaptureSink(),
        connection_factory=lambda: connect_database(database_path),
    )

    pipeline.process_next_frame()


def test_evidence_failure_prevents_retire_actuator_and_observer() -> None:
    frame = SimpleNamespace(calibration_id="pilot-v1")
    incident = SimpleNamespace(incident_id="incident-1")
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow(
        retired=(VEHICLE_ID,),
        active_incidents=(incident,),
        evidence_capture_intents=("capture-intent",),
    )
    planner = _ActuatorPlanner()
    port = _ActuatorPort()
    observed: list[tuple] = []

    class _FailingCaptureSink:
        def capture(self, *_args) -> None:
            raise RuntimeError("evidence remained WRITING")

    pipeline = _pipeline(
        _FrameSource([frame]),
        tracking,
        workflow,
        actuator_command_planner=planner,
        actuator_port=port,
        evidence_capture_sink=_FailingCaptureSink(),
    )

    with pytest.raises(RuntimeError, match="remained WRITING"):
        pipeline.process_next_frame(
            frame_observer=lambda *args: observed.append(args)
        )

    assert tracking.forgotten == []
    assert planner.calls == []
    assert port.projections == []
    assert observed == []


def test_retire_failure_propagates_after_evidence_capture() -> None:
    order: list[str] = []

    class _FailingTracking(_TrackingPipeline):
        def forget_physical_vehicle(self, physical_vehicle_id) -> None:
            order.append("retire")
            raise RuntimeError("retire failed")

    class _CaptureSink:
        def capture(self, *_args) -> None:
            order.append("capture")

    pipeline = _pipeline(
        _FrameSource([SimpleNamespace(calibration_id="pilot-v1")]),
        _FailingTracking(),
        _FrameWorkflow(
            retired=(VEHICLE_ID,),
            evidence_capture_intents=("capture-intent",),
        ),
        evidence_capture_sink=_CaptureSink(),
    )

    with pytest.raises(RuntimeError, match="retire failed"):
        pipeline.process_next_frame(
            frame_observer=lambda *_args: order.append("observer")
        )

    assert order == ["capture", "retire"]


def test_actuator_failure_propagates_after_evidence_capture_and_retire() -> None:
    order: list[str] = []

    class _CaptureSink:
        def capture(self, *_args) -> None:
            order.append("capture")

    class _FailingPort(_ActuatorPort):
        def apply_projection(self, _commands) -> None:
            order.append("actuator")
            raise RuntimeError("actuator failed")

    class _OrderedTracking(_TrackingPipeline):
        def forget_physical_vehicle(self, physical_vehicle_id) -> None:
            order.append("retire")
            super().forget_physical_vehicle(physical_vehicle_id)

    pipeline = _pipeline(
        _FrameSource([SimpleNamespace(calibration_id="pilot-v1")]),
        _OrderedTracking(),
        _FrameWorkflow(
            retired=(VEHICLE_ID,),
            active_incidents=(SimpleNamespace(incident_id="incident-1"),),
            evidence_capture_intents=("capture-intent",),
        ),
        actuator_command_planner=_ActuatorPlanner(),
        actuator_port=_FailingPort(),
        evidence_capture_sink=_CaptureSink(),
    )

    with pytest.raises(RuntimeError, match="actuator failed"):
        pipeline.process_next_frame(
            frame_observer=lambda *_args: order.append("observer")
        )

    assert order == ["capture", "retire", "actuator"]


def test_process_next_frame_skips_observer_when_frame_capture_fails() -> None:
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(_FailingFrameSource([]), tracking, workflow)
    observed: list[tuple] = []

    with pytest.raises(FrameSourceError, match="camera unavailable"):
        pipeline.process_next_frame(
            frame_observer=lambda f, batch, r: observed.append((f, batch, r))
        )

    assert observed == []


def test_process_next_frame_skips_observer_when_tracking_fails() -> None:
    frame = SimpleNamespace(calibration_id="pilot-v1", captured_at=OBSERVED_AT)
    tracking = _TrackingPipeline(process_error=TrackingError("inference failed"))
    workflow = _FrameWorkflow()
    pipeline = _pipeline(_FrameSource([frame]), tracking, workflow)
    observed: list[tuple] = []

    with pytest.raises(TrackingError, match="inference failed"):
        pipeline.process_next_frame(
            frame_observer=lambda f, batch, r: observed.append((f, batch, r))
        )

    assert observed == []


def test_run_threads_frame_observer_into_every_frame() -> None:
    frames = [
        SimpleNamespace(calibration_id="pilot-v1"),
        SimpleNamespace(calibration_id="other"),
    ]
    frame_source = _FrameSource(frames)
    tracking = _TrackingPipeline()
    workflow = _FrameWorkflow()
    pipeline = _pipeline(frame_source, tracking, workflow)
    observed: list[tuple] = []

    frame_count = pipeline.run(
        frame_observer=lambda f, batch, r: observed.append((f, batch, r))
    )

    assert frame_count == 2
    assert [entry[0] for entry in observed] == frames
    assert [entry[2] for entry in observed] == workflow.results

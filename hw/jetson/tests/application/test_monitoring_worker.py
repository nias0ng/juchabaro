"""Monitoring worker의 단일 thread·종료 생명주기 테스트."""

import logging
from threading import Event
from types import SimpleNamespace

import pytest

from src.application.monitoring_worker import MonitoringWorker
from src.domain.models import ObservationState
from src.parking.models import IncidentTransitionType
from src.session.models import EntryDecisionState, EntryMatchState


class _BlockingPipeline:
    def __init__(self) -> None:
        self.opened = False
        self.entered_run = Event()
        self.closed = Event()

    def open(self) -> None:
        self.opened = True

    def run(self, *, stop_requested, frame_observer=None) -> int:
        del frame_observer
        self.entered_run.set()
        while not stop_requested():
            self.closed.wait(0.01)
        return 4

    def close(self) -> None:
        self.closed.set()


class _OpenFailingPipeline(_BlockingPipeline):
    def open(self) -> None:
        raise RuntimeError("camera open failed")


class _RunFailingPipeline(_BlockingPipeline):
    def run(self, *, stop_requested, frame_observer=None) -> int:
        del stop_requested, frame_observer
        self.entered_run.set()
        raise RuntimeError("inference failed")


class _ObservingPipeline(_BlockingPipeline):
    def run(self, *, frame_observer, stop_requested) -> int:
        self.entered_run.set()
        frame_observer(
            None,
            _batch(frame_id=1),
            _result_with_transitions(),
        )
        frame_observer(
            None,
            _batch(frame_id=2),
            _empty_result(),
        )
        while not stop_requested():
            self.closed.wait(0.01)
        return 2


def test_worker_opens_once_and_closes_after_graceful_stop() -> None:
    pipeline = _BlockingPipeline()
    worker = MonitoringWorker(pipeline)

    worker.start()
    assert pipeline.entered_run.wait(timeout=1.0)

    worker.stop()

    assert pipeline.opened is True
    assert pipeline.closed.is_set()
    assert worker.is_running is False
    assert worker.failure is None


def test_worker_propagates_synchronous_startup_failure() -> None:
    worker = MonitoringWorker(_OpenFailingPipeline())

    with pytest.raises(RuntimeError, match="camera open failed"):
        worker.start()


def test_worker_records_background_failure_and_still_closes() -> None:
    pipeline = _RunFailingPipeline()
    worker = MonitoringWorker(pipeline)

    worker.start()
    assert pipeline.closed.wait(timeout=1.0)
    worker.stop()

    assert isinstance(worker.failure, RuntimeError)
    assert str(worker.failure) == "inference failed"
    assert worker.is_running is False


def test_worker_cannot_be_started_twice() -> None:
    pipeline = _BlockingPipeline()
    worker = MonitoringWorker(pipeline)
    worker.start()
    assert pipeline.entered_run.wait(timeout=1.0)
    try:
        with pytest.raises(RuntimeError, match="only be started once"):
            worker.start()
    finally:
        worker.stop()


def test_worker_logs_committed_transitions_and_throttled_heartbeat(
    caplog,
) -> None:
    pipeline = _ObservingPipeline()
    clock_values = iter((100.0, 101.0))
    worker = MonitoringWorker(
        pipeline,
        heartbeat_interval_seconds=10.0,
        monotonic_clock=lambda: next(clock_values),
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.application.monitoring_worker",
    ):
        worker.start()
        assert pipeline.entered_run.wait(timeout=1.0)
        worker.stop()

    assert "Jetson monitoring worker가 시작됐습니다." in caplog.text
    assert caplog.text.count("Jetson monitoring heartbeat.") == 1
    assert "detections=2" in caplog.text
    assert "trackedVehicles=1" in caplog.text
    assert "입차 차량 매치 결과가 확정됐습니다." in caplog.text
    assert "matchState=MATCHED" in caplog.text
    assert "주차 상태 전이가 확정됐습니다." in caplog.text
    assert "transitionType=PARKED" in caplog.text
    assert "주차 Incident 상태 전이가 확정됐습니다." in caplog.text
    assert "ruleCode=BAD_PARKING" in caplog.text
    assert "차량 출차 처리가 확정됐습니다." in caplog.text
    assert "raw-payload" not in caplog.text
    assert "api-key" not in caplog.text


def test_worker_composes_operational_and_external_frame_observers() -> None:
    pipeline = _ObservingPipeline()
    observed_frame_ids: list[int] = []

    def observer(_frame, tracking_batch, _result) -> None:
        observed_frame_ids.append(tracking_batch.frame_id)

    worker = MonitoringWorker(pipeline, frame_observer=observer)

    worker.start()
    assert pipeline.entered_run.wait(timeout=1.0)
    worker.stop()

    assert observed_frame_ids == [1, 2]


def _batch(*, frame_id: int):
    return SimpleNamespace(
        camera_id="camera-1",
        frame_id=frame_id,
        detection_count=2,
        vehicles=(object(),),
        observation=SimpleNamespace(state=ObservationState.OBSERVED),
        all_detections_tracked=True,
        all_identities_resolved=True,
    )


def _empty_result():
    return SimpleNamespace(
        entry_match_updates=(),
        parking_result=SimpleNamespace(
            parking_transitions=(),
            incident_transitions=(),
        ),
        retired_physical_vehicle_ids=(),
    )


def _result_with_transitions():
    physical_vehicle_id = "10000000-0000-4000-8000-000000000001"
    return SimpleNamespace(
        entry_match_updates=(
            SimpleNamespace(
                entry_attempt_id=(
                    "20000000-0000-4000-8000-000000000001"
                ),
                decision_state=EntryDecisionState.ALLOW,
                match_state=EntryMatchState.MATCHED,
                matched_physical_vehicle_id=physical_vehicle_id,
                terminal_reason=None,
            ),
        ),
        parking_result=SimpleNamespace(
            parking_transitions=(
                SimpleNamespace(
                    transition_type=SimpleNamespace(value="PARKED"),
                    parking_episode_id=(
                        "30000000-0000-4000-8000-000000000001"
                    ),
                    physical_vehicle_id=physical_vehicle_id,
                    assignment=SimpleNamespace(zone_id=7),
                    publication_revision=1,
                ),
            ),
            incident_transitions=(
                SimpleNamespace(
                    transition_type=IncidentTransitionType.OPEN,
                    incident=SimpleNamespace(
                        key=SimpleNamespace(rule_code="BAD_PARKING"),
                        incident_id=(
                            "40000000-0000-4000-8000-000000000001"
                        ),
                        physical_vehicle_id=physical_vehicle_id,
                        zone_id=7,
                        publication_revision=1,
                    ),
                ),
            ),
        ),
        retired_physical_vehicle_ids=(physical_vehicle_id,),
    )

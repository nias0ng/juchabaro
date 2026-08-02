"""Monitoring worker의 단일 thread·종료 생명주기 테스트."""

from threading import Event

import pytest

from src.application.monitoring_worker import MonitoringWorker


class _BlockingPipeline:
    def __init__(self) -> None:
        self.opened = False
        self.entered_run = Event()
        self.closed = Event()

    def open(self) -> None:
        self.opened = True

    def run(self, *, stop_requested) -> int:
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
    def run(self, *, stop_requested) -> int:
        del stop_requested
        self.entered_run.set()
        raise RuntimeError("inference failed")


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

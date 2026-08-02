"""MonitoringPipeline의 frame 결과 인계와 capture 오류 경계 테스트."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

# frame_source의 calibration helper가 numpy를 사용한다. Jetson runtime 또는
# full dev 환경에서는 실행하고, storage 전용 경량 환경에서는 module 단위로 건너뛴다.
pytest.importorskip("numpy")

from src.application.monitoring_pipeline import MonitoringPipeline
from src.camera.frame_source import EndOfVideo, FrameSourceError
from src.parking.models import ParkingPipelineResult


def _result() -> ParkingPipelineResult:
    return ParkingPipelineResult(
        zone_visit_updates=(),
        parking_episode_updates=(),
        incident_transitions=(),
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
    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.pause_count = 0
        self.full_area_flags: list[bool] = []

    def open(self) -> None:
        self.opened = True

    def process(self, frame, *, full_area_observed: bool):
        self.full_area_flags.append(full_area_observed)
        return frame

    def pause_absence_confirmation(self) -> None:
        self.pause_count += 1

    def close(self) -> None:
        self.closed = True


class _ParkingPipeline:
    def __init__(self) -> None:
        self.results: list[ParkingPipelineResult] = []

    def process(self, _batch) -> ParkingPipelineResult:
        result = _result()
        self.results.append(result)
        return result


def _pipeline(frame_source, tracking, parking) -> MonitoringPipeline:
    return MonitoringPipeline(
        frame_source=frame_source,
        tracking_pipeline=tracking,
        parking_pipeline=parking,
        calibration_reference="pilot-v1",
    )


def test_run_hands_every_frame_result_to_consumer_before_counting_it() -> None:
    frames = [
        SimpleNamespace(calibration_id="pilot-v1"),
        SimpleNamespace(calibration_id="other"),
    ]
    frame_source = _FrameSource(frames)
    tracking = _TrackingPipeline()
    parking = _ParkingPipeline()
    pipeline = _pipeline(frame_source, tracking, parking)
    consumed: list[ParkingPipelineResult] = []

    assert pipeline.run(result_consumer=consumed.append) == 2

    assert consumed == parking.results
    assert tracking.full_area_flags == [True, False]


def test_run_does_not_count_result_when_consumer_fails() -> None:
    frame_source = _FrameSource([SimpleNamespace(calibration_id="pilot-v1")])
    tracking = _TrackingPipeline()
    parking = _ParkingPipeline()
    pipeline = _pipeline(frame_source, tracking, parking)

    def reject(_result: ParkingPipelineResult) -> None:
        raise RuntimeError("transaction failed")

    with pytest.raises(RuntimeError, match="transaction failed"):
        pipeline.run(result_consumer=reject)

    assert len(parking.results) == 1


def test_capture_failure_pauses_absence_confirmation_and_propagates() -> None:
    tracking = _TrackingPipeline()
    pipeline = _pipeline(_FailingFrameSource([]), tracking, _ParkingPipeline())

    with pytest.raises(FrameSourceError, match="camera unavailable"):
        pipeline.process_next_frame()

    assert tracking.pause_count == 1


def test_open_and_close_delegate_resource_lifecycle() -> None:
    frame_source = _FrameSource([])
    tracking = _TrackingPipeline()
    pipeline = _pipeline(frame_source, tracking, _ParkingPipeline())

    pipeline.open()
    pipeline.close()

    assert frame_source.opened and frame_source.closed
    assert tracking.opened and tracking.closed

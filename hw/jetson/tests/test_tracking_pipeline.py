"""TrackingPipeline 통합 회귀 테스트 (436).

실제 YOLO/ByteTrack 없이, Detector 계약만 만족하는 FakeDetector로 조립
로직(entity resolve → motion estimate → snapshot/batch 구성)을 검증한다.
"""

from datetime import datetime, timedelta, timezone

from src.camera.models import CapturedFrame
from src.tracking.models import BoundingBox, MotionSignal, TrackObservation
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import ModelInfo

BASE_TIME = datetime(2026, 7, 31, 12, 0, 0, tzinfo=timezone.utc)


class FakeDetector:
    """capture마다 미리 준비된 TrackObservation 목록을 그대로 돌려주는 테스트용 Detector."""

    def __init__(self):
        self.observations_by_frame_id: dict[int, list[TrackObservation]] = {}
        self.opened = False
        self.closed = False

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(library="fake", library_version="0", model_name="fake.pt", tracker_config="fake.yaml")

    def open(self) -> None:
        self.opened = True

    def track(self, frame: CapturedFrame) -> list[TrackObservation]:
        return self.observations_by_frame_id.get(frame.frame_id, [])

    def close(self) -> None:
        self.closed = True


def _make_frame(frame_id: int, captured_at=BASE_TIME) -> CapturedFrame:
    return CapturedFrame(
        camera_id="cam-1", frame_id=frame_id, captured_at=captured_at, image=object(),
        width=640, height=480, calibration_id=None,
    )


def test_open_and_close_delegate_to_detector():
    detector = FakeDetector()
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    pipeline.open()
    pipeline.close()

    assert detector.opened
    assert detector.closed


def test_batch_carries_camera_id_frame_id_and_observed_at():
    detector = FakeDetector()
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    batch = pipeline.process(_make_frame(frame_id=7))

    assert batch.camera_id == "cam-1"
    assert batch.frame_id == 7
    assert batch.observed_at == BASE_TIME
    assert batch.source_available is True


def test_frame_with_no_detections_returns_empty_batch():
    """탐지된 차량이 0대인 프레임(빈 주차장)도 정상적으로 빈 배치를 반환해야 한다."""
    detector = FakeDetector()
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    batch = pipeline.process(_make_frame(frame_id=1))

    assert batch.vehicles == ()
    assert batch.ended_vehicle_ids == ()


def test_new_vehicle_snapshot_has_context_none_and_moving_signal():
    """436는 ContextMatcher(T-16)를 다루지 않으므로 context는 항상 None이어야 한다."""
    detector = FakeDetector()
    detector.observations_by_frame_id[1] = [
        TrackObservation(track_segment_id=1, bbox=BoundingBox(0.1, 0.1, 0.2, 0.2), confidence=0.9, observed_at=BASE_TIME)
    ]
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    batch = pipeline.process(_make_frame(frame_id=1))

    assert len(batch.vehicles) == 1
    snapshot = batch.vehicles[0]
    assert snapshot.physical_vehicle_id == "track-1"
    assert snapshot.camera_id == "cam-1"
    assert snapshot.context is None
    assert snapshot.motion_signal == MotionSignal.MOVING


def test_stationary_vehicle_across_two_frames():
    detector = FakeDetector()
    bbox = BoundingBox(0.1, 0.1, 0.2, 0.2)
    detector.observations_by_frame_id[1] = [
        TrackObservation(track_segment_id=1, bbox=bbox, confidence=0.9, observed_at=BASE_TIME)
    ]
    detector.observations_by_frame_id[2] = [
        TrackObservation(track_segment_id=1, bbox=bbox, confidence=0.9, observed_at=BASE_TIME + timedelta(seconds=1))
    ]
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    pipeline.process(_make_frame(frame_id=1))
    second_batch = pipeline.process(_make_frame(frame_id=2, captured_at=BASE_TIME + timedelta(seconds=1)))

    assert second_batch.vehicles[0].motion_signal == MotionSignal.STATIONARY


def test_vehicle_missing_from_next_frame_is_reported_as_ended():
    detector = FakeDetector()
    detector.observations_by_frame_id[1] = [
        TrackObservation(track_segment_id=1, bbox=BoundingBox(0.1, 0.1, 0.2, 0.2), confidence=0.9, observed_at=BASE_TIME)
    ]
    detector.observations_by_frame_id[2] = []  # 트랙 1이 이번 프레임엔 없음
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    pipeline.process(_make_frame(frame_id=1))
    second_batch = pipeline.process(_make_frame(frame_id=2, captured_at=BASE_TIME + timedelta(seconds=1)))

    assert second_batch.vehicles == ()
    assert second_batch.ended_vehicle_ids == ("track-1",)


def test_reappearing_after_forget_is_treated_as_new_moving_vehicle():
    """차량이 한 번 ended 처리된 뒤 다시 나타나면(§7 재식별 한계), 통과
    구현·MotionEstimator 둘 다 앵커가 정리돼 있어 새 관측(MOVING)으로
    취급해야 한다 — 조용히 STATIONARY로 남으면 정차 시간이 잘못 이어진다."""
    detector = FakeDetector()
    bbox = BoundingBox(0.1, 0.1, 0.2, 0.2)
    detector.observations_by_frame_id[1] = [
        TrackObservation(track_segment_id=1, bbox=bbox, confidence=0.9, observed_at=BASE_TIME)
    ]
    detector.observations_by_frame_id[2] = []
    detector.observations_by_frame_id[3] = [
        TrackObservation(track_segment_id=1, bbox=bbox, confidence=0.9, observed_at=BASE_TIME + timedelta(seconds=2))
    ]
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    pipeline.process(_make_frame(frame_id=1))
    pipeline.process(_make_frame(frame_id=2, captured_at=BASE_TIME + timedelta(seconds=1)))
    third_batch = pipeline.process(_make_frame(frame_id=3, captured_at=BASE_TIME + timedelta(seconds=2)))

    assert third_batch.vehicles[0].motion_signal == MotionSignal.MOVING


def test_multiple_vehicles_in_same_frame_get_independent_snapshots():
    detector = FakeDetector()
    detector.observations_by_frame_id[1] = [
        TrackObservation(track_segment_id=1, bbox=BoundingBox(0.1, 0.1, 0.2, 0.2), confidence=0.9, observed_at=BASE_TIME),
        TrackObservation(track_segment_id=2, bbox=BoundingBox(0.5, 0.5, 0.6, 0.6), confidence=0.8, observed_at=BASE_TIME),
    ]
    pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)

    batch = pipeline.process(_make_frame(frame_id=1))

    ids = {snapshot.physical_vehicle_id for snapshot in batch.vehicles}
    assert ids == {"track-1", "track-2"}

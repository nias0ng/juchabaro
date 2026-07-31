"""UltralyticsVehicleTracker 가드절 회귀 테스트 (436).

ai/training/tests/test_tracking_baseline.py의 test_tracker_rejects_zero_sized_frame과
같은 전략 — 실제 YOLO 모델·ultralytics 패키지 없이도 검증 가능한 가드절만
확인한다. `_model`을 open() 없이 더미로 채워 실제 추론 이전 단계까지만 태운다.
"""

from datetime import datetime, timezone

import pytest
from src.camera.models import CapturedFrame
from src.tracking.adapters.ultralytics_bytetrack import UltralyticsVehicleTracker
from src.tracking.protocols import TrackingError


class _FakeImage:
    """테스트에서 프레임 크기만 흉내 내는 최소 이미지 스텁."""

    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape


def _make_frame(image) -> CapturedFrame:
    return CapturedFrame(
        camera_id="cam-1",
        frame_id=1,
        captured_at=datetime.now(timezone.utc),
        image=image,
        width=0,
        height=0,
        calibration_id=None,
    )


def test_track_before_open_raises():
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)

    with pytest.raises(TrackingError):
        tracker.track(_make_frame(_FakeImage((100, 100, 3))))


def test_rejects_zero_sized_frame():
    """카메라가 순간적으로 빈 프레임을 반환하면 ZeroDivisionError 대신
    TrackingError로 처리되어야 한다."""
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)
    tracker._model = object()  # open() 없이 track()의 프레임 크기 검증만 확인

    with pytest.raises(TrackingError):
        tracker.track(_make_frame(_FakeImage((0, 0, 3))))


def test_model_info_reflects_configured_paths_before_open():
    tracker = UltralyticsVehicleTracker(
        model_path="yolo_vehicle.pt", tracker_config="bytetrack.yaml", confidence=0.5
    )

    info = tracker.model_info

    assert info.library == "ultralytics"
    assert info.model_name == "yolo_vehicle.pt"
    assert info.tracker_config == "bytetrack.yaml"
    assert info.library_version == "not-initialized"


def test_close_before_open_does_not_raise():
    tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)

    tracker.close()  # 예외 없이 조용히 통과해야 한다

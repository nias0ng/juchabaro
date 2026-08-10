"""OpenCvWebcamFrameSource 계약 테스트 (427, ai/tracking baseline에서 이관·확장).

실제 웹캠 장치 없이 cv2.VideoCapture를 가짜로 바꿔 계약을 검증한다. 핵심은
captured_at이 벽시계라는 것과, width/height가 요청값이 아니라 실제로
캡처된 프레임에서 계산된다는 것이다.
"""

from datetime import datetime, timezone

import cv2
import numpy as np
import pytest
from src.camera.frame_source import FrameSourceError, OpenCvWebcamFrameSource
from src.domain.models import ObservationReason, ObservationState


class FakeVideoCapture:
    """cv2.VideoCapture를 흉내 내는 가짜 장치."""

    def __init__(self, frames, *, opened=True):
        self._frames = list(frames)
        self._opened = opened
        self._index = 0
        self.set_calls: list[tuple[int, float]] = []
        self.released = False

    def isOpened(self):
        return self._opened

    def set(self, prop, value):
        self.set_calls.append((prop, value))

    def get(self, prop):
        for set_prop, value in reversed(self.set_calls):
            if set_prop == prop:
                return value
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return self._frames[0].shape[1] if self._frames else 0
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return self._frames[0].shape[0] if self._frames else 0
        return 0

    def read(self):
        if self._index >= len(self._frames):
            return False, None
        frame = self._frames[self._index]
        self._index += 1
        return True, frame

    def release(self):
        self.released = True


def make_bgr_frame(*, width=64, height=48, value=10):
    return np.full((height, width, 3), value, dtype=np.uint8)


def test_rejects_negative_camera_index():
    """음수 인덱스는 cv2 백엔드마다 다르게 반응하니(엉뚱한 장치를 열거나 조용히
    실패) 구성 시점에 막는다(baseline CLI 검증과 동일한 이유)."""
    with pytest.raises(ValueError):
        OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=-1)


@pytest.mark.parametrize("width,height", [(-1, 0), (0, -1), (-100, -100)])
def test_rejects_negative_width_or_height(width, height):
    """음수는 0("요청 생략")과 달리 truthy라 그대로 capture.set()에 넘어간다."""
    with pytest.raises(ValueError):
        OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0, width=width, height=height)


@pytest.mark.parametrize("fps", [-1.0, float("nan"), float("inf")])
def test_rejects_invalid_fps(fps):
    with pytest.raises(ValueError):
        OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0, fps=fps)


@pytest.mark.parametrize("fourcc", ["", "YUYV1", "한글AB"])
def test_rejects_invalid_fourcc(fourcc):
    with pytest.raises(ValueError):
        OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0, fourcc=fourcc)


def test_open_opens_the_device_at_given_index(monkeypatch):
    captured_index = None
    fake = FakeVideoCapture([make_bgr_frame()])

    def fake_video_capture(index):
        nonlocal captured_index
        captured_index = index
        return fake

    monkeypatch.setattr(cv2, "VideoCapture", fake_video_capture)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=2)

    source.open()

    assert captured_index == 2


def test_open_raises_frame_source_error_when_device_not_opened(monkeypatch):
    fake = FakeVideoCapture([], opened=False)
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)

    with pytest.raises(FrameSourceError) as raised:
        source.open()
    assert fake.released  # 실패한 핸들도 반드시 해제해야 한다
    assert raised.value.observation.state is ObservationState.UNKNOWN
    assert (
        raised.value.observation.reason
        is ObservationReason.CAMERA_UNAVAILABLE
    )


def test_open_is_idempotent(monkeypatch):
    open_calls = []

    def fake_video_capture(index):
        open_calls.append(index)
        return FakeVideoCapture([make_bgr_frame()])

    monkeypatch.setattr(cv2, "VideoCapture", fake_video_capture)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)

    source.open()
    source.open()

    assert len(open_calls) == 1


def test_requested_resolution_is_applied_via_set(monkeypatch):
    fake = FakeVideoCapture([make_bgr_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0, width=1280, height=720)

    source.open()

    assert (cv2.CAP_PROP_FRAME_WIDTH, 1280) in fake.set_calls
    assert (cv2.CAP_PROP_FRAME_HEIGHT, 720) in fake.set_calls


def test_requested_capture_mode_is_applied_before_resolution(monkeypatch):
    fake = FakeVideoCapture([make_bgr_frame(width=1280, height=720)])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(
        camera_id="cam-1",
        camera_index=0,
        width=1280,
        height=720,
        fourcc="mjpg",
        fps=30.0,
    )

    source.open()

    assert source.fourcc == "MJPG"
    assert fake.set_calls == [
        (cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG")),
        (cv2.CAP_PROP_FRAME_WIDTH, 1280),
        (cv2.CAP_PROP_FRAME_HEIGHT, 720),
        (cv2.CAP_PROP_FPS, 30.0),
    ]


def test_zero_resolution_skips_set_calls(monkeypatch):
    """width/height 기본값(0)은 장치 기본 해상도를 그대로 쓰겠다는 뜻이다."""
    fake = FakeVideoCapture([make_bgr_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)

    source.open()

    assert fake.set_calls == []


def test_capture_returns_rgb_frame_with_actual_shape(monkeypatch):
    """width/height는 요청값이 아니라 실제 캡처된 프레임에서 계산돼야 한다 —
    장치가 요청 해상도를 그대로 못 맞출 수 있어서다."""
    fake = FakeVideoCapture([make_bgr_frame(width=64, height=48)])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-9", camera_index=0, width=9999, height=9999)
    source.open()

    frame = source.capture()

    assert frame.camera_id == "cam-9"
    assert frame.width == 64
    assert frame.height == 48
    assert frame.image.shape == (48, 64, 3)
    assert frame.image.dtype == np.uint8
    assert frame.performance_timing is not None
    assert frame.performance_timing.duration_ms("rawRead") is not None
    assert frame.performance_timing.duration_ms("colorConvert") is not None


def test_capture_uses_wall_clock_time(monkeypatch):
    fake = FakeVideoCapture([make_bgr_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)
    source.open()

    before = datetime.now(timezone.utc)
    frame = source.capture()
    after = datetime.now(timezone.utc)

    assert before <= frame.captured_at <= after


def test_frame_id_starts_at_one_and_increases(monkeypatch):
    fake = FakeVideoCapture([make_bgr_frame(), make_bgr_frame(), make_bgr_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)
    source.open()

    ids = [source.capture().frame_id for _ in range(3)]

    assert ids == [1, 2, 3]


def test_calibration_id_is_none_without_remap(monkeypatch):
    """이 소스는 보정을 하지 않으므로 calibration_id는 항상 None이다."""
    fake = FakeVideoCapture([make_bgr_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)
    source.open()

    frame = source.capture()

    assert frame.calibration_id is None


def test_capture_before_open_raises():
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)

    with pytest.raises(FrameSourceError) as raised:
        source.capture()

    assert raised.value.observation.reason is ObservationReason.PIPELINE_STALLED


def test_read_failure_raises_frame_source_error(monkeypatch):
    fake = FakeVideoCapture([])  # read()가 곧바로 실패
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)
    source.open()

    with pytest.raises(FrameSourceError) as raised:
        source.capture()

    assert raised.value.observation.reason is ObservationReason.CAMERA_UNAVAILABLE


def test_close_releases_the_device(monkeypatch):
    fake = FakeVideoCapture([make_bgr_frame()])
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)
    source.open()

    source.close()

    assert fake.released


def test_close_before_open_is_a_no_op():
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)

    source.close()  # 예외 없이 통과해야 한다

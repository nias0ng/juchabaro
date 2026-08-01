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

    with pytest.raises(FrameSourceError):
        source.open()
    assert fake.released  # 실패한 핸들도 반드시 해제해야 한다


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

    with pytest.raises(FrameSourceError):
        source.capture()


def test_read_failure_raises_frame_source_error(monkeypatch):
    fake = FakeVideoCapture([])  # read()가 곧바로 실패
    monkeypatch.setattr(cv2, "VideoCapture", lambda index: fake)
    source = OpenCvWebcamFrameSource(camera_id="cam-1", camera_index=0)
    source.open()

    with pytest.raises(FrameSourceError):
        source.capture()


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

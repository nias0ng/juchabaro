"""VideoFileFrameSource 계약 테스트 (T-04, ai/training/tests/test_replay_video_source.py에서 이관·확장).

핵심은 captured_at이 벽시계가 아니라 영상 시간이라는 것과, 새 CapturedFrame 계약
(camera_id/width/height/calibration_id)이 채워지는지다.
"""

from datetime import timedelta, timezone
from datetime import datetime as dt

import cv2
import numpy as np
import pytest
from src.camera.frame_source import EPOCH, EndOfVideo, FrameSourceError, VideoFileFrameSource


def write_video(path, frames=10, fps=30.0, width=64, height=48):
    """지정한 프레임 수의 합성 mp4를 만든다. i번째 프레임은 밝기 i*20으로 채운다."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    assert writer.isOpened(), "테스트용 mp4 인코더를 열 수 없습니다"
    for i in range(frames):
        writer.write(np.full((height, width, 3), (i * 20) % 256, dtype=np.uint8))
    writer.release()
    return path


def test_captured_at_follows_video_time(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=5, fps=30.0)
    source = VideoFileFrameSource(camera_id="cam-1", path=path)
    source.open()
    try:
        stamps = [source.capture().captured_at for _ in range(5)]
    finally:
        source.close()

    assert stamps == [EPOCH + timedelta(seconds=i / 30.0) for i in range(5)]


def test_t0_shifts_all_timestamps(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=3, fps=30.0)
    t0 = dt(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    source = VideoFileFrameSource(camera_id="cam-1", path=path, t0=t0)
    source.open()
    try:
        stamps = [source.capture().captured_at for _ in range(3)]
    finally:
        source.close()

    assert stamps == [t0 + timedelta(seconds=i / 30.0) for i in range(3)]


def test_frame_id_starts_at_one_and_increases(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=4)
    source = VideoFileFrameSource(camera_id="cam-1", path=path)
    source.open()
    try:
        ids = [source.capture().frame_id for _ in range(4)]
    finally:
        source.close()

    assert ids == [1, 2, 3, 4]


def test_raises_end_of_video_when_exhausted_and_stays_exhausted(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=2)
    source = VideoFileFrameSource(camera_id="cam-1", path=path)
    source.open()
    try:
        source.capture()
        source.capture()
        with pytest.raises(EndOfVideo):
            source.capture()
        with pytest.raises(EndOfVideo):
            source.capture()
    finally:
        source.close()


def test_image_is_rgb_uint8_with_video_shape(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=1, width=64, height=48)
    source = VideoFileFrameSource(camera_id="cam-1", path=path)
    source.open()
    try:
        image = source.capture().image
    finally:
        source.close()

    assert image.shape == (48, 64, 3)
    assert image.dtype == np.uint8


def test_start_and_end_seconds_slice_the_video(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=30, fps=30.0)
    source = VideoFileFrameSource(camera_id="cam-1", path=path, start_seconds=0.1, end_seconds=0.2)
    source.open()
    try:
        stamps = []
        while True:
            try:
                stamps.append(source.capture().captured_at)
            except EndOfVideo:
                break
    finally:
        source.close()

    # 0.1s(=3프레임)부터 0.2s(=6프레임) 직전까지 → 프레임 인덱스 3,4,5
    assert stamps == [EPOCH + timedelta(seconds=i / 30.0) for i in (3, 4, 5)]


def test_exposes_fps_size_and_duration(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=60, fps=30.0, width=64, height=48)
    source = VideoFileFrameSource(camera_id="cam-1", path=path)
    source.open()
    try:
        assert source.fps == 30.0
        assert source.frame_size == (64, 48)
        assert source.duration_seconds == pytest.approx(2.0)
    finally:
        source.close()


def test_missing_file_raises_frame_source_error(tmp_path):
    source = VideoFileFrameSource(camera_id="cam-1", path=tmp_path / "nope.mp4")
    with pytest.raises(FrameSourceError):
        source.open()


def test_capture_before_open_raises(tmp_path):
    path = write_video(tmp_path / "v.mp4", frames=1)
    source = VideoFileFrameSource(camera_id="cam-1", path=path)
    with pytest.raises(FrameSourceError):
        source.capture()


class TestNewCapturedFrameContract:
    """T-04: 새 CapturedFrame 계약(camera_id/width/height/calibration_id)이
    실제로 채워지는지 확인한다 — 옛 baseline판은 이 필드들이 아예 없었다."""

    def test_carries_camera_id(self, tmp_path):
        path = write_video(tmp_path / "v.mp4", frames=1)
        source = VideoFileFrameSource(camera_id="cam-7", path=path)
        source.open()
        try:
            frame = source.capture()
        finally:
            source.close()

        assert frame.camera_id == "cam-7"

    def test_carries_width_and_height(self, tmp_path):
        path = write_video(tmp_path / "v.mp4", frames=1, width=64, height=48)
        source = VideoFileFrameSource(camera_id="cam-1", path=path)
        source.open()
        try:
            frame = source.capture()
        finally:
            source.close()

        assert (frame.width, frame.height) == (64, 48)

    def test_calibration_id_is_none_without_remap(self, tmp_path):
        """이 소스는 보정을 하지 않으므로 calibration_id는 항상 None이다."""
        path = write_video(tmp_path / "v.mp4", frames=1)
        source = VideoFileFrameSource(camera_id="cam-1", path=path)
        source.open()
        try:
            frame = source.capture()
        finally:
            source.close()

        assert frame.calibration_id is None

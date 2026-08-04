"""CropFrameSource 회귀 테스트 (test_remap_frame_source.py와 같은 "알려진 기하" 검증 방식)."""

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from src.camera.frame_source import CropFrameSource, FrameSourceError
from src.domain.models import ObservationReason, ObservationState

FRAME_W, FRAME_H = 400, 300


class FakeFrameSource:
    """capture()마다 미리 준비된 이미지를 그대로 돌려주는 테스트용 FrameSource."""

    def __init__(self, image, camera_id="cam-1", calibration_id="cal-abc"):
        self.image = image
        self.camera_id = camera_id
        self.calibration_id = calibration_id
        self.opened = False
        self.closed = False
        self._next_frame_id = 1

    def open(self):
        self.opened = True

    def capture(self):
        frame = SimpleNamespace(
            camera_id=self.camera_id,
            frame_id=self._next_frame_id,
            captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            image=self.image,
            width=self.image.shape[1],
            height=self.image.shape[0],
            calibration_id=self.calibration_id,
        )
        self._next_frame_id += 1
        return frame

    def close(self):
        self.closed = True


def make_marker_image():
    """(10, 20)과 (390, 200)에 마커를 심은 이미지. crop 후 마커 위치로 slice 정확성을 검증한다."""
    image = np.zeros((FRAME_H, FRAME_W, 3), np.uint8)
    image[20, 10] = (255, 255, 255)   # 왼쪽 여백 근처 마커 (crop_left_px=15에 잘려야 함)
    image[200, 390] = (255, 255, 255)  # 오른쪽 여백 근처 마커 (작은 crop_right_px엔 살아남아야 함)
    return image


def test_no_op_when_crop_amounts_are_zero():
    image = make_marker_image()
    source = CropFrameSource(inner=FakeFrameSource(image), crop_left_px=0, crop_right_px=0)
    source.open()

    out = source.capture()

    assert out.width == FRAME_W
    np.testing.assert_array_equal(out.image, image)


def test_crops_left_margin_and_shifts_marker():
    image = make_marker_image()
    source = CropFrameSource(inner=FakeFrameSource(image), crop_left_px=15, crop_right_px=0)
    source.open()

    out = source.capture()

    assert out.width == FRAME_W - 15
    # 원본 (10, 20)의 마커는 crop 후 x=10-15<0이라 잘려 나가야 한다.
    assert not (out.image[20, :] == 255).any()
    # 원본 (390, 200)의 마커는 x=390-15=375로 이동해야 한다.
    assert tuple(out.image[200, 375]) == (255, 255, 255)


def test_crops_both_sides():
    image = make_marker_image()
    source = CropFrameSource(inner=FakeFrameSource(image), crop_left_px=15, crop_right_px=5)
    source.open()

    out = source.capture()

    assert out.width == FRAME_W - 15 - 5
    assert tuple(out.image[200, 375]) == (255, 255, 255)


def test_preserves_height_calibration_id_camera_id_and_timestamps():
    image = make_marker_image()
    source = CropFrameSource(
        inner=FakeFrameSource(image, camera_id="cam-9", calibration_id="cal-xyz"), crop_left_px=15
    )
    source.open()

    out = source.capture()

    assert out.height == FRAME_H
    assert out.calibration_id == "cal-xyz"
    assert out.camera_id == "cam-9"
    assert out.frame_id == 1
    assert out.captured_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_rejects_negative_crop_left_px():
    with pytest.raises(ValueError, match="crop_left_px"):
        CropFrameSource(inner=FakeFrameSource(make_marker_image()), crop_left_px=-1)


def test_rejects_negative_crop_right_px():
    with pytest.raises(ValueError, match="crop_right_px"):
        CropFrameSource(inner=FakeFrameSource(make_marker_image()), crop_right_px=-1)


def test_raises_frame_source_error_when_crop_exceeds_width():
    image = make_marker_image()
    source = CropFrameSource(inner=FakeFrameSource(image), crop_left_px=FRAME_W)
    source.open()

    with pytest.raises(FrameSourceError) as raised:
        source.capture()

    assert raised.value.observation.state is ObservationState.DEGRADED
    assert raised.value.observation.reason is ObservationReason.PARTIAL_FRAME


def test_delegates_open_and_close_to_inner_source():
    inner = FakeFrameSource(make_marker_image())
    source = CropFrameSource(inner=inner, crop_left_px=10)

    source.open()
    assert inner.opened
    source.capture()
    source.close()

    assert inner.closed

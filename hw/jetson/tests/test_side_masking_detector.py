"""SideMaskingDetector 단위 테스트 (537).

영상 파일이나 실제 YOLO 모델 없이, numpy 합성 배열과 fake `Detector`만으로
좌우 마스킹 decorator의 동작을 검증한다. crop이 아니므로 width/height와
delegate가 받는 `CapturedFrame`의 메타데이터가 그대로 유지되는지가 핵심이다.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from src.camera.models import CapturedFrame
from src.tracking.adapters.side_masking_detector import (
    DEFAULT_LEFT_MASK_END_RATIO,
    DEFAULT_RIGHT_MASK_START_RATIO,
    SideMaskingDetector,
    _mask_bounds_px,
)
from src.tracking.models import TrackerFrameResult
from src.tracking.protocols import ModelInfo, TrackingError


FILL_VALUE = 200  # 0이 아닌 값이어야 "마스킹으로 0이 됐다"를 의미 있게 검증할 수 있다.


class _FakeInnerDetector:
    """delegate가 실제로 받는 프레임을 기록하는 최소 fake Detector."""

    def __init__(self, *, result: TrackerFrameResult | None = None) -> None:
        self.received_frames: list[CapturedFrame] = []
        self.opened = False
        self.closed = False
        self._result = result or TrackerFrameResult(
            observations=(), all_detections_tracked=True
        )

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(
            library="fake",
            library_version="0",
            model_name="fake.pt",
            tracker_config="fake.yaml",
        )

    def open(self) -> None:
        self.opened = True

    def track(self, frame: CapturedFrame) -> TrackerFrameResult:
        self.received_frames.append(frame)
        return self._result

    def close(self) -> None:
        self.closed = True


def _make_frame(
    image,
    *,
    camera_id: str = "cam-9",
    frame_id: int = 42,
    width: int,
    height: int,
    calibration_id: str | None = "cal-x",
) -> CapturedFrame:
    return CapturedFrame(
        camera_id=camera_id,
        frame_id=frame_id,
        captured_at=datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc),
        image=image,
        width=width,
        height=height,
        calibration_id=calibration_id,
    )


def _filled_image(*, width: int, height: int = 4) -> np.ndarray:
    return np.full((height, width, 3), FILL_VALUE, dtype=np.uint8)


# ---------------------------------------------------------------------------
# 반올림 정책
# ---------------------------------------------------------------------------


def test_mask_bounds_px_matches_1920_width_worked_example():
    left_end_px, right_start_px = _mask_bounds_px(
        1920, DEFAULT_LEFT_MASK_END_RATIO, DEFAULT_RIGHT_MASK_START_RATIO
    )

    assert (left_end_px, right_start_px) == (346, 1551)


def test_mask_bounds_px_scales_with_a_non_1920_width():
    # 100px 폭 기준: 0.180*100=18.0 -> 18, 0.808*100=80.8 -> 81
    left_end_px, right_start_px = _mask_bounds_px(100, 0.180, 0.808)

    assert (left_end_px, right_start_px) == (18, 81)


# ---------------------------------------------------------------------------
# 마스킹 동작: 좌우 0, 가운데 원본 유지, 원본 배열 불변
# ---------------------------------------------------------------------------


def test_left_and_right_regions_become_black_at_1920_width():
    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    original = _filled_image(width=1920)
    frame = _make_frame(original, width=1920, height=original.shape[0])

    detector.track(frame)

    masked = inner.received_frames[0].image
    assert np.all(masked[:, :346] == 0)
    assert np.all(masked[:, 1551:] == 0)


def test_visible_center_region_is_byte_identical_to_original():
    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    original = _filled_image(width=1920)
    frame = _make_frame(original, width=1920, height=original.shape[0])

    detector.track(frame)

    masked = inner.received_frames[0].image
    assert np.array_equal(masked[:, 346:1551], original[:, 346:1551])


def test_original_input_array_is_not_mutated():
    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    original = _filled_image(width=1920)
    untouched_copy = original.copy()
    frame = _make_frame(original, width=1920, height=original.shape[0])

    detector.track(frame)

    assert np.array_equal(original, untouched_copy)


def test_non_1920_width_masks_by_normalized_ratio():
    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    original = _filled_image(width=100)
    frame = _make_frame(original, width=100, height=original.shape[0])

    detector.track(frame)

    masked = inner.received_frames[0].image
    assert np.all(masked[:, :18] == 0)
    assert np.all(masked[:, 81:] == 0)
    assert np.array_equal(masked[:, 18:81], original[:, 18:81])


# ---------------------------------------------------------------------------
# 메타데이터·delegate 위임
# ---------------------------------------------------------------------------


def test_delegate_frame_preserves_metadata_but_replaces_image():
    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    original = _filled_image(width=1920)
    frame = _make_frame(
        original,
        camera_id="cam-9",
        frame_id=42,
        width=1920,
        height=original.shape[0],
        calibration_id="cal-x",
    )

    detector.track(frame)

    received = inner.received_frames[0]
    assert received.camera_id == frame.camera_id
    assert received.frame_id == frame.frame_id
    assert received.captured_at == frame.captured_at
    assert received.width == frame.width
    assert received.height == frame.height
    assert received.calibration_id == frame.calibration_id
    assert received.image is not original  # 복사본이어야 한다


def test_track_returns_inner_result_unchanged():
    expected_result = TrackerFrameResult(observations=(), all_detections_tracked=False)
    inner = _FakeInnerDetector(result=expected_result)
    detector = SideMaskingDetector(inner=inner)
    frame = _make_frame(_filled_image(width=1920), width=1920, height=4)

    result = detector.track(frame)

    assert result is expected_result


def test_model_info_open_close_delegate_exactly_to_inner():
    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)

    info = detector.model_info
    detector.open()
    detector.close()

    assert info == inner.model_info
    assert inner.opened is True
    assert inner.closed is True


def test_raw_inner_detector_used_directly_is_unaffected_by_wrapper_existing():
    """decorator를 조립하지 않으면 raw detector는 원본 프레임을 그대로 받는다."""

    inner = _FakeInnerDetector()
    original = _filled_image(width=1920)
    frame = _make_frame(original, width=1920, height=original.shape[0])

    inner.track(frame)

    assert inner.received_frames[0].image is original
    assert np.all(inner.received_frames[0].image[:, :346] == FILL_VALUE)


# ---------------------------------------------------------------------------
# 생성자 검증: fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "left_mask_end_ratio,right_mask_start_ratio",
    [
        (-0.01, 0.808),  # left < 0
        (0.180, 1.01),  # right > 1
        (0.5, 0.5),  # left == right
        (0.9, 0.1),  # left >= right
        (float("nan"), 0.808),
        (0.180, float("nan")),
        (float("inf"), 0.808),
        (0.180, float("-inf")),
    ],
)
def test_rejects_invalid_mask_ratios(left_mask_end_ratio, right_mask_start_ratio):
    with pytest.raises(ValueError):
        SideMaskingDetector(
            inner=_FakeInnerDetector(),
            left_mask_end_ratio=left_mask_end_ratio,
            right_mask_start_ratio=right_mask_start_ratio,
        )


# ---------------------------------------------------------------------------
# 프레임 입력 검증: fail-closed
# ---------------------------------------------------------------------------


class _ShapelessImage:
    """`.shape`이 없는 최소 스텁 — 이미지가 아닌 값이 들어온 경우를 흉내낸다."""


def test_rejects_image_without_shape_attribute():
    detector = SideMaskingDetector(inner=_FakeInnerDetector())
    frame = _make_frame(_ShapelessImage(), width=100, height=100)

    with pytest.raises(TrackingError):
        detector.track(frame)


def test_rejects_two_dimensional_image_shape():
    detector = SideMaskingDetector(inner=_FakeInnerDetector())
    image = np.zeros((100, 100), dtype=np.uint8)  # 채널 차원 없음
    frame = _make_frame(image, width=100, height=100)

    with pytest.raises(TrackingError):
        detector.track(frame)


def test_rejects_frame_metadata_that_does_not_match_image_shape():
    detector = SideMaskingDetector(inner=_FakeInnerDetector())
    image = _filled_image(width=120, height=80)
    frame = _make_frame(image, width=100, height=100)

    with pytest.raises(TrackingError, match="metadata"):
        detector.track(frame)


def test_rejects_zero_sized_frame():
    detector = SideMaskingDetector(inner=_FakeInnerDetector())

    class _ZeroImage:
        shape = (0, 0, 3)

    frame = _make_frame(_ZeroImage(), width=100, height=100)

    with pytest.raises(TrackingError):
        detector.track(frame)

"""SideMaskingDetector 단위 테스트 (537).

영상 파일이나 실제 YOLO 모델 없이, numpy 합성 배열과 fake `Detector`만으로
좌우 마스킹 decorator의 동작을 검증한다. crop이 아니므로 width/height와
delegate가 받는 `CapturedFrame`의 메타데이터가 그대로 유지되는지가 핵심이다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from src.camera.models import CapturedFrame
from src.parking.zone_registry import ZoneRegistry
from src.tracking.adapters.side_masking_detector import (
    DEFAULT_LEFT_MASK_END_RATIO,
    DEFAULT_MASK_MARGIN_RATIO,
    DEFAULT_RIGHT_MASK_START_RATIO,
    SideMaskingDetector,
    _mask_bounds_px,
    compute_mask_ratios_from_zones,
)
from src.tracking.models import TrackerFrameResult
from src.tracking.protocols import ModelInfo, TrackingError


FILL_VALUE = 200  # 0이 아닌 값이어야 "마스킹으로 0이 됐다"를 의미 있게 검증할 수 있다.

# hw/jetson/tests/test_side_masking_detector.py -> hw/jetson/config/zone_definition.json
_REAL_ZONE_DEFINITION_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "zone_definition.json"
)


class _FakeZone:
    """`compute_mask_ratios_from_zones`가 요구하는 `.polygon` 속성만 흉내내는 stub."""

    def __init__(self, polygon) -> None:
        self.polygon = polygon


class _FakeInnerDetector:
    """delegate가 실제로 받는 프레임을 기록하는 최소 fake Detector."""

    def __init__(self, *, result: TrackerFrameResult | None = None) -> None:
        self.received_frames: list[CapturedFrame] = []
        self.warm_up_frames: list[CapturedFrame] = []
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

    def warm_up(self, frame: CapturedFrame) -> None:
        self.warm_up_frames.append(frame)

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


def test_default_mask_bounds_stay_outside_real_zone_definition_polygon_extent():
    """`compute_mask_ratios_from_zones`가 실제 `zone_definition.json` +
    `DEFAULT_MASK_MARGIN_RATIO`로 계산한 경계가 실제 polygon x좌표 범위를
    침범하지 않는지 회귀 가드로 고정한다.

    이전에는 `DEFAULT_LEFT_MASK_END_RATIO`/`DEFAULT_RIGHT_MASK_START_RATIO`
    하드코딩 상수를 직접 pin했다. 이제 최종 경계는 항상 zone 파일에서 자동
    계산되므로, 이 테스트는 "계산된 값이 실제 zone을 침범하지 않는가"만
    검증한다 — 계산 산수 자체는 별도 순수 단위 테스트로 분리한다. 이후 구역
    추가·재-crop·calibration 변경으로 실제 polygon이 이 경계를 넘으면, 아무
    예외·로그 없이 YOLO 입력에서 진짜 주차면 픽셀이 검정으로 지워진다 — 이
    저장소가 반복 겪은 "stale hardcoded wire constant" 실패 패턴이다. 이
    테스트는 그 이탈을 실패로 드러낸다.
    """

    registry = ZoneRegistry.from_file(_REAL_ZONE_DEFINITION_PATH)
    x_coordinates = [
        point[0] for zone in registry.all() for point in zone.polygon
    ]
    min_x, max_x = min(x_coordinates), max(x_coordinates)

    left_ratio, right_ratio = compute_mask_ratios_from_zones(
        registry.all(), margin_ratio=DEFAULT_MASK_MARGIN_RATIO
    )

    assert left_ratio <= min_x, (
        "왼쪽 마스크가 실제 zone polygon을 침범합니다: "
        f"left_ratio={left_ratio}, min_x={min_x}"
    )
    assert right_ratio >= max_x, (
        "오른쪽 마스크가 실제 zone polygon을 침범합니다: "
        f"right_ratio={right_ratio}, max_x={max_x}"
    )


# ---------------------------------------------------------------------------
# compute_mask_ratios_from_zones: 순수 산수 + fail-closed 검증
# ---------------------------------------------------------------------------


def test_compute_mask_ratios_from_zones_matches_known_synthetic_polygon_arithmetic():
    zones = [
        _FakeZone([(0.30, 0.0), (0.60, 0.0), (0.60, 1.0), (0.30, 1.0)]),
        _FakeZone([(0.25, 0.2), (0.70, 0.2), (0.70, 0.8), (0.25, 0.8)]),
    ]

    left_ratio, right_ratio = compute_mask_ratios_from_zones(zones, margin_ratio=0.05)

    # min_x=0.25, max_x=0.70 -> (0.25-0.05, 0.70+0.05)
    assert left_ratio == pytest.approx(0.20, abs=1e-9)
    assert right_ratio == pytest.approx(0.75, abs=1e-9)


def test_compute_mask_ratios_from_zones_with_zero_margin_returns_exact_extent():
    zones = [_FakeZone([(0.4, 0.0), (0.9, 0.0), (0.9, 1.0), (0.4, 1.0)])]

    left_ratio, right_ratio = compute_mask_ratios_from_zones(zones, margin_ratio=0.0)

    assert (left_ratio, right_ratio) == pytest.approx((0.4, 0.9))


@pytest.mark.parametrize(
    "margin_ratio",
    [-0.01, -1.0, float("nan"), float("inf"), float("-inf")],
)
def test_compute_mask_ratios_from_zones_rejects_invalid_margin(margin_ratio):
    zones = [_FakeZone([(0.2, 0.0), (0.8, 0.0), (0.8, 1.0), (0.2, 1.0)])]

    with pytest.raises(ValueError):
        compute_mask_ratios_from_zones(zones, margin_ratio=margin_ratio)


def test_compute_mask_ratios_from_zones_rejects_empty_zones():
    with pytest.raises(ValueError):
        compute_mask_ratios_from_zones([], margin_ratio=0.04)


def test_compute_mask_ratios_from_zones_rejects_zones_with_no_polygon_points():
    with pytest.raises(ValueError):
        compute_mask_ratios_from_zones([_FakeZone([])], margin_ratio=0.04)


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


def test_warm_up_uses_the_same_masked_input_without_tracking():
    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    original = _filled_image(width=100)
    frame = _make_frame(original, width=100, height=original.shape[0])

    detector.warm_up(frame)

    assert inner.received_frames == []
    assert len(inner.warm_up_frames) == 1
    warmed_image = inner.warm_up_frames[0].image
    assert np.all(warmed_image[:, :18] == 0)
    assert np.all(warmed_image[:, 81:] == 0)
    assert np.all(warmed_image[:, 18:81] == FILL_VALUE)


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


# ---------------------------------------------------------------------------
# 내부 마스크 버퍼 재사용 (537 코드리뷰 반영: 프레임마다 새 배열 할당 금지)
# ---------------------------------------------------------------------------


def test_same_size_and_dtype_frames_reuse_the_same_delegate_buffer():
    """같은 크기/dtype 프레임으로 두 번 연속 호출하면 delegate가 받는 두
    `CapturedFrame.image`가 같은 객체여야 한다 — 버퍼가 실제로 재사용된다는
    증거."""

    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    first = _filled_image(width=1920)
    second = _filled_image(width=1920)

    detector.track(_make_frame(first, width=1920, height=first.shape[0]))
    detector.track(_make_frame(second, width=1920, height=second.shape[0]))

    assert len(inner.received_frames) == 2
    first_received = inner.received_frames[0].image
    second_received = inner.received_frames[1].image
    assert first_received is second_received


def test_resized_frame_triggers_reallocation_and_still_masks_correctly():
    """첫 호출과 크기가 다른 프레임으로 두 번째 호출하면 새 버퍼가 할당되고,
    결과는 여전히 새 크기 기준으로 올바르게 마스킹돼야 한다(`RemapFrameSource`의
    재할당 케이스와 같은 발상)."""

    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    first = _filled_image(width=1920)
    second = _filled_image(width=100)

    detector.track(_make_frame(first, width=1920, height=first.shape[0]))
    detector.track(_make_frame(second, width=100, height=second.shape[0]))

    second_received = inner.received_frames[1].image
    assert second_received.shape == second.shape
    assert np.all(second_received[:, :18] == 0)
    assert np.all(second_received[:, 81:] == 0)
    assert np.array_equal(second_received[:, 18:81], second[:, 18:81])


def test_dtype_change_triggers_reallocation():
    """크기는 같지만 dtype이 다른 프레임으로 두 번째 호출하면 새 버퍼가
    할당돼야 한다(같은 shape이라도 dtype이 다르면 버퍼를 재사용할 수 없다)."""

    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    first = _filled_image(width=1920)
    second = np.full((4, 1920, 3), FILL_VALUE, dtype=np.int16)

    detector.track(_make_frame(first, width=1920, height=first.shape[0]))
    detector.track(_make_frame(second, width=1920, height=second.shape[0]))

    second_received = inner.received_frames[1].image
    assert second_received.dtype == np.int16
    assert np.all(second_received[:, :346] == 0)
    assert np.all(second_received[:, 1551:] == 0)


def test_second_call_result_is_not_contaminated_by_first_calls_residual_data():
    """두 번째 호출의 마스킹 결과가 첫 번째 호출의 잔여 데이터에 오염되지
    않고, 두 번째 프레임의 가시 영역 내용만 반영해야 한다 — 버퍼 전체를 매
    프레임 다시 채워 넣는다는 증거."""

    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    first_value = 111
    second_value = 222
    first = np.full((4, 1920, 3), first_value, dtype=np.uint8)
    second = np.full((4, 1920, 3), second_value, dtype=np.uint8)

    detector.track(_make_frame(first, width=1920, height=first.shape[0]))
    detector.track(_make_frame(second, width=1920, height=second.shape[0]))

    second_received = inner.received_frames[1].image
    assert np.all(second_received[:, 346:1551] == second_value)
    assert not np.any(second_received[:, 346:1551] == first_value)


def test_original_input_arrays_are_not_mutated_across_repeated_calls():
    """버퍼 재사용 구현에서도 원본 배열은 여전히 in-place로 수정되지 않아야
    한다 — 원본과 버퍼는 서로 다른 객체다."""

    inner = _FakeInnerDetector()
    detector = SideMaskingDetector(inner=inner)
    first = _filled_image(width=1920)
    first_copy = first.copy()
    second = _filled_image(width=1920)
    second_copy = second.copy()

    detector.track(_make_frame(first, width=1920, height=first.shape[0]))
    detector.track(_make_frame(second, width=1920, height=second.shape[0]))

    assert np.array_equal(first, first_copy)
    assert np.array_equal(second, second_copy)

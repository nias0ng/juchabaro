"""YOLO delegate 입력 복사본의 좌우 바깥 영역만 검정으로 마스킹하는 decorator.

왜곡 보정된 full-frame의 크기와 좌표계를 그대로 유지하면서, `Detector.track()`이
하류 YOLO/ByteTrack에 넘기는 프레임 복사본만 좌우 바깥(주차면·통로 밖) 영역을
검정으로 칠한다. crop이 아니다 — width/height, bbox·zone polygon의 정규화
좌표계, calibration_id는 전혀 바뀌지 않는다.

`UltralyticsVehicleTracker`는 pilot v6 crop 리플레이 등 좌표계가 다른 경로에서도
재사용되므로, 마스킹은 그 내부가 아니라 여기서 선택적으로 조립하는 decorator로
구현한다(537 인수인계 §6).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Iterable

import numpy as np

from src.camera.models import CapturedFrame
from src.tracking.models import TrackerFrameResult
from src.tracking.protocols import Detector, ModelInfo, TrackingError


# zone_definition.json version 2의 1~9번 전체 polygon x좌표 합집합은 [0.220, 0.768]이다.
# AISLE만 기준으로 하면 좌우 주차면을 침범하므로 전체 구역 기준 고정 경계에 여백
# 0.040을 더한 값을 기본값으로 쓴다(537 인수인계 §5).
DEFAULT_LEFT_MASK_END_RATIO = 0.180
DEFAULT_RIGHT_MASK_START_RATIO = 0.808

# `compute_mask_ratios_from_zones`가 실제 zone polygon x-범위에 더하는 기본 여백
# 비율. 위 DEFAULT_LEFT_MASK_END_RATIO/DEFAULT_RIGHT_MASK_START_RATIO를 낳은 여백
# 0.040(537 인수인계 §5)과 같은 값이다 — 배포/검증 환경에서 이 여백만 조정할 수
# 있게 하고, 최종 경계는 항상 실제 zone 파일에서 자동 계산한다(537 코드리뷰 반영).
DEFAULT_MASK_MARGIN_RATIO = 0.04

# 마스킹 색상은 RGB (0, 0, 0)이다. 채널 수와 무관하게 broadcast로 채워지므로
# 스칼라 0 하나로 충분하다.
_MASK_COLOR = 0


def _mask_bounds_px(width: int, left_mask_end_ratio: float, right_mask_start_ratio: float) -> tuple[int, int]:
    """정규화 비율과 실제 폭에서 좌우 마스크 경계 픽셀을 고정 반올림 정책으로 계산한다.

    반올림 정책은 `round()`(가장 가까운 정수, 동률은 banker's rounding) 하나로
    고정한다. 1920px 폭 기준 0.180 -> 346, 0.808 -> 1551이며, 이는 537 인수인계
    §5가 명시한 예시와 일치한다.
    """

    left_end_px = round(width * left_mask_end_ratio)
    right_start_px = round(width * right_mask_start_ratio)
    return left_end_px, right_start_px


def compute_mask_ratios_from_zones(
    zones: Iterable[Any],
    *,
    margin_ratio: float,
) -> tuple[float, float]:
    """실제 zone polygon들의 x-범위에 여백을 더해 마스크 경계 비율을 계산한다.

    `zones`의 각 원소는 `(x, y)` 튜플들의 시퀀스인 `polygon` 속성을 가져야 한다
    (`src.parking.zone_registry.ZoneDefinition`이 실제 타입). 모든 zone의 모든
    polygon 점 x좌표의 union에서 min_x/max_x를 구해
    `(min_x - margin_ratio, max_x + margin_ratio)`를 반환한다.

    반환값이 `0.0 <= left < right <= 1.0`을 만족하는지는 이 함수가 검증하지
    않는다 — `SideMaskingDetector.__init__`이 이미 그 검증을 하므로 중복하지
    않는다.
    """

    if not math.isfinite(margin_ratio) or margin_ratio < 0.0:
        raise ValueError(
            f"margin_ratio는 유한하고 0 이상인 값이어야 합니다: margin_ratio={margin_ratio}"
        )
    x_coordinates = [point[0] for zone in zones for point in zone.polygon]
    if not x_coordinates:
        raise ValueError(
            "zone polygon 점이 하나도 없어 마스크 경계를 계산할 수 없습니다"
        )
    min_x, max_x = min(x_coordinates), max(x_coordinates)
    return min_x - margin_ratio, max_x + margin_ratio


class SideMaskingDetector:
    """`Detector`를 감싸 delegate에 넘기는 프레임 복사본의 좌우만 검정 마스킹한다.

    - 원본 `CapturedFrame.image`는 in-place로 수정하지 않는다.
    - `model_info`/`open()`/`close()`는 `inner`에 그대로 위임한다.
    - `track()`의 반환값은 `inner.track()`의 반환값을 그대로 돌려준다.
    - 프레임마다 새 배열을 할당하지 않고 내부 마스크 버퍼를 재사용한다(프레임
      크기·dtype이 바뀔 때만 재할당). 따라서 `inner`(delegate)는 `track()` 호출이
      끝난 뒤에도 넘겨받은 `CapturedFrame.image`를 참조로 들고 있으면 안 된다 —
      다음 호출에서 같은 버퍼가 덮어써진다. 실제 `UltralyticsVehicleTracker.track()`은
      `cv2.cvtColor`로 별도 배열을 즉시 만들어 그것만 YOLO에 넘기고 `frame.image`
      자체에 대한 참조를 내보내지 않으므로 이 계약을 만족한다.
    """

    def __init__(
        self,
        *,
        inner: Detector,
        left_mask_end_ratio: float = DEFAULT_LEFT_MASK_END_RATIO,
        right_mask_start_ratio: float = DEFAULT_RIGHT_MASK_START_RATIO,
    ) -> None:
        if not math.isfinite(left_mask_end_ratio) or not math.isfinite(right_mask_start_ratio):
            raise ValueError(
                "마스크 경계 비율은 유한한 값이어야 합니다: "
                f"left_mask_end_ratio={left_mask_end_ratio}, "
                f"right_mask_start_ratio={right_mask_start_ratio}"
            )
        if not (0.0 <= left_mask_end_ratio < right_mask_start_ratio <= 1.0):
            raise ValueError(
                "마스크 경계는 0.0 <= left_mask_end_ratio < right_mask_start_ratio <= 1.0을 "
                "만족해야 합니다: "
                f"left_mask_end_ratio={left_mask_end_ratio}, "
                f"right_mask_start_ratio={right_mask_start_ratio}"
            )
        self._inner = inner
        self._left_mask_end_ratio = left_mask_end_ratio
        self._right_mask_start_ratio = right_mask_start_ratio
        self._buffer: np.ndarray | None = None
        self._buffer_key: tuple[tuple[int, ...], Any] | None = None

    @property
    def model_info(self) -> ModelInfo:
        """`inner`의 모델 정보를 그대로 반환한다."""

        return self._inner.model_info

    def open(self) -> None:
        """`inner.open()`에 그대로 위임한다."""

        self._inner.open()

    def close(self) -> None:
        """`inner.close()`에 그대로 위임한다."""

        self._inner.close()

    def warm_up(self, frame: CapturedFrame) -> None:
        """운영 경로와 같은 마스킹 입력으로 ``inner``를 warm-up한다."""

        self._inner.warm_up(self._masked_frame(frame))

    def track(self, frame: CapturedFrame) -> TrackerFrameResult:
        """좌우만 검정 마스킹한 프레임 복사본을 `inner.track()`에 전달한다.

        입력 배열 검증·오류 변환 정책은 `UltralyticsVehicleTracker.track()`과
        맞춘다 — shape을 확인할 수 없거나 metadata와 실제 이미지 크기가 다르면
        `TrackingError`로 fail-closed 거부한다.
        """

        return self._inner.track(self._masked_frame(frame))

    def _masked_frame(self, frame: CapturedFrame) -> CapturedFrame:
        """검증된 입력을 재사용 buffer에 복사·마스킹해 delegate frame을 만든다."""

        image: Any = frame.image
        shape = getattr(image, "shape", None)
        if shape is None or len(shape) < 3:
            raise TrackingError(
                f"프레임 이미지가 (H, W, C) 형태가 아닙니다: shape={shape}"
            )
        image_height, image_width = int(shape[0]), int(shape[1])
        if image_height <= 0 or image_width <= 0:
            raise TrackingError(f"프레임 크기가 올바르지 않습니다: shape={shape}")
        if image_width != frame.width or image_height != frame.height:
            raise TrackingError(
                "frame metadata does not match image shape: "
                f"metadata={frame.width}x{frame.height}, "
                f"image={image_width}x{image_height}"
            )

        buffer_key = (tuple(shape), getattr(image, "dtype", None))
        if self._buffer is None or buffer_key != self._buffer_key:
            self._buffer = np.empty_like(image)
            self._buffer_key = buffer_key
        np.copyto(self._buffer, image)
        masked_image = self._buffer

        left_end_px, right_start_px = _mask_bounds_px(
            image_width,
            self._left_mask_end_ratio,
            self._right_mask_start_ratio,
        )
        if left_end_px > 0:
            masked_image[:, :left_end_px] = _MASK_COLOR
        if right_start_px < image_width:
            masked_image[:, right_start_px:] = _MASK_COLOR

        return replace(frame, image=masked_image)

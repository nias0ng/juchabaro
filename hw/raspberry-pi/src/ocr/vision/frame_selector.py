"""
촬영 burst의 프레임 품질을 평가하고 YOLO를 실행할 anchor를 선택한다.

파이프라인 위치:
    CapturedFrame burst → frame_selector → plate_detector

주요 기능:
    - 정책이 정한 앞쪽 후보를 축소해 선명도·대비·노출을 평가
    - 앞쪽 후보 중 품질이 좋은 프레임과 마지막 프레임 선택

담당하지 않는 기능:
    - 번호판 영역 검출
    - 번호판 crop 자체의 품질 판정
    - 원근 보정과 OCR 추론

품질 점수는 앞쪽 anchor 선택에만 사용하는 내부 계산값이다.
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np

from ..errors import OcrComponentError
from ..policy import OcrPipelinePolicy
from ..types import AnchorSelection, CapturedFrame


# [예외]


class FrameSelectionError(OcrComponentError, RuntimeError):
    """OpenCV 품질 평가를 실행할 수 없는 경우."""


# [프레임 품질 계산]


# 실제 Raspberry Pi burst 데이터로 재조정해야 하는 잠정 운영값이다.
_ANALYSIS_WIDTH = 320
_DARK_THRESHOLD = 32
_BRIGHT_THRESHOLD = 224
_SHARPNESS_REFERENCE = 500.0
_CONTRAST_REFERENCE = 64.0
_SHARPNESS_WEIGHT = 0.60
_CONTRAST_WEIGHT = 0.15
_BRIGHTNESS_WEIGHT = 0.10
_CLIPPING_WEIGHT = 0.15
_QUALITY_WEIGHT_SUM = (
    _SHARPNESS_WEIGHT
    + _CONTRAST_WEIGHT
    + _BRIGHTNESS_WEIGHT
    + _CLIPPING_WEIGHT
)


def _score_frame(frame: CapturedFrame) -> float:
    """앞쪽 anchor 후보 한 장의 0~1 종합 품질 점수를 계산한다."""

    image = frame.image
    height, width = image.shape[:2]
    # 품질 평가가 원본보다 비싸지지 않도록 작은 이미지는 확대하지 않는다.
    analysis_width = min(width, _ANALYSIS_WIDTH)
    scale = analysis_width / width
    analysis_height = max(1, round(height * scale))

    if scale < 1.0:
        resized = cv2.resize(
            image,
            (analysis_width, analysis_height),
            interpolation=cv2.INTER_AREA,
        )
    else:
        resized = image
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    contrast = float(gray.std())
    mean_brightness = float(gray.mean())
    dark_ratio = float(np.mean(gray <= _DARK_THRESHOLD))
    bright_ratio = float(np.mean(gray >= _BRIGHT_THRESHOLD))

    # 기준값 이상에서 완전히 포화시키지 않는 비선형 정규화로
    # 유난히 선명한 한 프레임이 다른 노출 지표를 압도하지 않게 한다.
    sharpness_score = sharpness / (
        sharpness + _SHARPNESS_REFERENCE
    )
    contrast_score = contrast / (
        contrast + _CONTRAST_REFERENCE
    )
    brightness_score = max(
        0.0,
        1.0 - abs(mean_brightness - 127.5) / 127.5,
    )
    clipping_score = max(
        0.0,
        1.0 - min(1.0, dark_ratio + bright_ratio),
    )

    score = (
        _SHARPNESS_WEIGHT * sharpness_score
        + _CONTRAST_WEIGHT * contrast_score
        + _BRIGHTNESS_WEIGHT * brightness_score
        + _CLIPPING_WEIGHT * clipping_score
    ) / _QUALITY_WEIGHT_SUM
    return float(min(1.0, max(0.0, score)))


# [Anchor 선택]


class QualityFrameSelector:
    """
    품질 평가 결과와 촬영 순서를 함께 사용해 YOLO anchor 두 장을 고른다.

    정책이 정한 앞쪽 후보에서 earlier anchor를 선택하고 마지막 프레임을
    later anchor로 사용해 두 anchor 사이를 보간할 수 있게 한다.

    입력:
        pipeline 진입 검증을 통과한 BGR uint8 CapturedFrame 시퀀스.

    출력:
        앞쪽 품질 우수 프레임과 마지막 프레임의 인덱스.

    입력 계약은 pipeline 경계에서 한 번 검증하며 여기서 반복하지 않는다.
    """

    def __init__(
        self,
        *,
        policy: OcrPipelinePolicy | None = None,
    ) -> None:
        self._policy = policy or OcrPipelinePolicy()

    def select_anchors(
        self,
        frames: Sequence[CapturedFrame],
    ) -> AnchorSelection:
        """
        앞쪽 후보 중 고품질 프레임과 마지막 프레임을 anchor로 선택한다.

        입력:
            정책의 frame_count와 일치하는 시간순 프레임.

        출력:
            earlier/later anchor 인덱스.

        실패:
            OpenCV 품질 평가가 실패하면 원인을 보존한
            FrameSelectionError가 발생한다.
        """

        early_frames = frames[
            : self._policy.early_anchor_candidate_count
        ]
        # 동점이면 정지선에 조금 더 가까울 가능성이 있는 뒤 프레임을 쓴다.
        try:
            earlier = max(
                early_frames,
                key=lambda frame: (
                    _score_frame(frame),
                    frame.frame_index,
                ),
            )
        except cv2.error as exc:
            raise FrameSelectionError(
                "OpenCV 프레임 품질 평가에 실패했습니다."
            ) from exc

        return AnchorSelection(
            earlier_frame_index=earlier.frame_index,
            later_frame_index=self._policy.frame_count - 1,
        )

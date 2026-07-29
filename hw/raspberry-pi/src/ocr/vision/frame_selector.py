"""
촬영 burst의 프레임 품질을 평가하고 YOLO를 실행할 anchor를 선택한다.

파이프라인 위치:
    CapturedFrame 6장 → frame_selector → plate_detector

주요 기능:
    - 필요할 때 전체 프레임을 축소해 선명도·대비·노출을 저비용으로 평가
    - 앞쪽 F1~F2 중 품질이 좋은 프레임과 마지막 F6을 anchor로 선택

담당하지 않는 기능:
    - 번호판 영역 검출
    - 번호판 crop 자체의 품질 판정
    - 원근 보정과 OCR 추론
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import cv2
import numpy as np

from ..types import CapturedFrame, FrameQuality, AnchorSelection


# [입력 계약과 예외]


EXPECTED_FRAME_COUNT = 6
EXPECTED_FRAME_INDICES = tuple(range(EXPECTED_FRAME_COUNT))


class FrameSelectionError(ValueError):
    """촬영 burst가 프레임 선택 입력 계약을 만족하지 않는 경우."""


def _validated_frames(
    frames: Sequence[CapturedFrame],
) -> tuple[CapturedFrame, ...]:
    """
    프레임 수·시간순 인덱스·이미지 형식을 검사한다.

    입력:
        촬영 시간순으로 정렬된 CapturedFrame 시퀀스.

    출력:
        길이가 6으로 고정된 tuple.

    실패:
        인덱스가 0~5 순서가 아니거나 이미지가 비어 있는
        BGR uint8 HxWx3 형식이 아니면 FrameSelectionError가 발생한다.
    """

    validated = tuple(frames)

    if len(validated) != EXPECTED_FRAME_COUNT:
        raise FrameSelectionError(
            f"프레임은 정확히 {EXPECTED_FRAME_COUNT}장이어야 합니다: "
            f"actual={len(validated)}"
        )

    if any(
        not isinstance(frame, CapturedFrame)
        for frame in validated
    ):
        raise FrameSelectionError(
            "frames의 모든 항목은 CapturedFrame이어야 합니다."
        )

    if any(
        isinstance(frame.frame_index, bool)
        or not isinstance(frame.frame_index, int)
        for frame in validated
    ):
        raise FrameSelectionError(
            "frame_index는 bool이 아닌 정수여야 합니다."
        )

    indices = tuple(frame.frame_index for frame in validated)
    if indices != EXPECTED_FRAME_INDICES:
        raise FrameSelectionError(
            "프레임은 촬영 시간순이며 frame_index가 0~5여야 합니다: "
            f"actual={indices}"
        )

    for frame in validated:
        image = frame.image
        if (
            not isinstance(image, np.ndarray)
            or image.dtype != np.uint8
            or image.ndim != 3
            or image.shape[2] != 3
            or image.shape[0] <= 0
            or image.shape[1] <= 0
        ):
            raise FrameSelectionError(
                "프레임 이미지는 비어 있지 않은 BGR uint8 HxWx3 "
                f"배열이어야 합니다: frame_index={frame.frame_index}"
            )

    return validated


# [품질 측정 설정]


@dataclass(frozen=True, slots=True)
class QualityWeights:
    """
    프레임 종합 품질 점수를 계산할 때 사용하는 지표별 가중치.

    현재 기본값은 초기 운영값이다. 전체 프레임의 품질은 번호판 crop
    품질의 근사치이므로 실제 Raspberry Pi burst 데이터로 재조정해야 한다.

    입력:
        각 지표에 적용할 0 이상의 유한한 가중치.

    실패:
        음수·NaN·Inf가 있거나 모든 가중치가 0이면 ValueError가 발생한다.
    """

    sharpness: float = 0.60
    contrast: float = 0.15
    brightness: float = 0.10
    clipping: float = 0.15

    def __post_init__(self) -> None:
        values = (
            self.sharpness,
            self.contrast,
            self.brightness,
            self.clipping,
        )
        if not all(math.isfinite(value) and value >= 0.0 for value in values):
            raise ValueError("품질 가중치는 0 이상의 유한한 값이어야 합니다.")
        if sum(values) <= 0.0:
            raise ValueError("품질 가중치 중 하나 이상은 0보다 커야 합니다.")


# [프레임 품질 계산]


class OpenCvFrameQualityEvaluator:
    """
    OpenCV 지표로 촬영 프레임 전체의 상대적 품질을 계산한다.

    프레임 크기에 따른 Laplacian 값의 차이를 줄이기 위해 큰 이미지를
    같은 최대 분석 너비로 축소한다. 종합 점수는 0~1 범위이며, 높을수록
    anchor로 사용하기 좋은 프레임을 뜻한다.

    입력:
        BGR uint8 HxWx3 형식의 CapturedFrame 6장.

    출력:
        입력 순서를 유지한 FrameQuality 6개.

    실패:
        프레임 계약이 잘못되면 FrameSelectionError가 발생한다.
        설정값이 유효하지 않으면 ValueError가 발생한다.
    """

    def __init__(
        self,
        weights: QualityWeights | None = None,
        *,
        analysis_width: int = 320,
        dark_threshold: int = 32,
        bright_threshold: int = 224,
        sharpness_reference: float = 500.0,
        contrast_reference: float = 64.0,
    ) -> None:
        if analysis_width <= 0:
            raise ValueError("analysis_width는 0보다 커야 합니다.")
        if not 0 <= dark_threshold < bright_threshold <= 255:
            raise ValueError(
                "밝기 임계값은 0 <= dark < bright <= 255여야 합니다."
            )
        if (
            not math.isfinite(sharpness_reference)
            or sharpness_reference <= 0.0
            or not math.isfinite(contrast_reference)
            or contrast_reference <= 0.0
        ):
            raise ValueError("품질 정규화 기준값은 0보다 큰 유한한 값이어야 합니다.")

        self._weights = weights or QualityWeights()
        self._analysis_width = analysis_width
        self._dark_threshold = dark_threshold
        self._bright_threshold = bright_threshold
        self._sharpness_reference = sharpness_reference
        self._contrast_reference = contrast_reference

    def evaluate(
        self,
        frames: Sequence[CapturedFrame],
    ) -> tuple[FrameQuality, ...]:
        """
        여섯 프레임의 선명도·대비·밝기·clipping 비율을 계산한다.

        입력:
            촬영 시간순이며 frame_index가 0~5인 프레임 6장.

        출력:
            각 지표의 원시값과 0~1 종합 점수를 담은 FrameQuality tuple.

        실패:
            입력 프레임 계약이 잘못되면 FrameSelectionError가 발생한다.
        """

        validated = _validated_frames(frames)
        return tuple(self._evaluate_one(frame) for frame in validated)

    def _evaluate_one(self, frame: CapturedFrame) -> FrameQuality:
        """한 프레임을 공통 크기로 바꾼 뒤 품질 지표를 계산한다."""

        image = frame.image
        height, width = image.shape[:2]
        # 품질 평가가 원본보다 비싸지지 않도록 작은 이미지는 확대하지 않는다.
        analysis_width = min(width, self._analysis_width)
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
        dark_ratio = float(np.mean(gray <= self._dark_threshold))
        bright_ratio = float(np.mean(gray >= self._bright_threshold))

        # 기준값 이상에서 완전히 포화시키지 않는 비선형 정규화로
        # 유난히 선명한 한 프레임이 다른 노출 지표를 압도하지 않게 한다.
        sharpness_score = sharpness / (
            sharpness + self._sharpness_reference
        )
        contrast_score = contrast / (
            contrast + self._contrast_reference
        )
        brightness_score = max(
            0.0,
            1.0 - abs(mean_brightness - 127.5) / 127.5,
        )
        clipping_score = max(
            0.0,
            1.0 - min(1.0, dark_ratio + bright_ratio),
        )

        weight_sum = (
            self._weights.sharpness
            + self._weights.contrast
            + self._weights.brightness
            + self._weights.clipping
        )
        score = (
            self._weights.sharpness * sharpness_score
            + self._weights.contrast * contrast_score
            + self._weights.brightness * brightness_score
            + self._weights.clipping * clipping_score
        ) / weight_sum

        return FrameQuality(
            frame_index=frame.frame_index,
            sharpness=sharpness,
            contrast=contrast,
            mean_brightness=mean_brightness,
            dark_ratio=dark_ratio,
            bright_ratio=bright_ratio,
            score=float(min(1.0, max(0.0, score))),
        )


# [Anchor 선택]


class QualityFrameSelector:
    """
    품질 평가 결과와 촬영 순서를 함께 사용해 YOLO anchor 두 장을 고른다.

    앞쪽 anchor를 F1~F2로 제한해 마지막 F6과의 시간 간격을 확보한다.
    이렇게 하면 나머지 프레임의 좌표를 긴 거리로 외삽하는 대신 두
    anchor 사이에서 보간할 수 있다.

    입력:
        BGR uint8 HxWx3 CapturedFrame 6장.

    출력:
        앞쪽 품질 우수 프레임과 마지막 프레임의 인덱스 및 품질 정보.

    실패:
        입력 프레임 계약이 잘못되면 FrameSelectionError가 발생한다.
    """

    def __init__(
        self,
        evaluator: OpenCvFrameQualityEvaluator | None = None,
    ) -> None:
        self._evaluator = evaluator or OpenCvFrameQualityEvaluator()

    def select_anchors(
        self,
        frames: Sequence[CapturedFrame],
    ) -> AnchorSelection:
        """
        F1~F2 중 고품질 프레임과 F6을 YOLO 실행 대상으로 선택한다.

        입력:
            촬영 시간순이며 frame_index가 0~5인 프레임 6장.

        출력:
            earlier/later anchor 인덱스와 전체 품질 평가 결과.

        실패:
            품질 평가가 불가능하면 FrameSelectionError가 발생한다.
        """

        qualities = self._evaluator.evaluate(frames)

        # 점수가 같으면 정지선에 조금 더 가까울 가능성이 있는 뒤 프레임을 쓴다.
        earlier = max(
            qualities[:2],
            key=lambda quality: (quality.score, quality.frame_index),
        )

        return AnchorSelection(
            earlier_frame_index=earlier.frame_index,
            later_frame_index=EXPECTED_FRAME_INDICES[-1],
            qualities=qualities,
        )

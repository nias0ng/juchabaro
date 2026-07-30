"""
원근 보정된 번호판 이미지를 PaddleOCR 입력으로 전처리한다.

파이프라인 위치:
    geometry → plate_preprocessor → plate_reader

주요 기능:
    - Grayscale과 CLAHE를 이용한 국부 명암 보정
    - Gaussian blur를 이용한 약한 sharpening
    - 번호판 외곽 복제 여백 추가
    - 가로세로 비율을 유지한 높이 기준 resize

담당하지 않는 기능:
    - 번호판 위치 검출과 4점 원근 보정
    - OCR 추론과 문자열 판정

기본값은 ``ai/ocr/tests/ocr_benchmark.py``의 비교용 초기 설정과 맞춘
값이다. 실제 Raspberry Pi 촬영 데이터에서의 정확도와 latency 개선은
아직 검증되지 않았으므로 운영 데이터를 수집한 뒤 재평가해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import cv2

from ..errors import OcrComponentError
from ..image_validation import is_nonempty_bgr_uint8_image
from ..types import BgrImage, PreparedPlate, RectifiedPlate


# [예외]


class PlatePreprocessError(OcrComponentError, ValueError):
    """번호판 이미지가 전처리 입력 계약을 만족하지 않는 경우."""


# [전처리 설정]


@dataclass(frozen=True, slots=True)
class PlatePreprocessConfig:
    """
    OCR 화질 전처리 단계에서 사용할 설정.

    기본값은 ``ai/ocr/tests/ocr_benchmark.py``의 비교용 초기값이다.
    실제 Raspberry Pi 촬영 데이터가 쌓이면 인식 정확도와 latency를
    함께 재평가해야 한다.

    실패:
        크기·비율·CLAHE·blur 설정이 유효하지 않으면 ValueError가 발생한다.
    """

    enabled: bool = True
    target_height: int = 64
    padding_percent: float = 5.0
    clahe_clip_limit: float = 2.0
    clahe_tile_size: tuple[int, int] = (8, 8)
    blur_sigma: float = 1.0
    sharpen_source_weight: float = 1.5
    sharpen_blur_weight: float = -0.5

    def __post_init__(self) -> None:
        if self.target_height <= 0:
            raise ValueError("target_height는 0보다 커야 합니다.")
        if (
            not math.isfinite(self.padding_percent)
            or not 0.0 <= self.padding_percent <= 100.0
        ):
            raise ValueError("padding_percent는 0~100 범위여야 합니다.")
        if (
            not math.isfinite(self.clahe_clip_limit)
            or self.clahe_clip_limit <= 0.0
        ):
            raise ValueError("clahe_clip_limit는 0보다 큰 유한한 값이어야 합니다.")
        if (
            len(self.clahe_tile_size) != 2
            or any(size <= 0 for size in self.clahe_tile_size)
        ):
            raise ValueError("clahe_tile_size의 가로·세로는 0보다 커야 합니다.")
        if not math.isfinite(self.blur_sigma) or self.blur_sigma <= 0.0:
            raise ValueError("blur_sigma는 0보다 큰 유한한 값이어야 합니다.")
        if not all(
            math.isfinite(weight)
            for weight in (
                self.sharpen_source_weight,
                self.sharpen_blur_weight,
            )
        ):
            raise ValueError("sharpen 가중치는 유한한 값이어야 합니다.")


# [번호판 화질 전처리]


class PlatePreprocessor:
    """
    원근 보정된 번호판을 PaddleOCR 입력 이미지로 변환한다.

    서비스 시작 시 한 번 생성한 뒤 차량 이벤트마다 재사용할 수 있다.
    모든 OpenCV 연산은 새 배열을 만들며 입력 이미지를 직접 변경하지 않는다.
    입력 RectifiedPlate의 buffer는 caller가 소유하고, 반환하는
    PreparedPlate만 별도 buffer를 소유한다.

    입력:
        BGR uint8 HxWx3 이미지를 가진 RectifiedPlate.

    출력:
        설정된 전처리 결과와 적용 여부를 가진 PreparedPlate.

    실패:
        입력 이미지 형식이 잘못되거나 OpenCV 처리에 실패하면
        PlatePreprocessError가 발생한다.
    """

    def __init__(
        self,
        config: PlatePreprocessConfig | None = None,
    ) -> None:
        self._config = config or PlatePreprocessConfig()
        self._clahe = cv2.createCLAHE(
            clipLimit=self._config.clahe_clip_limit,
            tileGridSize=self._config.clahe_tile_size,
        )

    def process(
        self,
        plate: RectifiedPlate,
    ) -> PreparedPlate:
        """
        번호판 한 장에 설정된 전처리 단계를 순서대로 적용한다.

        입력:
            원근 보정이 완료된 RectifiedPlate.

        출력:
            BGR uint8 HxWx3 이미지를 가진 PreparedPlate. 전처리가
            비활성화된 경우에도 원본과 별개의 배열을 반환한다.

        실패:
            이미지 계약이 잘못되거나 OpenCV 처리가 실패하면 원인을
            보존한 PlatePreprocessError가 발생한다.
        """

        image = self._validate_image(plate.image)

        if not self._config.enabled:
            processed = image.copy()
        else:
            try:
                processed = self._enhance(image)
                processed = self._add_padding(processed)
                processed = self._resize_by_height(processed)
            except cv2.error as exc:
                raise PlatePreprocessError(
                    f"번호판 화질 전처리에 실패했습니다: frame_index={plate.frame_index}"
                ) from exc

        # 내부 helper의 반환 계약도 확인해 PaddleOCR 경계에서의 오류를 줄인다.
        self._validate_image(processed)
        return PreparedPlate(
            frame_index=plate.frame_index,
            image=processed,
            quad_estimate=plate.quad_estimate,
            preprocessing_applied=self._config.enabled,
        )

    def _enhance(
        self,
        image: BgrImage,
    ) -> BgrImage:
        """
        국부 명암을 보정한 뒤 설정된 약한 unsharp mask를 적용한다.

        기본 가중치는 1.5/-0.5이며 PlatePreprocessConfig로
        조정할 수 있다.
        """

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        enhanced = self._clahe.apply(gray)
        blurred = cv2.GaussianBlur(
            enhanced,
            (0, 0),
            sigmaX=self._config.blur_sigma,
        )
        sharpened = cv2.addWeighted(
            enhanced,
            self._config.sharpen_source_weight,
            blurred,
            self._config.sharpen_blur_weight,
            0,
        )
        return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)

    def _add_padding(
        self,
        image: BgrImage,
    ) -> BgrImage:
        """crop 경계에 붙은 문자가 누락되지 않도록 복제 여백을 추가한다."""

        height, width = image.shape[:2]
        pad_y = round(height * self._config.padding_percent / 100.0)
        pad_x = round(width * self._config.padding_percent / 100.0)

        return cv2.copyMakeBorder(
            image,
            pad_y,
            pad_y,
            pad_x,
            pad_x,
            borderType=cv2.BORDER_REPLICATE,
        )

    def _resize_by_height(
        self,
        image: BgrImage,
    ) -> BgrImage:
        """가로세로 비율을 유지하며 설정된 높이로 resize한다."""

        height, width = image.shape[:2]
        scale = self._config.target_height / height
        target_width = max(1, round(width * scale))

        # 확대 시 획을 부드럽게 보간하고 축소 시 aliasing을 줄이는 조합이다.
        interpolation = (
            cv2.INTER_CUBIC
            if scale >= 1.0
            else cv2.INTER_AREA
        )
        return cv2.resize(
            image,
            (target_width, self._config.target_height),
            interpolation=interpolation,
        )

    @staticmethod
    def _validate_image(image: BgrImage) -> BgrImage:
        """이미지가 비어 있지 않은 BGR uint8 HxWx3인지 검사한다."""

        if not is_nonempty_bgr_uint8_image(image):
            raise PlatePreprocessError(
                "번호판 이미지는 비어 있지 않은 BGR uint8 HxWx3 "
                "배열이어야 합니다."
            )
        return image

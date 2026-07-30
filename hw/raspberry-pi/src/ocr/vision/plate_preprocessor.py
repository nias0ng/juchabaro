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

전처리 값은 ``ai/ocr/tests/ocr_benchmark.py``의 비교용 초기 설정과
맞춘 임시 고정값이다. 실제 Raspberry Pi 촬영 데이터에서의 정확도와
latency 개선은 아직 검증되지 않았으므로 운영 데이터를 수집한 뒤
재평가해야 한다.
"""

from __future__ import annotations

import cv2

from ..errors import OcrComponentError
from ..image_validation import is_nonempty_bgr_uint8_image
from ..types import BgrImage, PreparedPlate, RectifiedPlate


# [예외]


class PlatePreprocessError(OcrComponentError, ValueError):
    """번호판 이미지가 전처리 입력 계약을 만족하지 않는 경우."""


# [임시 전처리 값]


_TARGET_HEIGHT = 64
_PADDING_PERCENT = 5.0
_CLAHE_CLIP_LIMIT = 2.0
_CLAHE_TILE_SIZE = (8, 8)
_BLUR_SIGMA = 1.0
_SHARPEN_SOURCE_WEIGHT = 1.5
_SHARPEN_BLUR_WEIGHT = -0.5


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
        고정 전처리 결과를 가진 PreparedPlate.

    실패:
        입력 이미지 형식이 잘못되거나 OpenCV 처리에 실패하면
        PlatePreprocessError가 발생한다.
    """

    def __init__(self) -> None:
        self._clahe = cv2.createCLAHE(
            clipLimit=_CLAHE_CLIP_LIMIT,
            tileGridSize=_CLAHE_TILE_SIZE,
        )

    def process(
        self,
        plate: RectifiedPlate,
    ) -> PreparedPlate:
        """
        번호판 한 장에 고정 전처리 단계를 순서대로 적용한다.

        입력:
            원근 보정이 완료된 RectifiedPlate.

        출력:
            원본과 별개의 BGR uint8 HxWx3 배열을 가진 PreparedPlate.

        실패:
            이미지 계약이 잘못되거나 OpenCV 처리가 실패하면 원인을
            보존한 PlatePreprocessError가 발생한다.
        """

        image = self._validate_image(plate.image)

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
        )

    def _enhance(
        self,
        image: BgrImage,
    ) -> BgrImage:
        """국부 명암을 보정한 뒤 약한 unsharp mask를 적용한다."""

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        enhanced = self._clahe.apply(gray)
        blurred = cv2.GaussianBlur(
            enhanced,
            (0, 0),
            sigmaX=_BLUR_SIGMA,
        )
        sharpened = cv2.addWeighted(
            enhanced,
            _SHARPEN_SOURCE_WEIGHT,
            blurred,
            _SHARPEN_BLUR_WEIGHT,
            0,
        )
        return cv2.cvtColor(sharpened, cv2.COLOR_GRAY2BGR)

    def _add_padding(
        self,
        image: BgrImage,
    ) -> BgrImage:
        """crop 경계에 붙은 문자가 누락되지 않도록 복제 여백을 추가한다."""

        height, width = image.shape[:2]
        pad_y = round(height * _PADDING_PERCENT / 100.0)
        pad_x = round(width * _PADDING_PERCENT / 100.0)

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
        scale = _TARGET_HEIGHT / height
        target_width = max(1, round(width * scale))

        # 확대 시 획을 부드럽게 보간하고 축소 시 aliasing을 줄이는 조합이다.
        interpolation = (
            cv2.INTER_CUBIC
            if scale >= 1.0
            else cv2.INTER_AREA
        )
        return cv2.resize(
            image,
            (target_width, _TARGET_HEIGHT),
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

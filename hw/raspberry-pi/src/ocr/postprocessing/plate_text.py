"""
PaddleOCR의 원시 문자열을 번호판 후보로 정규화하고 형식을 검사한다.

파이프라인 위치:
    plate_reader → plate_text → aggregator

주요 기능:
    - Unicode NFKC 정규화
    - 공백·구두점을 제외한 글자와 숫자 추출
    - 현재 지원하는 일반 번호판 전체 형식 검사
    - RawOcrResult를 OcrCandidate로 변환

담당하지 않는 기능:
    - OCR 추론
    - OCR 오인식 문자의 추측 교정
    - 여러 프레임 후보의 투표와 최종 판정

현재는 ``12가3456``과 ``123가4567`` 형태의 일반 번호판만 지원한다.
외교·군용·건설기계·구형 지역 번호판은 지원 범위에 포함하지 않는다.
"""

from __future__ import annotations

import math
import re
import unicodedata
from numbers import Real

from ..types import OcrCandidate, RawOcrResult


# [지원 번호판 형식]


_SUPPORTED_PLATE_PATTERN = re.compile(
    r"[0-9]{2,3}[가-힣][0-9]{4}"
)


# [문자열 정규화]


def normalize_plate_text(text: str) -> str:
    """
    OCR 문자열의 Unicode 표현을 통일하고 글자와 숫자만 남긴다.

    NFKC 정규화를 먼저 적용하므로 전각 숫자처럼 호환 가능한 문자는
    일반적인 표현으로 바뀐다. 이후 ``str.isalnum()``으로 공백과
    구두점을 제거하되, 비슷하게 보이는 문자를 임의로 치환하지 않는다.

    입력:
        PaddleOCR가 반환한 문자열.

    출력:
        Unicode NFKC 정규화 후 영숫자만 남긴 문자열.

    실패:
        ``text``가 문자열이 아니면 TypeError가 발생한다.
    """

    if not isinstance(text, str):
        raise TypeError("text는 문자열이어야 합니다.")

    normalized = unicodedata.normalize("NFKC", text)
    return "".join(character for character in normalized if character.isalnum())


# [번호판 형식 검사]


def is_supported_plate_number(text: str) -> bool:
    """
    문자열이 현재 지원하는 일반 번호판 전체 형식인지 검사한다.

    입력:
        이미 정규화된 번호판 후보 문자열.

    출력:
        ASCII 숫자 2~3자리, 한글 1자, ASCII 숫자 4자리 형식을
        정확히 만족하면 True, 그렇지 않으면 False.

    실패:
        ``text``가 문자열이 아니면 TypeError가 발생한다.
    """

    if not isinstance(text, str):
        raise TypeError("text는 문자열이어야 합니다.")

    return _SUPPORTED_PLATE_PATTERN.fullmatch(text) is not None


# [OCR 후보 생성]


def build_ocr_candidate(result: RawOcrResult) -> OcrCandidate:
    """
    PaddleOCR 원시 결과를 정규화하고 형식을 판정한 후보로 변환한다.

    입력:
        프레임 인덱스, 원시 문자열, OCR confidence를 가진 RawOcrResult.

    출력:
        정규화 문자열과 지원 형식 여부가 채워진 OcrCandidate.

    실패:
        프레임 인덱스가 음수이거나 OCR confidence가 유한한 0~1 값이
        아니면 ValueError가 발생한다. 원시 문자열이 문자열이 아니면
        TypeError가 발생한다.
    """

    if isinstance(result.frame_index, bool) or not isinstance(
        result.frame_index,
        int,
    ):
        raise ValueError("frame_index는 0 이상의 정수여야 합니다.")
    if result.frame_index < 0:
        raise ValueError("frame_index는 0 이상의 정수여야 합니다.")

    if (
        isinstance(result.rec_score, bool)
        or not isinstance(result.rec_score, Real)
    ):
        raise ValueError("rec_score는 0~1 범위의 유한한 수여야 합니다.")

    rec_score = float(result.rec_score)
    if not math.isfinite(rec_score) or not 0.0 <= rec_score <= 1.0:
        raise ValueError("rec_score는 0~1 범위의 유한한 수여야 합니다.")

    normalized_text = normalize_plate_text(result.raw_text)

    return OcrCandidate(
        frame_index=result.frame_index,
        raw_text=result.raw_text,
        normalized_text=normalized_text,
        rec_score=rec_score,
        valid_format=is_supported_plate_number(normalized_text),
    )

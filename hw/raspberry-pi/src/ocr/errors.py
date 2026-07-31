"""OCR pipeline의 공개 오류 경계와 내부 component 오류 표식을 정의한다."""

from __future__ import annotations


class OcrPipelineError(Exception):
    """OCR pipeline 실행 계약 또는 runtime 오류."""


class InvalidBurstError(OcrPipelineError):
    """카메라가 전달한 burst가 입력 계약을 위반한 경우."""


class OcrRuntimeError(OcrPipelineError):
    """모델, adapter, OpenCV 또는 내부 invariant 오류."""


class OcrComponentError(OcrRuntimeError):
    """모델·adapter·OpenCV component에서 발생한 알려진 runtime 오류."""

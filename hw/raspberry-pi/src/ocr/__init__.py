"""
Raspberry Pi 입구 카메라의 번호판 OCR 파이프라인 공개 API.

운영 caller는 factory로 모델과 기본 component를 한 번 조립한다.
테스트와 debug viewer는 ``PlateOcrPipeline``에 fake 또는 traced
component를 직접 주입할 수 있다.
"""

from .errors import (
    InvalidBurstError,
    OcrPipelineError,
    OcrRuntimeError,
)
from .factory import OcrRuntimeConfig, load_plate_ocr_pipeline
from .pipeline import OcrPipelinePolicy, PlateOcrPipeline
from .types import CapturedFrame, PlateReadResult, ReadStatus


__all__ = [
    "CapturedFrame",
    "InvalidBurstError",
    "OcrPipelinePolicy",
    "OcrPipelineError",
    "OcrRuntimeConfig",
    "OcrRuntimeError",
    "PlateOcrPipeline",
    "PlateReadResult",
    "ReadStatus",
    "load_plate_ocr_pipeline",
]

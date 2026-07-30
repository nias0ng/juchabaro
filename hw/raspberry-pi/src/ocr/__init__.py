"""
Raspberry Pi 입구 카메라의 번호판 OCR 파이프라인 공개 API.

모델 loader와 세부 영상 처리 구현은 하위 패키지에 두고, 상위 서비스가
필요로 하는 파이프라인과 핵심 입출력 타입만 이 패키지에서 공개한다.
"""

from .pipeline import OcrPipelinePolicy, PlateOcrPipeline
from .types import CapturedFrame, PlateReadResult, ReadStatus


__all__ = [
    "CapturedFrame",
    "OcrPipelinePolicy",
    "PlateOcrPipeline",
    "PlateReadResult",
    "ReadStatus",
]

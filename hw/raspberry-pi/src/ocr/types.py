'''
OCR 모듈 사이에서 왔다갔다 할 데이터 타입만 정리해놨음!
촬영시간은 넣을까 말까 하다가 카메라 쪽 데이터라서 일단은 빼놨는데, 좀 고민중.
'''

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray


BgrImage: TypeAlias = NDArray[np.uint8]
Point: TypeAlias = tuple[float, float]
Quad: TypeAlias = tuple[Point, Point, Point, Point]


class ReadStatus(str, Enum):
    SUCCESS = "SUCCESS"
    INVALID_INPUT = "INVALID_INPUT"
    NO_PLATE_REGION = "NO_PLATE_REGION"
    OCR_EMPTY = "OCR_EMPTY"
    INVALID_FORMAT = "INVALID_FORMAT"
    LOW_SCORE = "LOW_SCORE"
    AMBIGUOUS = "AMBIGUOUS"
    MODEL_ERROR = "MODEL_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class QuadSource(str, Enum):
    DETECTED = "DETECTED"
    INTERPOLATED = "INTERPOLATED"
    EXTRAPOLATED = "EXTRAPOLATED"
    REUSED = "REUSED"


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """
    사진 데이터 프레임

    frame_index는 촬영 시간순 인덱스
    image는 BGR uint8 HxWx3 배열
    """

    frame_index: int
    image: BgrImage


@dataclass(frozen=True, slots=True)
class FrameQuality:
    '''
    사진 데이터 정보
    있다가 다른 파일 다 만들고 나서 어떤 파일 용인지도 적어놔야겠네.
    '''
    frame_index: int
    sharpness: float
    contrast: float
    mean_brightness: float
    dark_ratio: float
    bright_ratio: float
    score: float


@dataclass(frozen=True, slots=True)
class AnchorSelection:
    """YOLO를 실행할 앞쪽 프레임과 마지막 프레임. earlier 프레임이 0, 1 중에 선택해서 들어갈 예정이라 필요할 듯? """

    earlier_frame_index: int
    later_frame_index: int
    qualities: tuple[FrameQuality, ...]


@dataclass(frozen=True, slots=True)
class DetectedPlate:
    """한 anchor 프레임에서 YOLO가 특정한 번호판 위치"""

    frame_index: int
    bbox_xyxy: tuple[float, float, float, float]
    quad: Quad
    detector_score: float


@dataclass(frozen=True, slots=True)
class EstimatedQuad:
    """특정 프레임에서 사용할 검출·보간된 4점 좌표."""

    frame_index: int
    quad: Quad
    source: QuadSource
    source_anchor_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RectifiedPlate:
    """원근 보정이 끝난 PaddleOCR 입력."""

    frame_index: int
    image: BgrImage
    quad_estimate: EstimatedQuad


@dataclass(frozen=True, slots=True)
class OcrCandidate:
    frame_index: int
    raw_text: str
    normalized_text: str
    rec_score: float
    valid_format: bool


@dataclass(frozen=True, slots=True)
class PlateDecision:
    """aggregator가 내린 번호판 집계 결과."""

    status: ReadStatus
    plate_number: str | None
    valid_frames: int
    vote_count: int
    vote_ratio: float
    mean_rec_score: float
    error_message: str | None


@dataclass(slots=True)
class PipelineMetrics:
    frame_selection_ms: float = 0.0
    detection_ms: float = 0.0
    geometry_ms: float = 0.0
    recognition_ms: float = 0.0
    total_ms: float = 0.0
    detector_calls: int = 0
    recognizer_calls: int = 0


@dataclass(frozen=True, slots=True)
class StageFailure:
    stage: str
    frame_index: int | None
    message: str


@dataclass(frozen=True, slots=True)
class PlateReadResult:
    status: ReadStatus
    plate_number: str | None
    total_frames: int
    valid_frames: int
    vote_count: int
    vote_ratio: float
    mean_rec_score: float
    candidates: tuple[OcrCandidate, ...]
    failures: tuple[StageFailure, ...]
    metrics: PipelineMetrics
    error_message: str | None

    @property
    def succeeded(self) -> bool:
        return (
            self.status is ReadStatus.SUCCESS
            and self.plate_number is not None
        )
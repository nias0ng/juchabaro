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


# 타입별칭
BgrImage: TypeAlias = NDArray[np.uint8]
Point: TypeAlias = tuple[float, float]
Quad: TypeAlias = tuple[Point, Point, Point, Point]


# OCR 파이프라인 최종 처리 상태 Enum
# 로그나 디버깅 시 상태 표시용
class ReadStatus(str, Enum):
    '''
    SUCCESS: 번호판 읽기 성공, 최종 번호 확정
    INVALID_INPUT: 입력 이미지 수, 자료형, 해상도, shape 등이 요구 조건과 다름
    NO_PLATE_REGION: 번호판을 찾지 못했거나, 사용할 수 있는 번호판 영역을 만들지 못함
    OCR_EMPTY: OCR 결과가 모두 빈 문자열
    INVALID_FORMAT: 한국 번호판 형식에 맞는 결과가 없음
    LOW_SCORE: 번호판 형식은 맞지만 OCR 신뢰 점수가 기준보다 낮음
    AMBIGUOUS: 여러 프레임의 결과가 서로 달라 최종 번호를 확정하기 어려움
    MODEL_ERROR: 모델 실행 자체에서 오류가 발생함
    INTERNAL_ERROR: 모델 외의 파이프라인 내부 로직에서 예상하지 못한 오류가 발생함
    '''
    SUCCESS = "SUCCESS"
    INVALID_INPUT = "INVALID_INPUT"
    NO_PLATE_REGION = "NO_PLATE_REGION"
    OCR_EMPTY = "OCR_EMPTY"
    INVALID_FORMAT = "INVALID_FORMAT"
    LOW_SCORE = "LOW_SCORE"
    AMBIGUOUS = "AMBIGUOUS"
    MODEL_ERROR = "MODEL_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 프레임의 꼭짓점 좌표를 얻은 방식 Enum
# 로그 및 디버깅용
class QuadSource(str, Enum):
    '''
    DETECTED: 해당 프레임에서 YOLO가 직접 검출
    INTERPOLATED: 앞·뒤 두 검출 좌표 사이(안쪽)을 선형 보간
    EXTRAPOLATED: 이동 추세를 검출 구간 바깥까지 연장해서 계산
    REUSED: 검출 좌표 하나를 인접 프레임에 그대로 복사
    '''
    DETECTED = "DETECTED"
    INTERPOLATED = "INTERPOLATED"
    EXTRAPOLATED = "EXTRAPOLATED"
    REUSED = "REUSED"


# 사진 데이터용 프레임들
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
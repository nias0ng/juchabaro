"""
OCR 파이프라인 모듈 사이에서 전달되는 공통 데이터 타입을 정의한다.

이 파일은 촬영된 프레임부터 최종 번호판 판정까지의 데이터 계약만
담당한다. 모델 실행, 영상 처리, 문자열 판정 로직은 포함하지 않는다.
촬영 시각은 카메라·입차 이벤트 계층의 책임이므로 현재 계약에서 제외한다.
데이터 클래스는 경량 전달 객체이며 유효성은 각 처리 단계 입구에서 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

import numpy as np
from numpy.typing import NDArray


# [공통 타입 별칭]


BgrImage: TypeAlias = NDArray[np.uint8]
Point: TypeAlias = tuple[float, float]
Quad: TypeAlias = tuple[Point, Point, Point, Point]
BBox: TypeAlias = tuple[float, float, float, float]


# [처리 상태와 좌표 출처]


class ReadStatus(str, Enum):
    """OCR 파이프라인이 반환할 수 있는 최종 처리 상태."""

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
    """프레임의 번호판 4점 좌표를 얻은 방법."""

    DETECTED = "DETECTED"
    INTERPOLATED = "INTERPOLATED"
    EXTRAPOLATED = "EXTRAPOLATED"
    REUSED = "REUSED"


# [입력 프레임과 품질 정보]


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """
    한 번의 촬영 burst에 포함된 시간순 프레임.

    ``frame_index``는 burst 내부 인덱스 0~5이고, ``image``는
    BGR uint8 HxWx3 배열이다.
    """

    frame_index: int
    image: BgrImage


@dataclass(frozen=True, slots=True)
class FrameQuality:
    """
    전체 프레임에서 계산한 저비용 품질 지표.

    번호판 crop이 생기기 전에 계산하므로 번호판 자체 품질이 아닌
    전체 프레임 품질의 근사치라는 한계가 있다.
    """

    frame_index: int
    sharpness: float
    contrast: float
    mean_brightness: float
    dark_ratio: float
    bright_ratio: float
    score: float


@dataclass(frozen=True, slots=True)
class AnchorSelection:
    """YOLO를 실행할 앞쪽 anchor와 마지막 anchor 선택 결과."""

    earlier_frame_index: int
    later_frame_index: int
    qualities: tuple[FrameQuality, ...]


# [번호판 검출과 기하 처리 결과]


@dataclass(frozen=True, slots=True)
class DetectedPlate:
    """
    YOLO pose가 한 anchor 프레임에서 검출한 번호판 후보.

    ``quad``의 점 순서는 좌상→우상→우하→좌하이며,
    ``bbox_xyxy``는 좌상·우하 좌표 순서다.
    """

    frame_index: int
    bbox_xyxy: BBox
    quad: Quad
    detector_score: float


@dataclass(frozen=True, slots=True)
class EstimatedQuad:
    """특정 프레임에 적용할 검출·보간·재사용된 번호판 4점 좌표."""

    frame_index: int
    quad: Quad
    source: QuadSource
    source_anchor_indices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class RectifiedPlate:
    """4점 원근 보정이 끝난 번호판 이미지."""

    frame_index: int
    image: BgrImage
    quad_estimate: EstimatedQuad


@dataclass(frozen=True, slots=True)
class PreparedPlate:
    """화질 전처리를 마친 PaddleOCR 입력 이미지."""

    frame_index: int
    image: BgrImage
    quad_estimate: EstimatedQuad
    preprocessing_applied: bool


# [OCR 인식과 문자열 처리 결과]


@dataclass(frozen=True, slots=True)
class RawOcrResult:
    """PaddleOCR가 직접 반환한 아직 정규화되지 않은 인식 결과."""

    frame_index: int
    raw_text: str
    rec_score: float


@dataclass(frozen=True, slots=True)
class OcrCandidate:
    """문자열 정규화와 지원 번호판 형식 검사를 마친 OCR 후보."""

    frame_index: int
    raw_text: str
    normalized_text: str
    rec_score: float
    valid_format: bool


# [최종 판정과 파이프라인 진단]


@dataclass(frozen=True, slots=True)
class PlateDecision:
    """후처리 집계기가 내린 번호판 판정."""

    status: ReadStatus
    plate_number: str | None
    valid_frames: int
    vote_count: int
    vote_ratio: float
    mean_rec_score: float
    error_message: str | None = None


@dataclass(slots=True)
class PipelineMetrics:
    """단일 차량 이벤트의 단계별 실행 시간과 모델 호출 횟수."""

    frame_selection_ms: float = 0.0
    detection_ms: float = 0.0
    geometry_ms: float = 0.0
    preprocessing_ms: float = 0.0
    recognition_ms: float = 0.0
    postprocessing_ms: float = 0.0
    total_ms: float = 0.0
    detector_calls: int = 0
    recognizer_calls: int = 0


@dataclass(frozen=True, slots=True)
class StageFailure:
    """일부 프레임 처리 실패를 최종 결과에 남기는 진단 정보."""

    stage: str
    frame_index: int | None
    message: str


@dataclass(frozen=True, slots=True)
class PlateReadResult:
    """상위 입차 서비스에 반환하는 OCR 파이프라인 최종 결과."""

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
    error_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """전체 번호판이 성공적으로 확정되었는지 반환한다."""

        return (
            self.status is ReadStatus.SUCCESS
            and self.plate_number is not None
        )

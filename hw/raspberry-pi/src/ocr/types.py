"""
OCR 파이프라인 모듈 사이에서 전달되는 공통 데이터 타입을 정의한다.

이 파일은 촬영된 프레임부터 최종 번호판 판정까지의 데이터 계약만
담당한다. 모델 실행, 영상 처리, 문자열 판정 로직은 포함하지 않는다.
촬영 시각은 카메라·입차 이벤트 계층의 책임이므로 현재 계약에서 제외한다.
데이터 클래스는 경량 전달 객체다. 외부 입력과 모델 adapter 경계에서
유효성을 검증하고, 그 뒤의 내부 단계는 앞 단계가 만든 계약을 신뢰한다.

``frozen=True``는 필드 재할당만 막으며 ``numpy.ndarray``의 내부 값까지
불변으로 만들지는 않는다. 입력 이미지 buffer의 소유권은 caller에게 있고
pipeline과 component는 이를 deep copy하지 않은 read-only 참조로 다룬다.
caller는 OCR 실행 중 buffer를 변경하거나 재사용하면 안 된다. 원근 보정과
전처리처럼 이미지를 생성하는 단계의 결과만 별도 buffer로 전달한다.
카메라 buffer와 독립된 소유권이 필요하면 촬영 경계에서 한 번 확보한다.
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
    NO_PLATE_REGION = "NO_PLATE_REGION"
    OCR_EMPTY = "OCR_EMPTY"
    INVALID_FORMAT = "INVALID_FORMAT"
    LOW_SCORE = "LOW_SCORE"
    AMBIGUOUS = "AMBIGUOUS"


class QuadSource(str, Enum):
    """프레임의 번호판 4점 좌표를 얻은 방법."""

    DETECTED = "DETECTED"
    INTERPOLATED = "INTERPOLATED"
    EXTRAPOLATED = "EXTRAPOLATED"
    REUSED = "REUSED"


# [입력 프레임과 anchor 선택]


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    """
    한 번의 촬영 burst에 포함된 시간순 프레임.

    ``frame_index``는 0부터 시작하는 burst 내부 연속 인덱스이고,
    ``image``는 BGR uint8 HxWx3 배열이다. 이미지 buffer는 caller가
    소유하며 이 객체를 만들 때 deep copy하지 않는다. OCR 실행이 끝날
    때까지 같은 buffer를 변경하거나 다른 촬영에 재사용하면 안 된다.
    """

    frame_index: int
    image: BgrImage


@dataclass(frozen=True, slots=True)
class AnchorSelection:
    """YOLO를 실행할 앞쪽 anchor와 마지막 anchor 선택 결과."""

    earlier_frame_index: int
    later_frame_index: int


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
    """4점 원근 보정이 끝난 별도 buffer의 번호판 이미지.

    ``image``는 원본 CapturedFrame을 변경하지 않고 원근 보정 단계가 새로
    만든 배열이다. 후속 component는 이 배열도 read-only로 다룬다.
    """

    frame_index: int
    image: BgrImage


@dataclass(frozen=True, slots=True)
class PreparedPlate:
    """화질 전처리를 마친 별도 buffer의 PaddleOCR 입력 이미지.

    ``image``는 RectifiedPlate와 공유하지 않는 전처리 결과 배열이다.
    PaddleOCR adapter는 이를 deep copy하거나 변경하지 않고 읽기만 한다.
    """

    frame_index: int
    image: BgrImage


# [OCR 인식과 문자열 처리 결과]


@dataclass(frozen=True, slots=True)
class RawOcrResult:
    """PaddleOCR adapter가 만든 아직 정규화되지 않은 인식 결과."""

    frame_index: int
    raw_text: str
    rec_score: float


@dataclass(frozen=True, slots=True)
class OcrCandidate:
    """문자열 정규화와 지원 번호판 형식 검사를 마친 OCR 후보."""

    frame_index: int
    normalized_text: str
    rec_score: float
    valid_format: bool


# [최종 판정과 공개 결과]


@dataclass(frozen=True, slots=True)
class PlateDecision:
    """후처리 집계기가 내린 번호판 판정.

    ``winner_rec_score``는 성공한 winner 문자열에 투표한 후보 중 가장
    높은 PaddleOCR ``rec_score``다. 판정이 성공하지 않으면 ``None``이다.
    """

    status: ReadStatus
    plate_number: str | None
    valid_frames: int
    vote_count: int
    vote_ratio: float
    winner_rec_score: float | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class PlateReadResult:
    """상위 입차 서비스에 반환하는 최소 OCR 판독 결과.

    성공 시 ``rec_score``는 최종 번호판 winner의 대표 PaddleOCR 점수이며,
    외부 API의 ``ocrConfidence``로 전달할 수 있다.
    """

    status: ReadStatus
    plate_number: str | None
    rec_score: float | None = None

    @property
    def succeeded(self) -> bool:
        """전체 번호판이 성공적으로 확정되었는지 반환한다."""

        return (
            self.status is ReadStatus.SUCCESS
            and self.plate_number is not None
        )

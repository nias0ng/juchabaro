#!/usr/bin/env python3
"""Raspberry Pi 5 카메라 기반 4자리 차량 식별번호 OCR 베이스라인.

지원 모드는 카메라 점검(`--probe-camera`),
전체 프레임 저장 (`--capture-frame`),
1회/수동 반복 OCR(`--once`, `--interactive`),
하드웨어 비의존 자체 테스트(`--self-test`)다.

Raspberry Pi OS에서는 Picamera2와 OpenCV를 OS 패키지로 설치하는 방식을 우선한다.
OCR 모드에는 NumPy와 DBNet18 검출기를 포함한 EasyOCR가 필요하다.
가상환경은 시스템 Picamera2를 볼 수 있도록 다음 형태를 권장한다.

    python3 -m venv --system-site-packages .venv

실제 Raspberry Pi에서는 `uname -m`, `cat /etc/os-release`, `python3 --version`,
`free -h`, `lsblk`, `rpicam-hello --list-cameras`로 환경과 카메라를 먼저
확인해야 한다. 이 파일은 DBNet18 영역 검출, 4점 원근 보정, EasyOCR 문자
인식, 수동 트리거, 표준 출력 발행기를 분리해 이후 YOLO pose, 센서, 다른
OCR 런타임, 원격 전송 구현으로 교체할 수 있게 한다.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import importlib.metadata
import json
import logging
import math
from pathlib import Path
import re
import sys
import time
from types import TracebackType
from typing import Any, Mapping, Protocol, Sequence
import unicodedata
import unittest
from uuid import uuid4


LOGGER = logging.getLogger("rpi_ocr_baseline")
PLATE_PATTERN = re.compile(r"^[0-9]{4}$")


class ReadStatus(str, Enum):
    """번호판 인식 이벤트의 최종 상태."""

    SUCCESS = "SUCCESS"
    CAMERA_ERROR = "CAMERA_ERROR"
    NO_PLATE_REGION = "NO_PLATE_REGION"
    OCR_EMPTY = "OCR_EMPTY"
    INVALID_FORMAT = "INVALID_FORMAT"
    LOW_SCORE = "LOW_SCORE"
    AMBIGUOUS = "AMBIGUOUS"
    MODEL_ERROR = "MODEL_ERROR"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"


@dataclass(frozen=True)
class CapturedFrame:
    """촬영 순번, 시각, RGB888 uint8 이미지로 구성된 카메라 프레임."""

    frame_id: int
    captured_at: datetime
    image: Any


@dataclass(frozen=True)
class FrameQuality:
    """대표 프레임 선정을 위한 저비용 전체 프레임 품질 측정값."""

    frame_id: int
    sharpness: float
    contrast: float
    mean_brightness: float
    dark_ratio: float
    bright_ratio: float
    score: float


@dataclass(frozen=True)
class DetectedRegion:
    """원본 프레임 좌표의 네 꼭짓점으로 표현한 문자 영역 후보."""

    quad: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]
    detector_score: float | None
    source: str


@dataclass(frozen=True)
class OcrCandidate:
    """한 프레임의 OCR 원문과 내부 정규화 결과."""

    frame_id: int
    raw_text: str
    normalized_text: str
    rec_score: float
    valid_format: bool


@dataclass(frozen=True)
class _RegionAttempt:
    """대표 프레임의 영역·보정 이미지·OCR 후보를 묶은 내부 선택 단위."""

    region: DetectedRegion
    rectified: Any
    candidate: OcrCandidate


@dataclass(frozen=True)
class ModelInfo:
    """결과 재현을 위해 기록하는 OCR 라이브러리와 모델 정보."""

    library: str
    library_version: str
    model_name: str
    model_dir: str | None
    engine: str


@dataclass(frozen=True)
class PlateReadResult:
    """단일 인식 이벤트의 후보, 집계값, 지연시간을 담은 결과."""

    status: ReadStatus
    plate_number: str | None
    total_frames: int
    valid_frames: int
    vote_count: int
    vote_ratio: float
    mean_rec_score: float
    candidates: tuple[OcrCandidate, ...]
    latency_ms: float
    model_info: ModelInfo
    error_message: str | None


class BaselineError(RuntimeError):
    """CLI 경계까지 원래 상태와 원인을 보존하는 베이스라인 오류."""

    def __init__(self, status: ReadStatus, message: str) -> None:
        super().__init__(message)
        self.status = status


class TriggerSource(Protocol):
    """인식 이벤트를 시작하거나 종료할 시점을 제공하는 계약."""

    def wait_for_trigger(self) -> bool:
        """인식을 시작하면 True, 정상 종료 요청이면 False를 반환한다."""


class FrameSource(Protocol):
    """프레임 공급자의 초기화, 촬영, 해제 생명주기 계약."""

    def open(self) -> None:
        """프레임 공급자를 한 번 초기화한다."""

    def capture(self) -> CapturedFrame:
        """RGB888 uint8 프레임 한 장을 촬영한다."""

    def close(self) -> None:
        """프레임 공급자의 자원을 해제한다."""


class FrameSelector(Protocol):
    """촬영된 프레임을 OCR 대표성에 유리한 순서로 정렬하는 계약."""

    def rank(self, frames: Sequence[CapturedFrame]) -> Sequence[FrameQuality]:
        """모든 입력 프레임의 품질을 계산하여 우선순위 순서로 반환한다."""


class RegionDetector(Protocol):
    """전체 프레임에서 4점 문자 영역 후보를 찾는 계약."""

    def detect(self, frame: CapturedFrame) -> Sequence[DetectedRegion]:
        """원본 프레임 좌표의 문자 영역 후보를 반환한다."""


class RegionRectifier(Protocol):
    """4점 문자 영역을 recognizer가 읽을 정면 이미지로 보정하는 계약."""

    def rectify(self, frame: CapturedFrame, region: DetectedRegion) -> Any:
        """원본 프레임과 4점 영역으로 원근 보정된 이미지 배열을 반환한다."""


class PlatePreprocessor(Protocol):
    """번호판 Crop에 검증된 최소 전처리를 적용하는 계약."""

    def process(self, image: Any) -> Any:
        """OCR 입력용 이미지 배열을 반환한다."""


class TextRecognizer(Protocol):
    """번호판 Crop을 내부 OCR 후보로 변환하는 계약."""

    @property
    def model_info(self) -> ModelInfo:
        """현재 설정 또는 초기화된 모델 정보를 반환한다."""

    def open(self) -> None:
        """OCR 모델을 애플리케이션 시작 시 한 번 초기화한다."""

    def recognize(self, frame_id: int, image: Any) -> OcrCandidate:
        """한 줄 문자 이미지를 인식하여 내부 후보를 반환한다."""

    def close(self) -> None:
        """OCR 모델이 점유한 참조를 해제한다."""


class ResultPublisher(Protocol):
    """최종 인식 결과를 출력하거나 외부로 전달하는 계약."""

    def publish(self, result: PlateReadResult) -> None:
        """구조화된 결과를 발행한다."""


def normalize_plate_text(raw_text: str) -> str:
    """NFKC 적용 후 공백과 하이픈을 제거하되 문자를 추측 치환하지 않는다."""

    normalized = unicodedata.normalize("NFKC", raw_text).strip()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.replace("-", "")


def extract_plate_suffix(raw_text: str) -> str:
    """정규화된 OCR 문자열 끝의 숫자 네 자리를 차량 식별번호로 추출한다."""

    normalized = normalize_plate_text(raw_text)
    match = re.search(r"([0-9]{4})$", normalized)
    return match.group(1) if match is not None else normalized


def is_valid_plate_number(text: str) -> bool:
    """문자열이 ASCII 숫자 정확히 네 자리인지 검사한다."""

    return PLATE_PATTERN.fullmatch(text) is not None


def quad_area(region: DetectedRegion) -> float:
    """영역 후보의 면적을 shoelace 공식으로 계산한다."""

    points = order_quad_points(region.quad)
    area_twice = sum(
        points[index][0] * points[(index + 1) % 4][1]
        - points[(index + 1) % 4][0] * points[index][1]
        for index in range(4)
    )
    return abs(area_twice) / 2.0


def best_region_attempt(
    attempts: Sequence[_RegionAttempt],
    *,
    require_valid_format: bool,
) -> _RegionAttempt | None:
    """형식·OCR 점수·영역 크기 순으로 대표 문자 영역을 선택한다."""

    pool = [attempt for attempt in attempts if attempt.candidate.valid_format] if require_valid_format else list(attempts)
    if not pool:
        return None
    return max(
        pool,
        key=lambda attempt: (
            attempt.candidate.valid_format,
            bool(attempt.candidate.raw_text.strip()),
            attempt.candidate.rec_score,
            quad_area(attempt.region),
        ),
    )


def to_jsonable(value: Any) -> Any:
    """결과 데이터 모델을 외부 객체 없이 JSON 직렬화 가능한 값으로 바꾼다."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def make_failure_result(
    status: ReadStatus,
    message: str,
    model_info: ModelInfo,
    *,
    total_frames: int = 0,
    candidates: Sequence[OcrCandidate] = (),
    latency_ms: float = 0.0,
) -> PlateReadResult:
    """예외 경로에서도 동일한 결과 계약을 유지하는 실패 결과를 만든다."""

    return PlateReadResult(
        status=status,
        plate_number=None,
        total_frames=total_frames,
        valid_frames=0,
        vote_count=0,
        vote_ratio=0.0,
        mean_rec_score=0.0,
        candidates=tuple(candidates),
        latency_ms=latency_ms,
        model_info=model_info,
        error_message=message,
    )


def aggregate_candidates(
    candidates: Sequence[OcrCandidate],
    *,
    total_frames: int,
    min_rec_score: float,
    min_valid_frames: int,
    min_vote_ratio: float,
    ambiguity_margin: float,
    latency_ms: float,
    model_info: ModelInfo,
) -> PlateReadResult:
    """점수·형식 필터와 다중 프레임 투표로 최종 결과를 결정한다."""

    candidate_tuple = tuple(candidates)
    non_empty = [candidate for candidate in candidate_tuple if candidate.raw_text.strip()]
    formatted = [candidate for candidate in candidate_tuple if candidate.valid_format]
    eligible = [candidate for candidate in formatted if candidate.rec_score >= min_rec_score]

    if not non_empty:
        return make_failure_result(
            ReadStatus.OCR_EMPTY,
            "모든 프레임에서 OCR 문자열이 비어 있습니다.",
            model_info,
            total_frames=total_frames,
            candidates=candidate_tuple,
            latency_ms=latency_ms,
        )
    if not formatted:
        return make_failure_result(
            ReadStatus.INVALID_FORMAT,
            "OCR 문자열 중 ASCII 숫자 네 자리 형식을 만족한 후보가 없습니다.",
            model_info,
            total_frames=total_frames,
            candidates=candidate_tuple,
            latency_ms=latency_ms,
        )
    if not eligible:
        return make_failure_result(
            ReadStatus.LOW_SCORE,
            f"형식이 유효한 후보가 최소 OCR 점수 {min_rec_score:.3f}에 미달했습니다.",
            model_info,
            total_frames=total_frames,
            candidates=candidate_tuple,
            latency_ms=latency_ms,
        )

    counts = Counter(candidate.normalized_text for candidate in eligible)
    scores: defaultdict[str, list[float]] = defaultdict(list)
    for candidate in eligible:
        scores[candidate.normalized_text].append(candidate.rec_score)

    ranked = sorted(
        counts,
        key=lambda plate: (-counts[plate], -sum(scores[plate]) / len(scores[plate]), plate),
    )
    winner = ranked[0]
    vote_count = counts[winner]
    valid_frames = len(eligible)
    vote_ratio = vote_count / valid_frames
    mean_rec_score = sum(scores[winner]) / len(scores[winner])
    second_ratio = counts[ranked[1]] / valid_frames if len(ranked) > 1 else 0.0

    common = dict(
        plate_number=None,
        total_frames=total_frames,
        valid_frames=valid_frames,
        vote_count=vote_count,
        vote_ratio=vote_ratio,
        mean_rec_score=mean_rec_score,
        candidates=candidate_tuple,
        latency_ms=latency_ms,
        model_info=model_info,
    )
    if vote_ratio - second_ratio < ambiguity_margin:
        return PlateReadResult(
            status=ReadStatus.AMBIGUOUS,
            error_message=(
                "최다 후보와 차순위 후보의 투표 비율 차이 "
                f"{vote_ratio - second_ratio:.3f}가 ambiguity_margin "
                f"{ambiguity_margin:.3f}보다 작습니다."
            ),
            **common,
        )
    if valid_frames < min_valid_frames:
        return PlateReadResult(
            status=ReadStatus.AMBIGUOUS,
            error_message=(
                f"유효 프레임 {valid_frames}개가 최소 요구값 "
                f"{min_valid_frames}개에 미달했습니다."
            ),
            **common,
        )
    if vote_ratio < min_vote_ratio:
        return PlateReadResult(
            status=ReadStatus.AMBIGUOUS,
            error_message=(
                f"최다 후보 투표 비율 {vote_ratio:.3f}가 최소 요구값 "
                f"{min_vote_ratio:.3f}에 미달했습니다."
            ),
            **common,
        )
    return PlateReadResult(
        status=ReadStatus.SUCCESS,
        plate_number=winner,
        error_message=None,
        **{key: value for key, value in common.items() if key != "plate_number"},
    )


class ManualTriggerSource:
    """Enter로 인식하고 q로 종료하는 임시 수동 트리거.

    실제 접근 감지 조건과 오탐률이 정해진 뒤 이 TriggerSource만 초음파 센서
    구현으로 교체하며, 현재 베이스라인에는 GPIO 결합을 넣지 않는다.
    """

    def wait_for_trigger(self) -> bool:
        """표준 입력에서 다음 사용자 명령을 기다린다."""

        print("Enter: 인식, q: 종료", file=sys.stderr, flush=True)
        line = sys.stdin.readline()
        if line == "":
            return False
        return line.strip().lower() != "q"


class Picamera2FrameSource:
    """Picamera2를 실제 카메라 모드에서만 불러오는 프레임 공급자."""

    def __init__(
        self,
        *,
        width: int,
        height: int,
        camera_index: int,
        warmup_ms: int,
    ) -> None:
        self._width = width
        self._height = height
        self._camera_index = camera_index
        self._warmup_ms = warmup_ms
        self._camera: Any | None = None
        self._next_frame_id = 1

    @staticmethod
    def list_cameras() -> list[Any]:
        """Picamera2가 보고하는 연결 카메라 목록을 반환한다."""

        Picamera2 = _import_picamera2()
        try:
            return list(Picamera2.global_camera_info())
        except Exception as exc:
            raise BaselineError(
                ReadStatus.CAMERA_ERROR,
                f"Picamera2 카메라 목록 조회에 실패했습니다: {exc}",
            ) from exc

    def open(self) -> None:
        """RGB888 카메라 구성을 만들고 워밍업까지 한 번 수행한다."""

        if self._camera is not None:
            return
        Picamera2 = _import_picamera2()
        camera: Any | None = None
        try:
            camera = Picamera2(camera_num=self._camera_index)
            config = camera.create_video_configuration(
                main={"size": (self._width, self._height), "format": "RGB888"}
            )
            camera.configure(config)
            camera.start()
            if self._warmup_ms:
                time.sleep(self._warmup_ms / 1000.0)
            self._camera = camera
        except Exception as exc:
            if camera is not None:
                try:
                    camera.close()
                except Exception:
                    LOGGER.exception("초기화 실패 후 Picamera2 장치 해제 중 오류가 발생했습니다.")
            raise BaselineError(
                ReadStatus.CAMERA_ERROR,
                f"Picamera2 카메라 {self._camera_index} 초기화에 실패했습니다: {exc}",
            ) from exc

    def capture(self) -> CapturedFrame:
        """현재 카메라에서 RGB888 NumPy 프레임 한 장을 촬영한다."""

        if self._camera is None:
            raise BaselineError(ReadStatus.CAMERA_ERROR, "카메라가 초기화되지 않았습니다.")
        np = _import_numpy()
        try:
            image = self._camera.capture_array("main")
        except Exception as exc:
            raise BaselineError(ReadStatus.CAMERA_ERROR, f"카메라 촬영에 실패했습니다: {exc}") from exc
        if not isinstance(image, np.ndarray):
            raise BaselineError(
                ReadStatus.CAMERA_ERROR,
                f"카메라가 numpy.ndarray 대신 {type(image).__name__}을 반환했습니다.",
            )
        if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
            raise BaselineError(
                ReadStatus.CAMERA_ERROR,
                f"RGB888 uint8 프레임이 아닙니다: shape={image.shape}, dtype={image.dtype}",
            )
        frame = CapturedFrame(
            frame_id=self._next_frame_id,
            captured_at=datetime.now(timezone.utc),
            image=image,
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        """예외 발생 여부와 관계없이 카메라 스트림과 장치를 해제한다."""

        camera, self._camera = self._camera, None
        if camera is None:
            return
        try:
            camera.stop()
        except Exception:
            LOGGER.exception("Picamera2 스트림 중지 중 오류가 발생했습니다.")
        try:
            camera.close()
        except Exception:
            LOGGER.exception("Picamera2 장치 해제 중 오류가 발생했습니다.")


def rank_frame_qualities(qualities: Sequence[FrameQuality]) -> tuple[FrameQuality, ...]:
    """품질 점수 내림차순, 동점이면 촬영 순번 오름차순으로 정렬한다."""

    return tuple(sorted(qualities, key=lambda quality: (-quality.score, quality.frame_id)))


class QualityFrameSelector:
    """전체 프레임 축소본의 노출 상태와 선명도로 처리 순서를 정한다."""

    def __init__(self, target_width: int = 320, target_height: int = 180) -> None:
        if target_width <= 0 or target_height <= 0:
            raise ValueError("프레임 품질 평가 크기는 0보다 커야 합니다.")
        self._target_width = target_width
        self._target_height = target_height

    def rank(self, frames: Sequence[CapturedFrame]) -> Sequence[FrameQuality]:
        """RGB 프레임마다 저해상도 품질 점수를 계산하여 전체 순위를 반환한다."""

        cv2 = _import_cv2()
        qualities: list[FrameQuality] = []
        for frame in frames:
            shape = getattr(frame.image, "shape", None)
            if shape is None or len(shape) != 3 or shape[2] != 3:
                raise BaselineError(
                    ReadStatus.CAMERA_ERROR,
                    f"frame_id={frame.frame_id} 품질 평가용 RGB 이미지 형식이 잘못되었습니다.",
                )
            resized = cv2.resize(
                frame.image,
                (self._target_width, self._target_height),
                interpolation=cv2.INTER_AREA,
            )
            gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
            sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            contrast = float(gray.std())
            mean_brightness = float(gray.mean())
            dark_ratio = float((gray <= 32).mean())
            bright_ratio = float((gray >= 223).mean())
            clipped_ratio = min(1.0, dark_ratio + bright_ratio)
            score = (
                math.log1p(max(0.0, sharpness)) * (1.0 - clipped_ratio)
                + 0.25 * math.log1p(max(0.0, contrast))
            )
            qualities.append(
                FrameQuality(
                    frame_id=frame.frame_id,
                    sharpness=sharpness,
                    contrast=contrast,
                    mean_brightness=mean_brightness,
                    dark_ratio=dark_ratio,
                    bright_ratio=bright_ratio,
                    score=score,
                )
            )
        return rank_frame_qualities(qualities)


class EasyOcrRuntime:
    """DBNet18과 recognizer가 공유하는 EasyOCR Reader 한 인스턴스."""

    def __init__(self, *, model_dir: str | None, download_enabled: bool) -> None:
        self._model_dir = model_dir
        self._download_enabled = download_enabled
        self._reader: Any | None = None
        self._library_version = "not-initialized"

    @property
    def model_info(self) -> ModelInfo:
        """현재 EasyOCR 모델 구성과 확인된 라이브러리 버전을 반환한다."""

        return ModelInfo(
            library="easyocr",
            library_version=self._library_version,
            model_name="dbnet18+standard(en)",
            model_dir=self._model_dir,
            engine="torch-cpu",
        )

    @property
    def reader(self) -> Any:
        """초기화된 공유 Reader를 반환한다."""

        if self._reader is None:
            raise BaselineError(ReadStatus.MODEL_ERROR, "EasyOCR Reader가 초기화되지 않았습니다.")
        return self._reader

    def open(self) -> None:
        """DBNet18 검출기와 영문 recognizer를 CPU용으로 한 번만 초기화한다."""

        if self._reader is not None:
            return
        command = " ".join(sys.argv)
        started = time.perf_counter()
        try:
            import easyocr
        except ImportError as exc:
            missing = getattr(exc, "name", None) or "easyocr"
            raise BaselineError(
                ReadStatus.DEPENDENCY_ERROR,
                f"OCR 의존성 '{missing}' import에 실패했습니다. EasyOCR와 CPU용 "
                f"PyTorch를 설치해야 합니다. 실행 명령: {command}. 원인: {exc}",
            ) from exc
        try:
            self._library_version = importlib.metadata.version("easyocr")
        except importlib.metadata.PackageNotFoundError:
            self._library_version = "unknown"

        kwargs: dict[str, Any] = {
            "lang_list": ["en"],
            "gpu": False,
            "detect_network": "dbnet18",
            "recog_network": "standard",
            "download_enabled": self._download_enabled,
            "detector": True,
            "recognizer": True,
            "verbose": False,
            "quantize": True,
        }
        if self._model_dir is not None:
            kwargs["model_storage_directory"] = self._model_dir
        try:
            self._reader = easyocr.Reader(**kwargs)
        except (ImportError, ModuleNotFoundError) as exc:
            missing = getattr(exc, "name", None) or "torch"
            raise BaselineError(
                ReadStatus.DEPENDENCY_ERROR,
                f"EasyOCR 런타임 의존성 '{missing}' 초기화에 실패했습니다. "
                f"실행 명령: {command}. 원인: {exc}",
            ) from exc
        except Exception as exc:
            raise BaselineError(
                ReadStatus.MODEL_ERROR,
                f"EasyOCR DBNet18/recognizer 초기화에 실패했습니다(command={command}): {exc}",
            ) from exc
        LOGGER.info("EasyOCR 공유 모델 초기화 시간: %.1f ms", (time.perf_counter() - started) * 1000.0)

    def close(self) -> None:
        """EasyOCR가 별도 close API를 제공하지 않아 Reader 참조를 해제한다."""

        self._reader = None


def _as_easyocr_batch(output: Any, name: str) -> Sequence[Any]:
    """EasyOCR detect의 단일 이미지 배치 출력을 검증해 첫 항목을 반환한다."""

    if not isinstance(output, (list, tuple)) or not output:
        raise BaselineError(ReadStatus.MODEL_ERROR, f"EasyOCR detect의 {name} 출력 형식이 잘못되었습니다.")
    batch = output[0]
    if not isinstance(batch, (list, tuple)):
        raise BaselineError(ReadStatus.MODEL_ERROR, f"EasyOCR detect의 {name}[0]이 목록이 아닙니다.")
    return batch


def easyocr_regions(
    horizontal_output: Any,
    free_output: Any,
) -> tuple[DetectedRegion, ...]:
    """EasyOCR의 수평 박스와 자유형 네 점을 공통 영역 계약으로 변환한다."""

    regions: list[DetectedRegion] = []
    for box in _as_easyocr_batch(horizontal_output, "horizontal_list"):
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            raise BaselineError(ReadStatus.MODEL_ERROR, "EasyOCR 수평 문자 박스 형식이 잘못되었습니다.")
        x_min, x_max, y_min, y_max = box
        try:
            quad = (
                (float(x_min), float(y_min)),
                (float(x_max), float(y_min)),
                (float(x_max), float(y_max)),
                (float(x_min), float(y_max)),
            )
            ordered = order_quad_points(quad)
        except (TypeError, ValueError, BaselineError) as exc:
            raise BaselineError(
                ReadStatus.MODEL_ERROR,
                f"EasyOCR 수평 문자 박스 좌표가 잘못되었습니다: {exc}",
            ) from exc
        regions.append(DetectedRegion(ordered, None, "dbnet18-horizontal"))

    for box in _as_easyocr_batch(free_output, "free_list"):
        try:
            ordered = order_quad_points(box)
        except BaselineError as exc:
            raise BaselineError(ReadStatus.MODEL_ERROR, f"EasyOCR 자유형 문자 박스가 잘못되었습니다: {exc}") from exc
        regions.append(DetectedRegion(ordered, None, "dbnet18-free"))
    return tuple(regions)


class DbNet18RegionDetector:
    """전체 RGB 프레임에서 DBNet18 문자 영역을 한 번 검출한다."""

    def __init__(
        self,
        runtime: EasyOcrRuntime,
        *,
        canvas_size: int | None,
        max_candidates: int = 10,
    ) -> None:
        self._runtime = runtime
        self._canvas_size = canvas_size
        self._max_candidates = max_candidates

    def detect(self, frame: CapturedFrame) -> Sequence[DetectedRegion]:
        """RGB 프레임을 EasyOCR 형식으로 한 번 변환해 4점 후보를 반환한다."""

        bgr_image = rgb_to_bgr(frame.image)
        try:
            horizontal_list, free_list = self._runtime.reader.detect(
                bgr_image,
                min_size=10,
                canvas_size=self._canvas_size,
                reformat=True,
                threshold=0.2,
                bbox_min_score=0.2,
                bbox_min_size=3,
                max_candidates=self._max_candidates,
            )
        except Exception as exc:
            raise BaselineError(ReadStatus.MODEL_ERROR, f"EasyOCR DBNet18 detect 실행에 실패했습니다: {exc}") from exc
        return easyocr_regions(horizontal_list, free_list)


def order_quad_points(
    quad: Sequence[Sequence[float]],
) -> tuple[
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
    tuple[float, float],
]:
    """임의 순서 네 점을 좌상·우상·우하·좌하 순서의 볼록 사각형으로 정렬한다."""

    if len(quad) != 4 or any(len(point) != 2 for point in quad):
        raise BaselineError(ReadStatus.NO_PLATE_REGION, "문자 영역은 (x, y) 꼭짓점 4개여야 합니다.")
    try:
        points = tuple((float(point[0]), float(point[1])) for point in quad)
    except (TypeError, ValueError) as exc:
        raise BaselineError(ReadStatus.NO_PLATE_REGION, "문자 영역 좌표를 숫자로 변환할 수 없습니다.") from exc
    if not all(math.isfinite(value) for point in points for value in point):
        raise BaselineError(ReadStatus.NO_PLATE_REGION, "문자 영역 좌표는 유한한 숫자여야 합니다.")

    center_x = sum(point[0] for point in points) / 4.0
    center_y = sum(point[1] for point in points) / 4.0
    cyclic = sorted(points, key=lambda point: math.atan2(point[1] - center_y, point[0] - center_x))
    top_left_index = min(range(4), key=lambda index: sum(cyclic[index]))
    ordered = tuple(cyclic[(top_left_index + offset) % 4] for offset in range(4))

    signed_cross_products: list[float] = []
    for index in range(4):
        current = ordered[index]
        following = ordered[(index + 1) % 4]
        next_following = ordered[(index + 2) % 4]
        signed_cross_products.append(
            (following[0] - current[0]) * (next_following[1] - following[1])
            - (following[1] - current[1]) * (next_following[0] - following[0])
        )
    if any(abs(value) <= 1e-6 for value in signed_cross_products) or not (
        all(value > 0.0 for value in signed_cross_products)
        or all(value < 0.0 for value in signed_cross_products)
    ):
        raise BaselineError(ReadStatus.NO_PLATE_REGION, "문자 영역이 유효한 볼록 사각형이 아닙니다.")
    return ordered  # type: ignore[return-value]


class PerspectiveRegionRectifier:
    """검출된 네 점을 보존해 1회의 perspective transform으로 정면화한다."""

    def rectify(self, frame: CapturedFrame, region: DetectedRegion) -> Any:
        """RGB 원본에서 네 점을 잘라 기울기와 원근이 보정된 RGB 이미지를 반환한다."""

        shape = getattr(frame.image, "shape", None)
        if shape is None or len(shape) < 2:
            raise BaselineError(ReadStatus.NO_PLATE_REGION, "프레임 이미지 크기를 확인할 수 없습니다.")
        image_height, image_width = int(shape[0]), int(shape[1])
        ordered = order_quad_points(region.quad)
        if any(
            x < 0.0 or x > image_width - 1 or y < 0.0 or y > image_height - 1
            for x, y in ordered
        ):
            raise BaselineError(ReadStatus.NO_PLATE_REGION, "문자 영역이 원본 프레임 범위를 벗어납니다.")

        top_left, top_right, bottom_right, bottom_left = ordered
        target_width = max(
            2,
            round(
                max(
                    math.dist(top_left, top_right),
                    math.dist(bottom_left, bottom_right),
                )
            )
            + 1,
        )
        target_height = max(
            2,
            round(
                max(
                    math.dist(top_left, bottom_left),
                    math.dist(top_right, bottom_right),
                )
            )
            + 1,
        )
        cv2 = _import_cv2()
        np = _import_numpy()
        source = np.asarray(ordered, dtype=np.float32)
        destination = np.asarray(
            (
                (0.0, 0.0),
                (float(target_width - 1), 0.0),
                (float(target_width - 1), float(target_height - 1)),
                (0.0, float(target_height - 1)),
            ),
            dtype=np.float32,
        )
        try:
            transform = cv2.getPerspectiveTransform(source, destination)
            rectified = cv2.warpPerspective(
                frame.image,
                transform,
                (target_width, target_height),
                flags=cv2.INTER_LINEAR,
            )
        except Exception as exc:
            raise BaselineError(ReadStatus.NO_PLATE_REGION, f"문자 영역 원근 보정에 실패했습니다: {exc}") from exc
        if getattr(rectified, "size", 0) == 0:
            raise BaselineError(ReadStatus.NO_PLATE_REGION, "원근 보정된 문자 영역이 비어 있습니다.")
        return rectified


class MinimalPlatePreprocessor:
    """기본은 원본 유지, 요청 시 높이 비율 resize만 수행하는 전처리기.

    grayscale, CLAHE, threshold, sharpening, 원근 보정은 현장 데이터로 개선이
    입증된 처리만 이 경계에 추가한다.
    """

    def __init__(self, resize_height: int | None = None) -> None:
        self._resize_height = resize_height

    def process(self, image: Any) -> Any:
        """검증되지 않은 명암·이진화 처리를 추가하지 않고 이미지를 반환한다."""

        if self._resize_height is None:
            return image
        shape = getattr(image, "shape", None)
        if shape is None or len(shape) < 2 or shape[0] <= 0 or shape[1] <= 0:
            raise BaselineError(ReadStatus.NO_PLATE_REGION, "전처리할 문자 영역 이미지 크기가 잘못되었습니다.")
        cv2 = _import_cv2()
        target_width = max(1, round(shape[1] * self._resize_height / shape[0]))
        return cv2.resize(image, (target_width, self._resize_height), interpolation=cv2.INTER_LINEAR)


class EasyOcrTextRecognizer:
    """원근 보정된 번호판 전체를 EasyOCR recognizer로 한 번 읽는 어댑터."""

    def __init__(self, runtime: EasyOcrRuntime) -> None:
        self._runtime = runtime

    @property
    def model_info(self) -> ModelInfo:
        """공유 EasyOCR 런타임의 재현 정보를 반환한다."""

        return self._runtime.model_info

    def open(self) -> None:
        """공유 Reader를 애플리케이션 시작 시 한 번 초기화한다."""

        self._runtime.open()

    def recognize(self, frame_id: int, image: Any) -> OcrCandidate:
        """보정된 전체 영역을 숫자 allowlist로 한 번 인식한다."""

        gray_image = rgb_to_gray(image)
        try:
            results = list(
                self._runtime.reader.recognize(
                    gray_image,
                    horizontal_list=None,
                    free_list=None,
                    decoder="greedy",
                    beamWidth=1,
                    batch_size=1,
                    workers=0,
                    allowlist="0123456789",
                    blocklist=None,
                    detail=1,
                    rotation_info=None,
                    paragraph=False,
                    contrast_ths=0.1,
                    adjust_contrast=0.5,
                    filter_ths=0.003,
                    reformat=True,
                    output_format="standard",
                )
            )
        except Exception as exc:
            raise BaselineError(
                ReadStatus.MODEL_ERROR,
                f"EasyOCR recognize 실행에 실패했습니다: {exc}",
            ) from exc
        if not results:
            return OcrCandidate(frame_id, "", "", 0.0, False)
        if len(results) > 1:
            LOGGER.warning("보정된 단일 영역에서 OCR 결과 %d건이 반환되어 첫 결과만 사용합니다.", len(results))
        raw_text, rec_score = _extract_easyocr_result(results[0])
        normalized = extract_plate_suffix(raw_text)
        return OcrCandidate(
            frame_id=frame_id,
            raw_text=raw_text,
            normalized_text=normalized,
            rec_score=rec_score,
            valid_format=is_valid_plate_number(normalized),
        )

    def close(self) -> None:
        """공유 EasyOCR Reader 참조를 해제한다."""

        self._runtime.close()


class StdoutResultPublisher:
    """기본 JSON 또는 자동화용 plain 결과를 표준 스트림에 발행한다.

    Jetson HTTP 전송이나 로컬 Outbox가 실제 계약으로 확정되면 핵심 인식
    파이프라인을 바꾸지 않고 ResultPublisher 구현만 교체한다.
    """

    def __init__(self, *, plain: bool) -> None:
        self._plain = plain

    def publish(self, result: PlateReadResult) -> None:
        """성공 plain 값만 stdout, plain 실패는 stderr, 기본 결과는 JSON으로 출력한다."""

        if self._plain:
            if result.status is ReadStatus.SUCCESS and result.plate_number is not None:
                print(result.plate_number, flush=True)
            else:
                detail = f": {result.error_message}" if result.error_message else ""
                print(f"{result.status.value}{detail}", file=sys.stderr, flush=True)
            return
        print(json.dumps(to_jsonable(result), ensure_ascii=False, sort_keys=True), flush=True)


class DebugArtifactWriter:
    """명시적으로 활성화됐을 때만 개인정보성 디버그 자료를 저장한다."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BaselineError(
                ReadStatus.CONFIG_ERROR,
                f"디버그 디렉터리를 준비할 수 없습니다({directory}): {exc}",
            ) from exc

    def write_frame(self, event_id: str, frame: CapturedFrame, image: Any, label: str) -> None:
        """이벤트·프레임·촬영시각이 포함된 이름으로 RGB 이미지를 저장한다."""

        timestamp = frame.captured_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        path = self._directory / f"{event_id}_f{frame.frame_id:03d}_{timestamp}_{label}.jpg"
        save_rgb_image(path, image)

    def write_candidate(self, event_id: str, frame: CapturedFrame, candidate: OcrCandidate) -> None:
        """프레임별 OCR 원문, 정규화 문자열, 점수를 JSON으로 저장한다."""

        timestamp = frame.captured_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        path = self._directory / f"{event_id}_f{frame.frame_id:03d}_{timestamp}_ocr.json"
        try:
            path.write_text(
                json.dumps(to_jsonable(candidate), ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            raise BaselineError(ReadStatus.CONFIG_ERROR, f"OCR 디버그 JSON 저장에 실패했습니다: {exc}") from exc


class PlateReader:
    """주입된 카메라·영역 검출·원근 보정·전처리·OCR 구현을 조합한다."""

    def __init__(
        self,
        *,
        frame_source: FrameSource,
        frame_selector: FrameSelector,
        detector: RegionDetector,
        rectifier: RegionRectifier,
        preprocessor: PlatePreprocessor,
        recognizer: TextRecognizer,
        frame_count: int,
        frame_interval_ms: int,
        min_rec_score: float,
        min_valid_frames: int,
        min_vote_ratio: float,
        ambiguity_margin: float,
        debug_writer: DebugArtifactWriter | None = None,
    ) -> None:
        self._frame_source = frame_source
        self._frame_selector = frame_selector
        self._detector = detector
        self._rectifier = rectifier
        self._preprocessor = preprocessor
        self._recognizer = recognizer
        self._frame_count = frame_count
        self._frame_interval_ms = frame_interval_ms
        self._min_rec_score = min_rec_score
        self._min_valid_frames = min_valid_frames
        self._min_vote_ratio = min_vote_ratio
        self._ambiguity_margin = ambiguity_margin
        self._debug_writer = debug_writer
        self._opened = False

    def __enter__(self) -> PlateReader:
        """카메라와 OCR 모델을 이벤트 반복 전에 각각 한 번 초기화한다."""

        self._frame_source.open()
        try:
            self._recognizer.open()
        except Exception:
            self._frame_source.close()
            raise
        self._opened = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """정상·예외 종료 모두에서 OCR 참조와 카메라 자원을 해제한다."""

        try:
            self._recognizer.close()
        finally:
            self._frame_source.close()
            self._opened = False

    def read_once(self) -> PlateReadResult:
        """대표 프레임에서 영역을 찾고 같은 4점을 전체 프레임에 재사용한다."""

        if not self._opened:
            raise BaselineError(ReadStatus.CONFIG_ERROR, "PlateReader는 with 문 안에서 사용해야 합니다.")
        started = time.perf_counter()
        event_id = uuid4().hex
        candidates: list[OcrCandidate] = []
        captured_frames = 0
        try:
            frames: list[CapturedFrame] = []
            for index in range(self._frame_count):
                frame = self._frame_source.capture()
                frames.append(frame)
                captured_frames += 1
                if self._debug_writer is not None:
                    self._debug_writer.write_frame(event_id, frame, frame.image, "frame")
                if index + 1 < self._frame_count and self._frame_interval_ms:
                    time.sleep(self._frame_interval_ms / 1000.0)

            qualities = tuple(self._frame_selector.rank(frames))
            frame_by_id = {frame.frame_id: frame for frame in frames}
            ranked_ids = [quality.frame_id for quality in qualities]
            if len(qualities) != len(frames) or set(ranked_ids) != set(frame_by_id):
                raise BaselineError(
                    ReadStatus.CONFIG_ERROR,
                    "FrameSelector가 입력 프레임 전체에 대한 유효한 순위를 반환하지 않았습니다.",
                )
            LOGGER.info(
                "이벤트 %s 프레임 품질 순위: %s",
                event_id,
                ", ".join(
                    f"f{quality.frame_id}={quality.score:.3f}" for quality in qualities
                ),
            )

            selected_attempt: _RegionAttempt | None = None
            selected_frame: CapturedFrame | None = None
            diagnostic_candidates: list[OcrCandidate] = []
            detected_region_count = 0
            anchor_qualities = qualities[: min(2, len(qualities))]
            for quality in anchor_qualities:
                anchor_frame = frame_by_id[quality.frame_id]
                try:
                    regions = tuple(self._detector.detect(anchor_frame))
                except BaselineError as exc:
                    if exc.status is not ReadStatus.NO_PLATE_REGION:
                        raise
                    LOGGER.warning(
                        "대표 frame_id=%d DBNet18 영역 검출에 실패했습니다: %s",
                        anchor_frame.frame_id,
                        exc,
                    )
                    continue
                if not regions:
                    LOGGER.warning("대표 frame_id=%d에서 DBNet18 문자 영역을 찾지 못했습니다.", anchor_frame.frame_id)
                    continue

                detected_region_count += len(regions)
                attempts: list[_RegionAttempt] = []
                for region in regions:
                    try:
                        rectified = self._rectifier.rectify(anchor_frame, region)
                    except BaselineError as exc:
                        if exc.status is not ReadStatus.NO_PLATE_REGION:
                            raise
                        LOGGER.warning(
                            "대표 frame_id=%d의 문자 영역 보정에 실패했습니다: %s",
                            anchor_frame.frame_id,
                            exc,
                        )
                        continue
                    processed = self._preprocessor.process(rectified)
                    candidate = self._recognizer.recognize(anchor_frame.frame_id, processed)
                    attempts.append(_RegionAttempt(region, rectified, candidate))

                diagnostic_attempt = best_region_attempt(attempts, require_valid_format=False)
                if diagnostic_attempt is not None:
                    diagnostic_candidates.append(diagnostic_attempt.candidate)
                selected_attempt = best_region_attempt(attempts, require_valid_format=True)
                if selected_attempt is not None:
                    selected_frame = anchor_frame
                    LOGGER.info(
                        "이벤트 %s 대표 frame_id=%d의 %s 영역을 선택했습니다.",
                        event_id,
                        anchor_frame.frame_id,
                        selected_attempt.region.source,
                    )
                    break
                LOGGER.warning(
                    "대표 frame_id=%d의 문자 영역 %d개에서 유효한 끝 4자리를 얻지 못했습니다.",
                    anchor_frame.frame_id,
                    len(regions),
                )

            if selected_attempt is None or selected_frame is None:
                latency_ms = (time.perf_counter() - started) * 1000.0
                if detected_region_count == 0 or not diagnostic_candidates:
                    return make_failure_result(
                        ReadStatus.NO_PLATE_REGION,
                        "품질 상위 2프레임에서 사용 가능한 DBNet18 문자 영역을 얻지 못했습니다.",
                        self._recognizer.model_info,
                        total_frames=captured_frames,
                        candidates=diagnostic_candidates,
                        latency_ms=latency_ms,
                    )
                return aggregate_candidates(
                    diagnostic_candidates,
                    total_frames=captured_frames,
                    min_rec_score=self._min_rec_score,
                    min_valid_frames=self._min_valid_frames,
                    min_vote_ratio=self._min_vote_ratio,
                    ambiguity_margin=self._ambiguity_margin,
                    latency_ms=latency_ms,
                    model_info=self._recognizer.model_info,
                )

            candidate_by_frame_id = {selected_frame.frame_id: selected_attempt.candidate}
            if self._debug_writer is not None:
                self._debug_writer.write_frame(
                    event_id,
                    selected_frame,
                    selected_attempt.rectified,
                    "rectified",
                )
                self._debug_writer.write_candidate(event_id, selected_frame, selected_attempt.candidate)

            for frame in frames:
                if frame.frame_id == selected_frame.frame_id:
                    continue
                try:
                    rectified = self._rectifier.rectify(frame, selected_attempt.region)
                except BaselineError as exc:
                    if exc.status is not ReadStatus.NO_PLATE_REGION:
                        raise
                    LOGGER.warning(
                        "frame_id=%d에서 대표 4점 영역을 재사용할 수 없습니다: %s",
                        frame.frame_id,
                        exc,
                    )
                    continue
                if self._debug_writer is not None:
                    self._debug_writer.write_frame(event_id, frame, rectified, "rectified")
                processed = self._preprocessor.process(rectified)
                candidate = self._recognizer.recognize(frame.frame_id, processed)
                candidate_by_frame_id[frame.frame_id] = candidate
                if self._debug_writer is not None:
                    self._debug_writer.write_candidate(event_id, frame, candidate)

            candidates = [
                candidate_by_frame_id[frame.frame_id]
                for frame in frames
                if frame.frame_id in candidate_by_frame_id
            ]
        except BaselineError as exc:
            LOGGER.exception("인식 이벤트가 실패했습니다: %s", exc)
            return make_failure_result(
                exc.status,
                str(exc),
                self._recognizer.model_info,
                total_frames=captured_frames,
                candidates=candidates,
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )

        latency_ms = (time.perf_counter() - started) * 1000.0
        LOGGER.info("이벤트 %s 처리 시간: %.1f ms", event_id, latency_ms)
        return aggregate_candidates(
            candidates,
            total_frames=captured_frames,
            min_rec_score=self._min_rec_score,
            min_valid_frames=self._min_valid_frames,
            min_vote_ratio=self._min_vote_ratio,
            ambiguity_margin=self._ambiguity_margin,
            latency_ms=latency_ms,
            model_info=self._recognizer.model_info,
        )


def _import_picamera2() -> Any:
    try:
        from picamera2 import Picamera2
    except ImportError as exc:
        raise BaselineError(
            ReadStatus.DEPENDENCY_ERROR,
            "Picamera2 import에 실패했습니다. Raspberry Pi OS의 python3-picamera2 "
            "패키지를 우선 사용하고, 가상환경은 --system-site-packages로 만드세요. "
            f"원인: {exc}",
        ) from exc
    return Picamera2


def _import_numpy() -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise BaselineError(
            ReadStatus.DEPENDENCY_ERROR,
            f"NumPy import에 실패했습니다. 설치 대상 패키지: numpy. 원인: {exc}",
        ) from exc
    return np


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise BaselineError(
            ReadStatus.DEPENDENCY_ERROR,
            "OpenCV import에 실패했습니다. Raspberry Pi OS에서는 python3-opencv를 "
            f"우선 검토하세요. 원인: {exc}",
        ) from exc
    return cv2


def _extract_easyocr_result(result: Any) -> tuple[str, float]:
    """EasyOCR standard `(box, text, confidence)` 결과를 검증한다."""

    if not isinstance(result, (list, tuple)) or len(result) < 3:
        raise BaselineError(
            ReadStatus.MODEL_ERROR,
            f"지원하지 않는 EasyOCR 결과 형식입니다: {type(result).__name__}",
        )
    raw_text = str(result[1] or "")
    try:
        rec_score = float(result[2])
    except (TypeError, ValueError) as exc:
        raise BaselineError(
            ReadStatus.MODEL_ERROR,
            f"EasyOCR confidence를 숫자로 변환할 수 없습니다: {result[2]!r}",
        ) from exc
    if not math.isfinite(rec_score):
        raise BaselineError(ReadStatus.MODEL_ERROR, f"EasyOCR confidence가 유한하지 않습니다: {rec_score}")
    return raw_text, rec_score


def _validate_rgb_image(image: Any) -> None:
    """Picamera2부터 보정 단계까지 유지하는 RGB uint8 배열 계약을 검사한다."""

    np = _import_numpy()
    shape = getattr(image, "shape", None)
    dtype = getattr(image, "dtype", None)
    if shape is None or len(shape) != 3 or shape[2] != 3 or dtype != np.uint8:
        raise BaselineError(
            ReadStatus.MODEL_ERROR,
            f"EasyOCR 입력은 RGB uint8 HxWx3 배열이어야 합니다: shape={shape}, dtype={dtype}",
        )


def rgb_to_bgr(image: Any) -> Any:
    """RGB uint8 이미지를 DBNet18이 받는 OpenCV BGR 배열로 한 번 변환한다."""

    _validate_rgb_image(image)
    cv2 = _import_cv2()
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def rgb_to_gray(image: Any) -> Any:
    """RGB uint8 이미지를 recognizer가 받는 단일 채널 배열로 한 번 변환한다."""

    _validate_rgb_image(image)
    cv2 = _import_cv2()
    return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)


def save_rgb_image(path: Path, image: Any) -> None:
    """RGB 배열을 OpenCV가 기대하는 BGR로 변환하여 이미지 파일로 저장한다."""

    cv2 = _import_cv2()
    try:
        bgr_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        saved = cv2.imwrite(str(path), bgr_image)
    except Exception as exc:
        raise BaselineError(ReadStatus.CONFIG_ERROR, f"이미지 저장에 실패했습니다({path}): {exc}") from exc
    if not saved:
        raise BaselineError(ReadStatus.CONFIG_ERROR, f"OpenCV가 이미지 저장에 실패했습니다: {path}")


def build_parser() -> argparse.ArgumentParser:
    """베이스라인 실행 모드와 카메라·OCR·집계 설정 CLI를 정의한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--probe-camera", action="store_true", help="카메라 목록과 한 프레임을 점검합니다.")
    modes.add_argument("--capture-frame", metavar="PATH", help="카메라 점검용 전체 프레임을 저장합니다.")
    modes.add_argument("--once", action="store_true", help="인식 이벤트를 한 번 실행합니다.")
    modes.add_argument("--interactive", action="store_true", help="Enter로 반복 인식하고 q로 종료합니다.")
    modes.add_argument("--self-test", action="store_true", help="하드웨어 비의존 순수 로직 테스트를 실행합니다.")

    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--warmup-ms", type=int, default=1000)
    parser.add_argument("--frame-count", type=int, default=6)
    parser.add_argument("--frame-interval-ms", type=int, default=120)
    parser.add_argument("--resize-height", type=int, default=None)
    parser.add_argument("--model-dir", default=None)
    parser.add_argument(
        "--detector-canvas-size",
        type=int,
        default=None,
        help="DBNet18 입력의 짧은 변 길이입니다. 기본값은 원본 크기를 유지합니다.",
    )
    parser.add_argument("--disable-model-download", action="store_true")
    parser.add_argument("--min-rec-score", type=float, default=0.60)
    parser.add_argument("--min-valid-frames", type=int, default=2)
    parser.add_argument("--min-vote-ratio", type=float, default=0.50)
    parser.add_argument("--ambiguity-margin", type=float, default=0.15)
    parser.add_argument("--plain", action="store_true")
    parser.add_argument("--debug-dir", type=Path, default=None)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    """실행 전에 수치 범위와 모드별 필수 옵션을 검증한다."""

    if args.width <= 0 or args.height <= 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "카메라 width와 height는 0보다 커야 합니다.")
    if args.camera_index < 0 or args.warmup_ms < 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "camera-index와 warmup-ms는 음수일 수 없습니다.")
    if not (args.once or args.interactive):
        # 카메라 점검과 프레임 저장은 OCR 설정이나 모델 경로에 의존하지 않는다.
        return
    if args.frame_count <= 0 or args.frame_interval_ms < 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "frame-count는 양수, frame-interval-ms는 0 이상이어야 합니다.")
    if args.min_valid_frames <= 0 or args.min_valid_frames > args.frame_count:
        raise BaselineError(
            ReadStatus.CONFIG_ERROR,
            "min-valid-frames는 1 이상이고 frame-count 이하여야 합니다.",
        )
    if args.resize_height is not None and args.resize_height <= 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "resize-height는 0보다 커야 합니다.")
    if args.detector_canvas_size is not None and args.detector_canvas_size <= 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "detector-canvas-size는 0보다 커야 합니다.")
    for name in ("min_rec_score", "min_vote_ratio", "ambiguity_margin"):
        value = getattr(args, name)
        if not 0.0 <= value <= 1.0:
            raise BaselineError(ReadStatus.CONFIG_ERROR, f"{name.replace('_', '-')}는 0~1 범위여야 합니다.")
    if args.model_dir is not None:
        model_path = Path(args.model_dir)
        if model_path.exists() and not model_path.is_dir():
            raise BaselineError(ReadStatus.CONFIG_ERROR, f"model-dir가 디렉터리가 아닙니다: {args.model_dir}")


def create_frame_source(args: argparse.Namespace) -> Picamera2FrameSource:
    """검증된 CLI 설정으로 Picamera2 프레임 공급자를 만든다."""

    return Picamera2FrameSource(
        width=args.width,
        height=args.height,
        camera_index=args.camera_index,
        warmup_ms=args.warmup_ms,
    )


def probe_camera(args: argparse.Namespace) -> dict[str, Any]:
    """OCR 모델 없이 Picamera2 목록·초기화·한 프레임 촬영을 점검한다."""

    cameras = Picamera2FrameSource.list_cameras()
    source = create_frame_source(args)
    source.open()
    try:
        frame = source.capture()
    finally:
        source.close()
    return {
        "status": "SUCCESS",
        "picamera2_import": True,
        "cameras": to_jsonable(cameras),
        "camera_count": len(cameras),
        "frame_shape": list(frame.image.shape),
        "frame_dtype": str(frame.image.dtype),
        "captured_at": frame.captured_at.isoformat(),
    }


def capture_calibration_frame(args: argparse.Namespace, path: Path) -> dict[str, Any]:
    """OCR 모델 없이 전체 카메라 프레임을 지정한 경로에 저장한다."""

    source = create_frame_source(args)
    source.open()
    try:
        frame = source.capture()
        save_rgb_image(path, frame.image)
    finally:
        source.close()
    return {
        "status": "SUCCESS",
        "path": str(path),
        "frame_shape": list(frame.image.shape),
        "frame_dtype": str(frame.image.dtype),
        "captured_at": frame.captured_at.isoformat(),
    }


def build_plate_reader(args: argparse.Namespace) -> tuple[PlateReader, EasyOcrTextRecognizer]:
    """CLI 설정과 교체 가능한 기본 구현체로 PlateReader를 조립한다."""

    runtime = EasyOcrRuntime(
        model_dir=args.model_dir,
        download_enabled=not args.disable_model_download,
    )
    recognizer = EasyOcrTextRecognizer(runtime)
    debug_writer = DebugArtifactWriter(args.debug_dir) if args.debug_dir is not None else None
    reader = PlateReader(
        frame_source=create_frame_source(args),
        frame_selector=QualityFrameSelector(),
        detector=DbNet18RegionDetector(runtime, canvas_size=args.detector_canvas_size),
        rectifier=PerspectiveRegionRectifier(),
        preprocessor=MinimalPlatePreprocessor(args.resize_height),
        recognizer=recognizer,
        frame_count=args.frame_count,
        frame_interval_ms=args.frame_interval_ms,
        min_rec_score=args.min_rec_score,
        min_valid_frames=args.min_valid_frames,
        min_vote_ratio=args.min_vote_ratio,
        ambiguity_margin=args.ambiguity_margin,
        debug_writer=debug_writer,
    )
    return reader, recognizer


class _TestFrameSource:
    """내장 테스트에서 카메라 없이 순번 프레임을 공급한다."""

    def __init__(self, frame_count: int) -> None:
        self._frames = [
            CapturedFrame(index, datetime.now(timezone.utc), object())
            for index in range(1, frame_count + 1)
        ]
        self._next_index = 0

    def open(self) -> None:
        self._next_index = 0

    def capture(self) -> CapturedFrame:
        frame = self._frames[self._next_index]
        self._next_index += 1
        return frame

    def close(self) -> None:
        return None


class _TestFrameSelector:
    """내장 테스트가 지정한 순서로 대표 프레임을 반환한다."""

    def __init__(self, frame_ids: Sequence[int]) -> None:
        self._frame_ids = tuple(frame_ids)

    def rank(self, frames: Sequence[CapturedFrame]) -> Sequence[FrameQuality]:
        del frames
        return tuple(
            FrameQuality(frame_id, 1.0, 1.0, 128.0, 0.0, 0.0, float(len(self._frame_ids) - index))
            for index, frame_id in enumerate(self._frame_ids)
        )


class _TestRegionDetector:
    """프레임별 준비된 영역과 실제 호출 순서를 기록한다."""

    def __init__(self, regions_by_frame: Mapping[int, Sequence[DetectedRegion]]) -> None:
        self._regions_by_frame = regions_by_frame
        self.calls: list[int] = []

    def detect(self, frame: CapturedFrame) -> Sequence[DetectedRegion]:
        self.calls.append(frame.frame_id)
        return self._regions_by_frame.get(frame.frame_id, ())


class _TestRegionRectifier:
    """재사용된 영역을 확인할 수 있도록 `(frame_id, source)`를 반환한다."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def rectify(self, frame: CapturedFrame, region: DetectedRegion) -> tuple[int, str]:
        value = (frame.frame_id, region.source)
        self.calls.append(value)
        return value


class _TestTextRecognizer:
    """영역 출처별 준비된 문자열을 반환하고 OCR 호출을 기록한다."""

    MODEL_INFO = ModelInfo("test", "1", "test-model", None, "test-engine")

    def __init__(self, texts: Mapping[tuple[int, str], str] | None = None) -> None:
        self._texts = texts or {}
        self.calls: list[tuple[int, str]] = []

    @property
    def model_info(self) -> ModelInfo:
        return self.MODEL_INFO

    def open(self) -> None:
        return None

    def recognize(self, frame_id: int, image: Any) -> OcrCandidate:
        _, source = image
        key = (frame_id, source)
        self.calls.append(key)
        raw_text = self._texts.get(key, "1128")
        normalized = extract_plate_suffix(raw_text)
        score = 0.90 if raw_text else 0.0
        return OcrCandidate(
            frame_id,
            raw_text,
            normalized,
            score,
            is_valid_plate_number(normalized),
        )

    def close(self) -> None:
        return None


class BaselineLogicTests(unittest.TestCase):
    """카메라·OCR·네트워크 없이 실행하는 순수 로직 회귀 테스트."""

    MODEL_INFO = ModelInfo("test", "1", "test-model", None, "test-engine")

    @staticmethod
    def region(source: str) -> DetectedRegion:
        return DetectedRegion(
            ((1.0, 1.0), (9.0, 1.0), (9.0, 5.0), (1.0, 5.0)),
            None,
            source,
        )

    def make_pipeline(
        self,
        *,
        regions_by_frame: Mapping[int, Sequence[DetectedRegion]],
        texts: Mapping[tuple[int, str], str] | None = None,
    ) -> tuple[PlateReader, _TestRegionDetector, _TestRegionRectifier, _TestTextRecognizer]:
        detector = _TestRegionDetector(regions_by_frame)
        rectifier = _TestRegionRectifier()
        recognizer = _TestTextRecognizer(texts)
        reader = PlateReader(
            frame_source=_TestFrameSource(6),
            frame_selector=_TestFrameSelector((3, 2, 1, 4, 5, 6)),
            detector=detector,
            rectifier=rectifier,
            preprocessor=MinimalPlatePreprocessor(),
            recognizer=recognizer,
            frame_count=6,
            frame_interval_ms=0,
            min_rec_score=0.60,
            min_valid_frames=2,
            min_vote_ratio=0.50,
            ambiguity_margin=0.15,
        )
        return reader, detector, rectifier, recognizer

    @staticmethod
    def candidate(frame_id: int, text: str, score: float) -> OcrCandidate:
        normalized = extract_plate_suffix(text)
        return OcrCandidate(frame_id, text, normalized, score, is_valid_plate_number(normalized))

    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
        *,
        min_rec_score: float = 0.60,
        min_valid_frames: int = 3,  # min_vailid_ratio = 0.5를 넣는 대신 임시 조치로 숫자 2 -> 3
        min_vote_ratio: float = 0.50,
        ambiguity_margin: float = 0.15,
    ) -> PlateReadResult:
        return aggregate_candidates(
            candidates,
            total_frames=len(candidates),
            min_rec_score=min_rec_score,
            min_valid_frames=min_valid_frames,
            min_vote_ratio=min_vote_ratio,
            ambiguity_margin=ambiguity_margin,
            latency_ms=1.0,
            model_info=self.MODEL_INFO,
        )

    def test_frame_qualities_are_ranked_by_score_then_frame_id(self) -> None:
        qualities = [
            FrameQuality(3, 1.0, 1.0, 128.0, 0.0, 0.0, 2.0),
            FrameQuality(2, 1.0, 1.0, 128.0, 0.0, 0.0, 3.0),
            FrameQuality(1, 1.0, 1.0, 128.0, 0.0, 0.0, 3.0),
        ]
        self.assertEqual(
            [quality.frame_id for quality in rank_frame_qualities(qualities)],
            [1, 2, 3],
        )

    def test_frame_selector_rejects_nonpositive_target_size(self) -> None:
        with self.assertRaises(ValueError):
            QualityFrameSelector(target_width=0)

    def test_quad_points_are_ordered_clockwise_from_top_left(self) -> None:
        unordered = ((8.0, 6.0), (2.0, 1.0), (1.0, 5.0), (9.0, 2.0))
        self.assertEqual(
            order_quad_points(unordered),
            ((2.0, 1.0), (9.0, 2.0), (8.0, 6.0), (1.0, 5.0)),
        )

    def test_degenerate_quad_is_rejected(self) -> None:
        with self.assertRaises(BaselineError):
            order_quad_points(((0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)))

    def test_axis_aligned_quad_keeps_expected_rectified_shape(self) -> None:
        np = _import_numpy()
        frame = CapturedFrame(1, datetime.now(timezone.utc), np.zeros((8, 12, 3), dtype=np.uint8))
        region = DetectedRegion(
            quad=((2.0, 1.0), (8.0, 1.0), (8.0, 5.0), (2.0, 5.0)),
            detector_score=None,
            source="test",
        )
        rectified = PerspectiveRegionRectifier().rectify(frame, region)
        self.assertEqual(rectified.shape, (5, 7, 3))

    def test_easyocr_boxes_are_converted_to_common_quads(self) -> None:
        regions = easyocr_regions(
            [[[2, 8, 1, 5]]],
            [[[[10, 2], [15, 3], [14, 7], [9, 6]]]],
        )
        self.assertEqual(len(regions), 2)
        self.assertEqual(regions[0].quad, ((2.0, 1.0), (8.0, 1.0), (8.0, 5.0), (2.0, 5.0)))
        self.assertEqual(regions[0].source, "dbnet18-horizontal")
        self.assertEqual(regions[1].source, "dbnet18-free")

    def test_dbnet_detector_uses_bgr_once_and_preserves_native_canvas(self) -> None:
        np = _import_numpy()

        class FakeReader:
            def __init__(self) -> None:
                self.image: Any | None = None
                self.kwargs: dict[str, Any] = {}

            def detect(self, image: Any, **kwargs: Any) -> tuple[Any, Any]:
                self.image = image
                self.kwargs = kwargs
                return [[[1, 3, 1, 2]]], [[]]

        class FakeRuntime:
            def __init__(self) -> None:
                self.reader = FakeReader()

        runtime = FakeRuntime()
        rgb = np.zeros((4, 5, 3), dtype=np.uint8)
        rgb[0, 0] = (10, 20, 30)
        frame = CapturedFrame(1, datetime.now(timezone.utc), rgb)
        regions = DbNet18RegionDetector(runtime, canvas_size=None).detect(frame)  # type: ignore[arg-type]
        self.assertEqual(len(regions), 1)
        self.assertEqual(tuple(runtime.reader.image[0, 0]), (30, 20, 10))
        self.assertIsNone(runtime.reader.kwargs["canvas_size"])

    def test_easyocr_recognizer_reads_rectified_region_as_one_numeric_line(self) -> None:
        np = _import_numpy()

        class FakeReader:
            def __init__(self) -> None:
                self.kwargs: dict[str, Any] = {}

            def recognize(self, image: Any, **kwargs: Any) -> list[Any]:
                self.kwargs = kwargs
                return [([[0, 0], [1, 0], [1, 1], [0, 1]], "010785", 0.91)]

        class FakeRuntime:
            def __init__(self) -> None:
                self.reader = FakeReader()
                self.model_info = BaselineLogicTests.MODEL_INFO

            def open(self) -> None:
                return None

            def close(self) -> None:
                return None

        runtime = FakeRuntime()
        recognizer = EasyOcrTextRecognizer(runtime)  # type: ignore[arg-type]
        image = np.zeros((8, 20, 3), dtype=np.uint8)
        candidate = recognizer.recognize(7, image)
        self.assertEqual(candidate.normalized_text, "0785")
        self.assertTrue(candidate.valid_format)
        self.assertEqual(runtime.reader.kwargs["allowlist"], "0123456789")
        self.assertIsNone(runtime.reader.kwargs["horizontal_list"])
        self.assertIsNone(runtime.reader.kwargs["free_list"])

    def test_dbnet_runs_only_on_best_frame_when_it_yields_valid_region(self) -> None:
        plate_region = self.region("plate")
        reader, detector, rectifier, recognizer = self.make_pipeline(
            regions_by_frame={3: (plate_region,)},
        )
        with reader:
            result = reader.read_once()
        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(detector.calls, [3])
        self.assertEqual(len(recognizer.calls), 6)
        self.assertEqual(recognizer.calls.count((3, "plate")), 1)
        self.assertTrue(all(source == "plate" for _, source in rectifier.calls))

    def test_dbnet_falls_back_to_second_ranked_frame(self) -> None:
        plate_region = self.region("plate")
        reader, detector, _, recognizer = self.make_pipeline(
            regions_by_frame={2: (plate_region,)},
        )
        with reader:
            result = reader.read_once()
        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(detector.calls, [3, 2])
        self.assertEqual(len(recognizer.calls), 6)

    def test_valid_region_is_selected_and_cached_before_temporal_voting(self) -> None:
        sign_region = self.region("sign")
        plate_region = self.region("plate")
        reader, detector, rectifier, recognizer = self.make_pipeline(
            regions_by_frame={3: (sign_region, plate_region)},
            texts={(3, "sign"): "AB"},
        )
        with reader:
            result = reader.read_once()
        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(detector.calls, [3])
        self.assertEqual(recognizer.calls.count((3, "sign")), 1)
        self.assertEqual(recognizer.calls.count((3, "plate")), 1)
        self.assertEqual(len(recognizer.calls), 7)
        reused_sources = [source for frame_id, source in rectifier.calls if frame_id != 3]
        self.assertEqual(reused_sources, ["plate"] * 5)

    def test_four_ascii_digits_are_valid(self) -> None:
        self.assertTrue(is_valid_plate_number(normalize_plate_text("1234")))

    def test_spaces_and_hyphens_are_removed(self) -> None:
        self.assertEqual(normalize_plate_text(" 12 - 34 "), "1234")

    def test_full_width_digits_are_nfkc_normalized(self) -> None:
        self.assertEqual(normalize_plate_text("１２３４"), "1234")

    def test_three_and_five_digits_are_rejected(self) -> None:
        self.assertFalse(is_valid_plate_number("123"))
        self.assertFalse(is_valid_plate_number("12345"))

    def test_last_four_digits_are_extracted_without_character_guessing(self) -> None:
        self.assertEqual(extract_plate_suffix("010-785"), "0785")
        self.assertEqual(extract_plate_suffix("12가1128"), "1128")
        self.assertEqual(extract_plate_suffix("O234"), "O234")

    def test_letters_are_rejected(self) -> None:
        self.assertFalse(is_valid_plate_number(normalize_plate_text("12A4")))

    def test_letter_o_is_not_force_replaced(self) -> None:
        self.assertEqual(normalize_plate_text("O234"), "O234")
        self.assertFalse(is_valid_plate_number(normalize_plate_text("O234")))

    def test_single_winner_succeeds(self) -> None:
        result = self.aggregate(
            [self.candidate(1, "1234", 0.9), self.candidate(2, "1234", 0.8), self.candidate(3, "5678", 0.7)]
        )
        self.assertEqual(result.status, ReadStatus.SUCCESS)
        self.assertEqual(result.plate_number, "1234")

    def test_low_score_candidates_are_excluded(self) -> None:
        result = self.aggregate(
            [self.candidate(1, "1234", 0.59), self.candidate(2, "1234", 0.58)]
        )
        self.assertEqual(result.status, ReadStatus.LOW_SCORE)

    def test_tie_is_ambiguous(self) -> None:
        result = self.aggregate(
            [self.candidate(1, "1234", 0.9), self.candidate(2, "5678", 0.9)]
        )
        self.assertEqual(result.status, ReadStatus.AMBIGUOUS)
        self.assertIsNone(result.plate_number)

    def test_minimum_valid_frames_is_enforced(self) -> None:
        result = self.aggregate([self.candidate(1, "1234", 0.9)], min_valid_frames=2)
        self.assertEqual(result.status, ReadStatus.AMBIGUOUS)
        self.assertIn("유효 프레임", result.error_message or "")

    def test_minimum_vote_ratio_is_enforced(self) -> None:
        result = self.aggregate(
            [
                self.candidate(1, "1234", 0.9),
                self.candidate(2, "1234", 0.8),
                self.candidate(3, "5678", 0.9),
                self.candidate(4, "9012", 0.9),
            ],
            min_vote_ratio=0.75,
            ambiguity_margin=0.10,
        )
        self.assertEqual(result.status, ReadStatus.AMBIGUOUS)
        self.assertIn("투표 비율", result.error_message or "")


def run_self_tests() -> int:
    """선택 의존성을 불러오지 않고 내장 unittest 모음을 실행한다."""

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BaselineLogicTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    summary = {
        "status": "SUCCESS" if result.wasSuccessful() else "FAILED",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() else 1


def _exit_code(status: ReadStatus) -> int:
    return 0 if status is ReadStatus.SUCCESS else 2


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 모드를 선택하고 최상위 오류를 구조화된 결과로 변환한다."""

    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.self_test:
        return run_self_tests()

    recognizer: EasyOcrTextRecognizer | None = None
    try:
        validate_args(args)
        if args.probe_camera:
            print(json.dumps(probe_camera(args), ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        if args.capture_frame is not None:
            output = capture_calibration_frame(args, Path(args.capture_frame))
            print(json.dumps(output, ensure_ascii=False, sort_keys=True), flush=True)
            return 0

        reader, recognizer = build_plate_reader(args)
        publisher = StdoutResultPublisher(plain=args.plain)
        with reader:
            if args.once:
                result = reader.read_once()
                publisher.publish(result)
                return _exit_code(result.status)
            trigger = ManualTriggerSource()
            while trigger.wait_for_trigger():
                result = reader.read_once()
                publisher.publish(result)
        return 0
    except BaselineError as exc:
        LOGGER.exception("실행에 실패했습니다: %s", exc)
        model_info = (
            recognizer.model_info
            if recognizer is not None
            else ModelInfo("easyocr", "not-initialized", "dbnet18+standard(en)", args.model_dir, "torch-cpu")
        )
        result = make_failure_result(exc.status, str(exc), model_info)
        StdoutResultPublisher(plain=args.plain).publish(result)
        return _exit_code(result.status)
    except Exception as exc:
        LOGGER.exception("예상하지 못한 오류가 발생했습니다: %s", exc)
        model_info = (
            recognizer.model_info
            if recognizer is not None
            else ModelInfo("easyocr", "not-initialized", "dbnet18+standard(en)", args.model_dir, "torch-cpu")
        )
        result = make_failure_result(
            ReadStatus.MODEL_ERROR,
            f"예상하지 못한 내부 오류: {exc}",
            model_info,
        )
        StdoutResultPublisher(plain=args.plain).publish(result)
        return _exit_code(result.status)


if __name__ == "__main__":
    raise SystemExit(main())

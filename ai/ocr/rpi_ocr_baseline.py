#!/usr/bin/env python3
"""Raspberry Pi 5 카메라 기반 4자리 차량 식별번호 OCR 베이스라인.

지원 모드는 카메라 점검(`--probe-camera`),
전체 프레임 저장 (`--capture-frame`),
1회/수동 반복 OCR(`--once`, `--interactive`),
하드웨어 비의존 자체 테스트(`--self-test`)다.

Raspberry Pi OS에서는 Picamera2와 OpenCV를 OS 패키지로 설치하는 방식을 우선한다.
OCR 모드에는 NumPy, PaddleOCR 3.7.x와 선택한 추론 엔진의 런타임이
필요하다. 가상환경은 시스템 Picamera2를 볼 수 있도록 다음 형태를 권장한다.

    python3 -m venv --system-site-packages .venv

실제 Raspberry Pi에서는 `uname -m`, `cat /etc/os-release`, `python3 --version`,
`free -h`, `lsblk`, `rpicam-hello --list-cameras`로 환경과 카메라를 먼저
확인해야 한다. 이 파일은 고정 ROI, 수동 트리거, PaddleOCR 어댑터, 표준 출력
발행기를 Protocol 뒤에 두어 각각 객체 검출, 센서, 다른 OCR 런타임, 원격 전송 구현으로 교체할 수 있게 한다.
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
class NormalizedRoi:
    """0~1 정규화 좌표로 표현한 고정 번호판 영역."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in values):
            raise ValueError("ROI 값은 유한한 숫자여야 합니다.")
        if not all(0.0 <= value <= 1.0 for value in values):
            raise ValueError("ROI의 모든 값은 0~1 범위여야 합니다.")
        if self.width <= 0.0 or self.height <= 0.0:
            raise ValueError("ROI의 폭과 높이는 0보다 커야 합니다.")
        if self.x + self.width > 1.0 or self.y + self.height > 1.0:
            raise ValueError("ROI가 정규화 이미지 범위를 벗어납니다.")

    def to_pixel_bounds(self, image_width: int, image_height: int) -> tuple[int, int, int, int]:
        """이미지 크기에 맞는 `(x1, y1, x2, y2)` 픽셀 경계로 변환한다."""

        if image_width <= 0 or image_height <= 0:
            raise ValueError("이미지 폭과 높이는 0보다 커야 합니다.")
        x1 = math.floor(self.x * image_width)
        y1 = math.floor(self.y * image_height)
        x2 = math.ceil((self.x + self.width) * image_width)
        y2 = math.ceil((self.y + self.height) * image_height)
        if not (0 <= x1 < x2 <= image_width and 0 <= y1 < y2 <= image_height):
            raise ValueError("변환된 ROI가 이미지 픽셀 범위를 벗어납니다.")
        return x1, y1, x2, y2


@dataclass(frozen=True)
class CapturedFrame:
    """촬영 순번, 시각, RGB888 uint8 이미지로 구성된 카메라 프레임."""

    frame_id: int
    captured_at: datetime
    image: Any


@dataclass(frozen=True)
class OcrCandidate:
    """한 프레임의 OCR 원문과 내부 정규화 결과."""

    frame_id: int
    raw_text: str
    normalized_text: str
    rec_score: float
    valid_format: bool


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


class PlateLocator(Protocol):
    """전체 프레임에서 번호판 후보 영역을 추출하는 계약."""

    def locate(self, frame: CapturedFrame) -> Any:
        """번호판 후보 이미지 배열을 반환한다."""


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


def is_valid_plate_number(text: str) -> bool:
    """문자열이 ASCII 숫자 정확히 네 자리인지 검사한다."""

    return PLATE_PATTERN.fullmatch(text) is not None


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


class FixedRoiPlateLocator:
    """고정 게이트 카메라를 전제로 정규화 ROI를 잘라내는 위치 탐색기.

    현장 측정에서 차량 위치 편차에 따른 ROI 이탈이 주요 실패 원인으로 확인될
    때만 PlateLocator 구현을 YOLO 같은 객체 검출 방식으로 교체한다.
    """

    def __init__(self, roi: NormalizedRoi) -> None:
        self._roi = roi

    def locate(self, frame: CapturedFrame) -> Any:
        """프레임 크기에 맞춘 고정 ROI Crop을 반환한다."""

        shape = getattr(frame.image, "shape", None)
        if shape is None or len(shape) < 2:
            raise BaselineError(ReadStatus.NO_PLATE_REGION, "프레임 이미지 크기를 확인할 수 없습니다.")
        image_height, image_width = int(shape[0]), int(shape[1])
        try:
            x1, y1, x2, y2 = self._roi.to_pixel_bounds(image_width, image_height)
        except ValueError as exc:
            raise BaselineError(ReadStatus.NO_PLATE_REGION, str(exc)) from exc
        crop = frame.image[y1:y2, x1:x2]
        if getattr(crop, "size", 0) == 0:
            raise BaselineError(ReadStatus.NO_PLATE_REGION, "고정 ROI Crop이 비어 있습니다.")
        return crop


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
            raise BaselineError(ReadStatus.NO_PLATE_REGION, "전처리할 ROI 이미지 크기가 잘못되었습니다.")
        cv2 = _import_cv2()
        target_width = max(1, round(shape[1] * self._resize_height / shape[0]))
        return cv2.resize(image, (target_width, self._resize_height), interpolation=cv2.INTER_LINEAR)


class PaddleOcrTextRecognizer:
    """PaddleOCR 3.7.x TextRecognition 결과를 내부 후보로 격리하는 어댑터.

    같은 PaddleOCR 추론 형식의 파인튜닝 모델은 model_dir 설정만 바꾸며, 다른
    OCR 라이브러리나 직접 ONNX Runtime 구현은 TextRecognizer 전체를 교체한다.
    """

    def __init__(self, *, model_name: str, model_dir: str | None, engine: str) -> None:
        self._model_name = model_name
        self._model_dir = model_dir
        self._engine = engine
        self._model: Any | None = None
        self._library_version = "not-initialized"

    @property
    def model_info(self) -> ModelInfo:
        """현재 PaddleOCR 설정과 확인된 라이브러리 버전을 반환한다."""

        return ModelInfo(
            library="paddleocr",
            library_version=self._library_version,
            model_name=self._model_name,
            model_dir=self._model_dir,
            engine=self._engine,
        )

    def open(self) -> None:
        """TextRecognition 모델을 CPU용으로 한 번만 초기화한다."""

        if self._model is not None:
            return
        command = " ".join(sys.argv)
        started = time.perf_counter()
        try:
            from paddleocr import TextRecognition
        except ImportError as exc:
            missing = getattr(exc, "name", None) or "paddleocr"
            raise BaselineError(
                ReadStatus.DEPENDENCY_ERROR,
                f"OCR 의존성 '{missing}' import에 실패했습니다. PaddleOCR 3.7.x와 "
                f"'{self._engine}' 엔진 의존성을 실제 Raspberry Pi 환경에 맞게 설치해야 합니다. "
                f"실행 명령: {command}. 원인: {exc}",
            ) from exc
        try:
            self._library_version = importlib.metadata.version("paddleocr")
        except importlib.metadata.PackageNotFoundError:
            self._library_version = "unknown"

        kwargs: dict[str, Any] = {
            "model_name": self._model_name,
            "engine": self._engine,
            "device": "cpu",
        }
        if self._model_dir is not None:
            kwargs["model_dir"] = self._model_dir
        try:
            self._model = TextRecognition(**kwargs)
        except (ImportError, ModuleNotFoundError) as exc:
            missing = getattr(exc, "name", None) or self._engine
            raise BaselineError(
                ReadStatus.DEPENDENCY_ERROR,
                f"OCR 엔진 의존성 '{missing}' 초기화에 실패했습니다. 실행 명령: "
                f"{command}. 원인: {exc}",
            ) from exc
        except Exception as exc:
            raise BaselineError(
                ReadStatus.MODEL_ERROR,
                f"PaddleOCR 모델 초기화에 실패했습니다(model={self._model_name}, "
                f"engine={self._engine}, command={command}): {exc}",
            ) from exc
        LOGGER.info("OCR 모델 초기화 시간: %.1f ms", (time.perf_counter() - started) * 1000.0)

    def recognize(self, frame_id: int, image: Any) -> OcrCandidate:
        """TextRecognition.predict 결과 한 건을 내부 후보로 변환한다."""

        if self._model is None:
            raise BaselineError(ReadStatus.MODEL_ERROR, "OCR 모델이 초기화되지 않았습니다.")
        try:
            results = list(self._model.predict(input=image, batch_size=1))
        except Exception as exc:
            raise BaselineError(
                ReadStatus.MODEL_ERROR,
                f"PaddleOCR TextRecognition.predict 실행에 실패했습니다: {exc}",
            ) from exc
        if not results:
            return OcrCandidate(frame_id, "", "", 0.0, False)
        if len(results) > 1:
            LOGGER.warning("단일 ROI 입력에서 OCR 결과 %d건이 반환되어 첫 결과만 사용합니다.", len(results))
        raw_text, rec_score = _extract_paddle_result(results[0])
        normalized = normalize_plate_text(raw_text)
        return OcrCandidate(
            frame_id=frame_id,
            raw_text=raw_text,
            normalized_text=normalized,
            rec_score=rec_score,
            valid_format=is_valid_plate_number(normalized),
        )

    def close(self) -> None:
        """PaddleOCR가 별도 close API를 제공하지 않아 모델 참조를 해제한다."""

        self._model = None


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
    """주입된 카메라·위치 탐색·전처리·OCR 구현을 조합하는 핵심 애플리케이션."""

    def __init__(
        self,
        *,
        frame_source: FrameSource,
        locator: PlateLocator,
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
        self._locator = locator
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
        """여러 프레임을 촬영·인식·집계하여 구조화된 결과 한 건을 반환한다."""

        if not self._opened:
            raise BaselineError(ReadStatus.CONFIG_ERROR, "PlateReader는 with 문 안에서 사용해야 합니다.")
        started = time.perf_counter()
        event_id = uuid4().hex
        candidates: list[OcrCandidate] = []
        missing_regions = 0
        captured_frames = 0
        try:
            for index in range(self._frame_count):
                frame = self._frame_source.capture()
                captured_frames += 1
                if self._debug_writer is not None:
                    self._debug_writer.write_frame(event_id, frame, frame.image, "frame")
                try:
                    crop = self._locator.locate(frame)
                except BaselineError as exc:
                    if exc.status is not ReadStatus.NO_PLATE_REGION:
                        raise
                    missing_regions += 1
                    LOGGER.warning("frame_id=%d 번호판 ROI를 얻지 못했습니다: %s", frame.frame_id, exc)
                else:
                    if self._debug_writer is not None:
                        self._debug_writer.write_frame(event_id, frame, crop, "roi")
                    processed = self._preprocessor.process(crop)
                    candidate = self._recognizer.recognize(frame.frame_id, processed)
                    candidates.append(candidate)
                    if self._debug_writer is not None:
                        self._debug_writer.write_candidate(event_id, frame, candidate)
                if index + 1 < self._frame_count and self._frame_interval_ms:
                    time.sleep(self._frame_interval_ms / 1000.0)
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
        if missing_regions == self._frame_count:
            return make_failure_result(
                ReadStatus.NO_PLATE_REGION,
                "모든 프레임에서 번호판 ROI를 얻지 못했습니다.",
                self._recognizer.model_info,
                total_frames=captured_frames,
                candidates=candidates,
                latency_ms=latency_ms,
            )
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


def _extract_paddle_result(result: Any) -> tuple[str, float]:
    payload: Mapping[str, Any] | None = result if isinstance(result, Mapping) else None
    if payload is None:
        try:
            payload = dict(result)
        except (TypeError, ValueError):
            payload = None
    if payload is None:
        json_value = getattr(result, "json", None)
        if callable(json_value):
            json_value = json_value()
        if isinstance(json_value, str):
            try:
                json_value = json.loads(json_value)
            except json.JSONDecodeError:
                json_value = None
        if isinstance(json_value, Mapping):
            payload = json_value
    if payload is None:
        raise BaselineError(
            ReadStatus.MODEL_ERROR,
            f"지원하지 않는 PaddleOCR Result 형식입니다: {type(result).__name__}",
        )
    nested = payload.get("res")
    if isinstance(nested, Mapping):
        payload = nested
    if "rec_text" not in payload or "rec_score" not in payload:
        raise BaselineError(
            ReadStatus.MODEL_ERROR,
            f"PaddleOCR Result에 rec_text/rec_score가 없습니다: keys={list(payload.keys())}",
        )
    raw_text = str(payload["rec_text"] or "")
    try:
        rec_score = float(payload["rec_score"])
    except (TypeError, ValueError) as exc:
        raise BaselineError(
            ReadStatus.MODEL_ERROR,
            f"PaddleOCR rec_score를 숫자로 변환할 수 없습니다: {payload['rec_score']!r}",
        ) from exc
    if not math.isfinite(rec_score):
        raise BaselineError(ReadStatus.MODEL_ERROR, f"PaddleOCR rec_score가 유한하지 않습니다: {rec_score}")
    return raw_text, rec_score


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
    modes.add_argument("--capture-frame", metavar="PATH", help="ROI 설정용 전체 프레임을 저장합니다.")
    modes.add_argument("--once", action="store_true", help="인식 이벤트를 한 번 실행합니다.")
    modes.add_argument("--interactive", action="store_true", help="Enter로 반복 인식하고 q로 종료합니다.")
    modes.add_argument("--self-test", action="store_true", help="하드웨어 비의존 순수 로직 테스트를 실행합니다.")

    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--warmup-ms", type=int, default=1000)
    parser.add_argument("--roi", nargs=4, type=float, metavar=("X", "Y", "WIDTH", "HEIGHT"))
    parser.add_argument("--frame-count", type=int, default=6)
    parser.add_argument("--frame-interval-ms", type=int, default=120)
    parser.add_argument("--resize-height", type=int, default=None)
    parser.add_argument("--model-name", default="en_PP-OCRv4_mobile_rec")
    parser.add_argument("--model-dir", default=None)
    parser.add_argument(
        "--engine",
        choices=("paddle", "paddle_static", "paddle_dynamic", "transformers", "onnxruntime"),
        default="onnxruntime",
    )
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


def validate_args(args: argparse.Namespace) -> NormalizedRoi | None:
    """실행 전에 수치 범위와 모드별 필수 옵션을 검증한다."""

    if args.width <= 0 or args.height <= 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "카메라 width와 height는 0보다 커야 합니다.")
    if args.camera_index < 0 or args.warmup_ms < 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "camera-index와 warmup-ms는 음수일 수 없습니다.")
    if not (args.once or args.interactive):
        # 카메라 점검과 보정 프레임 저장은 OCR 설정이나 모델 경로에 의존하지 않는다.
        return None
    if args.frame_count <= 0 or args.frame_interval_ms < 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "frame-count는 양수, frame-interval-ms는 0 이상이어야 합니다.")
    if args.min_valid_frames <= 0 or args.min_valid_frames > args.frame_count:
        raise BaselineError(
            ReadStatus.CONFIG_ERROR,
            "min-valid-frames는 1 이상이고 frame-count 이하여야 합니다.",
        )
    if args.resize_height is not None and args.resize_height <= 0:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "resize-height는 0보다 커야 합니다.")
    for name in ("min_rec_score", "min_vote_ratio", "ambiguity_margin"):
        value = getattr(args, name)
        if not 0.0 <= value <= 1.0:
            raise BaselineError(ReadStatus.CONFIG_ERROR, f"{name.replace('_', '-')}는 0~1 범위여야 합니다.")
    if not args.model_name.strip():
        raise BaselineError(ReadStatus.CONFIG_ERROR, "model-name은 빈 문자열일 수 없습니다.")
    if args.model_dir is not None and not Path(args.model_dir).is_dir():
        raise BaselineError(ReadStatus.CONFIG_ERROR, f"model-dir 디렉터리가 없습니다: {args.model_dir}")
    if args.roi is None:
        raise BaselineError(ReadStatus.CONFIG_ERROR, "--once와 --interactive에는 --roi가 필요합니다.")
    try:
        return NormalizedRoi(*args.roi)
    except ValueError as exc:
        raise BaselineError(ReadStatus.CONFIG_ERROR, f"잘못된 ROI 설정입니다: {exc}") from exc


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


def build_plate_reader(
    args: argparse.Namespace,
    roi: NormalizedRoi,
) -> tuple[PlateReader, PaddleOcrTextRecognizer]:
    """CLI 설정과 교체 가능한 기본 구현체로 PlateReader를 조립한다."""

    recognizer = PaddleOcrTextRecognizer(
        model_name=args.model_name,
        model_dir=args.model_dir,
        engine=args.engine,
    )
    debug_writer = DebugArtifactWriter(args.debug_dir) if args.debug_dir is not None else None
    reader = PlateReader(
        frame_source=create_frame_source(args),
        locator=FixedRoiPlateLocator(roi),
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


class BaselineLogicTests(unittest.TestCase):
    """카메라·OCR·네트워크 없이 실행하는 순수 로직 회귀 테스트."""

    MODEL_INFO = ModelInfo("test", "1", "test-model", None, "test-engine")

    @staticmethod
    def candidate(frame_id: int, text: str, score: float) -> OcrCandidate:
        normalized = normalize_plate_text(text)
        return OcrCandidate(frame_id, text, normalized, score, is_valid_plate_number(normalized))

    def aggregate(
        self,
        candidates: Sequence[OcrCandidate],
        *,
        min_rec_score: float = 0.60,
        min_valid_frames: int = 2,
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

    def test_normalized_roi_to_pixels(self) -> None:
        self.assertEqual(NormalizedRoi(0.25, 0.50, 0.50, 0.30).to_pixel_bounds(1280, 720), (320, 360, 960, 576))

    def test_out_of_bounds_roi_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NormalizedRoi(0.8, 0.5, 0.3, 0.2)

    def test_four_ascii_digits_are_valid(self) -> None:
        self.assertTrue(is_valid_plate_number(normalize_plate_text("1234")))

    def test_spaces_and_hyphens_are_removed(self) -> None:
        self.assertEqual(normalize_plate_text(" 12 - 34 "), "1234")

    def test_full_width_digits_are_nfkc_normalized(self) -> None:
        self.assertEqual(normalize_plate_text("１２３４"), "1234")

    def test_three_and_five_digits_are_rejected(self) -> None:
        self.assertFalse(is_valid_plate_number("123"))
        self.assertFalse(is_valid_plate_number("12345"))

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

    recognizer: PaddleOcrTextRecognizer | None = None
    try:
        roi = validate_args(args)
        if args.probe_camera:
            print(json.dumps(probe_camera(args), ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        if args.capture_frame is not None:
            output = capture_calibration_frame(args, Path(args.capture_frame))
            print(json.dumps(output, ensure_ascii=False, sort_keys=True), flush=True)
            return 0

        if roi is None:
            raise BaselineError(ReadStatus.CONFIG_ERROR, "OCR 실행에 필요한 ROI 설정이 없습니다.")
        reader, recognizer = build_plate_reader(args, roi)
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
            else ModelInfo("paddleocr", "not-initialized", args.model_name, args.model_dir, args.engine)
        )
        result = make_failure_result(exc.status, str(exc), model_info)
        StdoutResultPublisher(plain=args.plain).publish(result)
        return _exit_code(result.status)
    except Exception as exc:
        LOGGER.exception("예상하지 못한 오류가 발생했습니다: %s", exc)
        model_info = (
            recognizer.model_info
            if recognizer is not None
            else ModelInfo("paddleocr", "not-initialized", args.model_name, args.model_dir, args.engine)
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

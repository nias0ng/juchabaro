"""
PaddleOCR recognition-only 모델로 전처리된 번호판 문자열을 읽는다.

파이프라인 위치:
    plate_preprocessor → plate_reader → plate_text

주요 기능:
    - 서비스 시작 시 주입된 PaddleOCR 모델 재사용
    - 여러 번호판 이미지의 batch recognition 실행
    - PaddleOCR ``Result.json``에서 원문과 confidence 추출

담당하지 않는 기능:
    - 번호판 이미지 전처리
    - OCR 문자열 정규화와 번호판 형식 검사
    - 여러 프레임 후보의 투표와 최종 판정
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from threading import Lock
from typing import Any, Sequence

import numpy as np

from ..image_validation import is_nonempty_bgr_uint8_image
from ..types import BgrImage, PreparedPlate, RawOcrResult


# PaddleOCR predict에 전달할 기본 recognition batch 크기다. Burst의
# frame_count와는 별도이며 입력 crop 시퀀스 전체를 predict에 전달한다.
DEFAULT_RECOGNITION_BATCH_SIZE = 6


# [예외]


class PaddleResultError(RuntimeError):
    """PaddleOCR 입력 또는 결과가 recognition adapter 계약을 위반한 경우."""


# [입력과 Paddle 결과 파싱]


def _validate_bgr_image(image: BgrImage, *, frame_index: int) -> None:
    """한 프레임의 OCR 입력이 비어 있지 않은 BGR uint8 배열인지 확인한다."""

    if not isinstance(image, np.ndarray):
        raise PaddleResultError(
            f"frame {frame_index}: OCR 입력은 numpy.ndarray여야 합니다."
        )

    if not is_nonempty_bgr_uint8_image(image):
        raise PaddleResultError(
            f"frame {frame_index}: OCR 입력은 비어 있지 않은 "
            "BGR uint8 HxWx3 배열이어야 합니다: "
            f"dtype={image.dtype}, shape={image.shape}"
        )


def _parse_paddle_result(result: Any) -> tuple[str, float]:
    """
    PaddleOCR ``Result.json``에서 인식 문자열과 confidence를 추출한다.

    입력:
        ``json`` 속성이 callable, JSON 문자열 또는 dict인 Paddle 결과.

    출력:
        정규화하지 않은 문자열과 0.0~1.0 범위 confidence.
        비어 있는 결과의 누락된 confidence는 0.0으로 변환한다.

    실패:
        JSON 구조가 잘못되었거나 confidence가 숫자가 아니고,
        유한하지 않거나 범위를 벗어나면 PaddleResultError가 발생한다.
    """

    data = getattr(result, "json", None)
    if callable(data):
        try:
            data = data()
        except Exception as exc:
            raise PaddleResultError(
                "PaddleOCR Result.json 호출에 실패했습니다."
            ) from exc

    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise PaddleResultError(
                "PaddleOCR Result.json이 올바른 JSON 문자열이 아닙니다."
            ) from exc

    if not isinstance(data, dict):
        raise PaddleResultError(
            "PaddleOCR Result.json은 dict 또는 JSON 문자열이어야 합니다."
        )

    payload = data.get("res", data)
    if not isinstance(payload, dict):
        raise PaddleResultError(
            "PaddleOCR Result.json의 res는 dict여야 합니다."
        )

    raw_text_value = payload.get("rec_text", "")
    raw_text = "" if raw_text_value is None else str(raw_text_value)

    score_value = payload.get("rec_score")
    if score_value is None or (
        isinstance(score_value, str)
        and not score_value.strip()
    ):
        # 빈 인식 결과는 일부 Paddle 버전에서 score를 생략한다.
        # 후처리에서 안전하게 제외할 수 있도록 0.0으로 통일한다.
        return raw_text, 0.0

    try:
        score = float(score_value)
    except (TypeError, ValueError) as exc:
        raise PaddleResultError(
            "PaddleOCR rec_score를 실수로 변환할 수 없습니다: "
            f"{score_value!r}"
        ) from exc

    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise PaddleResultError(
            "PaddleOCR rec_score는 유한한 0.0~1.0 값이어야 합니다: "
            f"{score}"
        )

    return raw_text, score


# [PaddleOCR 추론 Adapter]


class PaddlePlateReader:
    """
    이미 로드된 PaddleOCR recognition 모델로 번호판 batch를 읽는다.

    이 객체는 서비스 시작 시 한 번 생성한 뒤 차량 이벤트마다 재사용한다.
    모델 호출과 generator 소비를 하나의 lock 안에서 수행해 동시 추론으로
    모델 상태가 충돌하지 않게 한다.

    입력:
        ``recognize()``는 전처리가 끝난 PreparedPlate 시퀀스를 받는다.

    출력:
        입력 순서와 frame_index를 보존한 RawOcrResult tuple.

    실패:
        중복 frame_index, 잘못된 BGR 이미지, 결과 개수 불일치 또는
        비정상 Result.json이면 PaddleResultError를 발생시킨다.
        실제 모델 실행 오류는 원래 예외를 그대로 전달한다.
    """

    def __init__(
        self,
        model: Any,
        *,
        batch_size: int = DEFAULT_RECOGNITION_BATCH_SIZE,
    ) -> None:
        if not callable(getattr(model, "predict", None)):
            raise TypeError(
                "PaddleOCR model에는 callable predict가 필요합니다."
            )
        if (
            not isinstance(batch_size, int)
            or isinstance(batch_size, bool)
            or batch_size <= 0
        ):
            raise ValueError("batch_size는 양의 정수여야 합니다.")

        self._model = model
        self._batch_size = batch_size
        self._lock = Lock()

    def warm_up(self) -> None:
        """
        작은 검은 번호판 이미지로 첫 recognition을 실행한다.

        입력:
            별도 입력 없음.

        출력:
            없음.

        실패:
            모델 실행 또는 결과 개수 검증에 실패하면 해당 예외가 발생한다.
            검은 probe의 문자열과 confidence는 실제 OCR 입력이 아니므로
            유효성 판정에 사용하지 않는다.
        """

        probe = np.zeros((64, 192, 3), dtype=np.uint8)
        results = self._predict_images([probe])

        if len(results) != 1:
            raise PaddleResultError(
                "PaddleOCR warm-up은 결과 한 개를 반환해야 합니다: "
                f"count={len(results)}"
            )

    def recognize(
        self,
        plates: Sequence[PreparedPlate],
    ) -> tuple[RawOcrResult, ...]:
        """
        전처리된 번호판들을 한 번의 PaddleOCR batch 호출로 인식한다.

        입력:
            frame_index가 중복되지 않고 BGR uint8 이미지를 가진
            PreparedPlate 시퀀스.

        출력:
            입력과 동일한 순서로 정렬된 RawOcrResult tuple.
            빈 입력에는 빈 tuple을 반환하며 모델을 호출하지 않는다.

        실패:
            입력 계약 위반, Paddle 결과 개수 불일치 또는 결과 파싱
            실패 시 PaddleResultError를 발생시킨다.
        """

        prepared = tuple(plates)
        if not prepared:
            return ()

        if any(
            not isinstance(plate, PreparedPlate)
            for plate in prepared
        ):
            raise PaddleResultError(
                "PaddleOCR 입력은 PreparedPlate 시퀀스여야 합니다."
            )

        frame_indices = [plate.frame_index for plate in prepared]
        if len(set(frame_indices)) != len(frame_indices):
            raise PaddleResultError(
                "PaddleOCR 입력 frame_index는 중복될 수 없습니다: "
                f"{frame_indices}"
            )

        images: list[BgrImage] = []
        for plate in prepared:
            _validate_bgr_image(
                plate.image,
                frame_index=plate.frame_index,
            )
            images.append(plate.image)

        results = self._predict_images(images)
        if len(results) != len(prepared):
            raise PaddleResultError(
                "PaddleOCR 결과 개수가 입력 번호판 개수와 다릅니다: "
                f"inputs={len(prepared)}, results={len(results)}"
            )

        recognized: list[RawOcrResult] = []
        for plate, result in zip(prepared, results, strict=True):
            raw_text, rec_score = _parse_paddle_result(result)
            recognized.append(
                RawOcrResult(
                    frame_index=plate.frame_index,
                    raw_text=raw_text,
                    rec_score=rec_score,
                )
            )

        return tuple(recognized)

    def _predict_images(
        self,
        images: list[BgrImage],
    ) -> list[Any]:
        """PaddleOCR 호출과 lazy 결과 소비를 같은 lock 안에서 수행한다."""

        with self._lock:
            return list(
                self._model.predict(
                    input=images,
                    batch_size=self._batch_size,
                )
            )


# [모델 로더]


_PADDLE_REQUIRED_FILES = (
    "inference.json",
    "inference.pdiparams",
    "inference.yml",
)


def load_paddle_plate_reader(
    model_dir: Path,
    *,
    model_name: str = "korean_PP-OCRv5_mobile_rec",
    device: str = "cpu",
    batch_size: int = DEFAULT_RECOGNITION_BATCH_SIZE,
    warm_up: bool = True,
) -> PaddlePlateReader:
    """
    로컬 PaddleOCR inference model을 로드해 재사용 가능한 reader를 만든다.

    이 함수는 ``main.py``의 서비스 시작 단계에서 한 번만 호출해야 한다.
    차량 감지 반복문에서는 반환된 객체의 ``recognize()``만 재사용한다.

    입력:
        model_dir는 Paddle inference 파일 세 개가 있는 디렉터리다.
        model_name은 모델 구조 식별자, device와 batch_size는 추론 설정이다.

    출력:
        recognition model이 주입된 PaddlePlateReader.

    실패:
        모델 디렉터리나 필수 파일이 없거나 비어 있으면 파일 관련
        예외가 발생한다. PaddleOCR import·모델 로드·선택적 warm-up
        실패도 호출자에게 그대로 전달한다.
    """

    if not isinstance(model_name, str) or not model_name.strip():
        raise ValueError("model_name은 비어 있지 않은 문자열이어야 합니다.")
    if not isinstance(device, str) or not device.strip():
        raise ValueError("device는 비어 있지 않은 문자열이어야 합니다.")

    resolved_dir = model_dir.expanduser().resolve()
    if not resolved_dir.is_dir():
        raise FileNotFoundError(
            f"PaddleOCR 모델 디렉터리가 없습니다: {resolved_dir}"
        )

    for filename in _PADDLE_REQUIRED_FILES:
        artifact = resolved_dir / filename
        if not artifact.is_file():
            raise FileNotFoundError(
                f"PaddleOCR 필수 모델 파일이 없습니다: {artifact}"
            )
        if artifact.stat().st_size == 0:
            raise RuntimeError(
                f"PaddleOCR 모델 파일이 비어 있습니다: {artifact}"
            )

    # 무거운 runtime dependency는 실제 loader가 호출되는 시점에만 읽는다.
    from paddleocr import TextRecognition

    reader = PaddlePlateReader(
        TextRecognition(
            model_name=model_name,
            model_dir=str(resolved_dir),
            device=device,
        ),
        batch_size=batch_size,
    )

    if warm_up:
        reader.warm_up()

    return reader

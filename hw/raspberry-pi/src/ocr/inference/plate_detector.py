"""
YOLOv8n-pose 모델로 anchor 프레임의 번호판과 네 꼭짓점을 검출한다.

파이프라인 위치:
    frame_selector → plate_detector → geometry

주요 기능:
    - 서비스 시작 시 주입된 YOLO 모델 재사용
    - BGR 프레임 입력과 YOLO 출력 계약 검증
    - 여러 검출 후보를 confidence와 bbox 면적 순으로 정렬

담당하지 않는 기능:
    - 모델 파일 다운로드
    - 프레임 품질 평가와 anchor 선택
    - 네 꼭짓점 보간, 원근 보정과 OCR
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np

from ..errors import OcrComponentError
from ..image_validation import is_nonempty_bgr_uint8_image
from ..types import BgrImage, CapturedFrame, DetectedPlate, Quad


# [예외]


class DetectorContractError(OcrComponentError, RuntimeError):
    """입력 또는 YOLO 결과가 번호판 detector 계약을 만족하지 않는 경우."""


# [입력과 모델 출력 검증]


def _validate_bgr_image(image: BgrImage) -> None:
    """
    detector 입력이 비어 있지 않은 BGR uint8 HxWx3 배열인지 확인한다.

    입력:
        카메라가 생성한 BGR 이미지 배열.

    출력:
        계약을 만족하면 반환값 없이 종료한다.

    실패:
        dtype, 차원, 채널 수 또는 이미지 크기가 잘못되면
        DetectorContractError를 발생시킨다.
    """

    if not isinstance(image, np.ndarray):
        raise DetectorContractError(
            "YOLO 입력은 numpy.ndarray여야 합니다."
        )

    if not is_nonempty_bgr_uint8_image(image):
        raise DetectorContractError(
            "YOLO 입력은 비어 있지 않은 BGR uint8 HxWx3 "
            f"배열이어야 합니다: dtype={image.dtype}, "
            f"shape={image.shape}"
        )


def _to_numpy(value: Any, *, name: str) -> np.ndarray:
    """
    torch tensor 또는 배열형 YOLO 출력을 numpy 배열로 변환한다.
    """

    try:
        detach = getattr(value, "detach", None)
        if callable(detach):
            value = detach()

        cpu = getattr(value, "cpu", None)
        if callable(cpu):
            value = cpu()

        to_numpy = getattr(value, "numpy", None)
        if callable(to_numpy):
            value = to_numpy()

        return np.asarray(value)
    except Exception as exc:
        raise DetectorContractError(
            f"YOLO {name} 출력을 numpy 배열로 변환할 수 없습니다."
        ) from exc


def _bbox_area(bbox_xyxy: tuple[float, float, float, float]) -> float:
    """유효성이 확인된 xyxy bbox의 면적을 반환한다."""

    x1, y1, x2, y2 = bbox_xyxy
    return (x2 - x1) * (y2 - y1)


# [YOLO 추론 Adapter]


class YoloPlateDetector:
    """
    이미 로드된 YOLO pose 모델을 번호판 detector로 감싼다.

    이 객체는 서비스 시작 시 한 번 생성된 뒤 차량 이벤트마다 재사용한다.

    입력:
        ``detect()``는 BGR uint8 HxWx3 이미지를 가진 CapturedFrame을
        받는다. pose 모델의 네 keypoint 의미는 학습 계약에 따라
        좌상→우상→우하→좌하 순서여야 한다.

    출력:
        confidence와 bbox 면적 우선순위로 정렬된 DetectedPlate tuple.
        빈 tuple은 정상 미검출을 뜻한다. 후보의 geometry 유효성은 다음
        단계에서 검사하므로 여기서 대표 후보 하나를 확정하지 않는다.

    실패:
        입력 이미지나 YOLO 결과의 개수·shape·값이 계약과 다르면
        DetectorContractError를 발생시킨다. 실제 모델 실행 오류도
        원인을 보존한 DetectorContractError로 변환한다.
    """

    def __init__(
        self,
        model: Any,
        *,
        device: str = "cpu",
        imgsz: int = 640,
        confidence_threshold: float = 0.40,
        max_detections: int = 3,
    ) -> None:
        if not callable(getattr(model, "predict", None)):
            raise TypeError("YOLO model에는 callable predict가 필요합니다.")
        if not isinstance(device, str) or not device.strip():
            raise ValueError("device는 비어 있지 않은 문자열이어야 합니다.")
        if not isinstance(imgsz, int) or isinstance(imgsz, bool) or imgsz <= 0:
            raise ValueError("imgsz는 양의 정수여야 합니다.")
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError(
                "confidence_threshold는 0.0~1.0 범위여야 합니다."
            )
        if (
            not isinstance(max_detections, int)
            or isinstance(max_detections, bool)
            or max_detections <= 0
        ):
            raise ValueError("max_detections는 양의 정수여야 합니다.")

        self._model = model
        self._device = device
        self._imgsz = imgsz
        self._confidence_threshold = confidence_threshold
        self._max_detections = max_detections

    def warm_up(self) -> None:
        """
        빈 이미지로 첫 추론을 실행해 실제 이벤트 전 초기화를 끝낸다.

        입력:
            별도 입력 없음. 설정된 ``imgsz`` 크기의 검은 이미지를 사용한다.

        출력:
            없음.

        실패:
            모델 실행 오류 또는 결과 개수가 한 개가 아니면 예외가 발생한다.
        """

        probe = np.zeros(
            (self._imgsz, self._imgsz, 3),
            dtype=np.uint8,
        )
        self._require_single_result(self._predict(probe))

    def detect(
        self,
        frame: CapturedFrame,
    ) -> tuple[DetectedPlate, ...]:
        """
        한 anchor 프레임에서 번호판 후보들과 네 꼭짓점을 검출한다.

        입력:
            시간순 인덱스와 BGR uint8 HxWx3 이미지를 가진 CapturedFrame.

        출력:
            confidence 내림차순, 동률이면 bbox 면적 내림차순인
            DetectedPlate tuple. 두 값이 모두 같으면 모델의 원래 순서를
            유지하며, 후보가 없으면 빈 tuple이다.

        실패:
            입력 이미지 또는 YOLO 출력이 detector 계약을 위반하면
            DetectorContractError를 발생시킨다.
        """

        _validate_bgr_image(frame.image)
        result = self._require_single_result(
            self._predict(frame.image)
        )
        raw_candidates = self._extract_candidate_arrays(result)

        if raw_candidates is None:
            return ()

        box_count, boxes, scores, keypoints = raw_candidates
        candidates = self._parse_candidates(
            frame_index=frame.frame_index,
            box_count=box_count,
            boxes=boxes,
            scores=scores,
            keypoints=keypoints,
        )
        return self._rank_candidates(candidates)

    @staticmethod
    def _extract_candidate_arrays(
        result: Any,
    ) -> tuple[
        int,
        np.ndarray,
        np.ndarray,
        np.ndarray,
    ] | None:
        """YOLO result schema를 확인하고 후보별 raw 배열을 추출한다."""

        boxes_object = getattr(result, "boxes", None)
        keypoints_object = getattr(result, "keypoints", None)

        if boxes_object is None:
            if keypoints_object is None:
                raise DetectorContractError(
                    "YOLO result에 boxes와 keypoints 속성이 없습니다."
                )
            raise DetectorContractError(
                "YOLO keypoints는 있지만 boxes가 없습니다."
            )

        try:
            box_count = len(boxes_object)
        except TypeError as exc:
            raise DetectorContractError(
                "YOLO boxes의 개수를 확인할 수 없습니다."
            ) from exc

        if box_count == 0:
            if keypoints_object is not None:
                empty_keypoints = _to_numpy(
                    getattr(keypoints_object, "xy", None),
                    name="keypoints.xy",
                )
                if empty_keypoints.shape not in ((0, 4, 2), (0,)):
                    raise DetectorContractError(
                        "bbox가 없는데 pose keypoints가 반환되었습니다: "
                        f"shape={empty_keypoints.shape}"
                    )
            return None

        if keypoints_object is None:
            raise DetectorContractError(
                "번호판 bbox는 있지만 pose keypoints가 없습니다."
            )

        boxes = _to_numpy(
            getattr(boxes_object, "xyxy", None),
            name="boxes.xyxy",
        )
        scores = _to_numpy(
            getattr(boxes_object, "conf", None),
            name="boxes.conf",
        )
        keypoints = _to_numpy(
            getattr(keypoints_object, "xy", None),
            name="keypoints.xy",
        )

        return box_count, boxes, scores, keypoints

    @staticmethod
    def _parse_candidates(
        *,
        frame_index: int,
        box_count: int,
        boxes: np.ndarray,
        scores: np.ndarray,
        keypoints: np.ndarray,
    ) -> tuple[DetectedPlate, ...]:
        """후보 배열 계약을 검증하고 typed 번호판 후보로 변환한다."""

        if boxes.shape != (box_count, 4):
            raise DetectorContractError(
                "YOLO boxes.xyxy는 객체당 네 좌표여야 합니다: "
                f"shape={boxes.shape}"
            )
        if scores.shape != (box_count,):
            raise DetectorContractError(
                "YOLO boxes.conf 개수가 bbox 개수와 다릅니다: "
                f"shape={scores.shape}, boxes={box_count}"
            )
        if keypoints.shape != (box_count, 4, 2):
            raise DetectorContractError(
                "번호판 pose 모델은 객체당 네 점을 반환해야 합니다: "
                f"shape={keypoints.shape}, expected=({box_count}, 4, 2)"
            )

        if (
            not np.issubdtype(boxes.dtype, np.number)
            or not np.issubdtype(scores.dtype, np.number)
            or not np.issubdtype(keypoints.dtype, np.number)
        ):
            raise DetectorContractError(
                "YOLO 좌표와 confidence는 숫자 배열이어야 합니다."
            )

        if (
            not np.isfinite(boxes).all()
            or not np.isfinite(scores).all()
            or not np.isfinite(keypoints).all()
        ):
            raise DetectorContractError(
                "YOLO 결과에 NaN 또는 무한대가 포함되어 있습니다."
            )

        candidates: list[DetectedPlate] = []
        for box, score_value, points in zip(
            boxes,
            scores,
            keypoints,
            strict=True,
        ):
            score = float(score_value)
            if not 0.0 <= score <= 1.0:
                raise DetectorContractError(
                    "YOLO confidence는 0.0~1.0 범위여야 합니다: "
                    f"{score}"
                )

            x1, y1, x2, y2 = (float(value) for value in box)
            bbox_xyxy = (x1, y1, x2, y2)

            if x2 <= x1 or y2 <= y1:
                raise DetectorContractError(
                    "YOLO bbox는 양의 너비와 높이를 가져야 합니다: "
                    f"{bbox_xyxy}"
                )

            # keypoint의 의미는 재정렬하지 않고 학습 시 정의한
            # 좌상→우상→우하→좌하 순서를 그대로 보존한다.
            top_left, top_right, bottom_right, bottom_left = points
            quad = cast(
                Quad,
                (
                    (float(top_left[0]), float(top_left[1])),
                    (float(top_right[0]), float(top_right[1])),
                    (float(bottom_right[0]), float(bottom_right[1])),
                    (float(bottom_left[0]), float(bottom_left[1])),
                ),
            )

            candidates.append(
                DetectedPlate(
                    frame_index=frame_index,
                    bbox_xyxy=bbox_xyxy,
                    quad=quad,
                    detector_score=score,
                )
            )

        return tuple(candidates)

    @staticmethod
    def _rank_candidates(
        candidates: tuple[DetectedPlate, ...],
    ) -> tuple[DetectedPlate, ...]:
        """Geometry 검증 전 후보를 confidence와 bbox 면적 순으로 정렬한다."""

        # 오름차순 key에 음수를 사용해 완전 동률일 때 YOLO 원래 순서를
        # 보존하는 stable sort의 의미를 분명히 한다.
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -candidate.detector_score,
                    -_bbox_area(candidate.bbox_xyxy),
                ),
            ),
        )

    def _predict(self, image: BgrImage) -> list[Any]:
        """주입된 YOLO 모델을 한 번 호출하고 결과를 즉시 소비한다."""

        try:
            return list(
                self._model.predict(
                    source=image,
                    device=self._device,
                    imgsz=self._imgsz,
                    conf=self._confidence_threshold,
                    max_det=self._max_detections,
                    half=False,
                    verbose=False,
                )
            )
        except Exception as exc:
            raise DetectorContractError(
                "YOLO 모델 실행에 실패했습니다."
            ) from exc

    @staticmethod
    def _require_single_result(results: list[Any]) -> Any:
        """단일 이미지 추론 결과가 정확히 하나인지 확인한다."""

        if len(results) != 1:
            raise DetectorContractError(
                "한 이미지당 YOLO Results 한 개가 필요합니다: "
                f"count={len(results)}"
            )
        return results[0]


# [모델 로더]


def load_yolo_plate_detector(
    model_path: Path,
    *,
    device: str = "cpu",
    imgsz: int = 640,
    confidence_threshold: float = 0.40,
    max_detections: int = 3,
    warm_up: bool = True,
) -> YoloPlateDetector:
    """
    로컬 YOLOv8n-pose ``.pt``를 로드해 재사용 가능한 detector를 만든다.

    운영에서는 ``load_plate_ocr_pipeline()``이 서비스 시작 단계에서
    이 loader를 한 번 호출한다. 차량 이벤트마다 모델을 다시 읽지 않는다.

    입력:
        model_path는 파인튜닝한 YOLOv8n-pose ``.pt`` 파일 경로다.
        나머지 인자는 추론 장치, 입력 크기, confidence 기준과 최대
        후보 개수다.

    출력:
        모델이 주입된 YoloPlateDetector.

    실패:
        모델 파일이 없거나 비어 있으면 파일 관련 예외가 발생한다.
        Ultralytics import·모델 로드·선택적 warm-up 실패도 호출자에게
        그대로 전달한다.
    """

    resolved_path = model_path.expanduser().resolve()

    if not resolved_path.is_file():
        raise FileNotFoundError(
            f"YOLO 모델 파일이 없습니다: {resolved_path}"
        )
    if resolved_path.stat().st_size == 0:
        raise RuntimeError(
            f"YOLO 모델 파일이 비어 있습니다: {resolved_path}"
        )

    # 무거운 runtime dependency는 실제 loader가 호출되는 시점에만 읽는다.
    from ultralytics import YOLO

    # requirements.txt에 고정한 Ultralytics constructor 계약을 직접 사용한다.
    # 지원하지 않는 구버전은 fallback하지 않고 startup에서 드러낸다.
    detector = YoloPlateDetector(
        YOLO(str(resolved_path), task="pose"),
        device=device,
        imgsz=imgsz,
        confidence_threshold=confidence_threshold,
        max_detections=max_detections,
    )

    if warm_up:
        detector.warm_up()

    return detector

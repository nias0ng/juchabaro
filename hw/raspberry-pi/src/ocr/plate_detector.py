'''
사진 6장 파일 받아서 -> 품질 좋은 걸로 객체 탐지하고 -> 객체 탐지한 영역 기준으로 영역 6개 영역 뽑으면 -> 그렇게 파싱한거 reader로 넘기기 
Yolo 임시로 기본 Yolo 넣어놔야겠다.

Yolo 로딩이랑 작동이랑 두 개... 할 거 많네...
'''

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Any, cast

import numpy as np

from .types import (
    CapturedFrame,
    DetectedPlate,
    Quad,
)


class DetectorContractError(RuntimeError):
    pass


class YoloPlateDetector:
    def __init__(
        self,
        model: Any,
        *,
        device: str = "cpu",
        imgsz: int = 640,
        confidence_threshold: float = 0.40,
    ) -> None:
        self._model = model
        self._device = device
        self._imgsz = imgsz
        self._confidence_threshold = confidence_threshold
        self._lock = Lock()

    def warm_up(self) -> None:
        probe = np.zeros(
            (self._imgsz, self._imgsz, 3),
            dtype=np.uint8,
        )
        self._predict(probe)

    def detect(
        self,
        frame: CapturedFrame,
    ) -> DetectedPlate | None:
        results = self._predict(frame.image)

        if len(results) != 1:
            raise DetectorContractError(
                "한 이미지당 YOLO Results 1개가 필요합니다."
            )

        result = results[0]

        if (
            result.boxes is None
            or result.keypoints is None
            or len(result.boxes) == 0
        ):
            return None

        boxes = result.boxes.xyxy.detach().cpu().numpy()
        scores = result.boxes.conf.detach().cpu().numpy()
        keypoints = (
            result.keypoints.xy
            .detach()
            .cpu()
            .numpy()
        )

        if (
            keypoints.ndim != 3
            or keypoints.shape[1:] != (4, 2)
        ):
            raise DetectorContractError(
                "번호판 pose 모델은 객체당 4점을 "
                f"반환해야 합니다: shape={keypoints.shape}"
            )

        candidates: list[DetectedPlate] = []

        for box, score, points in zip(
            boxes,
            scores,
            keypoints,
            strict=True,
        ):
            if not np.isfinite(points).all():
                continue

            x1, y1, x2, y2 = box

            quad = cast(
                Quad,
                tuple(
                    (float(x), float(y))
                    for x, y in points
                ),
            )

            candidates.append(
                DetectedPlate(
                    frame_index=frame.frame_index,
                    bbox_xyxy=(
                        float(x1),
                        float(y1),
                        float(x2),
                        float(y2),
                    ),
                    quad=quad,
                    detector_score=float(score),
                )
            )

        if not candidates:
            return None

        # 입구에 차량 한 대가 있다는 초기 가정.
        # confidence 동점이면 bbox가 큰 번호판을 선택한다.
        return max(
            candidates,
            key=lambda candidate: (
                candidate.detector_score,
                (
                    candidate.bbox_xyxy[2]
                    - candidate.bbox_xyxy[0]
                )
                * (
                    candidate.bbox_xyxy[3]
                    - candidate.bbox_xyxy[1]
                ),
            ),
        )

    def _predict(self, image: np.ndarray) -> list[Any]:
        with self._lock:
            return list(
                self._model.predict(
                    source=image,
                    device=self._device,
                    imgsz=self._imgsz,
                    conf=self._confidence_threshold,
                    max_det=3,
                    half=False,
                    verbose=False,
                )
            )


def load_yolo_plate_detector(
    model_path: Path,
    *,
    device: str = "cpu",
    imgsz: int = 640,
    confidence_threshold: float = 0.40,
) -> YoloPlateDetector:
    """
    main.py가 시작 시 한 번 호출하는 로더.
    """

    model_path = model_path.resolve()

    if not model_path.is_file():
        raise FileNotFoundError(
            f"YOLO 모델이 없습니다: {model_path}"
        )

    if model_path.stat().st_size == 0:
        raise RuntimeError(
            f"YOLO 모델 파일이 비어 있습니다: {model_path}"
        )

    from ultralytics import YOLO

    model = YOLO(str(model_path))

    return YoloPlateDetector(
        model,
        device=device,
        imgsz=imgsz,
        confidence_threshold=confidence_threshold,
    )
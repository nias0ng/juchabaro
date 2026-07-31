"""Ultralytics YOLO와 ByteTrack 결과를 추적 계층 모델로 변환하는 어댑터.

ai/tracking/jetson_vehicle_tracking_baseline.py의 UltralyticsVehicleTracker
에서 이관(T-05). 출력을 옛 VehicleBox가 아니라 새 TrackObservation으로 바꿨다.
"""

from __future__ import annotations

from typing import Any

from src.camera.models import CapturedFrame
from src.tracking.models import BoundingBox, TrackObservation, TrackSegmentId
from src.tracking.protocols import ModelInfo, TrackingError


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise TrackingError(
            f"OpenCV import에 실패했습니다. `pip install opencv-python`으로 설치하세요. 원인: {exc}"
        ) from exc
    return cv2


class UltralyticsVehicleTracker:
    """Ultralytics YOLO + ByteTrack 결과를 정규화 TrackObservation으로 변환하는 어댑터.

    실제 Jetson 배치 시에는 `model_path`를 TensorRT `.engine` 가중치로,
    파인튜닝이 끝나면 `ai/training/configs/yolo_vehicle.yaml`로 학습한
    가중치로 교체한다.
    """

    def __init__(self, *, model_path: str, tracker_config: str, confidence: float) -> None:
        self._model_path = model_path
        self._tracker_config = tracker_config
        self._confidence = confidence
        self._model: Any | None = None
        self._library_version = "not-initialized"

    @property
    def model_info(self) -> ModelInfo:
        """현재 Ultralytics 설정과 확인된 라이브러리 버전을 반환한다."""

        return ModelInfo(
            library="ultralytics",
            library_version=self._library_version,
            model_name=self._model_path,
            tracker_config=self._tracker_config,
        )

    def open(self) -> None:
        """YOLO 모델을 한 번만 로드한다."""

        if self._model is not None:
            return
        try:
            import ultralytics
            from ultralytics import YOLO
        except ImportError as exc:
            missing = getattr(exc, "name", None) or "ultralytics"
            raise TrackingError(
                f"트래킹 의존성 '{missing}' import에 실패했습니다. `pip install ultralytics`로 설치하세요. 원인: {exc}"
            ) from exc
        self._library_version = getattr(ultralytics, "__version__", "unknown")
        try:
            self._model = YOLO(self._model_path)
        except Exception as exc:
            raise TrackingError(f"YOLO 모델 로드에 실패했습니다(model={self._model_path}): {exc}") from exc

    def track(self, frame: CapturedFrame) -> list[TrackObservation]:
        """YOLO 탐지 + ByteTrack 결과를 정규화 좌표의 TrackObservation 목록으로 변환한다."""

        if self._model is None:
            raise TrackingError("트래커가 초기화되지 않았습니다.")
        shape = getattr(frame.image, "shape", None)
        if shape is None or len(shape) < 2:
            raise TrackingError("프레임 이미지 크기를 확인할 수 없습니다.")
        image_height, image_width = int(shape[0]), int(shape[1])
        if image_height <= 0 or image_width <= 0:
            # 카메라가 순간적으로 빈 프레임을 반환하는 경우(리뷰 반영) 나눗셈 전에 걸러낸다.
            raise TrackingError(f"프레임 크기가 올바르지 않습니다: shape={shape}")
        cv2 = _import_cv2()
        # CapturedFrame.image는 RGB인데 Ultralytics는 ndarray source를 BGR로 해석한다
        # (ultralytics/data/loaders.py: "NumPy color inputs are assumed to use
        # OpenCV-compatible BGR order"). 학습 데이터는 cv2.imwrite로 BGR 저장 → BGR로
        # 로드되므로, 여기서 되돌리지 않으면 R/B가 뒤바뀐 입력으로 추론하게 된다.
        source_bgr = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
        try:
            results = self._model.track(
                source=source_bgr,
                persist=True,
                tracker=self._tracker_config,
                conf=self._confidence,
                verbose=False,
            )
        except Exception as exc:
            raise TrackingError(f"YOLO/ByteTrack 추론에 실패했습니다: {exc}") from exc

        observations: list[TrackObservation] = []
        if not results:
            return observations
        result_boxes = getattr(results[0], "boxes", None)
        if result_boxes is None or result_boxes.id is None:
            return observations
        xyxy = result_boxes.xyxy.tolist()
        track_ids = result_boxes.id.tolist()
        confidences = result_boxes.conf.tolist()
        for (x1, y1, x2, y2), track_id, confidence in zip(xyxy, track_ids, confidences):
            nx1 = max(0.0, min(1.0, x1 / image_width))
            ny1 = max(0.0, min(1.0, y1 / image_height))
            nx2 = max(0.0, min(1.0, x2 / image_width))
            ny2 = max(0.0, min(1.0, y2 / image_height))
            if nx2 <= nx1 or ny2 <= ny1:
                continue
            observations.append(
                TrackObservation(
                    track_segment_id=TrackSegmentId(int(track_id)),
                    bbox=BoundingBox(x1=nx1, y1=ny1, x2=nx2, y2=ny2),
                    confidence=float(confidence),
                    observed_at=frame.captured_at,
                )
            )
        return observations

    def close(self) -> None:
        """모델 참조를 해제한다."""

        self._model = None

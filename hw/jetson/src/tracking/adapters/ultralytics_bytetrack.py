"""Ultralytics YOLO와 ByteTrack 결과를 추적 계층 모델로 변환한다.

현재 frame의 detection 차집합은 segment 종료가 아니다. 핀된
Ultralytics ByteTrack가 `removed_stracks`로 max-age 종료를 확정한
시점에만 `ended_track_segment_ids`를 한 번 전달한다.
ID가 없는 tentative detection이 하나라도 있으면
`all_detections_tracked=False`로 부재 확정에 쓰지 않게 한다.
"""

from __future__ import annotations

import math
from typing import Any

from src.camera.models import CapturedFrame
from src.tracking.models import (
    BoundingBox,
    TrackerFrameResult,
    TrackObservation,
    TrackSegmentId,
)
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
    """Ultralytics YOLO + ByteTrack 결과를 tracking 계약으로 정규화한다.

    실제 Jetson 배치 시에는 `model_path`를 TensorRT `.engine` 가중치로,
    파인튜닝이 끝나면 `ai/training/configs/yolo_vehicle.yaml`로 학습한
    가중치로 교체한다.
    """

    def __init__(self, *, model_path: str, tracker_config: str, confidence: float) -> None:
        if not model_path.strip():
            raise ValueError("model_path must not be empty")
        if not tracker_config.strip():
            raise ValueError("tracker_config must not be empty")
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be a finite value between 0 and 1")
        self._model_path = model_path
        self._tracker_config = tracker_config
        self._confidence = confidence
        self._model: Any | None = None
        self._library_version = "not-initialized"
        self._known_removed_track_segment_ids: set[TrackSegmentId] = set()
        self._pretrack_detection_count: int | None = None

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
                f"트래킹 의존성 '{missing}' import에 실패했습니다. "
                f"`pip install ultralytics`로 설치하세요. 원인: {exc}"
            ) from exc
        self._library_version = getattr(ultralytics, "__version__", "unknown")
        try:
            self._model = YOLO(self._model_path)
            # Ultralytics track callback이 Results를 active track subset으로
            # 교체하기 전에 detection coverage를 보존한다. 이 callback은
            # 첫 model.track() call이 tracker callback을 등록하기 전에
            # 추가되므로 실행 순서가 앞선다.
            self._model.add_callback(
                "on_predict_postprocess_end",
                self._capture_pretrack_detection_count,
            )
        except Exception as exc:
            raise TrackingError(f"YOLO 모델 로드에 실패했습니다(model={self._model_path}): {exc}") from exc

    def track(self, frame: CapturedFrame) -> TrackerFrameResult:
        """YOLO/ByteTrack 관측·detection coverage·segment 종료를 반환한다."""

        if self._model is None:
            raise TrackingError("트래커가 초기화되지 않았습니다.")
        shape = getattr(frame.image, "shape", None)
        if shape is None or len(shape) < 2:
            raise TrackingError("프레임 이미지 크기를 확인할 수 없습니다.")
        image_height, image_width = int(shape[0]), int(shape[1])
        if image_height <= 0 or image_width <= 0:
            # 카메라가 순간적으로 빈 프레임을 반환해도 나눗셈까지
            # 진행하지 않는다.
            raise TrackingError(f"프레임 크기가 올바르지 않습니다: shape={shape}")
        if image_width != frame.width or image_height != frame.height:
            raise TrackingError(
                "frame metadata does not match image shape: "
                f"metadata={frame.width}x{frame.height}, "
                f"image={image_width}x{image_height}"
            )
        cv2 = _import_cv2()
        # CapturedFrame.image는 RGB인데 Ultralytics는 ndarray source를 BGR로
        # 해석한다. 학습 이미지는 cv2.imwrite로 BGR 저장했으므로
        # 여기서 다시 변환해야 학습·추론 color order가 같다.
        try:
            self._pretrack_detection_count = None
            source_bgr = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
            results = self._model.track(
                source=source_bgr,
                persist=True,
                tracker=self._tracker_config,
                conf=self._confidence,
                verbose=False,
            )
            observations = self._to_observations(
                results=results,
                frame=frame,
                image_width=image_width,
                image_height=image_height,
            )
            observed_ids = {
                observation.track_segment_id for observation in observations
            }
            ended_ids = tuple(
                track_segment_id
                for track_segment_id in self._take_newly_removed_track_segment_ids()
                if track_segment_id not in observed_ids
            )
            return TrackerFrameResult(
                observations=tuple(observations),
                all_detections_tracked=self._all_detections_tracked(
                    projected_observation_count=len(observations),
                ),
                ended_track_segment_ids=ended_ids,
            )
        except TrackingError:
            raise
        except Exception as exc:
            # color 변환, model 추론, result 정규화와 ByteTrack 상태
            # 해석을 하나의 실패 경계로 만든다. 상위 pipeline은
            # TrackingError일 때 부재 timer 연속성을 끊는다.
            raise TrackingError(
                f"YOLO/ByteTrack frame 처리에 실패했습니다: {exc}"
            ) from exc

    def _to_observations(
        self,
        *,
        results: Any,
        frame: CapturedFrame,
        image_width: int,
        image_height: int,
    ) -> list[TrackObservation]:
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

    def _capture_pretrack_detection_count(self, predictor: Any) -> None:
        """Tracker callback 전 YOLO detection 수를 frame-local로 보존한다."""

        self._pretrack_detection_count = self._result_detection_count(
            getattr(predictor, "results", None)
        )

    @staticmethod
    def _result_detection_count(results: Any) -> int | None:
        if not results:
            return 0
        boxes = getattr(results[0], "boxes", None)
        if boxes is None:
            # 현재 계약은 YOLO detect의 Boxes 결과다. OBB 등 다른
            # task를 잘못 배포했으면 빈 detection으로 간주하지 않는다.
            return None
        xyxy = getattr(boxes, "xyxy", None)
        return None if xyxy is None else len(xyxy)

    def _all_detections_tracked(
        self,
        *,
        projected_observation_count: int,
    ) -> bool:
        """ID를 받지 못한 vehicle detection이 하나라도 있으면 False다.

        ByteTrack tentative detection은 기존 차량의 재식별
        후보일 수 있으므로 해당 frame을 물리 부재 확정에
        사용하지 않는다.
        """

        source_detection_count = self._pretrack_detection_count
        if source_detection_count is None:
            # callback contract을 확인할 수 없으면 부재·입차 매칭을
            # 허용하지 않는 fail-closed 값으로 둔다.
            return False

        # post-track Results에는 active track subset만 남는다. 따라서
        # tracker 전 detection 수와 유효한 projection 수가 같아야
        # 모든 detection에 identity가 있다고 볼 수 있다.
        return source_detection_count == projected_observation_count

    def _take_newly_removed_track_segment_ids(self) -> tuple[TrackSegmentId, ...]:
        """ByteTrack max-age를 넘어 removed된 segment를 한 번만 가져온다.

        Ultralytics 8.4.108 predictor의 ByteTracker 상태를 읽는다.
        `removed_stracks`는 누적 목록이므로 이미 보고한 ID를 기억해
        반복 종료 신호를 막는다.
        """

        predictor = getattr(self._model, "predictor", None)
        trackers = getattr(predictor, "trackers", ()) if predictor is not None else ()
        removed_ids: set[TrackSegmentId] = set()
        for tracker in trackers or ():
            for removed_track in getattr(tracker, "removed_stracks", ()) or ():
                track_id = getattr(removed_track, "track_id", None)
                if track_id is not None:
                    removed_ids.add(TrackSegmentId(int(track_id)))

        new_ids = removed_ids - self._known_removed_track_segment_ids
        # removed_stracks는 누적 목록이지만 내부에서 잘릴 수 있다.
        # 현재 snapshot만 기억해 장기 실행 중 set이 무한히
        # 커지지 않게 하고 tracker reset 후 ID 재사용도 허용한다.
        self._known_removed_track_segment_ids = removed_ids
        return tuple(sorted(new_ids))

    def close(self) -> None:
        """모델 참조와 runtime 종료 보고 상태를 해제한다."""

        self._model = None
        self._pretrack_detection_count = None
        self._known_removed_track_segment_ids.clear()

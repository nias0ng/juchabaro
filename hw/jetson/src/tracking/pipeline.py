"""프레임 관측을 PhysicalVehicleSnapshot 목록으로 변환하는 추적 파이프라인(436).

Detector, EntityResolver, MotionEstimator를 조립해 TrackingBatch를 만든다.
ContextMatcher는 이번 티켓 범위 밖이다(383 미해결분, T-16) — 그래서
PhysicalVehicleSnapshot.context는 지금은 항상 None이다.

`source_available`은 항상 True다 — 이 클래스는 프레임을 성공적으로 캡처한
뒤에만 호출되므로, 카메라 장애(source_available=False)는 이 파이프라인이
아니라 application 계층이 프레임 캡처 실패를 감지했을 때 직접 판단한다.
"""

from __future__ import annotations

from src.camera.models import CapturedFrame
from src.tracking.entity_resolver import PassthroughEntityResolver
from src.tracking.motion_estimator import MotionEstimator
from src.tracking.models import PhysicalVehicleSnapshot, TrackingBatch
from src.tracking.protocols import Detector, EntityResolver


class TrackingPipeline:
    """한 카메라의 프레임을 받아 TrackingBatch를 만드는 조립 지점."""

    def __init__(
        self,
        *,
        camera_id: str,
        detector: Detector,
        entity_resolver: EntityResolver | None = None,
        motion_estimator: MotionEstimator | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._detector = detector
        self._entity_resolver = entity_resolver if entity_resolver is not None else PassthroughEntityResolver()
        self._motion_estimator = motion_estimator if motion_estimator is not None else MotionEstimator()

    def open(self) -> None:
        """탐지 모델을 초기화한다."""

        self._detector.open()

    def process(self, frame: CapturedFrame) -> TrackingBatch:
        """프레임 한 장을 처리해 TrackingBatch를 반환한다."""

        observations = self._detector.track(frame)

        vehicles: list[PhysicalVehicleSnapshot] = []
        observed_track_ids = set()
        for observation in observations:
            observed_track_ids.add(observation.track_segment_id)
            physical_vehicle_id = self._entity_resolver.resolve(observation.track_segment_id)
            motion_signal = self._motion_estimator.update(
                physical_vehicle_id=physical_vehicle_id,
                bbox=observation.bbox,
            )
            vehicles.append(
                PhysicalVehicleSnapshot(
                    physical_vehicle_id=physical_vehicle_id,
                    track_segment_id=observation.track_segment_id,
                    bbox=observation.bbox,
                    confidence=observation.confidence,
                    motion_signal=motion_signal,
                    observed_at=observation.observed_at,
                    camera_id=self._camera_id,
                    context=None,
                )
            )

        ended_ids = self._entity_resolver.resolve_ended(observed_track_ids)
        for physical_vehicle_id in ended_ids:
            self._motion_estimator.forget(physical_vehicle_id)

        return TrackingBatch(
            camera_id=self._camera_id,
            frame_id=frame.frame_id,
            observed_at=frame.captured_at,
            vehicles=tuple(vehicles),
            ended_vehicle_ids=tuple(ended_ids),
            source_available=True,
        )

    def close(self) -> None:
        """탐지 모델 자원을 해제한다."""

        self._detector.close()

"""차량 탐지·추적 구현체가 따라야 할 교체 가능한 인터페이스(436).

`TrackingError`는 이 계층(탐지·재식별·이동 판정) 전체가 공유하는 예외다 —
camera 계층의 FrameSourceError와 같은 역할이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.camera.models import CapturedFrame
from src.tracking.models import PhysicalVehicleId, TrackObservation, TrackSegmentId


class TrackingError(RuntimeError):
    """추적 계층(탐지·재식별·이동 판정) 처리 중 발생한 오류."""


@dataclass(frozen=True)
class ModelInfo:
    """결과 재현을 위해 기록하는 트래킹 라이브러리와 모델 정보."""

    library: str
    library_version: str
    model_name: str
    tracker_config: str


class Detector(Protocol):
    """전체 프레임에서 차량을 탐지하고 track_segment_id를 부여하는 계약."""

    @property
    def model_info(self) -> ModelInfo:
        """현재 설정 또는 초기화된 모델 정보를 반환한다."""

    def open(self) -> None:
        """탐지·트래킹 모델을 애플리케이션 시작 시 한 번 초기화한다."""

    def track(self, frame: CapturedFrame) -> list[TrackObservation]:
        """프레임 한 장에서 차량 목록(track_segment_id 포함)을 반환한다."""

    def close(self) -> None:
        """모델이 점유한 참조를 해제한다."""


class EntityResolver(Protocol):
    """일시적인 track_segment_id를 Jetson 내부 physical_vehicle_id로 묶는 계약.

    436는 재식별 없는 통과 구현(`entity_resolver.PassthroughEntityResolver`)만
    제공한다. 실제 재결합 알고리즘은 T-13에서 이 계약을 만족하는 구현체로
    교체한다 — pipeline.py는 이 인터페이스에만 의존하므로 교체 비용이 낮다.
    """

    def resolve(self, track_segment_id: TrackSegmentId) -> PhysicalVehicleId:
        """이번 프레임에 관측된 track_segment_id의 physical_vehicle_id를 반환한다."""

    def resolve_ended(self, observed_track_segment_ids: set[TrackSegmentId]) -> list[PhysicalVehicleId]:
        """더 이상 관측되지 않는 physical_vehicle_id 목록을 반환하고 내부 상태에서 정리한다."""

"""차량 탐지·추적 구현체가 따라야 할 교체 가능한 인터페이스.

`TrackingError`는 이 계층(탐지·재식별·이동 판정) 전체가 공유하는 예외다 —
camera 계층의 FrameSourceError와 같은 역할이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from src.camera.models import CapturedFrame
from src.tracking.models import (
    PhysicalVehicle,
    PhysicalVehicleId,
    TrackerFrameResult,
    TrackObservation,
    TrackSegmentId,
)


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

    def track(self, frame: CapturedFrame) -> TrackerFrameResult:
        """프레임 관측·detection coverage·확정 segment 종료를 반환한다."""

    def close(self) -> None:
        """모델이 점유한 참조를 해제한다."""


class EntityResolver(Protocol):
    """일시적인 track_segment_id를 Jetson 내부 physical_vehicle_id로 묶는 계약.

    현재 기본 구현은 segment를 1:1로 매핑한다. 후속 재식별
    구현이 bbox·confidence·observedAt을 근거로 쓸 수 있도록
    숫자 ID가 아닌 전체 ``TrackObservation``을 받는다.
    """

    def resolve(self, observation: TrackObservation) -> PhysicalVehicleId:
        """이번 관측 segment의 physical_vehicle_id를 반환한다."""

    def end_track_segments(
        self,
        ended_track_segment_ids: set[TrackSegmentId],
    ) -> None:
        """확정 종료된 segment 연결만 해제하고 값을 반환하지 않는다."""

    def forget_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> None:
        """PhysicalVehicle 종료 commit 후 남은 segment 연결을 모두 해제한다."""

    def reset_track_segments(self) -> None:
        """Tracker runtime reset 후 기존 segment 연결을 모두 폐기한다."""


@runtime_checkable
class RestartAwareEntityResolver(EntityResolver, Protocol):
    """재시작 뒤 durable active identity를 재식별할 수 있는 resolver."""

    def restore_active_physical_vehicles(
        self,
        vehicles: tuple[PhysicalVehicle, ...],
    ) -> None:
        """후속 ``resolve()``가 복구 identity를 반환하도록 후보를 복원한다."""

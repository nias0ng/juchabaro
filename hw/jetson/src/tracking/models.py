"""추적 관측과 Jetson-local 물리 차량 동일성 계약.

TrackSegment와 bbox는 process 안에서만 사용하는 관측값이다. PhysicalVehicle은
여러 TrackSegment를 이어 붙일 수 있는 별도 가설이며, track 소실만으로 종료하지
않는다. Backend session·등록 차량 식별자는 물리 차량 식별자를 대체하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import NewType
from uuid import UUID

from src.domain.models import (
    ObservationState,
    ObservationStatus,
    require_aware,
    require_non_negative,
    require_positive,
)


TrackSegmentId = NewType("TrackSegmentId", int)
PhysicalVehicleId = NewType("PhysicalVehicleId", UUID)
ParkingSessionId = NewType("ParkingSessionId", int)
VehicleId = NewType("VehicleId", int)


class TrackSegmentState(str, Enum):
    """한 tracker runtime 안에서만 유효한 연속 추적 구간 상태."""

    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class PhysicalVehicleState(str, Enum):
    """Jetson이 같은 실차로 판단하는 관측 가설의 수명주기."""

    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    CANCELED = "CANCELED"


class MotionSignal(str, Enum):
    """이동 판정기가 시간적 주차 판단에 전달하는 삼상태 관측값."""

    MOVING = "MOVING"
    STATIONARY = "STATIONARY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BoundingBox:
    """0~1 정규화 좌표의 ephemeral 차량 바운딩박스."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        if not all(0.0 <= value <= 1.0 for value in (self.x1, self.y1, self.x2, self.y2)):
            raise ValueError("bounding box coordinates must be normalized to [0, 1]")
        if self.x1 >= self.x2 or self.y1 >= self.y2:
            raise ValueError("bounding box must have positive width and height")


@dataclass(frozen=True)
class TrackObservation:
    """한 frame에서 tracker가 만든 비영속 관측."""

    track_segment_id: TrackSegmentId
    bbox: BoundingBox
    confidence: float
    observed_at: datetime

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, kw_only=True)
class PhysicalVehicle:
    """동일 장치 재시작 뒤 이어갈 수 있는 물리 차량 aggregate snapshot."""

    physical_vehicle_id: PhysicalVehicleId
    state: PhysicalVehicleState
    observation: ObservationStatus
    absence_trusted_seconds: float
    absence_confirmation_seconds: float
    record_version: int
    created_at: datetime
    updated_at: datetime
    terminated_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_negative(self.absence_trusted_seconds, "absence_trusted_seconds")
        require_non_negative(self.absence_confirmation_seconds, "absence_confirmation_seconds")
        require_positive(self.record_version, "record_version")
        for name in ("created_at", "updated_at", "terminated_at"):
            require_aware(getattr(self, name), name)
        is_terminal = self.state in {PhysicalVehicleState.RETIRED, PhysicalVehicleState.CANCELED}
        if is_terminal != (self.terminated_at is not None):
            raise ValueError("terminal PhysicalVehicle must have terminated_at, and only terminal state may have it")
        if is_terminal != (self.termination_reason is not None):
            raise ValueError("terminal PhysicalVehicle must have termination_reason")


@dataclass(frozen=True)
class PhysicalVehicleSnapshot:
    """한 frame에서 재구성한 PhysicalVehicle의 ephemeral 관측 projection."""

    physical_vehicle_id: PhysicalVehicleId
    track_segment_id: TrackSegmentId
    bbox: BoundingBox
    confidence: float
    motion_signal: MotionSignal
    observed_at: datetime
    camera_id: str
    observation: ObservationStatus | None = None

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not self.camera_id:
            raise ValueError("camera_id must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.observation is None:
            object.__setattr__(
                self,
                "observation",
                ObservationStatus(
                    state=ObservationState.OBSERVED,
                    last_reliable_observed_at=self.observed_at,
                ),
            )


@dataclass(frozen=True)
class TrackingBatch:
    """한 frame의 추적 결과와 관측 신뢰도를 묶는 비영속 값.

    TrackSegment 종료와 PhysicalVehicle 관측 소실은 실제 부재와 구분한다.
    RETIRED·EXIT·RESOLVE의 근거는 정상 전체 관측에서 확정한
    `not_present_confirmed_vehicle_ids`뿐이다.
    """

    camera_id: str
    frame_id: int
    observed_at: datetime
    vehicles: tuple[PhysicalVehicleSnapshot, ...]
    ended_track_segment_ids: tuple[TrackSegmentId, ...]
    unobserved_physical_vehicle_ids: tuple[PhysicalVehicleId, ...]
    observation: ObservationStatus
    full_area_observed: bool = False
    not_present_confirmed_vehicle_ids: tuple[PhysicalVehicleId, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not self.camera_id:
            raise ValueError("camera_id must not be empty")
        require_non_negative(self.frame_id, "frame_id")

        if self.not_present_confirmed_vehicle_ids and not (
            self.observation.state is ObservationState.OBSERVED and self.full_area_observed
        ):
            raise ValueError(
                "NOT_PRESENT_CONFIRMED requires healthy OBSERVED full-area observation"
            )

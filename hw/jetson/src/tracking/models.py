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


@dataclass(frozen=True)
class DetectionObservation:
    """confidence threshold를 통과한 tracker 적용 전 YOLO detection.

    판정·identity 입력이 아니라 모델 품질 분석용 ephemeral 진단값이다.
    ByteTrack ID가 붙지 않은 후보도 보존해 confidence 분포와 detection
    누락을 viewer에서 재구성할 수 있게 한다.
    """

    bbox: BoundingBox
    confidence: float
    class_id: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("detection confidence must be between 0 and 1")
        require_non_negative(self.class_id, "class_id")


@dataclass(frozen=True)
class TrackerFrameResult:
    """Tracker adapter가 한 frame에서 확정한 관측과 segment 종료.

    현재 frame에 보이지 않는 것은 종료가 아니다. `ended_track_segment_ids`는
    ByteTrack max-age 등 adapter가 소유한 종료 규칙이 충족된 경우에만 보고한다.
    `all_detections_tracked=False`는 ID가 없는 tentative detection이 있어
    해당 frame을 물리 부재 확정의 신뢰 sample로 쓸 수 없음을 의미한다.
    """

    observations: tuple[TrackObservation, ...]
    all_detections_tracked: bool
    ended_track_segment_ids: tuple[TrackSegmentId, ...] = ()
    detection_count: int | None = None
    detections: tuple[DetectionObservation, ...] = ()

    def __post_init__(self) -> None:
        observed_ids = tuple(observation.track_segment_id for observation in self.observations)
        if len(observed_ids) != len(set(observed_ids)):
            raise ValueError("tracker frame cannot contain duplicate observed track segment ids")
        if len(self.ended_track_segment_ids) != len(set(self.ended_track_segment_ids)):
            raise ValueError("tracker frame cannot contain duplicate ended track segment ids")
        if set(observed_ids).intersection(self.ended_track_segment_ids):
            raise ValueError("a track segment cannot be observed and ended in the same frame")
        if self.detection_count is not None:
            require_non_negative(self.detection_count, "detection_count")
            if self.detection_count < len(self.detections):
                raise ValueError(
                    "detection_count cannot be smaller than projected detections"
                )


@dataclass(frozen=True, kw_only=True)
class PhysicalVehicle:
    """동일 장치 재시작 뒤 이어갈 수 있는 물리 차량 aggregate snapshot."""

    physical_vehicle_id: PhysicalVehicleId
    state: PhysicalVehicleState
    observation: ObservationStatus
    absence_trusted_seconds: float
    absence_confirmation_seconds: float
    trusted_sample_max_gap_seconds: float
    record_version: int
    created_at: datetime
    updated_at: datetime
    absence_confirmed_at: datetime | None = None
    terminated_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        require_non_negative(self.absence_trusted_seconds, "absence_trusted_seconds")
        require_positive(self.absence_confirmation_seconds, "absence_confirmation_seconds")
        require_positive(
            self.trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        if round(self.absence_confirmation_seconds * 1_000_000) <= 0:
            raise ValueError(
                "absence_confirmation_seconds must be at least one microsecond"
            )
        if round(self.trusted_sample_max_gap_seconds * 1_000_000) <= 0:
            raise ValueError(
                "trusted_sample_max_gap_seconds must be at least one microsecond"
            )
        require_positive(self.record_version, "record_version")
        for name in (
            "created_at",
            "updated_at",
            "absence_confirmed_at",
            "terminated_at",
        ):
            require_aware(getattr(self, name), name)
        absence_is_confirmed = (
            round(self.absence_trusted_seconds * 1_000_000)
            >= round(self.absence_confirmation_seconds * 1_000_000)
        )
        if absence_is_confirmed != (self.absence_confirmed_at is not None):
            raise ValueError(
                "absence_confirmed_at must exist exactly when trusted absence "
                "reaches its confirmation threshold"
            )
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
    observation: ObservationStatus

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not self.camera_id:
            raise ValueError("camera_id must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class PhysicalVehicleAbsenceProgress:
    """정상 전체 관측으로 누적한 차량별 부재 timer snapshot."""

    physical_vehicle_id: PhysicalVehicleId
    trusted_seconds: float
    confirmed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_non_negative(self.trusted_seconds, "trusted_seconds")
        require_aware(self.confirmed_at, "confirmed_at")


@dataclass(frozen=True)
class TrackingBatch:
    """한 frame의 추적 결과와 관측 신뢰도를 묶는 비영속 값.

    TrackSegment 종료와 PhysicalVehicle 관측 소실은 실제 부재와 구분한다.
    `all_detections_tracked=False`이면 ID 없는 tentative detection이
    있으므로 부재 누적과 entry identity 매칭에 쓰지 않는다.
    RETIRED·EXIT·RESOLVE의 근거는 정상 전체 관측에서 확정한
    `not_present_confirmed_vehicle_ids`뿐이다. 한번 확정한 사실은 commit
    ack 전까지 반복되므로 현재 batch가 degraded여도 포함될 수 있다.
    """

    camera_id: str
    frame_id: int
    observed_at: datetime
    vehicles: tuple[PhysicalVehicleSnapshot, ...]
    ended_track_segment_ids: tuple[TrackSegmentId, ...]
    unobserved_physical_vehicle_ids: tuple[PhysicalVehicleId, ...]
    absence_progress: tuple[PhysicalVehicleAbsenceProgress, ...]
    observation: ObservationStatus
    full_area_observed: bool
    all_detections_tracked: bool
    not_present_confirmed_vehicle_ids: tuple[PhysicalVehicleId, ...] = ()
    detection_count: int | None = None
    detections: tuple[DetectionObservation, ...] = ()

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if not self.camera_id:
            raise ValueError("camera_id must not be empty")
        require_non_negative(self.frame_id, "frame_id")
        if self.detection_count is not None:
            require_non_negative(self.detection_count, "detection_count")
            if self.detection_count < len(self.detections):
                raise ValueError(
                    "detection_count cannot be smaller than projected detections"
                )

        observed_vehicle_ids = {
            snapshot.physical_vehicle_id for snapshot in self.vehicles
        }
        unobserved_vehicle_ids = set(self.unobserved_physical_vehicle_ids)
        progress_vehicle_ids = tuple(
            progress.physical_vehicle_id for progress in self.absence_progress
        )
        confirmed_vehicle_ids = tuple(self.not_present_confirmed_vehicle_ids)
        if len(progress_vehicle_ids) != len(set(progress_vehicle_ids)):
            raise ValueError(
                "absence progress cannot contain duplicate PhysicalVehicle ids"
            )
        if set(progress_vehicle_ids) != unobserved_vehicle_ids:
            raise ValueError(
                "absence progress must cover every unobserved PhysicalVehicle exactly once"
            )
        if len(confirmed_vehicle_ids) != len(set(confirmed_vehicle_ids)):
            raise ValueError(
                "NOT_PRESENT_CONFIRMED cannot contain duplicate PhysicalVehicle ids"
            )
        if observed_vehicle_ids.intersection(unobserved_vehicle_ids):
            raise ValueError(
                "a PhysicalVehicle cannot be observed and unobserved in the same batch"
            )
        if observed_vehicle_ids.intersection(
            self.not_present_confirmed_vehicle_ids
        ):
            raise ValueError(
                "a PhysicalVehicle cannot be observed and NOT_PRESENT_CONFIRMED "
                "in the same batch"
            )
        if not set(self.not_present_confirmed_vehicle_ids).issubset(
            unobserved_vehicle_ids
        ):
            raise ValueError(
                "NOT_PRESENT_CONFIRMED must reference an unobserved PhysicalVehicle"
            )
        progress_confirmed_vehicle_ids = {
            progress.physical_vehicle_id
            for progress in self.absence_progress
            if progress.confirmed_at is not None
        }
        if progress_confirmed_vehicle_ids != set(confirmed_vehicle_ids):
            raise ValueError(
                "NOT_PRESENT_CONFIRMED ids and confirmed absence progress must match"
            )

        # NOT_PRESENT는 정상 전체 관측에서만 새로 확정하지만, 확정된 사실은
        # 상위 consistency boundary의 commit ack까지 degraded batch에서도
        # 반복될 수 있다. 이 값 객체는 현재 sample의 신뢰도와 과거에 확정한
        # 사실을 같은 축으로 묶어 다시 거부하지 않는다.

"""여러 aggregate가 공유하는 관측·전달·저장 상태 값.

도메인 수명주기, 현재 관측 신뢰도, Backend 전달 상태를 서로 다른 축으로
유지한다. 이 모듈은 거대한 공통 aggregate를 제공하지 않으며 각 owner가 자기
수명주기와 record를 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ObservationState(str, Enum):
    """현재 판단에 필요한 관측의 신뢰 수준."""

    OBSERVED = "OBSERVED"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"


class ObservationReason(str, Enum):
    """관측이 정상적이지 않은 대표 원인.

    원인 자체는 어떤 scope의 terminal reason도 아니다.
    """

    CAMERA_UNAVAILABLE = "CAMERA_UNAVAILABLE"
    PIPELINE_STALLED = "PIPELINE_STALLED"
    PARTIAL_FRAME = "PARTIAL_FRAME"
    TRACK_LOST = "TRACK_LOST"
    REIDENTIFICATION_UNCERTAIN = "REIDENTIFICATION_UNCERTAIN"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    PROCESS_RESTARTED = "PROCESS_RESTARTED"
    RESOURCE_PRESSURE = "RESOURCE_PRESSURE"


class DeliveryState(str, Enum):
    """한 번 확정한 immutable publication의 전달 workflow 상태."""

    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    RETRY_WAIT = "RETRY_WAIT"
    DELIVERED = "DELIVERED"
    FAILED_TERMINAL = "FAILED_TERMINAL"


class StorageWatermark(str, Enum):
    """로컬 저장공간 pressure 단계."""

    NORMAL = "NORMAL"
    WARN = "WARN"
    CRITICAL = "CRITICAL"
    DRAIN = "DRAIN"


def require_aware(value: datetime | None, field_name: str) -> None:
    """도메인 timestamp가 timezone-aware인지 확인한다."""

    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


def require_non_negative(value: int | float, field_name: str) -> None:
    """누적 시간·revision처럼 음수가 될 수 없는 값을 확인한다."""

    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")


def require_positive(value: int | float, field_name: str) -> None:
    """확인 임계값·record version처럼 양수여야 하는 값을 확인한다."""

    if value <= 0:
        raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True, kw_only=True)
class ObservationStatus:
    """도메인 상태와 독립적으로 보존하는 현재 관측 상태."""

    state: ObservationState
    reason: ObservationReason | None = None
    last_reliable_observed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.last_reliable_observed_at, "last_reliable_observed_at")
        if self.state is ObservationState.OBSERVED:
            if self.reason is not None:
                raise ValueError("OBSERVED observation cannot have a degradation reason")
            if self.last_reliable_observed_at is None:
                raise ValueError("OBSERVED observation requires last_reliable_observed_at")

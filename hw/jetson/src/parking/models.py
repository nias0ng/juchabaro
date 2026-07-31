"""구역 방문, 주차 에피소드, 위반 사건의 공통 상태 계약.

공간 겹침·이동·위반 여부의 계산 방법은 정의하지 않고, 계산된 신호가
따라야 할 상태와 식별자만 고정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, NewType

from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleId,
)


ZoneId = NewType("ZoneId", int)
ZoneVisitId = NewType("ZoneVisitId", str)
ParkingEpisodeId = NewType("ParkingEpisodeId", str)
IncidentId = NewType("IncidentId", str)


class PresenceSignal(str, Enum):
    """구역 기하 계산 구현체가 방문 상태 머신에 전달하는 관측값."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class ZoneVisitState(str, Enum):
    """차량 하나와 구역 하나 사이의 방문 상태."""

    OUTSIDE = "OUTSIDE"
    ENTERING = "ENTERING"
    INSIDE = "INSIDE"
    EXITING = "EXITING"


class ParkingState(str, Enum):
    """물리 차량의 주차 에피소드 상태."""

    MOVING = "MOVING"
    STOP_PENDING = "STOP_PENDING"
    PARKED = "PARKED"
    ENDED = "ENDED"


class IncidentState(str, Enum):
    """Jetson 내부 후보부터 Backend 전송 이후 해소까지의 사건 상태."""

    CANDIDATE = "CANDIDATE"
    EDGE_CONFIRMED = "EDGE_CONFIRMED"
    RESOLVED = "RESOLVED"


class IncidentTransitionType(str, Enum):
    """Backend 전송 대상이 되는 사건 전이."""

    OPEN = "OPEN"
    RESOLVE = "RESOLVE"


@dataclass(frozen=True)
class ZoneVisit:
    """한 물리 차량이 한 구역을 연속해서 방문한 구간."""

    visit_id: ZoneVisitId
    physical_vehicle_id: PhysicalVehicleId
    zone_id: ZoneId
    state: ZoneVisitState
    entered_candidate_at: datetime | None = None
    entered_at: datetime | None = None
    exit_candidate_at: datetime | None = None
    exited_at: datetime | None = None


@dataclass(frozen=True)
class ParkingEpisode:
    """정지 후보 시작부터 주차 확정 및 종료까지의 독립된 주차 구간."""

    episode_id: ParkingEpisodeId
    physical_vehicle_id: PhysicalVehicleId
    parking_session_id: ParkingSessionId | None
    state: ParkingState
    stationary_observed_seconds: float
    last_signal: MotionSignal
    last_observed_at: datetime
    parked_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass(frozen=True)
class IncidentKey:
    """중복 판정과 사건 동일성 판단에 사용하는 도메인 키."""

    physical_vehicle_id: PhysicalVehicleId
    rule_code: str
    parking_episode_id: ParkingEpisodeId | None = None
    zone_visit_id: ZoneVisitId | None = None
    zone_id: ZoneId | None = None
    victim_physical_vehicle_id: PhysicalVehicleId | None = None


@dataclass(frozen=True)
class IncidentSignal:
    """개별 위반 규칙이 사건 축약기에 전달하는 공통 결과."""

    key: IncidentKey
    matched: bool
    confirmable: bool
    observed_at: datetime
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Incident:
    """동일한 IncidentKey로 유지되는 사건의 현재 상태."""

    incident_id: IncidentId
    key: IncidentKey
    state: IncidentState
    revision: int
    first_observed_at: datetime
    confirmed_at: datetime | None = None
    resolved_at: datetime | None = None


@dataclass(frozen=True)
class IncidentTransition:
    """확정 또는 해소 시 Backend로 전달할 수 있는 사건 전이."""

    transition_type: IncidentTransitionType
    incident: Incident

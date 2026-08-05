"""ZoneVisit, ParkingEpisode, BlockingRelation과 Incident 계약.

공간·주차 scope의 수명과 Incident 수명을 분리한다. 특히 이동 확정은
ParkingEpisode를 끝내고 규칙 재평가를 요청할 뿐 Incident를 직접 해소하지
않는다. 반복 frame 신호와 bbox는 이 모듈의 durable record가 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, NewType
from uuid import UUID

from src.domain.models import (
    ObservationStatus,
    require_aware,
    require_non_negative,
    require_positive,
)
from src.session.models import EntryAttemptId
from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicleId,
    TrackSegmentId,
)


ZoneId = NewType("ZoneId", int)
EgressAisleId = NewType("EgressAisleId", int)
ZoneDefinitionVersion = NewType("ZoneDefinitionVersion", int)
EgressAisleDefinitionVersion = NewType("EgressAisleDefinitionVersion", int)
ZoneVisitId = NewType("ZoneVisitId", UUID)
ParkingEpisodeId = NewType("ParkingEpisodeId", UUID)
BlockingRelationId = NewType("BlockingRelationId", UUID)
IncidentId = NewType("IncidentId", UUID)

NormalizedPoint = tuple[float, float]
NormalizedPolygon = tuple[NormalizedPoint, ...]
_PLACEMENT_RATIO_TOLERANCE = 1e-9


class ZoneType(str, Enum):
    """현재 단일-camera 배포에서 사용하는 기본 Zone 종류."""

    GENERAL = "GENERAL"
    DISABLED = "DISABLED"
    EV_CHARGING = "EV_CHARGING"
    AISLE = "AISLE"
    ENTRY_EXIT = "ENTRY_EXIT"


class EntryExitRole(str, Enum):
    """ENTRY_EXIT 구역이 입차와 출차 중 어느 경계인지 구분한다."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"


class PresenceSignal(str, Enum):
    """구역 기하 계산이 ZoneVisitTracker에 전달하는 삼상태 관측."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNKNOWN = "UNKNOWN"


class ZoneVisitState(str, Enum):
    """한 PhysicalVehicle과 한 zone 사이의 연속 방문 상태."""

    ENTERING = "ENTERING"
    INSIDE = "INSIDE"
    EXITING = "EXITING"
    ENDED = "ENDED"
    CANCELED = "CANCELED"


class ParkingState(str, Enum):
    """한 PhysicalVehicle의 연속 정지·주차 행위 상태."""

    STOP_PENDING = "STOP_PENDING"
    PARKED = "PARKED"
    MOVE_PENDING = "MOVE_PENDING"
    ENDED = "ENDED"
    CANCELED = "CANCELED"


class ParkingTransitionType(str, Enum):
    """A publishable transition from a ParkingEpisode."""

    PARKED = "PARKED"
    UNPARKED = "UNPARKED"


class BlockingRelationState(str, Enum):
    """순서가 있는 subject·victim·egress 차단 관계 상태."""

    CANDIDATE = "CANDIDATE"
    BLOCKING = "BLOCKING"
    CLEAR_PENDING = "CLEAR_PENDING"
    RESOLVED = "RESOLVED"
    CANCELED = "CANCELED"


class IncidentState(str, Enum):
    """로컬 Candidate부터 공개·해소까지의 Incident 상태."""

    CANDIDATE = "CANDIDATE"
    OPEN = "OPEN"
    CLEAR_PENDING = "CLEAR_PENDING"
    RESOLVED = "RESOLVED"
    CANCELED = "CANCELED"


class IncidentSignalValue(str, Enum):
    """RuleEvaluator가 IncidentReducer에 전달하는 삼상태 술어 결과."""

    MATCHED = "MATCHED"
    NOT_MATCHED = "NOT_MATCHED"
    UNKNOWN = "UNKNOWN"


class IncidentTransitionType(str, Enum):
    """Backend publication 대상이 되는 Incident 전이."""

    OPEN = "OPEN"
    RESOLVE = "RESOLVE"


class IncidentKeyScope(str, Enum):
    """규칙별 Incident continuity를 결정하는 scope 종류."""

    ZONE_VISIT = "ZONE_VISIT"
    PHYSICAL_VEHICLE = "PHYSICAL_VEHICLE"
    BLOCKING_RELATION = "BLOCKING_RELATION"


class AssignmentState(str, Enum):
    """ParkingEpisode 안에서 안정화한 대표 주차 위치 결과."""

    ASSIGNED = "ASSIGNED"
    AMBIGUOUS = "AMBIGUOUS"
    UNASSIGNED = "UNASSIGNED"


class PlacementEvidenceSource(str, Enum):
    """Rule evaluation에 사용한 공간 근거의 시간적 출처."""

    EPHEMERAL_FRAME = "EPHEMERAL_FRAME"
    PARKED_SNAPSHOT = "PARKED_SNAPSHOT"


@dataclass(frozen=True, kw_only=True)
class ZoneOverlapEvidence:
    """차량 footprint 대비 한 주차면의 포함 비율."""

    zone_id: ZoneId
    overlap_ratio: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.overlap_ratio <= 1.0:
            raise ValueError("zone overlap ratio must be between 0 and 1")


@dataclass(frozen=True, kw_only=True)
class PlacementEvidence:
    """Assignment와 공간 위반 규칙이 함께 소비하는 순수 geometry 근거."""

    representative_footprint: NormalizedPolygon
    zone_definition_version: ZoneDefinitionVersion
    observed_at: datetime
    candidate_overlaps: tuple[ZoneOverlapEvidence, ...]
    primary_zone_id: ZoneId | None
    primary_overlap_ratio: float
    secondary_zone_id: ZoneId | None
    secondary_overlap_ratio: float
    dominance_gap: float
    spot_union_overlap_ratio: float
    outside_spot_overlap_ratio: float

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        require_positive(
            self.zone_definition_version,
            "zone_definition_version",
        )
        if len(self.representative_footprint) < 3:
            raise ValueError("placement footprint requires at least three points")
        for point in self.representative_footprint:
            if len(point) != 2 or not all(
                0.0 <= coordinate <= 1.0 for coordinate in point
            ):
                raise ValueError(
                    "placement footprint must use normalized coordinates"
                )
        for name in (
            "primary_overlap_ratio",
            "secondary_overlap_ratio",
            "dominance_gap",
            "spot_union_overlap_ratio",
            "outside_spot_overlap_ratio",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        expected_primary = (
            None if not self.candidate_overlaps else self.candidate_overlaps[0].zone_id
        )
        expected_secondary = (
            None
            if len(self.candidate_overlaps) < 2
            else self.candidate_overlaps[1].zone_id
        )
        if self.primary_zone_id != expected_primary:
            raise ValueError("primary zone must match ranked candidate evidence")
        if self.secondary_zone_id != expected_secondary:
            raise ValueError("secondary zone must match ranked candidate evidence")
        candidate_zone_ids = tuple(
            item.zone_id for item in self.candidate_overlaps
        )
        if len(candidate_zone_ids) != len(set(candidate_zone_ids)):
            raise ValueError("candidate overlap zone ids must be unique")
        ranked = tuple(
            (-item.overlap_ratio, int(item.zone_id))
            for item in self.candidate_overlaps
        )
        if ranked != tuple(sorted(ranked)):
            raise ValueError("candidate overlaps must use deterministic rank order")
        expected_primary_ratio = (
            0.0
            if not self.candidate_overlaps
            else self.candidate_overlaps[0].overlap_ratio
        )
        expected_secondary_ratio = (
            0.0
            if len(self.candidate_overlaps) < 2
            else self.candidate_overlaps[1].overlap_ratio
        )
        expected_gap = expected_primary_ratio - expected_secondary_ratio
        expected_union = min(
            1.0,
            sum(item.overlap_ratio for item in self.candidate_overlaps),
        )
        for actual, expected, name in (
            (
                self.primary_overlap_ratio,
                expected_primary_ratio,
                "primary overlap ratio",
            ),
            (
                self.secondary_overlap_ratio,
                expected_secondary_ratio,
                "secondary overlap ratio",
            ),
            (self.dominance_gap, expected_gap, "dominance gap"),
            (self.spot_union_overlap_ratio, expected_union, "spot union ratio"),
        ):
            if abs(actual - expected) > _PLACEMENT_RATIO_TOLERANCE:
                raise ValueError(f"{name} must match candidate evidence")
        if abs(
            self.outside_spot_overlap_ratio
            - (1.0 - self.spot_union_overlap_ratio)
        ) > _PLACEMENT_RATIO_TOLERANCE:
            raise ValueError("outside ratio must complement spot union ratio")


@dataclass(frozen=True, kw_only=True)
class EgressAisleDefinition:
    """이중주차 관계 판정에만 사용하는 출차 공간 정의."""

    egress_zone_id: EgressAisleId
    parking_zone_id: ZoneId
    polygon: NormalizedPolygon
    egress_aisle_definition_version: EgressAisleDefinitionVersion
    zone_definition_version: ZoneDefinitionVersion
    calibration_reference: str

    def __post_init__(self) -> None:
        require_positive(self.egress_zone_id, "egress_zone_id")
        require_positive(self.parking_zone_id, "parking_zone_id")
        require_positive(
            self.egress_aisle_definition_version,
            "egress_aisle_definition_version",
        )
        require_positive(self.zone_definition_version, "zone_definition_version")
        if not self.calibration_reference:
            raise ValueError("calibration_reference must not be empty")
        if len(self.polygon) < 3:
            raise ValueError("egress aisle polygon requires at least three points")
        for point in self.polygon:
            if len(point) != 2 or not all(
                0.0 <= coordinate <= 1.0 for coordinate in point
            ):
                raise ValueError(
                    "egress aisle polygon coordinates must be normalized to [0, 1]"
                )


@dataclass(frozen=True, kw_only=True)
class EgressBlockingEvidence:
    """차량 footprint과 egress aisle의 immutable ephemeral 교차 근거."""

    egress_zone_id: EgressAisleId
    parking_zone_id: ZoneId
    representative_footprint: NormalizedPolygon
    subject_overlap_ratio: float
    egress_coverage_ratio: float
    intersection_area: float

    def __post_init__(self) -> None:
        require_positive(self.egress_zone_id, "egress_zone_id")
        require_positive(self.parking_zone_id, "parking_zone_id")
        for name in ("subject_overlap_ratio", "egress_coverage_ratio"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        require_non_negative(self.intersection_area, "intersection_area")
        if len(self.representative_footprint) < 3:
            raise ValueError("egress blocking footprint requires at least three points")
        for point in self.representative_footprint:
            if len(point) != 2 or not all(
                0.0 <= coordinate <= 1.0 for coordinate in point
            ):
                raise ValueError(
                    "egress blocking footprint must use normalized coordinates"
                )


@dataclass(frozen=True, kw_only=True)
class ZoneDefinition:
    """통제된 기동 시 배포하는 versioned 공간 정의."""

    zone_id: ZoneId
    zone_type: ZoneType
    polygon: NormalizedPolygon
    zone_definition_version: ZoneDefinitionVersion
    calibration_reference: str
    entry_exit_role: EntryExitRole | None = None
    allowed_duration_seconds: float | None = None
    charger_class: str | None = None
    egress_zone_ids: tuple[ZoneId, ...] = ()

    def __post_init__(self) -> None:
        require_positive(self.zone_definition_version, "zone_definition_version")
        if not self.calibration_reference:
            raise ValueError("calibration_reference must not be empty")
        if len(self.polygon) < 3:
            raise ValueError("zone polygon requires at least three points")
        for point in self.polygon:
            if len(point) != 2 or not all(0.0 <= coordinate <= 1.0 for coordinate in point):
                raise ValueError("zone polygon coordinates must be normalized to [0, 1]")

        is_entry_exit = self.zone_type is ZoneType.ENTRY_EXIT
        if is_entry_exit != (self.entry_exit_role is not None):
            raise ValueError(
                "ENTRY_EXIT requires entry_exit_role; other zone types must not carry it"
            )

        ev_only_values_present = self.allowed_duration_seconds is not None or self.charger_class is not None
        if ev_only_values_present and self.zone_type is not ZoneType.EV_CHARGING:
            raise ValueError("allowed duration and charger class are valid only for EV_CHARGING")
        if self.allowed_duration_seconds is not None:
            require_positive(self.allowed_duration_seconds, "allowed_duration_seconds")


@dataclass(frozen=True, kw_only=True)
class ParkingAssignment:
    """ParkingEpisode에 포함되는 대표 주차 위치 값 객체."""

    state: AssignmentState
    representative_footprint: NormalizedPolygon
    confidence: float
    last_stable_at: datetime
    zone_id: ZoneId | None = None
    unassigned_reason: str | None = None

    def __post_init__(self) -> None:
        require_aware(self.last_stable_at, "last_stable_at")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("assignment confidence must be between 0 and 1")
        if len(self.representative_footprint) < 3:
            raise ValueError("representative footprint requires at least three points")
        for point in self.representative_footprint:
            if len(point) != 2 or not all(0.0 <= coordinate <= 1.0 for coordinate in point):
                raise ValueError("representative footprint must use normalized coordinates")

        is_assigned = self.state is AssignmentState.ASSIGNED
        if is_assigned != (self.zone_id is not None):
            raise ValueError("ASSIGNED requires zone_id; non-assigned states must not have one")
        if is_assigned == (self.unassigned_reason is not None):
            raise ValueError("non-assigned states require unassigned_reason exclusively")


@dataclass(frozen=True, kw_only=True)
class ZoneVisit:
    """한 PhysicalVehicle과 한 versioned zone 사이의 연속 방문 snapshot."""

    visit_id: ZoneVisitId
    physical_vehicle_id: PhysicalVehicleId
    zone_id: ZoneId
    zone_definition_version: ZoneDefinitionVersion
    state: ZoneVisitState
    observation: ObservationStatus
    entry_trusted_seconds: float
    exit_trusted_seconds: float
    entry_confirmation_seconds: float
    exit_confirmation_seconds: float
    record_version: int
    created_at: datetime
    updated_at: datetime
    trusted_sample_max_gap_seconds: float
    entered_candidate_at: datetime | None = None
    entered_at: datetime | None = None
    exit_candidate_at: datetime | None = None
    ended_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        require_positive(self.zone_definition_version, "zone_definition_version")
        for name in ("entry_trusted_seconds", "exit_trusted_seconds"):
            require_non_negative(getattr(self, name), name)
        for name in ("entry_confirmation_seconds", "exit_confirmation_seconds"):
            require_non_negative(getattr(self, name), name)
        require_positive(
            self.trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        if round(self.trusted_sample_max_gap_seconds * 1_000_000) <= 0:
            raise ValueError(
                "trusted_sample_max_gap_seconds must be at least one microsecond"
            )
        require_positive(self.record_version, "record_version")
        for name in (
            "created_at",
            "updated_at",
            "entered_candidate_at",
            "entered_at",
            "exit_candidate_at",
            "ended_at",
        ):
            require_aware(getattr(self, name), name)

        is_terminal = self.state in {ZoneVisitState.ENDED, ZoneVisitState.CANCELED}
        if is_terminal != (self.ended_at is not None):
            raise ValueError("terminal ZoneVisit must have ended_at")
        if is_terminal != (self.termination_reason is not None):
            raise ValueError("terminal ZoneVisit must have termination_reason")
        if self.state in {ZoneVisitState.INSIDE, ZoneVisitState.EXITING, ZoneVisitState.ENDED}:
            if self.entered_at is None:
                raise ValueError("confirmed visit state requires entered_at")
        if self.state is ZoneVisitState.ENTERING and self.entered_candidate_at is None:
            raise ValueError("ENTERING ZoneVisit requires entered_candidate_at")
        if self.state is ZoneVisitState.EXITING and self.exit_candidate_at is None:
            raise ValueError("EXITING ZoneVisit requires exit_candidate_at")


@dataclass(frozen=True, kw_only=True)
class ParkingEpisode:
    """정지 후보부터 주차 확정과 이동·실제 출차까지의 행위 snapshot."""

    episode_id: ParkingEpisodeId
    physical_vehicle_id: PhysicalVehicleId
    state: ParkingState
    observation: ObservationStatus
    stationary_trusted_seconds: float
    movement_trusted_seconds: float
    parking_confirmation_seconds: float
    movement_confirmation_seconds: float
    last_signal: MotionSignal
    record_version: int
    publication_revision: int
    created_at: datetime
    updated_at: datetime
    trusted_sample_max_gap_seconds: float
    parking_session_id: ParkingSessionId | None = None
    assignment: ParkingAssignment | None = None
    parked_at: datetime | None = None
    movement_candidate_at: datetime | None = None
    ended_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("stationary_trusted_seconds", "movement_trusted_seconds", "publication_revision"):
            require_non_negative(getattr(self, name), name)
        require_positive(self.parking_confirmation_seconds, "parking_confirmation_seconds")
        require_non_negative(self.movement_confirmation_seconds, "movement_confirmation_seconds")
        require_positive(
            self.trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        if round(self.trusted_sample_max_gap_seconds * 1_000_000) <= 0:
            raise ValueError(
                "trusted_sample_max_gap_seconds must be at least one microsecond"
            )
        require_positive(self.record_version, "record_version")
        for name in ("created_at", "updated_at", "parked_at", "movement_candidate_at", "ended_at"):
            require_aware(getattr(self, name), name)
        was_parked = self.state in {ParkingState.PARKED, ParkingState.MOVE_PENDING, ParkingState.ENDED}
        if was_parked and (self.parked_at is None or self.assignment is None):
            raise ValueError("parked episode states require parked_at and assignment")
        is_terminal = self.state in {ParkingState.ENDED, ParkingState.CANCELED}
        if is_terminal != (self.ended_at is not None):
            raise ValueError("terminal ParkingEpisode must have ended_at")
        if is_terminal != (self.termination_reason is not None):
            raise ValueError("terminal ParkingEpisode must have termination_reason")
        if self.state is ParkingState.MOVE_PENDING and self.movement_candidate_at is None:
            raise ValueError("MOVE_PENDING ParkingEpisode requires movement_candidate_at")


@dataclass(frozen=True, kw_only=True)
class ParkingTransition:
    """An immutable PARKED or UNPARKED publication projection."""

    transition_type: ParkingTransitionType
    parking_episode_id: ParkingEpisodeId
    physical_vehicle_id: PhysicalVehicleId
    parking_session_id: ParkingSessionId
    publication_revision: int
    occurred_at: datetime
    assignment: ParkingAssignment

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, "occurred_at")
        expected_revision = (
            1 if self.transition_type is ParkingTransitionType.PARKED else 2
        )
        if self.publication_revision != expected_revision:
            raise ValueError(
                "ParkingTransition revision must follow PARKED=1, UNPARKED=2"
            )


@dataclass(frozen=True, kw_only=True)
class BlockingRelation:
    """subject가 victim의 egress 영역을 막는 순서 있는 관계 snapshot."""

    blocking_relation_id: BlockingRelationId
    subject_physical_vehicle_id: PhysicalVehicleId
    victim_physical_vehicle_id: PhysicalVehicleId
    # 기존 durable/API 필드명을 보존하지만 ID namespace는
    # ZoneDefinition이 아닌 EgressAisleRegistry가 소유한다.
    egress_zone_id: EgressAisleId
    state: BlockingRelationState
    observation: ObservationStatus
    confirm_trusted_seconds: float
    clear_trusted_seconds: float
    confirm_duration_seconds: float
    clear_duration_seconds: float
    record_version: int
    created_at: datetime
    updated_at: datetime
    source_parking_episode_id: ParkingEpisodeId | None = None
    confirmed_at: datetime | None = None
    resolved_at: datetime | None = None
    terminated_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        if self.subject_physical_vehicle_id == self.victim_physical_vehicle_id:
            raise ValueError("blocking relation subject and victim must differ")
        for name in ("confirm_trusted_seconds", "clear_trusted_seconds"):
            require_non_negative(getattr(self, name), name)
        for name in ("confirm_duration_seconds", "clear_duration_seconds"):
            require_non_negative(getattr(self, name), name)
        require_positive(self.record_version, "record_version")
        for name in ("created_at", "updated_at", "confirmed_at", "resolved_at", "terminated_at"):
            require_aware(getattr(self, name), name)
        is_confirmed = self.state in {
            BlockingRelationState.BLOCKING,
            BlockingRelationState.CLEAR_PENDING,
            BlockingRelationState.RESOLVED,
        }
        if is_confirmed != (self.confirmed_at is not None):
            raise ValueError("confirmed blocking states require confirmed_at exclusively")
        is_terminal = self.state in {BlockingRelationState.RESOLVED, BlockingRelationState.CANCELED}
        if is_terminal != (self.terminated_at is not None):
            raise ValueError("terminal BlockingRelation must have terminated_at")
        if is_terminal != (self.termination_reason is not None):
            raise ValueError("terminal BlockingRelation must have termination_reason")
        if (self.state is BlockingRelationState.RESOLVED) != (self.resolved_at is not None):
            raise ValueError("only RESOLVED BlockingRelation has resolved_at")


@dataclass(frozen=True)
class IncidentKey:
    """규칙별 continuity scope와 rule code로 고정한 local composite key."""

    scope_type: IncidentKeyScope
    scope_id: UUID
    rule_code: str

    def __post_init__(self) -> None:
        if not self.rule_code:
            raise ValueError("rule_code must not be empty")
        if not isinstance(self.scope_id, UUID):
            raise TypeError("IncidentKey scope_id must be a UUID-based domain identifier")

    @classmethod
    def for_zone_visit(cls, zone_visit_id: ZoneVisitId, rule_code: str) -> "IncidentKey":
        return cls(IncidentKeyScope.ZONE_VISIT, zone_visit_id, rule_code)

    @classmethod
    def for_physical_vehicle(
        cls, physical_vehicle_id: PhysicalVehicleId, rule_code: str
    ) -> "IncidentKey":
        return cls(IncidentKeyScope.PHYSICAL_VEHICLE, physical_vehicle_id, rule_code)

    @classmethod
    def for_blocking_relation(
        cls, blocking_relation_id: BlockingRelationId, rule_code: str
    ) -> "IncidentKey":
        return cls(IncidentKeyScope.BLOCKING_RELATION, blocking_relation_id, rule_code)


@dataclass(frozen=True)
class IncidentSignal:
    """상태 없는 RuleEvaluator가 IncidentReducer에 전달하는 결과."""

    key: IncidentKey
    value: IncidentSignalValue
    confirmable: bool
    observed_at: datetime
    evidence: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.observed_at, "observed_at")
        if self.value is not IncidentSignalValue.MATCHED and self.confirmable:
            raise ValueError("confirmable applies only to MATCHED IncidentSignal")


@dataclass(frozen=True, kw_only=True)
class PlacementDiagnostic:
    """한 frame에서 실제 rule 입력으로 사용한 비영속 placement 진단값."""

    physical_vehicle_id: PhysicalVehicleId
    track_segment_id: TrackSegmentId
    source: PlacementEvidenceSource
    evidence: PlacementEvidence
    assignment: ParkingAssignment
    parking_state: ParkingState | None
    bad_parking_signal: IncidentSignal
    out_of_zone_signal: IncidentSignal

    def __post_init__(self) -> None:
        expected_key = self.physical_vehicle_id
        for signal, rule_code in (
            (self.bad_parking_signal, "BAD_PARKING"),
            (self.out_of_zone_signal, "OUT_OF_ZONE"),
        ):
            if (
                signal.key.scope_type is not IncidentKeyScope.PHYSICAL_VEHICLE
                or signal.key.scope_id != expected_key
                or signal.key.rule_code != rule_code
            ):
                raise ValueError(
                    "placement diagnostic signals must match vehicle and rule"
                )


@dataclass(frozen=True, kw_only=True)
class Incident:
    """같은 IncidentKey를 Candidate부터 terminal까지 유지하는 aggregate."""

    incident_id: IncidentId
    key: IncidentKey
    physical_vehicle_id: PhysicalVehicleId
    state: IncidentState
    observation: ObservationStatus
    confirm_trusted_seconds: float
    clear_trusted_seconds: float
    confirm_duration_seconds: float
    clear_duration_seconds: float
    record_version: int
    publication_revision: int
    first_observed_at: datetime
    created_at: datetime
    updated_at: datetime
    trusted_sample_max_gap_seconds: float
    entry_attempt_id: EntryAttemptId | None = None
    parking_session_id: ParkingSessionId | None = None
    zone_id: ZoneId | None = None
    victim_physical_vehicle_id: PhysicalVehicleId | None = None
    confirmed_at: datetime | None = None
    resolved_at: datetime | None = None
    terminated_at: datetime | None = None
    termination_reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("confirm_trusted_seconds", "clear_trusted_seconds", "publication_revision"):
            require_non_negative(getattr(self, name), name)
        for name in ("confirm_duration_seconds", "clear_duration_seconds"):
            require_non_negative(getattr(self, name), name)
        require_positive(
            self.trusted_sample_max_gap_seconds,
            "trusted_sample_max_gap_seconds",
        )
        if round(self.trusted_sample_max_gap_seconds * 1_000_000) <= 0:
            raise ValueError(
                "trusted_sample_max_gap_seconds must be at least one microsecond"
            )
        require_positive(self.record_version, "record_version")
        for name in (
            "first_observed_at",
            "created_at",
            "updated_at",
            "confirmed_at",
            "resolved_at",
            "terminated_at",
        ):
            require_aware(getattr(self, name), name)

        was_opened = self.state in {
            IncidentState.OPEN,
            IncidentState.CLEAR_PENDING,
            IncidentState.RESOLVED,
        }
        if was_opened != (self.confirmed_at is not None):
            raise ValueError("opened Incident states require confirmed_at")
        if self.state in {IncidentState.CANDIDATE, IncidentState.CANCELED}:
            if self.publication_revision != 0:
                raise ValueError("Candidate and Canceled Incident are never published")
        if self.publication_revision > 0 and (
            self.entry_attempt_id is None and self.parking_session_id is None
        ):
            raise ValueError("published Incident requires entryAttempt or session correlation")
        is_terminal = self.state in {IncidentState.RESOLVED, IncidentState.CANCELED}
        if is_terminal != (self.terminated_at is not None):
            raise ValueError("terminal Incident must have terminated_at")
        if is_terminal != (self.termination_reason is not None):
            raise ValueError("terminal Incident must have termination_reason")
        if (self.state is IncidentState.RESOLVED) != (self.resolved_at is not None):
            raise ValueError("only RESOLVED Incident has resolved_at")


@dataclass(frozen=True)
class IncidentTransition:
    """Incident aggregate와 함께 원자적으로 outbox에 기록할 공개 전이."""

    transition_type: IncidentTransitionType
    incident: Incident

    def __post_init__(self) -> None:
        expected_state = (
            IncidentState.OPEN
            if self.transition_type is IncidentTransitionType.OPEN
            else IncidentState.RESOLVED
        )
        if self.incident.state is not expected_state:
            raise ValueError("IncidentTransition type must match the aggregate state")
        if self.incident.publication_revision < 1:
            raise ValueError("IncidentTransition requires a materialized publication revision")


@dataclass(frozen=True)
class IncidentReduction:
    """Incident의 durable update와 0개 이상의 외부 publication을 함께 반환한다.

    Candidate 누적, CLEAR_PENDING, UNKNOWN pause처럼 외부 전이가 없는 변경도
    저장 경계에서 잃지 않도록 aggregate snapshot을 항상 포함한다. 늦은
    correlation과 현재 신호가 같은 cycle에 오면 OPEN과 RESOLVE를 revision
    순서대로 함께 반환할 수 있다.
    """

    incident: Incident
    transitions: tuple[IncidentTransition, ...] = ()

    def __post_init__(self) -> None:
        revisions = [item.incident.publication_revision for item in self.transitions]
        if revisions != sorted(set(revisions)):
            raise ValueError("IncidentReduction transitions must have unique revision order")
        if any(
            item.incident.incident_id != self.incident.incident_id
            or item.incident.publication_revision > self.incident.publication_revision
            for item in self.transitions
        ):
            raise ValueError(
                "IncidentReduction transitions must belong to the updated Incident"
            )


@dataclass(frozen=True)
class ParkingPipelineResult:
    """한 frame Unit of Work가 영속 snapshot·publication으로 반영할 결과."""

    zone_visit_updates: tuple[ZoneVisit, ...]
    parking_episode_updates: tuple[ParkingEpisode, ...]
    incident_transitions: tuple[IncidentTransition, ...]
    parking_transitions: tuple[ParkingTransition, ...] = ()
    blocking_relation_updates: tuple[BlockingRelation, ...] = ()
    incident_updates: tuple[Incident, ...] = ()
    placement_diagnostics: tuple[PlacementDiagnostic, ...] = ()

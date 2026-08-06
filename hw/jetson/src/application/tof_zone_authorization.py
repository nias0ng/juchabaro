"""ToF 점유와 durable 차량 문맥으로 전용구역 차량 자격을 평가한다.

이 모듈은 한 snapshot을 한 번 평가하는 stateless application 경계다.
후보 선택 정책, 결과 revision 부여, publication, runtime callback 및 상태
저장은 소유하지 않는다. freshness 정책값은 현장 측정 뒤 재조정해야 하는
잠정 운영값이며 이 모듈은 기본값을 제공하지 않는다.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import math
from numbers import Real
import sqlite3
from typing import Iterator, Protocol

from src.application.sensor_occupancy import OccupancyState, ZoneOccupancySnapshot
from src.domain.models import ObservationState, ObservationStatus, require_aware
from src.parking.models import (
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.rules.restricted_zone import qualification_for_zone
from src.parking.zone_registry import ZoneRegistry
from src.session.models import (
    ContextBinding,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
)
from src.storage.aggregate_repositories import ZoneVisitRepository
from src.storage.repositories import (
    ContextBindingRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


class TofAuthorizationDecision(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    UNAUTHORIZED = "UNAUTHORIZED"
    UNKNOWN = "UNKNOWN"


class TofAuthorizationReason(str, Enum):
    ZONE_DEFINITION_UNAVAILABLE = "ZONE_DEFINITION_UNAVAILABLE"
    ZONE_VACANT = "ZONE_VACANT"
    OCCUPANCY_NOT_CONFIRMED = "OCCUPANCY_NOT_CONFIRMED"

    SENSOR_RUNTIME_UNAVAILABLE = "SENSOR_RUNTIME_UNAVAILABLE"
    SENSOR_OBSERVATION_UNRELIABLE = "SENSOR_OBSERVATION_UNRELIABLE"
    SENSOR_OBSERVATION_STALE = "SENSOR_OBSERVATION_STALE"

    VEHICLE_NOT_IDENTIFIED = "VEHICLE_NOT_IDENTIFIED"
    MULTIPLE_VEHICLE_CANDIDATES = "MULTIPLE_VEHICLE_CANDIDATES"
    ZONE_VISIT_NOT_CONFIRMED = "ZONE_VISIT_NOT_CONFIRMED"
    ZONE_VISIT_OBSERVATION_UNRELIABLE = "ZONE_VISIT_OBSERVATION_UNRELIABLE"
    ZONE_VISIT_OBSERVATION_STALE = "ZONE_VISIT_OBSERVATION_STALE"

    VEHICLE_STATE_UNAVAILABLE = "VEHICLE_STATE_UNAVAILABLE"
    VEHICLE_NOT_ACTIVE = "VEHICLE_NOT_ACTIVE"
    VEHICLE_OBSERVATION_UNRELIABLE = "VEHICLE_OBSERVATION_UNRELIABLE"
    VEHICLE_OBSERVATION_STALE = "VEHICLE_OBSERVATION_STALE"

    TEMPORAL_MISMATCH = "TEMPORAL_MISMATCH"
    CONTEXT_BINDING_UNAVAILABLE = "CONTEXT_BINDING_UNAVAILABLE"
    SESSION_MIRROR_UNAVAILABLE = "SESSION_MIRROR_UNAVAILABLE"
    SESSION_CLOSED = "SESSION_CLOSED"
    SESSION_PRESENCE_UNAVAILABLE = "SESSION_PRESENCE_UNAVAILABLE"
    SESSION_STATE_INCONSISTENT = "SESSION_STATE_INCONSISTENT"
    QUALIFICATION_UNAVAILABLE = "QUALIFICATION_UNAVAILABLE"


def _require_revision(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name}은 0 이상의 정수여야 합니다.")


def _finite_seconds(
    value: object,
    *,
    field_name: str,
    positive: bool,
) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{field_name}는 bool이 아닌 유한한 숫자여야 합니다.")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name}는 bool이 아닌 유한한 숫자여야 합니다.")
    if positive and normalized <= 0.0:
        raise ValueError(f"{field_name}는 0보다 커야 합니다.")
    if not positive and normalized < 0.0:
        raise ValueError(f"{field_name}는 0 이상이어야 합니다.")
    return normalized


@dataclass(frozen=True, kw_only=True)
class TofZoneAuthorizationAssessment:
    """한 ToF 점유 snapshot에 대한 비영속 전용구역 권한 평가 결과."""

    sensor_id: str
    zone_id: ZoneId
    zone_type: ZoneType | None

    occupancy_state: OccupancyState
    occupancy_revision: int
    occupancy_stable_since: datetime | None
    occupancy_observation: ObservationStatus

    zone_visit_id: ZoneVisitId | None
    physical_vehicle_id: PhysicalVehicleId | None
    parking_session_id: ParkingSessionId | None
    context_revision: int | None

    decision: TofAuthorizationDecision | None
    reason: TofAuthorizationReason | None

    evaluated_at: datetime
    assessment_revision: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.sensor_id, str) or not self.sensor_id.strip():
            raise ValueError("sensor_id는 공백이 아닌 문자열이어야 합니다.")
        if (
            isinstance(self.zone_id, bool)
            or not isinstance(self.zone_id, int)
            or self.zone_id <= 0
        ):
            raise ValueError("zone_id는 양의 정수여야 합니다.")
        if not isinstance(self.occupancy_observation, ObservationStatus):
            raise ValueError("occupancy_observation은 ObservationStatus여야 합니다.")

        _require_revision(self.occupancy_revision, "occupancy_revision")
        _require_revision(self.assessment_revision, "assessment_revision")
        if self.context_revision is not None:
            _require_revision(self.context_revision, "context_revision")
        require_aware(self.occupancy_stable_since, "occupancy_stable_since")
        require_aware(self.evaluated_at, "evaluated_at")

        if self.decision in {
            TofAuthorizationDecision.AUTHORIZED,
            TofAuthorizationDecision.UNAUTHORIZED,
        }:
            if self.occupancy_state is not OccupancyState.OCCUPIED:
                raise ValueError("확정 권한 판정에는 OCCUPIED 상태가 필요합니다.")
            if self.zone_type not in {
                ZoneType.DISABLED,
                ZoneType.EV_CHARGING,
            }:
                raise ValueError("확정 권한 판정에는 전용구역 종류가 필요합니다.")
            if any(
                value is None
                for value in (
                    self.zone_visit_id,
                    self.physical_vehicle_id,
                    self.parking_session_id,
                    self.context_revision,
                )
            ):
                raise ValueError(
                    "확정 권한 판정에는 차량과 session identity가 필요합니다."
                )
            if self.reason is not None:
                raise ValueError("확정 권한 판정에는 reason을 둘 수 없습니다.")
        elif self.decision is TofAuthorizationDecision.UNKNOWN:
            if self.occupancy_state is not OccupancyState.OCCUPIED:
                raise ValueError("UNKNOWN 권한 판정에는 OCCUPIED 상태가 필요합니다.")
            if self.reason is None:
                raise ValueError("UNKNOWN 권한 판정에는 reason이 필요합니다.")
        elif self.decision is None:
            if self.reason is None:
                raise ValueError("미적용 권한 판정에는 reason이 필요합니다.")
        else:
            raise ValueError("지원하지 않는 권한 판정 값입니다.")


@dataclass(frozen=True, kw_only=True)
class TofAuthorizationPolicy:
    """ToF와 camera 관측의 잠정 freshness 정책."""

    occupancy_freshness_seconds: float
    monitoring_freshness_seconds: float
    max_pre_occupancy_observation_seconds: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "occupancy_freshness_seconds",
            _finite_seconds(
                self.occupancy_freshness_seconds,
                field_name="occupancy_freshness_seconds",
                positive=True,
            ),
        )
        object.__setattr__(
            self,
            "monitoring_freshness_seconds",
            _finite_seconds(
                self.monitoring_freshness_seconds,
                field_name="monitoring_freshness_seconds",
                positive=True,
            ),
        )
        object.__setattr__(
            self,
            "max_pre_occupancy_observation_seconds",
            _finite_seconds(
                self.max_pre_occupancy_observation_seconds,
                field_name="max_pre_occupancy_observation_seconds",
                positive=False,
            ),
        )


@dataclass(frozen=True, kw_only=True)
class TofZoneVehicleCandidate:
    visit: ZoneVisit
    vehicle: PhysicalVehicle | None
    binding: ContextBinding | None
    session_mirror: ParkingSessionMirror | None


class TofZoneAuthorizationQuery(Protocol):
    def load_candidates(
        self,
        zone_id: ZoneId,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[TofZoneVehicleCandidate, ...]:
        ...


@contextmanager
def _read_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    owns_transaction = not connection.in_transaction
    if owns_transaction:
        connection.execute("BEGIN")
    try:
        yield
    except BaseException:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise
    else:
        if not owns_transaction:
            return
        try:
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise


class RepositoryTofZoneAuthorizationQuery:
    """관련 repository를 하나의 짧은 SQLite read snapshot에서 조합한다."""

    def load_candidates(
        self,
        zone_id: ZoneId,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[TofZoneVehicleCandidate, ...]:
        with _read_transaction(connection):
            visits = ZoneVisitRepository(connection).list_active_by_zone(zone_id)
            vehicle_repository = PhysicalVehicleRepository(connection)
            binding_repository = ContextBindingRepository(connection)
            mirror_repository = ParkingSessionMirrorRepository(connection)
            candidates: list[TofZoneVehicleCandidate] = []

            for visit in visits:
                vehicle = vehicle_repository.get(visit.physical_vehicle_id)
                binding = binding_repository.get_active_by_physical_vehicle_id(
                    visit.physical_vehicle_id
                )
                if binding is None:
                    mirror = (
                        mirror_repository.get_exit_enabled_by_physical_vehicle_id(
                            visit.physical_vehicle_id
                        )
                    )
                else:
                    mirror = mirror_repository.get(binding.parking_session_id)

                candidates.append(
                    TofZoneVehicleCandidate(
                        visit=visit,
                        vehicle=vehicle,
                        binding=binding,
                        session_mirror=mirror,
                    )
                )

            return tuple(candidates)


def _freshness_reason(
    observation: ObservationStatus,
    *,
    evaluated_at: datetime,
    freshness_seconds: float,
    stale_reason: TofAuthorizationReason,
) -> TofAuthorizationReason | None:
    observed_at = observation.last_reliable_observed_at
    if observed_at is None:
        return stale_reason
    if observed_at > evaluated_at:
        return TofAuthorizationReason.TEMPORAL_MISMATCH
    if (evaluated_at - observed_at).total_seconds() > freshness_seconds:
        return stale_reason
    return None


class TofZoneAuthorizationService:
    """한 ToF 점유 snapshot을 현재 durable 차량 권한으로 평가한다."""

    def __init__(
        self,
        *,
        zones: ZoneRegistry,
        policy: TofAuthorizationPolicy,
        query: TofZoneAuthorizationQuery,
    ) -> None:
        self._zones = zones
        self._policy = policy
        self._query = query

    def assess(
        self,
        snapshot: ZoneOccupancySnapshot,
        *,
        sensor_runtime_available: bool,
        evaluated_at: datetime,
        connection: sqlite3.Connection,
    ) -> TofZoneAuthorizationAssessment:
        if not isinstance(snapshot, ZoneOccupancySnapshot):
            raise ValueError("snapshot은 ZoneOccupancySnapshot이어야 합니다.")
        if not isinstance(sensor_runtime_available, bool):
            raise ValueError("sensor_runtime_available은 bool이어야 합니다.")
        require_aware(evaluated_at, "evaluated_at")

        zone = self._zones.get_or_none(snapshot.zone_id)
        if zone is None:
            return self._assessment(
                snapshot,
                zone_type=None,
                decision=None,
                reason=TofAuthorizationReason.ZONE_DEFINITION_UNAVAILABLE,
                evaluated_at=evaluated_at,
            )
        if zone.zone_type not in {ZoneType.DISABLED, ZoneType.EV_CHARGING}:
            raise ValueError(
                "ToF 권한 판정을 지원하지 않는 zone type입니다: "
                f"{zone.zone_type.value}"
            )

        if snapshot.stable_state is OccupancyState.UNKNOWN:
            return self._assessment(
                snapshot,
                zone_type=zone.zone_type,
                decision=None,
                reason=TofAuthorizationReason.OCCUPANCY_NOT_CONFIRMED,
                evaluated_at=evaluated_at,
            )

        sensor_reason = self._sensor_reason(
            snapshot,
            sensor_runtime_available=sensor_runtime_available,
            evaluated_at=evaluated_at,
        )
        if sensor_reason is not None:
            return self._assessment(
                snapshot,
                zone_type=zone.zone_type,
                decision=(
                    TofAuthorizationDecision.UNKNOWN
                    if snapshot.stable_state is OccupancyState.OCCUPIED
                    else None
                ),
                reason=sensor_reason,
                evaluated_at=evaluated_at,
            )

        if snapshot.stable_state is OccupancyState.VACANT:
            return self._assessment(
                snapshot,
                zone_type=zone.zone_type,
                decision=None,
                reason=TofAuthorizationReason.ZONE_VACANT,
                evaluated_at=evaluated_at,
            )

        candidates = self._query.load_candidates(
            snapshot.zone_id,
            connection=connection,
        )
        if not candidates:
            return self._assessment(
                snapshot,
                zone_type=zone.zone_type,
                decision=TofAuthorizationDecision.UNKNOWN,
                reason=TofAuthorizationReason.VEHICLE_NOT_IDENTIFIED,
                evaluated_at=evaluated_at,
            )
        if len(candidates) > 1:
            return self._assessment(
                snapshot,
                zone_type=zone.zone_type,
                decision=TofAuthorizationDecision.UNKNOWN,
                reason=TofAuthorizationReason.MULTIPLE_VEHICLE_CANDIDATES,
                evaluated_at=evaluated_at,
            )

        candidate = candidates[0]
        visit = candidate.visit
        if visit.state is not ZoneVisitState.INSIDE:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.ZONE_VISIT_NOT_CONFIRMED,
                evaluated_at,
            )
        if visit.observation.state is not ObservationState.OBSERVED:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.ZONE_VISIT_OBSERVATION_UNRELIABLE,
                evaluated_at,
            )
        visit_freshness = _freshness_reason(
            visit.observation,
            evaluated_at=evaluated_at,
            freshness_seconds=self._policy.monitoring_freshness_seconds,
            stale_reason=TofAuthorizationReason.ZONE_VISIT_OBSERVATION_STALE,
        )
        if visit_freshness is not None:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                visit_freshness,
                evaluated_at,
            )

        vehicle = candidate.vehicle
        if vehicle is None:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.VEHICLE_STATE_UNAVAILABLE,
                evaluated_at,
            )
        if vehicle.state is not PhysicalVehicleState.ACTIVE:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.VEHICLE_NOT_ACTIVE,
                evaluated_at,
            )
        if vehicle.observation.state is not ObservationState.OBSERVED:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.VEHICLE_OBSERVATION_UNRELIABLE,
                evaluated_at,
            )
        vehicle_freshness = _freshness_reason(
            vehicle.observation,
            evaluated_at=evaluated_at,
            freshness_seconds=self._policy.monitoring_freshness_seconds,
            stale_reason=TofAuthorizationReason.VEHICLE_OBSERVATION_STALE,
        )
        if vehicle_freshness is not None:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                vehicle_freshness,
                evaluated_at,
            )

        stable_since = snapshot.stable_since
        visit_observed_at = visit.observation.last_reliable_observed_at
        vehicle_observed_at = vehicle.observation.last_reliable_observed_at
        assert stable_since is not None
        assert visit_observed_at is not None
        assert vehicle_observed_at is not None
        oldest_allowed = stable_since - timedelta(
            seconds=self._policy.max_pre_occupancy_observation_seconds
        )
        if (
            visit_observed_at < oldest_allowed
            or vehicle_observed_at < oldest_allowed
        ):
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.TEMPORAL_MISMATCH,
                evaluated_at,
            )

        binding = candidate.binding
        mirror = candidate.session_mirror
        if binding is None:
            reason = (
                TofAuthorizationReason.SESSION_CLOSED
                if mirror is not None
                and mirror.administrative_state is SessionAdministrativeState.CLOSED
                else TofAuthorizationReason.CONTEXT_BINDING_UNAVAILABLE
            )
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                reason,
                evaluated_at,
            )
        if mirror is None:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.SESSION_MIRROR_UNAVAILABLE,
                evaluated_at,
            )
        if mirror.administrative_state is SessionAdministrativeState.CLOSED:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.SESSION_CLOSED,
                evaluated_at,
            )
        if mirror.physical_presence_state is not PhysicalPresenceState.INSIDE:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.SESSION_PRESENCE_UNAVAILABLE,
                evaluated_at,
            )
        if (
            vehicle.physical_vehicle_id != visit.physical_vehicle_id
            or binding.physical_vehicle_id != visit.physical_vehicle_id
            or mirror.physical_vehicle_id != visit.physical_vehicle_id
            or mirror.parking_session_id != binding.parking_session_id
            or mirror.entry_attempt_id != binding.entry_attempt_id
            or mirror.context_revision != binding.context_revision
            or mirror.last_context != binding.context
        ):
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.SESSION_STATE_INCONSISTENT,
                evaluated_at,
            )

        qualified = qualification_for_zone(zone.zone_type, binding.context)
        if qualified is None:
            return self._unknown(
                snapshot,
                zone.zone_type,
                candidate,
                TofAuthorizationReason.QUALIFICATION_UNAVAILABLE,
                evaluated_at,
            )
        return self._assessment(
            snapshot,
            zone_type=zone.zone_type,
            candidate=candidate,
            decision=(
                TofAuthorizationDecision.AUTHORIZED
                if qualified
                else TofAuthorizationDecision.UNAUTHORIZED
            ),
            reason=None,
            evaluated_at=evaluated_at,
        )

    def _sensor_reason(
        self,
        snapshot: ZoneOccupancySnapshot,
        *,
        sensor_runtime_available: bool,
        evaluated_at: datetime,
    ) -> TofAuthorizationReason | None:
        if not sensor_runtime_available:
            return TofAuthorizationReason.SENSOR_RUNTIME_UNAVAILABLE
        if snapshot.observation.state is not ObservationState.OBSERVED:
            return TofAuthorizationReason.SENSOR_OBSERVATION_UNRELIABLE
        freshness = _freshness_reason(
            snapshot.observation,
            evaluated_at=evaluated_at,
            freshness_seconds=self._policy.occupancy_freshness_seconds,
            stale_reason=TofAuthorizationReason.SENSOR_OBSERVATION_STALE,
        )
        if freshness is not None:
            return freshness
        if snapshot.stable_since is not None and snapshot.stable_since > evaluated_at:
            return TofAuthorizationReason.TEMPORAL_MISMATCH
        return None

    def _unknown(
        self,
        snapshot: ZoneOccupancySnapshot,
        zone_type: ZoneType,
        candidate: TofZoneVehicleCandidate,
        reason: TofAuthorizationReason,
        evaluated_at: datetime,
    ) -> TofZoneAuthorizationAssessment:
        return self._assessment(
            snapshot,
            zone_type=zone_type,
            candidate=candidate,
            decision=TofAuthorizationDecision.UNKNOWN,
            reason=reason,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _assessment(
        snapshot: ZoneOccupancySnapshot,
        *,
        zone_type: ZoneType | None,
        decision: TofAuthorizationDecision | None,
        reason: TofAuthorizationReason | None,
        evaluated_at: datetime,
        candidate: TofZoneVehicleCandidate | None = None,
    ) -> TofZoneAuthorizationAssessment:
        binding = candidate.binding if candidate is not None else None
        mirror = candidate.session_mirror if candidate is not None else None
        parking_session_id = (
            binding.parking_session_id
            if binding is not None
            else mirror.parking_session_id
            if mirror is not None
            else None
        )
        return TofZoneAuthorizationAssessment(
            sensor_id=snapshot.sensor_id,
            zone_id=snapshot.zone_id,
            zone_type=zone_type,
            occupancy_state=snapshot.stable_state,
            occupancy_revision=snapshot.revision,
            occupancy_stable_since=snapshot.stable_since,
            occupancy_observation=snapshot.observation,
            zone_visit_id=(
                candidate.visit.visit_id if candidate is not None else None
            ),
            physical_vehicle_id=(
                candidate.visit.physical_vehicle_id
                if candidate is not None
                else None
            ),
            parking_session_id=parking_session_id,
            context_revision=(
                binding.context_revision if binding is not None else None
            ),
            decision=decision,
            reason=reason,
            evaluated_at=evaluated_at,
            assessment_revision=0,
        )

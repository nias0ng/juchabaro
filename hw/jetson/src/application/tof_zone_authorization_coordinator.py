"""ToF 전용구역 권한 재평가와 process-local 최신 결과를 조정한다.

이 모듈은 재평가 요청 병합, zone별 평가 직렬화, assessment revision 부여,
의미가 같은 결과의 publication 억제와 명시적 retry 결과 생성을 담당한다.
retry timer, polling loop, Incident 처리와 결과의 durable 저장은 담당하지
않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import sqlite3
from threading import Lock
from typing import Callable

from src.application.sensor_occupancy import (
    OccupancyState,
    OccupancyTransition,
    ZoneOccupancySnapshot,
)
from src.application.tof_zone_authorization import (
    TofAuthorizationDecision,
    TofAuthorizationReason,
    TofZoneAuthorizationAssessment,
    TofZoneAuthorizationService,
)
from src.domain.models import ObservationReason, ObservationState
from src.parking.models import ZoneId, ZoneType
from src.parking.models import ZoneVisitId
from src.tracking.models import ParkingSessionId, PhysicalVehicleId


OccupancySnapshotSupplier = Callable[
    [],
    tuple[ZoneOccupancySnapshot, ...],
]
SensorRuntimeAvailabilitySupplier = Callable[[], bool]
ConnectionFactory = Callable[[], sqlite3.Connection]
AuthorizationClock = Callable[[], datetime]
AuthorizationAssessmentConsumer = Callable[
    [TofZoneAuthorizationAssessment],
    None,
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_zone_id(zone_id: object) -> None:
    if (
        isinstance(zone_id, bool)
        or not isinstance(zone_id, int)
        or zone_id <= 0
    ):
        raise ValueError("zone_id는 양의 정수여야 합니다.")


def _validate_revision(
    revision: object,
    *,
    field_name: str,
    allow_none: bool,
) -> None:
    if revision is None and allow_none:
        return
    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
    ):
        raise ValueError(f"{field_name}은 0 이상의 정수여야 합니다.")


class TofAuthorizationCoordinatorStage(str, Enum):
    SNAPSHOT = "SNAPSHOT"
    EVALUATION = "EVALUATION"
    PUBLICATION = "PUBLICATION"


@dataclass(frozen=True, kw_only=True)
class TofAuthorizationCoordinatorFailure:
    zone_id: ZoneId
    stage: TofAuthorizationCoordinatorStage
    error: Exception


@dataclass(frozen=True, kw_only=True)
class TofAuthorizationRetryRequest:
    """Worker가 이후 재평가해야 하는 zone 요청."""

    zone_id: ZoneId
    minimum_occupancy_revision: int | None

    def __post_init__(self) -> None:
        _validate_zone_id(self.zone_id)
        _validate_revision(
            self.minimum_occupancy_revision,
            field_name="minimum_occupancy_revision",
            allow_none=True,
        )


@dataclass(frozen=True, kw_only=True)
class TofAuthorizationCoordinatorRun:
    published_assessments: tuple[TofZoneAuthorizationAssessment, ...]
    unchanged_zone_ids: tuple[ZoneId, ...]
    deferred_zone_ids: tuple[ZoneId, ...]
    failures: tuple[TofAuthorizationCoordinatorFailure, ...]
    retry_requests: tuple[TofAuthorizationRetryRequest, ...] = ()


@dataclass(frozen=True)
class _CausalScope:
    sensor_id: str
    zone_id: ZoneId
    stable_state: OccupancyState
    stable_since: datetime | None
    observation_state: ObservationState
    observation_reason: ObservationReason | None


@dataclass(frozen=True)
class _SemanticFingerprint:
    sensor_id: str
    zone_id: ZoneId
    zone_type: ZoneType | None
    occupancy_state: OccupancyState
    occupancy_stable_since: datetime | None
    occupancy_observation_state: ObservationState
    occupancy_observation_reason: ObservationReason | None
    zone_visit_id: ZoneVisitId | None
    physical_vehicle_id: PhysicalVehicleId | None
    parking_session_id: ParkingSessionId | None
    context_revision: int | None
    decision: TofAuthorizationDecision | None
    reason: TofAuthorizationReason | None


@dataclass(frozen=True)
class _ZoneOutcome:
    published: TofZoneAuthorizationAssessment | None = None
    unchanged: bool = False
    deferred: bool = False
    failure: TofAuthorizationCoordinatorFailure | None = None
    retry_request: TofAuthorizationRetryRequest | None = None


def _causal_scope(snapshot: ZoneOccupancySnapshot) -> _CausalScope:
    return _CausalScope(
        sensor_id=snapshot.sensor_id,
        zone_id=snapshot.zone_id,
        stable_state=snapshot.stable_state,
        stable_since=snapshot.stable_since,
        observation_state=snapshot.observation.state,
        observation_reason=snapshot.observation.reason,
    )


def _semantic_fingerprint(
    assessment: TofZoneAuthorizationAssessment,
) -> _SemanticFingerprint:
    return _SemanticFingerprint(
        sensor_id=assessment.sensor_id,
        zone_id=assessment.zone_id,
        zone_type=assessment.zone_type,
        occupancy_state=assessment.occupancy_state,
        occupancy_stable_since=assessment.occupancy_stable_since,
        occupancy_observation_state=assessment.occupancy_observation.state,
        occupancy_observation_reason=assessment.occupancy_observation.reason,
        zone_visit_id=assessment.zone_visit_id,
        physical_vehicle_id=assessment.physical_vehicle_id,
        parking_session_id=assessment.parking_session_id,
        context_revision=assessment.context_revision,
        decision=assessment.decision,
        reason=assessment.reason,
    )


def _merge_revision(
    current: int | None,
    incoming: int | None,
) -> int | None:
    if current is None:
        return incoming
    if incoming is None:
        return current
    return max(current, incoming)


class TofZoneAuthorizationCoordinator:
    """ToF 권한 재평가 요청과 최신 process-local assessment를 관리한다.

    요청 메서드는 DB 조회나 권한 평가를 수행하지 않고 pending 상태만
    갱신한다. `drain_pending()`은 호출 시작 시점의 요청만 zone ID
    순서로 처리하며, 같은 zone의 평가는 동시에 실행되지 않는다.

    `assessment_consumer`는 이 coordinator의 request 메서드를 호출할 수
    있다. 그러나 consumer는 `drain_pending()` 또는
    `reevaluate_after_monitoring_commit()`을 동기적으로 재호출해서는 안
    된다. consumer는 zone 평가 lock 안에서 호출되므로 동기 재진입은
    교착을 일으킬 수 있다.
    """

    def __init__(
        self,
        *,
        authorization_service: TofZoneAuthorizationService,
        occupancy_snapshots: OccupancySnapshotSupplier,
        sensor_runtime_available: SensorRuntimeAvailabilitySupplier,
        connection_factory: ConnectionFactory,
        assessment_consumer: AuthorizationAssessmentConsumer | None = None,
        clock: AuthorizationClock = _utc_now,
    ) -> None:
        for dependency, name in (
            (occupancy_snapshots, "occupancy_snapshots"),
            (sensor_runtime_available, "sensor_runtime_available"),
            (connection_factory, "connection_factory"),
            (clock, "clock"),
        ):
            if not callable(dependency):
                raise ValueError(f"{name}은 callable이어야 합니다.")
        if assessment_consumer is not None and not callable(
            assessment_consumer
        ):
            raise ValueError("assessment_consumer는 callable이어야 합니다.")

        self._authorization_service = authorization_service
        self._occupancy_snapshots = occupancy_snapshots
        self._sensor_runtime_available = sensor_runtime_available
        self._connection_factory = connection_factory
        self._assessment_consumer = assessment_consumer
        self._clock = clock

        self._state_lock = Lock()
        self._zone_locks: dict[ZoneId, Lock] = {}

        self._pending_revisions: dict[ZoneId, int | None] = {}
        self._latest_assessments: dict[
            ZoneId,
            TofZoneAuthorizationAssessment,
        ] = {}
        self._pending_publications: dict[
            ZoneId,
            TofZoneAuthorizationAssessment,
        ] = {}
        self._last_issued_revisions: dict[ZoneId, int] = {}

    def request_transitions(
        self,
        transitions: tuple[OccupancyTransition, ...],
    ) -> None:
        """stable occupancy transition을 가벼운 재평가 요청으로 등록한다."""

        if not isinstance(transitions, tuple):
            raise ValueError("transitions는 tuple이어야 합니다.")
        if any(
            not isinstance(transition, OccupancyTransition)
            for transition in transitions
        ):
            raise ValueError(
                "transitions의 모든 항목은 OccupancyTransition이어야 합니다."
            )

        self._merge_requests(
            tuple(
                (transition.zone_id, transition.revision)
                for transition in transitions
            )
        )

    def request_zone(
        self,
        zone_id: ZoneId,
        *,
        minimum_occupancy_revision: int | None = None,
    ) -> None:
        """특정 zone을 선택적인 최소 occupancy revision과 함께 등록한다."""

        _validate_zone_id(zone_id)
        _validate_revision(
            minimum_occupancy_revision,
            field_name="minimum_occupancy_revision",
            allow_none=True,
        )
        self._merge_requests(
            ((zone_id, minimum_occupancy_revision),)
        )

    def request_occupied_zones(self) -> None:
        """현재 snapshot 중 OCCUPIED zone만 pending에 추가한다."""

        self._merge_requests(self.occupied_zone_revisions())

    def zone_occupancy_revisions(
        self,
    ) -> tuple[tuple[ZoneId, int, OccupancyState], ...]:
        """모든 zone의 현재 occupancy revision과 stable state를 반환한다.

        Snapshot supplier를 한 번만 호출한다. DB를 조회하거나 coordinator
        pending 상태를 변경하지 않는다. 정상 sensor read failure는 snapshot
        observation 상태로 표현돼야 한다. supplier 예외나 malformed snapshot은
        이를 호출한 authorization worker의 terminal failure가 된다.
        """

        return tuple(
            sorted(
                (
                    (
                        snapshot.zone_id,
                        snapshot.revision,
                        snapshot.stable_state,
                    )
                    for snapshot in self._validated_snapshots()
                ),
                key=lambda item: item[0],
            )
        )

    def occupied_zone_revisions(
        self,
    ) -> tuple[tuple[ZoneId, int], ...]:
        """현재 OCCUPIED zone과 revision을 정렬해 반환한다."""

        return tuple(
            (zone_id, revision)
            for zone_id, revision, state
            in self.zone_occupancy_revisions()
            if state is OccupancyState.OCCUPIED
        )

    def request_all_snapshots(self) -> None:
        """현재 공급되는 모든 zone snapshot을 pending에 추가한다."""

        snapshots = self._validated_snapshots()
        self._merge_requests(
            tuple(
                (snapshot.zone_id, snapshot.revision)
                for snapshot in snapshots
            )
        )

    def reevaluate_after_monitoring_commit(
        self,
    ) -> TofAuthorizationCoordinatorRun:
        """현재 OCCUPIED zone을 monitoring commit 이후 한 번 재평가한다."""

        self.request_occupied_zones()
        return self.drain_pending()

    def drain_pending(self) -> TofAuthorizationCoordinatorRun:
        """호출 시작 시점의 pending batch를 zone ID 순서로 한 번 처리한다.

        처리 중 다른 thread가 등록한 요청은 다음 호출에서 처리한다. 실패와
        deferred 결과는 내부 재등록하지 않고 명시적인 retry request로 반환한다.
        한 zone의 실패는 다른 zone 처리를 중단시키지 않는다.

        `assessment_consumer`는 이 메서드나
        `reevaluate_after_monitoring_commit()`을 동기 재호출해서는 안 된다.
        """

        batch, zone_locks = self._take_pending_batch()

        published: list[TofZoneAuthorizationAssessment] = []
        unchanged: list[ZoneId] = []
        deferred: list[ZoneId] = []
        failures: list[TofAuthorizationCoordinatorFailure] = []
        retry_requests: list[TofAuthorizationRetryRequest] = []

        for zone_id in sorted(batch):
            with zone_locks[zone_id]:
                outcome = self._process_zone(
                    zone_id,
                    minimum_revision=batch[zone_id],
                )

            if outcome.published is not None:
                published.append(outcome.published)
            if outcome.unchanged:
                unchanged.append(zone_id)
            if outcome.deferred:
                deferred.append(zone_id)
            if outcome.failure is not None:
                failures.append(outcome.failure)
            if outcome.retry_request is not None:
                retry_requests.append(outcome.retry_request)

        return TofAuthorizationCoordinatorRun(
            published_assessments=tuple(published),
            unchanged_zone_ids=tuple(unchanged),
            deferred_zone_ids=tuple(deferred),
            failures=tuple(failures),
            retry_requests=tuple(retry_requests),
        )

    def latest_assessment(
        self,
        zone_id: ZoneId,
    ) -> TofZoneAuthorizationAssessment | None:
        """zone의 pending publication 또는 마지막 성공 결과를 반환한다."""

        _validate_zone_id(zone_id)
        with self._state_lock:
            pending = self._pending_publications.get(zone_id)
            if pending is not None:
                return pending
            return self._latest_assessments.get(zone_id)

    def assessments(self) -> tuple[TofZoneAuthorizationAssessment, ...]:
        """현재 알려진 zone별 최신 assessment를 zone ID 순서로 반환한다."""

        with self._state_lock:
            zone_ids = sorted(
                set(self._latest_assessments)
                | set(self._pending_publications)
            )
            assessments: list[TofZoneAuthorizationAssessment] = []
            for zone_id in zone_ids:
                pending = self._pending_publications.get(zone_id)
                if pending is not None:
                    assessments.append(pending)
                    continue

                latest = self._latest_assessments.get(zone_id)
                if latest is not None:
                    assessments.append(latest)

            return tuple(assessments)

    def _merge_requests(
        self,
        requests: tuple[tuple[ZoneId, int | None], ...],
    ) -> None:
        with self._state_lock:
            for zone_id, revision in requests:
                current = self._pending_revisions.get(zone_id)
                self._pending_revisions[zone_id] = _merge_revision(
                    current,
                    revision,
                )

    def _take_pending_batch(
        self,
    ) -> tuple[
        dict[ZoneId, int | None],
        dict[ZoneId, Lock],
    ]:
        with self._state_lock:
            batch = self._pending_revisions
            self._pending_revisions = {}

            zone_locks: dict[ZoneId, Lock] = {}
            for zone_id in batch:
                zone_lock = self._zone_locks.get(zone_id)
                if zone_lock is None:
                    zone_lock = Lock()
                    self._zone_locks[zone_id] = zone_lock
                zone_locks[zone_id] = zone_lock

            return batch, zone_locks

    def _process_zone(
        self,
        zone_id: ZoneId,
        *,
        minimum_revision: int | None,
    ) -> _ZoneOutcome:
        try:
            snapshot = self._snapshot_for_zone(
                zone_id,
                minimum_revision=minimum_revision,
            )
        except Exception as exc:
            return _ZoneOutcome(
                failure=TofAuthorizationCoordinatorFailure(
                    zone_id=zone_id,
                    stage=TofAuthorizationCoordinatorStage.SNAPSHOT,
                    error=exc,
                ),
                retry_request=TofAuthorizationRetryRequest(
                    zone_id=zone_id,
                    minimum_occupancy_revision=minimum_revision,
                ),
            )

        try:
            assessment = self._evaluate(snapshot)
        except Exception as exc:
            return _ZoneOutcome(
                failure=TofAuthorizationCoordinatorFailure(
                    zone_id=zone_id,
                    stage=TofAuthorizationCoordinatorStage.EVALUATION,
                    error=exc,
                ),
                retry_request=TofAuthorizationRetryRequest(
                    zone_id=zone_id,
                    minimum_occupancy_revision=minimum_revision,
                ),
            )

        try:
            current_snapshot = self._snapshot_for_zone(
                zone_id,
                minimum_revision=None,
            )
            if current_snapshot.revision < snapshot.revision:
                raise ValueError(
                    "평가 후 occupancy revision이 평가 입력보다 감소했습니다."
                )
        except Exception as exc:
            return _ZoneOutcome(
                failure=TofAuthorizationCoordinatorFailure(
                    zone_id=zone_id,
                    stage=TofAuthorizationCoordinatorStage.SNAPSHOT,
                    error=exc,
                ),
                retry_request=TofAuthorizationRetryRequest(
                    zone_id=zone_id,
                    minimum_occupancy_revision=minimum_revision,
                ),
            )

        if _causal_scope(current_snapshot) != _causal_scope(snapshot):
            return _ZoneOutcome(
                deferred=True,
                retry_request=TofAuthorizationRetryRequest(
                    zone_id=zone_id,
                    minimum_occupancy_revision=current_snapshot.revision,
                ),
            )

        return self._publish_or_suppress(
            assessment,
            minimum_revision=minimum_revision,
        )

    def _evaluate(
        self,
        snapshot: ZoneOccupancySnapshot,
    ) -> TofZoneAuthorizationAssessment:
        runtime_available = self._sensor_runtime_available()
        evaluated_at = self._clock()

        connection = self._connection_factory()
        try:
            return self._authorization_service.assess(
                snapshot,
                sensor_runtime_available=runtime_available,
                evaluated_at=evaluated_at,
                connection=connection,
            )
        finally:
            connection.close()

    def _publish_or_suppress(
        self,
        assessment: TofZoneAuthorizationAssessment,
        *,
        minimum_revision: int | None,
    ) -> _ZoneOutcome:
        zone_id = assessment.zone_id
        fingerprint = _semantic_fingerprint(assessment)

        with self._state_lock:
            pending = self._pending_publications.get(zone_id)
            latest = self._latest_assessments.get(zone_id)
            current = pending if pending is not None else latest

            if (
                current is not None
                and _semantic_fingerprint(current) == fingerprint
            ):
                if pending is not None:
                    publication = pending
                else:
                    refreshed = replace(
                        assessment,
                        assessment_revision=current.assessment_revision,
                    )
                    self._latest_assessments[zone_id] = refreshed
                    return _ZoneOutcome(unchanged=True)
            else:
                next_revision = (
                    self._last_issued_revisions.get(zone_id, 0) + 1
                )
                publication = replace(
                    assessment,
                    assessment_revision=next_revision,
                )
                self._last_issued_revisions[zone_id] = next_revision
                self._pending_publications[zone_id] = publication

        if self._assessment_consumer is None:
            self._complete_publication(publication)
            return _ZoneOutcome(published=publication)

        try:
            self._assessment_consumer(publication)
        except Exception as exc:
            return _ZoneOutcome(
                failure=TofAuthorizationCoordinatorFailure(
                    zone_id=zone_id,
                    stage=TofAuthorizationCoordinatorStage.PUBLICATION,
                    error=exc,
                ),
                retry_request=TofAuthorizationRetryRequest(
                    zone_id=zone_id,
                    minimum_occupancy_revision=minimum_revision,
                ),
            )

        self._complete_publication(publication)
        return _ZoneOutcome(published=publication)

    def _complete_publication(
        self,
        assessment: TofZoneAuthorizationAssessment,
    ) -> None:
        with self._state_lock:
            pending = self._pending_publications.get(
                assessment.zone_id
            )
            if pending != assessment:
                return

            self._latest_assessments[assessment.zone_id] = assessment
            del self._pending_publications[assessment.zone_id]

    def _snapshot_for_zone(
        self,
        zone_id: ZoneId,
        *,
        minimum_revision: int | None,
    ) -> ZoneOccupancySnapshot:
        snapshots = self._validated_snapshots()
        matches = tuple(
            snapshot
            for snapshot in snapshots
            if snapshot.zone_id == zone_id
        )

        if not matches:
            raise ValueError(
                f"zone_id에 대응하는 occupancy snapshot이 없습니다: {zone_id!r}"
            )
        if len(matches) > 1:
            raise ValueError(
                f"zone_id에 대응하는 occupancy snapshot이 중복됐습니다: "
                f"{zone_id!r}"
            )

        snapshot = matches[0]
        if (
            minimum_revision is not None
            and snapshot.revision < minimum_revision
        ):
            raise ValueError(
                "occupancy snapshot revision이 요청한 최소 revision보다 "
                "작습니다."
            )
        return snapshot

    def _validated_snapshots(
        self,
    ) -> tuple[ZoneOccupancySnapshot, ...]:
        snapshots = self._occupancy_snapshots()
        if not isinstance(snapshots, tuple):
            raise ValueError(
                "occupancy_snapshots는 snapshot tuple을 반환해야 합니다."
            )
        if any(
            not isinstance(snapshot, ZoneOccupancySnapshot)
            for snapshot in snapshots
        ):
            raise ValueError(
                "occupancy_snapshots의 모든 항목은 "
                "ZoneOccupancySnapshot이어야 합니다."
            )
        return snapshots

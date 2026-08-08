"""ToF 권한 coordinator의 재평가·동시성·멱등성 계약을 검증한다."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from uuid import UUID

import pytest

from src.actuators.models import ActuatorCommand
from src.application.local_warning_coordinator import (
    LocalWarningCoordinator,
    LocalWarningDeliveryError,
    LocalWarningZoneBinding,
)
from src.application.sensor_occupancy import (
    OccupancyState,
    OccupancyTransition,
    ZoneOccupancySnapshot,
)
from src.application.tof_zone_authorization import (
    TofAuthorizationDecision,
    TofAuthorizationReason,
    TofZoneAuthorizationAssessment,
)
from src.application.tof_zone_authorization_coordinator import (
    TofAuthorizationCoordinatorRun,
    TofAuthorizationCoordinatorStage,
    TofAuthorizationRetryRequest,
    TofZoneAuthorizationCoordinator,
)
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import ZoneId, ZoneType, ZoneVisitId
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicleId,
)


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)

ZONE_1 = ZoneId(1)
ZONE_2 = ZoneId(2)

VISIT_ID = ZoneVisitId(UUID(int=1))
VEHICLE_ID = PhysicalVehicleId(UUID(int=2))
SESSION_ID = ParkingSessionId(10)


def _observed(
    observed_at: datetime = NOW,
) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=observed_at,
    )


def _snapshot(
    zone_id: ZoneId,
    *,
    state: OccupancyState = OccupancyState.OCCUPIED,
    stable_since: datetime | None = None,
    revision: int = 1,
    observation: ObservationStatus | None = None,
) -> ZoneOccupancySnapshot:
    return ZoneOccupancySnapshot(
        sensor_id=f"tof-zone-{int(zone_id)}",
        zone_id=zone_id,
        stable_state=state,
        stable_since=(
            None
            if state is OccupancyState.UNKNOWN
            else stable_since or NOW - timedelta(seconds=1)
        ),
        candidate_target=None,
        candidate_started_at=None,
        candidate_elapsed_seconds=0.0,
        observation=observation or _observed(),
        last_distance_mm=100.0,
        last_input_at=NOW,
        last_failure=None,
        revision=revision,
    )


def _transition(
    zone_id: ZoneId,
    *,
    revision: int,
    current_state: OccupancyState = OccupancyState.OCCUPIED,
) -> OccupancyTransition:
    previous_state = (
        OccupancyState.VACANT
        if current_state is OccupancyState.OCCUPIED
        else OccupancyState.OCCUPIED
    )
    return OccupancyTransition(
        sensor_id=f"tof-zone-{int(zone_id)}",
        zone_id=zone_id,
        previous_state=previous_state,
        current_state=current_state,
        candidate_started_at=NOW - timedelta(seconds=1),
        confirmed_at=NOW,
        confirming_distance_mm=100.0,
        revision=revision,
    )


@dataclass(frozen=True)
class _AssessmentSpec:
    decision: TofAuthorizationDecision | None
    reason: TofAuthorizationReason | None
    context_revision: int | None = None


UNKNOWN_SPEC = _AssessmentSpec(
    decision=TofAuthorizationDecision.UNKNOWN,
    reason=TofAuthorizationReason.VEHICLE_NOT_IDENTIFIED,
)
AUTHORIZED_SPEC = _AssessmentSpec(
    decision=TofAuthorizationDecision.AUTHORIZED,
    reason=None,
    context_revision=1,
)
UNAUTHORIZED_SPEC = _AssessmentSpec(
    decision=TofAuthorizationDecision.UNAUTHORIZED,
    reason=None,
    context_revision=1,
)


def _assessment(
    snapshot: ZoneOccupancySnapshot,
    *,
    zone_type: ZoneType,
    evaluated_at: datetime,
    spec: _AssessmentSpec,
) -> TofZoneAuthorizationAssessment:
    confirmed = spec.decision in {
        TofAuthorizationDecision.AUTHORIZED,
        TofAuthorizationDecision.UNAUTHORIZED,
    }

    return TofZoneAuthorizationAssessment(
        sensor_id=snapshot.sensor_id,
        zone_id=snapshot.zone_id,
        zone_type=zone_type,
        occupancy_state=snapshot.stable_state,
        occupancy_revision=snapshot.revision,
        occupancy_stable_since=snapshot.stable_since,
        occupancy_observation=snapshot.observation,
        zone_visit_id=VISIT_ID if confirmed else None,
        physical_vehicle_id=VEHICLE_ID if confirmed else None,
        parking_session_id=SESSION_ID if confirmed else None,
        context_revision=spec.context_revision if confirmed else None,
        decision=spec.decision,
        reason=spec.reason,
        evaluated_at=evaluated_at,
    )


class _SnapshotStore:
    def __init__(
        self,
        *snapshots: ZoneOccupancySnapshot,
    ) -> None:
        self._lock = Lock()
        self._snapshots = {
            snapshot.zone_id: snapshot
            for snapshot in snapshots
        }

    def snapshots(self) -> tuple[ZoneOccupancySnapshot, ...]:
        with self._lock:
            return tuple(
                self._snapshots[zone_id]
                for zone_id in sorted(self._snapshots)
            )

    def set(self, snapshot: ZoneOccupancySnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.zone_id] = snapshot


class _ScriptedSnapshotSupplier:
    def __init__(
        self,
        *results: tuple[ZoneOccupancySnapshot, ...] | Exception,
    ) -> None:
        self._results = list(results)

    def __call__(self) -> tuple[ZoneOccupancySnapshot, ...]:
        if not self._results:
            raise AssertionError("snapshot script가 모두 소비됐습니다.")
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _ConnectionFactory:
    def __init__(
        self,
        *,
        fail_calls: set[int] | None = None,
    ) -> None:
        self.calls = 0
        self.connections: list[_FakeConnection] = []
        self._fail_calls = fail_calls or set()

    def __call__(self) -> _FakeConnection:
        self.calls += 1
        if self.calls in self._fail_calls:
            raise RuntimeError("connection unavailable")

        connection = _FakeConnection()
        self.connections.append(connection)
        return connection


class _FakeService:
    def __init__(self) -> None:
        self.specs: dict[ZoneId, _AssessmentSpec] = {}
        self.zone_types: dict[ZoneId, ZoneType] = {}
        self.failures: dict[ZoneId, Exception] = {}
        self.calls: list[tuple[ZoneId, _FakeConnection]] = []

    def assess(
        self,
        snapshot: ZoneOccupancySnapshot,
        *,
        sensor_runtime_available: bool,
        evaluated_at: datetime,
        connection: _FakeConnection,
    ) -> TofZoneAuthorizationAssessment:
        self.calls.append((snapshot.zone_id, connection))

        failure = self.failures.get(snapshot.zone_id)
        if failure is not None:
            raise failure

        if snapshot.stable_state is OccupancyState.VACANT:
            spec = _AssessmentSpec(
                decision=None,
                reason=TofAuthorizationReason.ZONE_VACANT,
            )
        elif snapshot.stable_state is OccupancyState.UNKNOWN:
            spec = _AssessmentSpec(
                decision=None,
                reason=TofAuthorizationReason.OCCUPANCY_NOT_CONFIRMED,
            )
        else:
            spec = self.specs.get(snapshot.zone_id, UNKNOWN_SPEC)

        return _assessment(
            snapshot,
            zone_type=self.zone_types.get(
                snapshot.zone_id,
                ZoneType.DISABLED,
            ),
            evaluated_at=evaluated_at,
            spec=spec,
        )


class _BlockingService(_FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.entered = Event()
        self.release = Event()

    def assess(
        self,
        snapshot: ZoneOccupancySnapshot,
        *,
        sensor_runtime_available: bool,
        evaluated_at: datetime,
        connection: _FakeConnection,
    ) -> TofZoneAuthorizationAssessment:
        self.entered.set()
        if not self.release.wait(timeout=1):
            raise RuntimeError("test did not release service")
        return super().assess(
            snapshot,
            sensor_runtime_available=sensor_runtime_available,
            evaluated_at=evaluated_at,
            connection=connection,
        )


class _SerializingService(_FakeService):
    def __init__(self) -> None:
        super().__init__()
        self._call_lock = Lock()
        self.active_calls = 0
        self.max_concurrent_calls = 0
        self.call_count = 0
        self.first_entered = Event()
        self.release_first = Event()
        self.second_entered = Event()

    def assess(
        self,
        snapshot: ZoneOccupancySnapshot,
        *,
        sensor_runtime_available: bool,
        evaluated_at: datetime,
        connection: _FakeConnection,
    ) -> TofZoneAuthorizationAssessment:
        with self._call_lock:
            self.call_count += 1
            call_number = self.call_count
            self.active_calls += 1
            self.max_concurrent_calls = max(
                self.max_concurrent_calls,
                self.active_calls,
            )

        try:
            if call_number == 1:
                self.first_entered.set()
                if not self.release_first.wait(timeout=1):
                    raise RuntimeError("test did not release first evaluation")
            else:
                self.second_entered.set()

            return super().assess(
                snapshot,
                sensor_runtime_available=sensor_runtime_available,
                evaluated_at=evaluated_at,
                connection=connection,
            )
        finally:
            with self._call_lock:
                self.active_calls -= 1


@dataclass
class _ThreadCapture:
    results: list[TofAuthorizationCoordinatorRun] = field(
        default_factory=list
    )
    errors: list[BaseException] = field(default_factory=list)


def _start_drain(
    coordinator: TofZoneAuthorizationCoordinator,
    capture: _ThreadCapture,
    *,
    started: Event | None = None,
) -> Thread:
    def run() -> None:
        try:
            if started is not None:
                started.set()
            capture.results.append(coordinator.drain_pending())
        except BaseException as exc:
            capture.errors.append(exc)

    thread = Thread(target=run)
    thread.start()
    return thread


def _coordinator(
    *,
    store: _SnapshotStore,
    service: _FakeService,
    connection_factory: _ConnectionFactory | None = None,
    consumer=None,
    clock=None,
) -> TofZoneAuthorizationCoordinator:
    return TofZoneAuthorizationCoordinator(
        authorization_service=service,
        occupancy_snapshots=store.snapshots,
        sensor_runtime_available=lambda: True,
        connection_factory=connection_factory or _ConnectionFactory(),
        assessment_consumer=consumer,
        clock=clock or (lambda: NOW),
    )


def _assert_single_retry(
    run: TofAuthorizationCoordinatorRun,
    *,
    zone_id: ZoneId,
    minimum_revision: int | None,
) -> None:
    assert run.retry_requests == (
        TofAuthorizationRetryRequest(
            zone_id=zone_id,
            minimum_occupancy_revision=minimum_revision,
        ),
    )


@dataclass
class _RecordingActuatorPort:
    attempts: list[tuple[ActuatorCommand, ...]] = field(
        default_factory=list
    )
    applied_projections: list[tuple[ActuatorCommand, ...]] = field(
        default_factory=list
    )
    fail_first_error: Exception | None = None

    def apply_projection(
        self,
        commands: tuple[ActuatorCommand, ...],
    ) -> None:
        self.attempts.append(commands)

        if self.fail_first_error is not None:
            error = self.fail_first_error
            self.fail_first_error = None
            raise error

        self.applied_projections.append(commands)


def _local_warning_coordinator(
    *,
    led_port: _RecordingActuatorPort,
    speaker_port: _RecordingActuatorPort,
) -> LocalWarningCoordinator:
    return LocalWarningCoordinator(
        bindings=(
            LocalWarningZoneBinding(
                zone_id=ZONE_1,
                zone_type=ZoneType.DISABLED,
                led_actuator_id="disabled_zone_warning_led",
                led_action="BLINK",
                speaker_actuator_id="disabled_zone_warning_speaker",
                speaker_action="PLAY",
            ),
            LocalWarningZoneBinding(
                zone_id=ZONE_2,
                zone_type=ZoneType.EV_CHARGING,
                led_actuator_id="ev_zone_warning_led",
                led_action="BLINK",
                speaker_actuator_id="ev_zone_warning_speaker",
                speaker_action="PLAY",
            ),
        ),
        led_port=led_port,
        speaker_port=speaker_port,
    )


def test_request_transitions_only_registers_and_merges_requests() -> None:
    store = _SnapshotStore(
        _snapshot(ZONE_1, revision=5),
        _snapshot(ZONE_2, revision=1),
    )
    service = _FakeService()
    connections = _ConnectionFactory()
    consumed: list[TofZoneAuthorizationAssessment] = []
    coordinator = _coordinator(
        store=store,
        service=service,
        connection_factory=connections,
        consumer=consumed.append,
    )

    coordinator.request_transitions(
        (
            _transition(ZONE_1, revision=2),
            _transition(ZONE_1, revision=5),
            _transition(ZONE_2, revision=1),
        )
    )

    assert service.calls == []
    assert connections.calls == 0
    assert consumed == []

    run = coordinator.drain_pending()

    assert [call[0] for call in service.calls] == [ZONE_1, ZONE_2]
    assert [
        assessment.zone_id
        for assessment in run.published_assessments
    ] == [ZONE_1, ZONE_2]


def test_request_occupied_zones_preserves_existing_vacant_request() -> None:
    store = _SnapshotStore(
        _snapshot(ZONE_1, state=OccupancyState.OCCUPIED),
        _snapshot(ZONE_2, state=OccupancyState.VACANT),
    )
    service = _FakeService()
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_zone(ZONE_2)
    coordinator.request_occupied_zones()
    run = coordinator.drain_pending()

    assert [
        assessment.zone_id
        for assessment in run.published_assessments
    ] == [ZONE_1, ZONE_2]


def test_zone_occupancy_revisions_returns_every_state_without_side_effects(
) -> None:
    zone_3 = ZoneId(3)
    store = _SnapshotStore(
        _snapshot(
            zone_3,
            state=OccupancyState.UNKNOWN,
            revision=7,
        ),
        _snapshot(
            ZONE_2,
            state=OccupancyState.VACANT,
            revision=5,
        ),
        _snapshot(ZONE_1, revision=4),
    )
    connections = _ConnectionFactory()
    coordinator = _coordinator(
        store=store,
        service=_FakeService(),
        connection_factory=connections,
    )
    coordinator.request_zone(ZONE_1)

    assert coordinator.zone_occupancy_revisions() == (
        (ZONE_1, 4, OccupancyState.OCCUPIED),
        (ZONE_2, 5, OccupancyState.VACANT),
        (zone_3, 7, OccupancyState.UNKNOWN),
    )
    assert connections.calls == 0

    run = coordinator.drain_pending()
    assert [
        assessment.zone_id
        for assessment in run.published_assessments
    ] == [ZONE_1]


def test_request_occupied_zones_still_requests_only_occupied() -> None:
    store = _SnapshotStore(
        _snapshot(ZONE_1, revision=4),
        _snapshot(
            ZONE_2,
            state=OccupancyState.VACANT,
            revision=5,
        ),
        _snapshot(
            ZoneId(3),
            state=OccupancyState.UNKNOWN,
            revision=6,
        ),
    )
    coordinator = _coordinator(
        store=store,
        service=_FakeService(),
    )

    coordinator.request_occupied_zones()
    run = coordinator.drain_pending()

    assert [
        assessment.zone_id
        for assessment in run.published_assessments
    ] == [ZONE_1]


def test_request_all_snapshots_registers_every_snapshot() -> None:
    store = _SnapshotStore(
        _snapshot(ZONE_1, state=OccupancyState.OCCUPIED),
        _snapshot(ZONE_2, state=OccupancyState.VACANT),
    )
    service = _FakeService()
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_all_snapshots()
    coordinator.drain_pending()

    assert [call[0] for call in service.calls] == [ZONE_1, ZONE_2]


def test_monitoring_reevaluation_changes_unknown_to_authorized() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _FakeService()
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_zone(ZONE_1)
    first = coordinator.drain_pending().published_assessments[0]

    service.specs[ZONE_1] = AUTHORIZED_SPEC
    second = coordinator.reevaluate_after_monitoring_commit()
    authorized = second.published_assessments[0]

    assert first.decision is TofAuthorizationDecision.UNKNOWN
    assert first.assessment_revision == 1
    assert authorized.decision is TofAuthorizationDecision.AUTHORIZED
    assert authorized.assessment_revision == 2


def test_context_revision_change_is_new_semantic_result() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _FakeService()
    service.specs[ZONE_1] = AUTHORIZED_SPEC
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_zone(ZONE_1)
    first = coordinator.drain_pending().published_assessments[0]

    service.specs[ZONE_1] = _AssessmentSpec(
        decision=TofAuthorizationDecision.AUTHORIZED,
        reason=None,
        context_revision=2,
    )
    coordinator.request_zone(ZONE_1)
    second = coordinator.drain_pending().published_assessments[0]

    assert first.context_revision == 1
    assert second.context_revision == 2
    assert second.assessment_revision == 2


@pytest.mark.parametrize(
    ("first_spec", "second_spec"),
    (
        (AUTHORIZED_SPEC, UNAUTHORIZED_SPEC),
        (UNAUTHORIZED_SPEC, AUTHORIZED_SPEC),
    ),
)
def test_authorization_change_publishes_new_revision(
    first_spec: _AssessmentSpec,
    second_spec: _AssessmentSpec,
) -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _FakeService()
    service.specs[ZONE_1] = first_spec
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_zone(ZONE_1)
    first = coordinator.drain_pending().published_assessments[0]

    service.specs[ZONE_1] = second_spec
    coordinator.request_zone(ZONE_1)
    second = coordinator.drain_pending().published_assessments[0]

    assert first.assessment_revision == 1
    assert second.assessment_revision == 2
    assert first.decision is first_spec.decision
    assert second.decision is second_spec.decision


def test_assessment_revisions_are_independent_per_zone() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1), _snapshot(ZONE_2))
    service = _FakeService()
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_zone(ZONE_1)
    coordinator.request_zone(ZONE_2)
    first_run = coordinator.drain_pending()

    service.specs[ZONE_1] = AUTHORIZED_SPEC
    coordinator.request_zone(ZONE_1)
    second = coordinator.drain_pending().published_assessments[0]

    assert [
        assessment.assessment_revision
        for assessment in first_run.published_assessments
    ] == [1, 1]
    assert second.assessment_revision == 2


def test_same_semantic_result_is_not_republished_but_latest_is_refreshed() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1, revision=1))
    service = _FakeService()
    consumed: list[TofZoneAuthorizationAssessment] = []
    times = iter((NOW, NOW + timedelta(seconds=1)))
    coordinator = _coordinator(
        store=store,
        service=service,
        consumer=consumed.append,
        clock=lambda: next(times),
    )

    coordinator.request_zone(ZONE_1)
    first = coordinator.drain_pending().published_assessments[0]

    store.set(
        replace(
            _snapshot(ZONE_1, revision=1),
            revision=2,
            observation=_observed(NOW + timedelta(seconds=1)),
            last_input_at=NOW + timedelta(seconds=1),
        )
    )
    coordinator.request_zone(ZONE_1)
    second_run = coordinator.drain_pending()
    latest = coordinator.latest_assessment(ZONE_1)

    assert second_run.published_assessments == ()
    assert second_run.unchanged_zone_ids == (ZONE_1,)
    assert len(consumed) == 1
    assert latest is not None
    assert latest.assessment_revision == first.assessment_revision
    assert latest.occupancy_revision == 2
    assert latest.evaluated_at == NOW + timedelta(seconds=1)


def test_vacant_is_published_once_as_scope_termination() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _FakeService()
    service.specs[ZONE_1] = AUTHORIZED_SPEC
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_zone(ZONE_1)
    coordinator.drain_pending()

    store.set(
        _snapshot(
            ZONE_1,
            state=OccupancyState.VACANT,
            stable_since=NOW + timedelta(seconds=1),
            revision=2,
        )
    )
    coordinator.request_zone(ZONE_1)
    vacant = coordinator.drain_pending().published_assessments[0]

    coordinator.request_zone(ZONE_1)
    repeated = coordinator.drain_pending()

    assert vacant.decision is None
    assert vacant.reason is TofAuthorizationReason.ZONE_VACANT
    assert vacant.assessment_revision == 2
    assert repeated.published_assessments == ()
    assert repeated.unchanged_zone_ids == (ZONE_1,)


@pytest.mark.parametrize(
    "changed_snapshot",
    (
        _snapshot(
            ZONE_1,
            state=OccupancyState.VACANT,
            stable_since=NOW + timedelta(seconds=1),
            revision=2,
        ),
        replace(
            _snapshot(ZONE_1, revision=1),
            revision=2,
            observation=ObservationStatus(
                state=ObservationState.DEGRADED,
                reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
                last_reliable_observed_at=NOW,
            ),
            last_input_at=NOW + timedelta(seconds=1),
        ),
    ),
)
def test_changed_causal_scope_defers_late_result(
    changed_snapshot: ZoneOccupancySnapshot,
) -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _BlockingService()
    service.specs[ZONE_1] = AUTHORIZED_SPEC
    coordinator = _coordinator(store=store, service=service)
    coordinator.request_zone(ZONE_1)

    capture = _ThreadCapture()
    thread = _start_drain(coordinator, capture)

    assert service.entered.wait(timeout=1)
    store.set(changed_snapshot)
    service.release.set()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert capture.errors == []
    assert len(capture.results) == 1
    assert capture.results[0].published_assessments == ()
    assert capture.results[0].deferred_zone_ids == (ZONE_1,)
    _assert_single_retry(
        capture.results[0],
        zone_id=ZONE_1,
        minimum_revision=changed_snapshot.revision,
    )
    assert coordinator.latest_assessment(ZONE_1) is None
    assert coordinator.drain_pending().retry_requests == ()


def test_same_zone_concurrent_drains_are_serialized() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _SerializingService()
    coordinator = _coordinator(store=store, service=service)

    coordinator.request_zone(ZONE_1)
    first_capture = _ThreadCapture()
    first_thread = _start_drain(coordinator, first_capture)

    assert service.first_entered.wait(timeout=1)

    coordinator.request_zone(ZONE_1)
    second_capture = _ThreadCapture()
    second_started = Event()
    second_thread = _start_drain(
        coordinator,
        second_capture,
        started=second_started,
    )

    assert second_started.wait(timeout=1)
    assert not service.second_entered.wait(timeout=0.05)

    service.release_first.set()

    first_thread.join(timeout=1)
    second_thread.join(timeout=1)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert first_capture.errors == []
    assert second_capture.errors == []
    assert service.second_entered.is_set()
    assert service.call_count == 2
    assert service.max_concurrent_calls == 1


def test_service_failure_returns_retry_and_other_zone_continues() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1), _snapshot(ZONE_2))
    service = _FakeService()
    service.failures[ZONE_1] = RuntimeError("service unavailable")
    connections = _ConnectionFactory()
    coordinator = _coordinator(
        store=store,
        service=service,
        connection_factory=connections,
    )

    coordinator.request_zone(ZONE_1)
    coordinator.request_zone(ZONE_2)
    first_run = coordinator.drain_pending()

    assert [
        failure.zone_id for failure in first_run.failures
    ] == [ZONE_1]
    assert first_run.failures[0].stage is (
        TofAuthorizationCoordinatorStage.EVALUATION
    )
    assert [
        assessment.zone_id
        for assessment in first_run.published_assessments
    ] == [ZONE_2]
    _assert_single_retry(
        first_run,
        zone_id=ZONE_1,
        minimum_revision=None,
    )
    assert all(connection.closed for connection in connections.connections)

    assert coordinator.drain_pending().retry_requests == ()
    del service.failures[ZONE_1]
    retry = first_run.retry_requests[0]
    coordinator.request_zone(
        retry.zone_id,
        minimum_occupancy_revision=(
            retry.minimum_occupancy_revision
        ),
    )
    second_run = coordinator.drain_pending()

    assert [
        assessment.zone_id
        for assessment in second_run.published_assessments
    ] == [ZONE_1]
    assert second_run.failures == ()


def test_snapshot_revision_failure_returns_retry_until_snapshot_catches_up(
) -> None:
    store = _SnapshotStore(_snapshot(ZONE_1, revision=4))
    service = _FakeService()
    connections = _ConnectionFactory()
    coordinator = _coordinator(
        store=store,
        service=service,
        connection_factory=connections,
    )

    coordinator.request_zone(
        ZONE_1,
        minimum_occupancy_revision=5,
    )
    first_run = coordinator.drain_pending()

    assert first_run.failures[0].stage is (
        TofAuthorizationCoordinatorStage.SNAPSHOT
    )
    assert service.calls == []
    assert connections.calls == 0
    _assert_single_retry(
        first_run,
        zone_id=ZONE_1,
        minimum_revision=5,
    )

    assert coordinator.drain_pending().retry_requests == ()
    store.set(_snapshot(ZONE_1, revision=5))
    retry = first_run.retry_requests[0]
    coordinator.request_zone(
        retry.zone_id,
        minimum_occupancy_revision=(
            retry.minimum_occupancy_revision
        ),
    )
    second_run = coordinator.drain_pending()

    assert len(second_run.published_assessments) == 1
    assert second_run.published_assessments[0].zone_id == ZONE_1
    assert second_run.failures == ()


def test_post_evaluation_snapshot_failure_returns_matching_retry() -> None:
    snapshot = _snapshot(ZONE_1, revision=1)
    supplier = _ScriptedSnapshotSupplier(
        (snapshot,),
        RuntimeError("snapshot refresh failed"),
    )
    coordinator = TofZoneAuthorizationCoordinator(
        authorization_service=_FakeService(),
        occupancy_snapshots=supplier,
        sensor_runtime_available=lambda: True,
        connection_factory=_ConnectionFactory(),
        clock=lambda: NOW,
    )
    coordinator.request_zone(
        ZONE_1,
        minimum_occupancy_revision=1,
    )

    run = coordinator.drain_pending()

    assert run.failures[0].stage is (
        TofAuthorizationCoordinatorStage.SNAPSHOT
    )
    _assert_single_retry(
        run,
        zone_id=ZONE_1,
        minimum_revision=1,
    )
    assert coordinator.drain_pending().retry_requests == ()


def test_vacant_evaluation_failure_returns_matching_retry() -> None:
    store = _SnapshotStore(
        _snapshot(
            ZONE_1,
            state=OccupancyState.VACANT,
            revision=2,
        )
    )
    service = _FakeService()
    service.failures[ZONE_1] = RuntimeError("service unavailable")
    coordinator = _coordinator(store=store, service=service)
    coordinator.request_zone(
        ZONE_1,
        minimum_occupancy_revision=2,
    )

    run = coordinator.drain_pending()

    assert run.failures[0].stage is (
        TofAuthorizationCoordinatorStage.EVALUATION
    )
    _assert_single_retry(
        run,
        zone_id=ZONE_1,
        minimum_revision=2,
    )
    assert coordinator.drain_pending().retry_requests == ()


def test_connection_factory_failure_isolated_from_next_zone() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1), _snapshot(ZONE_2))
    service = _FakeService()
    connections = _ConnectionFactory(fail_calls={1})
    coordinator = _coordinator(
        store=store,
        service=service,
        connection_factory=connections,
    )

    coordinator.request_zone(ZONE_1)
    coordinator.request_zone(ZONE_2)
    run = coordinator.drain_pending()

    assert len(run.failures) == 1
    assert run.failures[0].zone_id == ZONE_1
    assert run.failures[0].stage is (
        TofAuthorizationCoordinatorStage.EVALUATION
    )
    assert [
        assessment.zone_id
        for assessment in run.published_assessments
    ] == [ZONE_2]
    _assert_single_retry(
        run,
        zone_id=ZONE_1,
        minimum_revision=None,
    )
    assert [call[0] for call in service.calls] == [ZONE_2]
    assert len(connections.connections) == 1
    assert connections.connections[0].closed


def test_consumer_failure_retries_same_revision_and_other_zone_continues() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1), _snapshot(ZONE_2))
    service = _FakeService()
    attempts: list[TofZoneAuthorizationAssessment] = []
    failed_once = False

    def consume(assessment: TofZoneAuthorizationAssessment) -> None:
        nonlocal failed_once
        attempts.append(assessment)
        if assessment.zone_id == ZONE_1 and not failed_once:
            failed_once = True
            raise RuntimeError("publication unavailable")

    coordinator = _coordinator(
        store=store,
        service=service,
        consumer=consume,
    )
    coordinator.request_zone(ZONE_1)
    coordinator.request_zone(ZONE_2)

    first_run = coordinator.drain_pending()

    assert first_run.failures[0].zone_id == ZONE_1
    assert first_run.failures[0].stage is (
        TofAuthorizationCoordinatorStage.PUBLICATION
    )
    assert [
        assessment.zone_id
        for assessment in first_run.published_assessments
    ] == [ZONE_2]

    pending = coordinator.latest_assessment(ZONE_1)
    assert pending is not None
    assert pending.assessment_revision == 1

    _assert_single_retry(
        first_run,
        zone_id=ZONE_1,
        minimum_revision=None,
    )
    assert coordinator.drain_pending().published_assessments == ()
    retry = first_run.retry_requests[0]
    coordinator.request_zone(
        retry.zone_id,
        minimum_occupancy_revision=(
            retry.minimum_occupancy_revision
        ),
    )
    second_run = coordinator.drain_pending()
    retried = second_run.published_assessments[0]

    assert retried.zone_id == ZONE_1
    assert retried.assessment_revision == 1
    assert [
        attempt.assessment_revision
        for attempt in attempts
        if attempt.zone_id == ZONE_1
    ] == [1, 1]


def test_vacant_publication_failure_preserves_pending_revision() -> None:
    store = _SnapshotStore(
        _snapshot(
            ZONE_1,
            state=OccupancyState.VACANT,
            revision=2,
        )
    )
    attempts: list[TofZoneAuthorizationAssessment] = []
    failed_once = False

    def consume(assessment: TofZoneAuthorizationAssessment) -> None:
        nonlocal failed_once
        attempts.append(assessment)
        if not failed_once:
            failed_once = True
            raise RuntimeError("publication unavailable")

    coordinator = _coordinator(
        store=store,
        service=_FakeService(),
        consumer=consume,
    )
    coordinator.request_zone(
        ZONE_1,
        minimum_occupancy_revision=2,
    )

    first = coordinator.drain_pending()

    assert first.failures[0].stage is (
        TofAuthorizationCoordinatorStage.PUBLICATION
    )
    _assert_single_retry(
        first,
        zone_id=ZONE_1,
        minimum_revision=2,
    )
    pending = coordinator.latest_assessment(ZONE_1)
    assert pending is not None
    assert pending.occupancy_state is OccupancyState.VACANT
    assert pending.assessment_revision == 1

    assert coordinator.drain_pending().published_assessments == ()
    coordinator.request_zone(
        ZONE_1,
        minimum_occupancy_revision=2,
    )
    second = coordinator.drain_pending()

    assert second.published_assessments == (pending,)
    assert attempts == [pending, pending]
    assert second.published_assessments[0].assessment_revision == 1


def test_local_warning_consumer_preserves_other_zone_when_one_zone_becomes_vacant(
) -> None:
    store = _SnapshotStore(
        _snapshot(ZONE_1),
        _snapshot(ZONE_2),
    )
    service = _FakeService()
    service.specs[ZONE_1] = UNAUTHORIZED_SPEC
    service.specs[ZONE_2] = UNAUTHORIZED_SPEC
    service.zone_types[ZONE_2] = ZoneType.EV_CHARGING
    led_port = _RecordingActuatorPort()
    speaker_port = _RecordingActuatorPort()
    local_warning = _local_warning_coordinator(
        led_port=led_port,
        speaker_port=speaker_port,
    )
    coordinator = _coordinator(
        store=store,
        service=service,
        consumer=local_warning.consume_assessment,
    )

    coordinator.request_zone(ZONE_1)
    coordinator.request_zone(ZONE_2)
    first_run = coordinator.drain_pending()

    assert first_run.failures == ()
    assert [
        assessment.zone_id
        for assessment in first_run.published_assessments
    ] == [ZONE_1, ZONE_2]
    assert [
        assessment.zone_type
        for assessment in first_run.published_assessments
    ] == [ZoneType.DISABLED, ZoneType.EV_CHARGING]
    assert [
        assessment.assessment_revision
        for assessment in first_run.published_assessments
    ] == [1, 1]
    assert all(
        assessment.decision
        is TofAuthorizationDecision.UNAUTHORIZED
        for assessment in first_run.published_assessments
    )
    assert local_warning.active_zone_ids() == (ZONE_1, ZONE_2)
    assert [
        command.actuator_id
        for command in led_port.applied_projections[-1]
    ] == [
        "disabled_zone_warning_led",
        "ev_zone_warning_led",
    ]
    assert [
        command.actuator_id
        for command in speaker_port.applied_projections[-1]
    ] == [
        "disabled_zone_warning_speaker",
        "ev_zone_warning_speaker",
    ]

    ev_led_requested_at = (
        led_port.applied_projections[-1][1].requested_at
    )
    ev_speaker_requested_at = (
        speaker_port.applied_projections[-1][1].requested_at
    )

    store.set(
        _snapshot(
            ZONE_1,
            state=OccupancyState.VACANT,
            stable_since=NOW + timedelta(seconds=1),
            revision=2,
        )
    )
    coordinator.request_zone(ZONE_1)
    vacant_run = coordinator.drain_pending()

    assert vacant_run.failures == ()
    assert len(vacant_run.published_assessments) == 1
    vacant = vacant_run.published_assessments[0]
    assert vacant.zone_id == ZONE_1
    assert vacant.zone_type is ZoneType.DISABLED
    assert vacant.assessment_revision == 2
    assert vacant.occupancy_state is OccupancyState.VACANT
    assert vacant.decision is None
    assert vacant.reason is TofAuthorizationReason.ZONE_VACANT

    assert local_warning.active_zone_ids() == (ZONE_2,)
    assert [
        command.actuator_id
        for command in led_port.applied_projections[-1]
    ] == ["ev_zone_warning_led"]
    assert [
        command.actuator_id
        for command in speaker_port.applied_projections[-1]
    ] == ["ev_zone_warning_speaker"]
    assert (
        led_port.applied_projections[-1][0].requested_at
        == ev_led_requested_at
    )
    assert (
        speaker_port.applied_projections[-1][0].requested_at
        == ev_speaker_requested_at
    )


def test_local_warning_delivery_failure_retries_same_publication_revision(
) -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _FakeService()
    service.specs[ZONE_1] = UNAUTHORIZED_SPEC
    led_error = RuntimeError("LED unavailable")
    led_port = _RecordingActuatorPort(
        fail_first_error=led_error
    )
    speaker_port = _RecordingActuatorPort()
    local_warning = _local_warning_coordinator(
        led_port=led_port,
        speaker_port=speaker_port,
    )
    coordinator = _coordinator(
        store=store,
        service=service,
        consumer=local_warning.consume_assessment,
    )
    coordinator.request_zone(ZONE_1)

    first_run = coordinator.drain_pending()

    assert first_run.published_assessments == ()
    assert len(first_run.failures) == 1
    failure = first_run.failures[0]
    assert failure.zone_id == ZONE_1
    assert failure.stage is TofAuthorizationCoordinatorStage.PUBLICATION
    assert isinstance(failure.error, LocalWarningDeliveryError)
    assert failure.error.primary_error is led_error

    pending = coordinator.latest_assessment(ZONE_1)
    assert pending is not None
    assert pending.assessment_revision == 1
    assert pending.decision is TofAuthorizationDecision.UNAUTHORIZED
    assert local_warning.active_zone_ids() == (ZONE_1,)
    assert len(led_port.attempts) == 1
    assert led_port.applied_projections == []
    assert len(speaker_port.attempts) == 1
    assert len(speaker_port.applied_projections) == 1

    _assert_single_retry(
        first_run,
        zone_id=ZONE_1,
        minimum_revision=None,
    )
    assert coordinator.drain_pending().published_assessments == ()
    retry = first_run.retry_requests[0]
    coordinator.request_zone(
        retry.zone_id,
        minimum_occupancy_revision=(
            retry.minimum_occupancy_revision
        ),
    )
    second_run = coordinator.drain_pending()

    assert second_run.failures == ()
    assert len(second_run.published_assessments) == 1
    retried = second_run.published_assessments[0]
    assert retried == pending
    assert retried.assessment_revision == 1
    assert len(led_port.attempts) == 2
    assert len(led_port.applied_projections) == 1
    assert led_port.attempts[1] == led_port.attempts[0]
    assert led_port.applied_projections == [led_port.attempts[0]]
    assert len(speaker_port.attempts) == 1
    assert len(speaker_port.applied_projections) == 1

    latest = coordinator.latest_assessment(ZONE_1)
    assert latest == retried
    assert latest.assessment_revision == 1

    third_run = coordinator.drain_pending()

    assert third_run.published_assessments == ()
    assert third_run.unchanged_zone_ids == ()
    assert third_run.deferred_zone_ids == ()
    assert third_run.failures == ()
    assert len(led_port.attempts) == 2
    assert len(speaker_port.attempts) == 1


def test_semantic_change_replaces_failed_pending_publication() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _FakeService()
    attempts: list[TofZoneAuthorizationAssessment] = []

    def consume(assessment: TofZoneAuthorizationAssessment) -> None:
        attempts.append(assessment)
        if len(attempts) == 1:
            raise RuntimeError("publication unavailable")

    coordinator = _coordinator(
        store=store,
        service=service,
        consumer=consume,
    )

    coordinator.request_zone(ZONE_1)
    first_run = coordinator.drain_pending()
    assert first_run.failures

    store.set(
        _snapshot(
            ZONE_1,
            state=OccupancyState.VACANT,
            stable_since=NOW + timedelta(seconds=1),
            revision=2,
        )
    )
    coordinator.request_zone(
        ZONE_1,
        minimum_occupancy_revision=2,
    )
    second_run = coordinator.drain_pending()

    assert len(attempts) == 2
    assert attempts[0].decision is TofAuthorizationDecision.UNKNOWN
    assert attempts[0].assessment_revision == 1
    assert attempts[1].decision is None
    assert attempts[1].reason is TofAuthorizationReason.ZONE_VACANT
    assert attempts[1].assessment_revision == 2
    assert second_run.published_assessments == (attempts[1],)


def test_connection_is_closed_before_consumer_is_called() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    service = _FakeService()
    connections = _ConnectionFactory()
    observed_closed: list[bool] = []

    def consume(assessment: TofZoneAuthorizationAssessment) -> None:
        observed_closed.append(connections.connections[-1].closed)

    coordinator = _coordinator(
        store=store,
        service=service,
        connection_factory=connections,
        consumer=consume,
    )
    coordinator.request_zone(ZONE_1)
    coordinator.drain_pending()

    assert observed_closed == [True]


def test_latest_queries_prefer_pending_and_order_by_zone() -> None:
    store = _SnapshotStore(_snapshot(ZONE_1), _snapshot(ZONE_2))
    service = _FakeService()

    def consume(assessment: TofZoneAuthorizationAssessment) -> None:
        if assessment.zone_id == ZONE_2:
            raise RuntimeError("publication unavailable")

    coordinator = _coordinator(
        store=store,
        service=service,
        consumer=consume,
    )

    coordinator.request_zone(ZONE_2)
    coordinator.request_zone(ZONE_1)
    coordinator.drain_pending()

    assessments = coordinator.assessments()

    assert [assessment.zone_id for assessment in assessments] == [
        ZONE_1,
        ZONE_2,
    ]
    assert coordinator.latest_assessment(ZONE_1) == assessments[0]
    assert coordinator.latest_assessment(ZONE_2) == assessments[1]
    assert coordinator.latest_assessment(ZoneId(999)) is None


@pytest.mark.parametrize(
    "revision",
    (-1, True, 1.5),
)
def test_request_zone_rejects_invalid_revision(revision: object) -> None:
    store = _SnapshotStore(_snapshot(ZONE_1))
    coordinator = _coordinator(
        store=store,
        service=_FakeService(),
    )

    with pytest.raises(ValueError):
        coordinator.request_zone(
            ZONE_1,
            minimum_occupancy_revision=revision,
        )

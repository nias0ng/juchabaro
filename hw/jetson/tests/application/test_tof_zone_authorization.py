"""ToF 전용구역 권한 평가와 SQLite read snapshot 계약 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
from pathlib import Path
import sqlite3
from typing import cast
from unittest.mock import patch
from uuid import UUID

import pytest

from src.application.sensor_occupancy import OccupancyState, ZoneOccupancySnapshot
from src.application.tof_monitoring_projection import (
    LatestTofMonitoringProjectionStore,
    TofMonitoringProjectionUpdate,
    TofVehicleObservationProjection,
)
from src.application.tof_zone_authorization import (
    RepositoryTofZoneAuthorizationQuery,
    TofAuthorizationDecision,
    TofAuthorizationPolicy,
    TofAuthorizationReason,
    TofZoneAuthorizationAssessment,
    TofZoneAuthorizationService,
    TofZoneVehicleCandidate,
)
from src.application.tof_zone_authorization_coordinator import (
    TofZoneAuthorizationCoordinator,
)
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.parking.zone_registry import ZoneRegistry
from src.session.models import (
    ContextBinding,
    ContextBindingId,
    ContextBindingState,
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.aggregate_repositories import ZoneVisitRepository
from src.storage.database import open_database
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
    VehicleId,
)


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
ZONE_ID = ZoneId(7)
SESSION_ID = ParkingSessionId(55)
VEHICLE_ID = PhysicalVehicleId(UUID(int=1))
VISIT_ID = ZoneVisitId(UUID(int=2))
ENTRY_ATTEMPT_ID = EntryAttemptId(UUID(int=3))
CONTEXT_BINDING_ID = ContextBindingId(UUID(int=4))
_DEFAULT_CANDIDATE_VALUE = object()


def _observed(at: datetime = NOW) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at,
    )


def _unreliable(
    state: ObservationState = ObservationState.UNKNOWN,
) -> ObservationStatus:
    return ObservationStatus(
        state=state,
        reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
        last_reliable_observed_at=NOW,
    )


def _zone(zone_type: ZoneType, zone_id: ZoneId = ZONE_ID) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=zone_id,
        zone_type=zone_type,
        polygon=((0.1, 0.1), (0.4, 0.1), (0.4, 0.4), (0.1, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="calibration-v1",
    )


def _snapshot(
    *,
    state: OccupancyState = OccupancyState.OCCUPIED,
    observation: ObservationStatus | None = None,
    stable_since: datetime | None = None,
) -> ZoneOccupancySnapshot:
    return ZoneOccupancySnapshot(
        sensor_id="tof-zone-7",
        zone_id=ZONE_ID,
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
        revision=3,
    )


def _context(
    *,
    disabled: bool | None = True,
    electric: bool | None = False,
) -> SessionContext:
    return SessionContext(
        parking_session_id=SESSION_ID,
        vehicle_id=VehicleId(10),
        is_electric=electric,
        is_disabled_vehicle=disabled,
    )


def _visit(**changes: object) -> ZoneVisit:
    visit = ZoneVisit(
        visit_id=VISIT_ID,
        physical_vehicle_id=VEHICLE_ID,
        zone_id=ZONE_ID,
        zone_definition_version=ZoneDefinitionVersion(1),
        state=ZoneVisitState.INSIDE,
        observation=_observed(),
        entry_trusted_seconds=1.0,
        exit_trusted_seconds=0.0,
        entry_confirmation_seconds=1.0,
        exit_confirmation_seconds=1.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=NOW - timedelta(seconds=2),
        updated_at=NOW,
        entered_candidate_at=NOW - timedelta(seconds=2),
        entered_at=NOW - timedelta(seconds=1),
    )
    return replace(visit, **changes)


def _vehicle(**changes: object) -> PhysicalVehicle:
    vehicle = PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=_observed(),
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=4.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=NOW - timedelta(seconds=3),
        updated_at=NOW,
    )
    return replace(vehicle, **changes)


def _binding(
    *,
    context: SessionContext | None = None,
    **changes: object,
) -> ContextBinding:
    binding = ContextBinding(
        context_binding_id=CONTEXT_BINDING_ID,
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        parking_session_id=SESSION_ID,
        physical_vehicle_id=VEHICLE_ID,
        state=ContextBindingState.BOUND,
        context_revision=2,
        context=context or _context(),
        record_version=1,
        bound_at=NOW - timedelta(seconds=3),
        updated_at=NOW,
    )
    return replace(binding, **changes)


def _mirror(
    *,
    context: SessionContext | None = None,
    **changes: object,
) -> ParkingSessionMirror:
    mirror = ParkingSessionMirror(
        parking_session_id=SESSION_ID,
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        physical_vehicle_id=VEHICLE_ID,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=_observed(),
        context_revision=2,
        last_context=context or _context(),
        record_version=1,
        publication_revision=0,
        created_at=NOW - timedelta(seconds=3),
        updated_at=NOW,
    )
    return replace(mirror, **changes)


def _candidate(
    *,
    visit: ZoneVisit | None = None,
    vehicle: PhysicalVehicle | None | object = _DEFAULT_CANDIDATE_VALUE,
    binding: ContextBinding | None | object = _DEFAULT_CANDIDATE_VALUE,
    mirror: ParkingSessionMirror | None | object = _DEFAULT_CANDIDATE_VALUE,
) -> TofZoneVehicleCandidate:
    resolved_vehicle = (
        _vehicle()
        if vehicle is _DEFAULT_CANDIDATE_VALUE
        else cast(PhysicalVehicle | None, vehicle)
    )
    resolved_binding = (
        _binding()
        if binding is _DEFAULT_CANDIDATE_VALUE
        else cast(ContextBinding | None, binding)
    )
    resolved_mirror = (
        _mirror()
        if mirror is _DEFAULT_CANDIDATE_VALUE
        else cast(ParkingSessionMirror | None, mirror)
    )
    return TofZoneVehicleCandidate(
        visit=visit or _visit(),
        vehicle=resolved_vehicle,
        binding=resolved_binding,
        session_mirror=resolved_mirror,
    )


def _entry_match_attempt(
    *,
    physical_vehicle_id: PhysicalVehicleId = VEHICLE_ID,
    context: SessionContext | None = None,
) -> EntryMatchAttempt:
    authoritative_context = context or _context()
    return EntryMatchAttempt(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        match_state=EntryMatchState.MATCHED,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=1,
        matched_physical_vehicle_id=physical_vehicle_id,
        authoritative_session_id=authoritative_context.parking_session_id,
        authoritative_context=authoritative_context,
        match_deadline_at=NOW + timedelta(seconds=10),
        match_terminated_at=NOW,
        record_version=1,
        created_at=NOW - timedelta(seconds=3),
        updated_at=NOW,
    )


def _store_candidate_graph(
    connection: sqlite3.Connection,
    *,
    context: SessionContext,
    visit: ZoneVisit | None = None,
) -> tuple[ContextBinding, ParkingSessionMirror]:
    stored_visit = visit if visit is not None else _visit()
    binding = _binding(context=context)
    mirror = _mirror(context=context)

    with UnitOfWork(connection):
        PhysicalVehicleRepository(connection).ensure(_vehicle())
        EntryMatchAttemptRepository(connection).add(
            _entry_match_attempt(context=context)
        )
        ParkingSessionMirrorRepository(connection).add(mirror)
        ContextBindingRepository(connection).add(binding)
        ZoneVisitRepository(connection).add(stored_visit)

    return binding, mirror


def _projection_store(
    *visits: ZoneVisit,
    observed_at: datetime = NOW,
) -> LatestTofMonitoringProjectionStore:
    store = LatestTofMonitoringProjectionStore(
        target_zone_ids=(ZONE_ID, ZoneId(8)),
    )
    _publish_projection(store, *visits, observed_at=observed_at)
    return store


def _publish_projection(
    store: LatestTofMonitoringProjectionStore,
    *visits: ZoneVisit,
    observed_at: datetime = NOW,
    frame_id: int = 1,
) -> None:
    vehicle_ids = tuple(
        dict.fromkeys(visit.physical_vehicle_id for visit in visits)
    )
    store.publish(
        TofMonitoringProjectionUpdate(
            camera_id="camera-1",
            frame_id=frame_id,
            observed_at=observed_at,
            vehicles=tuple(
                TofVehicleObservationProjection(
                    physical_vehicle_id=physical_vehicle_id,
                    observation=_observed(observed_at),
                )
                for physical_vehicle_id in vehicle_ids
            ),
            zone_visits=visits,
        )
    )


def _repository_query(
    *visits: ZoneVisit,
    observed_at: datetime = NOW,
) -> RepositoryTofZoneAuthorizationQuery:
    return RepositoryTofZoneAuthorizationQuery(
        projection_store=_projection_store(
            *visits,
            observed_at=observed_at,
        ),
    )


class FakeQuery:
    def __init__(
        self,
        candidates: tuple[TofZoneVehicleCandidate, ...],
    ) -> None:
        self.candidates = candidates
        self.calls = 0

    def load_candidates(
        self,
        zone_id: ZoneId,
        *,
        connection: sqlite3.Connection,
    ) -> tuple[TofZoneVehicleCandidate, ...]:
        self.calls += 1
        assert zone_id == ZONE_ID
        return self.candidates


def _policy(**changes: object) -> TofAuthorizationPolicy:
    values: dict[str, object] = {
        "occupancy_freshness_seconds": 5.0,
        "monitoring_freshness_seconds": 5.0,
        "max_pre_occupancy_observation_seconds": 2.0,
    }
    values.update(changes)
    return TofAuthorizationPolicy(**values)


def _service(
    query: FakeQuery,
    zone_type: ZoneType = ZoneType.DISABLED,
) -> TofZoneAuthorizationService:
    return TofZoneAuthorizationService(
        zones=ZoneRegistry((_zone(zone_type),)),
        policy=_policy(),
        query=query,
    )


def _assess(
    query: FakeQuery,
    *,
    snapshot: ZoneOccupancySnapshot | None = None,
    zone_type: ZoneType = ZoneType.DISABLED,
    runtime: bool = True,
) -> TofZoneAuthorizationAssessment:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        return _service(query, zone_type).assess(
            snapshot or _snapshot(),
            sensor_runtime_available=runtime,
            evaluated_at=NOW,
            connection=connection,
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"occupancy_freshness_seconds": True},
        {"occupancy_freshness_seconds": 0.0},
        {"occupancy_freshness_seconds": math.nan},
        {"monitoring_freshness_seconds": True},
        {"monitoring_freshness_seconds": 0.0},
        {"monitoring_freshness_seconds": math.inf},
        {"max_pre_occupancy_observation_seconds": True},
        {"max_pre_occupancy_observation_seconds": -0.1},
        {"max_pre_occupancy_observation_seconds": math.nan},
    ],
)
def test_policy_rejects_invalid_values(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _policy(**changes)


def test_assessment_rejects_naive_timestamp_and_invalid_revisions() -> None:
    valid: dict[str, object] = {
        "sensor_id": "tof-zone-7",
        "zone_id": ZONE_ID,
        "zone_type": ZoneType.DISABLED,
        "occupancy_state": OccupancyState.OCCUPIED,
        "occupancy_revision": 1,
        "occupancy_stable_since": NOW,
        "occupancy_observation": _observed(),
        "zone_visit_id": None,
        "physical_vehicle_id": None,
        "parking_session_id": None,
        "context_revision": None,
        "decision": TofAuthorizationDecision.UNKNOWN,
        "reason": TofAuthorizationReason.VEHICLE_NOT_IDENTIFIED,
        "evaluated_at": NOW,
    }
    with pytest.raises(ValueError):
        TofZoneAuthorizationAssessment(
            **{**valid, "evaluated_at": NOW.replace(tzinfo=None)}
        )
    for field_name, value in (
        ("occupancy_revision", True),
        ("occupancy_revision", -1),
        ("assessment_revision", True),
        ("assessment_revision", -1),
    ):
        with pytest.raises(ValueError):
            TofZoneAuthorizationAssessment(**{**valid, field_name: value})


def test_assessment_rejects_invalid_decision_identity_combinations() -> None:
    common: dict[str, object] = {
        "sensor_id": "tof-zone-7",
        "zone_id": ZONE_ID,
        "zone_type": ZoneType.DISABLED,
        "occupancy_state": OccupancyState.OCCUPIED,
        "occupancy_revision": 1,
        "occupancy_stable_since": NOW,
        "occupancy_observation": _observed(),
        "zone_visit_id": None,
        "physical_vehicle_id": None,
        "parking_session_id": None,
        "context_revision": None,
        "evaluated_at": NOW,
    }
    with pytest.raises(ValueError):
        TofZoneAuthorizationAssessment(
            **common,
            decision=TofAuthorizationDecision.AUTHORIZED,
            reason=None,
        )
    with pytest.raises(ValueError):
        TofZoneAuthorizationAssessment(
            **common,
            decision=TofAuthorizationDecision.UNKNOWN,
            reason=None,
        )
    with pytest.raises(ValueError):
        TofZoneAuthorizationAssessment(**common, decision=None, reason=None)


@pytest.mark.parametrize(
    "visit_state",
    [
        ZoneVisitState.ENTERING,
        ZoneVisitState.INSIDE,
    ],
)
@pytest.mark.parametrize(
    ("zone_type", "disabled", "electric", "expected"),
    [
        (ZoneType.DISABLED, True, False, TofAuthorizationDecision.AUTHORIZED),
        (ZoneType.DISABLED, False, True, TofAuthorizationDecision.UNAUTHORIZED),
        (ZoneType.DISABLED, None, True, TofAuthorizationDecision.UNKNOWN),
        (ZoneType.EV_CHARGING, False, True, TofAuthorizationDecision.AUTHORIZED),
        (ZoneType.EV_CHARGING, True, False, TofAuthorizationDecision.UNAUTHORIZED),
        (ZoneType.EV_CHARGING, True, None, TofAuthorizationDecision.UNKNOWN),
    ],
)
def test_zone_qualification_uses_the_shared_zone_specific_policy(
    visit_state: ZoneVisitState,
    zone_type: ZoneType,
    disabled: bool | None,
    electric: bool | None,
    expected: TofAuthorizationDecision,
) -> None:
    visit = _visit(
        state=visit_state,
        entry_trusted_seconds=(
            0.0
            if visit_state is ZoneVisitState.ENTERING
            else 1.0
        ),
        entered_at=(
            None
            if visit_state is ZoneVisitState.ENTERING
            else NOW - timedelta(seconds=1)
        ),
    )
    context = _context(disabled=disabled, electric=electric)
    candidate = _candidate(
        visit=visit,
        binding=_binding(context=context),
        mirror=_mirror(context=context),
    )

    assessment = _assess(FakeQuery((candidate,)), zone_type=zone_type)

    assert assessment.decision is expected
    assert assessment.assessment_revision == 0
    assert assessment.reason is (
        TofAuthorizationReason.QUALIFICATION_UNAVAILABLE
        if expected is TofAuthorizationDecision.UNKNOWN
        else None
    )


def test_authorized_assessment_preserves_the_full_public_contract() -> None:
    snapshot = _snapshot()

    assessment = _assess(FakeQuery((_candidate(),)), snapshot=snapshot)

    assert assessment == TofZoneAuthorizationAssessment(
        sensor_id=snapshot.sensor_id,
        zone_id=ZONE_ID,
        zone_type=ZoneType.DISABLED,
        occupancy_state=OccupancyState.OCCUPIED,
        occupancy_revision=snapshot.revision,
        occupancy_stable_since=snapshot.stable_since,
        occupancy_observation=snapshot.observation,
        zone_visit_id=VISIT_ID,
        physical_vehicle_id=VEHICLE_ID,
        parking_session_id=SESSION_ID,
        context_revision=2,
        decision=TofAuthorizationDecision.AUTHORIZED,
        reason=None,
        evaluated_at=NOW,
        assessment_revision=0,
    )


@pytest.mark.parametrize(
    ("snapshot", "runtime", "decision", "reason"),
    [
        (
            _snapshot(state=OccupancyState.UNKNOWN),
            True,
            None,
            TofAuthorizationReason.OCCUPANCY_NOT_CONFIRMED,
        ),
        (
            _snapshot(state=OccupancyState.VACANT),
            True,
            None,
            TofAuthorizationReason.ZONE_VACANT,
        ),
        (
            _snapshot(),
            False,
            TofAuthorizationDecision.UNKNOWN,
            TofAuthorizationReason.SENSOR_RUNTIME_UNAVAILABLE,
        ),
        (
            _snapshot(state=OccupancyState.VACANT),
            False,
            None,
            TofAuthorizationReason.SENSOR_RUNTIME_UNAVAILABLE,
        ),
        (
            _snapshot(observation=_unreliable(ObservationState.DEGRADED)),
            True,
            TofAuthorizationDecision.UNKNOWN,
            TofAuthorizationReason.SENSOR_OBSERVATION_UNRELIABLE,
        ),
        (
            _snapshot(observation=_unreliable()),
            True,
            TofAuthorizationDecision.UNKNOWN,
            TofAuthorizationReason.SENSOR_OBSERVATION_UNRELIABLE,
        ),
        (
            _snapshot(observation=_observed(NOW - timedelta(seconds=5.001))),
            True,
            TofAuthorizationDecision.UNKNOWN,
            TofAuthorizationReason.SENSOR_OBSERVATION_STALE,
        ),
        (
            _snapshot(observation=_observed(NOW + timedelta(microseconds=1))),
            True,
            TofAuthorizationDecision.UNKNOWN,
            TofAuthorizationReason.TEMPORAL_MISMATCH,
        ),
    ],
)
def test_non_query_occupancy_and_sensor_paths(
    snapshot: ZoneOccupancySnapshot,
    runtime: bool,
    decision: TofAuthorizationDecision | None,
    reason: TofAuthorizationReason,
) -> None:
    query = FakeQuery((_candidate(),))

    assessment = _assess(query, snapshot=snapshot, runtime=runtime)

    assert assessment.decision is decision
    assert assessment.reason is reason
    assert query.calls == 0


def test_sensor_freshness_boundary_is_inclusive() -> None:
    assessment = _assess(
        FakeQuery((_candidate(),)),
        snapshot=_snapshot(observation=_observed(NOW - timedelta(seconds=5))),
    )

    assert assessment.decision is TofAuthorizationDecision.AUTHORIZED


def test_service_rejects_invalid_runtime_and_evaluation_time() -> None:
    service = _service(FakeQuery(()))
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        with pytest.raises(ValueError, match="sensor_runtime_available"):
            service.assess(
                _snapshot(),
                sensor_runtime_available=1,
                evaluated_at=NOW,
                connection=connection,
            )
        with pytest.raises(ValueError, match="evaluated_at"):
            service.assess(
                _snapshot(),
                sensor_runtime_available=True,
                evaluated_at=NOW.replace(tzinfo=None),
                connection=connection,
            )
    finally:
        connection.close()


def test_missing_zone_and_unsupported_zone() -> None:
    connection = sqlite3.connect(":memory:", isolation_level=None)
    query = FakeQuery(())
    try:
        missing_service = TofZoneAuthorizationService(
            zones=ZoneRegistry((_zone(ZoneType.DISABLED, ZoneId(8)),)),
            policy=_policy(),
            query=query,
        )
        missing = missing_service.assess(
            _snapshot(),
            sensor_runtime_available=True,
            evaluated_at=NOW,
            connection=connection,
        )
        assert missing.decision is None
        assert missing.reason is TofAuthorizationReason.ZONE_DEFINITION_UNAVAILABLE

        unsupported_service = TofZoneAuthorizationService(
            zones=ZoneRegistry((_zone(ZoneType.GENERAL),)),
            policy=_policy(),
            query=query,
        )
        with pytest.raises(ValueError):
            unsupported_service.assess(
                _snapshot(),
                sensor_runtime_available=True,
                evaluated_at=NOW,
                connection=connection,
            )
    finally:
        connection.close()


def test_candidate_cardinality_is_not_collapsed() -> None:
    no_candidate = _assess(FakeQuery(()))
    multiple = _assess(FakeQuery((_candidate(), _candidate())))

    assert no_candidate.reason is TofAuthorizationReason.VEHICLE_NOT_IDENTIFIED
    assert multiple.reason is TofAuthorizationReason.MULTIPLE_VEHICLE_CANDIDATES


def test_entering_candidate_is_not_selected_when_an_exiting_candidate_also_exists(
) -> None:
    entering_visit = _visit(
        state=ZoneVisitState.ENTERING,
        entry_trusted_seconds=0.0,
        entered_at=None,
    )
    exiting_visit = _visit(
        visit_id=ZoneVisitId(UUID(int=5)),
        physical_vehicle_id=PhysicalVehicleId(UUID(int=6)),
        state=ZoneVisitState.EXITING,
        exit_candidate_at=NOW,
    )

    assessment = _assess(
        FakeQuery(
            (
                _candidate(visit=entering_visit),
                _candidate(visit=exiting_visit),
            )
        )
    )

    assert assessment.decision is TofAuthorizationDecision.UNKNOWN
    assert assessment.reason is (
        TofAuthorizationReason.MULTIPLE_VEHICLE_CANDIDATES
    )
    assert assessment.zone_visit_id is None
    assert assessment.physical_vehicle_id is None


def test_entering_candidate_still_requires_reliable_visit_observation() -> None:
    candidate = _candidate(
        visit=_visit(
            state=ZoneVisitState.ENTERING,
            observation=_unreliable(),
            entry_trusted_seconds=0.0,
            entered_at=None,
        )
    )

    assessment = _assess(FakeQuery((candidate,)))

    assert assessment.decision is TofAuthorizationDecision.UNKNOWN
    assert assessment.reason is (
        TofAuthorizationReason.ZONE_VISIT_OBSERVATION_UNRELIABLE
    )


def test_entering_candidate_still_requires_an_active_session_binding() -> None:
    candidate = _candidate(
        visit=_visit(
            state=ZoneVisitState.ENTERING,
            entry_trusted_seconds=0.0,
            entered_at=None,
        ),
        binding=None,
        mirror=None,
    )

    assessment = _assess(FakeQuery((candidate,)))

    assert assessment.decision is TofAuthorizationDecision.UNKNOWN
    assert assessment.reason is (
        TofAuthorizationReason.CONTEXT_BINDING_UNAVAILABLE
    )


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (
            _candidate(
                visit=_visit(
                    state=ZoneVisitState.EXITING,
                    exit_candidate_at=NOW,
                )
            ),
            TofAuthorizationReason.ZONE_VISIT_NOT_CONFIRMED,
        ),
        (
            _candidate(visit=_visit(observation=_unreliable())),
            TofAuthorizationReason.ZONE_VISIT_OBSERVATION_UNRELIABLE,
        ),
        (
            _candidate(
                visit=_visit(
                    observation=_observed(NOW - timedelta(seconds=5.001))
                )
            ),
            TofAuthorizationReason.ZONE_VISIT_OBSERVATION_STALE,
        ),
        (
            _candidate(
                vehicle=_vehicle(
                    state=PhysicalVehicleState.RETIRED,
                    terminated_at=NOW,
                    termination_reason="EXIT_CONFIRMED",
                )
            ),
            TofAuthorizationReason.VEHICLE_NOT_ACTIVE,
        ),
        (
            _candidate(vehicle=_vehicle(observation=_unreliable())),
            TofAuthorizationReason.VEHICLE_OBSERVATION_UNRELIABLE,
        ),
        (
            _candidate(
                vehicle=_vehicle(
                    observation=_observed(NOW - timedelta(seconds=5.001))
                )
            ),
            TofAuthorizationReason.VEHICLE_OBSERVATION_STALE,
        ),
    ],
)
def test_visit_and_vehicle_validation(
    candidate: TofZoneVehicleCandidate,
    reason: TofAuthorizationReason,
) -> None:
    assessment = _assess(FakeQuery((candidate,)))

    assert assessment.decision is TofAuthorizationDecision.UNKNOWN
    assert assessment.reason is reason


def test_missing_physical_vehicle_is_unknown() -> None:
    assessment = _assess(FakeQuery((_candidate(vehicle=None),)))

    assert assessment.decision is TofAuthorizationDecision.UNKNOWN
    assert assessment.reason is TofAuthorizationReason.VEHICLE_STATE_UNAVAILABLE
    assert assessment.physical_vehicle_id == VEHICLE_ID


def test_pre_occupancy_temporal_boundary_is_inclusive() -> None:
    stable_since = NOW - timedelta(seconds=2)
    oldest_allowed = stable_since - timedelta(seconds=2)
    mismatch = _assess(
        FakeQuery(
            (
                _candidate(
                    visit=_visit(
                        observation=_observed(
                            oldest_allowed - timedelta(microseconds=1)
                        )
                    ),
                    vehicle=_vehicle(observation=_observed(NOW)),
                ),
            )
        ),
        snapshot=_snapshot(stable_since=stable_since),
    )
    accepted = _assess(
        FakeQuery(
            (
                _candidate(
                    visit=_visit(observation=_observed(oldest_allowed)),
                    vehicle=_vehicle(observation=_observed(NOW)),
                ),
            )
        ),
        snapshot=_snapshot(stable_since=stable_since),
    )

    assert mismatch.reason is TofAuthorizationReason.TEMPORAL_MISMATCH
    assert accepted.decision is TofAuthorizationDecision.AUTHORIZED
    assert accepted.reason is None


def test_long_occupied_period_accepts_recent_camera_observations() -> None:
    assessment = _assess(
        FakeQuery(
            (
                _candidate(
                    visit=_visit(observation=_observed(NOW)),
                    vehicle=_vehicle(observation=_observed(NOW)),
                ),
            )
        ),
        snapshot=_snapshot(stable_since=NOW - timedelta(seconds=30)),
    )

    assert assessment.decision is TofAuthorizationDecision.AUTHORIZED
    assert assessment.reason is None


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (
            _candidate(binding=None, mirror=None),
            TofAuthorizationReason.CONTEXT_BINDING_UNAVAILABLE,
        ),
        (
            _candidate(binding=_binding(), mirror=None),
            TofAuthorizationReason.SESSION_MIRROR_UNAVAILABLE,
        ),
        (
            _candidate(
                mirror=_mirror(
                    administrative_state=SessionAdministrativeState.CLOSED
                )
            ),
            TofAuthorizationReason.SESSION_CLOSED,
        ),
        (
            _candidate(
                mirror=_mirror(
                    physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
                    physical_vehicle_id=None,
                )
            ),
            TofAuthorizationReason.SESSION_PRESENCE_UNAVAILABLE,
        ),
        (
            _candidate(
                binding=_binding(
                    physical_vehicle_id=PhysicalVehicleId(UUID(int=99))
                )
            ),
            TofAuthorizationReason.SESSION_STATE_INCONSISTENT,
        ),
        (
            _candidate(
                mirror=_mirror(entry_attempt_id=EntryAttemptId(UUID(int=99)))
            ),
            TofAuthorizationReason.SESSION_STATE_INCONSISTENT,
        ),
        (
            _candidate(mirror=_mirror(context_revision=3)),
            TofAuthorizationReason.SESSION_STATE_INCONSISTENT,
        ),
        (
            _candidate(
                mirror=_mirror(context=_context(disabled=False, electric=False))
            ),
            TofAuthorizationReason.SESSION_STATE_INCONSISTENT,
        ),
    ],
)
def test_session_validation(
    candidate: TofZoneVehicleCandidate,
    reason: TofAuthorizationReason,
) -> None:
    assessment = _assess(FakeQuery((candidate,)))

    assert assessment.decision is TofAuthorizationDecision.UNKNOWN
    assert assessment.reason is reason


def test_closed_mirror_without_binding_preserves_diagnostic_session_id() -> None:
    assessment = _assess(
        FakeQuery(
            (
                _candidate(
                    binding=None,
                    mirror=_mirror(
                        administrative_state=SessionAdministrativeState.CLOSED
                    ),
                ),
            )
        )
    )

    assert assessment.decision is TofAuthorizationDecision.UNKNOWN
    assert assessment.reason is TofAuthorizationReason.SESSION_CLOSED
    assert assessment.parking_session_id == SESSION_ID
    assert assessment.context_revision is None


def test_repository_query_loads_the_complete_candidate_graph(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    context = _context()
    vehicle = _vehicle()
    visit = _visit()
    binding = _binding(context=context)
    mirror = _mirror(context=context)
    other_vehicle_id = PhysicalVehicleId(UUID(int=100))
    other_vehicle = replace(_vehicle(), physical_vehicle_id=other_vehicle_id)
    other_visit = replace(
        _visit(),
        visit_id=ZoneVisitId(UUID(int=101)),
        physical_vehicle_id=other_vehicle_id,
        zone_id=ZoneId(8),
    )

    try:
        with UnitOfWork(connection):
            vehicle_repository = PhysicalVehicleRepository(connection)
            vehicle_repository.ensure(vehicle)
            vehicle_repository.ensure(other_vehicle)
            EntryMatchAttemptRepository(connection).add(
                _entry_match_attempt(context=context)
            )
            ParkingSessionMirrorRepository(connection).add(mirror)
            ContextBindingRepository(connection).add(binding)
            visit_repository = ZoneVisitRepository(connection)
            visit_repository.add(other_visit)
            visit_repository.add(visit)

        candidates = _repository_query(visit, other_visit).load_candidates(
            ZONE_ID,
            connection=connection,
        )

        assert candidates == (
            TofZoneVehicleCandidate(
                visit=visit,
                vehicle=vehicle,
                binding=binding,
                session_mirror=mirror,
            ),
        )
        assert connection.in_transaction is False
    finally:
        connection.close()


def test_repository_query_does_not_fallback_to_durable_visit_observation(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            ZoneVisitRepository(connection).add(_visit())

        candidates = _repository_query().load_candidates(
            ZONE_ID,
            connection=connection,
        )

        assert candidates == ()
    finally:
        connection.close()


def test_repository_query_overlays_latest_projected_observations(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    stale_at = NOW - timedelta(seconds=10)
    durable_vehicle = _vehicle(observation=_observed(stale_at))
    durable_visit = _visit(observation=_observed(stale_at))
    projected_visit = replace(
        durable_visit,
        observation=_observed(NOW),
        updated_at=NOW,
        record_version=durable_visit.record_version + 1,
    )

    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(durable_vehicle)
            ZoneVisitRepository(connection).add(durable_visit)

        candidate, = _repository_query(projected_visit).load_candidates(
            ZONE_ID,
            connection=connection,
        )

        assert candidate.visit == projected_visit
        assert candidate.vehicle == replace(
            durable_vehicle,
            observation=_observed(NOW),
        )
    finally:
        connection.close()


def test_repository_query_preserves_zone_visit_order(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    first_visit = _visit(
        visit_id=ZoneVisitId(UUID(int=10)),
        physical_vehicle_id=PhysicalVehicleId(UUID(int=10)),
    )
    second_visit = _visit(
        visit_id=ZoneVisitId(UUID(int=20)),
        physical_vehicle_id=PhysicalVehicleId(UUID(int=20)),
    )

    try:
        with (
            patch.object(PhysicalVehicleRepository, "get", return_value=None),
            patch.object(
                ContextBindingRepository,
                "get_active_by_physical_vehicle_id",
                return_value=None,
            ),
            patch.object(
                ParkingSessionMirrorRepository,
                "get_exit_enabled_by_physical_vehicle_id",
                return_value=None,
            ),
        ):
            candidates = _repository_query(
                first_visit,
                second_visit,
            ).load_candidates(
                ZONE_ID,
                connection=connection,
            )

        assert tuple(candidate.visit for candidate in candidates) == (
            first_visit,
            second_visit,
        )
        assert connection.in_transaction is False
    finally:
        connection.close()


def test_repository_query_owns_successful_read_transaction(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        result = _repository_query().load_candidates(
            ZoneId(999),
            connection=connection,
        )

        assert result == ()
        assert connection.in_transaction is False
    finally:
        connection.close()


def test_repository_query_rolls_back_its_failed_transaction(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with patch.object(
            PhysicalVehicleRepository,
            "get",
            side_effect=RuntimeError("forced failure"),
        ):
            with pytest.raises(RuntimeError, match="forced failure"):
                _repository_query(_visit()).load_candidates(
                    ZONE_ID,
                    connection=connection,
                )

        assert connection.in_transaction is False
    finally:
        connection.close()


def test_repository_query_preserves_caller_owned_transaction(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        connection.execute("BEGIN")

        assert _repository_query().load_candidates(
            ZoneId(999),
            connection=connection,
        ) == ()
        assert connection.in_transaction is True
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def test_repository_query_does_not_roll_back_failed_caller_transaction(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        connection.execute("BEGIN")

        with patch.object(
            PhysicalVehicleRepository,
            "get",
            side_effect=RuntimeError("forced failure"),
        ):
            with pytest.raises(RuntimeError, match="forced failure"):
                _repository_query(_visit()).load_candidates(
                    ZONE_ID,
                    connection=connection,
                )

        assert connection.in_transaction is True
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def test_coordinator_reevaluates_when_durable_vehicle_context_arrives(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "jetson.db"
    setup_connection = open_database(database_path)
    current_snapshot = [_snapshot()]
    current_time = [NOW]
    published: list[TofZoneAuthorizationAssessment] = []

    def occupancy_snapshots() -> tuple[ZoneOccupancySnapshot, ...]:
        return (current_snapshot[0],)

    def clock() -> datetime:
        return current_time[0]

    projection_store = _projection_store()
    service = TofZoneAuthorizationService(
        zones=ZoneRegistry(
            (
                _zone(ZoneType.DISABLED),
            )
        ),
        policy=_policy(),
        query=RepositoryTofZoneAuthorizationQuery(
            projection_store=projection_store,
        ),
    )
    coordinator = TofZoneAuthorizationCoordinator(
        authorization_service=service,
        occupancy_snapshots=occupancy_snapshots,
        sensor_runtime_available=lambda: True,
        connection_factory=lambda: open_database(database_path),
        assessment_consumer=published.append,
        clock=clock,
    )

    try:
        coordinator.request_zone(ZONE_ID)
        first_run = coordinator.drain_pending()

        assert first_run.failures == ()
        assert len(first_run.published_assessments) == 1
        first = first_run.published_assessments[0]
        assert first.decision is TofAuthorizationDecision.UNKNOWN
        assert first.reason is TofAuthorizationReason.VEHICLE_NOT_IDENTIFIED
        assert first.assessment_revision == 1
        assert first.physical_vehicle_id is None
        assert first.parking_session_id is None
        assert setup_connection.in_transaction is False

        context = _context(disabled=True, electric=False)
        entering_visit = _visit(
            state=ZoneVisitState.ENTERING,
            entry_trusted_seconds=0.0,
            entered_at=None,
        )
        binding, _ = _store_candidate_graph(
            setup_connection,
            context=context,
            visit=entering_visit,
        )

        assert setup_connection.in_transaction is False

        current_time[0] = NOW + timedelta(seconds=1)
        _publish_projection(
            projection_store,
            replace(
                entering_visit,
                observation=_observed(current_time[0]),
                updated_at=current_time[0],
                record_version=entering_visit.record_version + 1,
            ),
            observed_at=current_time[0],
            frame_id=2,
        )
        current_snapshot[0] = replace(
            current_snapshot[0],
            revision=current_snapshot[0].revision + 1,
            observation=_observed(current_time[0]),
            last_input_at=current_time[0],
        )

        second_run = coordinator.reevaluate_after_monitoring_commit()

        assert second_run.failures == ()
        assert len(second_run.published_assessments) == 1
        second = second_run.published_assessments[0]
        assert second.decision is TofAuthorizationDecision.AUTHORIZED
        assert second.reason is None
        assert second.assessment_revision == 2
        assert second.zone_visit_id == VISIT_ID
        assert second.physical_vehicle_id == VEHICLE_ID
        assert second.parking_session_id == SESSION_ID
        assert second.context_revision == binding.context_revision
        assert second.occupancy_stable_since == first.occupancy_stable_since
        assert published == [first, second]
        assert [
            assessment.decision for assessment in published
        ] == [
            TofAuthorizationDecision.UNKNOWN,
            TofAuthorizationDecision.AUTHORIZED,
        ]
        assert [
            assessment.assessment_revision
            for assessment in published
        ] == [1, 2]
    finally:
        setup_connection.close()


def test_coordinator_reevaluates_when_session_qualification_is_updated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "jetson.db"
    setup_connection = open_database(database_path)
    current_snapshot = [_snapshot()]
    current_time = [NOW]
    published: list[TofZoneAuthorizationAssessment] = []

    def occupancy_snapshots() -> tuple[ZoneOccupancySnapshot, ...]:
        return (current_snapshot[0],)

    def clock() -> datetime:
        return current_time[0]

    service = TofZoneAuthorizationService(
        zones=ZoneRegistry(
            (
                _zone(ZoneType.DISABLED),
            )
        ),
        policy=_policy(),
        query=_repository_query(_visit()),
    )
    coordinator = TofZoneAuthorizationCoordinator(
        authorization_service=service,
        occupancy_snapshots=occupancy_snapshots,
        sensor_runtime_available=lambda: True,
        connection_factory=lambda: open_database(database_path),
        assessment_consumer=published.append,
        clock=clock,
    )

    try:
        initial_context = _context(disabled=None, electric=False)
        binding, mirror = _store_candidate_graph(
            setup_connection,
            context=initial_context,
        )

        assert binding.context == mirror.last_context
        assert binding.context_revision == mirror.context_revision
        assert setup_connection.in_transaction is False

        coordinator.request_zone(ZONE_ID)
        first_run = coordinator.drain_pending()

        assert first_run.failures == ()
        assert len(first_run.published_assessments) == 1
        first = first_run.published_assessments[0]
        assert first.decision is TofAuthorizationDecision.UNKNOWN
        assert first.reason is (
            TofAuthorizationReason.QUALIFICATION_UNAVAILABLE
        )
        assert first.assessment_revision == 1
        assert first.physical_vehicle_id == VEHICLE_ID
        assert first.parking_session_id == SESSION_ID
        assert first.context_revision == binding.context_revision

        current_time[0] = NOW + timedelta(seconds=1)
        updated_context = _context(disabled=True, electric=False)
        updated_binding = replace(
            binding,
            context=updated_context,
            context_revision=binding.context_revision + 1,
            record_version=binding.record_version + 1,
            updated_at=current_time[0],
        )
        updated_mirror = replace(
            mirror,
            last_context=updated_context,
            context_revision=mirror.context_revision + 1,
            record_version=mirror.record_version + 1,
            updated_at=current_time[0],
        )

        assert updated_binding.context == updated_mirror.last_context
        assert (
            updated_binding.context_revision
            == updated_mirror.context_revision
        )

        with UnitOfWork(setup_connection):
            ParkingSessionMirrorRepository(setup_connection).save(
                updated_mirror,
                expected_record_version=mirror.record_version,
            )
            ContextBindingRepository(setup_connection).save(
                updated_binding,
                expected_record_version=binding.record_version,
            )

        assert setup_connection.in_transaction is False

        current_snapshot[0] = replace(
            current_snapshot[0],
            revision=current_snapshot[0].revision + 1,
            observation=_observed(current_time[0]),
            last_input_at=current_time[0],
        )

        second_run = coordinator.reevaluate_after_monitoring_commit()

        assert second_run.failures == ()
        assert len(second_run.published_assessments) == 1
        second = second_run.published_assessments[0]
        assert second.decision is TofAuthorizationDecision.AUTHORIZED
        assert second.reason is None
        assert second.assessment_revision == 2
        assert second.physical_vehicle_id == VEHICLE_ID
        assert second.parking_session_id == SESSION_ID
        assert second.context_revision == updated_binding.context_revision
        assert second.occupancy_stable_since == first.occupancy_stable_since
        assert published == [first, second]
        assert [
            assessment.decision for assessment in published
        ] == [
            TofAuthorizationDecision.UNKNOWN,
            TofAuthorizationDecision.AUTHORIZED,
        ]
        assert [
            assessment.assessment_revision
            for assessment in published
        ] == [1, 2]
    finally:
        setup_connection.close()

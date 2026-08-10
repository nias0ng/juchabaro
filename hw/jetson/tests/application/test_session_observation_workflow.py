"""TrackingBatch → durable session correlation workflow 회귀 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.application.session_observation_workflow import SessionObservationWorkflow
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.session.context_binding_coordinator import (
    ContextBindingCoordinator,
    ContextBindingError,
)
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.database import open_database
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleAbsenceProgress,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    PhysicalVehicleState,
    TrackSegmentId,
    TrackingBatch,
    VehicleId,
)


T0 = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
ENTRY_BBOX = BoundingBox(0.25, 0.25, 0.35, 0.35)
OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=T0,
)


def _attempt_id(value: int) -> EntryAttemptId:
    return EntryAttemptId(UUID(int=value))


def _vehicle_id(value: int) -> PhysicalVehicleId:
    return PhysicalVehicleId(UUID(int=value))


def _context(session_id: int) -> SessionContext:
    return SessionContext(
        parking_session_id=ParkingSessionId(session_id),
        vehicle_id=VehicleId(session_id + 100),
        is_electric=True,
        is_disabled_vehicle=False,
    )


def _entry_coordinator() -> EntryMatchCoordinator:
    entry_zone = ZoneDefinition(
        zone_id=ZoneId(8),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="camera-1:v1",
        entry_exit_role=EntryExitRole.ENTRY,
    )
    return EntryMatchCoordinator(zones=ZoneRegistry([entry_zone]))


def _workflow(
    coordinator: EntryMatchCoordinator,
    *,
    absence_confirmation_seconds: float = 5.0,
    trusted_sample_max_gap_seconds: float = 1.0,
) -> SessionObservationWorkflow:
    return SessionObservationWorkflow(
        entry_match_coordinator=coordinator,
        context_binding_coordinator=ContextBindingCoordinator(
            id_factory=lambda: UUID(int=999),
        ),
        absence_confirmation_seconds=absence_confirmation_seconds,
        trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
    )


def _pending_attempt(
    coordinator: EntryMatchCoordinator,
    *,
    identity: int,
    decision: EntryDecisionState,
    session_id: int | None = None,
    created_at: datetime = T0,
    deadline_at: datetime | None = None,
) -> EntryMatchAttempt:
    context = None if session_id is None else _context(session_id)
    if decision is EntryDecisionState.REVIEW_ALLOW:
        review = coordinator.open_attempt(
            entry_attempt_id=_attempt_id(identity),
            decision_state=EntryDecisionState.REVIEW_PENDING,
            decision_revision=0,
            created_at=created_at,
            match_deadline_at=deadline_at or created_at + timedelta(seconds=10),
        )
        return coordinator.apply_decision(
            review,
            decision_state=EntryDecisionState.REVIEW_ALLOW,
            decision_revision=1,
            authoritative_context=context,
            updated_at=created_at,
        )

    return coordinator.open_attempt(
        entry_attempt_id=_attempt_id(identity),
        decision_state=decision,
        decision_revision=0,
        created_at=created_at,
        match_deadline_at=deadline_at or created_at + timedelta(seconds=10),
        authoritative_context=context,
    )


def _snapshot(
    vehicle_id: PhysicalVehicleId,
    *,
    track_id: int,
    observed_at: datetime,
) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=vehicle_id,
        track_segment_id=TrackSegmentId(track_id),
        bbox=ENTRY_BBOX,
        confidence=0.9,
        motion_signal=MotionSignal.MOVING,
        observed_at=observed_at,
        camera_id="camera-1",
        observation=ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=observed_at,
        ),
    )


def _batch(
    *snapshots: PhysicalVehicleSnapshot,
    observed_at: datetime,
    ended_track_segment_ids: tuple[TrackSegmentId, ...] = (),
    unobserved_physical_vehicle_ids: tuple[PhysicalVehicleId, ...] = (),
    not_present_confirmed_vehicle_ids: tuple[PhysicalVehicleId, ...] = (),
    not_present_confirmed_at: datetime | None = None,
    all_detections_tracked: bool = True,
) -> TrackingBatch:
    return TrackingBatch(
        camera_id="camera-1",
        frame_id=1,
        observed_at=observed_at,
        vehicles=tuple(snapshots),
        ended_track_segment_ids=ended_track_segment_ids,
        unobserved_physical_vehicle_ids=unobserved_physical_vehicle_ids,
        absence_progress=tuple(
            PhysicalVehicleAbsenceProgress(
                physical_vehicle_id=physical_vehicle_id,
                trusted_seconds=(
                    5.0
                    if physical_vehicle_id
                    in not_present_confirmed_vehicle_ids
                    else 0.0
                ),
                confirmed_at=(
                    not_present_confirmed_at or observed_at
                    if physical_vehicle_id
                    in not_present_confirmed_vehicle_ids
                    else None
                ),
            )
            for physical_vehicle_id in unobserved_physical_vehicle_ids
        ),
        observation=ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=observed_at,
        ),
        full_area_observed=True,
        all_detections_tracked=all_detections_tracked,
        not_present_confirmed_vehicle_ids=not_present_confirmed_vehicle_ids,
    )


def _add_attempt(connection, attempt: EntryMatchAttempt) -> None:
    with UnitOfWork(connection):
        EntryMatchAttemptRepository(connection).add(attempt)


@pytest.mark.parametrize(
    "decision",
    [EntryDecisionState.ALLOW, EntryDecisionState.REVIEW_ALLOW],
)
def test_authoritative_match_is_committed_with_vehicle_mirror_and_binding(
    tmp_path: Path,
    decision: EntryDecisionState,
) -> None:
    connection = open_database(tmp_path / f"{decision.value}.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=1,
        decision=decision,
        session_id=55,
    )
    vehicle_id = _vehicle_id(100)
    observed_at = T0 + timedelta(seconds=1)
    try:
        _add_attempt(connection, attempt)

        with UnitOfWork(connection):
            result = _workflow(coordinator).apply(
                _batch(
                    _snapshot(vehicle_id, track_id=10, observed_at=observed_at),
                    observed_at=observed_at,
                ),
                connection=connection,
            )
        contexts = result.session_contexts

        persisted_attempt = EntryMatchAttemptRepository(connection).get(
            attempt.entry_attempt_id
        )
        vehicle = PhysicalVehicleRepository(connection).get(vehicle_id)
        mirror = ParkingSessionMirrorRepository(connection).get(ParkingSessionId(55))
        (binding,) = ContextBindingRepository(connection).list_active()

        assert persisted_attempt is not None
        assert persisted_attempt.match_state is EntryMatchState.MATCHED
        assert persisted_attempt.matched_physical_vehicle_id == vehicle_id
        assert vehicle is not None
        assert vehicle.state is PhysicalVehicleState.ACTIVE
        assert mirror is not None
        assert mirror.physical_presence_state is PhysicalPresenceState.INSIDE
        assert mirror.physical_vehicle_id == vehicle_id
        assert binding.entry_attempt_id == attempt.entry_attempt_id
        assert binding.physical_vehicle_id == vehicle_id
        assert contexts == {vehicle_id: _context(55)}
        assert result.entry_attempt_ids == {
            vehicle_id: attempt.entry_attempt_id
        }
        assert result.entry_match_updates == (persisted_attempt,)
        assert connection.in_transaction is False
    finally:
        connection.close()


def test_review_allow_after_physical_match_creates_one_binding_on_next_batch(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "review-allow-backfill.db")
    coordinator = _entry_coordinator()
    review = _pending_attempt(
        coordinator,
        identity=10,
        decision=EntryDecisionState.REVIEW_PENDING,
    )
    vehicle_id = _vehicle_id(110)
    workflow = _workflow(coordinator)
    matched_at = T0 + timedelta(seconds=1)
    resolved_at = T0 + timedelta(seconds=2)
    try:
        _add_attempt(connection, review)
        workflow.process(
            _batch(
                _snapshot(vehicle_id, track_id=11, observed_at=matched_at),
                observed_at=matched_at,
            ),
            connection=connection,
        )
        matched = EntryMatchAttemptRepository(connection).get(review.entry_attempt_id)
        assert matched is not None
        assert matched.match_state is EntryMatchState.MATCHED
        assert ContextBindingRepository(connection).list_active() == ()

        resolved = coordinator.apply_decision(
            matched,
            decision_state=EntryDecisionState.REVIEW_ALLOW,
            decision_revision=1,
            authoritative_context=_context(66),
            updated_at=resolved_at,
        )
        with UnitOfWork(connection):
            EntryMatchAttemptRepository(connection).save(
                resolved,
                expected_record_version=matched.record_version,
            )

        contexts = workflow.process(
            _batch(
                _snapshot(vehicle_id, track_id=11, observed_at=resolved_at),
                observed_at=resolved_at,
            ),
            connection=connection,
        )
        (binding,) = ContextBindingRepository(connection).list_active()
        mirror = ParkingSessionMirrorRepository(connection).get(ParkingSessionId(66))

        assert binding.entry_attempt_id == review.entry_attempt_id
        assert binding.physical_vehicle_id == vehicle_id
        assert mirror is not None
        assert mirror.physical_presence_state is PhysicalPresenceState.INSIDE
        assert contexts == {vehicle_id: _context(66)}

        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=11,
                    observed_at=resolved_at + timedelta(seconds=1),
                ),
                observed_at=resolved_at + timedelta(seconds=1),
            ),
            connection=connection,
        )
        assert ContextBindingRepository(connection).list_active() == (binding,)
    finally:
        connection.close()


def test_conflict_disabled_mirror_does_not_repeat_binding_failure(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "disabled-correlation.db")
    coordinator = _entry_coordinator()
    pending = _pending_attempt(
        coordinator,
        identity=12,
        decision=EntryDecisionState.REVIEW_ALLOW,
        session_id=67,
    )
    vehicle_id = _vehicle_id(112)
    matched_at = T0 + timedelta(seconds=1)
    matched = coordinator.match_earliest(
        (pending,),
        observed_vehicle_bboxes={vehicle_id: ENTRY_BBOX},
        observed_at=matched_at,
    )
    assert matched is not None
    vehicle = PhysicalVehicle(
        physical_vehicle_id=vehicle_id,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0,
        absence_confirmation_seconds=5,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        created_at=T0,
        updated_at=matched_at,
    )
    mirror = ParkingSessionMirror(
        parking_session_id=ParkingSessionId(67),
        entry_attempt_id=matched.entry_attempt_id,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
        physical_observation=OBSERVED,
        context_revision=0,
        last_context=_context(67),
        exit_correlation_enabled=False,
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=matched_at,
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(vehicle)
            EntryMatchAttemptRepository(connection).add(matched)
            ParkingSessionMirrorRepository(connection).add(mirror)

        contexts = _workflow(coordinator).process(
            _batch(observed_at=T0 + timedelta(seconds=2)),
            connection=connection,
        )

        assert ContextBindingRepository(connection).list_active() == ()
        assert contexts == {}
        assert (
            ParkingSessionMirrorRepository(connection).get(ParkingSessionId(67))
            == mirror
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("administrative_state", "exit_correlation_enabled"),
    [
        (SessionAdministrativeState.CLOSED, True),
        (SessionAdministrativeState.ACTIVE, False),
    ],
)
def test_new_match_is_preserved_when_mirror_rejects_active_binding(
    tmp_path: Path,
    administrative_state: SessionAdministrativeState,
    exit_correlation_enabled: bool,
) -> None:
    connection = open_database(
        tmp_path
        / f"new-match-{administrative_state.value}-{exit_correlation_enabled}.db"
    )
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=13,
        decision=EntryDecisionState.ALLOW,
        session_id=68,
    )
    mirror = ParkingSessionMirror(
        parking_session_id=ParkingSessionId(68),
        entry_attempt_id=attempt.entry_attempt_id,
        administrative_state=administrative_state,
        physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
        physical_observation=OBSERVED,
        context_revision=0,
        last_context=_context(68),
        exit_correlation_enabled=exit_correlation_enabled,
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T0,
    )
    vehicle_id = _vehicle_id(113)
    observed_at = T0 + timedelta(seconds=1)
    try:
        with UnitOfWork(connection):
            EntryMatchAttemptRepository(connection).add(attempt)
            ParkingSessionMirrorRepository(connection).add(mirror)

        contexts = _workflow(coordinator).process(
            _batch(
                _snapshot(vehicle_id, track_id=13, observed_at=observed_at),
                observed_at=observed_at,
            ),
            connection=connection,
        )

        persisted_attempt = EntryMatchAttemptRepository(connection).get(
            attempt.entry_attempt_id
        )
        assert persisted_attempt is not None
        assert persisted_attempt.match_state is EntryMatchState.MATCHED
        assert persisted_attempt.matched_physical_vehicle_id == vehicle_id
        assert ContextBindingRepository(connection).list_active() == ()
        assert (
            ParkingSessionMirrorRepository(connection).get(ParkingSessionId(68))
            == mirror
        )
        assert contexts == {}
    finally:
        connection.close()


@pytest.mark.parametrize(
    "decision",
    [EntryDecisionState.REVIEW_PENDING, EntryDecisionState.DENY],
)
def test_review_or_deny_is_physically_matched_without_authoritative_binding(
    tmp_path: Path,
    decision: EntryDecisionState,
) -> None:
    connection = open_database(tmp_path / f"{decision.value}.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=2,
        decision=decision,
    )
    vehicle_id = _vehicle_id(200)
    observed_at = T0 + timedelta(seconds=1)
    try:
        _add_attempt(connection, attempt)

        contexts = _workflow(coordinator).process(
            _batch(
                _snapshot(vehicle_id, track_id=20, observed_at=observed_at),
                observed_at=observed_at,
            ),
            connection=connection,
        )

        persisted_attempt = EntryMatchAttemptRepository(connection).get(
            attempt.entry_attempt_id
        )
        assert persisted_attempt is not None
        assert persisted_attempt.match_state is EntryMatchState.MATCHED
        assert persisted_attempt.matched_physical_vehicle_id == vehicle_id
        assert ContextBindingRepository(connection).list_active() == ()
        assert contexts == {}
    finally:
        connection.close()


@pytest.mark.parametrize(
    "decision",
    [EntryDecisionState.REVIEW_PENDING, EntryDecisionState.DENY],
)
def test_already_matched_unbound_vehicle_does_not_consume_another_attempt(
    tmp_path: Path,
    decision: EntryDecisionState,
) -> None:
    connection = open_database(tmp_path / f"no-rematch-{decision.value}.db")
    coordinator = _entry_coordinator()
    first = _pending_attempt(
        coordinator,
        identity=20,
        decision=decision,
    )
    second = _pending_attempt(
        coordinator,
        identity=21,
        decision=EntryDecisionState.DENY,
        created_at=T0 + timedelta(microseconds=1),
    )
    vehicle_id = _vehicle_id(220)
    workflow = _workflow(coordinator)
    try:
        _add_attempt(connection, first)
        _add_attempt(connection, second)
        first_observed_at = T0 + timedelta(seconds=1)
        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=22,
                    observed_at=first_observed_at,
                ),
                observed_at=first_observed_at,
            ),
            connection=connection,
        )

        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=22,
                    observed_at=first_observed_at + timedelta(seconds=1),
                ),
                observed_at=first_observed_at + timedelta(seconds=1),
            ),
            connection=connection,
        )

        persisted_first = EntryMatchAttemptRepository(connection).get(
            first.entry_attempt_id
        )
        persisted_second = EntryMatchAttemptRepository(connection).get(
            second.entry_attempt_id
        )
        assert persisted_first is not None
        assert persisted_first.match_state is EntryMatchState.MATCHED
        assert persisted_second == second
    finally:
        connection.close()


def test_expired_attempt_is_saved_before_matching(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "expired.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=3,
        decision=EntryDecisionState.DENY,
        deadline_at=T0 + timedelta(seconds=1),
    )
    try:
        _add_attempt(connection, attempt)

        contexts = _workflow(coordinator).process(
            _batch(observed_at=T0 + timedelta(seconds=2)),
            connection=connection,
        )

        expired = EntryMatchAttemptRepository(connection).get(attempt.entry_attempt_id)
        assert expired is not None
        assert expired.match_state is EntryMatchState.EXPIRED
        assert expired.terminal_reason == "MATCH_DEADLINE_EXCEEDED"
        assert contexts == {}
    finally:
        connection.close()


def test_degraded_geometry_does_not_consume_pending_entry_attempt(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "degraded-no-match.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=30,
        decision=EntryDecisionState.DENY,
    )
    vehicle_id = _vehicle_id(300)
    observed_at = T0 + timedelta(seconds=1)
    snapshot = _snapshot(vehicle_id, track_id=30, observed_at=observed_at)
    degraded_observation = ObservationStatus(
        state=ObservationState.DEGRADED,
        reason=ObservationReason.PARTIAL_FRAME,
        last_reliable_observed_at=T0,
    )
    degraded_snapshot = replace(
        snapshot,
        motion_signal=MotionSignal.UNKNOWN,
        observation=degraded_observation,
    )
    degraded_batch = replace(
        _batch(degraded_snapshot, observed_at=observed_at),
        observation=degraded_observation,
        full_area_observed=False,
    )
    try:
        _add_attempt(connection, attempt)

        contexts = _workflow(coordinator).process(
            degraded_batch,
            connection=connection,
        )

        assert EntryMatchAttemptRepository(connection).get(attempt.entry_attempt_id) == attempt
        assert ContextBindingRepository(connection).list_active() == ()
        assert contexts == {}
    finally:
        connection.close()


def test_tentative_detection_prevents_entry_identity_guess(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "tentative-entry-no-match.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=31,
        decision=EntryDecisionState.DENY,
    )
    observed_at = T0 + timedelta(seconds=1)
    try:
        _add_attempt(connection, attempt)

        _workflow(coordinator).process(
            _batch(
                _snapshot(
                    _vehicle_id(310),
                    track_id=31,
                    observed_at=observed_at,
                ),
                observed_at=observed_at,
                all_detections_tracked=False,
            ),
            connection=connection,
        )

        assert (
            EntryMatchAttemptRepository(connection).get(attempt.entry_attempt_id)
            == attempt
        )
    finally:
        connection.close()


def test_track_end_unobserved_and_not_present_do_not_end_durable_scopes(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "non-terminal-signals.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=4,
        decision=EntryDecisionState.ALLOW,
        session_id=77,
    )
    vehicle_id = _vehicle_id(400)
    first_observed_at = T0 + timedelta(seconds=1)
    workflow = _workflow(coordinator)
    try:
        _add_attempt(connection, attempt)
        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=40,
                    observed_at=first_observed_at,
                ),
                observed_at=first_observed_at,
            ),
            connection=connection,
        )

        contexts = workflow.process(
            _batch(
                observed_at=T0 + timedelta(seconds=10),
                ended_track_segment_ids=(TrackSegmentId(40),),
                unobserved_physical_vehicle_ids=(vehicle_id,),
                not_present_confirmed_vehicle_ids=(vehicle_id,),
            ),
            connection=connection,
        )

        vehicle = PhysicalVehicleRepository(connection).get(vehicle_id)
        mirror = ParkingSessionMirrorRepository(connection).get(ParkingSessionId(77))
        (binding,) = ContextBindingRepository(connection).list_active()
        assert vehicle is not None
        assert vehicle.state is PhysicalVehicleState.ACTIVE
        assert vehicle.terminated_at is None
        assert vehicle.observation.state is ObservationState.UNKNOWN
        assert vehicle.observation.reason is ObservationReason.TRACK_LOST
        assert mirror is not None
        assert mirror.physical_presence_state is PhysicalPresenceState.INSIDE
        assert mirror.physical_observation == vehicle.observation
        assert binding.state.value == "BOUND"
        assert contexts == {}
    finally:
        connection.close()


def test_reobservation_resets_durable_absence_checkpoint(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "reobserved.db")
    coordinator = _entry_coordinator()
    vehicle_id = _vehicle_id(500)
    degraded = ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.TRACK_LOST,
        last_reliable_observed_at=T0,
    )
    checkpoint = PhysicalVehicle(
        physical_vehicle_id=vehicle_id,
        state=PhysicalVehicleState.ACTIVE,
        observation=degraded,
        absence_trusted_seconds=3.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
    )
    observed_at = T0 + timedelta(seconds=1)
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(checkpoint)

        _workflow(coordinator).process(
            _batch(
                _snapshot(vehicle_id, track_id=50, observed_at=observed_at),
                observed_at=observed_at,
            ),
            connection=connection,
        )

        persisted = PhysicalVehicleRepository(connection).get(vehicle_id)
        assert persisted is not None
        assert persisted.observation.state is ObservationState.OBSERVED
        assert persisted.absence_trusted_seconds == 0
        assert persisted.record_version == 2
    finally:
        connection.close()


def test_existing_vehicle_keeps_its_absence_policy_snapshot(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "absence-policy-snapshot.db")
    coordinator = _entry_coordinator()
    vehicle_id = _vehicle_id(5001)
    checkpoint = PhysicalVehicle(
        physical_vehicle_id=vehicle_id,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=10.0,
        trusted_sample_max_gap_seconds=2.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
    )
    observed_at = T0 + timedelta(seconds=1)
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(checkpoint)

        _workflow(
            coordinator,
            absence_confirmation_seconds=3.0,
            trusted_sample_max_gap_seconds=0.5,
        ).process(
            _batch(
                _snapshot(vehicle_id, track_id=5001, observed_at=observed_at),
                observed_at=observed_at,
            ),
            connection=connection,
        )

        persisted = PhysicalVehicleRepository(connection).get(vehicle_id)
        assert persisted is not None
        assert persisted.absence_confirmation_seconds == 10.0
        assert persisted.trusted_sample_max_gap_seconds == 2.0
    finally:
        connection.close()


def test_dirty_checkpoint_does_not_regress_last_reliable_observation(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "last-reliable-monotonic.db")
    coordinator = _entry_coordinator()
    workflow = _workflow(coordinator)
    vehicle_id = _vehicle_id(501)
    durable_observed_at = T0 + timedelta(seconds=1)
    latest_observed_at = T0 + timedelta(seconds=5)
    checkpoint = PhysicalVehicle(
        physical_vehicle_id=vehicle_id,
        state=PhysicalVehicleState.ACTIVE,
        observation=replace(
            OBSERVED,
            last_reliable_observed_at=durable_observed_at,
        ),
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=durable_observed_at,
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(checkpoint)

        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=501,
                    observed_at=latest_observed_at,
                ),
                observed_at=latest_observed_at,
            ),
            connection=connection,
        )
        workflow.process(
            _batch(
                observed_at=T0 + timedelta(seconds=6),
                unobserved_physical_vehicle_ids=(vehicle_id,),
            ),
            connection=connection,
        )

        persisted = PhysicalVehicleRepository(connection).get(vehicle_id)
        assert persisted is not None
        assert persisted.observation.state is ObservationState.UNKNOWN
        assert (
            persisted.observation.last_reliable_observed_at
            == latest_observed_at
        )
    finally:
        connection.close()


def test_absence_progress_uses_bounded_dirty_checkpoint_and_confirmation_flush(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "absence-dirty-checkpoint.db")
    coordinator = _entry_coordinator()
    workflow = _workflow(coordinator)
    vehicle_id = _vehicle_id(5010)
    first_observed_at = T0 + timedelta(seconds=1)

    def absence_batch(*, seconds: int, trusted_seconds: float, confirmed: bool = False):
        observed_at = T0 + timedelta(seconds=seconds)
        return replace(
            _batch(
                observed_at=observed_at,
                unobserved_physical_vehicle_ids=(vehicle_id,),
                not_present_confirmed_vehicle_ids=(vehicle_id,) if confirmed else (),
            ),
            absence_progress=(
                PhysicalVehicleAbsenceProgress(
                    physical_vehicle_id=vehicle_id,
                    trusted_seconds=trusted_seconds,
                    confirmed_at=observed_at if confirmed else None,
                ),
            ),
        )

    try:
        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=501,
                    observed_at=first_observed_at,
                ),
                observed_at=first_observed_at,
            ),
            connection=connection,
        )
        workflow.process(
            absence_batch(seconds=2, trusted_seconds=0.0),
            connection=connection,
        )
        workflow.process(
            absence_batch(seconds=5, trusted_seconds=3.0),
            connection=connection,
        )

        before_interval = PhysicalVehicleRepository(connection).get(vehicle_id)
        assert before_interval is not None
        assert before_interval.record_version == 2
        assert before_interval.absence_trusted_seconds == 0.0

        workflow.process(
            absence_batch(seconds=12, trusted_seconds=4.0),
            connection=connection,
        )
        interval_checkpoint = PhysicalVehicleRepository(connection).get(vehicle_id)
        assert interval_checkpoint is not None
        assert interval_checkpoint.record_version == 3
        assert interval_checkpoint.absence_trusted_seconds == 4.0

        workflow.process(
            absence_batch(seconds=13, trusted_seconds=5.0, confirmed=True),
            connection=connection,
        )
        confirmed_checkpoint = PhysicalVehicleRepository(connection).get(vehicle_id)
        assert confirmed_checkpoint is not None
        assert confirmed_checkpoint.record_version == 4
        assert confirmed_checkpoint.absence_trusted_seconds == 5.0
    finally:
        connection.close()


def test_repeated_observation_does_not_write_an_unchanged_vehicle_checkpoint(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "unchanged-observation.db")
    coordinator = _entry_coordinator()
    vehicle_id = _vehicle_id(501)
    workflow = _workflow(coordinator)
    first_observed_at = T0 + timedelta(seconds=1)
    second_observed_at = T0 + timedelta(seconds=2)
    try:
        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=51,
                    observed_at=first_observed_at,
                ),
                observed_at=first_observed_at,
            ),
            connection=connection,
        )
        first_checkpoint = PhysicalVehicleRepository(connection).get(vehicle_id)

        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=51,
                    observed_at=second_observed_at,
                ),
                observed_at=second_observed_at,
            ),
            connection=connection,
        )
        second_checkpoint = PhysicalVehicleRepository(connection).get(vehicle_id)

        assert first_checkpoint is not None
        assert second_checkpoint is not None
        assert second_checkpoint.record_version == first_checkpoint.record_version
        assert second_checkpoint.updated_at == first_checkpoint.updated_at
    finally:
        connection.close()


def test_repeated_observation_is_checkpointed_at_the_ten_second_bound(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "bounded-observation-checkpoint.db")
    coordinator = _entry_coordinator()
    vehicle_id = _vehicle_id(502)
    workflow = _workflow(coordinator)
    first_observed_at = T0 + timedelta(seconds=1)
    checkpointed_at = first_observed_at + timedelta(seconds=10)
    try:
        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=52,
                    observed_at=first_observed_at,
                ),
                observed_at=first_observed_at,
            ),
            connection=connection,
        )
        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=52,
                    observed_at=checkpointed_at,
                ),
                observed_at=checkpointed_at,
            ),
            connection=connection,
        )

        checkpoint = PhysicalVehicleRepository(connection).get(vehicle_id)
        assert checkpoint is not None
        assert checkpoint.record_version == 2
        assert checkpoint.updated_at == checkpointed_at
        assert checkpoint.observation.last_reliable_observed_at == checkpointed_at
    finally:
        connection.close()


def test_binding_uses_current_observation_between_durable_checkpoints(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "current-binding-observation.db")
    coordinator = _entry_coordinator()
    vehicle_id = _vehicle_id(503)
    workflow = _workflow(coordinator)
    first_observed_at = T0 + timedelta(seconds=1)
    matched_at = T0 + timedelta(seconds=5)
    attempt = _pending_attempt(
        coordinator,
        identity=503,
        decision=EntryDecisionState.ALLOW,
        session_id=503,
        created_at=T0 + timedelta(seconds=2),
    )
    try:
        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=53,
                    observed_at=first_observed_at,
                ),
                observed_at=first_observed_at,
            ),
            connection=connection,
        )
        _add_attempt(connection, attempt)

        workflow.process(
            _batch(
                _snapshot(
                    vehicle_id,
                    track_id=53,
                    observed_at=matched_at,
                ),
                observed_at=matched_at,
            ),
            connection=connection,
        )

        vehicle = PhysicalVehicleRepository(connection).get(vehicle_id)
        mirror = ParkingSessionMirrorRepository(connection).get(
            ParkingSessionId(503)
        )
        assert vehicle is not None
        assert vehicle.record_version == 1
        assert vehicle.observation.last_reliable_observed_at == first_observed_at
        assert mirror is not None
        assert mirror.physical_observation.last_reliable_observed_at == matched_at
    finally:
        connection.close()


def test_binding_failure_rolls_back_match_vehicle_and_mirror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = open_database(tmp_path / "rollback.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=6,
        decision=EntryDecisionState.ALLOW,
        session_id=88,
    )
    vehicle_id = _vehicle_id(600)
    observed_at = T0 + timedelta(seconds=1)

    def fail_add(_repository, _binding) -> None:
        raise RuntimeError("simulated binding write failure")

    try:
        _add_attempt(connection, attempt)
        monkeypatch.setattr(ContextBindingRepository, "add", fail_add)

        with pytest.raises(RuntimeError, match="simulated binding"):
            _workflow(coordinator).process(
                _batch(
                    _snapshot(vehicle_id, track_id=60, observed_at=observed_at),
                    observed_at=observed_at,
                ),
                connection=connection,
            )

        assert (
            EntryMatchAttemptRepository(connection).get(attempt.entry_attempt_id)
            == attempt
        )
        assert PhysicalVehicleRepository(connection).get(vehicle_id) is None
        assert (
            ParkingSessionMirrorRepository(connection).get(ParkingSessionId(88)) is None
        )
        assert connection.in_transaction is False
    finally:
        connection.close()


def test_existing_mirror_vehicle_correlation_is_not_overwritten(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "mirror-correlation-conflict.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=70,
        decision=EntryDecisionState.ALLOW,
        session_id=99,
    )
    original_vehicle_id = _vehicle_id(700)
    conflicting_vehicle_id = _vehicle_id(701)
    workflow = _workflow(coordinator)
    original_vehicle = PhysicalVehicle(
        physical_vehicle_id=original_vehicle_id,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0,
        absence_confirmation_seconds=5,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        created_at=T0,
        updated_at=T0,
    )
    original_mirror = ParkingSessionMirror(
        parking_session_id=ParkingSessionId(99),
        entry_attempt_id=attempt.entry_attempt_id,
        physical_vehicle_id=original_vehicle_id,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=OBSERVED,
        context_revision=0,
        last_context=_context(99),
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T0,
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(original_vehicle)
            EntryMatchAttemptRepository(connection).add(attempt)
            ParkingSessionMirrorRepository(connection).add(original_mirror)

        observed_at = T0 + timedelta(seconds=1)
        with pytest.raises(ContextBindingError, match="another PhysicalVehicle"):
            workflow.process(
                _batch(
                    _snapshot(
                        conflicting_vehicle_id,
                        track_id=71,
                        observed_at=observed_at,
                    ),
                    observed_at=observed_at,
                ),
                connection=connection,
            )

        assert (
            ParkingSessionMirrorRepository(connection).get(ParkingSessionId(99))
            == original_mirror
        )
        assert (
            EntryMatchAttemptRepository(connection).get(attempt.entry_attempt_id)
            == attempt
        )
        assert PhysicalVehicleRepository(connection).get(conflicting_vehicle_id) is None
    finally:
        connection.close()


def test_not_present_confirmation_blocks_late_review_allow_binding(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "late-review-after-departure.db")
    coordinator = _entry_coordinator()
    review = _pending_attempt(
        coordinator,
        identity=80,
        decision=EntryDecisionState.REVIEW_PENDING,
    )
    vehicle_id = _vehicle_id(800)
    workflow = _workflow(coordinator)
    matched_at = T0 + timedelta(seconds=1)
    resolved_at = T0 + timedelta(seconds=2)
    departed_at = T0 + timedelta(seconds=3)
    try:
        _add_attempt(connection, review)
        workflow.process(
            _batch(
                _snapshot(vehicle_id, track_id=80, observed_at=matched_at),
                observed_at=matched_at,
            ),
            connection=connection,
        )
        matched = EntryMatchAttemptRepository(connection).get(review.entry_attempt_id)
        assert matched is not None

        resolved = coordinator.apply_decision(
            matched,
            decision_state=EntryDecisionState.REVIEW_ALLOW,
            decision_revision=1,
            authoritative_context=_context(108),
            updated_at=resolved_at,
        )
        with UnitOfWork(connection):
            EntryMatchAttemptRepository(connection).save(
                resolved,
                expected_record_version=matched.record_version,
            )

        workflow.process(
            _batch(
                observed_at=departed_at,
                unobserved_physical_vehicle_ids=(vehicle_id,),
                not_present_confirmed_vehicle_ids=(vehicle_id,),
            ),
            connection=connection,
        )
        degraded_observation = ObservationStatus(
            state=ObservationState.DEGRADED,
            reason=ObservationReason.PARTIAL_FRAME,
            last_reliable_observed_at=departed_at,
        )
        with UnitOfWork(connection):
            result = workflow.apply(
                replace(
                    _batch(
                        observed_at=departed_at + timedelta(seconds=1),
                        unobserved_physical_vehicle_ids=(vehicle_id,),
                        not_present_confirmed_vehicle_ids=(vehicle_id,),
                        not_present_confirmed_at=departed_at,
                    ),
                    observation=degraded_observation,
                    full_area_observed=False,
                ),
                connection=connection,
            )

        assert ContextBindingRepository(connection).list_active() == ()
        assert result.historical_attempts == (resolved,)
        assert result.entry_attempt_ids == {
            vehicle_id: review.entry_attempt_id
        }
        assert (
            ParkingSessionMirrorRepository(connection).get(ParkingSessionId(108))
            is None
        )
    finally:
        connection.close()


def test_active_mirror_follows_observation_quality_change(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "mirror-observation-quality.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=81,
        decision=EntryDecisionState.ALLOW,
        session_id=109,
    )
    vehicle_id = _vehicle_id(810)
    workflow = _workflow(coordinator)
    bound_at = T0 + timedelta(seconds=1)
    degraded_at = T0 + timedelta(seconds=2)
    degraded_observation = ObservationStatus(
        state=ObservationState.DEGRADED,
        reason=ObservationReason.PARTIAL_FRAME,
        last_reliable_observed_at=bound_at,
    )
    degraded_snapshot = replace(
        _snapshot(vehicle_id, track_id=81, observed_at=degraded_at),
        motion_signal=MotionSignal.UNKNOWN,
        observation=degraded_observation,
    )
    try:
        _add_attempt(connection, attempt)
        workflow.process(
            _batch(
                _snapshot(vehicle_id, track_id=81, observed_at=bound_at),
                observed_at=bound_at,
            ),
            connection=connection,
        )

        workflow.process(
            replace(
                _batch(degraded_snapshot, observed_at=degraded_at),
                observation=degraded_observation,
                full_area_observed=False,
            ),
            connection=connection,
        )

        mirror = ParkingSessionMirrorRepository(connection).get(
            ParkingSessionId(109)
        )
        assert mirror is not None
        assert mirror.physical_observation == degraded_observation
        assert mirror.record_version == 2
    finally:
        connection.close()


def test_late_binding_preserves_newer_mirror_context(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "latest-mirror-context.db")
    coordinator = _entry_coordinator()
    pending = _pending_attempt(
        coordinator,
        identity=82,
        decision=EntryDecisionState.ALLOW,
        session_id=110,
    )
    vehicle_id = _vehicle_id(820)
    matched_at = T0 + timedelta(seconds=1)
    matched = replace(
        pending,
        match_state=EntryMatchState.MATCHED,
        matched_physical_vehicle_id=vehicle_id,
        match_terminated_at=matched_at,
        record_version=pending.record_version + 1,
        updated_at=matched_at,
    )
    vehicle = PhysicalVehicle(
        physical_vehicle_id=vehicle_id,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0,
        absence_confirmation_seconds=5,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        created_at=T0,
        updated_at=matched_at,
    )
    latest_context = replace(_context(110), is_electric=False)
    mirror = ParkingSessionMirror(
        parking_session_id=ParkingSessionId(110),
        entry_attempt_id=matched.entry_attempt_id,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
        physical_observation=OBSERVED,
        context_revision=2,
        last_context=latest_context,
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=matched_at,
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(vehicle)
            EntryMatchAttemptRepository(connection).add(matched)
            ParkingSessionMirrorRepository(connection).add(mirror)

        _workflow(coordinator).process(
            _batch(observed_at=T0 + timedelta(seconds=2)),
            connection=connection,
        )

        (binding,) = ContextBindingRepository(connection).list_active()
        persisted_mirror = ParkingSessionMirrorRepository(connection).get(
            ParkingSessionId(110)
        )
        assert binding.context_revision == 2
        assert binding.context == latest_context
        assert persisted_mirror is not None
        assert persisted_mirror.context_revision == 2
        assert persisted_mirror.last_context == latest_context
    finally:
        connection.close()


def test_multiple_entry_candidates_are_not_matched_by_snapshot_order(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "ambiguous-entry-candidates.db")
    coordinator = _entry_coordinator()
    attempt = _pending_attempt(
        coordinator,
        identity=83,
        decision=EntryDecisionState.DENY,
    )
    observed_at = T0 + timedelta(seconds=1)
    try:
        _add_attempt(connection, attempt)

        _workflow(coordinator).process(
            _batch(
                _snapshot(_vehicle_id(830), track_id=83, observed_at=observed_at),
                _snapshot(_vehicle_id(831), track_id=84, observed_at=observed_at),
                observed_at=observed_at,
            ),
            connection=connection,
        )

        assert (
            EntryMatchAttemptRepository(connection).get(attempt.entry_attempt_id)
            == attempt
        )
        assert ContextBindingRepository(connection).list_active() == ()
    finally:
        connection.close()

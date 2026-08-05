"""PendingHandoffWorkflow의 late correlation·retention 계약 테스트."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.application.pending_handoff_workflow import (
    HistoricalCorrelationResult,
    PendingHandoffWorkflow,
)
from src.application.physical_presence_workflow import (
    ABSENCE_WITHOUT_EXIT_EVIDENCE,
)
from src.application.session_observation_workflow import SessionObservationResult
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.models import (
    AssignmentState,
    Incident,
    IncidentId,
    IncidentKey,
    IncidentState,
    IncidentTransition,
    IncidentTransitionType,
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingPipelineResult,
    ParkingState,
    ParkingTransition,
    ParkingTransitionType,
    ZoneId,
)
from src.parking.parking_episode_tracker import MOVEMENT_CONFIRMED
from src.session.models import (
    ContextBinding,
    ContextBindingId,
    ContextBindingState,
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchAttempt,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalExitEvidence,
    PhysicalPresenceState,
    PhysicalTerminationOrigin,
    SessionAdministrativeState,
    SessionContext,
)
from src.storage.aggregate_repositories import (
    IncidentRepository,
    ParkingEpisodeRepository,
)
from src.storage.database import open_database
from src.storage.models import PendingHandoffState
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
    PendingHandoffRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    MotionSignal,
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
    VehicleId,
)


T0 = datetime(2026, 8, 2, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(seconds=10)
T2 = T0 + timedelta(seconds=20)
VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000021")
)
EPISODE_ID = ParkingEpisodeId(
    UUID("20000000-0000-4000-8000-000000000021")
)
INCIDENT_ID = IncidentId(
    UUID("25000000-0000-4000-8000-000000000021")
)
ATTEMPT_ID = EntryAttemptId(
    UUID("30000000-0000-4000-8000-000000000021")
)
SESSION_ID = ParkingSessionId(71)


OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=T0,
)
ABSENT = ObservationStatus(
    state=ObservationState.UNKNOWN,
    reason=ObservationReason.TRACK_LOST,
    last_reliable_observed_at=T0,
)


def _assignment() -> ParkingAssignment:
    return ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        zone_id=ZoneId(3),
        representative_footprint=(
            (0.1, 0.1),
            (0.2, 0.1),
            (0.2, 0.2),
            (0.1, 0.2),
        ),
        confidence=0.9,
        last_stable_at=T1,
    )


def _active_vehicle() -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=T0,
        updated_at=T0,
    )


def _retired_vehicle(
    termination_reason: str = "PHYSICAL_VEHICLE_LEFT",
) -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.RETIRED,
        observation=ABSENT,
        absence_trusted_seconds=5.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        absence_confirmed_at=T1,
        terminated_at=T1,
        termination_reason=termination_reason,
        record_version=2,
        created_at=T0,
        updated_at=T1,
    )


def _terminal_episode() -> ParkingEpisode:
    return ParkingEpisode(
        episode_id=EPISODE_ID,
        physical_vehicle_id=VEHICLE_ID,
        state=ParkingState.ENDED,
        observation=OBSERVED,
        stationary_trusted_seconds=10.0,
        movement_trusted_seconds=10.0,
        parking_confirmation_seconds=5.0,
        movement_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        last_signal=MotionSignal.MOVING,
        assignment=_assignment(),
        parked_at=T1,
        ended_at=T2,
        termination_reason=MOVEMENT_CONFIRMED,
        record_version=3,
        publication_revision=0,
        created_at=T0,
        updated_at=T2,
    )


def _context(
    session_id: ParkingSessionId = SESSION_ID,
) -> SessionContext:
    return SessionContext(
        parking_session_id=session_id,
        vehicle_id=VehicleId(8),
        is_electric=False,
        is_disabled_vehicle=False,
    )


def _matched_allow_attempt() -> EntryMatchAttempt:
    return EntryMatchAttempt(
        entry_attempt_id=ATTEMPT_ID,
        match_state=EntryMatchState.MATCHED,
        decision_state=EntryDecisionState.REVIEW_ALLOW,
        decision_revision=1,
        matched_physical_vehicle_id=VEHICLE_ID,
        authoritative_session_id=SESSION_ID,
        authoritative_context=_context(),
        match_terminated_at=T0,
        match_deadline_at=T1,
        record_version=2,
        created_at=T0,
        updated_at=T2,
    )


def _matched_deny_attempt() -> EntryMatchAttempt:
    return EntryMatchAttempt(
        entry_attempt_id=ATTEMPT_ID,
        match_state=EntryMatchState.MATCHED,
        decision_state=EntryDecisionState.DENY,
        decision_revision=0,
        matched_physical_vehicle_id=VEHICLE_ID,
        match_terminated_at=T0,
        match_deadline_at=T1,
        record_version=2,
        created_at=T0,
        updated_at=T0,
    )


def _inside_mirror(
    *,
    administrative_state: SessionAdministrativeState = (
        SessionAdministrativeState.ACTIVE
    ),
) -> ParkingSessionMirror:
    return ParkingSessionMirror(
        parking_session_id=SESSION_ID,
        entry_attempt_id=ATTEMPT_ID,
        physical_vehicle_id=VEHICLE_ID,
        administrative_state=administrative_state,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=OBSERVED,
        context_revision=1,
        last_context=_context(),
        record_version=1,
        publication_revision=0,
        created_at=T0,
        updated_at=T2,
    )


def _active_binding() -> ContextBinding:
    return ContextBinding(
        context_binding_id=ContextBindingId(
            UUID("35000000-0000-4000-8000-000000000021")
        ),
        entry_attempt_id=ATTEMPT_ID,
        parking_session_id=SESSION_ID,
        physical_vehicle_id=VEHICLE_ID,
        state=ContextBindingState.BOUND,
        context_revision=1,
        context=_context(),
        record_version=1,
        bound_at=T0,
        updated_at=T2,
    )


def _terminal_incident() -> Incident:
    return Incident(
        incident_id=INCIDENT_ID,
        key=IncidentKey.for_physical_vehicle(VEHICLE_ID, "BAD_PARKING"),
        physical_vehicle_id=VEHICLE_ID,
        state=IncidentState.RESOLVED,
        observation=OBSERVED,
        confirm_trusted_seconds=5.0,
        clear_trusted_seconds=5.0,
        confirm_duration_seconds=5.0,
        clear_duration_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        confirmed_at=T1,
        resolved_at=T2,
        terminated_at=T2,
        termination_reason="PREDICATE_CLEAR_CONFIRMED",
        record_version=3,
        publication_revision=0,
        first_observed_at=T0,
        created_at=T0,
        updated_at=T2,
    )


def _result(episode: ParkingEpisode) -> ParkingPipelineResult:
    return ParkingPipelineResult(
        zone_visit_updates=(),
        parking_episode_updates=(episode,),
        incident_transitions=(),
    )


def _incident_result(incident: Incident) -> ParkingPipelineResult:
    return ParkingPipelineResult(
        zone_visit_updates=(),
        parking_episode_updates=(),
        incident_updates=(incident,),
        incident_transitions=(),
    )


def test_terminal_parking_fact_materializes_in_original_revision_order(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "late-parking.db")
    workflow = PendingHandoffWorkflow()
    episode = _terminal_episode()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            ParkingEpisodeRepository(connection).add(episode)
            workflow.capture(_result(episode), connection=connection)

        markers = PendingHandoffRepository(connection).list_waiting()
        assert [marker.transition_type for marker in markers] == [
            ParkingTransitionType.PARKED.value,
            ParkingTransitionType.UNPARKED.value,
        ]
        assert [marker.original_occurred_at_us for marker in markers] == sorted(
            marker.original_occurred_at_us for marker in markers
        )

        with UnitOfWork(connection):
            materialized = workflow.materialize(
                SessionObservationResult(
                    session_contexts={VEHICLE_ID: _context()},
                    entry_attempt_ids={},
                ),
                HistoricalCorrelationResult({}, {}, ()),
                materialized_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        transitions = materialized.parking_result.parking_transitions
        assert [transition.transition_type for transition in transitions] == [
            ParkingTransitionType.PARKED,
            ParkingTransitionType.UNPARKED,
        ]
        assert [transition.publication_revision for transition in transitions] == [
            1,
            2,
        ]
        assert [transition.occurred_at for transition in transitions] == [T1, T2]
        persisted = ParkingEpisodeRepository(connection).get(EPISODE_ID)
        assert persisted is not None
        assert persisted.parking_session_id == SESSION_ID
        assert persisted.publication_revision == 2
        # outbox enqueue와 함께 mark하기 전이므로 marker는 아직 waiting이다.
        assert all(
            marker.workflow_state is PendingHandoffState.WAITING_CORRELATION
            for marker in PendingHandoffRepository(connection).list_waiting()
        )
    finally:
        connection.close()


def test_unobserved_active_binding_materializes_from_durable_correlation(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "durable-active-correlation.db")
    workflow = PendingHandoffWorkflow()
    episode = _terminal_episode()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            EntryMatchAttemptRepository(connection).add(
                _matched_allow_attempt()
            )
            ParkingSessionMirrorRepository(connection).add(_inside_mirror())
            ContextBindingRepository(connection).add(_active_binding())
            ParkingEpisodeRepository(connection).add(episode)
            workflow.capture(_result(episode), connection=connection)

        # 현재 frame의 observation/session map에 차량이 없어도
        # durable active binding이 authoritative correlation이다.
        with UnitOfWork(connection):
            materialized = workflow.materialize(
                SessionObservationResult({}, {}),
                HistoricalCorrelationResult({}, {}, ()),
                materialized_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        transitions = materialized.parking_result.parking_transitions
        assert [transition.transition_type for transition in transitions] == [
            ParkingTransitionType.PARKED,
            ParkingTransitionType.UNPARKED,
        ]
        persisted = ParkingEpisodeRepository(connection).get(EPISODE_ID)
        assert persisted is not None
        assert persisted.parking_session_id == SESSION_ID
        assert persisted.publication_revision == 2
    finally:
        connection.close()


def test_materialized_transitions_expose_global_occurred_at_revision_order(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "global-pending-order.db")
    workflow = PendingHandoffWorkflow()
    episode = _terminal_episode()
    incident = _terminal_incident()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            ParkingEpisodeRepository(connection).add(episode)
            IncidentRepository(connection).add(incident)
            workflow.capture(_result(episode), connection=connection)
            workflow.capture(_incident_result(incident), connection=connection)

        with UnitOfWork(connection):
            materialized = workflow.materialize(
                SessionObservationResult(
                    session_contexts={VEHICLE_ID: _context()},
                    entry_attempt_ids={VEHICLE_ID: ATTEMPT_ID},
                ),
                HistoricalCorrelationResult({}, {}, ()),
                materialized_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        ordered = materialized.ordered_transitions
        assert [transition.transition_type.value for transition in ordered] == [
            "OPEN",
            "PARKED",
            "RESOLVE",
            "UNPARKED",
        ]
        assert [
            (
                transition.publication_revision
                if isinstance(transition, ParkingTransition)
                else transition.incident.publication_revision
            )
            for transition in ordered
        ] == [1, 1, 2, 2]
        assert [
            isinstance(transition, IncidentTransition)
            for transition in ordered
        ] == [
            True,
            False,
            True,
            False,
        ]
    finally:
        connection.close()


def test_late_allow_after_retirement_creates_historical_exit_without_binding(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "historical-exit.db")
    workflow = PendingHandoffWorkflow()
    attempt = _matched_allow_attempt()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_retired_vehicle())
            EntryMatchAttemptRepository(connection).add(attempt)
            result = workflow.correlate_historical_sessions(
                (attempt,),
                observed_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        assert len(result.session_exit_transitions) == 1
        session_exit = result.session_exit_transitions[0]
        assert session_exit.parking_session_id == SESSION_ID
        assert session_exit.occurred_at == T1
        assert (
            session_exit.origin
            is PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
        )
        assert session_exit.evidence is PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL
        mirror = ParkingSessionMirrorRepository(connection).get(SESSION_ID)
        assert mirror is not None
        assert mirror.physical_vehicle_id == VEHICLE_ID
        assert mirror.physical_presence_state is PhysicalPresenceState.EXITED
        assert mirror.exited_at == T1
        assert mirror.physical_termination_origin is PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
        assert mirror.physical_exit_evidence is PhysicalExitEvidence.ENTRY_EXIT_TRAVERSAL
        assert ContextBindingRepository(connection).list_active() == ()

        with UnitOfWork(connection):
            repeated = workflow.correlate_historical_sessions(
                (attempt,),
                observed_at=T2 + timedelta(seconds=2),
                connection=connection,
            )
        assert repeated.session_exit_transitions == ()
    finally:
        connection.close()


def test_late_allow_after_absence_without_exit_evidence_creates_no_exit(
    tmp_path: Path,
) -> None:
    """출차 근거 없이 종료된 차량은 늦은 correlation에서도 출차로 만들지 않는다(565).

    이 경로에서는 통과 여부를 재계산할 수 없다 — 차량이 이미 RETIRED이고
    ZoneVisit도 함께 종료됐다. 그래서 departure 시점에 termination_reason으로
    영속한 값을 읽는다.
    """

    connection = open_database(tmp_path / "historical-no-evidence.db")
    workflow = PendingHandoffWorkflow()
    attempt = _matched_allow_attempt()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(
                _retired_vehicle(
                    termination_reason=ABSENCE_WITHOUT_EXIT_EVIDENCE,
                )
            )
            EntryMatchAttemptRepository(connection).add(attempt)
            result = workflow.correlate_historical_sessions(
                (attempt,),
                observed_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        assert result.session_exit_transitions == ()
        # 확인할 수 없는 출차 상태를 만들어 두지 않는다.
        assert ParkingSessionMirrorRepository(connection).get(SESSION_ID) is None
    finally:
        connection.close()


def test_retired_vehicle_disables_second_exited_session_correlation(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "duplicate-historical-exit.db")
    workflow = PendingHandoffWorkflow()
    attempt = _matched_allow_attempt()
    other_session_id = ParkingSessionId(70)
    existing_exit = ParkingSessionMirror(
        parking_session_id=other_session_id,
        physical_vehicle_id=VEHICLE_ID,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.EXITED,
        physical_observation=ABSENT,
        context_revision=0,
        last_context=_context(other_session_id),
        physical_termination_origin=(
            PhysicalTerminationOrigin.JETSON_EXIT_CONFIRMED
        ),
        physical_exit_evidence=PhysicalExitEvidence.FULL_AREA_ABSENCE,
        exited_at=T1,
        record_version=1,
        publication_revision=1,
        created_at=T0,
        updated_at=T1,
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_retired_vehicle())
            EntryMatchAttemptRepository(connection).add(attempt)
            ParkingSessionMirrorRepository(connection).add(existing_exit)

        with UnitOfWork(connection):
            result = workflow.correlate_historical_sessions(
                (attempt,),
                observed_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        assert result.session_exit_transitions == ()
        assert result.session_contexts == {}
        assert result.entry_attempt_ids == {}
        conflict = ParkingSessionMirrorRepository(connection).get(SESSION_ID)
        assert conflict is not None
        assert conflict.physical_presence_state is PhysicalPresenceState.UNCONFIRMED
        assert conflict.physical_vehicle_id is None
        assert conflict.exit_correlation_enabled is False
        assert (
            ParkingSessionMirrorRepository(connection).get(other_session_id)
            == existing_exit
        )

        with UnitOfWork(connection):
            repeated = workflow.correlate_historical_sessions(
                (attempt,),
                observed_at=T2 + timedelta(seconds=2),
                connection=connection,
            )
        assert repeated.session_exit_transitions == ()
        assert ParkingSessionMirrorRepository(connection).get(SESSION_ID) == conflict
    finally:
        connection.close()


def test_terminal_incident_materializes_open_then_resolve_by_entry_attempt(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "late-incident.db")
    workflow = PendingHandoffWorkflow()
    incident = _terminal_incident()
    attempt = _matched_deny_attempt()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            EntryMatchAttemptRepository(connection).add(attempt)
            IncidentRepository(connection).add(incident)
            workflow.capture(_incident_result(incident), connection=connection)

        with UnitOfWork(connection):
            materialized = workflow.materialize(
                SessionObservationResult(
                    session_contexts={},
                    entry_attempt_ids={VEHICLE_ID: ATTEMPT_ID},
                ),
                HistoricalCorrelationResult({}, {}, ()),
                materialized_at=T2 + timedelta(seconds=1),
                connection=connection,
            )

        transitions = materialized.parking_result.incident_transitions
        assert [transition.transition_type for transition in transitions] == [
            IncidentTransitionType.OPEN,
            IncidentTransitionType.RESOLVE,
        ]
        assert [
            transition.incident.publication_revision
            for transition in transitions
        ] == [1, 2]
        assert transitions[0].incident.state is IncidentState.OPEN
        assert transitions[1].incident.state is IncidentState.RESOLVED
        persisted = IncidentRepository(connection).get(INCIDENT_ID)
        assert persisted is not None
        assert persisted.entry_attempt_id == ATTEMPT_ID
        assert persisted.publication_revision == 2
    finally:
        connection.close()


def test_closed_withheld_session_does_not_prevent_terminal_marker_expiry(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "closed-withheld-expiry.db")
    workflow = PendingHandoffWorkflow()
    episode = _terminal_episode()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            EntryMatchAttemptRepository(connection).add(
                _matched_allow_attempt()
            )
            ParkingSessionMirrorRepository(connection).add(
                _inside_mirror(
                    administrative_state=SessionAdministrativeState.CLOSED
                )
            )
            ParkingEpisodeRepository(connection).add(episode)
            workflow.capture(_result(episode), connection=connection)

        with UnitOfWork(connection):
            withheld = workflow.materialize(
                SessionObservationResult({}, {}),
                HistoricalCorrelationResult({}, {}, ()),
                materialized_at=T2 + timedelta(seconds=1),
                connection=connection,
            )
        assert withheld.parking_result.parking_transitions == ()

        with UnitOfWork(connection):
            assert workflow.expire_due(
                now=T2 + timedelta(days=7, seconds=1),
                connection=connection,
            ) == 2

        rows = connection.execute(
            "SELECT workflow_state, disposition_reason FROM pending_handoffs"
        ).fetchall()
        assert {tuple(row) for row in rows} == {
            ("EXPIRED", "UNBOUND_CONTEXT_EXPIRED")
        }
        assert ParkingEpisodeRepository(connection).get(EPISODE_ID) == episode
    finally:
        connection.close()


def test_terminal_uncorrelated_marker_expires_without_changing_domain(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "pending-expiry.db")
    workflow = PendingHandoffWorkflow()
    episode = _terminal_episode()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            ParkingEpisodeRepository(connection).add(episode)
            workflow.capture(_result(episode), connection=connection)

        expiry_check = T2 + timedelta(days=7, seconds=1)
        with UnitOfWork(connection):
            assert workflow.expire_due(
                now=expiry_check,
                connection=connection,
            ) == 2

        rows = connection.execute(
            "SELECT workflow_state, disposition_reason FROM pending_handoffs"
        ).fetchall()
        assert {tuple(row) for row in rows} == {
            ("EXPIRED", "UNBOUND_CONTEXT_EXPIRED")
        }
        persisted = ParkingEpisodeRepository(connection).get(EPISODE_ID)
        assert persisted == episode
    finally:
        connection.close()


def test_ambiguous_matched_attempts_leave_incident_pending_until_expiry(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "ambiguous-incident-expiry.db")
    workflow = PendingHandoffWorkflow()
    incident = _terminal_incident()
    second_attempt = replace(
        _matched_deny_attempt(),
        entry_attempt_id=EntryAttemptId(
            UUID("30000000-0000-4000-8000-000000000022")
        ),
    )
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_active_vehicle())
            EntryMatchAttemptRepository(connection).add(
                _matched_allow_attempt()
            )
            EntryMatchAttemptRepository(connection).add(second_attempt)
            IncidentRepository(connection).add(incident)
            workflow.capture(_incident_result(incident), connection=connection)

        with UnitOfWork(connection):
            materialized = workflow.materialize(
                SessionObservationResult({}, {}),
                HistoricalCorrelationResult({}, {}, ()),
                materialized_at=T2 + timedelta(seconds=1),
                connection=connection,
            )
        assert materialized.parking_result.incident_transitions == ()

        with UnitOfWork(connection):
            assert workflow.expire_due(
                now=T2 + timedelta(days=7, seconds=1),
                connection=connection,
            ) == 2

        assert PendingHandoffRepository(connection).list_waiting() == ()
        persisted = IncidentRepository(connection).get(INCIDENT_ID)
        assert persisted is not None
        assert persisted.entry_attempt_id is None
        assert persisted.publication_revision == 0
    finally:
        connection.close()

"""EntryMatchCoordinator의 입차 decision·물리 매칭 축 분리 계약."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.diagnostics import DiagnosticEvent, DiagnosticEventType
from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.models import (
    EntryExitRole,
    ExitTraversalDefinition,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.session.entry_match_coordinator import (
    EntryMatchCoordinator,
    EntryMatchTransitionError,
    StaleEntryDecisionError,
)
from src.session.models import EntryAttemptId, EntryDecisionState, EntryMatchState, SessionContext
from src.tracking.models import BoundingBox, ParkingSessionId, PhysicalVehicleId, VehicleId


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
ENTRY_BBOX = BoundingBox(0.41, 0.41, 0.49, 0.49)
EXIT_BBOX = BoundingBox(0.61, 0.41, 0.69, 0.49)
FAR_BBOX = BoundingBox(0.8, 0.8, 0.9, 0.9)
OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=NOW,
)


class RecordingDiagnosticsSink:
    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)


def _attempt_id(value: int) -> EntryAttemptId:
    return EntryAttemptId(UUID(int=value))


def _vehicle_id(value: int) -> PhysicalVehicleId:
    return PhysicalVehicleId(UUID(int=value))


def _context(session_id: int = 55, *, electric: bool = True) -> SessionContext:
    return SessionContext(
        parking_session_id=ParkingSessionId(session_id),
        vehicle_id=VehicleId(10),
        is_electric=electric,
        is_disabled_vehicle=False,
    )


def _zones() -> ZoneRegistry:
    entry_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="camera-1:v1",
        entry_exit_role=EntryExitRole.ENTRY,
    )
    exit_zone = ZoneDefinition(
        zone_id=ZoneId(10),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.6, 0.4), (0.7, 0.4), (0.7, 0.5), (0.6, 0.5)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="camera-1:v1",
        entry_exit_role=EntryExitRole.EXIT,
        exit_traversal=ExitTraversalDefinition(
            line=((0.6, 0.45), (0.7, 0.45)),
            outward_point=(0.65, 0.4),
            hysteresis=0.0,
        ),
    )
    return ZoneRegistry([entry_zone, exit_zone])


def _coordinator(diagnostics_sink=None) -> EntryMatchCoordinator:
    return EntryMatchCoordinator(
        zones=_zones(),
        diagnostics_sink=diagnostics_sink,
    )


def _open(
    coordinator: EntryMatchCoordinator,
    *,
    identity: int = 1,
    created_at: datetime = NOW,
    decision_state: EntryDecisionState = EntryDecisionState.ALLOW,
    context: SessionContext | None = None,
):
    if context is None and decision_state is EntryDecisionState.ALLOW:
        context = _context()
    return coordinator.open_attempt(
        entry_attempt_id=_attempt_id(identity),
        decision_state=decision_state,
        decision_revision=1,
        created_at=created_at,
        match_deadline_at=created_at + timedelta(seconds=10),
        authoritative_context=context,
    )


def test_entry_overlap_threshold_cannot_make_zero_overlap_a_match() -> None:
    with pytest.raises(ValueError, match="greater than 0"):
        EntryMatchCoordinator(
            zones=_zones(),
            entry_zone_min_overlap_ratio=0.0,
        )


def test_open_attempt_uses_explicit_deadline_and_keeps_decision_separate() -> None:
    coordinator = _coordinator()

    attempt = _open(coordinator)

    assert attempt.match_state is EntryMatchState.PENDING
    assert attempt.decision_state is EntryDecisionState.ALLOW
    assert attempt.authoritative_session_id == ParkingSessionId(55)
    assert attempt.match_deadline_at == NOW + timedelta(seconds=10)


def test_review_resolution_cannot_open_a_new_attempt_without_review_pending() -> None:
    coordinator = _coordinator()

    with pytest.raises(EntryMatchTransitionError, match="existing REVIEW_PENDING"):
        _open(
            coordinator,
            decision_state=EntryDecisionState.REVIEW_ALLOW,
            context=_context(),
        )


def test_matches_earliest_eligible_attempt_in_entry_zone() -> None:
    diagnostics = RecordingDiagnosticsSink()
    coordinator = _coordinator(diagnostics)
    later = _open(coordinator, identity=2, created_at=NOW)
    earlier = _open(coordinator, identity=1, created_at=NOW - timedelta(seconds=3))

    matched = coordinator.match_earliest(
        (later, earlier),
        observed_vehicle_bboxes={_vehicle_id(100): ENTRY_BBOX},
        observed_at=NOW,
    )

    assert matched is not None
    assert matched.entry_attempt_id == earlier.entry_attempt_id
    assert matched.match_state is EntryMatchState.MATCHED
    assert matched.matched_physical_vehicle_id == _vehicle_id(100)
    assert matched.match_terminated_at == NOW
    assert matched.record_version == earlier.record_version + 1
    event = diagnostics.events[0]
    assert event.event_type is DiagnosticEventType.ENTRY_MATCH_EVALUATED
    assert event.attributes["result"] == "MATCHED"
    assert event.attributes["candidateCount"] == 1
    assert event.attributes["candidateZoneId"] == 9
    assert event.attributes["selectedEntryAttemptId"] == str(
        earlier.entry_attempt_id
    )


def test_review_and_deny_are_still_physically_matchable() -> None:
    coordinator = _coordinator()
    attempts = (
        _open(
            coordinator,
            identity=1,
            decision_state=EntryDecisionState.REVIEW_PENDING,
        ),
        _open(
            coordinator,
            identity=2,
            created_at=NOW + timedelta(seconds=1),
            decision_state=EntryDecisionState.DENY,
        ),
    )

    review_match = coordinator.match_earliest(
        attempts,
        observed_vehicle_bboxes={_vehicle_id(1): ENTRY_BBOX},
        observed_at=NOW,
    )
    deny_match = coordinator.match_earliest(
        (attempts[1],),
        observed_vehicle_bboxes={_vehicle_id(2): ENTRY_BBOX},
        observed_at=NOW + timedelta(seconds=1),
    )

    assert review_match is not None
    assert review_match.decision_state is EntryDecisionState.REVIEW_PENDING
    assert deny_match is not None
    assert deny_match.decision_state is EntryDecisionState.DENY


def test_does_not_match_outside_entry_zone_or_after_deadline() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)

    assert (
        coordinator.match_earliest(
            (attempt,),
            observed_vehicle_bboxes={_vehicle_id(1): FAR_BBOX},
            observed_at=NOW,
        )
        is None
    )
    assert (
        coordinator.match_earliest(
            (attempt,),
            observed_vehicle_bboxes={_vehicle_id(1): ENTRY_BBOX},
            observed_at=NOW + timedelta(seconds=11),
        )
        is None
    )


def test_exit_role_zone_does_not_consume_entry_attempt() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)

    matched = coordinator.match_earliest(
        (attempt,),
        observed_vehicle_bboxes={_vehicle_id(1): EXIT_BBOX},
        observed_at=NOW,
    )

    assert matched is None


def test_exit_role_vehicle_does_not_make_single_entry_candidate_ambiguous() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)

    matched = coordinator.match_earliest(
        (attempt,),
        observed_vehicle_bboxes={
            _vehicle_id(1): ENTRY_BBOX,
            _vehicle_id(2): EXIT_BBOX,
        },
        observed_at=NOW,
    )

    assert matched is not None
    assert matched.matched_physical_vehicle_id == _vehicle_id(1)


def test_multiple_entry_candidates_in_same_sample_are_held() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)

    first_order = coordinator.match_earliest(
        (attempt,),
        observed_vehicle_bboxes={
            _vehicle_id(1): ENTRY_BBOX,
            _vehicle_id(2): ENTRY_BBOX,
        },
        observed_at=NOW,
    )
    reversed_order = coordinator.match_earliest(
        (attempt,),
        observed_vehicle_bboxes={
            _vehicle_id(2): ENTRY_BBOX,
            _vehicle_id(1): ENTRY_BBOX,
        },
        observed_at=NOW,
    )

    assert first_order is None
    assert reversed_order is None


def test_vehicle_outside_entry_zone_does_not_make_single_entry_candidate_ambiguous() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)

    matched = coordinator.match_earliest(
        (attempt,),
        observed_vehicle_bboxes={
            _vehicle_id(1): ENTRY_BBOX,
            _vehicle_id(2): FAR_BBOX,
        },
        observed_at=NOW,
    )

    assert matched is not None
    assert matched.matched_physical_vehicle_id == _vehicle_id(1)


def test_expire_due_records_source_unavailable_instead_of_guessing_a_match() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)
    degraded = ObservationStatus(
        state=ObservationState.DEGRADED,
        reason=ObservationReason.CAMERA_UNAVAILABLE,
        last_reliable_observed_at=NOW,
    )

    (expired,) = coordinator.expire_due(
        (attempt,),
        observed_at=NOW + timedelta(seconds=11),
        observation=degraded,
    )

    assert expired.match_state is EntryMatchState.EXPIRED
    assert expired.terminal_reason == "SOURCE_UNAVAILABLE"
    assert expired.matched_physical_vehicle_id is None


def test_expire_due_uses_deadline_reason_when_observation_is_healthy() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)

    (expired,) = coordinator.expire_due(
        (attempt,),
        observed_at=NOW + timedelta(seconds=11),
        observation=OBSERVED,
    )

    assert expired.terminal_reason == "MATCH_DEADLINE_EXCEEDED"


def test_review_resolution_reuses_physical_match_and_adds_authoritative_context() -> None:
    coordinator = _coordinator()
    pending = _open(
        coordinator,
        decision_state=EntryDecisionState.REVIEW_PENDING,
    )
    matched = coordinator.match_earliest(
        (pending,),
        observed_vehicle_bboxes={_vehicle_id(7): ENTRY_BBOX},
        observed_at=NOW,
    )
    assert matched is not None

    resolved = coordinator.apply_decision(
        matched,
        decision_state=EntryDecisionState.REVIEW_ALLOW,
        decision_revision=2,
        authoritative_context=_context(session_id=77),
        updated_at=NOW + timedelta(seconds=1),
    )

    assert resolved.match_state is EntryMatchState.MATCHED
    assert resolved.matched_physical_vehicle_id == _vehicle_id(7)
    assert resolved.decision_state is EntryDecisionState.REVIEW_ALLOW
    assert resolved.authoritative_session_id == ParkingSessionId(77)


def test_decision_revision_distinguishes_retry_stale_and_conflict() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)

    retry = coordinator.apply_decision(
        attempt,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=1,
        authoritative_context=_context(),
        updated_at=NOW + timedelta(seconds=1),
    )
    assert retry is attempt

    with pytest.raises(StaleEntryDecisionError):
        coordinator.apply_decision(
            attempt,
            decision_state=EntryDecisionState.ALLOW,
            decision_revision=0,
            authoritative_context=_context(),
            updated_at=NOW + timedelta(seconds=1),
        )

    with pytest.raises(EntryMatchTransitionError, match="same decision_revision"):
        coordinator.apply_decision(
            attempt,
            decision_state=EntryDecisionState.ALLOW,
            decision_revision=1,
            authoritative_context=_context(electric=False),
            updated_at=NOW + timedelta(seconds=1),
        )

    with pytest.raises(EntryMatchTransitionError, match="only REVIEW_PENDING"):
        coordinator.apply_decision(
            attempt,
            decision_state=EntryDecisionState.REVIEW_DENY,
            decision_revision=2,
            updated_at=NOW + timedelta(seconds=1),
        )


def test_same_decision_retry_survives_later_physical_match_timestamp() -> None:
    coordinator = _coordinator()
    attempt = _open(coordinator)
    matched = coordinator.match_earliest(
        (attempt,),
        observed_vehicle_bboxes={_vehicle_id(1): ENTRY_BBOX},
        observed_at=NOW + timedelta(seconds=1),
    )
    assert matched is not None

    retried = coordinator.apply_decision(
        matched,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=attempt.decision_revision,
        authoritative_context=attempt.authoritative_context,
        updated_at=attempt.updated_at,
    )

    assert retried is matched

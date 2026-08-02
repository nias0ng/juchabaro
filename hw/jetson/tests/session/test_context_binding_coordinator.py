"""ContextBindingCoordinator의 authoritative correlation 계약."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.domain.models import ObservationState, ObservationStatus
from src.session.context_binding_coordinator import (
    ContextBindingCoordinator,
    ContextBindingError,
    StaleContextRevisionError,
)
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
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
    VehicleId,
)


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=NOW,
)


def _entry_attempt_id(value: int) -> EntryAttemptId:
    return EntryAttemptId(UUID(int=value))


def _physical_vehicle_id(value: int) -> PhysicalVehicleId:
    return PhysicalVehicleId(UUID(int=value))


def _context(session_id: int = 55, *, electric: bool = True) -> SessionContext:
    return SessionContext(
        parking_session_id=ParkingSessionId(session_id),
        vehicle_id=VehicleId(10),
        is_electric=electric,
        is_disabled_vehicle=False,
    )


def _attempt(
    *,
    identity: int = 1,
    physical_vehicle_id: PhysicalVehicleId | None = None,
    context: SessionContext | None = None,
    decision_state: EntryDecisionState = EntryDecisionState.ALLOW,
) -> EntryMatchAttempt:
    vehicle_id = physical_vehicle_id or _physical_vehicle_id(100)
    authoritative_context = context or _context()
    if decision_state not in {
        EntryDecisionState.ALLOW,
        EntryDecisionState.REVIEW_ALLOW,
    }:
        authoritative_context = None
    return EntryMatchAttempt(
        entry_attempt_id=_entry_attempt_id(identity),
        match_state=EntryMatchState.MATCHED,
        decision_state=decision_state,
        decision_revision=1,
        record_version=2,
        created_at=NOW,
        updated_at=NOW,
        match_deadline_at=NOW + timedelta(seconds=10),
        matched_physical_vehicle_id=vehicle_id,
        authoritative_session_id=(
            None
            if authoritative_context is None
            else authoritative_context.parking_session_id
        ),
        authoritative_context=authoritative_context,
        match_terminated_at=NOW,
    )


def _vehicle(physical_vehicle_id: PhysicalVehicleId | None = None) -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=physical_vehicle_id or _physical_vehicle_id(100),
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0,
        absence_confirmation_seconds=5,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _mirror(
    *,
    context: SessionContext | None = None,
    physical_vehicle_id: PhysicalVehicleId | None = None,
    administrative_state: SessionAdministrativeState = SessionAdministrativeState.ACTIVE,
) -> ParkingSessionMirror:
    session_context = context or _context()
    presence = (
        PhysicalPresenceState.UNCONFIRMED
        if physical_vehicle_id is None
        else PhysicalPresenceState.INSIDE
    )
    return ParkingSessionMirror(
        parking_session_id=session_context.parking_session_id,
        administrative_state=administrative_state,
        physical_presence_state=presence,
        physical_observation=OBSERVED,
        context_revision=0,
        record_version=1,
        publication_revision=0,
        created_at=NOW,
        updated_at=NOW,
        physical_vehicle_id=physical_vehicle_id,
        last_context=session_context,
    )


def _coordinator() -> ContextBindingCoordinator:
    return ContextBindingCoordinator(id_factory=lambda: UUID(int=999))


def test_binds_only_authoritative_attempt_to_active_vehicle_and_session() -> None:
    coordinator = _coordinator()
    attempt = _attempt()
    vehicle = _vehicle()

    binding = coordinator.bind(
        attempt=attempt,
        physical_vehicle=vehicle,
        session_mirror=_mirror(),
        existing_bindings=(),
        bound_at=NOW,
    )

    assert binding.entry_attempt_id == attempt.entry_attempt_id
    assert binding.parking_session_id == ParkingSessionId(55)
    assert binding.physical_vehicle_id == vehicle.physical_vehicle_id
    assert binding.context == _context()
    assert binding.state.value == "BOUND"


def test_binding_uses_latest_mirror_context_instead_of_entry_snapshot() -> None:
    coordinator = _coordinator()
    attempt = _attempt(context=_context(electric=True))
    latest_context = _context(electric=False)
    mirror = replace(
        _mirror(context=latest_context),
        context_revision=2,
    )

    binding = coordinator.bind(
        attempt=attempt,
        physical_vehicle=_vehicle(),
        session_mirror=mirror,
        existing_bindings=(),
        bound_at=NOW,
    )

    assert binding.context_revision == 2
    assert binding.context == latest_context


@pytest.mark.parametrize(
    "decision_state",
    [
        EntryDecisionState.REVIEW_PENDING,
        EntryDecisionState.DENY,
        EntryDecisionState.REVIEW_DENY,
        EntryDecisionState.REVIEW_EXPIRED,
    ],
)
def test_does_not_bind_non_authoritative_decisions(
    decision_state: EntryDecisionState,
) -> None:
    coordinator = _coordinator()

    with pytest.raises(ContextBindingError, match="ALLOW"):
        coordinator.bind(
            attempt=_attempt(decision_state=decision_state),
            physical_vehicle=_vehicle(),
            session_mirror=_mirror(),
            existing_bindings=(),
            bound_at=NOW,
        )


def test_does_not_bind_retired_vehicle_or_closed_session() -> None:
    coordinator = _coordinator()
    attempt = _attempt()
    retired = replace(
        _vehicle(),
        state=PhysicalVehicleState.RETIRED,
        terminated_at=NOW,
        termination_reason="NOT_PRESENT_CONFIRMED",
    )

    with pytest.raises(ContextBindingError, match="ACTIVE PhysicalVehicle"):
        coordinator.bind(
            attempt=attempt,
            physical_vehicle=retired,
            session_mirror=_mirror(),
            existing_bindings=(),
            bound_at=NOW,
        )

    with pytest.raises(ContextBindingError, match="closed session"):
        coordinator.bind(
            attempt=attempt,
            physical_vehicle=_vehicle(),
            session_mirror=_mirror(
                administrative_state=SessionAdministrativeState.CLOSED
            ),
            existing_bindings=(),
            bound_at=NOW,
        )


def test_bind_retry_returns_existing_binding_but_identity_conflict_is_rejected() -> None:
    coordinator = _coordinator()
    attempt = _attempt()
    vehicle = _vehicle()
    mirror = _mirror()
    binding = coordinator.bind(
        attempt=attempt,
        physical_vehicle=vehicle,
        session_mirror=mirror,
        existing_bindings=(),
        bound_at=NOW,
    )

    retry = coordinator.bind(
        attempt=attempt,
        physical_vehicle=vehicle,
        session_mirror=mirror,
        existing_bindings=(binding,),
        bound_at=NOW + timedelta(seconds=1),
    )
    assert retry is binding

    conflicting_attempt = _attempt(
        identity=2,
        physical_vehicle_id=_physical_vehicle_id(200),
    )
    with pytest.raises(ContextBindingError, match="session already"):
        coordinator.bind(
            attempt=conflicting_attempt,
            physical_vehicle=_vehicle(_physical_vehicle_id(200)),
            session_mirror=mirror,
            existing_bindings=(binding,),
            bound_at=NOW + timedelta(seconds=1),
        )


def test_context_update_changes_qualification_without_changing_binding_identity() -> None:
    coordinator = _coordinator()
    binding = coordinator.bind(
        attempt=_attempt(),
        physical_vehicle=_vehicle(),
        session_mirror=_mirror(),
        existing_bindings=(),
        bound_at=NOW,
    )
    changed_context = _context(electric=False)

    updated = coordinator.update_context(
        binding,
        context=changed_context,
        context_revision=1,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert updated.context_binding_id == binding.context_binding_id
    assert updated.entry_attempt_id == binding.entry_attempt_id
    assert updated.parking_session_id == binding.parking_session_id
    assert updated.physical_vehicle_id == binding.physical_vehicle_id
    assert updated.context == changed_context
    assert updated.record_version == binding.record_version + 1
    assert (
        coordinator.active_context_for((updated,), binding.physical_vehicle_id)
        == changed_context
    )


def test_context_revision_distinguishes_retry_stale_and_conflict() -> None:
    coordinator = _coordinator()
    binding = coordinator.bind(
        attempt=_attempt(),
        physical_vehicle=_vehicle(),
        session_mirror=_mirror(),
        existing_bindings=(),
        bound_at=NOW,
    )

    retry = coordinator.update_context(
        binding,
        context=binding.context,
        context_revision=0,
        updated_at=NOW + timedelta(seconds=1),
    )
    assert retry is binding

    later_snapshot = replace(binding, updated_at=NOW + timedelta(seconds=2))
    delayed_retry = coordinator.update_context(
        later_snapshot,
        context=binding.context,
        context_revision=0,
        updated_at=NOW,
    )
    assert delayed_retry is later_snapshot

    with pytest.raises(StaleContextRevisionError):
        coordinator.update_context(
            replace(binding, context_revision=1),
            context=binding.context,
            context_revision=0,
            updated_at=NOW + timedelta(seconds=1),
        )

    with pytest.raises(ContextBindingError, match="same context_revision"):
        coordinator.update_context(
            binding,
            context=_context(electric=False),
            context_revision=0,
            updated_at=NOW + timedelta(seconds=1),
        )


def test_admin_close_ends_binding_without_ending_physical_vehicle() -> None:
    coordinator = _coordinator()
    vehicle = _vehicle()
    binding = coordinator.bind(
        attempt=_attempt(),
        physical_vehicle=vehicle,
        session_mirror=_mirror(),
        existing_bindings=(),
        bound_at=NOW,
    )

    ended = coordinator.end(
        binding,
        ended_at=NOW + timedelta(seconds=1),
        reason="ADMIN_CLOSED",
    )

    assert ended.state.value == "ENDED"
    assert ended.termination_reason == "ADMIN_CLOSED"
    assert coordinator.active_context_for((ended,), vehicle.physical_vehicle_id) is None
    assert vehicle.state is PhysicalVehicleState.ACTIVE

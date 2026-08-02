"""Session frame workflow에 필요한 SQLite repository 회귀 테스트."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
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
from src.storage.database import open_database
from src.storage.repositories import (
    ContextBindingConflictError,
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    OptimisticConcurrencyError,
    ParkingSessionMirrorConflictError,
    ParkingSessionMirrorRepository,
    PhysicalVehicleConflictError,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import TransactionStateError, UnitOfWork
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
    VehicleId,
)


NOW = datetime(2026, 8, 2, 14, 30, 0, 123456, tzinfo=timezone.utc)
VEHICLE_ID = PhysicalVehicleId(UUID("10000000-0000-4000-8000-000000000001"))
ATTEMPT_ID = EntryAttemptId(UUID("20000000-0000-4000-8000-000000000001"))
BINDING_ID = ContextBindingId(UUID("30000000-0000-4000-8000-000000000001"))
SESSION_ID = ParkingSessionId(55)

OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=NOW,
)
DEGRADED = ObservationStatus(
    state=ObservationState.DEGRADED,
    reason=ObservationReason.TRACK_LOST,
    last_reliable_observed_at=NOW,
)


def _context() -> SessionContext:
    return SessionContext(
        parking_session_id=SESSION_ID,
        vehicle_id=VehicleId(77),
        is_electric=True,
        is_disabled_vehicle=False,
    )


def _vehicle() -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=OBSERVED,
        absence_trusted_seconds=0,
        absence_confirmation_seconds=4,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _attempt() -> EntryMatchAttempt:
    return EntryMatchAttempt(
        entry_attempt_id=ATTEMPT_ID,
        match_state=EntryMatchState.MATCHED,
        decision_state=EntryDecisionState.ALLOW,
        decision_revision=0,
        authoritative_session_id=SESSION_ID,
        authoritative_context=_context(),
        matched_physical_vehicle_id=VEHICLE_ID,
        match_terminated_at=NOW,
        match_deadline_at=NOW + timedelta(seconds=10),
        record_version=2,
        created_at=NOW,
        updated_at=NOW,
    )


def _mirror() -> ParkingSessionMirror:
    return ParkingSessionMirror(
        parking_session_id=SESSION_ID,
        entry_attempt_id=ATTEMPT_ID,
        physical_vehicle_id=VEHICLE_ID,
        administrative_state=SessionAdministrativeState.ACTIVE,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=OBSERVED,
        context_revision=0,
        last_context=_context(),
        record_version=1,
        publication_revision=0,
        created_at=NOW,
        updated_at=NOW,
    )


def _binding() -> ContextBinding:
    return ContextBinding(
        context_binding_id=BINDING_ID,
        entry_attempt_id=ATTEMPT_ID,
        parking_session_id=SESSION_ID,
        physical_vehicle_id=VEHICLE_ID,
        state=ContextBindingState.BOUND,
        context_revision=0,
        context=_context(),
        record_version=1,
        bound_at=NOW,
        updated_at=NOW,
    )


def _add_binding_dependencies(connection: sqlite3.Connection) -> None:
    PhysicalVehicleRepository(connection).ensure(_vehicle())
    EntryMatchAttemptRepository(connection).add(_attempt())
    ParkingSessionMirrorRepository(connection).add(_mirror())


def test_physical_vehicle_ensure_preserves_checkpoint_and_save_is_optimistic(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = PhysicalVehicleRepository(connection)
    vehicle = _vehicle()
    try:
        with pytest.raises(TransactionStateError):
            repository.ensure(vehicle)

        with UnitOfWork(connection):
            assert repository.ensure(vehicle) == vehicle
        assert repository.list_active() == (vehicle,)

        # ensure retry는 신규 관측치를 암묵적으로 checkpoint하지 않는다.
        changed_input = replace(
            vehicle,
            observation=DEGRADED,
            absence_trusted_seconds=1.25,
            updated_at=NOW + timedelta(seconds=1),
        )
        with UnitOfWork(connection):
            assert repository.ensure(changed_input) == vehicle

        with pytest.raises(PhysicalVehicleConflictError):
            with UnitOfWork(connection):
                repository.ensure(
                    replace(vehicle, absence_confirmation_seconds=5)
                )
        with pytest.raises(PhysicalVehicleConflictError):
            with UnitOfWork(connection):
                repository.ensure(
                    replace(vehicle, trusted_sample_max_gap_seconds=2)
                )

        checkpoint = replace(
            changed_input,
            record_version=2,
        )
        with pytest.raises(TransactionStateError):
            repository.save(checkpoint, expected_record_version=1)
        with UnitOfWork(connection):
            repository.save(checkpoint, expected_record_version=1)

        assert repository.get(VEHICLE_ID) == checkpoint
        confirmed_at = NOW + timedelta(seconds=4)
        confirmed = replace(
            checkpoint,
            absence_trusted_seconds=4,
            absence_confirmed_at=confirmed_at,
            record_version=3,
            updated_at=confirmed_at,
        )
        with UnitOfWork(connection):
            repository.save(confirmed, expected_record_version=2)
        assert repository.get(VEHICLE_ID) == confirmed

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.save(checkpoint, expected_record_version=1)
    finally:
        connection.close()


def test_parking_session_mirror_round_trip_conflict_and_optimistic_save(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = ParkingSessionMirrorRepository(connection)
    mirror = _mirror()
    try:
        with pytest.raises(TransactionStateError):
            repository.add(mirror)

        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            EntryMatchAttemptRepository(connection).add(_attempt())
            repository.add(mirror)

        assert repository.get(SESSION_ID) == mirror

        with pytest.raises(ParkingSessionMirrorConflictError):
            with UnitOfWork(connection):
                repository.add(mirror)

        closed = replace(
            mirror,
            administrative_state=SessionAdministrativeState.CLOSED,
            physical_observation=DEGRADED,
            context_revision=1,
            record_version=2,
            updated_at=NOW + timedelta(seconds=1),
        )
        with pytest.raises(TransactionStateError):
            repository.save(closed, expected_record_version=1)
        with UnitOfWork(connection):
            repository.save(closed, expected_record_version=1)
        assert repository.get(SESSION_ID) == closed

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.save(closed, expected_record_version=1)

        missing_parent = replace(
            mirror,
            parking_session_id=ParkingSessionId(999),
            entry_attempt_id=EntryAttemptId(
                UUID("20000000-0000-4000-8000-000000000099")
            ),
            physical_vehicle_id=None,
            physical_presence_state=PhysicalPresenceState.UNCONFIRMED,
            last_context=SessionContext(
                parking_session_id=ParkingSessionId(999),
                vehicle_id=None,
                is_electric=None,
                is_disabled_vehicle=None,
            ),
        )
        with pytest.raises(ParkingSessionMirrorConflictError):
            with UnitOfWork(connection):
                repository.add(missing_parent)
    finally:
        connection.close()


def test_context_binding_lists_only_active_and_translates_fk_conflict(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = ContextBindingRepository(connection)
    binding = _binding()
    try:
        with pytest.raises(TransactionStateError):
            repository.add(binding)

        with UnitOfWork(connection):
            _add_binding_dependencies(connection)
            repository.add(binding)

        assert repository.get(BINDING_ID) == binding
        assert repository.get_by_entry_attempt_id(binding.entry_attempt_id) == binding
        assert repository.list_active() == (binding,)

        with pytest.raises(ContextBindingConflictError):
            with UnitOfWork(connection):
                repository.add(binding)

        second_attempt_id = EntryAttemptId(
            UUID("20000000-0000-4000-8000-000000000002")
        )
        second_attempt = EntryMatchAttempt(
            entry_attempt_id=second_attempt_id,
            match_state=EntryMatchState.PENDING,
            decision_state=EntryDecisionState.DENY,
            decision_revision=0,
            record_version=1,
            created_at=NOW + timedelta(microseconds=1),
            updated_at=NOW + timedelta(microseconds=1),
            match_deadline_at=NOW + timedelta(seconds=10),
        )
        same_active_session = replace(
            binding,
            context_binding_id=ContextBindingId(
                UUID("30000000-0000-4000-8000-000000000002")
            ),
            entry_attempt_id=second_attempt_id,
        )
        with pytest.raises(ContextBindingConflictError):
            with UnitOfWork(connection):
                EntryMatchAttemptRepository(connection).add(second_attempt)
                repository.add(same_active_session)

        ended = replace(
            binding,
            state=ContextBindingState.ENDED,
            ended_at=NOW + timedelta(seconds=2),
            termination_reason="ADMIN_CLOSED",
            record_version=2,
            updated_at=NOW + timedelta(seconds=2),
        )
        with pytest.raises(TransactionStateError):
            repository.save(ended, expected_record_version=1)
        with UnitOfWork(connection):
            repository.save(ended, expected_record_version=1)

        assert repository.get(BINDING_ID) == ended
        assert repository.list_active() == ()
        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.save(ended, expected_record_version=1)

        missing_parent = replace(
            binding,
            context_binding_id=ContextBindingId(
                UUID("30000000-0000-4000-8000-000000000099")
            ),
            entry_attempt_id=EntryAttemptId(
                UUID("20000000-0000-4000-8000-000000000099")
            ),
        )
        with pytest.raises(ContextBindingConflictError):
            with UnitOfWork(connection):
                repository.add(missing_parent)
    finally:
        connection.close()

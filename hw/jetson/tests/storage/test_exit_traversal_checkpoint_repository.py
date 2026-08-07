"""Exit-traversal workflow checkpoint persistence and CAS tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import ZoneDefinitionVersion, ZoneId, ZoneVisitId
from src.storage import (
    ExitTraversalCheckpointConflictError,
    ExitTraversalCheckpointRecord,
    ExitTraversalCheckpointRepository,
    OptimisticConcurrencyError,
    TransactionStateError,
    UnitOfWork,
    open_database,
)
from src.storage.repositories import PhysicalVehicleRepository
from src.tracking.models import (
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


NOW = datetime(2026, 8, 7, 4, 30, 0, 123456, tzinfo=timezone.utc)
VEHICLE_ID = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000061")
)
VISIT_ID = ZoneVisitId(UUID("20000000-0000-4000-8000-000000000061"))


def _vehicle() -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=NOW,
        ),
        absence_trusted_seconds=0,
        absence_confirmation_seconds=30,
        trusted_sample_max_gap_seconds=1,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def _checkpoint() -> ExitTraversalCheckpointRecord:
    return ExitTraversalCheckpointRecord(
        physical_vehicle_id=VEHICLE_ID,
        exit_zone_id=ZoneId(12),
        exit_zone_visit_id=VISIT_ID,
        zone_definition_version=ZoneDefinitionVersion(7),
        outward_observed_at=NOW,
        reentry_candidate_at=None,
        reentry_trusted_seconds=0,
        reentry_confirmation_seconds=2,
        last_trusted_sample_at=None,
        record_version=1,
        updated_at=NOW,
    )


def test_checkpoint_model_rejects_incoherent_reentry_accumulation() -> None:
    checkpoint = _checkpoint()

    with pytest.raises(ValueError, match="requires reentry_candidate_at"):
        replace(checkpoint, reentry_trusted_seconds=0.25)
    with pytest.raises(ValueError, match="requires last_trusted_sample_at"):
        replace(
            checkpoint,
            reentry_candidate_at=NOW + timedelta(seconds=1),
            last_trusted_sample_at=None,
            updated_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValueError, match="at least one microsecond"):
        replace(checkpoint, reentry_confirmation_seconds=0.0000001)
    with pytest.raises(ValueError, match="cannot precede outward_observed_at"):
        replace(checkpoint, updated_at=NOW - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(checkpoint, outward_observed_at=NOW.replace(tzinfo=None))


def test_add_requires_uow_enforces_fk_and_survives_reopen(tmp_path: Path) -> None:
    database_path = tmp_path / "jetson.db"
    connection = open_database(database_path)
    repository = ExitTraversalCheckpointRepository(connection)
    checkpoint = _checkpoint()
    try:
        with pytest.raises(TransactionStateError):
            repository.add(checkpoint)

        with pytest.raises(ExitTraversalCheckpointConflictError, match="FK"):
            with UnitOfWork(connection):
                repository.add(checkpoint)

        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            repository.add(checkpoint)

        assert repository.get(VEHICLE_ID) == checkpoint

        conflicting_origin = replace(
            checkpoint,
            exit_zone_id=ZoneId(13),
            exit_zone_visit_id=ZoneVisitId(
                UUID("20000000-0000-4000-8000-000000000062")
            ),
        )
        with pytest.raises(ExitTraversalCheckpointConflictError):
            with UnitOfWork(connection):
                repository.add(conflicting_origin)
    finally:
        connection.close()

    reopened = open_database(database_path)
    try:
        assert ExitTraversalCheckpointRepository(reopened).get(VEHICLE_ID) == checkpoint
    finally:
        reopened.close()


def test_save_is_optimistic_and_origin_policy_is_immutable(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = ExitTraversalCheckpointRepository(connection)
    checkpoint = _checkpoint()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            repository.add(checkpoint)

        candidate_at = NOW + timedelta(seconds=1)
        accumulating = replace(
            checkpoint,
            reentry_candidate_at=candidate_at,
            reentry_trusted_seconds=0.125678,
            last_trusted_sample_at=candidate_at + timedelta(microseconds=125678),
            record_version=2,
            updated_at=candidate_at + timedelta(microseconds=125678),
        )
        with pytest.raises(TransactionStateError):
            repository.save(accumulating, expected_record_version=1)
        with UnitOfWork(connection):
            repository.save(accumulating, expected_record_version=1)
        assert repository.get(VEHICLE_ID) == accumulating

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.save(accumulating, expected_record_version=1)

        changed_origin = replace(
            accumulating,
            exit_zone_id=ZoneId(99),
            record_version=3,
            updated_at=accumulating.updated_at + timedelta(seconds=1),
        )
        with pytest.raises(
            ExitTraversalCheckpointConflictError,
            match="origin",
        ):
            with UnitOfWork(connection):
                repository.save(changed_origin, expected_record_version=2)

        changed_policy = replace(
            accumulating,
            reentry_confirmation_seconds=3,
            record_version=3,
            updated_at=accumulating.updated_at + timedelta(seconds=1),
        )
        with pytest.raises(
            ExitTraversalCheckpointConflictError,
            match="policy",
        ):
            with UnitOfWork(connection):
                repository.save(changed_policy, expected_record_version=2)
    finally:
        connection.close()


def test_delete_is_cas_and_rolls_back_with_outer_uow(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    repository = ExitTraversalCheckpointRepository(connection)
    checkpoint = _checkpoint()
    try:
        with UnitOfWork(connection):
            PhysicalVehicleRepository(connection).ensure(_vehicle())
            repository.add(checkpoint)

        with pytest.raises(TransactionStateError):
            repository.delete(VEHICLE_ID, expected_record_version=1)
        with pytest.raises(RuntimeError, match="rollback sentinel"):
            with UnitOfWork(connection):
                repository.delete(VEHICLE_ID, expected_record_version=1)
                raise RuntimeError("rollback sentinel")
        assert repository.get(VEHICLE_ID) == checkpoint

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.delete(VEHICLE_ID, expected_record_version=2)
        assert repository.get(VEHICLE_ID) == checkpoint

        with UnitOfWork(connection):
            repository.delete(VEHICLE_ID, expected_record_version=1)
        assert repository.get(VEHICLE_ID) is None

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.delete(VEHICLE_ID, expected_record_version=1)
    finally:
        connection.close()

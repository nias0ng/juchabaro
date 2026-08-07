"""Durable workflow checkpoint repository for observed exit traversal.

The checkpoint is deliberately separate from the public Parking/Session
aggregates. Its sole purpose is to bridge an observed outward traversal to a
later physical-absence decision across ZoneVisit termination and restarts.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from src.parking.models import ZoneDefinitionVersion, ZoneId, ZoneVisitId
from src.tracking.models import PhysicalVehicleId

from .codecs import (
    datetime_from_epoch_microseconds,
    datetime_to_epoch_microseconds,
    uuid_from_text,
    uuid_to_text,
)
from .models import ExitTraversalCheckpointRecord
from .repositories import OptimisticConcurrencyError, optimistic_update
from .unit_of_work import require_write_transaction


class ExitTraversalCheckpointConflictError(RuntimeError):
    """Checkpoint identity, immutable policy, or database contract conflicts."""


def _seconds_to_microseconds(value: float) -> int:
    return round(value * 1_000_000)


def _microseconds_to_seconds(value: int) -> float:
    return value / 1_000_000


def _optional_datetime_to_storage(value: datetime | None) -> int | None:
    return None if value is None else datetime_to_epoch_microseconds(value)


def _checkpoint_from_row(row: sqlite3.Row) -> ExitTraversalCheckpointRecord:
    return ExitTraversalCheckpointRecord(
        physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["physical_vehicle_id"]))
        ),
        exit_zone_id=ZoneId(int(row["exit_zone_id"])),
        exit_zone_visit_id=ZoneVisitId(
            uuid_from_text(str(row["exit_zone_visit_id"]))
        ),
        zone_definition_version=ZoneDefinitionVersion(
            int(row["zone_definition_version"])
        ),
        outward_observed_at=datetime_from_epoch_microseconds(
            int(row["outward_observed_at_us"])
        ),
        reentry_candidate_at=(
            datetime_from_epoch_microseconds(int(row["reentry_candidate_at_us"]))
            if row["reentry_candidate_at_us"] is not None
            else None
        ),
        reentry_trusted_seconds=_microseconds_to_seconds(
            int(row["reentry_trusted_duration_us"])
        ),
        reentry_confirmation_seconds=_microseconds_to_seconds(
            int(row["reentry_confirmation_duration_us"])
        ),
        last_trusted_sample_at=(
            datetime_from_epoch_microseconds(
                int(row["last_trusted_sample_at_us"])
            )
            if row["last_trusted_sample_at_us"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


class ExitTraversalCheckpointRepository:
    """Store one active exit-traversal latch per PhysicalVehicle.

    Writes never open their own transaction. ``add``, ``save``, and ``delete``
    must participate in the caller's UnitOfWork so checkpoint consumption can
    commit atomically with PhysicalVehicle/SessionExit state and its outbox.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> ExitTraversalCheckpointRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM exit_traversal_checkpoints
            WHERE physical_vehicle_id = ?
            """,
            (uuid_to_text(physical_vehicle_id),),
        ).fetchone()
        return _checkpoint_from_row(row) if row is not None else None

    def add(self, checkpoint: ExitTraversalCheckpointRecord) -> None:
        """Insert a newly latched traversal; an existing active latch conflicts."""

        require_write_transaction(self._connection)
        if checkpoint.record_version != 1:
            raise ValueError("new exit traversal checkpoint record_version must be 1")
        try:
            self._connection.execute(
                """
                INSERT INTO exit_traversal_checkpoints(
                    physical_vehicle_id, exit_zone_id, exit_zone_visit_id,
                    zone_definition_version, outward_observed_at_us,
                    reentry_candidate_at_us, reentry_trusted_duration_us,
                    reentry_confirmation_duration_us,
                    last_trusted_sample_at_us, record_version, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_text(checkpoint.physical_vehicle_id),
                    int(checkpoint.exit_zone_id),
                    uuid_to_text(checkpoint.exit_zone_visit_id),
                    int(checkpoint.zone_definition_version),
                    datetime_to_epoch_microseconds(
                        checkpoint.outward_observed_at
                    ),
                    _optional_datetime_to_storage(
                        checkpoint.reentry_candidate_at
                    ),
                    _seconds_to_microseconds(
                        checkpoint.reentry_trusted_seconds
                    ),
                    _seconds_to_microseconds(
                        checkpoint.reentry_confirmation_seconds
                    ),
                    _optional_datetime_to_storage(
                        checkpoint.last_trusted_sample_at
                    ),
                    checkpoint.record_version,
                    datetime_to_epoch_microseconds(checkpoint.updated_at),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ExitTraversalCheckpointConflictError(
                "exit traversal checkpoint violates identity, FK, or state contract"
            ) from error

    def save(
        self,
        checkpoint: ExitTraversalCheckpointRecord,
        *,
        expected_record_version: int,
    ) -> None:
        """Optimistically update only re-entry accumulation fields."""

        require_write_transaction(self._connection)
        if checkpoint.record_version != expected_record_version + 1:
            raise ValueError(
                "checkpoint.record_version must be exactly one greater than "
                "expected_record_version"
            )
        existing = self.get(checkpoint.physical_vehicle_id)
        if existing is None:
            raise OptimisticConcurrencyError(
                "exit traversal checkpoint is missing"
            )
        immutable_fields = (
            "exit_zone_id",
            "exit_zone_visit_id",
            "zone_definition_version",
            "outward_observed_at",
        )
        if any(
            getattr(checkpoint, field_name) != getattr(existing, field_name)
            for field_name in immutable_fields
        ) or _seconds_to_microseconds(
            checkpoint.reentry_confirmation_seconds
        ) != _seconds_to_microseconds(existing.reentry_confirmation_seconds):
            raise ExitTraversalCheckpointConflictError(
                "exit traversal origin and applied re-entry policy are immutable"
            )
        if checkpoint.updated_at < existing.updated_at:
            raise ExitTraversalCheckpointConflictError(
                "exit traversal checkpoint updated_at cannot move backwards"
            )

        try:
            new_version = optimistic_update(
                self._connection,
                table="exit_traversal_checkpoints",
                key_column="physical_vehicle_id",
                key_value=uuid_to_text(checkpoint.physical_vehicle_id),
                expected_record_version=expected_record_version,
                changes={
                    "reentry_candidate_at_us": _optional_datetime_to_storage(
                        checkpoint.reentry_candidate_at
                    ),
                    "reentry_trusted_duration_us": _seconds_to_microseconds(
                        checkpoint.reentry_trusted_seconds
                    ),
                    "last_trusted_sample_at_us": _optional_datetime_to_storage(
                        checkpoint.last_trusted_sample_at
                    ),
                    "updated_at_us": datetime_to_epoch_microseconds(
                        checkpoint.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise ExitTraversalCheckpointConflictError(
                "exit traversal checkpoint update violates the durable contract"
            ) from error
        if new_version != checkpoint.record_version:  # pragma: no cover
            raise RuntimeError(
                "optimistic update returned an unexpected record version"
            )

    def delete(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        *,
        expected_record_version: int,
    ) -> None:
        """CAS-delete a consumed or explicitly invalidated active latch."""

        require_write_transaction(self._connection)
        if expected_record_version < 1:
            raise ValueError("expected_record_version must be positive")
        cursor = self._connection.execute(
            """
            DELETE FROM exit_traversal_checkpoints
            WHERE physical_vehicle_id = ? AND record_version = ?
            """,
            (uuid_to_text(physical_vehicle_id), expected_record_version),
        )
        if cursor.rowcount != 1:
            raise OptimisticConcurrencyError(
                "exit traversal checkpoint is missing or has a newer version"
            )

"""Parking aggregate snapshot과 SQLite row를 연결하는 repository.

이 모듈은 ``ZoneVisit``, ``ParkingEpisode``, ``BlockingRelation``,
``Incident``의 영속 조회와
optimistic write만 담당한다. transaction은 호출 application이 ``UnitOfWork``로
소유하며, 공개 전이의 outbox 직렬화·enqueue도 같은 application
transaction에서 조정한다.

ParkingAssignment은 별도 aggregate가 아닌 ParkingEpisode의 값 객체이므로,
조회·제약에 필요한 column은 정규화하고 footprint만 canonical JSON
BLOB으로 보존한다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import UUID

from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.models import (
    AssignmentState,
    BlockingRelation,
    BlockingRelationId,
    BlockingRelationState,
    EgressAisleId,
    Incident,
    IncidentId,
    IncidentKey,
    IncidentKeyScope,
    IncidentState,
    NormalizedPolygon,
    ParkingAssignment,
    ParkingEpisode,
    ParkingEpisodeId,
    ParkingState,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneVisit,
    ZoneVisitId,
    ZoneVisitState,
)
from src.session.models import EntryAttemptId
from src.tracking.models import MotionSignal, ParkingSessionId, PhysicalVehicleId

from .codecs import (
    datetime_from_epoch_microseconds,
    datetime_to_epoch_microseconds,
    uuid_from_text,
    uuid_to_text,
)
from .repositories import OptimisticConcurrencyError, optimistic_update
from .unit_of_work import require_write_transaction


class ZoneVisitConflictError(RuntimeError):
    """ZoneVisit identity·scalar·cardinality가 durable row와 충돌했다."""


class ParkingEpisodeConflictError(RuntimeError):
    """ParkingEpisode identity·scalar·correlation이 durable row와 충돌했다."""


class BlockingRelationConflictError(RuntimeError):
    """BlockingRelation identity·scalar·cardinality가 durable row와 충돌했다."""


class IncidentConflictError(RuntimeError):
    """Incident identity·scalar·correlation이 durable row와 충돌했다."""


# [Shared codecs]


def _seconds_to_microseconds(value: float) -> int:
    """Domain의 초 단위를 schema의 정수 microseconds로 바꾼다."""

    return round(value * 1_000_000)


def _microseconds_to_seconds(value: int) -> float:
    return value / 1_000_000


def _optional_datetime_from_row(
    row: sqlite3.Row,
    column: str,
) -> datetime | None:
    value = row[column]
    return (
        datetime_from_epoch_microseconds(int(value))
        if value is not None
        else None
    )


def _optional_datetime_to_storage(value: datetime | None) -> int | None:
    return (
        datetime_to_epoch_microseconds(value)
        if value is not None
        else None
    )


def _observation_from_row(row: sqlite3.Row) -> ObservationStatus:
    reason = row["observation_reason"]
    return ObservationStatus(
        state=ObservationState(str(row["observation_state"])),
        reason=ObservationReason(str(reason)) if reason is not None else None,
        last_reliable_observed_at=_optional_datetime_from_row(
            row,
            "last_reliable_observed_at_us",
        ),
    )


def _observation_columns(
    observation: ObservationStatus,
) -> tuple[str, str | None, int | None]:
    return (
        observation.state.value,
        observation.reason.value if observation.reason is not None else None,
        _optional_datetime_to_storage(observation.last_reliable_observed_at),
    )


def _footprint_to_payload(footprint: NormalizedPolygon) -> bytes:
    """NormalizedPolygon을 결정적인 JSON bytes로 직렬화한다."""

    return json.dumps(
        [[float(x), float(y)] for x, y in footprint],
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _footprint_from_payload(
    payload: bytes | bytearray | memoryview,
) -> NormalizedPolygon:
    try:
        raw = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("invalid ParkingAssignment footprint payload") from error

    if not isinstance(raw, list) or len(raw) < 3:
        raise ValueError("ParkingAssignment footprint must contain at least three points")

    points: list[tuple[float, float]] = []
    for raw_point in raw:
        if not isinstance(raw_point, list) or len(raw_point) != 2:
            raise ValueError("ParkingAssignment footprint point must contain x and y")
        if any(
            isinstance(coordinate, bool)
            or not isinstance(coordinate, (int, float))
            for coordinate in raw_point
        ):
            raise ValueError("ParkingAssignment footprint coordinates must be numeric")
        points.append((float(raw_point[0]), float(raw_point[1])))
    return tuple(points)


def _assignment_columns(
    assignment: ParkingAssignment | None,
) -> dict[str, object | None]:
    if assignment is None:
        return {
            "assignment_state": None,
            "assignment_zone_id": None,
            "assignment_unassigned_reason": None,
            "representative_footprint": None,
            "assignment_confidence": None,
            "assignment_last_stable_at_us": None,
        }
    return {
        "assignment_state": assignment.state.value,
        "assignment_zone_id": (
            int(assignment.zone_id) if assignment.zone_id is not None else None
        ),
        "assignment_unassigned_reason": assignment.unassigned_reason,
        "representative_footprint": _footprint_to_payload(
            assignment.representative_footprint
        ),
        "assignment_confidence": assignment.confidence,
        "assignment_last_stable_at_us": datetime_to_epoch_microseconds(
            assignment.last_stable_at
        ),
    }


def _assignment_from_row(row: sqlite3.Row) -> ParkingAssignment | None:
    state_value = row["assignment_state"]
    if state_value is None:
        return None

    footprint_payload = row["representative_footprint"]
    confidence = row["assignment_confidence"]
    last_stable_at_us = row["assignment_last_stable_at_us"]
    if footprint_payload is None or confidence is None or last_stable_at_us is None:
        raise ValueError("persisted ParkingAssignment metadata is incomplete")

    return ParkingAssignment(
        state=AssignmentState(str(state_value)),
        zone_id=(
            ZoneId(int(row["assignment_zone_id"]))
            if row["assignment_zone_id"] is not None
            else None
        ),
        unassigned_reason=(
            str(row["assignment_unassigned_reason"])
            if row["assignment_unassigned_reason"] is not None
            else None
        ),
        representative_footprint=_footprint_from_payload(footprint_payload),
        confidence=float(confidence),
        last_stable_at=datetime_from_epoch_microseconds(int(last_stable_at_us)),
    )


def _require_advanced_record_version(
    *,
    aggregate_name: str,
    record_version: int,
    expected_record_version: int,
) -> None:
    if record_version <= expected_record_version:
        raise ValueError(
            f"{aggregate_name}.record_version must be greater than "
            "expected_record_version"
        )


def _require_not_reactivated(
    *,
    aggregate_name: str,
    existing_state: object,
    incoming_state: object,
    terminal_states: set[object],
    error_type: type[Exception],
) -> None:
    if existing_state in terminal_states and incoming_state != existing_state:
        raise error_type(
            f"terminal {aggregate_name} cannot be reactivated or change terminal state"
        )


def _raise_missing_for_update(
    aggregate_name: str,
    aggregate_id: object,
) -> None:
    raise OptimisticConcurrencyError(
        f"{aggregate_name} {aggregate_id!r} is missing or has a newer version"
    )


def _require_fill_only(
    *,
    aggregate_name: str,
    field_name: str,
    existing: object | None,
    incoming: object | None,
    error_type: type[RuntimeError],
) -> None:
    """Nullable correlation은 한 번 채운 뒤 변경·제거할 수 없다."""

    if existing is not None and incoming != existing:
        raise error_type(f"{aggregate_name} {field_name} may only be filled once")


# [Row mappers]


def _zone_visit_from_row(row: sqlite3.Row) -> ZoneVisit:
    return ZoneVisit(
        visit_id=ZoneVisitId(uuid_from_text(str(row["zone_visit_id"]))),
        physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["physical_vehicle_id"]))
        ),
        zone_id=ZoneId(int(row["zone_id"])),
        zone_definition_version=ZoneDefinitionVersion(
            int(row["zone_definition_version"])
        ),
        state=ZoneVisitState(str(row["domain_state"])),
        observation=_observation_from_row(row),
        entry_trusted_seconds=_microseconds_to_seconds(
            int(row["entry_trusted_duration_us"])
        ),
        exit_trusted_seconds=_microseconds_to_seconds(
            int(row["exit_trusted_duration_us"])
        ),
        entry_confirmation_seconds=_microseconds_to_seconds(
            int(row["entry_confirmation_duration_us"])
        ),
        exit_confirmation_seconds=_microseconds_to_seconds(
            int(row["exit_confirmation_duration_us"])
        ),
        trusted_sample_max_gap_seconds=_microseconds_to_seconds(
            int(row["trusted_sample_max_gap_duration_us"])
        ),
        entered_candidate_at=_optional_datetime_from_row(
            row, "entered_candidate_at_us"
        ),
        entered_at=_optional_datetime_from_row(row, "entered_at_us"),
        exit_candidate_at=_optional_datetime_from_row(
            row, "exit_candidate_at_us"
        ),
        ended_at=_optional_datetime_from_row(row, "ended_at_us"),
        termination_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


def _parking_episode_from_row(row: sqlite3.Row) -> ParkingEpisode:
    return ParkingEpisode(
        episode_id=ParkingEpisodeId(
            uuid_from_text(str(row["parking_episode_id"]))
        ),
        physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["physical_vehicle_id"]))
        ),
        parking_session_id=(
            ParkingSessionId(int(row["session_id"]))
            if row["session_id"] is not None
            else None
        ),
        state=ParkingState(str(row["domain_state"])),
        observation=_observation_from_row(row),
        stationary_trusted_seconds=_microseconds_to_seconds(
            int(row["stationary_trusted_duration_us"])
        ),
        movement_trusted_seconds=_microseconds_to_seconds(
            int(row["movement_trusted_duration_us"])
        ),
        parking_confirmation_seconds=_microseconds_to_seconds(
            int(row["parking_confirmation_duration_us"])
        ),
        movement_confirmation_seconds=_microseconds_to_seconds(
            int(row["movement_confirmation_duration_us"])
        ),
        trusted_sample_max_gap_seconds=_microseconds_to_seconds(
            int(row["trusted_sample_max_gap_duration_us"])
        ),
        last_signal=MotionSignal(str(row["last_motion_signal"])),
        assignment=_assignment_from_row(row),
        parked_at=_optional_datetime_from_row(row, "parked_at_us"),
        movement_candidate_at=_optional_datetime_from_row(
            row, "movement_candidate_at_us"
        ),
        ended_at=_optional_datetime_from_row(row, "ended_at_us"),
        termination_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        publication_revision=int(row["publication_revision"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


def _blocking_relation_from_row(row: sqlite3.Row) -> BlockingRelation:
    return BlockingRelation(
        blocking_relation_id=BlockingRelationId(
            uuid_from_text(str(row["blocking_relation_id"]))
        ),
        subject_physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["subject_physical_vehicle_id"]))
        ),
        victim_physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["victim_physical_vehicle_id"]))
        ),
        egress_zone_id=EgressAisleId(int(row["egress_zone_id"])),
        source_parking_episode_id=(
            ParkingEpisodeId(
                uuid_from_text(str(row["source_parking_episode_id"]))
            )
            if row["source_parking_episode_id"] is not None
            else None
        ),
        state=BlockingRelationState(str(row["domain_state"])),
        observation=_observation_from_row(row),
        confirm_trusted_seconds=_microseconds_to_seconds(
            int(row["confirm_trusted_duration_us"])
        ),
        clear_trusted_seconds=_microseconds_to_seconds(
            int(row["clear_trusted_duration_us"])
        ),
        confirm_duration_seconds=_microseconds_to_seconds(
            int(row["confirm_duration_us"])
        ),
        clear_duration_seconds=_microseconds_to_seconds(
            int(row["clear_duration_us"])
        ),
        confirmed_at=_optional_datetime_from_row(row, "confirmed_at_us"),
        resolved_at=_optional_datetime_from_row(row, "resolved_at_us"),
        terminated_at=_optional_datetime_from_row(row, "terminated_at_us"),
        termination_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


def _incident_from_row(row: sqlite3.Row) -> Incident:
    return Incident(
        incident_id=IncidentId(uuid_from_text(str(row["incident_id"]))),
        key=IncidentKey(
            scope_type=IncidentKeyScope(str(row["key_scope_type"])),
            scope_id=uuid_from_text(str(row["key_scope_id"])),
            rule_code=str(row["rule_code"]),
        ),
        physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["subject_physical_vehicle_id"]))
        ),
        entry_attempt_id=(
            EntryAttemptId(uuid_from_text(str(row["entry_attempt_id"])))
            if row["entry_attempt_id"] is not None
            else None
        ),
        parking_session_id=(
            ParkingSessionId(int(row["session_id"]))
            if row["session_id"] is not None
            else None
        ),
        zone_id=(
            ZoneId(int(row["zone_id"])) if row["zone_id"] is not None else None
        ),
        victim_physical_vehicle_id=(
            PhysicalVehicleId(
                uuid_from_text(str(row["victim_physical_vehicle_id"]))
            )
            if row["victim_physical_vehicle_id"] is not None
            else None
        ),
        state=IncidentState(str(row["domain_state"])),
        observation=_observation_from_row(row),
        confirm_trusted_seconds=_microseconds_to_seconds(
            int(row["confirm_trusted_duration_us"])
        ),
        clear_trusted_seconds=_microseconds_to_seconds(
            int(row["clear_trusted_duration_us"])
        ),
        confirm_duration_seconds=_microseconds_to_seconds(
            int(row["confirm_duration_us"])
        ),
        clear_duration_seconds=_microseconds_to_seconds(
            int(row["clear_duration_us"])
        ),
        trusted_sample_max_gap_seconds=_microseconds_to_seconds(
            int(row["trusted_sample_max_gap_duration_us"])
        ),
        first_observed_at=datetime_from_epoch_microseconds(
            int(row["first_observed_at_us"])
        ),
        confirmed_at=_optional_datetime_from_row(row, "confirmed_at_us"),
        resolved_at=_optional_datetime_from_row(row, "resolved_at_us"),
        terminated_at=_optional_datetime_from_row(row, "terminated_at_us"),
        termination_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        publication_revision=int(row["publication_revision"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


# [ZoneVisit]


class ZoneVisitRepository:
    """ZoneVisit snapshot과 ``(PhysicalVehicle, zone)`` cardinality를 보존한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, visit_id: ZoneVisitId) -> ZoneVisit | None:
        row = self._connection.execute(
            "SELECT * FROM zone_visits WHERE zone_visit_id = ?",
            (uuid_to_text(visit_id),),
        ).fetchone()
        return _zone_visit_from_row(row) if row is not None else None

    def get_active(
        self,
        physical_vehicle_id: PhysicalVehicleId,
        zone_id: ZoneId,
    ) -> ZoneVisit | None:
        row = self._connection.execute(
            """
            SELECT * FROM zone_visits
            WHERE physical_vehicle_id = ? AND zone_id = ?
              AND domain_state IN ('ENTERING', 'INSIDE', 'EXITING')
            """,
            (uuid_to_text(physical_vehicle_id), int(zone_id)),
        ).fetchone()
        return _zone_visit_from_row(row) if row is not None else None

    def list_active(
        self,
        physical_vehicle_id: PhysicalVehicleId | None = None,
    ) -> tuple[ZoneVisit, ...]:
        """nonterminal visit을 생성 순서로 반환한다."""

        if physical_vehicle_id is None:
            rows = self._connection.execute(
                """
                SELECT * FROM zone_visits
                WHERE domain_state IN ('ENTERING', 'INSIDE', 'EXITING')
                ORDER BY created_at_us, zone_visit_id
                """
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT * FROM zone_visits
                WHERE physical_vehicle_id = ?
                  AND domain_state IN ('ENTERING', 'INSIDE', 'EXITING')
                ORDER BY created_at_us, zone_visit_id
                """,
                (uuid_to_text(physical_vehicle_id),),
            ).fetchall()
        return tuple(_zone_visit_from_row(row) for row in rows)

    def list_active_by_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> tuple[ZoneVisit, ...]:
        return self.list_active(physical_vehicle_id)

    def add(self, visit: ZoneVisit) -> None:
        require_write_transaction(self._connection)
        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(visit.observation)
        )
        try:
            self._connection.execute(
                """
                INSERT INTO zone_visits(
                    zone_visit_id, physical_vehicle_id, zone_id,
                    zone_definition_version, domain_state, observation_state,
                    observation_reason, last_reliable_observed_at_us,
                    entry_trusted_duration_us, exit_trusted_duration_us,
                    entry_confirmation_duration_us,
                    exit_confirmation_duration_us,
                    trusted_sample_max_gap_duration_us,
                    entered_candidate_at_us, entered_at_us,
                    exit_candidate_at_us, termination_reason, ended_at_us,
                    record_version, created_at_us, updated_at_us
                ) VALUES (
                    :zone_visit_id, :physical_vehicle_id, :zone_id,
                    :zone_definition_version, :domain_state, :observation_state,
                    :observation_reason, :last_reliable_observed_at_us,
                    :entry_trusted_duration_us, :exit_trusted_duration_us,
                    :entry_confirmation_duration_us,
                    :exit_confirmation_duration_us,
                    :trusted_sample_max_gap_duration_us,
                    :entered_candidate_at_us, :entered_at_us,
                    :exit_candidate_at_us, :termination_reason, :ended_at_us,
                    :record_version, :created_at_us, :updated_at_us
                )
                """,
                {
                    "zone_visit_id": uuid_to_text(visit.visit_id),
                    "physical_vehicle_id": uuid_to_text(visit.physical_vehicle_id),
                    "zone_id": int(visit.zone_id),
                    "zone_definition_version": int(visit.zone_definition_version),
                    "domain_state": visit.state.value,
                    "observation_state": observation_state,
                    "observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "entry_trusted_duration_us": _seconds_to_microseconds(
                        visit.entry_trusted_seconds
                    ),
                    "exit_trusted_duration_us": _seconds_to_microseconds(
                        visit.exit_trusted_seconds
                    ),
                    "entry_confirmation_duration_us": _seconds_to_microseconds(
                        visit.entry_confirmation_seconds
                    ),
                    "exit_confirmation_duration_us": _seconds_to_microseconds(
                        visit.exit_confirmation_seconds
                    ),
                    "trusted_sample_max_gap_duration_us": _seconds_to_microseconds(
                        visit.trusted_sample_max_gap_seconds
                    ),
                    "entered_candidate_at_us": _optional_datetime_to_storage(
                        visit.entered_candidate_at
                    ),
                    "entered_at_us": _optional_datetime_to_storage(visit.entered_at),
                    "exit_candidate_at_us": _optional_datetime_to_storage(
                        visit.exit_candidate_at
                    ),
                    "termination_reason": visit.termination_reason,
                    "ended_at_us": _optional_datetime_to_storage(visit.ended_at),
                    "record_version": visit.record_version,
                    "created_at_us": datetime_to_epoch_microseconds(visit.created_at),
                    "updated_at_us": datetime_to_epoch_microseconds(visit.updated_at),
                },
            )
        except sqlite3.IntegrityError as error:
            raise ZoneVisitConflictError(
                "ZoneVisit violates an identity, FK, state, or cardinality contract"
            ) from error

    def save(
        self,
        visit: ZoneVisit,
        *,
        expected_record_version: int,
    ) -> None:
        require_write_transaction(self._connection)
        _require_advanced_record_version(
            aggregate_name="ZoneVisit",
            record_version=visit.record_version,
            expected_record_version=expected_record_version,
        )
        existing = self.get(visit.visit_id)
        if existing is None:
            _raise_missing_for_update("ZoneVisit", visit.visit_id)
        assert existing is not None
        if (
            visit.physical_vehicle_id != existing.physical_vehicle_id
            or visit.zone_id != existing.zone_id
            or visit.zone_definition_version != existing.zone_definition_version
            or visit.created_at != existing.created_at
            or _seconds_to_microseconds(visit.entry_confirmation_seconds)
            != _seconds_to_microseconds(existing.entry_confirmation_seconds)
            or _seconds_to_microseconds(visit.exit_confirmation_seconds)
            != _seconds_to_microseconds(existing.exit_confirmation_seconds)
            or _seconds_to_microseconds(visit.trusted_sample_max_gap_seconds)
            != _seconds_to_microseconds(existing.trusted_sample_max_gap_seconds)
        ):
            raise ZoneVisitConflictError(
                "ZoneVisit identity and applied confirmation scalars are immutable"
            )
        _require_not_reactivated(
            aggregate_name="ZoneVisit",
            existing_state=existing.state,
            incoming_state=visit.state,
            terminal_states={ZoneVisitState.ENDED, ZoneVisitState.CANCELED},
            error_type=ZoneVisitConflictError,
        )

        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(visit.observation)
        )
        try:
            new_version = optimistic_update(
                self._connection,
                table="zone_visits",
                key_column="zone_visit_id",
                key_value=uuid_to_text(visit.visit_id),
                expected_record_version=expected_record_version,
                next_record_version=visit.record_version,
                changes={
                    "domain_state": visit.state.value,
                    "observation_state": observation_state,
                    "observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "entry_trusted_duration_us": _seconds_to_microseconds(
                        visit.entry_trusted_seconds
                    ),
                    "exit_trusted_duration_us": _seconds_to_microseconds(
                        visit.exit_trusted_seconds
                    ),
                    "entered_candidate_at_us": _optional_datetime_to_storage(
                        visit.entered_candidate_at
                    ),
                    "entered_at_us": _optional_datetime_to_storage(visit.entered_at),
                    "exit_candidate_at_us": _optional_datetime_to_storage(
                        visit.exit_candidate_at
                    ),
                    "termination_reason": visit.termination_reason,
                    "ended_at_us": _optional_datetime_to_storage(visit.ended_at),
                    "updated_at_us": datetime_to_epoch_microseconds(visit.updated_at),
                },
            )
        except sqlite3.IntegrityError as error:
            raise ZoneVisitConflictError(
                "ZoneVisit update violates the durable state contract"
            ) from error
        if new_version != visit.record_version:  # pragma: no cover
            raise RuntimeError("optimistic update returned an unexpected record version")


# [ParkingEpisode]


class ParkingEpisodeRepository:
    """ParkingEpisode snapshot과 PhysicalVehicle별 active cardinality를 보존한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, episode_id: ParkingEpisodeId) -> ParkingEpisode | None:
        row = self._connection.execute(
            "SELECT * FROM parking_episodes WHERE parking_episode_id = ?",
            (uuid_to_text(episode_id),),
        ).fetchone()
        return _parking_episode_from_row(row) if row is not None else None

    def get_active(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> ParkingEpisode | None:
        row = self._connection.execute(
            """
            SELECT * FROM parking_episodes
            WHERE physical_vehicle_id = ?
              AND domain_state IN ('STOP_PENDING', 'PARKED', 'MOVE_PENDING')
            """,
            (uuid_to_text(physical_vehicle_id),),
        ).fetchone()
        return _parking_episode_from_row(row) if row is not None else None

    def list_active(self) -> tuple[ParkingEpisode, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM parking_episodes
            WHERE domain_state IN ('STOP_PENDING', 'PARKED', 'MOVE_PENDING')
            ORDER BY created_at_us, parking_episode_id
            """
        ).fetchall()
        return tuple(_parking_episode_from_row(row) for row in rows)

    def add(self, episode: ParkingEpisode) -> None:
        require_write_transaction(self._connection)
        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(episode.observation)
        )
        parameters: dict[str, object | None] = {
            "parking_episode_id": uuid_to_text(episode.episode_id),
            "physical_vehicle_id": uuid_to_text(episode.physical_vehicle_id),
            "domain_state": episode.state.value,
            "observation_state": observation_state,
            "observation_reason": observation_reason,
            "last_reliable_observed_at_us": last_reliable_at_us,
            "stationary_trusted_duration_us": _seconds_to_microseconds(
                episode.stationary_trusted_seconds
            ),
            "movement_trusted_duration_us": _seconds_to_microseconds(
                episode.movement_trusted_seconds
            ),
            "parking_confirmation_duration_us": _seconds_to_microseconds(
                episode.parking_confirmation_seconds
            ),
            "movement_confirmation_duration_us": _seconds_to_microseconds(
                episode.movement_confirmation_seconds
            ),
            "trusted_sample_max_gap_duration_us": _seconds_to_microseconds(
                episode.trusted_sample_max_gap_seconds
            ),
            "last_motion_signal": episode.last_signal.value,
            "session_id": (
                int(episode.parking_session_id)
                if episode.parking_session_id is not None
                else None
            ),
            "parked_at_us": _optional_datetime_to_storage(episode.parked_at),
            "movement_candidate_at_us": _optional_datetime_to_storage(
                episode.movement_candidate_at
            ),
            "termination_reason": episode.termination_reason,
            "ended_at_us": _optional_datetime_to_storage(episode.ended_at),
            "record_version": episode.record_version,
            "publication_revision": episode.publication_revision,
            "created_at_us": datetime_to_epoch_microseconds(episode.created_at),
            "updated_at_us": datetime_to_epoch_microseconds(episode.updated_at),
            **_assignment_columns(episode.assignment),
        }
        try:
            self._connection.execute(
                """
                INSERT INTO parking_episodes(
                    parking_episode_id, physical_vehicle_id, domain_state,
                    observation_state, observation_reason,
                    last_reliable_observed_at_us,
                    stationary_trusted_duration_us,
                    movement_trusted_duration_us,
                    parking_confirmation_duration_us,
                    movement_confirmation_duration_us,
                    trusted_sample_max_gap_duration_us, last_motion_signal,
                    session_id, assignment_state, assignment_zone_id,
                    assignment_unassigned_reason, representative_footprint,
                    assignment_confidence, assignment_last_stable_at_us,
                    parked_at_us, movement_candidate_at_us,
                    termination_reason, ended_at_us, record_version,
                    publication_revision, created_at_us, updated_at_us
                ) VALUES (
                    :parking_episode_id, :physical_vehicle_id, :domain_state,
                    :observation_state, :observation_reason,
                    :last_reliable_observed_at_us,
                    :stationary_trusted_duration_us,
                    :movement_trusted_duration_us,
                    :parking_confirmation_duration_us,
                    :movement_confirmation_duration_us,
                    :trusted_sample_max_gap_duration_us, :last_motion_signal,
                    :session_id, :assignment_state, :assignment_zone_id,
                    :assignment_unassigned_reason, :representative_footprint,
                    :assignment_confidence, :assignment_last_stable_at_us,
                    :parked_at_us, :movement_candidate_at_us,
                    :termination_reason, :ended_at_us, :record_version,
                    :publication_revision, :created_at_us, :updated_at_us
                )
                """,
                parameters,
            )
        except sqlite3.IntegrityError as error:
            raise ParkingEpisodeConflictError(
                "ParkingEpisode violates an identity, FK, state, or cardinality contract"
            ) from error

    def save(
        self,
        episode: ParkingEpisode,
        *,
        expected_record_version: int,
    ) -> None:
        require_write_transaction(self._connection)
        _require_advanced_record_version(
            aggregate_name="ParkingEpisode",
            record_version=episode.record_version,
            expected_record_version=expected_record_version,
        )
        existing = self.get(episode.episode_id)
        if existing is None:
            _raise_missing_for_update("ParkingEpisode", episode.episode_id)
        assert existing is not None
        if (
            episode.physical_vehicle_id != existing.physical_vehicle_id
            or episode.created_at != existing.created_at
            or _seconds_to_microseconds(episode.parking_confirmation_seconds)
            != _seconds_to_microseconds(existing.parking_confirmation_seconds)
            or _seconds_to_microseconds(episode.movement_confirmation_seconds)
            != _seconds_to_microseconds(existing.movement_confirmation_seconds)
            or _seconds_to_microseconds(episode.trusted_sample_max_gap_seconds)
            != _seconds_to_microseconds(existing.trusted_sample_max_gap_seconds)
        ):
            raise ParkingEpisodeConflictError(
                "ParkingEpisode identity and applied confirmation scalars are immutable"
            )
        _require_not_reactivated(
            aggregate_name="ParkingEpisode",
            existing_state=existing.state,
            incoming_state=episode.state,
            terminal_states={ParkingState.ENDED, ParkingState.CANCELED},
            error_type=ParkingEpisodeConflictError,
        )
        _require_fill_only(
            aggregate_name="ParkingEpisode",
            field_name="parking_session_id",
            existing=existing.parking_session_id,
            incoming=episode.parking_session_id,
            error_type=ParkingEpisodeConflictError,
        )
        if episode.publication_revision < existing.publication_revision:
            raise ParkingEpisodeConflictError(
                "ParkingEpisode publication_revision cannot decrease"
            )

        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(episode.observation)
        )
        changes: dict[str, object | None] = {
            "domain_state": episode.state.value,
            "observation_state": observation_state,
            "observation_reason": observation_reason,
            "last_reliable_observed_at_us": last_reliable_at_us,
            "stationary_trusted_duration_us": _seconds_to_microseconds(
                episode.stationary_trusted_seconds
            ),
            "movement_trusted_duration_us": _seconds_to_microseconds(
                episode.movement_trusted_seconds
            ),
            "last_motion_signal": episode.last_signal.value,
            "session_id": (
                int(episode.parking_session_id)
                if episode.parking_session_id is not None
                else None
            ),
            "parked_at_us": _optional_datetime_to_storage(episode.parked_at),
            "movement_candidate_at_us": _optional_datetime_to_storage(
                episode.movement_candidate_at
            ),
            "termination_reason": episode.termination_reason,
            "ended_at_us": _optional_datetime_to_storage(episode.ended_at),
            "publication_revision": episode.publication_revision,
            "updated_at_us": datetime_to_epoch_microseconds(episode.updated_at),
            **_assignment_columns(episode.assignment),
        }
        try:
            new_version = optimistic_update(
                self._connection,
                table="parking_episodes",
                key_column="parking_episode_id",
                key_value=uuid_to_text(episode.episode_id),
                expected_record_version=expected_record_version,
                next_record_version=episode.record_version,
                changes=changes,
            )
        except sqlite3.IntegrityError as error:
            raise ParkingEpisodeConflictError(
                "ParkingEpisode update violates the durable state contract"
            ) from error
        if new_version != episode.record_version:  # pragma: no cover
            raise RuntimeError("optimistic update returned an unexpected record version")


# [BlockingRelation]


class BlockingRelationRepository:
    """subject·victim·egress별 non-terminal 관계를 보존한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, blocking_relation_id: BlockingRelationId
    ) -> BlockingRelation | None:
        row = self._connection.execute(
            "SELECT * FROM blocking_relations WHERE blocking_relation_id = ?",
            (uuid_to_text(blocking_relation_id),),
        ).fetchone()
        return _blocking_relation_from_row(row) if row is not None else None

    def list_active(self) -> tuple[BlockingRelation, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM blocking_relations
            WHERE domain_state IN ('CANDIDATE', 'BLOCKING', 'CLEAR_PENDING')
            ORDER BY created_at_us, blocking_relation_id
            """
        ).fetchall()
        return tuple(_blocking_relation_from_row(row) for row in rows)

    def add(self, relation: BlockingRelation) -> None:
        require_write_transaction(self._connection)
        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(relation.observation)
        )
        try:
            self._connection.execute(
                """
                INSERT INTO blocking_relations(
                    blocking_relation_id, subject_physical_vehicle_id,
                    victim_physical_vehicle_id, egress_zone_id,
                    source_parking_episode_id, domain_state,
                    observation_state, observation_reason,
                    last_reliable_observed_at_us,
                    confirm_trusted_duration_us, clear_trusted_duration_us,
                    confirm_duration_us, clear_duration_us,
                    confirmed_at_us, resolved_at_us,
                    termination_reason, terminated_at_us,
                    record_version, created_at_us, updated_at_us
                ) VALUES (
                    :blocking_relation_id, :subject_physical_vehicle_id,
                    :victim_physical_vehicle_id, :egress_zone_id,
                    :source_parking_episode_id, :domain_state,
                    :observation_state, :observation_reason,
                    :last_reliable_observed_at_us,
                    :confirm_trusted_duration_us, :clear_trusted_duration_us,
                    :confirm_duration_us, :clear_duration_us,
                    :confirmed_at_us, :resolved_at_us,
                    :termination_reason, :terminated_at_us,
                    :record_version, :created_at_us, :updated_at_us
                )
                """,
                {
                    "blocking_relation_id": uuid_to_text(
                        relation.blocking_relation_id
                    ),
                    "subject_physical_vehicle_id": uuid_to_text(
                        relation.subject_physical_vehicle_id
                    ),
                    "victim_physical_vehicle_id": uuid_to_text(
                        relation.victim_physical_vehicle_id
                    ),
                    "egress_zone_id": int(relation.egress_zone_id),
                    "source_parking_episode_id": (
                        uuid_to_text(relation.source_parking_episode_id)
                        if relation.source_parking_episode_id is not None
                        else None
                    ),
                    "domain_state": relation.state.value,
                    "observation_state": observation_state,
                    "observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "confirm_trusted_duration_us": _seconds_to_microseconds(
                        relation.confirm_trusted_seconds
                    ),
                    "clear_trusted_duration_us": _seconds_to_microseconds(
                        relation.clear_trusted_seconds
                    ),
                    "confirm_duration_us": _seconds_to_microseconds(
                        relation.confirm_duration_seconds
                    ),
                    "clear_duration_us": _seconds_to_microseconds(
                        relation.clear_duration_seconds
                    ),
                    "confirmed_at_us": _optional_datetime_to_storage(
                        relation.confirmed_at
                    ),
                    "resolved_at_us": _optional_datetime_to_storage(
                        relation.resolved_at
                    ),
                    "termination_reason": relation.termination_reason,
                    "terminated_at_us": _optional_datetime_to_storage(
                        relation.terminated_at
                    ),
                    "record_version": relation.record_version,
                    "created_at_us": datetime_to_epoch_microseconds(
                        relation.created_at
                    ),
                    "updated_at_us": datetime_to_epoch_microseconds(
                        relation.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise BlockingRelationConflictError(
                "BlockingRelation violates an identity, FK, state, or cardinality contract"
            ) from error

    def save(
        self,
        relation: BlockingRelation,
        *,
        expected_record_version: int,
    ) -> None:
        require_write_transaction(self._connection)
        _require_advanced_record_version(
            aggregate_name="BlockingRelation",
            record_version=relation.record_version,
            expected_record_version=expected_record_version,
        )
        existing = self.get(relation.blocking_relation_id)
        if existing is None:
            _raise_missing_for_update(
                "BlockingRelation", relation.blocking_relation_id
            )
        assert existing is not None
        if (
            relation.subject_physical_vehicle_id
            != existing.subject_physical_vehicle_id
            or relation.victim_physical_vehicle_id
            != existing.victim_physical_vehicle_id
            or relation.egress_zone_id != existing.egress_zone_id
            or relation.source_parking_episode_id
            != existing.source_parking_episode_id
            or relation.created_at != existing.created_at
            or _seconds_to_microseconds(relation.confirm_duration_seconds)
            != _seconds_to_microseconds(existing.confirm_duration_seconds)
            or _seconds_to_microseconds(relation.clear_duration_seconds)
            != _seconds_to_microseconds(existing.clear_duration_seconds)
        ):
            raise BlockingRelationConflictError(
                "BlockingRelation identity and applied confirmation scalars are immutable"
            )
        _require_not_reactivated(
            aggregate_name="BlockingRelation",
            existing_state=existing.state,
            incoming_state=relation.state,
            terminal_states={
                BlockingRelationState.RESOLVED,
                BlockingRelationState.CANCELED,
            },
            error_type=BlockingRelationConflictError,
        )

        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(relation.observation)
        )
        try:
            new_version = optimistic_update(
                self._connection,
                table="blocking_relations",
                key_column="blocking_relation_id",
                key_value=uuid_to_text(relation.blocking_relation_id),
                expected_record_version=expected_record_version,
                next_record_version=relation.record_version,
                changes={
                    "domain_state": relation.state.value,
                    "observation_state": observation_state,
                    "observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "confirm_trusted_duration_us": _seconds_to_microseconds(
                        relation.confirm_trusted_seconds
                    ),
                    "clear_trusted_duration_us": _seconds_to_microseconds(
                        relation.clear_trusted_seconds
                    ),
                    "confirmed_at_us": _optional_datetime_to_storage(
                        relation.confirmed_at
                    ),
                    "resolved_at_us": _optional_datetime_to_storage(
                        relation.resolved_at
                    ),
                    "termination_reason": relation.termination_reason,
                    "terminated_at_us": _optional_datetime_to_storage(
                        relation.terminated_at
                    ),
                    "updated_at_us": datetime_to_epoch_microseconds(
                        relation.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise BlockingRelationConflictError(
                "BlockingRelation update violates the durable state contract"
            ) from error
        if new_version != relation.record_version:  # pragma: no cover
            raise RuntimeError(
                "optimistic update returned an unexpected record version"
            )


# [Incident]


class IncidentRepository:
    """IncidentKey continuity와 publication revision snapshot을 보존한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, incident_id: IncidentId) -> Incident | None:
        row = self._connection.execute(
            "SELECT * FROM incidents WHERE incident_id = ?",
            (uuid_to_text(incident_id),),
        ).fetchone()
        return _incident_from_row(row) if row is not None else None

    def get_active(self, key: IncidentKey) -> Incident | None:
        row = self._connection.execute(
            """
            SELECT * FROM incidents
            WHERE rule_code = ? AND key_scope_type = ? AND key_scope_id = ?
              AND domain_state IN ('CANDIDATE', 'OPEN', 'CLEAR_PENDING')
            """,
            (key.rule_code, key.scope_type.value, uuid_to_text(key.scope_id)),
        ).fetchone()
        return _incident_from_row(row) if row is not None else None

    def get_latest(self, key: IncidentKey) -> Incident | None:
        row = self._connection.execute(
            """
            SELECT * FROM incidents
            WHERE rule_code = ? AND key_scope_type = ? AND key_scope_id = ?
            ORDER BY created_at_us DESC, incident_id DESC
            LIMIT 1
            """,
            (key.rule_code, key.scope_type.value, uuid_to_text(key.scope_id)),
        ).fetchone()
        return _incident_from_row(row) if row is not None else None

    def list_active(self) -> tuple[Incident, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM incidents
            WHERE domain_state IN ('CANDIDATE', 'OPEN', 'CLEAR_PENDING')
            ORDER BY created_at_us, incident_id
            """
        ).fetchall()
        return tuple(_incident_from_row(row) for row in rows)

    def list_active_by_scope(
        self,
        scope_type: IncidentKeyScope,
        scope_id: UUID,
    ) -> tuple[Incident, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM incidents
            WHERE key_scope_type = ? AND key_scope_id = ?
              AND domain_state IN ('CANDIDATE', 'OPEN', 'CLEAR_PENDING')
            ORDER BY created_at_us, incident_id
            """,
            (scope_type.value, uuid_to_text(scope_id)),
        ).fetchall()
        return tuple(_incident_from_row(row) for row in rows)

    def list_active_related_to_physical_vehicle(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> tuple[Incident, ...]:
        vehicle_id = uuid_to_text(physical_vehicle_id)
        rows = self._connection.execute(
            """
            SELECT * FROM incidents
            WHERE (subject_physical_vehicle_id = ?
                   OR victim_physical_vehicle_id = ?)
              AND domain_state IN ('CANDIDATE', 'OPEN', 'CLEAR_PENDING')
            ORDER BY created_at_us, incident_id
            """,
            (vehicle_id, vehicle_id),
        ).fetchall()
        return tuple(_incident_from_row(row) for row in rows)

    def add(self, incident: Incident) -> None:
        require_write_transaction(self._connection)
        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(incident.observation)
        )
        try:
            self._connection.execute(
                """
                INSERT INTO incidents(
                    incident_id, rule_code, key_scope_type, key_scope_id,
                    subject_physical_vehicle_id, entry_attempt_id, session_id,
                    zone_id, victim_physical_vehicle_id, domain_state,
                    observation_state, observation_reason,
                    last_reliable_observed_at_us,
                    confirm_trusted_duration_us, clear_trusted_duration_us,
                    confirm_duration_us, clear_duration_us,
                    trusted_sample_max_gap_duration_us,
                    first_observed_at_us, confirmed_at_us, resolved_at_us,
                    termination_reason, terminated_at_us, record_version,
                    publication_revision, created_at_us, updated_at_us
                ) VALUES (
                    :incident_id, :rule_code, :key_scope_type, :key_scope_id,
                    :subject_physical_vehicle_id, :entry_attempt_id, :session_id,
                    :zone_id, :victim_physical_vehicle_id, :domain_state,
                    :observation_state, :observation_reason,
                    :last_reliable_observed_at_us,
                    :confirm_trusted_duration_us, :clear_trusted_duration_us,
                    :confirm_duration_us, :clear_duration_us,
                    :trusted_sample_max_gap_duration_us,
                    :first_observed_at_us, :confirmed_at_us, :resolved_at_us,
                    :termination_reason, :terminated_at_us, :record_version,
                    :publication_revision, :created_at_us, :updated_at_us
                )
                """,
                {
                    "incident_id": uuid_to_text(incident.incident_id),
                    "rule_code": incident.key.rule_code,
                    "key_scope_type": incident.key.scope_type.value,
                    "key_scope_id": uuid_to_text(incident.key.scope_id),
                    "subject_physical_vehicle_id": uuid_to_text(
                        incident.physical_vehicle_id
                    ),
                    "entry_attempt_id": (
                        uuid_to_text(incident.entry_attempt_id)
                        if incident.entry_attempt_id is not None
                        else None
                    ),
                    "session_id": (
                        int(incident.parking_session_id)
                        if incident.parking_session_id is not None
                        else None
                    ),
                    "zone_id": (
                        int(incident.zone_id) if incident.zone_id is not None else None
                    ),
                    "victim_physical_vehicle_id": (
                        uuid_to_text(incident.victim_physical_vehicle_id)
                        if incident.victim_physical_vehicle_id is not None
                        else None
                    ),
                    "domain_state": incident.state.value,
                    "observation_state": observation_state,
                    "observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "confirm_trusted_duration_us": _seconds_to_microseconds(
                        incident.confirm_trusted_seconds
                    ),
                    "clear_trusted_duration_us": _seconds_to_microseconds(
                        incident.clear_trusted_seconds
                    ),
                    "confirm_duration_us": _seconds_to_microseconds(
                        incident.confirm_duration_seconds
                    ),
                    "clear_duration_us": _seconds_to_microseconds(
                        incident.clear_duration_seconds
                    ),
                    "trusted_sample_max_gap_duration_us": _seconds_to_microseconds(
                        incident.trusted_sample_max_gap_seconds
                    ),
                    "first_observed_at_us": datetime_to_epoch_microseconds(
                        incident.first_observed_at
                    ),
                    "confirmed_at_us": _optional_datetime_to_storage(
                        incident.confirmed_at
                    ),
                    "resolved_at_us": _optional_datetime_to_storage(
                        incident.resolved_at
                    ),
                    "termination_reason": incident.termination_reason,
                    "terminated_at_us": _optional_datetime_to_storage(
                        incident.terminated_at
                    ),
                    "record_version": incident.record_version,
                    "publication_revision": incident.publication_revision,
                    "created_at_us": datetime_to_epoch_microseconds(
                        incident.created_at
                    ),
                    "updated_at_us": datetime_to_epoch_microseconds(
                        incident.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise IncidentConflictError(
                "Incident violates an identity, FK, state, or active-key contract"
            ) from error

    def save(
        self,
        incident: Incident,
        *,
        expected_record_version: int,
    ) -> None:
        require_write_transaction(self._connection)
        _require_advanced_record_version(
            aggregate_name="Incident",
            record_version=incident.record_version,
            expected_record_version=expected_record_version,
        )
        existing = self.get(incident.incident_id)
        if existing is None:
            _raise_missing_for_update("Incident", incident.incident_id)
        assert existing is not None
        if (
            incident.key != existing.key
            or incident.physical_vehicle_id != existing.physical_vehicle_id
            or incident.first_observed_at != existing.first_observed_at
            or incident.created_at != existing.created_at
            or _seconds_to_microseconds(incident.confirm_duration_seconds)
            != _seconds_to_microseconds(existing.confirm_duration_seconds)
            or _seconds_to_microseconds(incident.clear_duration_seconds)
            != _seconds_to_microseconds(existing.clear_duration_seconds)
            or _seconds_to_microseconds(incident.trusted_sample_max_gap_seconds)
            != _seconds_to_microseconds(existing.trusted_sample_max_gap_seconds)
        ):
            raise IncidentConflictError(
                "Incident identity and applied confirmation scalars are immutable"
            )
        _require_not_reactivated(
            aggregate_name="Incident",
            existing_state=existing.state,
            incoming_state=incident.state,
            terminal_states={IncidentState.RESOLVED, IncidentState.CANCELED},
            error_type=IncidentConflictError,
        )
        for field_name in (
            "entry_attempt_id",
            "parking_session_id",
            "zone_id",
            "victim_physical_vehicle_id",
        ):
            _require_fill_only(
                aggregate_name="Incident",
                field_name=field_name,
                existing=getattr(existing, field_name),
                incoming=getattr(incident, field_name),
                error_type=IncidentConflictError,
            )
        if incident.publication_revision < existing.publication_revision:
            raise IncidentConflictError("Incident publication_revision cannot decrease")

        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(incident.observation)
        )
        try:
            new_version = optimistic_update(
                self._connection,
                table="incidents",
                key_column="incident_id",
                key_value=uuid_to_text(incident.incident_id),
                expected_record_version=expected_record_version,
                next_record_version=incident.record_version,
                changes={
                    "entry_attempt_id": (
                        uuid_to_text(incident.entry_attempt_id)
                        if incident.entry_attempt_id is not None
                        else None
                    ),
                    "session_id": (
                        int(incident.parking_session_id)
                        if incident.parking_session_id is not None
                        else None
                    ),
                    "zone_id": (
                        int(incident.zone_id) if incident.zone_id is not None else None
                    ),
                    "victim_physical_vehicle_id": (
                        uuid_to_text(incident.victim_physical_vehicle_id)
                        if incident.victim_physical_vehicle_id is not None
                        else None
                    ),
                    "domain_state": incident.state.value,
                    "observation_state": observation_state,
                    "observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "confirm_trusted_duration_us": _seconds_to_microseconds(
                        incident.confirm_trusted_seconds
                    ),
                    "clear_trusted_duration_us": _seconds_to_microseconds(
                        incident.clear_trusted_seconds
                    ),
                    "confirmed_at_us": _optional_datetime_to_storage(
                        incident.confirmed_at
                    ),
                    "resolved_at_us": _optional_datetime_to_storage(
                        incident.resolved_at
                    ),
                    "termination_reason": incident.termination_reason,
                    "terminated_at_us": _optional_datetime_to_storage(
                        incident.terminated_at
                    ),
                    "publication_revision": incident.publication_revision,
                    "updated_at_us": datetime_to_epoch_microseconds(
                        incident.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise IncidentConflictError(
                "Incident update violates the durable state contract"
            ) from error
        if new_version != incident.record_version:  # pragma: no cover
            raise RuntimeError("optimistic update returned an unexpected record version")


__all__ = [
    "IncidentConflictError",
    "IncidentRepository",
    "ParkingEpisodeConflictError",
    "ParkingEpisodeRepository",
    "ZoneVisitConflictError",
    "ZoneVisitRepository",
]

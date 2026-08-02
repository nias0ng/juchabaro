"""durable input·EntryMatchAttempt·transactional outbox repository."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Mapping

from src.domain.models import (
    DeliveryState,
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
    PhysicalExitEvidence,
    PhysicalPresenceState,
    PhysicalTerminationOrigin,
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

from .codecs import (
    datetime_from_epoch_microseconds,
    datetime_to_epoch_microseconds,
    uuid_from_text,
    uuid_to_text,
)
from .models import AcceptedInputRecord, OutboxRecord
from .unit_of_work import require_write_transaction

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AcceptedInputConflictError(RuntimeError):
    """같은 input identity·revision이 다른 payload로 재사용됐다."""


class OutboxConflictError(RuntimeError):
    """outbox publication identity가 다른 immutable data로 재사용됐다."""


class EntryMatchAttemptConflictError(RuntimeError):
    """이미 존재하는 entryAttemptId를 새 attempt로 재사용했다."""


class PhysicalVehicleConflictError(RuntimeError):
    """PhysicalVehicle identity·checkpoint가 durable row와 충돌했다."""


class ParkingSessionMirrorConflictError(RuntimeError):
    """ParkingSessionMirror가 unique·FK·state 계약을 어겼다."""


class ContextBindingConflictError(RuntimeError):
    """ContextBinding이 immutable identity·active cardinality와 충돌했다."""


class OptimisticConcurrencyError(RuntimeError):
    """저장 record가 호출자가 기대한 version에서 이미 변경됐다."""


@dataclass(frozen=True)
class AcceptanceResult:
    record: AcceptedInputRecord
    created: bool


@dataclass(frozen=True)
class OutboxEnqueueResult:
    record: OutboxRecord
    created: bool


def _utc_now_microseconds() -> int:
    return time.time_ns() // 1_000


def _payload_bytes(payload: bytes | bytearray | memoryview) -> bytes:
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("immutable serialized payload must be bytes-like")
    return bytes(payload)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _seconds_to_microseconds(value: float) -> int:
    """도메인 누적 초 단위를 SQLite 손실 없는 정수 단위로 변환한다."""

    return round(value * 1_000_000)


def _microseconds_to_seconds(value: int) -> float:
    return value / 1_000_000


def _accepted_input_from_row(row: sqlite3.Row) -> AcceptedInputRecord:
    return AcceptedInputRecord(
        input_type=str(row["input_type"]),
        input_identity=str(row["input_identity"]),
        input_revision=int(row["input_revision"]),
        payload_hash=str(row["payload_hash"]),
        request_payload=bytes(row["request_payload"]),
        workflow_state=str(row["workflow_state"]),
        result_payload=(
            bytes(row["result_payload"]) if row["result_payload"] is not None else None
        ),
        accepted_at_us=int(row["accepted_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
        record_version=int(row["record_version"]),
    )


def _outbox_from_row(row: sqlite3.Row) -> OutboxRecord:
    return OutboxRecord(
        delivery_id=str(row["delivery_id"]),
        aggregate_type=str(row["aggregate_type"]),
        aggregate_id=str(row["aggregate_id"]),
        destination=str(row["destination"]),
        publication_revision=int(row["publication_revision"]),
        transition_type=str(row["transition_type"]),
        payload=bytes(row["payload"]),
        payload_hash=str(row["payload_hash"]),
        idempotency_key=str(row["idempotency_key"]),
        delivery_state=DeliveryState(str(row["delivery_state"])),
        attempt_count=int(row["attempt_count"]),
        next_attempt_at_us=(
            int(row["next_attempt_at_us"])
            if row["next_attempt_at_us"] is not None
            else None
        ),
        last_error=str(row["last_error"]) if row["last_error"] is not None else None,
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
        confirmed_at_us=(
            int(row["confirmed_at_us"])
            if row["confirmed_at_us"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
    )


def _session_context_to_payload(context: SessionContext) -> bytes:
    """SessionContext를 SQLite BLOB에 저장할 canonical JSON으로 변환한다."""

    return json.dumps(
        {
            "isDisabledVehicle": context.is_disabled_vehicle,
            "isElectric": context.is_electric,
            "parkingSessionId": int(context.parking_session_id),
            "vehicleId": None if context.vehicle_id is None else int(context.vehicle_id),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _session_context_from_payload(payload: bytes | bytearray | memoryview) -> SessionContext:
    """SQLite의 authoritative context payload를 domain value로 복원한다."""

    try:
        raw = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("invalid authoritative SessionContext payload") from error
    if not isinstance(raw, dict) or set(raw) != {
        "isDisabledVehicle",
        "isElectric",
        "parkingSessionId",
        "vehicleId",
    }:
        raise ValueError("authoritative SessionContext payload has an invalid shape")

    session_id = raw["parkingSessionId"]
    vehicle_id = raw["vehicleId"]
    is_electric = raw["isElectric"]
    is_disabled_vehicle = raw["isDisabledVehicle"]
    if isinstance(session_id, bool) or not isinstance(session_id, int):
        raise ValueError("parkingSessionId must be an integer")
    if vehicle_id is not None and (
        isinstance(vehicle_id, bool) or not isinstance(vehicle_id, int)
    ):
        raise ValueError("vehicleId must be an integer or null")
    if is_electric is not None and not isinstance(is_electric, bool):
        raise ValueError("isElectric must be a boolean or null")
    if is_disabled_vehicle is not None and not isinstance(is_disabled_vehicle, bool):
        raise ValueError("isDisabledVehicle must be a boolean or null")

    return SessionContext(
        parking_session_id=ParkingSessionId(session_id),
        vehicle_id=None if vehicle_id is None else VehicleId(vehicle_id),
        is_electric=is_electric,
        is_disabled_vehicle=is_disabled_vehicle,
    )


def _observation_from_row(
    row: sqlite3.Row,
    *,
    state_column: str,
    reason_column: str,
    last_reliable_column: str,
) -> ObservationStatus:
    reason = row[reason_column]
    last_reliable_at = row[last_reliable_column]
    return ObservationStatus(
        state=ObservationState(str(row[state_column])),
        reason=ObservationReason(str(reason)) if reason is not None else None,
        last_reliable_observed_at=(
            datetime_from_epoch_microseconds(int(last_reliable_at))
            if last_reliable_at is not None
            else None
        ),
    )


def _observation_columns(
    observation: ObservationStatus,
) -> tuple[str, str | None, int | None]:
    return (
        observation.state.value,
        observation.reason.value if observation.reason is not None else None,
        (
            datetime_to_epoch_microseconds(observation.last_reliable_observed_at)
            if observation.last_reliable_observed_at is not None
            else None
        ),
    )


def _physical_vehicle_from_row(row: sqlite3.Row) -> PhysicalVehicle:
    return PhysicalVehicle(
        physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["physical_vehicle_id"]))
        ),
        state=PhysicalVehicleState(str(row["domain_state"])),
        observation=_observation_from_row(
            row,
            state_column="observation_state",
            reason_column="observation_reason",
            last_reliable_column="last_reliable_observed_at_us",
        ),
        absence_trusted_seconds=_microseconds_to_seconds(
            int(row["absence_trusted_duration_us"])
        ),
        absence_confirmation_seconds=_microseconds_to_seconds(
            int(row["absence_confirmation_duration_us"])
        ),
        trusted_sample_max_gap_seconds=_microseconds_to_seconds(
            int(row["trusted_sample_max_gap_duration_us"])
        ),
        absence_confirmed_at=(
            datetime_from_epoch_microseconds(int(row["absence_confirmed_at_us"]))
            if row["absence_confirmed_at_us"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
        terminated_at=(
            datetime_from_epoch_microseconds(int(row["terminated_at_us"]))
            if row["terminated_at_us"] is not None
            else None
        ),
        termination_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
    )


def _parking_session_mirror_from_row(row: sqlite3.Row) -> ParkingSessionMirror:
    context_payload = row["last_context_payload"]
    return ParkingSessionMirror(
        parking_session_id=ParkingSessionId(int(row["session_id"])),
        entry_attempt_id=(
            EntryAttemptId(uuid_from_text(str(row["entry_attempt_id"])))
            if row["entry_attempt_id"] is not None
            else None
        ),
        physical_vehicle_id=(
            PhysicalVehicleId(uuid_from_text(str(row["physical_vehicle_id"])))
            if row["physical_vehicle_id"] is not None
            else None
        ),
        administrative_state=SessionAdministrativeState(
            str(row["administrative_state"])
        ),
        physical_presence_state=PhysicalPresenceState(
            str(row["physical_presence_state"])
        ),
        physical_observation=_observation_from_row(
            row,
            state_column="physical_observation_state",
            reason_column="physical_observation_reason",
            last_reliable_column="last_reliable_observed_at_us",
        ),
        physical_termination_origin=(
            PhysicalTerminationOrigin(str(row["physical_termination_origin"]))
            if row["physical_termination_origin"] is not None
            else None
        ),
        physical_exit_evidence=(
            PhysicalExitEvidence(str(row["physical_exit_evidence"]))
            if row["physical_exit_evidence"] is not None
            else None
        ),
        exit_correlation_enabled=bool(int(row["exit_correlation_enabled"])),
        context_revision=int(row["context_revision"]),
        last_context=(
            _session_context_from_payload(context_payload)
            if context_payload is not None
            else None
        ),
        exited_at=(
            datetime_from_epoch_microseconds(int(row["exited_at_us"]))
            if row["exited_at_us"] is not None
            else None
        ),
        termination_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        terminated_at=(
            datetime_from_epoch_microseconds(int(row["terminated_at_us"]))
            if row["terminated_at_us"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        publication_revision=int(row["publication_revision"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


def _context_binding_from_row(row: sqlite3.Row) -> ContextBinding:
    return ContextBinding(
        context_binding_id=ContextBindingId(
            uuid_from_text(str(row["context_binding_id"]))
        ),
        entry_attempt_id=EntryAttemptId(
            uuid_from_text(str(row["entry_attempt_id"]))
        ),
        parking_session_id=ParkingSessionId(int(row["session_id"])),
        physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["physical_vehicle_id"]))
        ),
        state=ContextBindingState(str(row["domain_state"])),
        context_revision=int(row["context_revision"]),
        context=_session_context_from_payload(row["context_payload"]),
        termination_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        ended_at=(
            datetime_from_epoch_microseconds(int(row["ended_at_us"]))
            if row["ended_at_us"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        bound_at=datetime_from_epoch_microseconds(int(row["bound_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


def _entry_match_attempt_from_row(row: sqlite3.Row) -> EntryMatchAttempt:
    context_payload = row["authoritative_context_payload"]
    return EntryMatchAttempt(
        entry_attempt_id=EntryAttemptId(uuid_from_text(str(row["entry_attempt_id"]))),
        match_state=EntryMatchState(str(row["match_state"])),
        decision_state=EntryDecisionState(str(row["decision_state"])),
        decision_revision=int(row["decision_revision"]),
        authoritative_session_id=(
            ParkingSessionId(int(row["session_id"]))
            if row["session_id"] is not None
            else None
        ),
        authoritative_context=(
            _session_context_from_payload(context_payload)
            if context_payload is not None
            else None
        ),
        match_deadline_at=datetime_from_epoch_microseconds(
            int(row["match_deadline_at_us"])
        ),
        matched_physical_vehicle_id=(
            PhysicalVehicleId(uuid_from_text(str(row["physical_vehicle_id"])))
            if row["physical_vehicle_id"] is not None
            else None
        ),
        match_terminated_at=(
            datetime_from_epoch_microseconds(int(row["match_terminated_at_us"]))
            if row["match_terminated_at_us"] is not None
            else None
        ),
        terminal_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        created_at=datetime_from_epoch_microseconds(int(row["created_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
    )


class AcceptedInputRepository:
    """성공 응답 전에 inbound idempotency identity를 영속한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self, input_type: str, input_identity: str, input_revision: int
    ) -> AcceptedInputRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM accepted_inputs
            WHERE input_type = ? AND input_identity = ? AND input_revision = ?
            """,
            (input_type, input_identity, input_revision),
        ).fetchone()
        return _accepted_input_from_row(row) if row is not None else None

    def accept(
        self,
        *,
        input_type: str,
        input_identity: str,
        input_revision: int,
        request_payload: bytes | bytearray | memoryview,
        workflow_state: str,
        accepted_at_us: int | None = None,
    ) -> AcceptanceResult:
        """한 번만 삽입하고 byte가 같은 retry에는 기존 record를 반환한다."""

        require_write_transaction(self._connection)
        if input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        payload = _payload_bytes(request_payload)
        payload_hash = _sha256(payload)

        existing = self.get(input_type, input_identity, input_revision)
        if existing is not None:
            if existing.payload_hash != payload_hash or existing.request_payload != payload:
                raise AcceptedInputConflictError(
                    "input identity and revision were reused with a different payload"
                )
            return AcceptanceResult(record=existing, created=False)

        now = accepted_at_us if accepted_at_us is not None else _utc_now_microseconds()
        try:
            self._connection.execute(
                """
                INSERT INTO accepted_inputs(
                    input_type, input_identity, input_revision, payload_hash,
                    request_payload, workflow_state, result_payload,
                    accepted_at_us, updated_at_us, record_version
                ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)
                """,
                (
                    input_type,
                    input_identity,
                    input_revision,
                    payload_hash,
                    payload,
                    workflow_state,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise AcceptedInputConflictError(
                "input identity conflicts with an existing durable record"
            ) from error

        record = self.get(input_type, input_identity, input_revision)
        if record is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("accepted input disappeared during its transaction")
        return AcceptanceResult(record=record, created=True)


class PhysicalVehicleRepository:
    """PhysicalVehicle identity와 관측·absence checkpoint를 저장한다.

    ``ensure``는 tracking이 처음 생성한 identity만 추가한다. 기존
    row가 있으면 관측 snapshot을 암묵적으로 덮어쓰지 않고, 부재
    확정 임계가 같은 기존 snapshot을 반환한다.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> PhysicalVehicle | None:
        row = self._connection.execute(
            "SELECT * FROM physical_vehicles WHERE physical_vehicle_id = ?",
            (uuid_to_text(physical_vehicle_id),),
        ).fetchone()
        return _physical_vehicle_from_row(row) if row is not None else None

    def list_active(self) -> tuple[PhysicalVehicle, ...]:
        """worker restart에서 복원할 active 차량 checkpoint를 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM physical_vehicles
            WHERE domain_state = 'ACTIVE'
            ORDER BY created_at_us, physical_vehicle_id
            """
        ).fetchall()
        return tuple(_physical_vehicle_from_row(row) for row in rows)

    def ensure(self, vehicle: PhysicalVehicle) -> PhysicalVehicle:
        """없으면 추가하고, 이미 있으면 durable checkpoint를 반환한다."""

        require_write_transaction(self._connection)
        existing = self.get(vehicle.physical_vehicle_id)
        if existing is not None:
            if _seconds_to_microseconds(
                existing.absence_confirmation_seconds
            ) != _seconds_to_microseconds(vehicle.absence_confirmation_seconds):
                raise PhysicalVehicleConflictError(
                    "PhysicalVehicle absence confirmation threshold conflicts "
                    "with its durable identity"
                )
            if _seconds_to_microseconds(
                existing.trusted_sample_max_gap_seconds
            ) != _seconds_to_microseconds(
                vehicle.trusted_sample_max_gap_seconds
            ):
                raise PhysicalVehicleConflictError(
                    "PhysicalVehicle trusted sample gap conflicts with its "
                    "durable identity"
                )
            return existing

        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(vehicle.observation)
        )
        try:
            self._connection.execute(
                """
                INSERT INTO physical_vehicles(
                    physical_vehicle_id, domain_state, observation_state,
                    observation_reason, last_reliable_observed_at_us,
                    absence_trusted_duration_us,
                    absence_confirmation_duration_us,
                    trusted_sample_max_gap_duration_us,
                    absence_confirmed_at_us, termination_reason,
                    terminated_at_us, record_version, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_text(vehicle.physical_vehicle_id),
                    vehicle.state.value,
                    observation_state,
                    observation_reason,
                    last_reliable_at_us,
                    _seconds_to_microseconds(vehicle.absence_trusted_seconds),
                    _seconds_to_microseconds(vehicle.absence_confirmation_seconds),
                    _seconds_to_microseconds(
                        vehicle.trusted_sample_max_gap_seconds
                    ),
                    (
                        datetime_to_epoch_microseconds(
                            vehicle.absence_confirmed_at
                        )
                        if vehicle.absence_confirmed_at is not None
                        else None
                    ),
                    vehicle.termination_reason,
                    (
                        datetime_to_epoch_microseconds(vehicle.terminated_at)
                        if vehicle.terminated_at is not None
                        else None
                    ),
                    vehicle.record_version,
                    datetime_to_epoch_microseconds(vehicle.created_at),
                    datetime_to_epoch_microseconds(vehicle.updated_at),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise PhysicalVehicleConflictError(
                "PhysicalVehicle violates the durable state contract"
            ) from error

        persisted = self.get(vehicle.physical_vehicle_id)
        if persisted is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("PhysicalVehicle disappeared during its transaction")
        return persisted

    def save(
        self,
        vehicle: PhysicalVehicle,
        *,
        expected_record_version: int,
    ) -> None:
        """관측 상태와 신뢰 부재 누적을 optimistic checkpoint한다."""

        require_write_transaction(self._connection)
        if vehicle.record_version != expected_record_version + 1:
            raise ValueError(
                "vehicle.record_version must be exactly one greater than "
                "expected_record_version"
            )
        existing = self.get(vehicle.physical_vehicle_id)
        if existing is not None and _seconds_to_microseconds(
            existing.absence_confirmation_seconds
        ) != _seconds_to_microseconds(vehicle.absence_confirmation_seconds):
            raise PhysicalVehicleConflictError(
                "PhysicalVehicle absence confirmation threshold is immutable"
            )
        if existing is not None and _seconds_to_microseconds(
            existing.trusted_sample_max_gap_seconds
        ) != _seconds_to_microseconds(vehicle.trusted_sample_max_gap_seconds):
            raise PhysicalVehicleConflictError(
                "PhysicalVehicle trusted sample gap is immutable"
            )

        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(vehicle.observation)
        )
        try:
            new_version = optimistic_update(
                self._connection,
                table="physical_vehicles",
                key_column="physical_vehicle_id",
                key_value=uuid_to_text(vehicle.physical_vehicle_id),
                expected_record_version=expected_record_version,
                changes={
                    "domain_state": vehicle.state.value,
                    "observation_state": observation_state,
                    "observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "absence_trusted_duration_us": _seconds_to_microseconds(
                        vehicle.absence_trusted_seconds
                    ),
                    "absence_confirmed_at_us": (
                        datetime_to_epoch_microseconds(
                            vehicle.absence_confirmed_at
                        )
                        if vehicle.absence_confirmed_at is not None
                        else None
                    ),
                    "termination_reason": vehicle.termination_reason,
                    "terminated_at_us": (
                        datetime_to_epoch_microseconds(vehicle.terminated_at)
                        if vehicle.terminated_at is not None
                        else None
                    ),
                    "updated_at_us": datetime_to_epoch_microseconds(
                        vehicle.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise PhysicalVehicleConflictError(
                "PhysicalVehicle update violates the durable state contract"
            ) from error
        if new_version != vehicle.record_version:  # pragma: no cover - helper invariant.
            raise RuntimeError("optimistic update returned an unexpected record version")


class EntryMatchAttemptRepository:
    """EntryMatchAttempt snapshot을 SQLite domain row로 저장한다.

    connection은 호출 요청이 소유하며 repository는 자체 transaction을
    열지 않는다. 쓰기는 반드시 바깥 ``UnitOfWork`` 안에서 수행한다.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, entry_attempt_id: EntryAttemptId) -> EntryMatchAttempt | None:
        row = self._connection.execute(
            "SELECT * FROM entry_match_attempts WHERE entry_attempt_id = ?",
            (uuid_to_text(entry_attempt_id),),
        ).fetchone()
        return _entry_match_attempt_from_row(row) if row is not None else None

    def list_pending(self) -> tuple[EntryMatchAttempt, ...]:
        """매칭 대기 중인 attempt를 오래된 접수 순으로 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM entry_match_attempts
            WHERE match_state = 'PENDING'
            ORDER BY created_at_us, entry_attempt_id
            """
        ).fetchall()
        return tuple(_entry_match_attempt_from_row(row) for row in rows)

    def list_unbound_authoritative_matches(self) -> tuple[EntryMatchAttempt, ...]:
        """binding 없는 MATCHED+ALLOW attempt만 매칭 순서로 반환한다.

        이미 ENDED된 binding도 포함해 한 번이라도 binding row가 있는
        entryAttemptId는 제외한다. 전체 MATCHED 이력을 frame마다
        Python으로 복원하지 않고 SQLite에서 후보를 제한한다.
        """

        rows = self._connection.execute(
            """
            SELECT attempt.*
            FROM entry_match_attempts AS attempt
            LEFT JOIN context_bindings AS binding
              ON binding.entry_attempt_id = attempt.entry_attempt_id
            WHERE attempt.match_state = 'MATCHED'
              AND attempt.decision_state IN ('ALLOW', 'REVIEW_ALLOW')
              AND binding.context_binding_id IS NULL
            ORDER BY attempt.match_terminated_at_us, attempt.entry_attempt_id
            """
        ).fetchall()
        return tuple(_entry_match_attempt_from_row(row) for row in rows)

    def list_active_matched_physical_vehicle_ids(
        self,
    ) -> tuple[PhysicalVehicleId, ...]:
        """terminal 매칭을 이미 소비한 ACTIVE 차량 ID를 반환한다."""

        rows = self._connection.execute(
            """
            SELECT DISTINCT attempt.physical_vehicle_id
            FROM entry_match_attempts AS attempt
            JOIN physical_vehicles AS vehicle
              ON vehicle.physical_vehicle_id = attempt.physical_vehicle_id
            WHERE attempt.match_state = 'MATCHED'
              AND vehicle.domain_state = 'ACTIVE'
            ORDER BY attempt.physical_vehicle_id
            """
        ).fetchall()
        return tuple(
            PhysicalVehicleId(uuid_from_text(str(row[0]))) for row in rows
        )

    def add(self, attempt: EntryMatchAttempt) -> None:
        """새 attempt snapshot을 추가한다. 중복 identity는 conflict다."""

        require_write_transaction(self._connection)
        context_payload = (
            _session_context_to_payload(attempt.authoritative_context)
            if attempt.authoritative_context is not None
            else None
        )
        try:
            self._connection.execute(
                """
                INSERT INTO entry_match_attempts(
                    entry_attempt_id, match_state, decision_state,
                    decision_revision, session_id, physical_vehicle_id,
                    authoritative_context_payload, match_deadline_at_us,
                    termination_reason, match_terminated_at_us, record_version,
                    created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_text(attempt.entry_attempt_id),
                    attempt.match_state.value,
                    attempt.decision_state.value,
                    attempt.decision_revision,
                    (
                        int(attempt.authoritative_session_id)
                        if attempt.authoritative_session_id is not None
                        else None
                    ),
                    (
                        uuid_to_text(attempt.matched_physical_vehicle_id)
                        if attempt.matched_physical_vehicle_id is not None
                        else None
                    ),
                    context_payload,
                    datetime_to_epoch_microseconds(attempt.match_deadline_at),
                    attempt.terminal_reason,
                    (
                        datetime_to_epoch_microseconds(attempt.match_terminated_at)
                        if attempt.match_terminated_at is not None
                        else None
                    ),
                    attempt.record_version,
                    datetime_to_epoch_microseconds(attempt.created_at),
                    datetime_to_epoch_microseconds(attempt.updated_at),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise EntryMatchAttemptConflictError(
                "entryAttemptId conflicts with an existing durable attempt"
            ) from error

    def save(
        self,
        attempt: EntryMatchAttempt,
        *,
        expected_record_version: int,
    ) -> None:
        """Coordinator가 만든 다음 snapshot을 optimistic update한다."""

        require_write_transaction(self._connection)
        if attempt.record_version != expected_record_version + 1:
            raise ValueError(
                "attempt.record_version must be exactly one greater than "
                "expected_record_version"
            )
        context_payload = (
            _session_context_to_payload(attempt.authoritative_context)
            if attempt.authoritative_context is not None
            else None
        )
        try:
            new_version = optimistic_update(
                self._connection,
                table="entry_match_attempts",
                key_column="entry_attempt_id",
                key_value=uuid_to_text(attempt.entry_attempt_id),
                expected_record_version=expected_record_version,
                changes={
                    "match_state": attempt.match_state.value,
                    "decision_state": attempt.decision_state.value,
                    "decision_revision": attempt.decision_revision,
                    "session_id": (
                        int(attempt.authoritative_session_id)
                        if attempt.authoritative_session_id is not None
                        else None
                    ),
                    "physical_vehicle_id": (
                        uuid_to_text(attempt.matched_physical_vehicle_id)
                        if attempt.matched_physical_vehicle_id is not None
                        else None
                    ),
                    "authoritative_context_payload": context_payload,
                    "match_deadline_at_us": datetime_to_epoch_microseconds(
                        attempt.match_deadline_at
                    ),
                    "termination_reason": attempt.terminal_reason,
                    "match_terminated_at_us": (
                        datetime_to_epoch_microseconds(attempt.match_terminated_at)
                        if attempt.match_terminated_at is not None
                        else None
                    ),
                    "updated_at_us": datetime_to_epoch_microseconds(
                        attempt.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise EntryMatchAttemptConflictError(
                "EntryMatchAttempt update violates the durable state contract"
            ) from error
        if new_version != attempt.record_version:  # pragma: no cover - helper invariant.
            raise RuntimeError("optimistic update returned an unexpected record version")


class ParkingSessionMirrorRepository:
    """Backend session의 행정 상태와 현장 presence mirror를 저장한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self,
        parking_session_id: ParkingSessionId,
    ) -> ParkingSessionMirror | None:
        row = self._connection.execute(
            "SELECT * FROM parking_session_mirrors WHERE session_id = ?",
            (int(parking_session_id),),
        ).fetchone()
        return _parking_session_mirror_from_row(row) if row is not None else None

    def add(self, mirror: ParkingSessionMirror) -> None:
        """새 session mirror를 추가하며 identity·FK 충돌을 번역한다."""

        require_write_transaction(self._connection)
        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(mirror.physical_observation)
        )
        context_payload = (
            _session_context_to_payload(mirror.last_context)
            if mirror.last_context is not None
            else None
        )
        try:
            self._connection.execute(
                """
                INSERT INTO parking_session_mirrors(
                    session_id, entry_attempt_id, physical_vehicle_id,
                    administrative_state, physical_presence_state,
                    physical_observation_state, physical_observation_reason,
                    last_reliable_observed_at_us, physical_termination_origin,
                    physical_exit_evidence, exit_correlation_enabled,
                    context_revision, last_context_payload, exited_at_us,
                    termination_reason, terminated_at_us, record_version,
                    publication_revision, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(mirror.parking_session_id),
                    (
                        uuid_to_text(mirror.entry_attempt_id)
                        if mirror.entry_attempt_id is not None
                        else None
                    ),
                    (
                        uuid_to_text(mirror.physical_vehicle_id)
                        if mirror.physical_vehicle_id is not None
                        else None
                    ),
                    mirror.administrative_state.value,
                    mirror.physical_presence_state.value,
                    observation_state,
                    observation_reason,
                    last_reliable_at_us,
                    (
                        mirror.physical_termination_origin.value
                        if mirror.physical_termination_origin is not None
                        else None
                    ),
                    (
                        mirror.physical_exit_evidence.value
                        if mirror.physical_exit_evidence is not None
                        else None
                    ),
                    int(mirror.exit_correlation_enabled),
                    mirror.context_revision,
                    context_payload,
                    (
                        datetime_to_epoch_microseconds(mirror.exited_at)
                        if mirror.exited_at is not None
                        else None
                    ),
                    mirror.termination_reason,
                    (
                        datetime_to_epoch_microseconds(mirror.terminated_at)
                        if mirror.terminated_at is not None
                        else None
                    ),
                    mirror.record_version,
                    mirror.publication_revision,
                    datetime_to_epoch_microseconds(mirror.created_at),
                    datetime_to_epoch_microseconds(mirror.updated_at),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ParkingSessionMirrorConflictError(
                "ParkingSessionMirror violates an identity, FK, or state contract"
            ) from error

    def save(
        self,
        mirror: ParkingSessionMirror,
        *,
        expected_record_version: int,
    ) -> None:
        """session·presence snapshot을 optimistic update한다."""

        require_write_transaction(self._connection)
        if mirror.record_version != expected_record_version + 1:
            raise ValueError(
                "mirror.record_version must be exactly one greater than "
                "expected_record_version"
            )
        observation_state, observation_reason, last_reliable_at_us = (
            _observation_columns(mirror.physical_observation)
        )
        context_payload = (
            _session_context_to_payload(mirror.last_context)
            if mirror.last_context is not None
            else None
        )
        try:
            new_version = optimistic_update(
                self._connection,
                table="parking_session_mirrors",
                key_column="session_id",
                key_value=int(mirror.parking_session_id),
                expected_record_version=expected_record_version,
                changes={
                    "entry_attempt_id": (
                        uuid_to_text(mirror.entry_attempt_id)
                        if mirror.entry_attempt_id is not None
                        else None
                    ),
                    "physical_vehicle_id": (
                        uuid_to_text(mirror.physical_vehicle_id)
                        if mirror.physical_vehicle_id is not None
                        else None
                    ),
                    "administrative_state": mirror.administrative_state.value,
                    "physical_presence_state": mirror.physical_presence_state.value,
                    "physical_observation_state": observation_state,
                    "physical_observation_reason": observation_reason,
                    "last_reliable_observed_at_us": last_reliable_at_us,
                    "physical_termination_origin": (
                        mirror.physical_termination_origin.value
                        if mirror.physical_termination_origin is not None
                        else None
                    ),
                    "physical_exit_evidence": (
                        mirror.physical_exit_evidence.value
                        if mirror.physical_exit_evidence is not None
                        else None
                    ),
                    "exit_correlation_enabled": int(
                        mirror.exit_correlation_enabled
                    ),
                    "context_revision": mirror.context_revision,
                    "last_context_payload": context_payload,
                    "exited_at_us": (
                        datetime_to_epoch_microseconds(mirror.exited_at)
                        if mirror.exited_at is not None
                        else None
                    ),
                    "termination_reason": mirror.termination_reason,
                    "terminated_at_us": (
                        datetime_to_epoch_microseconds(mirror.terminated_at)
                        if mirror.terminated_at is not None
                        else None
                    ),
                    "publication_revision": mirror.publication_revision,
                    "updated_at_us": datetime_to_epoch_microseconds(
                        mirror.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise ParkingSessionMirrorConflictError(
                "ParkingSessionMirror update violates an identity, FK, or state contract"
            ) from error
        if new_version != mirror.record_version:  # pragma: no cover - helper invariant.
            raise RuntimeError("optimistic update returned an unexpected record version")


class ContextBindingRepository:
    """ContextBinding snapshot과 active cardinality를 SQLite에 보존한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self,
        context_binding_id: ContextBindingId,
    ) -> ContextBinding | None:
        row = self._connection.execute(
            "SELECT * FROM context_bindings WHERE context_binding_id = ?",
            (uuid_to_text(context_binding_id),),
        ).fetchone()
        return _context_binding_from_row(row) if row is not None else None

    def get_by_entry_attempt_id(
        self,
        entry_attempt_id: EntryAttemptId,
    ) -> ContextBinding | None:
        """immutable entryAttempt correlation으로 active·ended binding을 조회한다."""

        row = self._connection.execute(
            "SELECT * FROM context_bindings WHERE entry_attempt_id = ?",
            (uuid_to_text(entry_attempt_id),),
        ).fetchone()
        return _context_binding_from_row(row) if row is not None else None

    def list_active(self) -> tuple[ContextBinding, ...]:
        """현재 BOUND binding을 결정적인 생성 순서로 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM context_bindings
            WHERE domain_state = 'BOUND'
            ORDER BY bound_at_us, context_binding_id
            """
        ).fetchall()
        return tuple(_context_binding_from_row(row) for row in rows)

    def add(self, binding: ContextBinding) -> None:
        """새 immutable correlation을 추가하고 DB cardinality 충돌을 번역한다."""

        require_write_transaction(self._connection)
        try:
            self._connection.execute(
                """
                INSERT INTO context_bindings(
                    context_binding_id, entry_attempt_id, session_id,
                    physical_vehicle_id, domain_state, context_revision,
                    context_payload, termination_reason, ended_at_us,
                    record_version, bound_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid_to_text(binding.context_binding_id),
                    uuid_to_text(binding.entry_attempt_id),
                    int(binding.parking_session_id),
                    uuid_to_text(binding.physical_vehicle_id),
                    binding.state.value,
                    binding.context_revision,
                    _session_context_to_payload(binding.context),
                    binding.termination_reason,
                    (
                        datetime_to_epoch_microseconds(binding.ended_at)
                        if binding.ended_at is not None
                        else None
                    ),
                    binding.record_version,
                    datetime_to_epoch_microseconds(binding.bound_at),
                    datetime_to_epoch_microseconds(binding.updated_at),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise ContextBindingConflictError(
                "ContextBinding violates an identity, FK, state, or active-cardinality contract"
            ) from error

    def save(
        self,
        binding: ContextBinding,
        *,
        expected_record_version: int,
    ) -> None:
        """binding context·lifecycle snapshot을 optimistic update한다."""

        require_write_transaction(self._connection)
        if binding.record_version != expected_record_version + 1:
            raise ValueError(
                "binding.record_version must be exactly one greater than "
                "expected_record_version"
            )
        try:
            new_version = optimistic_update(
                self._connection,
                table="context_bindings",
                key_column="context_binding_id",
                key_value=uuid_to_text(binding.context_binding_id),
                expected_record_version=expected_record_version,
                changes={
                    "domain_state": binding.state.value,
                    "context_revision": binding.context_revision,
                    "context_payload": _session_context_to_payload(binding.context),
                    "termination_reason": binding.termination_reason,
                    "ended_at_us": (
                        datetime_to_epoch_microseconds(binding.ended_at)
                        if binding.ended_at is not None
                        else None
                    ),
                    "updated_at_us": datetime_to_epoch_microseconds(
                        binding.updated_at
                    ),
                },
            )
        except sqlite3.IntegrityError as error:
            raise ContextBindingConflictError(
                "ContextBinding update violates the durable state contract"
            ) from error
        if new_version != binding.record_version:  # pragma: no cover - helper invariant.
            raise RuntimeError("optimistic update returned an unexpected record version")


class OutboxRepository:
    """aggregate publication revision마다 immutable payload 하나를 만든다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_publication(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        destination: str,
        publication_revision: int,
    ) -> OutboxRecord | None:
        row = self._connection.execute(
            """
            SELECT * FROM outbox
            WHERE aggregate_type = ? AND aggregate_id = ?
              AND destination = ? AND publication_revision = ?
            """,
            (aggregate_type, aggregate_id, destination, publication_revision),
        ).fetchone()
        return _outbox_from_row(row) if row is not None else None

    def enqueue(
        self,
        *,
        delivery_id: str,
        aggregate_type: str,
        aggregate_id: str,
        destination: str,
        publication_revision: int,
        transition_type: str,
        payload: bytes | bytearray | memoryview,
        idempotency_key: str,
        created_at_us: int | None = None,
    ) -> OutboxEnqueueResult:
        require_write_transaction(self._connection)
        if publication_revision < 1:
            raise ValueError("publication_revision must be positive")
        immutable_payload = _payload_bytes(payload)
        payload_hash = _sha256(immutable_payload)

        existing = self.get_by_publication(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            destination=destination,
            publication_revision=publication_revision,
        )
        if existing is not None:
            immutable_identity = (
                existing.delivery_id,
                existing.transition_type,
                existing.payload,
                existing.payload_hash,
                existing.idempotency_key,
            )
            requested_identity = (
                delivery_id,
                transition_type,
                immutable_payload,
                payload_hash,
                idempotency_key,
            )
            if immutable_identity != requested_identity:
                raise OutboxConflictError(
                    "publication identity was reused with different immutable data"
                )
            return OutboxEnqueueResult(record=existing, created=False)

        now = created_at_us if created_at_us is not None else _utc_now_microseconds()
        try:
            self._connection.execute(
                """
                INSERT INTO outbox(
                    delivery_id, aggregate_type, aggregate_id, destination,
                    publication_revision, transition_type, payload, payload_hash,
                    idempotency_key, delivery_state, attempt_count,
                    next_attempt_at_us, last_error, created_at_us, updated_at_us,
                    confirmed_at_us, record_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0,
                          NULL, NULL, ?, ?, NULL, 1)
                """,
                (
                    delivery_id,
                    aggregate_type,
                    aggregate_id,
                    destination,
                    publication_revision,
                    transition_type,
                    immutable_payload,
                    payload_hash,
                    idempotency_key,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise OutboxConflictError(
                "delivery or idempotency identity conflicts with an existing outbox row"
            ) from error

        record = self.get_by_publication(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            destination=destination,
            publication_revision=publication_revision,
        )
        if record is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("outbox record disappeared during its transaction")
        return OutboxEnqueueResult(record=record, created=True)


def _quoted_identifier(identifier: str) -> str:
    if _SQL_IDENTIFIER.fullmatch(identifier) is None:
        raise ValueError(f"unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def optimistic_update(
    connection: sqlite3.Connection,
    *,
    table: str,
    key_column: str,
    key_value: Any,
    expected_record_version: int,
    changes: Mapping[str, Any],
) -> int:
    """field 변경과 ``record_version`` 증가를 원자적으로 수행한다.

    새 version을 반환한다. 누락 record와 stale version은 어느 쪽도 안전하게
    덮어쓸 수 없으므로 같은 오류로 처리한다.
    """

    require_write_transaction(connection)
    if expected_record_version < 1:
        raise ValueError("expected_record_version must be positive")
    if not changes:
        raise ValueError("optimistic update requires at least one field")
    if "record_version" in changes:
        raise ValueError("record_version is managed by optimistic_update")

    table_sql = _quoted_identifier(table)
    key_sql = _quoted_identifier(key_column)
    ordered_changes = sorted(changes.items())
    assignments = ", ".join(
        f"{_quoted_identifier(column)} = ?" for column, _ in ordered_changes
    )
    values = [value for _, value in ordered_changes]
    values.extend((key_value, expected_record_version))
    cursor = connection.execute(
        f"""
        UPDATE {table_sql}
        SET {assignments}, record_version = record_version + 1
        WHERE {key_sql} = ? AND record_version = ?
        """,
        values,
    )
    if cursor.rowcount != 1:
        raise OptimisticConcurrencyError(
            f"{table}.{key_column}={key_value!r} is missing or has a newer version"
        )
    return expected_record_version + 1

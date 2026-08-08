"""durable input·pending handoff·session·transactional outbox repository."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

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
from src.parking.models import IncidentId
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
from .models import (
    AcceptedInputRecord,
    OutboxRecord,
    PendingHandoffRecord,
    PendingHandoffState,
    PublicationApplicationStatus,
)
from .unit_of_work import require_write_transaction

if TYPE_CHECKING:
    from src.communication.models import (
        MoveRequestId,
        MoveVerificationAttempt,
        MoveVerificationIncidentResult,
    )

_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class AcceptedInputConflictError(RuntimeError):
    """같은 input identity·revision이 다른 payload로 재사용됐다."""


class OutboxConflictError(RuntimeError):
    """outbox publication identity가 다른 immutable data로 재사용됐다."""


class OutboxAlreadyDeliveredError(RuntimeError):
    """publication의 Backend application receipt가 이미 보존돼 있다."""


class OutboxStateError(RuntimeError):
    """outbox delivery state가 요청한 명시적 전이를 허용하지 않는다."""


class PendingHandoffConflictError(RuntimeError):
    """pending handoff identity가 다른 local fact에 재사용됐다."""


class PendingHandoffStateError(RuntimeError):
    """pending handoff state·disposition·delivery 조합이 계약을 어겼다."""


class EntryMatchAttemptConflictError(RuntimeError):
    """이미 존재하는 entryAttemptId를 새 attempt로 재사용했다."""


class PhysicalVehicleConflictError(RuntimeError):
    """PhysicalVehicle identity·checkpoint가 durable row와 충돌했다."""


class ParkingSessionMirrorConflictError(RuntimeError):
    """ParkingSessionMirror가 unique·FK·state 계약을 어겼다."""


class ContextBindingConflictError(RuntimeError):
    """ContextBinding이 immutable identity·active cardinality와 충돌했다."""


class MoveVerificationAttemptConflictError(RuntimeError):
    """MoveVerificationAttempt identity 또는 immutable command가 충돌했다."""


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


@dataclass(frozen=True)
class PendingHandoffEnsureResult:
    record: PendingHandoffRecord
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
        idempotency_key=(
            str(row["idempotency_key"])
            if row["idempotency_key"] is not None
            else None
        ),
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


def _pending_handoff_from_row(row: sqlite3.Row) -> PendingHandoffRecord:
    record = PendingHandoffRecord(
        handoff_id=str(row["handoff_id"]),
        aggregate_type=str(row["aggregate_type"]),
        aggregate_id=str(row["aggregate_id"]),
        transition_type=str(row["transition_type"]),
        original_occurred_at_us=int(row["original_occurred_at_us"]),
        workflow_state=PendingHandoffState(str(row["workflow_state"])),
        disposition_reason=(
            str(row["disposition_reason"])
            if row["disposition_reason"] is not None
            else None
        ),
        materialized_delivery_id=(
            str(row["materialized_delivery_id"])
            if row["materialized_delivery_id"] is not None
            else None
        ),
        expires_at_us=int(row["expires_at_us"]),
        record_version=int(row["record_version"]),
        created_at_us=int(row["created_at_us"]),
        updated_at_us=int(row["updated_at_us"]),
    )
    _validate_pending_handoff_state(record)
    return record


def _validate_pending_handoff_state(record: PendingHandoffRecord) -> None:
    """DB CHECK가 표현하지 못한 nullable field 조합을 검증한다."""

    if record.workflow_state is PendingHandoffState.WAITING_CORRELATION:
        if (
            record.disposition_reason is not None
            or record.materialized_delivery_id is not None
        ):
            raise PendingHandoffStateError(
                "WAITING_CORRELATION handoff cannot have a disposition or delivery"
            )
        return
    if record.workflow_state is PendingHandoffState.MATERIALIZED:
        if (
            not record.materialized_delivery_id
            or record.disposition_reason is not None
        ):
            raise PendingHandoffStateError(
                "MATERIALIZED handoff requires only materialized_delivery_id"
            )
        return
    if not record.disposition_reason or record.materialized_delivery_id is not None:
        raise PendingHandoffStateError(
            "EXPIRED handoff requires only disposition_reason"
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


def _incident_ids_to_payload(incident_ids: tuple[IncidentId, ...]) -> bytes:
    return json.dumps(
        [uuid_to_text(incident_id) for incident_id in incident_ids],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _incident_ids_from_payload(
    payload: bytes | bytearray | memoryview,
) -> tuple[IncidentId, ...]:
    try:
        raw = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("invalid target Incident payload") from error
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError("target Incident payload must be a JSON string array")
    return tuple(IncidentId(uuid_from_text(item)) for item in raw)


def _move_verification_incident_results_from_payload(
    payload: bytes | bytearray | memoryview | None,
) -> tuple[MoveVerificationIncidentResult, ...]:
    from src.communication.models import (
        MoveVerificationIncidentResult,
        MoveVerificationResult,
    )

    if payload is None:
        return ()
    try:
        raw = json.loads(bytes(payload).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as error:
        raise ValueError("invalid MoveVerification incident results payload") from error
    if not isinstance(raw, list):
        raise ValueError("MoveVerification incident results must be a JSON array")
    try:
        return tuple(
            MoveVerificationIncidentResult(
                incident_id=IncidentId(uuid_from_text(str(item["incidentId"]))),
                result=MoveVerificationResult(str(item["result"])),
                incident_publication_revision=int(
                    item["incidentPublicationRevision"]
                ),
            )
            for item in raw
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            "invalid MoveVerification incident result item"
        ) from error


def _move_verification_attempt_from_row(
    row: sqlite3.Row,
) -> MoveVerificationAttempt:
    # communication package는 outbox를 통해 이 repository를 import한다.
    # 런타임 import를 row 복원 시점으로 늦춰 module initialization cycle을 막는다.
    from src.communication.models import (
        MoveRequestId,
        MoveVerificationAttempt,
        MoveVerificationResult,
        MoveVerificationState,
    )

    return MoveVerificationAttempt(
        request_id=MoveRequestId(int(row["request_id"])),
        verification_attempt=int(row["verification_attempt"]),
        subject_physical_vehicle_id=PhysicalVehicleId(
            uuid_from_text(str(row["subject_physical_vehicle_id"]))
        ),
        target_incident_ids=_incident_ids_from_payload(
            row["target_incident_ids_payload"]
        ),
        command_payload_hash=str(row["command_payload_hash"]),
        state=MoveVerificationState(str(row["domain_state"])),
        result=(
            MoveVerificationResult(str(row["result"]))
            if row["result"] is not None
            else None
        ),
        incident_results=_move_verification_incident_results_from_payload(
            row["per_incident_results_payload"]
        ),
        deadline_at=(
            datetime_from_epoch_microseconds(int(row["deadline_at_us"]))
            if row["deadline_at_us"] is not None
            else None
        ),
        terminal_reason=(
            str(row["termination_reason"])
            if row["termination_reason"] is not None
            else None
        ),
        record_version=int(row["record_version"]),
        publication_revision=int(row["publication_revision"]),
        accepted_at=datetime_from_epoch_microseconds(int(row["accepted_at_us"])),
        updated_at=datetime_from_epoch_microseconds(int(row["updated_at_us"])),
        completed_at=(
            datetime_from_epoch_microseconds(int(row["completed_at_us"]))
            if row["completed_at_us"] is not None
            else None
        ),
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

    def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> AcceptedInputRecord | None:
        row = self._connection.execute(
            "SELECT * FROM accepted_inputs WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return _accepted_input_from_row(row) if row is not None else None

    def accept(
        self,
        *,
        input_type: str,
        input_identity: str,
        input_revision: int,
        idempotency_key: str,
        request_payload: bytes | bytearray | memoryview,
        workflow_state: str,
        accepted_at_us: int | None = None,
    ) -> AcceptanceResult:
        """한 번만 삽입하고 byte가 같은 retry에는 기존 record를 반환한다."""

        require_write_transaction(self._connection)
        if input_revision < 0:
            raise ValueError("input_revision must be non-negative")
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ValueError("idempotency_key must not be empty")
        payload = _payload_bytes(request_payload)
        payload_hash = _sha256(payload)

        key_record = self.get_by_idempotency_key(normalized_key)
        if key_record is not None:
            if (
                key_record.input_type != input_type
                or key_record.input_identity != input_identity
                or key_record.input_revision != input_revision
                or key_record.payload_hash != payload_hash
                or key_record.request_payload != payload
            ):
                raise AcceptedInputConflictError(
                    "Idempotency-Key was reused for a different input"
                )
            return AcceptanceResult(record=key_record, created=False)

        existing = self.get(input_type, input_identity, input_revision)
        if existing is not None:
            if existing.payload_hash != payload_hash or existing.request_payload != payload:
                raise AcceptedInputConflictError(
                    "input identity and revision were reused with a different payload"
                )
            if existing.idempotency_key is not None:
                raise AcceptedInputConflictError(
                    "input identity and revision were retried with a different Idempotency-Key"
                )
            self._connection.execute(
                """
                UPDATE accepted_inputs
                SET idempotency_key = ?, updated_at_us = ?,
                    record_version = record_version + 1
                WHERE input_type = ? AND input_identity = ? AND input_revision = ?
                """,
                (
                    normalized_key,
                    _utc_now_microseconds(),
                    input_type,
                    input_identity,
                    input_revision,
                ),
            )
            adopted = self.get(input_type, input_identity, input_revision)
            if adopted is None:  # pragma: no cover - broken SQLite connection.
                raise RuntimeError("accepted input disappeared while adopting its key")
            return AcceptanceResult(record=adopted, created=False)

        now = accepted_at_us if accepted_at_us is not None else _utc_now_microseconds()
        try:
            self._connection.execute(
                """
                INSERT INTO accepted_inputs(
                    input_type, input_identity, input_revision, idempotency_key,
                    payload_hash,
                    request_payload, workflow_state, result_payload,
                    accepted_at_us, updated_at_us, record_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, 1)
                """,
                (
                    input_type,
                    input_identity,
                    input_revision,
                    normalized_key,
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


class MoveVerificationAttemptRepository:
    """Backend 재확인 command의 immutable scope와 workflow 상태를 저장한다."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(
        self,
        request_id: MoveRequestId,
        verification_attempt: int,
    ) -> MoveVerificationAttempt | None:
        row = self._connection.execute(
            """
            SELECT * FROM move_verification_attempts
            WHERE request_id = ? AND verification_attempt = ?
            """,
            (int(request_id), verification_attempt),
        ).fetchone()
        return (
            _move_verification_attempt_from_row(row)
            if row is not None
            else None
        )

    def get_latest(
        self,
        request_id: MoveRequestId,
    ) -> MoveVerificationAttempt | None:
        """한 MoveRequest에서 가장 큰 verificationAttempt를 반환한다."""

        row = self._connection.execute(
            """
            SELECT * FROM move_verification_attempts
            WHERE request_id = ?
            ORDER BY verification_attempt DESC
            LIMIT 1
            """,
            (int(request_id),),
        ).fetchone()
        return (
            _move_verification_attempt_from_row(row)
            if row is not None
            else None
        )

    def list_non_terminal(self) -> tuple[MoveVerificationAttempt, ...]:
        """실행 또는 재시작 복구가 필요한 command를 접수 순서로 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM move_verification_attempts
            WHERE domain_state IN ('ACCEPTED', 'CHECKING')
            ORDER BY accepted_at_us, request_id, verification_attempt
            """
        ).fetchall()
        return tuple(_move_verification_attempt_from_row(row) for row in rows)

    def add(self, attempt: MoveVerificationAttempt) -> None:
        """신규 ACCEPTED command를 추가한다. 같은 identity는 conflict다."""

        require_write_transaction(self._connection)
        try:
            self._connection.execute(
                """
                INSERT INTO move_verification_attempts(
                    request_id, verification_attempt,
                    subject_physical_vehicle_id,
                    target_incident_ids_payload, command_payload_hash,
                    domain_state, result, per_incident_results_payload,
                    deadline_at_us, termination_reason, record_version,
                    publication_revision, accepted_at_us, updated_at_us,
                    completed_at_us
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(attempt.request_id),
                    attempt.verification_attempt,
                    uuid_to_text(attempt.subject_physical_vehicle_id),
                    _incident_ids_to_payload(attempt.target_incident_ids),
                    attempt.command_payload_hash,
                    attempt.state.value,
                    attempt.result.value if attempt.result is not None else None,
                    (
                        json.dumps(
                            [
                                {
                                    "incidentId": uuid_to_text(item.incident_id),
                                    "incidentPublicationRevision": (
                                        item.incident_publication_revision
                                    ),
                                    "result": item.result.value,
                                }
                                for item in attempt.incident_results
                            ],
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ).encode("utf-8")
                        if attempt.incident_results
                        else None
                    ),
                    (
                        datetime_to_epoch_microseconds(attempt.deadline_at)
                        if attempt.deadline_at is not None
                        else None
                    ),
                    attempt.terminal_reason,
                    attempt.record_version,
                    attempt.publication_revision,
                    datetime_to_epoch_microseconds(attempt.accepted_at),
                    datetime_to_epoch_microseconds(attempt.updated_at),
                    (
                        datetime_to_epoch_microseconds(attempt.completed_at)
                        if attempt.completed_at is not None
                        else None
                    ),
                ),
            )
        except sqlite3.IntegrityError as error:
            raise MoveVerificationAttemptConflictError(
                "MoveVerificationAttempt identity 또는 state가 충돌합니다."
            ) from error

    def save(
        self,
        attempt: MoveVerificationAttempt,
        *,
        expected_record_version: int,
    ) -> None:
        """실행 상태와 immutable 결과를 optimistic update한다."""

        from src.communication.models import MoveVerificationState

        require_write_transaction(self._connection)
        if attempt.record_version != expected_record_version + 1:
            raise ValueError(
                "attempt.record_version must be exactly one greater than "
                "expected_record_version"
            )
        existing = self.get(
            attempt.request_id,
            attempt.verification_attempt,
        )
        if existing is None:
            raise MoveVerificationAttemptConflictError(
                "MoveVerificationAttempt를 찾을 수 없습니다."
            )
        immutable_fields = (
            "subject_physical_vehicle_id",
            "target_incident_ids",
            "command_payload_hash",
            "deadline_at",
            "accepted_at",
        )
        if any(
            getattr(attempt, field_name) != getattr(existing, field_name)
            for field_name in immutable_fields
        ):
            raise MoveVerificationAttemptConflictError(
                "MoveVerificationAttempt command scope는 변경할 수 없습니다."
            )
        allowed_states = {
            MoveVerificationState.ACCEPTED: {
                MoveVerificationState.CHECKING,
                MoveVerificationState.CANCELED,
                MoveVerificationState.FAILED,
            },
            MoveVerificationState.CHECKING: {
                MoveVerificationState.COMPLETED,
                MoveVerificationState.CANCELED,
                MoveVerificationState.FAILED,
            },
        }
        if attempt.state not in allowed_states.get(existing.state, set()):
            raise MoveVerificationAttemptConflictError(
                f"허용되지 않은 MoveVerificationAttempt 전이입니다: "
                f"{existing.state.value} -> {attempt.state.value}"
            )

        results_payload = (
            json.dumps(
                [
                    {
                        "incidentId": uuid_to_text(item.incident_id),
                        "incidentPublicationRevision": (
                            item.incident_publication_revision
                        ),
                        "result": item.result.value,
                    }
                    for item in attempt.incident_results
                ],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if attempt.incident_results
            else None
        )
        try:
            cursor = self._connection.execute(
                """
                UPDATE move_verification_attempts
                SET domain_state = ?, result = ?,
                    per_incident_results_payload = ?, termination_reason = ?,
                    publication_revision = ?, updated_at_us = ?,
                    completed_at_us = ?, record_version = ?
                WHERE request_id = ? AND verification_attempt = ?
                  AND record_version = ?
                """,
                (
                    attempt.state.value,
                    (
                        attempt.result.value
                        if attempt.result is not None
                        else None
                    ),
                    results_payload,
                    attempt.terminal_reason,
                    attempt.publication_revision,
                    datetime_to_epoch_microseconds(attempt.updated_at),
                    (
                        datetime_to_epoch_microseconds(attempt.completed_at)
                        if attempt.completed_at is not None
                        else None
                    ),
                    attempt.record_version,
                    int(attempt.request_id),
                    attempt.verification_attempt,
                    expected_record_version,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise MoveVerificationAttemptConflictError(
                "MoveVerificationAttempt update가 durable state 계약을 위반했습니다."
            ) from error
        if cursor.rowcount != 1:
            raise OptimisticConcurrencyError(
                "MoveVerificationAttempt가 없거나 더 최신 version입니다: "
                f"{int(attempt.request_id)}:{attempt.verification_attempt}"
            )


class PendingHandoffRepository:
    """correlation 전 local fact의 publication eligibility marker를 저장한다.

    aggregate snapshot과 outbox를 같은 transaction에서 바꾸는 application
    workflow가 이 repository의 외부 ``UnitOfWork``를 소유한다. marker는
    ``WAITING_CORRELATION``으로만 생성하고 한 번 소비되거나
    만료되면 다시 waiting으로 되돌리지 않는다.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, handoff_id: str) -> PendingHandoffRecord | None:
        row = self._connection.execute(
            "SELECT * FROM pending_handoffs WHERE handoff_id = ?",
            (handoff_id,),
        ).fetchone()
        return _pending_handoff_from_row(row) if row is not None else None

    def get_by_identity(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        transition_type: str,
        original_occurred_at_us: int,
    ) -> PendingHandoffRecord | None:
        """local fact의 immutable composite identity로 marker를 조회한다."""

        row = self._connection.execute(
            """
            SELECT * FROM pending_handoffs
            WHERE aggregate_type = ? AND aggregate_id = ?
              AND transition_type = ? AND original_occurred_at_us = ?
            """,
            (
                aggregate_type,
                aggregate_id,
                transition_type,
                original_occurred_at_us,
            ),
        ).fetchone()
        return _pending_handoff_from_row(row) if row is not None else None

    def list_waiting(self) -> tuple[PendingHandoffRecord, ...]:
        """materialize 대상을 원래 occurredAt 순서로 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM pending_handoffs
            WHERE workflow_state = 'WAITING_CORRELATION'
            ORDER BY original_occurred_at_us, created_at_us, handoff_id
            """
        ).fetchall()
        return tuple(_pending_handoff_from_row(row) for row in rows)

    def list_waiting_for_aggregate(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
    ) -> tuple[PendingHandoffRecord, ...]:
        """aggregate 하나의 누락 publication을 원래 순서로 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM pending_handoffs
            WHERE workflow_state = 'WAITING_CORRELATION'
              AND aggregate_type = ? AND aggregate_id = ?
            ORDER BY original_occurred_at_us, created_at_us, handoff_id
            """,
            (aggregate_type, aggregate_id),
        ).fetchall()
        return tuple(_pending_handoff_from_row(row) for row in rows)

    def list_due(self, *, now_us: int) -> tuple[PendingHandoffRecord, ...]:
        """application이 terminal·correlation 조건을 추가 판정할 만료 후보다."""

        rows = self._connection.execute(
            """
            SELECT * FROM pending_handoffs
            WHERE workflow_state = 'WAITING_CORRELATION'
              AND expires_at_us <= ?
            ORDER BY expires_at_us, original_occurred_at_us, handoff_id
            """,
            (now_us,),
        ).fetchall()
        return tuple(_pending_handoff_from_row(row) for row in rows)

    def ensure_waiting(
        self,
        record: PendingHandoffRecord,
    ) -> PendingHandoffEnsureResult:
        """local fact marker를 한 번만 삽입하고 같은 retry를 합친다.

        composite identity와 handoffId가 모두 같으면 이미 terminal인
        marker도 그대로 반환한다. 이로써 frame retry가 MATERIALIZED
        또는 EXPIRED marker를 다시 열지 않는다.
        """

        require_write_transaction(self._connection)
        self._validate_new_waiting(record)

        existing_by_identity = self.get_by_identity(
            aggregate_type=record.aggregate_type,
            aggregate_id=record.aggregate_id,
            transition_type=record.transition_type,
            original_occurred_at_us=record.original_occurred_at_us,
        )
        if existing_by_identity is not None:
            if existing_by_identity.handoff_id != record.handoff_id:
                raise PendingHandoffConflictError(
                    "pending handoff fact identity was reused with another handoff_id"
                )
            return PendingHandoffEnsureResult(
                record=existing_by_identity,
                created=False,
            )

        existing_by_id = self.get(record.handoff_id)
        if existing_by_id is not None:
            raise PendingHandoffConflictError(
                "handoff_id was reused for another pending handoff fact"
            )

        try:
            self._connection.execute(
                """
                INSERT INTO pending_handoffs(
                    handoff_id, aggregate_type, aggregate_id, transition_type,
                    original_occurred_at_us, workflow_state,
                    disposition_reason, materialized_delivery_id,
                    expires_at_us, record_version, created_at_us, updated_at_us
                ) VALUES (?, ?, ?, ?, ?, 'WAITING_CORRELATION', NULL, NULL,
                          ?, 1, ?, ?)
                """,
                (
                    record.handoff_id,
                    record.aggregate_type,
                    record.aggregate_id,
                    record.transition_type,
                    record.original_occurred_at_us,
                    record.expires_at_us,
                    record.created_at_us,
                    record.updated_at_us,
                ),
            )
        except sqlite3.IntegrityError as error:
            raise PendingHandoffConflictError(
                "pending handoff identity conflicts with an existing durable record"
            ) from error

        persisted = self.get(record.handoff_id)
        if persisted is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("pending handoff disappeared during its transaction")
        return PendingHandoffEnsureResult(record=persisted, created=True)

    def mark_materialized(
        self,
        handoff_id: str,
        *,
        expected_record_version: int,
        delivery_id: str,
        updated_at_us: int,
    ) -> PendingHandoffRecord:
        """immutable outbox row와 연결한 marker를 MATERIALIZED로 만든다."""

        require_write_transaction(self._connection)
        if not delivery_id:
            raise ValueError("delivery_id must not be empty")
        record = self._require_waiting(
            handoff_id,
            expected_record_version=expected_record_version,
        )
        self._require_monotonic_update_time(record, updated_at_us)
        return self._update_waiting(
            record,
            changes={
                "workflow_state": PendingHandoffState.MATERIALIZED.value,
                "materialized_delivery_id": delivery_id,
                "disposition_reason": None,
                "updated_at_us": updated_at_us,
            },
        )

    def extend_expiry(
        self,
        handoff_id: str,
        *,
        expected_record_version: int,
        expires_at_us: int,
        updated_at_us: int,
    ) -> PendingHandoffRecord:
        """terminal 시각을 반영해 waiting retention을 단조 연장한다."""

        require_write_transaction(self._connection)
        record = self._require_waiting(
            handoff_id,
            expected_record_version=expected_record_version,
        )
        self._require_monotonic_update_time(record, updated_at_us)
        if expires_at_us < record.expires_at_us:
            raise ValueError("pending handoff expiry cannot move backward")
        if expires_at_us == record.expires_at_us:
            return record
        return self._update_waiting(
            record,
            changes={
                "expires_at_us": expires_at_us,
                "updated_at_us": updated_at_us,
            },
        )

    def mark_expired(
        self,
        handoff_id: str,
        *,
        expected_record_version: int,
        disposition_reason: str,
        updated_at_us: int,
    ) -> PendingHandoffRecord:
        """publication 불가 disposition을 기록하되 domain은 바꾸지 않는다."""

        require_write_transaction(self._connection)
        if not disposition_reason:
            raise ValueError("disposition_reason must not be empty")
        record = self._require_waiting(
            handoff_id,
            expected_record_version=expected_record_version,
        )
        self._require_monotonic_update_time(record, updated_at_us)
        if updated_at_us < record.expires_at_us:
            raise ValueError("pending handoff cannot expire before expires_at_us")
        return self._update_waiting(
            record,
            changes={
                "workflow_state": PendingHandoffState.EXPIRED.value,
                "disposition_reason": disposition_reason,
                "materialized_delivery_id": None,
                "updated_at_us": updated_at_us,
            },
        )

    def mark_excluded(
        self,
        handoff_id: str,
        *,
        expected_record_version: int,
        disposition_reason: str,
        updated_at_us: int,
    ) -> PendingHandoffRecord:
        """확정된 publication 범위 밖 marker를 retention 전에 종결한다.

        ``mark_expired``는 상관관계를 끝내 확인하지 못한 marker의 retention
        만료만 처리한다. 이 메서드는 authoritative correlation을 얻은 뒤
        entryTime 같은 업무 경계로 publication 부적격이 확정된 경우에만
        사용한다. 두 경로 모두 같은 terminal state를 쓰되 disposition으로
        원인을 구분한다.
        """

        require_write_transaction(self._connection)
        if not disposition_reason:
            raise ValueError("disposition_reason must not be empty")
        record = self._require_waiting(
            handoff_id,
            expected_record_version=expected_record_version,
        )
        self._require_monotonic_update_time(record, updated_at_us)
        return self._update_waiting(
            record,
            changes={
                "workflow_state": PendingHandoffState.EXPIRED.value,
                "disposition_reason": disposition_reason,
                "materialized_delivery_id": None,
                "updated_at_us": updated_at_us,
            },
        )

    def _validate_new_waiting(self, record: PendingHandoffRecord) -> None:
        for name in (
            "handoff_id",
            "aggregate_type",
            "aggregate_id",
            "transition_type",
        ):
            if not getattr(record, name):
                raise ValueError(f"{name} must not be empty")
        if record.workflow_state is not PendingHandoffState.WAITING_CORRELATION:
            raise PendingHandoffStateError(
                "new pending handoff must be WAITING_CORRELATION"
            )
        _validate_pending_handoff_state(record)
        if record.record_version != 1:
            raise ValueError("new pending handoff record_version must be 1")
        if record.updated_at_us != record.created_at_us:
            raise ValueError(
                "new pending handoff updated_at_us must equal created_at_us"
            )
        if record.expires_at_us <= record.original_occurred_at_us:
            raise ValueError(
                "pending handoff expiry must be later than original occurredAt"
            )

    def _require_waiting(
        self,
        handoff_id: str,
        *,
        expected_record_version: int,
    ) -> PendingHandoffRecord:
        record = self.get(handoff_id)
        if record is None or record.record_version != expected_record_version:
            raise OptimisticConcurrencyError(
                f"pending handoff is missing or stale: {handoff_id}"
            )
        if record.workflow_state is not PendingHandoffState.WAITING_CORRELATION:
            raise PendingHandoffStateError(
                "pending handoff transition requires WAITING_CORRELATION, "
                f"got {record.workflow_state.value}"
            )
        return record

    @staticmethod
    def _require_monotonic_update_time(
        record: PendingHandoffRecord,
        updated_at_us: int,
    ) -> None:
        if updated_at_us < record.updated_at_us:
            raise ValueError("pending handoff updated_at_us cannot move backward")

    def _update_waiting(
        self,
        record: PendingHandoffRecord,
        *,
        changes: Mapping[str, Any],
    ) -> PendingHandoffRecord:
        optimistic_update(
            self._connection,
            table="pending_handoffs",
            key_column="handoff_id",
            key_value=record.handoff_id,
            expected_record_version=record.record_version,
            changes=changes,
        )
        updated = self.get(record.handoff_id)
        if updated is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("updated pending handoff disappeared")
        return updated


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

    def get_matched_by_physical_vehicle_id(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> EntryMatchAttempt | None:
        """PhysicalVehicle가 소비한 단일 입차 시도를 반환한다.

        ACTIVE PhysicalVehicle는 새 입차 시도에 재매칭되지 않는다.
        DB에 중복 이력이 있다면 임의로 하나를 고르지 않고 domain
        cardinality 훼손으로 보고한다.
        """

        rows = self._connection.execute(
            """
            SELECT * FROM entry_match_attempts
            WHERE match_state = 'MATCHED'
              AND physical_vehicle_id = ?
            ORDER BY match_terminated_at_us, entry_attempt_id
            """,
            (uuid_to_text(physical_vehicle_id),),
        ).fetchall()
        if len(rows) > 1:
            raise EntryMatchAttemptConflictError(
                "PhysicalVehicle is matched to multiple entry attempts"
            )
        return _entry_match_attempt_from_row(rows[0]) if rows else None

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

    def get_exit_enabled_by_physical_vehicle_id(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> ParkingSessionMirror | None:
        """PhysicalVehicle의 아직 사용 가능한 출차 correlation을 반환한다.

        행정적으로 CLOSED된 mirror도 실제 출차 전까지 correlation을 보존한다.
        이미 EXITED이거나 conflict 처리로 출차 correlation이 비활성화된 mirror는
        새 SessionExit의 대상이 아니므로 반환하지 않는다.
        """

        row = self._connection.execute(
            """
            SELECT * FROM parking_session_mirrors
            WHERE physical_vehicle_id = ?
              AND exit_correlation_enabled = 1
              AND physical_presence_state <> 'EXITED'
            """,
            (uuid_to_text(physical_vehicle_id),),
        ).fetchone()
        return _parking_session_mirror_from_row(row) if row is not None else None

    def list_inside(self) -> tuple[ParkingSessionMirror, ...]:
        """재시작 시 observation을 끊어야 하는 현장 재석 mirror를 반환한다."""

        rows = self._connection.execute(
            """
            SELECT * FROM parking_session_mirrors
            WHERE physical_presence_state = 'INSIDE'
            ORDER BY created_at_us, session_id
            """
        ).fetchall()
        return tuple(_parking_session_mirror_from_row(row) for row in rows)

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

    def get_active_by_physical_vehicle_id(
        self,
        physical_vehicle_id: PhysicalVehicleId,
    ) -> ContextBinding | None:
        """PhysicalVehicle의 authoritative active binding을 반환한다."""

        row = self._connection.execute(
            """
            SELECT * FROM context_bindings
            WHERE physical_vehicle_id = ? AND domain_state = 'BOUND'
            """,
            (uuid_to_text(physical_vehicle_id),),
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
    """immutable publication과 명시적 delivery state machine을 저장한다.

    쓰기 API는 모두 외부 :class:`UnitOfWork`를 요구한다. HTTP I/O는
    transaction 밖에서 수행하고, claim·ACK·retry 결과만 각각 짧은
    transaction으로 반영한다.
    """

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

    def get_by_delivery_id(self, delivery_id: str) -> OutboxRecord | None:
        """delivery identity로 publication을 조회한다."""

        row = self._connection.execute(
            "SELECT * FROM outbox WHERE delivery_id = ?",
            (delivery_id,),
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

        receipt = self._connection.execute(
            """
            SELECT payload_hash
            FROM delivery_receipts
            WHERE aggregate_type = ? AND aggregate_id = ?
              AND destination = ? AND publication_revision = ?
            """,
            (
                aggregate_type,
                aggregate_id,
                destination,
                publication_revision,
            ),
        ).fetchone()
        if receipt is not None:
            if str(receipt["payload_hash"]) != payload_hash:
                raise OutboxConflictError(
                    "delivered publication identity was reused with a different payload"
                )
            raise OutboxAlreadyDeliveredError(
                "publication was already confirmed and retained as a delivery receipt"
            )

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

    def recover_in_flight(
        self,
        *,
        now_us: int | None = None,
        reason: str = "PROCESS_RESTARTED",
    ) -> int:
        """restart 전 ``IN_FLIGHT``를 즉시 retry 가능한 상태로 돌린다."""

        require_write_transaction(self._connection)
        if not reason:
            raise ValueError("recovery reason must not be empty")
        recovered_at = now_us if now_us is not None else _utc_now_microseconds()
        cursor = self._connection.execute(
            """
            UPDATE outbox
            SET delivery_state = 'RETRY_WAIT',
                next_attempt_at_us = ?,
                last_error = ?,
                updated_at_us = ?,
                record_version = record_version + 1
            WHERE delivery_state = 'IN_FLIGHT'
            """,
            (recovered_at, reason, recovered_at),
        )
        return cursor.rowcount

    def claim_next(
        self,
        *,
        destination: str,
        now_us: int | None = None,
    ) -> OutboxRecord | None:
        """due publication 하나를 aggregate revision 순서로 claim한다.

        revision 2 이상은 직전 revision의 delivered row 또는 receipt가
        있어야 한다. 더 낮은 미확인 revision이 하나라도 있으면
        뒤 publication을 건너뛰지 않는다.
        """

        require_write_transaction(self._connection)
        if not destination:
            raise ValueError("destination must not be empty")
        claimed_at = now_us if now_us is not None else _utc_now_microseconds()
        row = self._connection.execute(
            """
            SELECT candidate.*
            FROM outbox AS candidate
            WHERE candidate.destination = ?
              AND (
                    candidate.delivery_state = 'PENDING'
                    OR (
                        candidate.delivery_state = 'RETRY_WAIT'
                        AND candidate.next_attempt_at_us IS NOT NULL
                        AND candidate.next_attempt_at_us <= ?
                    )
              )
              AND (
                    candidate.publication_revision = 1
                    OR EXISTS (
                        SELECT 1
                        FROM outbox AS predecessor
                        WHERE predecessor.aggregate_type = candidate.aggregate_type
                          AND predecessor.aggregate_id = candidate.aggregate_id
                          AND predecessor.destination = candidate.destination
                          AND predecessor.publication_revision =
                              candidate.publication_revision - 1
                          AND predecessor.delivery_state = 'DELIVERED'
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM delivery_receipts AS receipt
                        WHERE receipt.aggregate_type = candidate.aggregate_type
                          AND receipt.aggregate_id = candidate.aggregate_id
                          AND receipt.destination = candidate.destination
                          AND receipt.publication_revision =
                              candidate.publication_revision - 1
                    )
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM outbox AS blocker
                    WHERE blocker.aggregate_type = candidate.aggregate_type
                      AND blocker.aggregate_id = candidate.aggregate_id
                      AND blocker.destination = candidate.destination
                      AND blocker.publication_revision <
                          candidate.publication_revision
                      AND blocker.delivery_state <> 'DELIVERED'
              )
            ORDER BY
                COALESCE(candidate.next_attempt_at_us, candidate.created_at_us),
                candidate.created_at_us,
                candidate.delivery_id
            LIMIT 1
            """,
            (destination, claimed_at),
        ).fetchone()
        if row is None:
            return None

        record = _outbox_from_row(row)
        cursor = self._connection.execute(
            """
            UPDATE outbox
            SET delivery_state = 'IN_FLIGHT',
                attempt_count = attempt_count + 1,
                next_attempt_at_us = NULL,
                updated_at_us = ?,
                record_version = record_version + 1
            WHERE delivery_id = ?
              AND record_version = ?
              AND delivery_state IN ('PENDING', 'RETRY_WAIT')
            """,
            (claimed_at, record.delivery_id, record.record_version),
        )
        if cursor.rowcount != 1:  # pragma: no cover - BEGIN IMMEDIATE serializes writers.
            raise OptimisticConcurrencyError(
                f"outbox claim lost a concurrent update: {record.delivery_id}"
            )
        claimed = self.get_by_delivery_id(record.delivery_id)
        if claimed is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("claimed outbox record disappeared")
        return claimed

    def schedule_retry(
        self,
        delivery_id: str,
        *,
        expected_record_version: int,
        next_attempt_at_us: int,
        error: str,
        updated_at_us: int | None = None,
    ) -> OutboxRecord:
        """retryable 실패를 ``IN_FLIGHT → RETRY_WAIT``로 기록한다."""

        if not error:
            raise ValueError("retry error must not be empty")
        updated_at = (
            updated_at_us if updated_at_us is not None else _utc_now_microseconds()
        )
        if next_attempt_at_us < updated_at:
            raise ValueError("next_attempt_at_us must not be earlier than updated_at_us")
        return self._transition(
            delivery_id,
            expected_record_version=expected_record_version,
            expected_state=DeliveryState.IN_FLIGHT,
            changes={
                "delivery_state": DeliveryState.RETRY_WAIT.value,
                "next_attempt_at_us": next_attempt_at_us,
                "last_error": error,
                "updated_at_us": updated_at,
            },
        )

    def mark_delivered(
        self,
        delivery_id: str,
        *,
        expected_record_version: int,
        application_status: PublicationApplicationStatus | str,
        confirmed_payload_hash: str,
        confirmed_at_us: int,
        receipt_expires_at_us: int,
        backend_correlation_payload: bytes | bytearray | memoryview | None = None,
    ) -> OutboxRecord:
        """Backend application confirmation과 receipt를 원자적으로 남긴다.

        이 local repository는 저장된 payload hash만 대조한다. Backend
        confirmation의 aggregate identity·publication revision이 request와 같은지
        검증하는 것은 후속 wire adapter 계약의 책임이다.

        내부 savepoint는 호출자가 예외를 밖의 ``UnitOfWork`` 안에서
        처리해도 DELIVERED update만 부분 commit되는 것을 막는다.
        """

        require_write_transaction(self._connection)
        try:
            status = PublicationApplicationStatus(application_status)
        except ValueError as error:
            raise ValueError(
                "only APPLIED or ALREADY_APPLIED can mark an outbox row delivered"
            ) from error
        if receipt_expires_at_us <= confirmed_at_us:
            raise ValueError("receipt expiry must be later than confirmation")

        record = self._require_transition_source(
            delivery_id,
            expected_record_version=expected_record_version,
            expected_state=DeliveryState.IN_FLIGHT,
        )
        if confirmed_payload_hash != record.payload_hash:
            raise OutboxConflictError(
                "Backend confirmation payload hash differs from the immutable publication"
            )
        correlation = (
            _payload_bytes(backend_correlation_payload)
            if backend_correlation_payload is not None
            else None
        )

        savepoint = "outbox_mark_delivered"
        self._connection.execute(f"SAVEPOINT {savepoint}")
        try:
            delivered = self._transition_existing(
                record,
                changes={
                    "delivery_state": DeliveryState.DELIVERED.value,
                    "next_attempt_at_us": None,
                    "last_error": None,
                    "confirmed_at_us": confirmed_at_us,
                    "updated_at_us": confirmed_at_us,
                },
            )
            try:
                self._connection.execute(
                    """
                    INSERT INTO delivery_receipts(
                        delivery_id, aggregate_type, aggregate_id, destination,
                        publication_revision, payload_hash, application_status,
                        backend_correlation_payload, confirmed_at_us, expires_at_us
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.delivery_id,
                        record.aggregate_type,
                        record.aggregate_id,
                        record.destination,
                        record.publication_revision,
                        record.payload_hash,
                        status.value,
                        correlation,
                        confirmed_at_us,
                        receipt_expires_at_us,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise OutboxConflictError(
                    "delivery confirmation conflicts with an existing receipt"
                ) from error
            self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
        except BaseException:
            self._connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            self._connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise
        return delivered

    def mark_failed_terminal(
        self,
        delivery_id: str,
        *,
        expected_record_version: int,
        error: str,
        updated_at_us: int | None = None,
    ) -> OutboxRecord:
        """non-retryable 실패를 격리하고 뒤 revision을 차단한다."""

        if not error:
            raise ValueError("terminal error must not be empty")
        updated_at = (
            updated_at_us if updated_at_us is not None else _utc_now_microseconds()
        )
        return self._transition(
            delivery_id,
            expected_record_version=expected_record_version,
            expected_state=DeliveryState.IN_FLIGHT,
            changes={
                "delivery_state": DeliveryState.FAILED_TERMINAL.value,
                "next_attempt_at_us": None,
                "last_error": error,
                "updated_at_us": updated_at,
            },
        )

    def retry_failed_terminal(
        self,
        delivery_id: str,
        *,
        expected_record_version: int,
        next_attempt_at_us: int,
        updated_at_us: int | None = None,
    ) -> OutboxRecord:
        """explicit intervention으로만 terminal publication을 retry한다."""

        updated_at = (
            updated_at_us if updated_at_us is not None else _utc_now_microseconds()
        )
        if next_attempt_at_us < updated_at:
            raise ValueError("next_attempt_at_us must not be earlier than updated_at_us")
        return self._transition(
            delivery_id,
            expected_record_version=expected_record_version,
            expected_state=DeliveryState.FAILED_TERMINAL,
            changes={
                "delivery_state": DeliveryState.RETRY_WAIT.value,
                "next_attempt_at_us": next_attempt_at_us,
                "updated_at_us": updated_at,
            },
        )

    def _transition(
        self,
        delivery_id: str,
        *,
        expected_record_version: int,
        expected_state: DeliveryState,
        changes: Mapping[str, Any],
    ) -> OutboxRecord:
        require_write_transaction(self._connection)
        record = self._require_transition_source(
            delivery_id,
            expected_record_version=expected_record_version,
            expected_state=expected_state,
        )
        return self._transition_existing(record, changes=changes)

    def _require_transition_source(
        self,
        delivery_id: str,
        *,
        expected_record_version: int,
        expected_state: DeliveryState,
    ) -> OutboxRecord:
        record = self.get_by_delivery_id(delivery_id)
        if record is None or record.record_version != expected_record_version:
            raise OptimisticConcurrencyError(
                f"outbox record is missing or stale: {delivery_id}"
            )
        if record.delivery_state is not expected_state:
            raise OutboxStateError(
                f"outbox transition requires {expected_state.value}, "
                f"got {record.delivery_state.value}"
            )
        return record

    def _transition_existing(
        self,
        record: OutboxRecord,
        *,
        changes: Mapping[str, Any],
    ) -> OutboxRecord:
        optimistic_update(
            self._connection,
            table="outbox",
            key_column="delivery_id",
            key_value=record.delivery_id,
            expected_record_version=record.record_version,
            changes=changes,
        )
        updated = self.get_by_delivery_id(record.delivery_id)
        if updated is None:  # pragma: no cover - protects a broken SQLite connection.
            raise RuntimeError("updated outbox record disappeared")
        return updated


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
    next_record_version: int | None = None,
    changes: Mapping[str, Any],
) -> int:
    """field 변경과 ``record_version`` 전진을 원자적으로 수행한다.

    기본은 한 단계 증가한다. frame별 in-memory version을 여러 개 묶어
    checkpoint하는 aggregate는 더 큰 ``next_record_version``을 전달할 수 있다.
    어느 경우에도 ``WHERE record_version = expected`` CAS는 유지한다.

    새 version을 반환한다. 누락 record와 stale version은 어느 쪽도 안전하게
    덮어쓸 수 없으므로 같은 오류로 처리한다.
    """

    require_write_transaction(connection)
    if expected_record_version < 1:
        raise ValueError("expected_record_version must be positive")
    resolved_next_version = (
        expected_record_version + 1
        if next_record_version is None
        else next_record_version
    )
    if resolved_next_version <= expected_record_version:
        raise ValueError(
            "next_record_version must be greater than expected_record_version"
        )
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
    values.append(resolved_next_version)
    values.extend((key_value, expected_record_version))
    cursor = connection.execute(
        f"""
        UPDATE {table_sql}
        SET {assignments}, record_version = ?
        WHERE {key_sql} = ? AND record_version = ?
        """,
        values,
    )
    if cursor.rowcount != 1:
        raise OptimisticConcurrencyError(
            f"{table}.{key_column}={key_value!r} is missing or has a newer version"
        )
    return resolved_next_version

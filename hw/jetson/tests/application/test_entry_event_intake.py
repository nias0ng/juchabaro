"""RPi EntryDecision의 durable EntryMatchAttempt 접수 계약."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.application.entry_event_intake import EntryEventIntake
from src.communication.models import (
    EntryAccessDecision,
    EntryDecisionInput,
    EntrySessionContextInput,
)
from src.domain.models import ObservationState
from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchState,
    PhysicalPresenceState,
    SessionAdministrativeState,
)
from src.storage.database import open_database
from src.storage.repositories import (
    AcceptedInputConflictError,
    AcceptedInputRepository,
    EntryMatchAttemptConflictError,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorConflictError,
    ParkingSessionMirrorRepository,
)
from src.tracking.models import ParkingSessionId, VehicleId


NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
ENTRY_ATTEMPT_ID = UUID("11111111-1111-4111-8111-111111111111")
DECISION_REVISION = 1


def _intake() -> EntryEventIntake:
    entry_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="camera-1:v1",
        entry_exit_role=EntryExitRole.ENTRY,
    )
    return EntryEventIntake(
        EntryMatchCoordinator(zones=ZoneRegistry([entry_zone])),
        match_window_seconds=10,
    )


def _session_context() -> EntrySessionContextInput:
    return EntrySessionContextInput(
        session_id=55,
        vehicle_id=10,
        is_disabled_vehicle=False,
        is_electric=True,
    )


def _entry_decision(**overrides: object) -> EntryDecisionInput:
    fields: dict[str, object] = {
        "entry_attempt_id": ENTRY_ATTEMPT_ID,
        "decision_revision": DECISION_REVISION,
        "entry_time": NOW,
        "access_decision": EntryAccessDecision.ALLOW,
        "session_context": _session_context(),
    }
    fields.update(overrides)
    return EntryDecisionInput(**fields)  # type: ignore[arg-type]


def test_allow_is_stored_with_wire_revision_in_one_uow(
    tmp_path: Path,
    caplog,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    intake = _intake()
    try:
        with caplog.at_level(
            logging.INFO,
            logger="src.application.entry_event_intake",
        ):
            acceptance = intake.receive(
                _entry_decision(),
                idempotency_key="rpi-request-1",
                connection=connection,
            )

        assert "입차 결정을 접수했습니다." in caplog.text
        assert f"entryAttemptId={ENTRY_ATTEMPT_ID}" in caplog.text
        assert "decisionState=ALLOW" in caplog.text
        assert "revision=1" in caplog.text
        assert "created=True" in caplog.text
        assert "rpi-request-1" not in caplog.text

        assert acceptance.created is True
        assert acceptance.entry_attempt_id == EntryAttemptId(ENTRY_ATTEMPT_ID)
        assert acceptance.decision_revision == DECISION_REVISION
        assert acceptance.accepted_at.tzinfo is not None
        assert acceptance.match_deadline_at == NOW + timedelta(seconds=10)

        attempt = EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(ENTRY_ATTEMPT_ID)
        )
        assert attempt is not None
        assert attempt.match_state is EntryMatchState.PENDING
        assert attempt.decision_state is EntryDecisionState.ALLOW
        assert attempt.decision_revision == DECISION_REVISION
        assert attempt.match_deadline_at == NOW + timedelta(seconds=10)
        assert attempt.authoritative_session_id == ParkingSessionId(55)
        assert attempt.authoritative_context is not None
        assert attempt.authoritative_context.vehicle_id == VehicleId(10)

        mirror = ParkingSessionMirrorRepository(connection).get(ParkingSessionId(55))
        assert mirror is not None
        assert mirror.entry_attempt_id == EntryAttemptId(ENTRY_ATTEMPT_ID)
        assert mirror.context_revision == DECISION_REVISION
        assert mirror.administrative_state is SessionAdministrativeState.ACTIVE
        assert mirror.physical_presence_state is PhysicalPresenceState.UNCONFIRMED
        assert mirror.physical_vehicle_id is None
        assert mirror.physical_observation.state is ObservationState.UNKNOWN
        assert mirror.last_context == attempt.authoritative_context
        assert not hasattr(intake, "_connection")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("wire_decision", "domain_decision"),
    [
        (EntryAccessDecision.DENY, EntryDecisionState.DENY),
        (EntryAccessDecision.REVIEW, EntryDecisionState.REVIEW_PENDING),
    ],
)
def test_non_allow_decisions_are_stored_without_authoritative_context(
    tmp_path: Path,
    wire_decision: EntryAccessDecision,
    domain_decision: EntryDecisionState,
) -> None:
    connection = open_database(tmp_path / f"{wire_decision.value.lower()}.db")
    try:
        acceptance = _intake().receive(
            _entry_decision(
                access_decision=wire_decision,
                session_context=None,
            ),
            idempotency_key=f"request-{wire_decision.value.lower()}",
            connection=connection,
        )

        assert acceptance.created is True
        attempt = EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(ENTRY_ATTEMPT_ID)
        )
        assert attempt is not None
        assert attempt.decision_state is domain_decision
        assert attempt.authoritative_session_id is None
        assert attempt.authoritative_context is None
        assert connection.execute(
            "SELECT COUNT(*) FROM parking_session_mirrors"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_domain_identity_and_transport_key_are_both_immutable_on_retry(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    intake = _intake()
    original = _entry_decision()
    try:
        first = intake.receive(
            original,
            idempotency_key="same-key",
            connection=connection,
        )
        same_key_retry = intake.receive(
            original,
            idempotency_key="same-key",
            connection=connection,
        )
        assert first.created is True
        assert same_key_retry.created is False
        assert same_key_retry.accepted_at == first.accepted_at

        with pytest.raises(AcceptedInputConflictError):
            intake.receive(
                original,
                idempotency_key="different-transport-key",
                connection=connection,
            )

        with pytest.raises(AcceptedInputConflictError):
            intake.receive(
                replace(original, entry_time=NOW + timedelta(seconds=1)),
                idempotency_key="same-key",
                connection=connection,
            )

        assert connection.execute(
            "SELECT COUNT(*) FROM accepted_inputs"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM entry_match_attempts"
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM parking_session_mirrors"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_receipt_uses_new_entry_decision_payload(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        _intake().receive(
            _entry_decision(),
            idempotency_key="rpi-request-1",
            connection=connection,
        )

        receipt = AcceptedInputRepository(connection).get(
            "EntryDecision",
            str(ENTRY_ATTEMPT_ID),
            DECISION_REVISION,
        )
        assert receipt is not None
        assert b'"entryAttemptId"' in receipt.request_payload
        assert b'"decisionRevision":1' in receipt.request_payload
        assert b'"sessionContext"' in receipt.request_payload
        assert b'"trackingId"' not in receipt.request_payload
        assert b'"duplicateRequest"' not in receipt.request_payload
        assert b'"recognizedPlateNumber"' not in receipt.request_payload
    finally:
        connection.close()


def test_receipt_rolls_back_when_attempt_insert_conflicts(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    intake = _intake()
    try:
        intake.receive(
            _entry_decision(),
            idempotency_key="first-key",
            connection=connection,
        )
        connection.execute("DELETE FROM accepted_inputs")

        with pytest.raises(EntryMatchAttemptConflictError):
            intake.receive(
                _entry_decision(),
                idempotency_key="second-key",
                connection=connection,
            )

        assert AcceptedInputRepository(connection).get(
            "EntryDecision",
            str(ENTRY_ATTEMPT_ID),
            DECISION_REVISION,
        ) is None
    finally:
        connection.close()


def test_receipt_and_attempt_roll_back_when_initial_mirror_insert_conflicts(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    connection.execute(
        """
        CREATE TRIGGER reject_initial_session_mirror
        BEFORE INSERT ON parking_session_mirrors
        BEGIN
            SELECT RAISE(ABORT, 'test mirror rejection');
        END
        """
    )
    try:
        with pytest.raises(ParkingSessionMirrorConflictError):
            _intake().receive(
                _entry_decision(),
                idempotency_key="mirror-conflict",
                connection=connection,
            )

        assert AcceptedInputRepository(connection).get(
            "EntryDecision",
            str(ENTRY_ATTEMPT_ID),
            DECISION_REVISION,
        ) is None
        assert EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(ENTRY_ATTEMPT_ID)
        ) is None
        assert connection.execute(
            "SELECT COUNT(*) FROM parking_session_mirrors"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_empty_idempotency_key_fails_before_any_write(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with pytest.raises(ValueError):
            _intake().receive(
                _entry_decision(),
                idempotency_key="   ",
                connection=connection,
            )

        assert connection.execute(
            "SELECT COUNT(*) FROM accepted_inputs"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM entry_match_attempts"
        ).fetchone()[0] == 0
    finally:
        connection.close()

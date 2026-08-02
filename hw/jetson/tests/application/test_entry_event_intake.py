"""Legacy EntryContext의 durable EntryMatchAttempt 접수 계약."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.application.entry_event_intake import EntryEventIntake
from src.communication.models import EntryContext
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
TRACKING_ID = "11111111-1111-4111-8111-111111111111"


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


def _entry_context(**overrides: object) -> EntryContext:
    fields: dict[str, object] = {
        "tracking_id": TRACKING_ID,
        "recognized_plate_number": "12가3456",
        "entry_time": NOW,
        "access_decision": "ALLOW",
        "registered": True,
        "vehicle_id": 10,
        "is_disabled_vehicle": False,
        "is_electric": True,
        "vehicle_status": "ACTIVE",
        "session_id": 55,
        "duplicate_request": False,
    }
    fields.update(overrides)
    return EntryContext(**fields)  # type: ignore[arg-type]


def test_allow_is_stored_as_legacy_revision_zero_in_one_uow(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    intake = _intake()
    try:
        accepted = intake.receive(
            _entry_context(),
            idempotency_key="rpi-request-1",
            connection=connection,
        )

        assert accepted is True
        attempt = EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(UUID(TRACKING_ID))
        )
        assert attempt is not None
        assert attempt.match_state is EntryMatchState.PENDING
        assert attempt.decision_state is EntryDecisionState.ALLOW
        assert attempt.decision_revision == 0
        assert attempt.match_deadline_at == NOW + timedelta(seconds=10)
        assert attempt.authoritative_session_id == ParkingSessionId(55)
        assert attempt.authoritative_context is not None
        assert attempt.authoritative_context.vehicle_id == VehicleId(10)
        mirror = ParkingSessionMirrorRepository(connection).get(ParkingSessionId(55))
        assert mirror is not None
        assert mirror.entry_attempt_id == EntryAttemptId(UUID(TRACKING_ID))
        assert mirror.administrative_state is SessionAdministrativeState.ACTIVE
        assert mirror.physical_presence_state is PhysicalPresenceState.UNCONFIRMED
        assert mirror.physical_vehicle_id is None
        assert mirror.physical_observation.state is ObservationState.UNKNOWN
        assert mirror.last_context == attempt.authoritative_context
        assert (
            connection.execute("SELECT COUNT(*) FROM accepted_inputs").fetchone()[0]
            == 1
        )
        assert not hasattr(intake, "_connection")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("wire_decision", "domain_decision"),
    [
        ("DENY", EntryDecisionState.DENY),
        ("REVIEW", EntryDecisionState.REVIEW_PENDING),
    ],
)
def test_non_allow_decisions_are_mapped_without_authoritative_context(
    tmp_path: Path,
    wire_decision: str,
    domain_decision: EntryDecisionState,
) -> None:
    connection = open_database(tmp_path / f"{wire_decision.lower()}.db")
    try:
        assert _intake().receive(
            _entry_context(
                access_decision=wire_decision,
                registered=False,
                vehicle_id=None,
                is_disabled_vehicle=None,
                is_electric=None,
                vehicle_status=None,
                session_id=None,
            ),
            idempotency_key=f"request-{wire_decision.lower()}",
            connection=connection,
        )

        attempt = EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(UUID(TRACKING_ID))
        )
        assert attempt is not None
        assert attempt.decision_state is domain_decision
        assert attempt.authoritative_session_id is None
        assert attempt.authoritative_context is None
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM parking_session_mirrors"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_domain_identity_controls_retry_independently_of_transport_key(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    intake = _intake()
    original = _entry_context()
    try:
        assert intake.receive(
            original, idempotency_key="same-key", connection=connection
        ) is True
        assert intake.receive(
            original, idempotency_key="same-key", connection=connection
        ) is False
        assert intake.receive(
            original,
            idempotency_key="different-transport-key",
            connection=connection,
        ) is False

        with pytest.raises(AcceptedInputConflictError):
            intake.receive(
                _entry_context(recognized_plate_number="99나9999"),
                idempotency_key="same-key",
                connection=connection,
            )

        assert (
            connection.execute("SELECT COUNT(*) FROM accepted_inputs").fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM entry_match_attempts"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM parking_session_mirrors"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_receipt_rolls_back_when_attempt_insert_conflicts(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "jetson.db")
    intake = _intake()
    try:
        assert intake.receive(
            _entry_context(), idempotency_key="first-key", connection=connection
        )
        # attempt만 이미 있고 receipt가 없는 부분 실패 상황을
        # 만들어, 새 receipt가 attempt conflict와 함께 rollback되는지 본다.
        connection.execute("DELETE FROM accepted_inputs")

        with pytest.raises(EntryMatchAttemptConflictError):
            intake.receive(
                _entry_context(), idempotency_key="second-key", connection=connection
            )

        assert (
            AcceptedInputRepository(connection).get("EntryDecision", TRACKING_ID, 0)
            is None
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM accepted_inputs").fetchone()[0]
            == 0
        )
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
                _entry_context(),
                idempotency_key="mirror-conflict",
                connection=connection,
            )

        assert (
            AcceptedInputRepository(connection).get(
                "EntryDecision", TRACKING_ID, 0
            )
            is None
        )
        assert (
            EntryMatchAttemptRepository(connection).get(
                EntryAttemptId(UUID(TRACKING_ID))
            )
            is None
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM parking_session_mirrors"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    "entry_context",
    [
        _entry_context(tracking_id="not-a-uuid"),
        _entry_context(access_decision="REVIEW_ALLOW"),
        _entry_context(session_id=None),
    ],
)
def test_invalid_legacy_values_fail_before_any_write(
    tmp_path: Path,
    entry_context: EntryContext,
) -> None:
    connection = open_database(tmp_path / "jetson.db")
    try:
        with pytest.raises(ValueError):
            _intake().receive(
                entry_context,
                idempotency_key="invalid-key",
                connection=connection,
            )

        assert (
            connection.execute("SELECT COUNT(*) FROM accepted_inputs").fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM entry_match_attempts"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM parking_session_mirrors"
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()

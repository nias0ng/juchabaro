"""Backend intake의 post-commit ToF 문맥 변경 신호 계약 테스트."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import sqlite3
from uuid import UUID

import pytest

import src.application.entry_review_resolution_intake as entry_review_module
import src.application.session_context_update_intake as session_update_module
from src.application.entry_event_intake import EntryEventIntake
from src.application.entry_review_resolution_intake import (
    EntryReviewResolutionIntake,
)
from src.application.session_context_update_intake import (
    SessionContextUpdateConflictError,
    SessionContextUpdateIntake,
)
from src.communication.models import (
    EntryAccessDecision,
    EntryDecisionInput,
    EntryReviewResolution,
    EntryReviewResolutionInput,
    EntrySessionContextInput,
    InboundApplicationResult,
    SessionContextUpdateContextInput,
    SessionContextUpdateInput,
)
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.session.context_binding_coordinator import (
    ContextBindingCoordinator,
)
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.session.models import (
    ContextBinding,
    ContextBindingId,
    ContextBindingState,
    EntryAttemptId,
    EntryDecisionState,
    EntryMatchState,
    ParkingSessionMirror,
    PhysicalPresenceState,
    SessionAdministrativeState,
)
from src.storage.database import connect_database, open_database
from src.storage.repositories import (
    ContextBindingRepository,
    EntryMatchAttemptRepository,
    ParkingSessionMirrorRepository,
    PhysicalVehicleRepository,
)
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    ParkingSessionId,
    PhysicalVehicle,
    PhysicalVehicleId,
    PhysicalVehicleState,
)


NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
ENTRY_ATTEMPT_ID = UUID(
    "11111111-1111-4111-8111-111111111111"
)
SESSION_ID = 55
PHYSICAL_VEHICLE_ID = PhysicalVehicleId(
    UUID("22222222-2222-4222-8222-222222222222")
)
CONTEXT_BINDING_ID = ContextBindingId(
    UUID("33333333-3333-4333-8333-333333333333")
)


class _Signal:
    def __init__(
        self,
        *,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[
            tuple[tuple[object, ...], dict[str, object]]
        ] = []
        self.error = error

    def __call__(
        self,
        *args: object,
        **kwargs: object,
    ) -> None:
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error


class _FailingCommitUnitOfWork(UnitOfWork):
    def commit(self) -> None:
        try:
            if self.connection.in_transaction:
                self.connection.rollback()
        finally:
            self._active = False
        raise RuntimeError("commit failed")


def _entry_match_coordinator() -> EntryMatchCoordinator:
    entry_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=(
            (0.4, 0.4),
            (0.5, 0.4),
            (0.5, 0.5),
            (0.4, 0.5),
        ),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="camera-1:v1",
        entry_exit_role=EntryExitRole.ENTRY,
    )
    return EntryMatchCoordinator(
        zones=ZoneRegistry([entry_zone])
    )


def _entry_session_context() -> EntrySessionContextInput:
    return EntrySessionContextInput(
        session_id=SESSION_ID,
        vehicle_id=10,
        is_disabled_vehicle=False,
        is_electric=True,
    )


def _seed_entry(
    connection: sqlite3.Connection,
    *,
    access_decision: EntryAccessDecision,
) -> None:
    context = (
        _entry_session_context()
        if access_decision is EntryAccessDecision.ALLOW
        else None
    )
    EntryEventIntake(
        _entry_match_coordinator(),
        match_window_seconds=10.0,
    ).receive(
        EntryDecisionInput(
            entry_attempt_id=ENTRY_ATTEMPT_ID,
            decision_revision=1,
            access_decision=access_decision,
            entry_time=NOW,
            session_context=context,
        ),
        idempotency_key=f"entry:{access_decision.value}:1",
        connection=connection,
    )


def _review_resolution(
    *,
    revision: int = 2,
    resolution: EntryReviewResolution = (
        EntryReviewResolution.REVIEW_DENY
    ),
) -> EntryReviewResolutionInput:
    context = (
        _entry_session_context()
        if resolution is EntryReviewResolution.REVIEW_ALLOW
        else None
    )
    return EntryReviewResolutionInput(
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        decision_revision=revision,
        resolution=resolution,
        resolved_at=NOW + timedelta(seconds=revision),
        session_context=context,
    )


def _session_update(
    *,
    revision: int = 2,
    administrative_state: str = "ACTIVE",
    is_disabled_vehicle: bool = True,
) -> SessionContextUpdateInput:
    return SessionContextUpdateInput(
        session_id=SESSION_ID,
        entry_attempt_id=ENTRY_ATTEMPT_ID,
        context_revision=revision,
        administrative_state=administrative_state,
        updated_at=NOW + timedelta(seconds=revision),
        session_context=SessionContextUpdateContextInput(
            vehicle_id=10,
            is_disabled_vehicle=is_disabled_vehicle,
            is_electric=True,
        ),
    )


def _seed_active_binding(
    connection: sqlite3.Connection,
) -> None:
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.ALLOW,
    )
    observed_at = NOW + timedelta(seconds=1)
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=observed_at,
    )

    attempt_repository = EntryMatchAttemptRepository(connection)
    mirror_repository = ParkingSessionMirrorRepository(connection)
    attempt = attempt_repository.get(
        EntryAttemptId(ENTRY_ATTEMPT_ID)
    )
    mirror = mirror_repository.get(ParkingSessionId(SESSION_ID))
    assert attempt is not None
    assert mirror is not None
    assert mirror.last_context is not None

    vehicle = PhysicalVehicle(
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        state=PhysicalVehicleState.ACTIVE,
        observation=observation,
        absence_trusted_seconds=0.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.0,
        record_version=1,
        created_at=observed_at,
        updated_at=observed_at,
    )
    matched_attempt = replace(
        attempt,
        match_state=EntryMatchState.MATCHED,
        matched_physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        match_terminated_at=observed_at,
        record_version=attempt.record_version + 1,
        updated_at=observed_at,
    )
    inside_mirror = replace(
        mirror,
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        physical_presence_state=PhysicalPresenceState.INSIDE,
        physical_observation=observation,
        record_version=mirror.record_version + 1,
        updated_at=observed_at,
    )
    binding = ContextBinding(
        context_binding_id=CONTEXT_BINDING_ID,
        entry_attempt_id=EntryAttemptId(ENTRY_ATTEMPT_ID),
        parking_session_id=ParkingSessionId(SESSION_ID),
        physical_vehicle_id=PHYSICAL_VEHICLE_ID,
        state=ContextBindingState.BOUND,
        context_revision=1,
        context=inside_mirror.last_context,
        record_version=1,
        bound_at=observed_at,
        updated_at=observed_at,
    )

    with UnitOfWork(connection):
        PhysicalVehicleRepository(connection).ensure(vehicle)
        attempt_repository.save(
            matched_attempt,
            expected_record_version=attempt.record_version,
        )
        mirror_repository.save(
            inside_mirror,
            expected_record_version=mirror.record_version,
        )
        ContextBindingRepository(connection).add(binding)


def test_entry_review_applied_signals_once_after_commit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "entry-review.db"
    connection = open_database(database_path)
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    callback_states: list[EntryDecisionState] = []

    def after_applied() -> None:
        assert connection.in_transaction is False
        reader = connect_database(database_path)
        try:
            attempt = EntryMatchAttemptRepository(reader).get(
                EntryAttemptId(ENTRY_ATTEMPT_ID)
            )
        finally:
            reader.close()

        assert attempt is not None
        callback_states.append(attempt.decision_state)

    try:
        acceptance = EntryReviewResolutionIntake(
            _entry_match_coordinator(),
            after_applied=after_applied,
        ).receive(
            _review_resolution(),
            idempotency_key="review:2",
            connection=connection,
        )
    finally:
        connection.close()

    assert acceptance.application_result is InboundApplicationResult.APPLIED
    assert callback_states == [EntryDecisionState.REVIEW_DENY]


def test_review_allow_callback_sees_committed_initial_mirror(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "review-allow.db"
    connection = open_database(database_path)
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    observed_mirrors: list[ParkingSessionMirror | None] = []

    def after_applied() -> None:
        assert connection.in_transaction is False
        reader = connect_database(database_path)
        try:
            observed_mirrors.append(
                ParkingSessionMirrorRepository(reader).get(
                    ParkingSessionId(SESSION_ID)
                )
            )
        finally:
            reader.close()

    try:
        acceptance = EntryReviewResolutionIntake(
            _entry_match_coordinator(),
            after_applied=after_applied,
        ).receive(
            _review_resolution(
                resolution=EntryReviewResolution.REVIEW_ALLOW,
            ),
            idempotency_key="review-allow:2",
            connection=connection,
        )
    finally:
        connection.close()

    assert acceptance.application_result is InboundApplicationResult.APPLIED
    assert len(observed_mirrors) == 1
    mirror = observed_mirrors[0]
    assert mirror is not None
    assert mirror.entry_attempt_id == EntryAttemptId(ENTRY_ATTEMPT_ID)
    assert mirror.context_revision == 2
    assert mirror.last_context is not None
    assert mirror.last_context.is_electric is True


def test_session_update_applied_signals_once_after_commit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "session-update.db"
    connection = open_database(database_path)
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.ALLOW,
    )
    observed_revisions: list[int] = []

    def after_applied() -> None:
        assert connection.in_transaction is False
        reader = connect_database(database_path)
        try:
            mirror = ParkingSessionMirrorRepository(reader).get(
                ParkingSessionId(SESSION_ID)
            )
        finally:
            reader.close()

        assert mirror is not None
        observed_revisions.append(mirror.context_revision)

    try:
        acceptance = SessionContextUpdateIntake(
            ContextBindingCoordinator(),
            after_applied=after_applied,
        ).receive(
            _session_update(),
            idempotency_key="session:2",
            connection=connection,
        )
    finally:
        connection.close()

    assert acceptance.application_result is InboundApplicationResult.APPLIED
    assert observed_revisions == [2]


def test_entry_retry_and_stale_do_not_signal_again(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "entry-results.db")
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    signal = _Signal()
    intake = EntryReviewResolutionIntake(
        _entry_match_coordinator(),
        after_applied=signal,
    )
    latest = _review_resolution(revision=3)
    stale = _review_resolution(revision=2)

    try:
        applied = intake.receive(
            latest,
            idempotency_key="review:3",
            connection=connection,
        )
        retry = intake.receive(
            latest,
            idempotency_key="review:3",
            connection=connection,
        )
        stale_result = intake.receive(
            stale,
            idempotency_key="review:2",
            connection=connection,
        )
    finally:
        connection.close()

    assert applied.application_result is InboundApplicationResult.APPLIED
    assert (
        retry.application_result
        is InboundApplicationResult.ALREADY_APPLIED
    )
    assert stale_result.application_result is InboundApplicationResult.STALE
    assert signal.calls == [((), {})]


def test_session_retry_and_stale_do_not_signal_again(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "session-results.db")
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.ALLOW,
    )
    signal = _Signal()
    intake = SessionContextUpdateIntake(
        ContextBindingCoordinator(),
        after_applied=signal,
    )
    latest = _session_update(revision=3)
    stale = _session_update(
        revision=2,
        is_disabled_vehicle=False,
    )

    try:
        applied = intake.receive(
            latest,
            idempotency_key="session:3",
            connection=connection,
        )
        retry = intake.receive(
            latest,
            idempotency_key="session:3",
            connection=connection,
        )
        stale_result = intake.receive(
            stale,
            idempotency_key="session:2",
            connection=connection,
        )
    finally:
        connection.close()

    assert applied.application_result is InboundApplicationResult.APPLIED
    assert (
        retry.application_result
        is InboundApplicationResult.ALREADY_APPLIED
    )
    assert stale_result.application_result is InboundApplicationResult.STALE
    assert signal.calls == [((), {})]


def test_validation_and_domain_conflict_do_not_signal(
    tmp_path: Path,
) -> None:
    review_connection = open_database(tmp_path / "validation.db")
    _seed_entry(
        review_connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    review_signal = _Signal()
    try:
        with pytest.raises(
            ValueError,
            match="idempotency_key must not be empty",
        ):
            EntryReviewResolutionIntake(
                _entry_match_coordinator(),
                after_applied=review_signal,
            ).receive(
                _review_resolution(),
                idempotency_key=" ",
                connection=review_connection,
            )
    finally:
        review_connection.close()

    session_connection = open_database(tmp_path / "conflict.db")
    _seed_entry(
        session_connection,
        access_decision=EntryAccessDecision.ALLOW,
    )
    session_signal = _Signal()
    try:
        with pytest.raises(SessionContextUpdateConflictError):
            SessionContextUpdateIntake(
                ContextBindingCoordinator(),
                after_applied=session_signal,
            ).receive(
                _session_update(
                    revision=1,
                    is_disabled_vehicle=True,
                ),
                idempotency_key="session-conflict:1",
                connection=session_connection,
            )
    finally:
        session_connection.close()

    assert review_signal.calls == []
    assert session_signal.calls == []


def test_repository_failure_does_not_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = open_database(tmp_path / "save-failure.db")
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    signal = _Signal()

    def fail_save(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError("save failed")

    monkeypatch.setattr(
        EntryMatchAttemptRepository,
        "save",
        fail_save,
    )

    try:
        with pytest.raises(RuntimeError, match="save failed"):
            EntryReviewResolutionIntake(
                _entry_match_coordinator(),
                after_applied=signal,
            ).receive(
                _review_resolution(),
                idempotency_key="review-save-failure:2",
                connection=connection,
            )
    finally:
        connection.close()

    assert signal.calls == []


def test_entry_commit_failure_does_not_signal_or_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = open_database(tmp_path / "entry-commit-failure.db")
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    signal = _Signal()
    monkeypatch.setattr(
        entry_review_module,
        "UnitOfWork",
        _FailingCommitUnitOfWork,
    )

    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            EntryReviewResolutionIntake(
                _entry_match_coordinator(),
                after_applied=signal,
            ).receive(
                _review_resolution(),
                idempotency_key="review-commit-failure:2",
                connection=connection,
            )

        attempt = EntryMatchAttemptRepository(connection).get(
            EntryAttemptId(ENTRY_ATTEMPT_ID)
        )
    finally:
        connection.close()

    assert signal.calls == []
    assert attempt is not None
    assert attempt.decision_revision == 1
    assert attempt.decision_state is EntryDecisionState.REVIEW_PENDING


def test_session_commit_failure_does_not_signal_or_persist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = open_database(tmp_path / "session-commit-failure.db")
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.ALLOW,
    )
    signal = _Signal()
    monkeypatch.setattr(
        session_update_module,
        "UnitOfWork",
        _FailingCommitUnitOfWork,
    )

    try:
        with pytest.raises(RuntimeError, match="commit failed"):
            SessionContextUpdateIntake(
                ContextBindingCoordinator(),
                after_applied=signal,
            ).receive(
                _session_update(),
                idempotency_key="session-commit-failure:2",
                connection=connection,
            )

        mirror = ParkingSessionMirrorRepository(connection).get(
            ParkingSessionId(SESSION_ID)
        )
    finally:
        connection.close()

    assert signal.calls == []
    assert mirror is not None
    assert mirror.context_revision == 1
    assert (
        mirror.administrative_state
        is SessionAdministrativeState.ACTIVE
    )


def test_entry_callback_failure_preserves_acceptance_and_logs_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_path = tmp_path / "entry-callback-failure.db"
    connection = open_database(database_path)
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    signal = _Signal(error=RuntimeError("mailbox unavailable"))

    try:
        with caplog.at_level(
            logging.ERROR,
            logger=(
                "src.application.entry_review_resolution_intake"
            ),
        ):
            acceptance = EntryReviewResolutionIntake(
                _entry_match_coordinator(),
                after_applied=signal,
            ).receive(
                _review_resolution(),
                idempotency_key="review-callback-failure:2",
                connection=connection,
            )
    finally:
        connection.close()

    reader = connect_database(database_path)
    try:
        attempt = EntryMatchAttemptRepository(reader).get(
            EntryAttemptId(ENTRY_ATTEMPT_ID)
        )
    finally:
        reader.close()

    assert acceptance.application_result is InboundApplicationResult.APPLIED
    assert signal.calls == [((), {})]
    assert attempt is not None
    assert attempt.decision_state is EntryDecisionState.REVIEW_DENY
    assert "EntryReviewResolution" in caplog.text
    assert "stage=post_commit_reevaluation_signal" in caplog.text
    assert "applicationResult=APPLIED" in caplog.text
    assert f"entryAttemptId={ENTRY_ATTEMPT_ID}" in caplog.text
    assert "mailbox unavailable" in caplog.text


def test_session_callback_failure_preserves_acceptance_and_logs_context(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    database_path = tmp_path / "session-callback-failure.db"
    connection = open_database(database_path)
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.ALLOW,
    )
    signal = _Signal(error=RuntimeError("mailbox unavailable"))

    try:
        with caplog.at_level(
            logging.ERROR,
            logger=(
                "src.application.session_context_update_intake"
            ),
        ):
            acceptance = SessionContextUpdateIntake(
                ContextBindingCoordinator(),
                after_applied=signal,
            ).receive(
                _session_update(),
                idempotency_key="session-callback-failure:2",
                connection=connection,
            )
    finally:
        connection.close()

    reader = connect_database(database_path)
    try:
        mirror = ParkingSessionMirrorRepository(reader).get(
            ParkingSessionId(SESSION_ID)
        )
    finally:
        reader.close()

    assert acceptance.application_result is InboundApplicationResult.APPLIED
    assert signal.calls == [((), {})]
    assert mirror is not None
    assert mirror.context_revision == 2
    assert "SessionContextUpdate" in caplog.text
    assert "stage=post_commit_reevaluation_signal" in caplog.text
    assert "applicationResult=APPLIED" in caplog.text
    assert f"sessionId={SESSION_ID}" in caplog.text
    assert "mailbox unavailable" in caplog.text


def test_existing_constructors_without_callback_keep_working(
    tmp_path: Path,
) -> None:
    entry_connection = open_database(tmp_path / "legacy-entry.db")
    _seed_entry(
        entry_connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    try:
        entry_acceptance = EntryReviewResolutionIntake(
            _entry_match_coordinator()
        ).receive(
            _review_resolution(),
            idempotency_key="legacy-review:2",
            connection=entry_connection,
        )
    finally:
        entry_connection.close()

    session_connection = open_database(tmp_path / "legacy-session.db")
    _seed_entry(
        session_connection,
        access_decision=EntryAccessDecision.ALLOW,
    )
    try:
        session_acceptance = SessionContextUpdateIntake(
            ContextBindingCoordinator()
        ).receive(
            _session_update(),
            idempotency_key="legacy-session:2",
            connection=session_connection,
        )
    finally:
        session_connection.close()

    assert (
        entry_acceptance.application_result
        is InboundApplicationResult.APPLIED
    )
    assert (
        session_acceptance.application_result
        is InboundApplicationResult.APPLIED
    )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: EntryReviewResolutionIntake(
            _entry_match_coordinator(),
            after_applied=object(),
        ),
        lambda: SessionContextUpdateIntake(
            ContextBindingCoordinator(),
            after_applied=object(),
        ),
    ],
)
def test_non_callable_after_applied_is_rejected(
    factory: Callable[[], object],
) -> None:
    with pytest.raises(
        TypeError,
        match="after_applied must be callable or None",
    ):
        factory()


def test_review_without_session_context_still_signals_when_applied(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "review-deny.db")
    _seed_entry(
        connection,
        access_decision=EntryAccessDecision.REVIEW,
    )
    signal = _Signal()

    try:
        acceptance = EntryReviewResolutionIntake(
            _entry_match_coordinator(),
            after_applied=signal,
        ).receive(
            _review_resolution(
                resolution=EntryReviewResolution.REVIEW_DENY,
            ),
            idempotency_key="review-deny:2",
            connection=connection,
        )
    finally:
        connection.close()

    assert acceptance.application_result is InboundApplicationResult.APPLIED
    assert signal.calls == [((), {})]


def test_closed_session_callback_sees_committed_binding_end(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "closed-session.db"
    connection = open_database(database_path)
    _seed_active_binding(connection)
    callback_states: list[
        tuple[
            SessionAdministrativeState,
            ContextBindingState,
            str | None,
        ]
    ] = []

    def after_applied() -> None:
        assert connection.in_transaction is False
        reader = connect_database(database_path)
        try:
            mirror = ParkingSessionMirrorRepository(reader).get(
                ParkingSessionId(SESSION_ID)
            )
            binding = ContextBindingRepository(
                reader
            ).get_by_entry_attempt_id(
                EntryAttemptId(ENTRY_ATTEMPT_ID)
            )
        finally:
            reader.close()

        assert mirror is not None
        assert binding is not None
        callback_states.append(
            (
                mirror.administrative_state,
                binding.state,
                binding.termination_reason,
            )
        )

    try:
        acceptance = SessionContextUpdateIntake(
            ContextBindingCoordinator(),
            after_applied=after_applied,
        ).receive(
            _session_update(administrative_state="CLOSED"),
            idempotency_key="session-closed:2",
            connection=connection,
        )
    finally:
        connection.close()

    assert acceptance.application_result is InboundApplicationResult.APPLIED
    assert callback_states == [
        (
            SessionAdministrativeState.CLOSED,
            ContextBindingState.ENDED,
            "ADMIN_CLOSED",
        )
    ]

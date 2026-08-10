"""Pending handoff marker의 멱등 생성·CAS 전이·만료 조회 계약."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.storage import (
    OptimisticConcurrencyError,
    PendingHandoffConflictError,
    PendingHandoffRecord,
    PendingHandoffRepository,
    PendingHandoffState,
    PendingHandoffStateError,
    TransactionStateError,
    UnitOfWork,
    open_database,
)


def _waiting(
    handoff_id: str,
    *,
    aggregate_type: str = "ParkingEpisode",
    aggregate_id: str = "episode-1",
    transition_type: str = "PARKED",
    occurred_at_us: int = 100,
    expires_at_us: int = 1_000,
    created_at_us: int = 200,
) -> PendingHandoffRecord:
    return PendingHandoffRecord(
        handoff_id=handoff_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        transition_type=transition_type,
        original_occurred_at_us=occurred_at_us,
        workflow_state=PendingHandoffState.WAITING_CORRELATION,
        expires_at_us=expires_at_us,
        record_version=1,
        created_at_us=created_at_us,
        updated_at_us=created_at_us,
    )


def test_ensure_waiting_requires_uow_and_deduplicates_exact_fact(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "pending.db")
    repository = PendingHandoffRepository(connection)
    marker = _waiting("handoff-1")
    try:
        with pytest.raises(TransactionStateError):
            repository.ensure_waiting(marker)

        with UnitOfWork(connection):
            created = repository.ensure_waiting(marker)
        with UnitOfWork(connection):
            retry = repository.ensure_waiting(marker)

        assert created.created is True
        assert created.record == marker
        assert retry.created is False
        assert retry.record == marker
        assert repository.get(marker.handoff_id) == marker
        assert repository.get_by_identity(
            aggregate_type=marker.aggregate_type,
            aggregate_id=marker.aggregate_id,
            transition_type=marker.transition_type,
            original_occurred_at_us=marker.original_occurred_at_us,
        ) == marker

        with pytest.raises(PendingHandoffConflictError, match="another handoff_id"):
            with UnitOfWork(connection):
                repository.ensure_waiting(
                    replace(marker, handoff_id="handoff-for-same-fact")
                )
        with pytest.raises(PendingHandoffConflictError, match="another pending"):
            with UnitOfWork(connection):
                repository.ensure_waiting(
                    replace(marker, aggregate_id="episode-2")
                )
    finally:
        connection.close()


def test_ensure_waiting_rejects_non_initial_or_inconsistent_state(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "invalid-pending.db")
    repository = PendingHandoffRepository(connection)
    marker = _waiting("handoff-invalid")
    try:
        invalid_cases = (
            replace(
                marker,
                workflow_state=PendingHandoffState.MATERIALIZED,
                materialized_delivery_id="delivery-1",
            ),
            replace(marker, disposition_reason="UNBOUND_CONTEXT_EXPIRED"),
        )
        for invalid in invalid_cases:
            with pytest.raises(PendingHandoffStateError):
                with UnitOfWork(connection):
                    repository.ensure_waiting(invalid)

        with pytest.raises(ValueError, match="record_version"):
            with UnitOfWork(connection):
                repository.ensure_waiting(replace(marker, record_version=2))
        with pytest.raises(ValueError, match="later than original"):
            with UnitOfWork(connection):
                repository.ensure_waiting(replace(marker, expires_at_us=100))
    finally:
        connection.close()


def test_waiting_and_due_queries_are_deterministically_ordered(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "pending-order.db")
    repository = PendingHandoffRepository(connection)
    later_fact = _waiting(
        "handoff-later",
        occurred_at_us=300,
        expires_at_us=700,
        created_at_us=310,
    )
    earliest_fact = _waiting(
        "handoff-earliest",
        occurred_at_us=100,
        expires_at_us=900,
        created_at_us=110,
    )
    middle_fact = _waiting(
        "handoff-middle",
        aggregate_id="episode-2",
        transition_type="UNPARKED",
        occurred_at_us=200,
        expires_at_us=600,
        created_at_us=210,
    )
    try:
        with UnitOfWork(connection):
            repository.ensure_waiting(later_fact)
            repository.ensure_waiting(earliest_fact)
            repository.ensure_waiting(middle_fact)

        assert repository.list_waiting() == (
            earliest_fact,
            middle_fact,
            later_fact,
        )
        assert repository.list_waiting_for_aggregate(
            aggregate_type="ParkingEpisode",
            aggregate_id="episode-1",
        ) == (earliest_fact, later_fact)
        assert repository.list_due(now_us=750) == (
            middle_fact,
            later_fact,
        )
    finally:
        connection.close()


def test_materialization_is_cas_guarded_and_terminal_retry_does_not_reopen(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "materialized.db")
    repository = PendingHandoffRepository(connection)
    marker = _waiting("handoff-materialized")
    try:
        with UnitOfWork(connection):
            repository.ensure_waiting(marker)
        with pytest.raises(TransactionStateError):
            repository.mark_materialized(
                marker.handoff_id,
                expected_record_version=1,
                delivery_id="delivery-1",
                updated_at_us=300,
            )

        with UnitOfWork(connection):
            materialized = repository.mark_materialized(
                marker.handoff_id,
                expected_record_version=1,
                delivery_id="delivery-1",
                updated_at_us=300,
            )

        assert materialized.workflow_state is PendingHandoffState.MATERIALIZED
        assert materialized.materialized_delivery_id == "delivery-1"
        assert materialized.disposition_reason is None
        assert materialized.record_version == 2
        assert repository.list_waiting() == ()

        with pytest.raises(OptimisticConcurrencyError):
            with UnitOfWork(connection):
                repository.mark_materialized(
                    marker.handoff_id,
                    expected_record_version=1,
                    delivery_id="delivery-1",
                    updated_at_us=301,
                )
        with pytest.raises(PendingHandoffStateError, match="requires WAITING"):
            with UnitOfWork(connection):
                repository.mark_expired(
                    marker.handoff_id,
                    expected_record_version=2,
                    disposition_reason="UNBOUND_CONTEXT_EXPIRED",
                    updated_at_us=1_000,
                )

        with UnitOfWork(connection):
            retry = repository.ensure_waiting(marker)
        assert retry.created is False
        assert retry.record == materialized
    finally:
        connection.close()


def test_expiry_can_only_extend_and_expiration_is_cas_guarded(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "expired.db")
    repository = PendingHandoffRepository(connection)
    marker = _waiting("handoff-expired", expires_at_us=1_000)
    try:
        with UnitOfWork(connection):
            repository.ensure_waiting(marker)
            extended = repository.extend_expiry(
                marker.handoff_id,
                expected_record_version=1,
                expires_at_us=2_000,
                updated_at_us=300,
            )

        assert extended.expires_at_us == 2_000
        assert extended.record_version == 2

        with UnitOfWork(connection):
            unchanged = repository.extend_expiry(
                marker.handoff_id,
                expected_record_version=2,
                expires_at_us=2_000,
                updated_at_us=400,
            )
        assert unchanged == extended

        with pytest.raises(ValueError, match="cannot move backward"):
            with UnitOfWork(connection):
                repository.extend_expiry(
                    marker.handoff_id,
                    expected_record_version=2,
                    expires_at_us=1_999,
                    updated_at_us=400,
                )
        with pytest.raises(ValueError, match="before expires_at_us"):
            with UnitOfWork(connection):
                repository.mark_expired(
                    marker.handoff_id,
                    expected_record_version=2,
                    disposition_reason="UNBOUND_CONTEXT_EXPIRED",
                    updated_at_us=1_999,
                )

        with UnitOfWork(connection):
            expired = repository.mark_expired(
                marker.handoff_id,
                expected_record_version=2,
                disposition_reason="UNBOUND_CONTEXT_EXPIRED",
                updated_at_us=2_000,
            )

        assert expired.workflow_state is PendingHandoffState.EXPIRED
        assert expired.disposition_reason == "UNBOUND_CONTEXT_EXPIRED"
        assert expired.materialized_delivery_id is None
        assert expired.record_version == 3
        assert repository.list_due(now_us=3_000) == ()

        with pytest.raises(PendingHandoffStateError, match="requires WAITING"):
            with UnitOfWork(connection):
                repository.extend_expiry(
                    marker.handoff_id,
                    expected_record_version=3,
                    expires_at_us=3_000,
                    updated_at_us=3_000,
                )
    finally:
        connection.close()


def test_known_ineligible_marker_can_be_excluded_before_retention(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "excluded.db")
    repository = PendingHandoffRepository(connection)
    marker = _waiting("handoff-excluded", expires_at_us=10_000)
    try:
        with UnitOfWork(connection):
            repository.ensure_waiting(marker)
            excluded = repository.mark_excluded(
                marker.handoff_id,
                expected_record_version=1,
                disposition_reason="PRE_ENTRY_SCOPE_EXCLUDED",
                updated_at_us=300,
            )

        assert excluded.workflow_state is PendingHandoffState.EXPIRED
        assert excluded.disposition_reason == "PRE_ENTRY_SCOPE_EXCLUDED"
        assert excluded.materialized_delivery_id is None
        assert excluded.record_version == 2
        assert repository.list_waiting() == ()

        with pytest.raises(PendingHandoffStateError, match="requires WAITING"):
            with UnitOfWork(connection):
                repository.mark_excluded(
                    marker.handoff_id,
                    expected_record_version=2,
                    disposition_reason="PRE_ENTRY_SCOPE_EXCLUDED",
                    updated_at_us=301,
                )
    finally:
        connection.close()


def test_read_rejects_nullable_state_combination_not_covered_by_schema(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "corrupted-pending.db")
    repository = PendingHandoffRepository(connection)
    try:
        with UnitOfWork(connection):
            connection.execute(
                """
                INSERT INTO pending_handoffs(
                    handoff_id, aggregate_type, aggregate_id, transition_type,
                    original_occurred_at_us, workflow_state,
                    disposition_reason, materialized_delivery_id,
                    expires_at_us, record_version, created_at_us, updated_at_us
                ) VALUES (
                    'broken', 'Incident', 'incident-1', 'OPEN',
                    100, 'MATERIALIZED', NULL, NULL, 1000, 1, 200, 200
                )
                """
            )

        with pytest.raises(PendingHandoffStateError, match="requires only"):
            repository.get("broken")
    finally:
        connection.close()

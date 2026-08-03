"""카메라·저장소 없이 BlockingRelation 상태축만 검증한다."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.blocking_relation_tracker import (
    BLOCKING_RELATION_CLEAR_CONFIRMED,
    CANDIDATE_NOT_CONFIRMED,
    PHYSICAL_EXIT,
    InMemoryBlockingRelationTracker,
)
from src.parking.models import BlockingRelationState, PresenceSignal, ZoneId
from src.tracking.models import PhysicalVehicleId

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
SUBJECT = PhysicalVehicleId(UUID(int=1))
VICTIM = PhysicalVehicleId(UUID(int=2))
OTHER_SUBJECT = PhysicalVehicleId(UUID(int=3))
EGRESS_ZONE = ZoneId(21)
OTHER_EGRESS_ZONE = ZoneId(22)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def observed(seconds: float) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=at(seconds),
    )


def unknown(*, last_reliable: float | None = None) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.UNKNOWN,
        reason=ObservationReason.CAMERA_UNAVAILABLE,
        last_reliable_observed_at=(
            None if last_reliable is None else at(last_reliable)
        ),
    )


def degraded(*, last_reliable: float | None = None) -> ObservationStatus:
    return ObservationStatus(
        state=ObservationState.DEGRADED,
        reason=ObservationReason.PARTIAL_FRAME,
        last_reliable_observed_at=(
            None if last_reliable is None else at(last_reliable)
        ),
    )


def make_tracker(
    confirm: float = 3.0,
    clear: float = 3.0,
    max_gap: float = 10.0,
) -> InMemoryBlockingRelationTracker:
    return InMemoryBlockingRelationTracker(
        confirm_duration_seconds=confirm,
        clear_duration_seconds=clear,
        trusted_sample_max_gap_seconds=max_gap,
    )


def feed(
    tracker: InMemoryBlockingRelationTracker,
    signal: PresenceSignal,
    seconds: float,
    *,
    subject: PhysicalVehicleId = SUBJECT,
    victim: PhysicalVehicleId = VICTIM,
    egress_zone: ZoneId = EGRESS_ZONE,
    observation: ObservationStatus | None = None,
):
    if observation is None:
        observation = observed(seconds)
    return tracker.update(
        subject_physical_vehicle_id=subject,
        victim_physical_vehicle_id=victim,
        egress_zone_id=egress_zone,
        signal=signal,
        observation=observation,
        observed_at=at(seconds),
    )


def confirm(
    tracker: InMemoryBlockingRelationTracker,
    *,
    start: float = 0.0,
    confirmed: float = 3.0,
    subject: PhysicalVehicleId = SUBJECT,
    victim: PhysicalVehicleId = VICTIM,
    egress_zone: ZoneId = EGRESS_ZONE,
):
    feed(tracker, PresenceSignal.PRESENT, start, subject=subject, victim=victim, egress_zone=egress_zone)
    return feed(
        tracker, PresenceSignal.PRESENT, confirmed, subject=subject, victim=victim, egress_zone=egress_zone
    )


def test_absent_or_unknown_without_relation_returns_none() -> None:
    tracker = make_tracker()
    assert feed(tracker, PresenceSignal.ABSENT, 0) is None
    assert feed(tracker, PresenceSignal.UNKNOWN, 1, observation=unknown()) is None


def test_first_present_creates_complete_candidate_snapshot() -> None:
    relation = feed(make_tracker(), PresenceSignal.PRESENT, 0)

    assert relation.state is BlockingRelationState.CANDIDATE
    assert isinstance(relation.blocking_relation_id, UUID)
    assert relation.subject_physical_vehicle_id == SUBJECT
    assert relation.victim_physical_vehicle_id == VICTIM
    assert relation.egress_zone_id == EGRESS_ZONE
    assert relation.confirm_trusted_seconds == 0.0
    assert relation.clear_trusted_seconds == 0.0
    assert relation.confirm_duration_seconds == 3.0
    assert relation.clear_duration_seconds == 3.0
    assert relation.record_version == 1
    assert relation.created_at == relation.updated_at == T0
    assert relation.confirmed_at is None
    assert relation.terminated_at is None


def test_subject_equal_to_victim_is_rejected() -> None:
    tracker = make_tracker()
    with pytest.raises(ValueError, match="differ"):
        tracker.update(
            subject_physical_vehicle_id=SUBJECT,
            victim_physical_vehicle_id=SUBJECT,
            egress_zone_id=EGRESS_ZONE,
            signal=PresenceSignal.PRESENT,
            observation=observed(0),
            observed_at=at(0),
        )


def test_present_for_confirmation_duration_becomes_blocking() -> None:
    tracker = make_tracker(confirm=3.0)
    first = feed(tracker, PresenceSignal.PRESENT, 0)
    assert feed(tracker, PresenceSignal.PRESENT, 2.9).state is BlockingRelationState.CANDIDATE
    relation = feed(tracker, PresenceSignal.PRESENT, 3.0)

    assert relation.state is BlockingRelationState.BLOCKING
    assert relation.blocking_relation_id == first.blocking_relation_id
    assert relation.confirmed_at == at(3.0)
    assert relation.confirm_trusted_seconds == pytest.approx(3.0)


def test_zero_confirm_threshold_confirms_on_first_sample() -> None:
    relation = feed(make_tracker(confirm=0.0), PresenceSignal.PRESENT, 0)
    assert relation.state is BlockingRelationState.BLOCKING
    assert relation.confirmed_at == T0


def test_absent_during_candidate_returns_canceled_record() -> None:
    tracker = make_tracker()
    candidate = feed(tracker, PresenceSignal.PRESENT, 0)
    canceled = feed(tracker, PresenceSignal.ABSENT, 1)

    assert canceled.blocking_relation_id == candidate.blocking_relation_id
    assert canceled.state is BlockingRelationState.CANCELED
    assert canceled.terminated_at == at(1)
    assert canceled.termination_reason == CANDIDATE_NOT_CONFIRMED
    assert canceled.resolved_at is None
    assert tracker.active_relations(SUBJECT) == ()
    assert tracker._slots == {}


def test_reentry_after_cancellation_gets_new_id() -> None:
    tracker = make_tracker()
    first = feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.ABSENT, 1)
    second = feed(tracker, PresenceSignal.PRESENT, 2)
    assert second.blocking_relation_id != first.blocking_relation_id


def test_absent_while_blocking_enters_clear_pending_and_present_returns_to_blocking() -> None:
    tracker = make_tracker(confirm=1.0, clear=3.0)
    blocking = confirm(tracker, confirmed=1.0)
    clear_pending = feed(tracker, PresenceSignal.ABSENT, 2.0)
    reblocked = feed(tracker, PresenceSignal.PRESENT, 3.0)

    assert clear_pending.state is BlockingRelationState.CLEAR_PENDING
    assert clear_pending.clear_trusted_seconds == 0.0
    assert reblocked.state is BlockingRelationState.BLOCKING
    assert reblocked.blocking_relation_id == blocking.blocking_relation_id
    assert reblocked.confirmed_at == blocking.confirmed_at
    assert reblocked.clear_trusted_seconds == 0.0


def test_trusted_blocking_duration_accumulates_across_present_samples() -> None:
    tracker = make_tracker(confirm=1.0, clear=10.0)
    blocking = confirm(tracker, confirmed=1.0)
    later = feed(tracker, PresenceSignal.PRESENT, 4.0)

    assert blocking.confirm_trusted_seconds == pytest.approx(1.0)
    assert later.confirm_trusted_seconds == pytest.approx(4.0)


def test_clear_confirmation_resolves_relation() -> None:
    tracker = make_tracker(confirm=1.0, clear=3.0)
    confirm(tracker, confirmed=1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    resolved = feed(tracker, PresenceSignal.ABSENT, 5.0)

    assert resolved.state is BlockingRelationState.RESOLVED
    assert resolved.terminated_at == at(5.0)
    assert resolved.resolved_at == at(5.0)
    assert resolved.termination_reason == BLOCKING_RELATION_CLEAR_CONFIRMED
    assert resolved.clear_trusted_seconds == pytest.approx(3.0)
    assert tracker.active_relations(SUBJECT) == ()
    assert tracker._slots == {}


def test_zero_clear_threshold_resolves_on_first_absent_sample() -> None:
    tracker = make_tracker(confirm=0.0, clear=0.0)
    confirm(tracker, confirmed=0.0)
    resolved = feed(tracker, PresenceSignal.ABSENT, 1)
    assert resolved.state is BlockingRelationState.RESOLVED
    assert resolved.terminated_at == at(1)


def test_unknown_pauses_confirm_timer_and_preserves_lower_bound() -> None:
    tracker = make_tracker(confirm=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 2)
    paused = feed(
        tracker,
        PresenceSignal.UNKNOWN,
        50,
        observation=unknown(last_reliable=2),
    )
    resumed = feed(tracker, PresenceSignal.PRESENT, 51)

    assert paused.state is BlockingRelationState.CANDIDATE
    assert paused.confirm_trusted_seconds == pytest.approx(2.0)
    assert paused.observation.state is ObservationState.UNKNOWN
    assert resumed.state is BlockingRelationState.CANDIDATE
    assert resumed.confirm_trusted_seconds == pytest.approx(2.0)
    assert feed(tracker, PresenceSignal.PRESENT, 52).state is BlockingRelationState.BLOCKING


def test_unknown_signal_with_observed_status_is_rejected_without_mutation() -> None:
    tracker = make_tracker(confirm=3.0)
    before = feed(tracker, PresenceSignal.PRESENT, 0)

    with pytest.raises(ValueError, match="UNKNOWN presence signal"):
        feed(tracker, PresenceSignal.UNKNOWN, 1, observation=observed(1))

    assert tracker.active_relations(SUBJECT) == (before,)


def test_degraded_sample_also_pauses_timer_even_with_present_signal() -> None:
    tracker = make_tracker(confirm=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 2)
    paused = feed(
        tracker,
        PresenceSignal.PRESENT,
        20,
        observation=degraded(last_reliable=2),
    )
    resumed = feed(tracker, PresenceSignal.PRESENT, 21)

    assert paused.confirm_trusted_seconds == pytest.approx(2.0)
    assert paused.observation.state is ObservationState.DEGRADED
    assert resumed.confirm_trusted_seconds == pytest.approx(2.0)


def test_unknown_pauses_clear_timer_without_resolving() -> None:
    tracker = make_tracker(confirm=1.0, clear=3.0)
    confirm(tracker, confirmed=1.0)
    feed(tracker, PresenceSignal.ABSENT, 2)
    feed(tracker, PresenceSignal.ABSENT, 4)
    paused = feed(
        tracker,
        PresenceSignal.UNKNOWN,
        100,
        observation=unknown(last_reliable=4),
    )
    resumed = feed(tracker, PresenceSignal.ABSENT, 101)

    assert paused.state is BlockingRelationState.CLEAR_PENDING
    assert paused.clear_trusted_seconds == pytest.approx(2.0)
    assert resumed.clear_trusted_seconds == pytest.approx(2.0)
    assert feed(tracker, PresenceSignal.ABSENT, 102).state is BlockingRelationState.RESOLVED


def test_long_unknown_never_resolves_blocking_relation() -> None:
    tracker = make_tracker(confirm=1.0)
    blocking = confirm(tracker, confirmed=1.0)
    feed(tracker, PresenceSignal.PRESENT, 4)
    paused = feed(
        tracker,
        PresenceSignal.UNKNOWN,
        100_000,
        observation=unknown(last_reliable=4),
    )

    assert paused.blocking_relation_id == blocking.blocking_relation_id
    assert paused.state is BlockingRelationState.BLOCKING
    assert paused.observation.state is ObservationState.UNKNOWN
    assert tracker.active_relations(SUBJECT) == (paused,)


def test_relation_keys_are_independent_per_subject_victim_egress_triple() -> None:
    tracker = make_tracker(confirm=1.0)
    first = confirm(tracker, confirmed=1, subject=SUBJECT, victim=VICTIM, egress_zone=EGRESS_ZONE)
    second = confirm(
        tracker, confirmed=1, subject=SUBJECT, victim=VICTIM, egress_zone=OTHER_EGRESS_ZONE
    )
    third = confirm(
        tracker, confirmed=1, subject=OTHER_SUBJECT, victim=VICTIM, egress_zone=EGRESS_ZONE
    )

    assert len({first.blocking_relation_id, second.blocking_relation_id, third.blocking_relation_id}) == 3
    assert len(tracker.active_relations(SUBJECT)) == 2
    assert len(tracker.active_relations(OTHER_SUBJECT)) == 1


def test_all_active_relations_ignores_vehicle_and_excludes_terminal() -> None:
    tracker = make_tracker(confirm=1.0)
    confirm(tracker, confirmed=1, subject=SUBJECT, victim=VICTIM, egress_zone=EGRESS_ZONE)
    confirm(
        tracker, confirmed=1, subject=OTHER_SUBJECT, victim=VICTIM, egress_zone=OTHER_EGRESS_ZONE
    )
    feed(tracker, PresenceSignal.PRESENT, 0, subject=SUBJECT, victim=OTHER_SUBJECT, egress_zone=EGRESS_ZONE)
    canceled_key_signal = feed(
        tracker, PresenceSignal.ABSENT, 1, subject=SUBJECT, victim=OTHER_SUBJECT, egress_zone=EGRESS_ZONE
    )
    assert canceled_key_signal.state is BlockingRelationState.CANCELED

    active = tracker.all_active_relations()
    assert len(active) == 2
    assert all(relation.state is BlockingRelationState.BLOCKING for relation in active)


def test_active_relations_includes_relations_where_vehicle_is_victim() -> None:
    tracker = make_tracker(confirm=1.0)
    relation = confirm(tracker, confirmed=1, subject=SUBJECT, victim=VICTIM)
    assert tracker.active_relations(VICTIM) == (relation,)


def test_active_relations_contains_all_non_terminal_states_only() -> None:
    tracker = make_tracker(confirm=1.0, clear=2.0)
    candidate = feed(tracker, PresenceSignal.PRESENT, 0, egress_zone=EGRESS_ZONE)
    confirm(tracker, start=0, confirmed=1, egress_zone=OTHER_EGRESS_ZONE)
    clear_pending = feed(tracker, PresenceSignal.ABSENT, 3, egress_zone=OTHER_EGRESS_ZONE)

    assert [relation.state for relation in tracker.active_relations(SUBJECT)] == [
        candidate.state,
        clear_pending.state,
    ]


def test_physical_exit_cancels_candidate_and_resolves_confirmed_relations() -> None:
    tracker = make_tracker(confirm=1.0, clear=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0, egress_zone=EGRESS_ZONE)
    confirm(tracker, start=0, confirmed=1, egress_zone=OTHER_EGRESS_ZONE)
    terminated = tracker.physical_exit(physical_vehicle_id=SUBJECT, observed_at=at(2))

    assert {relation.egress_zone_id: relation.state for relation in terminated} == {
        EGRESS_ZONE: BlockingRelationState.CANCELED,
        OTHER_EGRESS_ZONE: BlockingRelationState.RESOLVED,
    }
    for relation in terminated:
        assert relation.termination_reason == PHYSICAL_EXIT
        assert relation.terminated_at == at(2)
    resolved = next(r for r in terminated if r.egress_zone_id == OTHER_EGRESS_ZONE)
    assert resolved.resolved_at == at(2)
    canceled = next(r for r in terminated if r.egress_zone_id == EGRESS_ZONE)
    assert canceled.resolved_at is None
    assert tracker.active_relations(SUBJECT) == ()


def test_physical_exit_by_victim_also_terminates_relation() -> None:
    tracker = make_tracker(confirm=1.0)
    confirm(tracker, confirmed=1)
    terminated = tracker.physical_exit(physical_vehicle_id=VICTIM, observed_at=at(2))
    assert len(terminated) == 1
    assert terminated[0].state is BlockingRelationState.RESOLVED
    assert terminated[0].termination_reason == PHYSICAL_EXIT


def test_physical_exit_validates_all_relation_timestamps_before_mutation() -> None:
    tracker = make_tracker(confirm=3.0)
    first = feed(tracker, PresenceSignal.PRESENT, 10, egress_zone=EGRESS_ZONE)
    second = feed(tracker, PresenceSignal.PRESENT, 20, egress_zone=OTHER_EGRESS_ZONE)

    with pytest.raises(ValueError, match="past|과거"):
        tracker.physical_exit(physical_vehicle_id=SUBJECT, observed_at=at(15))

    assert tracker.active_relations(SUBJECT) == (first, second)


def test_checkpoint_and_restore_state_roundtrip() -> None:
    tracker = make_tracker(confirm=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    checkpoint = tracker.checkpoint_state()
    confirm(tracker, start=0, confirmed=3)

    tracker.restore_state(checkpoint)
    assert tracker.active_relations(SUBJECT)[0].state is BlockingRelationState.CANDIDATE


def test_restored_relation_does_not_count_process_downtime() -> None:
    original = make_tracker(confirm=3.0)
    checkpoint = feed(original, PresenceSignal.PRESENT, 0)
    restored = make_tracker(confirm=3.0)
    restored.restore_active((checkpoint,))

    resumed = feed(restored, PresenceSignal.PRESENT, 100)
    blocking = feed(restored, PresenceSignal.PRESENT, 103)

    assert resumed.confirm_trusted_seconds == 0.0
    assert blocking.state is BlockingRelationState.BLOCKING
    assert blocking.confirm_trusted_seconds == 3.0


def test_restore_active_rejects_terminal_relations() -> None:
    tracker = make_tracker()
    candidate = feed(tracker, PresenceSignal.PRESENT, 0)
    from dataclasses import replace

    terminal = replace(
        candidate,
        state=BlockingRelationState.CANCELED,
        terminated_at=at(1),
        termination_reason="X",
    )
    with pytest.raises(ValueError, match="nonterminal"):
        make_tracker().restore_active((terminal,))


def test_invalid_constructor_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        InMemoryBlockingRelationTracker(
            confirm_duration_seconds=-1,
            clear_duration_seconds=1,
            trusted_sample_max_gap_seconds=1,
        )
    with pytest.raises(ValueError, match="finite"):
        InMemoryBlockingRelationTracker(
            confirm_duration_seconds=1,
            clear_duration_seconds=float("inf"),
            trusted_sample_max_gap_seconds=1,
        )
    for invalid_gap in (0, 0.0000001, 0.0000006):
        with pytest.raises(ValueError, match="trusted_sample_max_gap_seconds"):
            InMemoryBlockingRelationTracker(
                confirm_duration_seconds=1,
                clear_duration_seconds=1,
                trusted_sample_max_gap_seconds=invalid_gap,
            )


def test_naive_and_backwards_observations_are_rejected_without_corrupting_timer() -> None:
    tracker = make_tracker(confirm=3.0)
    feed(tracker, PresenceSignal.PRESENT, 10)
    with pytest.raises(ValueError, match="timezone"):
        tracker.update(
            subject_physical_vehicle_id=SUBJECT,
            victim_physical_vehicle_id=VICTIM,
            egress_zone_id=EGRESS_ZONE,
            signal=PresenceSignal.PRESENT,
            observation=observed(10),
            observed_at=datetime(2026, 7, 31, 10, 0, 0),
        )
    with pytest.raises(ValueError, match="past|과거"):
        feed(tracker, PresenceSignal.PRESENT, 5)
    assert feed(tracker, PresenceSignal.PRESENT, 13).state is BlockingRelationState.BLOCKING

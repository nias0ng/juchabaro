"""카메라·저장소 없이 ZoneVisit 상태축만 검증한다."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.models import PresenceSignal, ZoneDefinitionVersion, ZoneId, ZoneVisitState
from src.parking.zone_visit_tracker import (
    ENTRY_NOT_CONFIRMED,
    PHYSICAL_EXIT,
    ZONE_EXIT_CONFIRMED,
    InMemoryZoneVisitTracker,
)
from src.tracking.models import PhysicalVehicleId

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
OTHER_CAR = PhysicalVehicleId(UUID(int=2))
ZONE = ZoneId(12)
OTHER_ZONE = ZoneId(13)
VERSION = ZoneDefinitionVersion(7)


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
    entry: float = 3.0,
    exit_: float = 3.0,
    max_gap: float = 10.0,
) -> InMemoryZoneVisitTracker:
    return InMemoryZoneVisitTracker(
        zone_definition_version=VERSION,
        entry_confirm_seconds=entry,
        exit_confirm_seconds=exit_,
        trusted_sample_max_gap_seconds=max_gap,
    )


def feed(
    tracker: InMemoryZoneVisitTracker,
    signal: PresenceSignal,
    seconds: float,
    *,
    vehicle: PhysicalVehicleId = CAR,
    zone: ZoneId = ZONE,
    observation: ObservationStatus | None = None,
):
    if observation is None:
        observation = observed(seconds)
    return tracker.update(
        physical_vehicle_id=vehicle,
        zone_id=zone,
        signal=signal,
        observation=observation,
        observed_at=at(seconds),
    )


def enter(
    tracker: InMemoryZoneVisitTracker,
    *,
    start: float = 0.0,
    confirmed: float = 3.0,
    vehicle: PhysicalVehicleId = CAR,
    zone: ZoneId = ZONE,
):
    feed(tracker, PresenceSignal.PRESENT, start, vehicle=vehicle, zone=zone)
    return feed(tracker, PresenceSignal.PRESENT, confirmed, vehicle=vehicle, zone=zone)


def test_absent_or_unknown_without_visit_returns_none() -> None:
    tracker = make_tracker()
    assert feed(tracker, PresenceSignal.ABSENT, 0) is None
    assert feed(
        tracker,
        PresenceSignal.UNKNOWN,
        1,
        observation=unknown(),
    ) is None


def test_first_present_creates_complete_entering_snapshot() -> None:
    visit = feed(make_tracker(), PresenceSignal.PRESENT, 0)

    assert visit.state is ZoneVisitState.ENTERING
    assert isinstance(visit.visit_id, UUID)
    assert visit.zone_definition_version == VERSION
    assert visit.entered_candidate_at == T0
    assert visit.entry_trusted_seconds == 0.0
    assert visit.exit_trusted_seconds == 0.0
    assert visit.entry_confirmation_seconds == 3.0
    assert visit.exit_confirmation_seconds == 3.0
    assert visit.record_version == 1
    assert visit.created_at == visit.updated_at == T0


def test_present_for_confirmation_duration_becomes_inside() -> None:
    tracker = make_tracker(entry=3.0)
    first = feed(tracker, PresenceSignal.PRESENT, 0)
    assert feed(tracker, PresenceSignal.PRESENT, 2.9).state is ZoneVisitState.ENTERING
    visit = feed(tracker, PresenceSignal.PRESENT, 3.0)

    assert visit.state is ZoneVisitState.INSIDE
    assert visit.visit_id == first.visit_id
    assert visit.entered_at == T0
    assert visit.entry_trusted_seconds == pytest.approx(3.0)


def test_long_observed_gap_contributes_zero_and_restarts_entry_chain() -> None:
    tracker = make_tracker(entry=3.0, max_gap=2.0)
    feed(tracker, PresenceSignal.PRESENT, 0)

    after_gap = feed(tracker, PresenceSignal.PRESENT, 100)
    resumed = feed(tracker, PresenceSignal.PRESENT, 102)

    assert after_gap.state is ZoneVisitState.ENTERING
    assert after_gap.entry_trusted_seconds == 0.0
    assert resumed.state is ZoneVisitState.ENTERING
    assert resumed.entry_trusted_seconds == pytest.approx(2.0)


def test_zero_entry_threshold_confirms_on_first_sample() -> None:
    visit = feed(make_tracker(entry=0.0), PresenceSignal.PRESENT, 0)
    assert visit.state is ZoneVisitState.INSIDE
    assert visit.entered_at == T0


def test_absent_during_entering_returns_canceled_record() -> None:
    tracker = make_tracker()
    candidate = feed(tracker, PresenceSignal.PRESENT, 0)
    canceled = feed(tracker, PresenceSignal.ABSENT, 1)

    assert canceled.visit_id == candidate.visit_id
    assert canceled.state is ZoneVisitState.CANCELED
    assert canceled.ended_at == at(1)
    assert canceled.termination_reason == ENTRY_NOT_CONFIRMED
    assert tracker.active_visits(CAR) == ()
    assert tracker._slots == {}


def test_reentry_after_cancellation_gets_new_id() -> None:
    tracker = make_tracker()
    first = feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.ABSENT, 1)
    second = feed(tracker, PresenceSignal.PRESENT, 2)
    assert second.visit_id != first.visit_id


def test_absent_inside_enters_exiting_and_present_cancels_exit() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    inside = enter(tracker, confirmed=1.0)
    exiting = feed(tracker, PresenceSignal.ABSENT, 2.0)
    returned = feed(tracker, PresenceSignal.PRESENT, 3.0)

    assert exiting.state is ZoneVisitState.EXITING
    assert exiting.exit_candidate_at == at(2.0)
    assert returned.state is ZoneVisitState.INSIDE
    assert returned.visit_id == inside.visit_id
    assert returned.entered_at == T0
    assert returned.exit_candidate_at is None
    assert returned.exit_trusted_seconds == 0.0


def test_trusted_present_occupancy_continues_inside_but_excludes_exiting_gap() -> None:
    tracker = make_tracker(entry=1.0, exit_=10.0)
    inside = enter(tracker, confirmed=1.0)
    occupied = feed(tracker, PresenceSignal.PRESENT, 4.0)
    feed(tracker, PresenceSignal.ABSENT, 5.0)
    returned = feed(tracker, PresenceSignal.PRESENT, 20.0)
    resumed = feed(tracker, PresenceSignal.PRESENT, 22.0)

    assert inside.entry_trusted_seconds == pytest.approx(1.0)
    assert occupied.entry_trusted_seconds == pytest.approx(4.0)
    assert returned.entry_trusted_seconds == pytest.approx(4.0)
    assert resumed.entry_trusted_seconds == pytest.approx(6.0)


def test_long_observed_gap_contributes_zero_to_exit_confirmation() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0, max_gap=2.0)
    enter(tracker, confirmed=1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)

    after_gap = feed(tracker, PresenceSignal.ABSENT, 100.0)
    resumed = feed(tracker, PresenceSignal.ABSENT, 102.0)

    assert after_gap.state is ZoneVisitState.EXITING
    assert after_gap.exit_trusted_seconds == 0.0
    assert resumed.state is ZoneVisitState.EXITING
    assert resumed.exit_trusted_seconds == pytest.approx(2.0)


def test_reliable_exit_confirmation_returns_ended_record() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    enter(tracker, confirmed=1.0)
    feed(tracker, PresenceSignal.ABSENT, 2.0)
    ended = feed(tracker, PresenceSignal.ABSENT, 5.0)

    assert ended.state is ZoneVisitState.ENDED
    assert ended.ended_at == at(2.0)
    assert ended.updated_at == at(5.0)
    assert ended.termination_reason == ZONE_EXIT_CONFIRMED
    assert ended.exit_trusted_seconds == pytest.approx(3.0)
    assert tracker.active_visits(CAR) == ()
    assert tracker._slots == {}


def test_zero_exit_threshold_ends_on_first_absent_sample() -> None:
    tracker = make_tracker(entry=0.0, exit_=0.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    ended = feed(tracker, PresenceSignal.ABSENT, 1)
    assert ended.state is ZoneVisitState.ENDED
    assert ended.ended_at == at(1)


def test_unknown_pauses_entry_timer_and_preserves_lower_bound() -> None:
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 2)
    paused = feed(
        tracker,
        PresenceSignal.UNKNOWN,
        50,
        observation=unknown(last_reliable=2),
    )
    resumed = feed(tracker, PresenceSignal.PRESENT, 51)

    assert paused.state is ZoneVisitState.ENTERING
    assert paused.entry_trusted_seconds == pytest.approx(2.0)
    assert paused.observation.state is ObservationState.UNKNOWN
    assert resumed.state is ZoneVisitState.ENTERING
    assert resumed.entry_trusted_seconds == pytest.approx(2.0)
    assert feed(tracker, PresenceSignal.PRESENT, 52).state is ZoneVisitState.INSIDE


def test_unknown_signal_with_observed_status_is_rejected_without_mutation() -> None:
    tracker = make_tracker(entry=3.0)
    before = feed(tracker, PresenceSignal.PRESENT, 0)

    with pytest.raises(ValueError, match="UNKNOWN presence signal"):
        feed(tracker, PresenceSignal.UNKNOWN, 1, observation=observed(1))

    assert tracker.active_visits(CAR) == (before,)


def test_degraded_sample_also_pauses_timer_even_with_present_signal() -> None:
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0)
    feed(tracker, PresenceSignal.PRESENT, 2)
    paused = feed(
        tracker,
        PresenceSignal.PRESENT,
        20,
        observation=degraded(last_reliable=2),
    )
    resumed = feed(tracker, PresenceSignal.PRESENT, 21)

    assert paused.entry_trusted_seconds == pytest.approx(2.0)
    assert paused.observation.state is ObservationState.DEGRADED
    assert resumed.entry_trusted_seconds == pytest.approx(2.0)


def test_pause_without_snapshot_updates_all_visits_and_breaks_timer_chains() -> None:
    tracker = make_tracker(entry=3.0)
    for zone in (ZONE, OTHER_ZONE):
        feed(tracker, PresenceSignal.PRESENT, 0, zone=zone)
        feed(tracker, PresenceSignal.PRESENT, 2, zone=zone)

    paused = tracker.pause_physical_vehicle(
        CAR,
        unknown(last_reliable=2),
        at(100),
    )

    assert {visit.zone_id for visit in paused} == {ZONE, OTHER_ZONE}
    assert all(visit.state is ZoneVisitState.ENTERING for visit in paused)
    assert all(visit.entry_trusted_seconds == pytest.approx(2.0) for visit in paused)
    assert all(visit.observation.state is ObservationState.UNKNOWN for visit in paused)
    for zone in (ZONE, OTHER_ZONE):
        resumed = feed(tracker, PresenceSignal.PRESENT, 101, zone=zone)
        assert resumed.entry_trusted_seconds == pytest.approx(2.0)
        assert feed(tracker, PresenceSignal.PRESENT, 102, zone=zone).state is ZoneVisitState.INSIDE


def test_pause_without_active_visit_returns_empty_tuple() -> None:
    tracker = make_tracker()
    assert tracker.pause_physical_vehicle(CAR, unknown(), at(0)) == ()


def test_pause_rejects_backwards_time_without_partially_mutating_visits() -> None:
    tracker = make_tracker(entry=3.0)
    first = feed(tracker, PresenceSignal.PRESENT, 10, zone=ZONE)
    second = feed(tracker, PresenceSignal.PRESENT, 10, zone=OTHER_ZONE)

    with pytest.raises(ValueError, match="past|과거"):
        tracker.pause_physical_vehicle(CAR, unknown(), at(5))

    assert tracker.active_visits(CAR) == (first, second)


def test_unknown_pauses_exit_timer_without_ending_visit() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    enter(tracker, confirmed=1.0)
    feed(tracker, PresenceSignal.ABSENT, 2)
    feed(tracker, PresenceSignal.ABSENT, 4)
    paused = feed(
        tracker,
        PresenceSignal.UNKNOWN,
        100,
        observation=unknown(last_reliable=4),
    )
    resumed = feed(tracker, PresenceSignal.ABSENT, 101)

    assert paused.state is ZoneVisitState.EXITING
    assert paused.exit_trusted_seconds == pytest.approx(2.0)
    assert resumed.exit_trusted_seconds == pytest.approx(2.0)
    assert feed(tracker, PresenceSignal.ABSENT, 102).state is ZoneVisitState.ENDED


def test_long_unknown_never_terminates_inside_visit() -> None:
    tracker = make_tracker(entry=1.0)
    inside = enter(tracker, confirmed=1.0)
    occupied = feed(tracker, PresenceSignal.PRESENT, 4)
    paused = feed(
        tracker,
        PresenceSignal.UNKNOWN,
        100_000,
        observation=unknown(last_reliable=4),
    )
    resumed = feed(tracker, PresenceSignal.PRESENT, 100_001)
    advanced = feed(tracker, PresenceSignal.PRESENT, 100_003)

    assert paused.visit_id == inside.visit_id
    assert paused.state is ZoneVisitState.INSIDE
    assert paused.observation.state is ObservationState.UNKNOWN
    assert occupied.entry_trusted_seconds == pytest.approx(4.0)
    assert paused.entry_trusted_seconds == pytest.approx(4.0)
    assert resumed.entry_trusted_seconds == pytest.approx(4.0)
    assert advanced.entry_trusted_seconds == pytest.approx(6.0)
    assert tracker.active_visits(CAR) == (advanced,)


def test_vehicle_zone_pairs_are_independent() -> None:
    tracker = make_tracker(entry=1.0)
    first = enter(tracker, confirmed=1, vehicle=CAR, zone=ZONE)
    second = enter(tracker, confirmed=1, vehicle=CAR, zone=OTHER_ZONE)
    third = enter(tracker, confirmed=1, vehicle=OTHER_CAR, zone=ZONE)

    assert len({first.visit_id, second.visit_id, third.visit_id}) == 3
    assert len(tracker.active_visits(CAR)) == 2
    assert len(tracker.active_visits(OTHER_CAR)) == 1


def test_active_visits_contains_all_non_terminal_states_only() -> None:
    tracker = make_tracker(entry=2.0, exit_=2.0)
    entering = feed(tracker, PresenceSignal.PRESENT, 0, zone=ZONE)
    enter(tracker, start=0, confirmed=2, zone=OTHER_ZONE)
    exiting = feed(tracker, PresenceSignal.ABSENT, 3, zone=OTHER_ZONE)

    assert [visit.state for visit in tracker.active_visits(CAR)] == [
        entering.state,
        exiting.state,
    ]


def test_physical_exit_cancels_entering_and_ends_confirmed_visits() -> None:
    tracker = make_tracker(entry=1.0, exit_=3.0)
    feed(tracker, PresenceSignal.PRESENT, 0, zone=ZONE)
    enter(tracker, start=0, confirmed=1, zone=OTHER_ZONE)
    terminated = tracker.physical_exit(physical_vehicle_id=CAR, observed_at=at(2))

    assert {visit.zone_id: visit.state for visit in terminated} == {
        ZONE: ZoneVisitState.CANCELED,
        OTHER_ZONE: ZoneVisitState.ENDED,
    }
    assert all(visit.termination_reason == PHYSICAL_EXIT for visit in terminated)
    assert all(visit.ended_at == at(2) for visit in terminated)
    assert tracker.active_visits(CAR) == ()
    assert tracker.physical_exit(physical_vehicle_id=CAR, observed_at=at(3)) == ()


def test_physical_exit_validates_all_visit_timestamps_before_mutation() -> None:
    tracker = make_tracker(entry=3.0)
    first = feed(tracker, PresenceSignal.PRESENT, 10, zone=ZONE)
    second = feed(tracker, PresenceSignal.PRESENT, 20, zone=OTHER_ZONE)

    with pytest.raises(ValueError, match="past|과거"):
        tracker.physical_exit(physical_vehicle_id=CAR, observed_at=at(15))

    assert tracker.active_visits(CAR) == (first, second)


def test_threshold_and_version_are_snapshotted_per_tracker_scope() -> None:
    visit = feed(make_tracker(entry=4.0, exit_=5.0), PresenceSignal.PRESENT, 0)
    assert visit.zone_definition_version == VERSION
    assert visit.entry_confirmation_seconds == 4.0
    assert visit.exit_confirmation_seconds == 5.0


def test_invalid_constructor_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="version"):
        InMemoryZoneVisitTracker(
            zone_definition_version=ZoneDefinitionVersion(0),
            entry_confirm_seconds=1,
            exit_confirm_seconds=1,
            trusted_sample_max_gap_seconds=1,
        )
    with pytest.raises(ValueError, match="non-negative"):
        InMemoryZoneVisitTracker(
            zone_definition_version=VERSION,
            entry_confirm_seconds=-1,
            exit_confirm_seconds=1,
            trusted_sample_max_gap_seconds=1,
        )
    with pytest.raises(ValueError, match="finite"):
        InMemoryZoneVisitTracker(
            zone_definition_version=VERSION,
            entry_confirm_seconds=1,
            exit_confirm_seconds=float("inf"),
            trusted_sample_max_gap_seconds=1,
        )
    for invalid_gap in (0, 0.0000001, 0.0000006):
        with pytest.raises(ValueError, match="trusted_sample_max_gap_seconds"):
            InMemoryZoneVisitTracker(
                zone_definition_version=VERSION,
                entry_confirm_seconds=1,
                exit_confirm_seconds=1,
                trusted_sample_max_gap_seconds=invalid_gap,
            )


def test_naive_and_backwards_observations_are_rejected_without_corrupting_timer() -> None:
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 10)
    with pytest.raises(ValueError, match="timezone"):
        tracker.update(
            physical_vehicle_id=CAR,
            zone_id=ZONE,
            signal=PresenceSignal.PRESENT,
            observation=observed(10),
            observed_at=datetime(2026, 7, 31, 10, 0, 0),
        )
    with pytest.raises(ValueError, match="past|\uacfc\uac70"):
        feed(tracker, PresenceSignal.PRESENT, 5)
    assert feed(tracker, PresenceSignal.PRESENT, 13).state is ZoneVisitState.INSIDE


def test_same_timestamp_is_allowed_and_order_is_checked_per_pair() -> None:
    tracker = make_tracker(entry=3.0)
    feed(tracker, PresenceSignal.PRESENT, 10, zone=ZONE)
    assert feed(tracker, PresenceSignal.PRESENT, 10, zone=ZONE).state is ZoneVisitState.ENTERING
    other = feed(tracker, PresenceSignal.PRESENT, 5, zone=OTHER_ZONE)
    assert other.state is ZoneVisitState.ENTERING

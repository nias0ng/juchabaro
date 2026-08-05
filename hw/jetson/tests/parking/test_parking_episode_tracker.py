"""카메라·저장소 없이 ParkingEpisode 상태축만 검증한다."""

from datetime import datetime, timedelta, timezone
import math
from uuid import UUID

import pytest

from src.domain.models import ObservationReason, ObservationState, ObservationStatus
from src.parking.models import (
    AssignmentState,
    ParkingAssignment,
    ParkingState,
    ZoneId,
)
from src.parking.parking_episode_tracker import (
    MOVEMENT_CONFIRMED,
    PHYSICAL_EXIT,
    STOP_NOT_CONFIRMED,
    InMemoryParkingEpisodeTracker,
)
from src.tracking.models import MotionSignal, ParkingSessionId, PhysicalVehicleId

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
CAR = PhysicalVehicleId(UUID(int=1))
OTHER_CAR = PhysicalVehicleId(UUID(int=2))
SESSION = ParkingSessionId(77)
OTHER_SESSION = ParkingSessionId(88)
ZONE = ZoneId(12)
OTHER_ZONE = ZoneId(13)
_DEFAULT_ASSIGNMENT = object()


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


def parking_assignment(
    seconds: float,
    *,
    zone_id: ZoneId = ZONE,
    footprint=None,
) -> ParkingAssignment:
    return ParkingAssignment(
        state=AssignmentState.ASSIGNED,
        representative_footprint=(
            (
                (0.1, 0.1),
                (0.3, 0.1),
                (0.3, 0.4),
                (0.1, 0.4),
            )
            if footprint is None
            else footprint
        ),
        confidence=0.9,
        last_stable_at=at(seconds),
        zone_id=zone_id,
    )


def make_tracker(
    parking: float = 3.0,
    movement: float = 2.0,
    max_gap: float = 10.0,
) -> InMemoryParkingEpisodeTracker:
    return InMemoryParkingEpisodeTracker(
        parking_confirmation_seconds=parking,
        movement_confirmation_seconds=movement,
        trusted_sample_max_gap_seconds=max_gap,
    )


def feed(
    tracker: InMemoryParkingEpisodeTracker,
    signal: MotionSignal,
    seconds: float,
    *,
    vehicle: PhysicalVehicleId = CAR,
    session: ParkingSessionId | None = SESSION,
    observation: ObservationStatus | None = None,
    assignment: ParkingAssignment | None | object = _DEFAULT_ASSIGNMENT,
):
    if observation is None:
        observation = observed(seconds)
    resolved_assignment = (
        parking_assignment(seconds)
        if assignment is _DEFAULT_ASSIGNMENT
        else assignment
    )
    return tracker.update(
        physical_vehicle_id=vehicle,
        parking_session_id=session,
        signal=signal,
        observation=observation,
        observed_at=at(seconds),
        assignment=resolved_assignment,
    )


def park(
    tracker: InMemoryParkingEpisodeTracker,
    *,
    start: float = 0.0,
    confirmed: float = 3.0,
    vehicle: PhysicalVehicleId = CAR,
    session: ParkingSessionId | None = SESSION,
):
    feed(
        tracker,
        MotionSignal.STATIONARY,
        start,
        vehicle=vehicle,
        session=session,
    )
    return feed(
        tracker,
        MotionSignal.STATIONARY,
        confirmed,
        vehicle=vehicle,
        session=session,
    )


def test_moving_unknown_or_degraded_without_episode_returns_none() -> None:
    tracker = make_tracker()
    assert feed(tracker, MotionSignal.MOVING, 0) is None
    assert feed(
        tracker,
        MotionSignal.UNKNOWN,
        1,
        observation=unknown(),
    ) is None
    assert feed(
        tracker,
        MotionSignal.STATIONARY,
        2,
        observation=degraded(),
    ) is None


def test_restored_episode_does_not_count_process_downtime() -> None:
    original = make_tracker(parking=3.0)
    checkpoint = feed(original, MotionSignal.STATIONARY, 0)
    restored = make_tracker(parking=3.0)
    restored.restore_active((checkpoint,))

    resumed = feed(restored, MotionSignal.STATIONARY, 100)
    parked = feed(restored, MotionSignal.STATIONARY, 103)

    assert resumed.stationary_trusted_seconds == 0.0
    assert parked.state is ParkingState.PARKED
    assert parked.stationary_trusted_seconds == 3.0


def test_first_stationary_creates_complete_stop_pending_snapshot() -> None:
    episode = feed(make_tracker(parking=4, movement=5), MotionSignal.STATIONARY, 0)

    assert episode.state is ParkingState.STOP_PENDING
    assert isinstance(episode.episode_id, UUID)
    assert episode.parking_session_id == SESSION
    assert episode.assignment == parking_assignment(0)
    assert episode.parked_at is None
    assert episode.stationary_trusted_seconds == 0.0
    assert episode.movement_trusted_seconds == 0.0
    assert episode.parking_confirmation_seconds == 4.0
    assert episode.movement_confirmation_seconds == 5.0
    assert episode.last_signal is MotionSignal.STATIONARY
    assert episode.observation == observed(0)
    assert episode.record_version == 1
    assert episode.publication_revision == 0
    assert episode.created_at == episode.updated_at == T0


def test_stationary_confirmation_attaches_assignment_and_becomes_parked() -> None:
    tracker = make_tracker(parking=3)
    candidate = feed(tracker, MotionSignal.STATIONARY, 0)
    pending = feed(tracker, MotionSignal.STATIONARY, 2.9)
    parked = feed(tracker, MotionSignal.STATIONARY, 3)

    assert pending.state is ParkingState.STOP_PENDING
    assert parked.state is ParkingState.PARKED
    assert parked.episode_id == candidate.episode_id
    assert parked.stationary_trusted_seconds == pytest.approx(3.0)
    assert parked.parked_at == at(3)
    assert pending.assignment == parking_assignment(0)
    assert parked.assignment == pending.assignment
    assert parked.publication_revision == 1


def test_local_only_parked_episode_keeps_publication_revision_zero() -> None:
    tracker = make_tracker(parking=1)
    parked = park(tracker, confirmed=1, session=None)
    assert parked.state is ParkingState.PARKED
    assert parked.publication_revision == 0


def test_assignment_is_required_exactly_when_episode_becomes_parked() -> None:
    tracker = make_tracker(parking=3)
    candidate = feed(tracker, MotionSignal.STATIONARY, 0, assignment=None)

    with pytest.raises(ValueError, match="assignment"):
        feed(tracker, MotionSignal.STATIONARY, 3, assignment=None)

    assert tracker.active_episode(CAR) == candidate
    parked = feed(tracker, MotionSignal.STATIONARY, 3)
    assert parked.state is ParkingState.PARKED


def test_moving_during_stop_pending_returns_canceled_record() -> None:
    tracker = make_tracker(parking=3)
    candidate = feed(tracker, MotionSignal.STATIONARY, 0)
    canceled = feed(tracker, MotionSignal.MOVING, 1)

    assert canceled.episode_id == candidate.episode_id
    assert canceled.state is ParkingState.CANCELED
    assert canceled.ended_at == at(1)
    assert canceled.termination_reason == STOP_NOT_CONFIRMED
    assert tracker.active_episode(CAR) is None
    assert tracker._slots == {}


def test_restop_after_cancellation_gets_new_episode_id() -> None:
    tracker = make_tracker()
    first = feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.MOVING, 1)
    second = feed(tracker, MotionSignal.STATIONARY, 2)
    assert second.episode_id != first.episode_id


def test_unknown_update_pauses_timer_and_preserves_lower_bound() -> None:
    tracker = make_tracker(parking=3)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 2)
    paused = feed(
        tracker,
        MotionSignal.UNKNOWN,
        50,
        observation=unknown(last_reliable=2),
    )
    resumed = feed(tracker, MotionSignal.STATIONARY, 51)

    assert paused.state is ParkingState.STOP_PENDING
    assert paused.stationary_trusted_seconds == pytest.approx(2.0)
    assert paused.observation.state is ObservationState.UNKNOWN
    assert resumed.stationary_trusted_seconds == pytest.approx(2.0)
    assert feed(tracker, MotionSignal.STATIONARY, 52).state is ParkingState.PARKED


def test_degraded_sample_pauses_timer_even_with_stationary_signal() -> None:
    tracker = make_tracker(parking=3)
    feed(tracker, MotionSignal.STATIONARY, 0)
    feed(tracker, MotionSignal.STATIONARY, 2)
    paused = feed(
        tracker,
        MotionSignal.STATIONARY,
        20,
        observation=degraded(last_reliable=2),
    )
    resumed = feed(tracker, MotionSignal.STATIONARY, 21)

    assert paused.stationary_trusted_seconds == pytest.approx(2.0)
    assert paused.observation.state is ObservationState.DEGRADED
    assert resumed.stationary_trusted_seconds == pytest.approx(2.0)


def test_pause_without_snapshot_updates_observation_and_breaks_timer_chain() -> None:
    tracker = make_tracker(parking=3)
    feed(tracker, MotionSignal.STATIONARY, 0)
    before = feed(tracker, MotionSignal.STATIONARY, 2)
    paused = tracker.pause_physical_vehicle(
        CAR,
        unknown(last_reliable=2),
        at(100),
    )

    assert len(paused) == 1
    assert paused[0].state is ParkingState.STOP_PENDING
    assert paused[0].stationary_trusted_seconds == pytest.approx(2.0)
    assert paused[0].record_version == before.record_version + 1
    assert paused[0].observation.state is ObservationState.UNKNOWN
    assert feed(tracker, MotionSignal.STATIONARY, 101).stationary_trusted_seconds == 2
    assert feed(tracker, MotionSignal.STATIONARY, 102).state is ParkingState.PARKED


def test_pause_without_active_episode_returns_empty_tuple() -> None:
    tracker = make_tracker()
    assert tracker.pause_physical_vehicle(CAR, unknown(), at(0)) == ()


def test_pause_rejects_observed_status_even_without_active_episode() -> None:
    tracker = make_tracker()

    with pytest.raises(ValueError, match="UNKNOWN or DEGRADED"):
        tracker.pause_physical_vehicle(CAR, observed(0), at(0))


def test_long_unknown_pause_never_terminates_parked_episode() -> None:
    tracker = make_tracker(parking=1)
    parked = park(tracker, confirmed=1)
    (paused,) = tracker.pause_physical_vehicle(
        CAR,
        unknown(last_reliable=1),
        at(100_000),
    )

    assert paused.episode_id == parked.episode_id
    assert paused.state is ParkingState.PARKED
    assert tracker.active_episode(CAR) == paused


def test_two_vehicles_and_their_pause_chains_are_independent() -> None:
    tracker = make_tracker(parking=3)
    feed(tracker, MotionSignal.STATIONARY, 0, vehicle=CAR)
    other = feed(tracker, MotionSignal.STATIONARY, 0, vehicle=OTHER_CAR)
    tracker.pause_physical_vehicle(CAR, degraded(), at(10))

    advanced_other = feed(tracker, MotionSignal.STATIONARY, 3, vehicle=OTHER_CAR)
    assert advanced_other.state is ParkingState.PARKED
    assert advanced_other.episode_id == other.episode_id
    assert tracker.active_episode(CAR).state is ParkingState.STOP_PENDING


def test_session_can_bind_late_but_cannot_change_during_active_episode() -> None:
    tracker = make_tracker(parking=10)
    opened = feed(tracker, MotionSignal.STATIONARY, 0, session=None)
    bound = feed(tracker, MotionSignal.STATIONARY, 1, session=SESSION)

    assert opened.parking_session_id is None
    assert bound.parking_session_id == SESSION
    with pytest.raises(ValueError, match="parking_session_id"):
        feed(tracker, MotionSignal.STATIONARY, 2, session=OTHER_SESSION)
    assert tracker.active_episode(CAR) == bound


def test_late_session_binding_publishes_already_parked_episode() -> None:
    tracker = make_tracker(parking=1)
    parked = park(tracker, confirmed=1, session=None)
    published = feed(tracker, MotionSignal.STATIONARY, 2, session=SESSION)

    assert parked.publication_revision == 0
    assert published.parking_session_id == SESSION
    assert published.publication_revision == 1


def test_parked_assignment_is_frozen_for_late_publication() -> None:
    tracker = make_tracker(parking=1, movement=3)
    parked = park(tracker, confirmed=1, session=None)

    still_parked = feed(
        tracker,
        MotionSignal.STATIONARY,
        2,
        session=None,
        assignment=parking_assignment(2, zone_id=OTHER_ZONE),
    )
    feed(
        tracker,
        MotionSignal.MOVING,
        3,
        session=None,
        assignment=parking_assignment(3, zone_id=OTHER_ZONE),
    )
    returned = feed(
        tracker,
        MotionSignal.STATIONARY,
        4,
        session=SESSION,
        assignment=parking_assignment(4, zone_id=OTHER_ZONE),
    )

    assert still_parked.assignment == parked.assignment
    assert returned.assignment == parked.assignment
    assert returned.parking_session_id == SESSION
    assert returned.publication_revision == 1


def test_parked_assignment_latches_first_trusted_candidate_across_later_jitter() -> None:
    tracker = make_tracker(parking=2)
    first = parking_assignment(
        0,
        footprint=((0.10, 0.1), (0.30, 0.1), (0.30, 0.4), (0.10, 0.4)),
    )
    representative = parking_assignment(
        1,
        footprint=((0.11, 0.1), (0.31, 0.1), (0.31, 0.4), (0.11, 0.4)),
    )
    final_jitter = parking_assignment(
        2,
        zone_id=OTHER_ZONE,
        footprint=((0.70, 0.1), (0.90, 0.1), (0.90, 0.4), (0.70, 0.4)),
    )

    feed(tracker, MotionSignal.STATIONARY, 0, assignment=first)
    feed(tracker, MotionSignal.STATIONARY, 1, assignment=representative)
    parked = feed(
        tracker,
        MotionSignal.STATIONARY,
        2,
        assignment=final_jitter,
    )

    assert parked.state is ParkingState.PARKED
    assert parked.assignment == first


def test_restored_stop_pending_preserves_durable_placement_candidate() -> None:
    original = make_tracker(parking=2)
    representative = parking_assignment(
        0,
        footprint=((0.11, 0.1), (0.31, 0.1), (0.31, 0.4), (0.11, 0.4)),
    )
    feed(
        original,
        MotionSignal.STATIONARY,
        0,
        assignment=representative,
    )
    checkpoint = feed(
        original,
        MotionSignal.STATIONARY,
        1,
        assignment=parking_assignment(1),
    )

    restored = make_tracker(parking=99)
    restored.restore_active((checkpoint,))

    assert restored.active_episode(CAR) == checkpoint
    assert restored.active_episode(CAR).assignment == representative

    # downtime은 timer에 더하지 않고, resumed frame과 경계 frame의 jitter도
    # restart 전에 latch한 최초 trusted placement를 바꾸지 않는다.
    resumed = feed(
        restored,
        MotionSignal.STATIONARY,
        100,
        assignment=representative,
    )
    final_jitter = parking_assignment(
        101,
        zone_id=OTHER_ZONE,
        footprint=((0.70, 0.1), (0.90, 0.1), (0.90, 0.4), (0.70, 0.4)),
    )
    parked = feed(
        restored,
        MotionSignal.STATIONARY,
        101,
        assignment=final_jitter,
    )

    assert resumed.state is ParkingState.STOP_PENDING
    assert parked.state is ParkingState.PARKED
    assert parked.assignment == representative


def test_late_session_binding_during_move_pending_publishes_parked_fact() -> None:
    tracker = make_tracker(parking=1, movement=3)
    park(tracker, confirmed=1, session=None)
    moving = feed(tracker, MotionSignal.MOVING, 2, session=None)
    published = feed(tracker, MotionSignal.MOVING, 3, session=SESSION)

    assert moving.publication_revision == 0
    assert published.state is ParkingState.MOVE_PENDING
    assert published.publication_revision == 1


def test_moving_after_parked_enters_move_pending() -> None:
    tracker = make_tracker(parking=1, movement=3)
    parked = park(tracker, confirmed=1)
    moving = feed(tracker, MotionSignal.MOVING, 2)

    assert moving.state is ParkingState.MOVE_PENDING
    assert moving.episode_id == parked.episode_id
    assert moving.movement_candidate_at == at(2)
    assert moving.movement_trusted_seconds == 0.0
    assert moving.assignment == parked.assignment


def test_stationary_during_move_pending_returns_to_same_parked_episode() -> None:
    tracker = make_tracker(parking=1, movement=3)
    parked = park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)
    returned = feed(tracker, MotionSignal.STATIONARY, 2.5)

    assert returned.state is ParkingState.PARKED
    assert returned.episode_id == parked.episode_id
    assert returned.parked_at == parked.parked_at
    assert returned.movement_candidate_at is None
    assert returned.movement_trusted_seconds == 0.0


def test_confirmed_movement_ends_episode_at_confirmation_time() -> None:
    tracker = make_tracker(parking=1, movement=3)
    parked = park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)
    ended = feed(tracker, MotionSignal.MOVING, 5)

    assert ended.state is ParkingState.ENDED
    assert ended.episode_id == parked.episode_id
    assert ended.ended_at == at(5)
    assert ended.updated_at == at(5)
    assert ended.termination_reason == MOVEMENT_CONFIRMED
    assert ended.assignment == parked.assignment
    assert ended.publication_revision == 2
    assert tracker.active_episode(CAR) is None
    assert tracker._slots == {}


def test_fractional_movement_threshold_ends_at_greater_or_equal_boundary() -> None:
    tracker = make_tracker(parking=1, movement=0.5)
    park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)

    before_boundary = feed(tracker, MotionSignal.MOVING, 2.499999)
    at_boundary = feed(tracker, MotionSignal.MOVING, 2.5)

    assert before_boundary.state is ParkingState.MOVE_PENDING
    assert before_boundary.movement_trusted_seconds == pytest.approx(0.499999)
    assert at_boundary.state is ParkingState.ENDED
    assert at_boundary.movement_trusted_seconds == pytest.approx(0.5)
    assert at_boundary.ended_at == at(2.5)
    assert at_boundary.termination_reason == MOVEMENT_CONFIRMED


def test_restored_move_pending_preserves_only_pre_restart_trusted_time() -> None:
    original = make_tracker(parking=1, movement=0.5)
    park(original, confirmed=1)
    feed(original, MotionSignal.MOVING, 2)
    checkpoint = feed(original, MotionSignal.MOVING, 2.2)

    restored = make_tracker(parking=99, movement=99)
    restored.restore_active((checkpoint,))

    resumed = feed(restored, MotionSignal.MOVING, 100)
    before_boundary = feed(restored, MotionSignal.MOVING, 100.299999)
    at_boundary = feed(restored, MotionSignal.MOVING, 100.3)

    assert resumed.state is ParkingState.MOVE_PENDING
    assert resumed.movement_trusted_seconds == pytest.approx(0.2)
    assert before_boundary.state is ParkingState.MOVE_PENDING
    assert before_boundary.movement_trusted_seconds == pytest.approx(0.499999)
    assert at_boundary.state is ParkingState.ENDED
    assert at_boundary.movement_trusted_seconds == pytest.approx(0.5)


def test_restored_move_pending_stationary_returns_to_same_parked_episode() -> None:
    original = make_tracker(parking=1, movement=0.5)
    parked = park(original, confirmed=1)
    checkpoint = feed(original, MotionSignal.MOVING, 2)

    restored = make_tracker()
    restored.restore_active((checkpoint,))
    returned = feed(restored, MotionSignal.STATIONARY, 100)

    assert returned.state is ParkingState.PARKED
    assert returned.episode_id == parked.episode_id
    assert returned.movement_trusted_seconds == 0.0
    assert returned.movement_candidate_at is None


def test_local_only_movement_end_keeps_publication_revision_zero() -> None:
    tracker = make_tracker(parking=1, movement=1)
    park(tracker, confirmed=1, session=None)
    feed(tracker, MotionSignal.MOVING, 2, session=None)
    ended = feed(tracker, MotionSignal.MOVING, 3, session=None)
    assert ended.state is ParkingState.ENDED
    assert ended.ended_at == at(3)
    assert ended.publication_revision == 0


def test_zero_movement_threshold_ends_on_first_moving_sample() -> None:
    tracker = make_tracker(parking=1, movement=0)
    park(tracker, confirmed=1)
    ended = feed(tracker, MotionSignal.MOVING, 2)
    assert ended.state is ParkingState.ENDED
    assert ended.ended_at == at(2)


def test_unknown_pause_preserves_movement_timer_lower_bound() -> None:
    tracker = make_tracker(parking=1, movement=0.5)
    park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)
    feed(tracker, MotionSignal.MOVING, 2.2)
    tracker.pause_physical_vehicle(CAR, unknown(last_reliable=2.2), at(100))
    resumed = feed(tracker, MotionSignal.MOVING, 101)
    before_boundary = feed(tracker, MotionSignal.MOVING, 101.299999)
    ended = feed(tracker, MotionSignal.MOVING, 101.3)

    assert resumed.state is ParkingState.MOVE_PENDING
    assert resumed.movement_trusted_seconds == pytest.approx(0.2)
    assert before_boundary.state is ParkingState.MOVE_PENDING
    assert before_boundary.movement_trusted_seconds == pytest.approx(0.499999)
    assert ended.state is ParkingState.ENDED
    assert ended.movement_trusted_seconds == pytest.approx(0.5)


def test_unknown_motion_update_preserves_movement_timer_lower_bound() -> None:
    tracker = make_tracker(parking=1, movement=0.5)
    park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)
    feed(tracker, MotionSignal.MOVING, 2.2)

    paused = feed(
        tracker,
        MotionSignal.UNKNOWN,
        100,
        observation=ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
            last_reliable_observed_at=at(2.2),
        ),
    )
    resumed = feed(tracker, MotionSignal.MOVING, 101)
    ended = feed(tracker, MotionSignal.MOVING, 101.3)

    assert paused.state is ParkingState.MOVE_PENDING
    assert paused.movement_trusted_seconds == pytest.approx(0.2)
    assert paused.observation.reason is ObservationReason.DEPENDENCY_UNAVAILABLE
    assert resumed.movement_trusted_seconds == pytest.approx(0.2)
    assert ended.state is ParkingState.ENDED
    assert ended.movement_trusted_seconds == pytest.approx(0.5)


def test_long_gap_between_observed_samples_does_not_advance_stationary_timer() -> None:
    tracker = make_tracker(parking=3, max_gap=1)
    feed(tracker, MotionSignal.STATIONARY, 0)

    after_gap = feed(tracker, MotionSignal.STATIONARY, 100)
    progressed = feed(tracker, MotionSignal.STATIONARY, 101)

    assert after_gap.state is ParkingState.STOP_PENDING
    assert after_gap.stationary_trusted_seconds == 0
    assert progressed.stationary_trusted_seconds == pytest.approx(1)


def test_long_gap_between_observed_samples_does_not_confirm_movement() -> None:
    tracker = make_tracker(parking=1, movement=2, max_gap=1)
    park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)

    after_gap = feed(tracker, MotionSignal.MOVING, 100)
    progressed = feed(tracker, MotionSignal.MOVING, 101)

    assert after_gap.state is ParkingState.MOVE_PENDING
    assert after_gap.movement_trusted_seconds == 0
    assert progressed.movement_trusted_seconds == pytest.approx(1)


def test_unknown_motion_cannot_be_stored_as_observed() -> None:
    tracker = make_tracker()

    with pytest.raises(ValueError, match="UNKNOWN motion signal"):
        feed(tracker, MotionSignal.UNKNOWN, 0, observation=observed(0))

    assert tracker.active_episode(CAR) is None


def test_return_to_parked_restarts_next_movement_timer() -> None:
    tracker = make_tracker(parking=1, movement=3)
    park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)
    feed(tracker, MotionSignal.MOVING, 4)
    feed(tracker, MotionSignal.STATIONARY, 5)
    feed(tracker, MotionSignal.MOVING, 6)

    assert feed(tracker, MotionSignal.MOVING, 8).state is ParkingState.MOVE_PENDING
    assert feed(tracker, MotionSignal.MOVING, 9).state is ParkingState.ENDED


def test_new_episode_after_movement_end_gets_new_id() -> None:
    tracker = make_tracker(parking=1, movement=1)
    first = park(tracker, confirmed=1)
    feed(tracker, MotionSignal.MOVING, 2)
    feed(tracker, MotionSignal.MOVING, 3)
    feed(tracker, MotionSignal.STATIONARY, 10)
    second = feed(tracker, MotionSignal.STATIONARY, 11)

    assert second.state is ParkingState.PARKED
    assert second.episode_id != first.episode_id


def test_reliable_stationary_sample_does_not_rewrite_parked_assignment() -> None:
    tracker = make_tracker(parking=1)
    parked = park(tracker, confirmed=1)
    reassigned = parking_assignment(2, zone_id=OTHER_ZONE)
    updated = feed(
        tracker,
        MotionSignal.STATIONARY,
        2,
        assignment=reassigned,
    )

    assert updated.episode_id == parked.episode_id
    assert updated.assignment == parked.assignment


def test_physical_exit_cancels_stop_pending() -> None:
    tracker = make_tracker()
    pending = feed(tracker, MotionSignal.STATIONARY, 0)
    canceled = tracker.physical_exit(physical_vehicle_id=CAR, observed_at=at(1))

    assert canceled.episode_id == pending.episode_id
    assert canceled.state is ParkingState.CANCELED
    assert canceled.ended_at == at(1)
    assert canceled.termination_reason == PHYSICAL_EXIT
    assert tracker.active_episode(CAR) is None


@pytest.mark.parametrize("move_pending", [False, True])
def test_physical_exit_ends_parked_states_without_unparked(move_pending: bool) -> None:
    tracker = make_tracker(parking=1, movement=3)
    parked = park(tracker, confirmed=1)
    if move_pending:
        feed(tracker, MotionSignal.MOVING, 2)
    ended = tracker.physical_exit(physical_vehicle_id=CAR, observed_at=at(3))

    assert ended.state is ParkingState.ENDED
    assert ended.assignment == parked.assignment
    assert ended.ended_at == at(3)
    assert ended.termination_reason == PHYSICAL_EXIT
    assert ended.publication_revision == parked.publication_revision
    assert tracker.physical_exit(physical_vehicle_id=CAR, observed_at=at(4)) is None


def test_physical_exit_does_not_publish_local_only_parked_episode() -> None:
    tracker = make_tracker(parking=1)
    park(tracker, confirmed=1, session=None)
    ended = tracker.physical_exit(physical_vehicle_id=CAR, observed_at=at(2))
    assert ended.publication_revision == 0


def test_active_episode_returns_only_non_terminal_state_and_is_a_pure_read() -> None:
    tracker = make_tracker(parking=1, movement=1)
    assert tracker.active_episode(CAR) is None
    parked = park(tracker, confirmed=1)
    assert tracker.active_episode(CAR) == parked
    assert tracker.active_episode(CAR) == tracker.active_episode(CAR)
    feed(tracker, MotionSignal.MOVING, 2)
    feed(tracker, MotionSignal.MOVING, 3)
    assert tracker.active_episode(CAR) is None


def test_thresholds_are_snapshotted_in_each_episode() -> None:
    episode = feed(make_tracker(parking=4, movement=5), MotionSignal.STATIONARY, 0)
    assert episode.parking_confirmation_seconds == 4
    assert episode.movement_confirmation_seconds == 5


@pytest.mark.parametrize(
    ("parking", "movement"),
    [
        (0, 1),
        (-1, 1),
        (math.inf, 1),
        (1, -1),
        (1, math.inf),
    ],
)
def test_invalid_thresholds_are_rejected(parking: float, movement: float) -> None:
    with pytest.raises(ValueError, match="seconds"):
        make_tracker(parking=parking, movement=movement)


@pytest.mark.parametrize("max_gap", [0, -1, math.inf, 0.0000001, 0.0000006])
def test_invalid_trusted_sample_max_gap_is_rejected(max_gap: float) -> None:
    with pytest.raises(ValueError, match="trusted_sample_max_gap_seconds"):
        make_tracker(max_gap=max_gap)


def test_naive_and_backwards_observations_do_not_corrupt_timer() -> None:
    tracker = make_tracker(parking=3)
    feed(tracker, MotionSignal.STATIONARY, 10)
    with pytest.raises(ValueError, match="timezone"):
        tracker.update(
            physical_vehicle_id=CAR,
            parking_session_id=SESSION,
            signal=MotionSignal.STATIONARY,
            observation=observed(10),
            observed_at=datetime(2026, 7, 31, 10, 0, 0),
            assignment=parking_assignment(10),
        )
    with pytest.raises(ValueError, match="past|과거"):
        feed(tracker, MotionSignal.STATIONARY, 5)
    assert feed(tracker, MotionSignal.STATIONARY, 13).state is ParkingState.PARKED


def test_pause_rejects_backwards_time_without_mutating_episode() -> None:
    tracker = make_tracker()
    episode = feed(tracker, MotionSignal.STATIONARY, 10)
    with pytest.raises(ValueError, match="past|과거"):
        tracker.pause_physical_vehicle(CAR, unknown(), at(5))
    assert tracker.active_episode(CAR) == episode


def test_same_timestamp_is_allowed_and_order_is_checked_per_vehicle() -> None:
    tracker = make_tracker(parking=3)
    feed(tracker, MotionSignal.STATIONARY, 10, vehicle=CAR)
    same_time = feed(tracker, MotionSignal.STATIONARY, 10, vehicle=CAR)
    other = feed(tracker, MotionSignal.STATIONARY, 5, vehicle=OTHER_CAR)
    assert same_time.state is ParkingState.STOP_PENDING
    assert other.state is ParkingState.STOP_PENDING

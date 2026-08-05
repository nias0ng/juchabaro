"""ToF 구역 점유 상태 머신의 순수 결정론 테스트."""

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
import math

import pytest

from src.application.sensor_occupancy import (
    OccupancyPolicy,
    OccupancyState,
    OccupancyStateManager,
    OccupancyTransition,
    OccupancyUpdate,
    SensorZoneBinding,
    ZoneOccupancySnapshot,
)
from src.domain.models import (
    ObservationReason,
    ObservationState,
    ObservationStatus,
)
from src.parking.models import ZoneId
from src.sensors.models import (
    TOF_SENSOR_TYPE,
    SensorObservation,
    SensorReadFailure,
    SensorReadFailureReason,
)


T0 = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
DISABLED_SENSOR_ID = "tof_disabled_zone"
EV_SENSOR_ID = "tof_ev_charging_zone"


def _bindings() -> tuple[SensorZoneBinding, ...]:
    return (
        SensorZoneBinding(
            sensor_id=DISABLED_SENSOR_ID,
            zone_id=ZoneId(1),
        ),
        SensorZoneBinding(
            sensor_id=EV_SENSOR_ID,
            zone_id=ZoneId(2),
        ),
    )


def _policy(
    *,
    enter_confirm_seconds: float = 2.0,
    exit_confirm_seconds: float = 3.0,
    trusted_sample_max_gap_seconds: float = 1.0,
    stale_after_seconds: float = 2.0,
) -> OccupancyPolicy:
    return OccupancyPolicy(
        enter_distance_mm=150.0,
        exit_distance_mm=220.0,
        enter_confirm_seconds=enter_confirm_seconds,
        exit_confirm_seconds=exit_confirm_seconds,
        trusted_sample_max_gap_seconds=trusted_sample_max_gap_seconds,
        stale_after_seconds=stale_after_seconds,
    )


def _manager(
    *,
    policy: OccupancyPolicy | None = None,
) -> OccupancyStateManager:
    return OccupancyStateManager(
        bindings=_bindings(),
        policy=policy or _policy(),
    )


def _observation(
    distance_mm: float,
    *,
    sensor_id: str = DISABLED_SENSOR_ID,
    seconds: float = 0.0,
    sensor_type: str = TOF_SENSOR_TYPE,
    observed_at: datetime | None = None,
) -> SensorObservation:
    return SensorObservation(
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        value=distance_mm,
        observed_at=observed_at or T0 + timedelta(seconds=seconds),
    )


def _failure(
    *,
    sensor_id: str = DISABLED_SENSOR_ID,
    seconds: float = 0.0,
    observed_at: datetime | None = None,
) -> SensorReadFailure:
    return SensorReadFailure(
        sensor_id=sensor_id,
        observed_at=observed_at or T0 + timedelta(seconds=seconds),
        reason=SensorReadFailureReason.TIMEOUT,
        message="timeout",
    )


def _snapshot(**overrides) -> ZoneOccupancySnapshot:
    values = {
        "sensor_id": DISABLED_SENSOR_ID,
        "zone_id": ZoneId(1),
        "stable_state": OccupancyState.UNKNOWN,
        "stable_since": None,
        "candidate_target": None,
        "candidate_started_at": None,
        "candidate_elapsed_seconds": 0.0,
        "observation": ObservationStatus(
            state=ObservationState.UNKNOWN,
            reason=ObservationReason.DEPENDENCY_UNAVAILABLE,
        ),
        "last_distance_mm": None,
        "last_input_at": None,
        "last_failure": None,
        "revision": 0,
    }
    values.update(overrides)
    return ZoneOccupancySnapshot(**values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"enter_distance_mm": 220.0}, "enter_distance_mm"),
        ({"enter_distance_mm": 221.0}, "enter_distance_mm"),
        ({"enter_distance_mm": math.nan}, "enter_distance_mm"),
        ({"exit_distance_mm": math.inf}, "exit_distance_mm"),
        ({"enter_distance_mm": True}, "enter_distance_mm"),
        ({"enter_confirm_seconds": -0.1}, "enter_confirm_seconds"),
        ({"exit_confirm_seconds": -0.1}, "exit_confirm_seconds"),
        (
            {"trusted_sample_max_gap_seconds": 0.0},
            "trusted_sample_max_gap_seconds",
        ),
        (
            {"trusted_sample_max_gap_seconds": -1.0},
            "trusted_sample_max_gap_seconds",
        ),
        ({"stale_after_seconds": 0.0}, "stale_after_seconds"),
        ({"stale_after_seconds": -1.0}, "stale_after_seconds"),
    ],
)
def test_policy_rejects_invalid_values(overrides, message) -> None:
    values = {
        "enter_distance_mm": 150.0,
        "exit_distance_mm": 220.0,
        "enter_confirm_seconds": 2.0,
        "exit_confirm_seconds": 3.0,
        "trusted_sample_max_gap_seconds": 1.0,
        "stale_after_seconds": 2.0,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        OccupancyPolicy(**values)


def test_policy_accepts_zero_confirmation() -> None:
    policy = _policy(
        enter_confirm_seconds=0.0,
        exit_confirm_seconds=0.0,
    )

    assert policy.enter_confirm_seconds == 0.0
    assert policy.exit_confirm_seconds == 0.0


def test_policy_rejects_stale_window_shorter_than_trusted_gap() -> None:
    with pytest.raises(ValueError, match="stale_after_seconds"):
        _policy(
            trusted_sample_max_gap_seconds=2.0,
            stale_after_seconds=1.999,
        )


@pytest.mark.parametrize("sensor_id", ["", " ", "\t"])
def test_binding_rejects_blank_sensor_id(sensor_id: str) -> None:
    with pytest.raises(ValueError, match="sensor_id"):
        SensorZoneBinding(sensor_id=sensor_id, zone_id=ZoneId(1))


@pytest.mark.parametrize("zone_id", [0, -1, True, 1.5])
def test_binding_rejects_non_positive_integer_zone_id(zone_id) -> None:
    with pytest.raises(ValueError, match="zone_id"):
        SensorZoneBinding(
            sensor_id=DISABLED_SENSOR_ID,
            zone_id=zone_id,
        )


def test_manager_rejects_duplicate_sensor_id() -> None:
    bindings = (
        SensorZoneBinding(sensor_id="same", zone_id=ZoneId(1)),
        SensorZoneBinding(sensor_id="same", zone_id=ZoneId(2)),
    )

    with pytest.raises(ValueError, match="sensor_id"):
        OccupancyStateManager(bindings=bindings, policy=_policy())


def test_manager_rejects_duplicate_zone_id() -> None:
    bindings = (
        SensorZoneBinding(sensor_id="first", zone_id=ZoneId(1)),
        SensorZoneBinding(sensor_id="second", zone_id=ZoneId(1)),
    )

    with pytest.raises(ValueError, match="zone_id"):
        OccupancyStateManager(bindings=bindings, policy=_policy())


def test_manager_rejects_empty_bindings() -> None:
    with pytest.raises(ValueError, match="하나 이상"):
        OccupancyStateManager(bindings=(), policy=_policy())


def test_manager_rejects_non_binding_element() -> None:
    with pytest.raises(TypeError, match="SensorZoneBinding"):
        OccupancyStateManager(
            bindings=(object(),),  # type: ignore[arg-type]
            policy=_policy(),
        )


def test_initial_snapshots_follow_binding_order_and_are_unknown() -> None:
    manager = _manager()

    snapshots = manager.snapshots()

    assert [item.sensor_id for item in snapshots] == [
        DISABLED_SENSOR_ID,
        EV_SENSOR_ID,
    ]
    assert all(item.stable_state is OccupancyState.UNKNOWN for item in snapshots)
    assert all(item.stable_since is None for item in snapshots)
    assert all(item.candidate_target is None for item in snapshots)
    assert all(item.candidate_elapsed_seconds == 0.0 for item in snapshots)
    assert all(item.revision == 0 for item in snapshots)
    assert all(
        item.observation.state is ObservationState.UNKNOWN
        for item in snapshots
    )
    assert all(
        item.observation.reason
        is ObservationReason.DEPENDENCY_UNAVAILABLE
        for item in snapshots
    )


def test_snapshot_is_immutable() -> None:
    snapshot = _manager().snapshot_for_sensor(DISABLED_SENSOR_ID)

    with pytest.raises(FrozenInstanceError):
        snapshot.revision = 1


def test_snapshot_rejects_candidate_time_without_candidate() -> None:
    with pytest.raises(ValueError, match="candidate_started_at"):
        _snapshot(candidate_started_at=T0)


@pytest.mark.parametrize(
    "stable_state",
    [OccupancyState.VACANT, OccupancyState.OCCUPIED],
)
def test_snapshot_rejects_stable_state_without_stable_since(
    stable_state: OccupancyState,
) -> None:
    with pytest.raises(ValueError, match="stable_since"):
        _snapshot(stable_state=stable_state)


@pytest.mark.parametrize(
    "transition_overrides",
    [
        {"sensor_id": EV_SENSOR_ID},
        {"zone_id": ZoneId(2)},
        {
            "previous_state": OccupancyState.UNKNOWN,
            "current_state": OccupancyState.VACANT,
        },
        {"revision": 2},
    ],
)
def test_update_rejects_transition_that_does_not_match_snapshot(
    transition_overrides,
) -> None:
    snapshot = _snapshot(
        stable_state=OccupancyState.OCCUPIED,
        stable_since=T0,
        observation=ObservationStatus(
            state=ObservationState.OBSERVED,
            last_reliable_observed_at=T0,
        ),
        last_distance_mm=150.0,
        last_input_at=T0,
        revision=1,
    )
    transition_values = {
        "sensor_id": DISABLED_SENSOR_ID,
        "zone_id": ZoneId(1),
        "previous_state": OccupancyState.UNKNOWN,
        "current_state": OccupancyState.OCCUPIED,
        "candidate_started_at": T0,
        "confirmed_at": T0,
        "confirming_distance_mm": 150.0,
        "revision": 1,
    }
    transition_values.update(transition_overrides)
    transition = OccupancyTransition(**transition_values)

    with pytest.raises(ValueError, match="결과 snapshot"):
        OccupancyUpdate(
            snapshot=snapshot,
            transition=transition,
        )


@pytest.mark.parametrize(
    ("distance_mm", "expected_target"),
    [
        (149.9, OccupancyState.OCCUPIED),
        (150.0, OccupancyState.OCCUPIED),
        (150.1, None),
        (219.9, None),
        (220.0, OccupancyState.VACANT),
        (220.1, OccupancyState.VACANT),
    ],
)
def test_distance_boundaries(
    distance_mm: float,
    expected_target: OccupancyState | None,
) -> None:
    manager = _manager()

    update = manager.apply_observation(
        _observation(distance_mm),
        monotonic_now=0.0,
    )

    assert update.snapshot.candidate_target is expected_target
    assert update.snapshot.stable_state is OccupancyState.UNKNOWN
    assert update.transition is None


@pytest.mark.parametrize(
    ("second_sample_seconds", "transition_expected"),
    [
        (1.999, False),
        (2.0, True),
        (2.001, True),
    ],
)
def test_enter_confirmation_boundary(
    second_sample_seconds: float,
    transition_expected: bool,
) -> None:
    manager = _manager(
        policy=_policy(
            trusted_sample_max_gap_seconds=3.0,
            stale_after_seconds=3.0,
        )
    )
    manager.apply_observation(
        _observation(150.0),
        monotonic_now=0.0,
    )

    update = manager.apply_observation(
        _observation(149.9, seconds=second_sample_seconds),
        monotonic_now=second_sample_seconds,
    )

    assert (update.transition is not None) is transition_expected
    if transition_expected:
        assert update.snapshot.stable_state is OccupancyState.OCCUPIED
        assert update.snapshot.stable_since == (
            T0 + timedelta(seconds=second_sample_seconds)
        )
        assert update.transition is not None
        assert update.transition.previous_state is OccupancyState.UNKNOWN
        assert update.transition.current_state is OccupancyState.OCCUPIED
        assert update.transition.candidate_started_at == T0
        assert update.transition.confirmed_at == (
            T0 + timedelta(seconds=second_sample_seconds)
        )
        assert update.transition.revision == update.snapshot.revision


def test_exit_confirmation_boundary() -> None:
    manager = _manager(
        policy=_policy(
            enter_confirm_seconds=0.0,
            exit_confirm_seconds=3.0,
            trusted_sample_max_gap_seconds=3.0,
            stale_after_seconds=3.0,
        )
    )
    occupied = manager.apply_observation(
        _observation(150.0),
        monotonic_now=0.0,
    )
    candidate = manager.apply_observation(
        _observation(220.0, seconds=1.0),
        monotonic_now=1.0,
    )
    immediately_before = manager.apply_observation(
        _observation(220.1, seconds=3.999),
        monotonic_now=3.999,
    )
    confirmed = manager.apply_observation(
        _observation(220.1, seconds=4.0),
        monotonic_now=4.0,
    )

    assert occupied.snapshot.stable_state is OccupancyState.OCCUPIED
    assert candidate.transition is None
    assert candidate.snapshot.candidate_started_at == (
        T0 + timedelta(seconds=1.0)
    )
    assert immediately_before.transition is None
    assert (
        immediately_before.snapshot.stable_state
        is OccupancyState.OCCUPIED
    )

    assert confirmed.snapshot.stable_state is OccupancyState.VACANT
    assert confirmed.snapshot.stable_since == T0 + timedelta(seconds=4.0)
    assert confirmed.snapshot.revision == 4
    assert confirmed.transition is not None
    assert confirmed.transition.previous_state is OccupancyState.OCCUPIED
    assert confirmed.transition.current_state is OccupancyState.VACANT
    assert confirmed.transition.candidate_started_at == (
        T0 + timedelta(seconds=1.0)
    )
    assert confirmed.transition.confirmed_at == (
        T0 + timedelta(seconds=4.0)
    )
    assert confirmed.transition.confirming_distance_mm == 220.1
    assert confirmed.transition.revision == confirmed.snapshot.revision


def test_zero_confirmation_changes_state_on_first_sample() -> None:
    manager = _manager(
        policy=_policy(
            enter_confirm_seconds=0.0,
            exit_confirm_seconds=0.0,
        )
    )

    occupied = manager.apply_observation(
        _observation(150.0),
        monotonic_now=0.0,
    )
    vacant = manager.apply_observation(
        _observation(220.0, seconds=1.0),
        monotonic_now=1.0,
    )

    assert occupied.transition is not None
    assert occupied.transition.previous_state is OccupancyState.UNKNOWN
    assert occupied.transition.current_state is OccupancyState.OCCUPIED
    assert vacant.transition is not None
    assert vacant.transition.previous_state is OccupancyState.OCCUPIED
    assert vacant.transition.current_state is OccupancyState.VACANT


def test_unknown_to_vacant_is_a_real_transition() -> None:
    manager = _manager(policy=_policy(exit_confirm_seconds=0.0))

    update = manager.apply_observation(
        _observation(220.0),
        monotonic_now=0.0,
    )

    assert update.transition is not None
    assert update.transition.previous_state is OccupancyState.UNKNOWN
    assert update.transition.current_state is OccupancyState.VACANT


def test_candidate_is_cancelled_by_stable_evidence() -> None:
    manager = _manager(policy=_policy(exit_confirm_seconds=0.0))
    manager.apply_observation(_observation(220.0), monotonic_now=0.0)
    manager.apply_observation(
        _observation(150.0, seconds=1.0),
        monotonic_now=1.0,
    )

    update = manager.apply_observation(
        _observation(220.0, seconds=1.5),
        monotonic_now=1.5,
    )

    assert update.snapshot.stable_state is OccupancyState.VACANT
    assert update.snapshot.candidate_target is None
    assert update.transition is None


def test_candidate_is_cancelled_by_hysteresis() -> None:
    manager = _manager()
    manager.apply_observation(_observation(150.0), monotonic_now=0.0)

    update = manager.apply_observation(
        _observation(180.0, seconds=0.5),
        monotonic_now=0.5,
    )

    assert update.snapshot.candidate_target is None
    assert update.snapshot.candidate_elapsed_seconds == 0.0


def test_opposite_evidence_restarts_candidate() -> None:
    manager = _manager()
    manager.apply_observation(_observation(150.0), monotonic_now=0.0)

    update = manager.apply_observation(
        _observation(220.0, seconds=0.5),
        monotonic_now=0.5,
    )

    assert update.snapshot.candidate_target is OccupancyState.VACANT
    assert update.snapshot.candidate_started_at == T0 + timedelta(seconds=0.5)
    assert update.snapshot.candidate_elapsed_seconds == 0.0


def test_gap_above_trusted_max_restarts_candidate() -> None:
    manager = _manager(
        policy=_policy(
            enter_confirm_seconds=2.0,
            trusted_sample_max_gap_seconds=1.0,
        )
    )
    manager.apply_observation(_observation(150.0), monotonic_now=0.0)

    update = manager.apply_observation(
        _observation(150.0, seconds=1.001),
        monotonic_now=1.001,
    )

    assert update.snapshot.candidate_started_at == (
        T0 + timedelta(seconds=1.001)
    )
    assert update.snapshot.candidate_elapsed_seconds == 0.0
    assert update.transition is None


def test_gap_equal_to_trusted_max_continues_candidate() -> None:
    manager = _manager(
        policy=_policy(
            enter_confirm_seconds=2.0,
            trusted_sample_max_gap_seconds=1.0,
            stale_after_seconds=1.0,
        )
    )
    manager.apply_observation(
        _observation(150.0),
        monotonic_now=0.0,
    )

    update = manager.apply_observation(
        _observation(150.0, seconds=1.0),
        monotonic_now=1.0,
    )

    assert update.snapshot.candidate_started_at == T0
    assert update.snapshot.candidate_elapsed_seconds == 1.0
    assert update.transition is None


def test_failure_without_reliable_history_is_unknown() -> None:
    manager = _manager()

    update = manager.apply_failure(
        _failure(),
        monotonic_now=0.0,
    )

    assert update.snapshot.observation.state is ObservationState.UNKNOWN
    assert (
        update.snapshot.observation.reason
        is ObservationReason.DEPENDENCY_UNAVAILABLE
    )
    assert update.snapshot.last_reliable_observed_at is None
    assert update.transition is None


def test_failure_degrades_then_becomes_unknown_at_exact_stale_boundary() -> None:
    manager = _manager(
        policy=_policy(
            enter_confirm_seconds=0.0,
            stale_after_seconds=2.0,
        )
    )
    occupied = manager.apply_observation(
        _observation(150.0),
        monotonic_now=0.0,
    )

    degraded = manager.apply_failure(
        _failure(seconds=1.999),
        monotonic_now=1.999,
    )
    stale = manager.apply_failure(
        _failure(seconds=2.0),
        monotonic_now=2.0,
    )

    assert occupied.snapshot.stable_state is OccupancyState.OCCUPIED
    assert degraded.snapshot.observation.state is ObservationState.DEGRADED
    assert stale.snapshot.observation.state is ObservationState.UNKNOWN
    assert stale.snapshot.stable_state is OccupancyState.OCCUPIED
    assert stale.snapshot.last_distance_mm == 150.0
    assert stale.snapshot.last_reliable_observed_at == T0
    assert stale.transition is None


def test_failure_cancels_candidate_and_recovery_does_not_restore_elapsed_time() -> None:
    manager = _manager(
        policy=_policy(
            enter_confirm_seconds=2.0,
            trusted_sample_max_gap_seconds=3.0,
            stale_after_seconds=3.0,
        )
    )
    manager.apply_observation(_observation(150.0), monotonic_now=0.0)
    failed = manager.apply_failure(
        _failure(seconds=0.5),
        monotonic_now=0.5,
    )
    recovered = manager.apply_observation(
        _observation(150.0, seconds=1.0),
        monotonic_now=1.0,
    )
    not_yet_confirmed = manager.apply_observation(
        _observation(150.0, seconds=2.9),
        monotonic_now=2.9,
    )

    assert failed.snapshot.candidate_target is None
    assert recovered.snapshot.observation.state is ObservationState.OBSERVED
    assert recovered.snapshot.candidate_elapsed_seconds == 0.0
    assert not_yet_confirmed.snapshot.candidate_elapsed_seconds == pytest.approx(
        1.9
    )
    assert not_yet_confirmed.transition is None


def test_recovery_preserves_last_failure_diagnostic() -> None:
    manager = _manager()
    failure = _failure()

    failed = manager.apply_failure(
        failure,
        monotonic_now=0.0,
    )
    recovered = manager.apply_observation(
        _observation(180.0, seconds=1.0),
        monotonic_now=1.0,
    )

    assert failed.snapshot.last_failure == failure
    assert recovered.snapshot.observation.state is ObservationState.OBSERVED
    assert recovered.snapshot.last_failure == failure
    assert recovered.snapshot.last_reliable_observed_at == (
        T0 + timedelta(seconds=1.0)
    )


def test_transition_is_emitted_once_after_confirmation() -> None:
    manager = _manager(
        policy=_policy(
            enter_confirm_seconds=1.0,
            trusted_sample_max_gap_seconds=2.0,
        )
    )

    candidate = manager.apply_observation(
        _observation(150.0),
        monotonic_now=0.0,
    )
    confirmed = manager.apply_observation(
        _observation(150.0, seconds=1.0),
        monotonic_now=1.0,
    )
    repeated = manager.apply_observation(
        _observation(149.0, seconds=2.0),
        monotonic_now=2.0,
    )

    assert candidate.transition is None
    assert confirmed.transition is not None
    assert repeated.transition is None
    assert repeated.snapshot.stable_state is OccupancyState.OCCUPIED


def test_sensors_keep_independent_candidates_revisions_and_failures() -> None:
    manager = _manager()
    manager.apply_observation(
        _observation(150.0, sensor_id=DISABLED_SENSOR_ID),
        monotonic_now=0.0,
    )
    ev_failure = manager.apply_failure(
        _failure(sensor_id=EV_SENSOR_ID),
        monotonic_now=0.0,
    )

    disabled = manager.snapshot_for_zone(ZoneId(1))
    ev = manager.snapshot_for_zone(ZoneId(2))

    assert disabled.candidate_target is OccupancyState.OCCUPIED
    assert disabled.revision == 1
    assert ev.candidate_target is None
    assert ev.revision == 1
    assert ev_failure.snapshot.sensor_id == EV_SENSOR_ID


@pytest.mark.parametrize(
    "distance_mm",
    [math.nan, math.inf, -math.inf, -0.1, True],
)
def test_observation_rejects_invalid_distance(distance_mm) -> None:
    manager = _manager()

    with pytest.raises(ValueError, match="observation.value"):
        manager.apply_observation(
            _observation(distance_mm),
            monotonic_now=0.0,
        )

    assert manager.snapshot_for_sensor(DISABLED_SENSOR_ID).revision == 0


def test_observation_rejects_unknown_sensor_id() -> None:
    with pytest.raises(ValueError, match="sensor_id"):
        _manager().apply_observation(
            _observation(150.0, sensor_id="unknown"),
            monotonic_now=0.0,
        )


def test_failure_rejects_unknown_sensor_id() -> None:
    with pytest.raises(ValueError, match="sensor_id"):
        _manager().apply_failure(
            _failure(sensor_id="unknown"),
            monotonic_now=0.0,
        )


def test_observation_rejects_wrong_sensor_type() -> None:
    with pytest.raises(ValueError, match="sensor_type"):
        _manager().apply_observation(
            _observation(150.0, sensor_type="camera"),
            monotonic_now=0.0,
        )


def test_input_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _manager().apply_observation(
            _observation(
                150.0,
                observed_at=datetime(2026, 8, 6, 10, 0),
            ),
            monotonic_now=0.0,
        )


def test_input_rejects_wall_clock_regression() -> None:
    manager = _manager()
    manager.apply_observation(
        _observation(150.0, seconds=1.0),
        monotonic_now=1.0,
    )

    with pytest.raises(ValueError, match="과거"):
        manager.apply_failure(
            _failure(seconds=0.5),
            monotonic_now=1.5,
        )


@pytest.mark.parametrize("monotonic_now", [True, math.nan, math.inf, -0.1])
def test_input_rejects_invalid_monotonic_value(monotonic_now) -> None:
    with pytest.raises(ValueError, match="monotonic_now"):
        _manager().apply_observation(
            _observation(150.0),
            monotonic_now=monotonic_now,
        )


def test_input_rejects_monotonic_regression_for_same_sensor() -> None:
    manager = _manager()
    manager.apply_observation(
        _observation(150.0),
        monotonic_now=1.0,
    )

    with pytest.raises(ValueError, match="감소"):
        manager.apply_observation(
            _observation(150.0, seconds=1.0),
            monotonic_now=0.999,
        )


def test_same_monotonic_value_is_allowed_for_different_sensors() -> None:
    manager = _manager()

    disabled = manager.apply_observation(
        _observation(150.0, sensor_id=DISABLED_SENSOR_ID),
        monotonic_now=10.0,
    )
    ev = manager.apply_observation(
        _observation(220.0, sensor_id=EV_SENSOR_ID),
        monotonic_now=10.0,
    )

    assert disabled.snapshot.revision == 1
    assert ev.snapshot.revision == 1


def test_unknown_snapshot_queries_fail_explicitly() -> None:
    manager = _manager()

    with pytest.raises(ValueError, match="sensor_id"):
        manager.snapshot_for_sensor("unknown")
    with pytest.raises(ValueError, match="zone_id"):
        manager.snapshot_for_zone(ZoneId(999))

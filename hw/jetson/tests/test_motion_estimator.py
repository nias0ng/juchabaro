"""MotionEstimator의 시간 기반 PhysicalVehicle별 evidence 계약."""

from datetime import datetime, timedelta, timezone

import pytest

from src.domain.models import ObservationState, ObservationStatus
from src.tracking.models import (
    BoundingBox,
    MotionEstimateReason,
    MotionSignal,
    PhysicalVehicleSnapshot,
)
from src.tracking.motion_estimator import MotionEstimator


START = datetime(2026, 8, 5, tzinfo=timezone.utc)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def box(*, shift_x: float = 0.0, size: float = 1.0) -> BoundingBox:
    width = 0.10 * size
    height = 0.20 * size
    x1 = 0.20 + shift_x
    y1 = 0.20
    return BoundingBox(x1=x1, y1=y1, x2=x1 + width, y2=y1 + height)


def update(
    estimator: MotionEstimator,
    seconds: float,
    *,
    vehicle: str = "veh-1",
    shift_x: float = 0.0,
    size: float = 1.0,
):
    return estimator.update(
        physical_vehicle_id=vehicle,
        bbox=box(shift_x=shift_x, size=size),
        observed_at=at(seconds),
    )


def test_first_sample_is_unknown_with_diagnostic_reason():
    estimate = update(MotionEstimator(), 0)

    assert estimate.signal is MotionSignal.UNKNOWN
    assert estimate.reason is MotionEstimateReason.FIRST_SAMPLE
    assert estimate.sample_count == 1
    assert estimate.window_span_seconds == 0
    assert estimate.normalized_displacement is None


def test_sample_count_and_time_span_must_both_be_sufficient():
    estimator = MotionEstimator(min_samples=3, min_observation_span_seconds=0.2)

    update(estimator, 0)
    second = update(estimator, 0.1)
    still_too_short = update(estimator, 0.15)

    assert second.reason is MotionEstimateReason.INSUFFICIENT_HISTORY
    assert still_too_short.reason is MotionEstimateReason.INSUFFICIENT_HISTORY
    assert still_too_short.sample_count == 3
    assert still_too_short.window_span_seconds == pytest.approx(0.15)


def test_bbox_jitter_is_stationary_after_warmup():
    estimator = MotionEstimator()
    shifts = (0.0, 0.001, -0.001, 0.002, -0.002, 0.001, 0.0)

    estimates = [
        update(estimator, index * 0.1, shift_x=shift)
        for index, shift in enumerate(shifts)
    ]

    assert estimates[-1].signal is MotionSignal.STATIONARY
    assert estimates[-1].reason is MotionEstimateReason.STATIONARY_EVIDENCE
    assert estimates[-1].normalized_displacement is not None
    assert estimates[-1].normalized_displacement < 0.03
    assert estimates[-1].normalized_trend is not None
    assert estimates[-1].normalized_trend < 0.03


def test_single_intermediate_outlier_does_not_become_moving():
    estimator = MotionEstimator()
    shifts = (0.0, 0.001, 0.15, -0.001, 0.001, 0.0)

    estimate = None
    for index, shift in enumerate(shifts):
        estimate = update(estimator, index * 0.1, shift_x=shift)

    assert estimate is not None
    assert estimate.signal is MotionSignal.STATIONARY


def test_five_fps_single_endpoint_spike_is_unknown():
    """5fps 최소 3-sample 창의 마지막 bbox 하나만 튀어도 이동으로 확정하지 않는다."""

    estimator = MotionEstimator()
    estimates = [
        update(estimator, seconds, shift_x=shift)
        for seconds, shift in zip(
            (0.0, 0.2, 0.4),
            (0.0, 0.0, 0.03),
            strict=True,
        )
    ]

    endpoint = estimates[-1]
    assert endpoint.normalized_displacement == pytest.approx(0.134164, rel=1e-5)
    assert endpoint.normalized_trend == pytest.approx(0.134164, rel=1e-5)
    assert endpoint.trend_consistency == 0
    assert endpoint.signal is MotionSignal.UNKNOWN
    assert endpoint.reason is MotionEstimateReason.AMBIGUOUS_EVIDENCE


def test_five_fps_three_consecutive_positions_support_real_motion():
    estimator = MotionEstimator()
    estimate = None
    for seconds, shift in zip(
        (0.0, 0.2, 0.4),
        (0.0, 0.015, 0.03),
        strict=True,
    ):
        estimate = update(estimator, seconds, shift_x=shift)

    assert estimate is not None
    assert estimate.signal is MotionSignal.MOVING
    assert estimate.reason is MotionEstimateReason.MOVING_EVIDENCE
    assert estimate.trend_consistency == pytest.approx(1.0)


def test_irregular_sample_intervals_use_velocity_for_temporal_support():
    estimator = MotionEstimator()
    estimate = None
    for seconds, shift in zip(
        (0.0, 0.1, 0.5),
        (0.0, 0.01, 0.05),
        strict=True,
    ):
        estimate = update(estimator, seconds, shift_x=shift)

    assert estimate is not None
    assert estimate.signal is MotionSignal.MOVING
    assert estimate.reason is MotionEstimateReason.MOVING_EVIDENCE
    assert estimate.trend_consistency == pytest.approx(1.0)


def test_thirty_fps_single_endpoint_spike_is_absorbed_by_robust_window():
    estimator = MotionEstimator()
    estimates = [
        update(
            estimator,
            index / 30,
            shift_x=0.03 if index == 23 else 0.0,
        )
        for index in range(24)
    ]

    assert estimates[-1].signal is not MotionSignal.MOVING


def test_thirty_fps_continuous_slow_motion_remains_moving():
    estimator = MotionEstimator()
    estimates = [
        update(estimator, index / 30, shift_x=index * 0.0015)
        for index in range(24)
    ]

    assert estimates[-1].signal is MotionSignal.MOVING
    assert estimates[-1].trend_consistency > 0.9


def test_continuous_slow_motion_eventually_becomes_and_remains_moving():
    estimator = MotionEstimator()
    estimates = [
        update(estimator, index * 0.1, shift_x=index * 0.005)
        for index in range(13)
    ]

    first_moving_index = next(
        index
        for index, estimate in enumerate(estimates)
        if estimate.signal is MotionSignal.MOVING
    )
    assert first_moving_index >= 2
    assert all(
        estimate.signal is MotionSignal.MOVING
        for estimate in estimates[first_moving_index:]
    )
    assert estimates[-1].reason is MotionEstimateReason.MOVING_EVIDENCE
    assert estimates[-1].trend_consistency == pytest.approx(1.0)


def test_dead_band_returns_unknown_instead_of_reusing_previous_signal():
    estimator = MotionEstimator()
    estimates = [
        update(estimator, index * 0.1, shift_x=index * 0.005)
        for index in range(4)
    ]

    assert estimates[-1].signal is MotionSignal.UNKNOWN
    assert estimates[-1].reason is MotionEstimateReason.AMBIGUOUS_EVIDENCE
    assert 0.03 < estimates[-1].normalized_displacement < 0.10


def test_sample_gap_breaks_chain_and_requires_new_warmup():
    estimator = MotionEstimator(max_sample_gap_seconds=0.5)
    update(estimator, 0)
    update(estimator, 0.1)
    before_gap = update(estimator, 0.2)

    after_gap = update(estimator, 0.8)
    second = update(estimator, 0.9)
    recovered = update(estimator, 1.0)

    assert before_gap.signal is MotionSignal.STATIONARY
    assert after_gap.signal is MotionSignal.UNKNOWN
    assert after_gap.reason is MotionEstimateReason.SAMPLE_GAP_EXCEEDED
    assert after_gap.latest_sample_gap_seconds == pytest.approx(0.6)
    assert after_gap.sample_count == 1
    assert second.reason is MotionEstimateReason.INSUFFICIENT_HISTORY
    assert recovered.signal is MotionSignal.STATIONARY


def test_time_window_prunes_old_samples_even_below_gap_limit():
    estimator = MotionEstimator(
        window_seconds=0.25,
        min_observation_span_seconds=0.1,
        max_sample_gap_seconds=1.0,
        min_samples=3,
    )
    update(estimator, 0)
    update(estimator, 0.1)
    assert update(estimator, 0.2).signal is MotionSignal.STATIONARY

    pruned = update(estimator, 0.5)

    assert pruned.signal is MotionSignal.UNKNOWN
    assert pruned.reason is MotionEstimateReason.INSUFFICIENT_HISTORY
    assert pruned.sample_count == 1
    assert pruned.latest_sample_gap_seconds == pytest.approx(0.3)


def test_pause_breaks_only_selected_vehicle_chain():
    estimator = MotionEstimator(
        min_samples=3,
        min_observation_span_seconds=0.1,
    )
    for vehicle in ("veh-1", "veh-2"):
        update(estimator, 0, vehicle=vehicle)
        update(estimator, 0.1, vehicle=vehicle)
        assert update(estimator, 0.2, vehicle=vehicle).signal is MotionSignal.STATIONARY

    estimator.pause("veh-1")

    assert update(estimator, 0.3, vehicle="veh-1").reason is MotionEstimateReason.FIRST_SAMPLE
    assert update(estimator, 0.3, vehicle="veh-2").signal is MotionSignal.STATIONARY


def test_pause_all_breaks_every_vehicle_chain():
    estimator = MotionEstimator()
    update(estimator, 0, vehicle="veh-1")
    update(estimator, 0, vehicle="veh-2")

    estimator.pause_all()

    assert update(estimator, 0.1, vehicle="veh-1").reason is MotionEstimateReason.FIRST_SAMPLE
    assert update(estimator, 0.1, vehicle="veh-2").reason is MotionEstimateReason.FIRST_SAMPLE


def test_forget_removes_history_after_physical_vehicle_termination():
    estimator = MotionEstimator()
    update(estimator, 0)

    estimator.forget("veh-1")

    assert update(estimator, 0.1).reason is MotionEstimateReason.FIRST_SAMPLE


def test_bbox_scale_normalization_produces_same_relative_decision():
    estimator = MotionEstimator()
    small_estimate = None
    large_estimate = None
    for index in range(7):
        small_estimate = update(
            estimator,
            index * 0.1,
            vehicle="small",
            shift_x=index * 0.0025,
            size=0.5,
        )
        large_estimate = update(
            estimator,
            index * 0.1,
            vehicle="large",
            shift_x=index * 0.005,
            size=1.0,
        )

    assert small_estimate is not None
    assert large_estimate is not None
    assert small_estimate.signal is MotionSignal.MOVING
    assert large_estimate.signal is MotionSignal.MOVING
    assert small_estimate.normalized_displacement == pytest.approx(
        large_estimate.normalized_displacement
    )
    assert small_estimate.normalized_trend == pytest.approx(
        large_estimate.normalized_trend
    )


def test_non_monotonic_timestamp_is_rejected_without_corrupting_history():
    estimator = MotionEstimator(
        min_samples=3,
        min_observation_span_seconds=0.1,
    )
    update(estimator, 0)

    with pytest.raises(ValueError, match="strictly increasing"):
        update(estimator, 0)

    update(estimator, 0.1)
    recovered = update(estimator, 0.2)
    assert recovered.signal is MotionSignal.STATIONARY


def test_snapshot_rejects_motion_diagnostic_with_different_signal():
    estimate = update(MotionEstimator(), 0)

    with pytest.raises(ValueError, match="signal must match"):
        PhysicalVehicleSnapshot(
            physical_vehicle_id="veh-1",
            track_segment_id=1,
            bbox=box(),
            confidence=0.9,
            motion_signal=MotionSignal.MOVING,
            observed_at=at(0),
            camera_id="camera-1",
            observation=ObservationStatus(
                state=ObservationState.OBSERVED,
                last_reliable_observed_at=at(0),
            ),
            motion_estimate=estimate,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"min_observation_span_seconds": 1.0, "window_seconds": 0.5}, "cannot exceed"),
        ({"stationary_threshold": 0.1, "moving_threshold": 0.1}, "must be smaller"),
        ({"min_samples": 2}, "at least 3"),
        ({"min_trend_consistency": 0.0}, "greater than 0"),
    ],
)
def test_configuration_invariants(kwargs, message):
    with pytest.raises(ValueError, match=message):
        MotionEstimator(**kwargs)

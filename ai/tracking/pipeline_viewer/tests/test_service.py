"""Viewer 입력 계약과 기본 경로 테스트."""

import json

import pytest

from pipeline_viewer.service import (
    EPOCH,
    ViewerInputError,
    ViewerPolicy,
    _policy_snapshot_json,
    build_allow_example,
    default_idempotency_key,
    default_paths,
    parse_entry_event,
)


def test_default_model_path_uses_jetson_model_directory() -> None:
    assert default_paths().model.as_posix().endswith(
        "hw/jetson/model/yolov8s.pt"
    )


def test_placement_defaults_are_forwarded_to_monitoring_policy() -> None:
    viewer_policy = ViewerPolicy()
    monitoring = viewer_policy.to_monitoring_policy()

    assert viewer_policy.bad_parking_min_primary_overlap_ratio == 0.75
    assert viewer_policy.bad_parking_min_secondary_overlap_ratio == 0.25
    assert viewer_policy.out_of_zone_min_spot_overlap_ratio == 0.50
    assert monitoring.bad_parking_min_primary_overlap_ratio == 0.75
    assert monitoring.bad_parking_min_secondary_overlap_ratio == 0.25
    assert monitoring.out_of_zone_min_spot_overlap_ratio == 0.50


def test_yolo_confidence_default_is_low_for_viewer_diagnostics() -> None:
    assert ViewerPolicy().confidence == 0.01


def test_reidentification_window_bridges_observed_multisecond_id_switch() -> None:
    policy = ViewerPolicy()

    assert policy.reidentification_max_gap_seconds == 4.0
    assert (
        policy.reidentification_max_gap_seconds
        < policy.absence_confirmation_seconds
    )


def test_viewer_motion_policy_is_provisional_and_forwarded_exactly() -> None:
    policy = ViewerPolicy()
    monitoring = policy.to_monitoring_policy()

    assert policy.parking_confirm_seconds == 5.0
    assert policy.parking_move_confirm_seconds == 0.5
    assert policy.motion_window_seconds == pytest.approx(0.75)
    assert policy.motion_min_observation_span_seconds == pytest.approx(0.20)
    assert policy.motion_max_sample_gap_seconds == pytest.approx(0.50)
    assert policy.motion_stationary_threshold == pytest.approx(0.03)
    assert policy.motion_moving_threshold == pytest.approx(0.10)
    assert policy.motion_min_samples == 3
    assert policy.motion_min_trend_consistency == pytest.approx(0.60)
    assert monitoring.motion_window_seconds == policy.motion_window_seconds
    assert (
        monitoring.motion_min_observation_span_seconds
        == policy.motion_min_observation_span_seconds
    )
    assert (
        monitoring.motion_max_sample_gap_seconds
        == policy.motion_max_sample_gap_seconds
    )
    assert (
        monitoring.motion_stationary_threshold
        == policy.motion_stationary_threshold
    )
    assert monitoring.motion_moving_threshold == policy.motion_moving_threshold
    assert monitoring.motion_min_samples == policy.motion_min_samples
    assert (
        monitoring.motion_min_trend_consistency
        == policy.motion_min_trend_consistency
    )


def test_policy_snapshot_is_canonical_and_contains_actual_test_overrides() -> None:
    snapshot = _policy_snapshot_json(ViewerPolicy())

    assert snapshot == _policy_snapshot_json(ViewerPolicy())
    decoded = json.loads(snapshot)
    assert decoded["parking_confirm_seconds"] == 5.0
    assert decoded["parking_move_confirm_seconds"] == 0.5
    assert decoded["motion_stationary_threshold"] == pytest.approx(0.03)
    assert list(decoded) == sorted(decoded)


def test_allow_example_matches_current_entry_event_wire() -> None:
    raw = build_allow_example()
    payload = parse_entry_event(raw)

    assert payload.access_decision == "ALLOW"
    assert payload.entry_time == EPOCH
    assert payload.decision_revision == 1
    assert payload.session_context is not None
    assert payload.session_context.session_id == 1
    assert payload.session_context.vehicle_id == 1
    assert default_idempotency_key(raw).endswith("-r1")


def test_entry_event_time_must_match_video_zero() -> None:
    raw = json.loads(build_allow_example())
    raw["entryTime"] = "2026-08-03T00:00:00+00:00"

    with pytest.raises(ViewerInputError, match="영상 첫 프레임"):
        parse_entry_event(json.dumps(raw))

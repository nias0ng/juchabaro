"""수동 live viewer도 production MonitoringPolicy 계약을 빠짐없이 조립한다."""

from pathlib import Path

from scripts.watch_live_stream import build_parser, build_policy


def test_build_policy_populates_identity_motion_and_placement_fields() -> None:
    args = build_parser().parse_args(
        [
            "--video",
            "pilot.mp4",
            "--zones-file",
            "zones.json",
            "--calibration",
            "calibration.json",
            "--model-path",
            "best.pt",
        ]
    )

    assert args.video == Path("pilot.mp4")
    policy = build_policy(args)

    assert policy.reidentification_max_gap_seconds == 4.0
    assert policy.reidentification_min_score == 0.42
    assert policy.reidentification_ambiguity_margin == 0.08
    assert policy.bad_parking_min_primary_overlap_ratio == 0.75
    assert policy.bad_parking_min_secondary_overlap_ratio == 0.25
    assert policy.out_of_zone_min_spot_overlap_ratio == 0.50
    assert policy.parking_confirm_seconds == 5.0
    assert policy.parking_move_confirm_seconds == 0.5
    assert policy.motion_window_seconds == 0.75
    assert policy.motion_min_observation_span_seconds == 0.20
    assert policy.motion_max_sample_gap_seconds == 0.50
    assert policy.motion_stationary_threshold == 0.03
    assert policy.motion_moving_threshold == 0.10
    assert policy.motion_min_samples == 3
    assert policy.motion_min_trend_consistency == 0.60

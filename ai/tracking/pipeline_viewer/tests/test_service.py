"""Viewer 입력 계약과 기본 경로 테스트."""

import json
from pathlib import Path

import pytest

from pipeline_viewer import service
from pipeline_viewer.service import (
    EPOCH,
    SideMaskingDetector,
    ViewerInputError,
    ViewerPolicy,
    _asset_snapshot_json,
    _policy_snapshot_json,
    build_allow_example,
    default_idempotency_key,
    default_paths,
    parse_entry_event,
)
from src.config.monitoring_policy import build_incident_rule_timings
from src.parking.egress_aisle_registry import EgressAisleRegistry
from src.parking.zone_registry import ZoneRegistry


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


def test_incident_rule_timings_are_explicit_and_forwarded_exactly() -> None:
    policy = ViewerPolicy()
    monitoring = policy.to_monitoring_policy()
    timings = build_incident_rule_timings(policy)

    assert {timing.rule_code for timing in timings} == {
        "DISABLED_ZONE_UNAUTHORIZED",
        "EV_ZONE_UNAUTHORIZED",
        "EV_OVERSTAY",
        "BAD_PARKING",
        "OUT_OF_ZONE",
        "AISLE_BLOCK",
        "DOUBLE_PARKING",
    }
    by_rule = {timing.rule_code: timing for timing in timings}
    for rule_code in ("BAD_PARKING", "OUT_OF_ZONE", "AISLE_BLOCK"):
        assert by_rule[rule_code].confirm_duration_seconds == 0.5
        assert by_rule[rule_code].clear_duration_seconds == 0.5
    for rule_code in (
        "DISABLED_ZONE_UNAUTHORIZED",
        "EV_ZONE_UNAUTHORIZED",
        "EV_OVERSTAY",
        "DOUBLE_PARKING",
    ):
        assert by_rule[rule_code].confirm_duration_seconds == 0.0
        assert by_rule[rule_code].clear_duration_seconds == 0.0
    assert monitoring.incident_rule_timings == timings


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
    assert decoded["incident_bad_parking_confirm_seconds"] == 0.5
    assert decoded["incident_bad_parking_clear_seconds"] == 0.5
    assert list(decoded) == sorted(decoded)


def test_asset_snapshot_records_versions_fingerprints_and_full_hashes() -> None:
    paths = default_paths()
    zones = ZoneRegistry.from_file(paths.zones)
    egress_aisles = EgressAisleRegistry.from_file(
        paths.egress_aisles,
        zones=zones,
    )

    decoded = json.loads(
        _asset_snapshot_json(
            paths=paths,
            zones=zones,
            egress_aisles=egress_aisles,
            remap_balance=ViewerPolicy().remap_balance,
        )
    )

    assert decoded["schemaVersion"] == 1
    assert decoded["zones"]["zoneDefinitionVersion"] == int(
        zones.zone_definition_version
    )
    assert decoded["egressAisles"]["egressAisleDefinitionVersion"] == int(
        egress_aisles.egress_aisle_definition_version
    )
    assert decoded["calibration"]["runtimeFingerprint"]["balance"] == 0.5
    for asset in ("model", "zones", "egressAisles", "calibration"):
        assert len(decoded[asset]["sha256"]) == 64


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


class _FakeZone:
    """`compute_mask_ratios_from_zones`가 요구하는 `.polygon` 속성만 흉내내는 stub."""

    def __init__(self, polygon) -> None:
        self.polygon = polygon


class _FakeZoneRegistry:
    """`ZoneRegistry.all()`만 흉내내는 최소 fake — 실제 zone 파일 없이 조립을
    검증한다."""

    def __init__(self, zones) -> None:
        self._zones = tuple(zones)

    def all(self):
        return self._zones


def test_full_frame_detector_is_wrapped_with_side_masking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """full-frame 경로의 YOLO delegate가 SideMaskingDetector로 조립되는지
    실제 YOLO 모델·영상 없이 fake raw detector로 확인한다(537). 계산된 마스크
    ratio가 실제로 SideMaskingDetector에 전달됐는지도 합성 zone + 알려진
    margin으로 기대값을 직접 계산해서 대조한다."""

    captured_kwargs: dict[str, object] = {}

    class _FakeRawDetector:
        def __init__(
            self, *, model_path, tracker_config, confidence, capture_detections
        ) -> None:
            captured_kwargs["model_path"] = model_path
            captured_kwargs["tracker_config"] = tracker_config
            captured_kwargs["confidence"] = confidence
            captured_kwargs["capture_detections"] = capture_detections

    monkeypatch.setattr(service, "UltralyticsVehicleTracker", _FakeRawDetector)

    zones = _FakeZoneRegistry(
        [_FakeZone([(0.25, 0.0), (0.70, 0.0), (0.70, 1.0), (0.25, 1.0)])]
    )
    margin_ratio = 0.05

    detector = service._build_detector(
        model_path=Path("fake-model.pt"),
        tracker_config="bytetrack.yaml",
        confidence=0.5,
        capture_detections=True,
        zones=zones,
        mask_margin_ratio=margin_ratio,
    )

    assert isinstance(detector, SideMaskingDetector)
    assert isinstance(detector._inner, _FakeRawDetector)
    assert captured_kwargs == {
        "model_path": "fake-model.pt",
        "tracker_config": "bytetrack.yaml",
        "confidence": 0.5,
        "capture_detections": True,
    }
    # min_x=0.25, max_x=0.70 -> (0.25-0.05, 0.70+0.05)
    assert detector._left_mask_end_ratio == pytest.approx(0.20)
    assert detector._right_mask_start_ratio == pytest.approx(0.75)

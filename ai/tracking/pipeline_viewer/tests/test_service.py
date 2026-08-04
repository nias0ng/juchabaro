"""Viewer 입력 계약과 기본 경로 테스트."""

import json

import pytest

from pipeline_viewer.service import (
    EPOCH,
    ViewerInputError,
    ViewerPolicy,
    build_allow_example,
    default_idempotency_key,
    default_paths,
    parse_entry_event,
)


def test_default_model_path_uses_jetson_model_directory() -> None:
    assert default_paths().model.as_posix().endswith(
        "hw/jetson/model/yolov8s.pt"
    )


def test_bad_parking_overlap_default_is_forwarded_to_monitoring_policy() -> None:
    viewer_policy = ViewerPolicy()

    assert viewer_policy.bad_parking_min_primary_overlap_ratio == 0.75
    assert (
        viewer_policy.to_monitoring_policy().bad_parking_min_primary_overlap_ratio
        == 0.75
    )


def test_yolo_confidence_default_is_low_for_viewer_diagnostics() -> None:
    assert ViewerPolicy().confidence == 0.01


def test_allow_example_matches_current_entry_event_wire() -> None:
    raw = build_allow_example()
    payload = parse_entry_event(raw)

    assert payload.access_decision == "ALLOW"
    assert payload.entry_time == EPOCH
    assert payload.session_id == 1
    assert payload.registered is True
    assert payload.recognized_plate_number == "12가3456"
    assert default_idempotency_key(raw).endswith("-r0")


def test_entry_event_time_must_match_video_zero() -> None:
    raw = json.loads(build_allow_example())
    raw["entryTime"] = "2026-08-03T00:00:00+00:00"

    with pytest.raises(ViewerInputError, match="영상 첫 프레임"):
        parse_entry_event(json.dumps(raw))

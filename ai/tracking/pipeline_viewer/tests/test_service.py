"""Viewer 입력 계약과 기본 경로 테스트."""

import json

import pytest

from pipeline_viewer.service import (
    EPOCH,
    ViewerInputError,
    build_allow_example,
    default_idempotency_key,
    default_paths,
    parse_entry_event,
)


def test_default_model_path_uses_jetson_model_directory() -> None:
    assert default_paths().model.as_posix().endswith(
        "hw/jetson/model/yolo26n.pt"
    )


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

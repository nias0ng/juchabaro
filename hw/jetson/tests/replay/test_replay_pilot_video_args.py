"""replay_pilot_video CLI 인자 파싱·검증 테스트(465/T-17).

실제 영상·모델 없이도 인자 계약을 확인한다 — cv2/ultralytics를 부르지
않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.replay_pilot_video import ReplayArgumentError, build_parser, validate_args, verify_zone_calibration
from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE
from src.camera.frame_source import calibration_fingerprint


def _parse(
    *extra_args: str,
    calibration: str | None = "ai/tracking/camera_calibration.json",
    zones_file: str = "ai/tracking/zones_pilot.json",
):
    args_list = [
        "--video", "docs/video/video1.mp4",
        "--zones-file", zones_file,
        "--model-path", "ai/training/yolo26n.pt",
        "--out-events", "out/events.jsonl",
        "--out-zone-visits", "out/zone_visits.jsonl",
        "--zone-entry-confirm-seconds", "3.0",
        "--zone-exit-confirm-seconds", "3.0",
        *(["--calibration", calibration] if calibration is not None else []),
        *extra_args,
    ]
    return build_parser().parse_args(args_list)


def _write_zones_file(path: Path, *, calibration: dict | None) -> None:
    """검증 대상 필드(calibration)만 채운 최소 zones 파일을 만든다."""

    payload: dict = {"zones": []}
    if calibration is not None:
        payload["calibration"] = calibration
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_defaults_match_documented_baseline_values():
    args = _parse()

    assert args.tracker_config == "bytetrack.yaml"
    assert args.confidence == 0.5
    assert args.min_overlap_ratio == 0.40
    assert args.movement_epsilon == 0.01
    assert args.remap_balance == 0.5


def test_missing_calibration_is_rejected(tmp_path):
    args = _parse(calibration=None)

    with pytest.raises(ReplayArgumentError, match="calibration"):
        validate_args(args)


def test_nonexistent_calibration_file_is_rejected(tmp_path):
    missing = tmp_path / "missing.json"
    args = _parse(calibration=str(missing))

    with pytest.raises(ReplayArgumentError, match="calibration"):
        validate_args(args)


def test_remap_balance_out_of_range_is_rejected():
    args = _parse("--remap-balance", "1.5")

    with pytest.raises(ReplayArgumentError, match="remap-balance"):
        validate_args(args)


def test_valid_args_pass_validation(tmp_path):
    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(b"fake-calibration-bytes")
    zones_file = tmp_path / "zones.json"
    _write_zones_file(
        zones_file, calibration=calibration_fingerprint(calibration, DEFAULT_REMAP_BALANCE)
    )
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    validate_args(args)  # 예외가 나지 않아야 한다


def test_missing_confirm_seconds_flags_fail_parsing():
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--video", "docs/video/video1.mp4", "--zones-file", "ai/tracking/zones_pilot.json"])


def test_zone_calibration_matching_fingerprint_is_accepted(tmp_path):
    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(b"fake-calibration-bytes")
    zones_file = tmp_path / "zones.json"
    _write_zones_file(
        zones_file, calibration=calibration_fingerprint(calibration, DEFAULT_REMAP_BALANCE)
    )
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    verify_zone_calibration(args)  # 예외가 나지 않아야 한다


def test_zone_calibration_mismatched_fingerprint_is_rejected(tmp_path):
    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(b"fake-calibration-bytes")
    zones_file = tmp_path / "zones.json"
    _write_zones_file(
        zones_file,
        calibration={"remap": True, "calibrationSha256": "0" * 16, "balance": 0.5},
    )
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    with pytest.raises(ReplayArgumentError, match="좌표계"):
        verify_zone_calibration(args)


def test_zone_calibration_missing_key_defaults_to_no_remap_and_is_rejected_when_calibration_given(tmp_path):
    """zones 파일에 calibration 키가 없으면 {"remap": False}로 간주한다.

    `--calibration`이 주어졌다면(이 리플레이는 항상 필수) 기대 지문은
    remap=True이므로, 지문이 없는 zones 파일은 항상 불일치로 걸린다.
    """

    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(b"fake-calibration-bytes")
    zones_file = tmp_path / "zones.json"
    _write_zones_file(zones_file, calibration=None)
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    with pytest.raises(ReplayArgumentError, match="좌표계"):
        verify_zone_calibration(args)

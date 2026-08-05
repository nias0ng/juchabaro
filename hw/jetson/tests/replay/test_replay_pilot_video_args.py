"""replay_pilot_video CLI 인자 파싱·검증 테스트(465/T-17).

실제 영상·모델 없이도 인자 계약을 확인한다 — cv2/ultralytics를 부르지
않는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.replay_pilot_video import (
    ReplayArgumentError,
    build_parser,
    build_policy,
    validate_args,
    verify_zone_calibration,
)
from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE
from src.camera.frame_source import calibration_fingerprint

# 464의 §4.7 정책값 전부를 CLI가 명시하게 되면서 필수 플래그가 늘었다.
# 값을 숨기지 않는 것이 이 CLI의 계약이라(모듈 docstring 참고) 여기서
# 한 곳에 모아 둔다.
REQUIRED_THRESHOLD_ARGS = [
    "--zone-entry-confirm-seconds", "3.0",
    "--zone-exit-confirm-seconds", "3.0",
    "--parking-move-confirm-seconds", "0.5",
    "--absence-confirmation-seconds", "5.0",
    "--trusted-sample-max-gap-seconds", "1.0",
    "--reidentification-max-gap-seconds", "4.0",
    "--reidentification-min-score", "0.42",
    "--reidentification-ambiguity-margin", "0.08",
    "--assignment-min-overlap-ratio", "0.5",
    "--assignment-ambiguous-margin", "0.05",
    "--bad-parking-min-primary-overlap-ratio", "0.75",
    "--blocking-relation-confirm-seconds", "3.0",
    "--blocking-relation-clear-seconds", "3.0",
]


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
        *REQUIRED_THRESHOLD_ARGS,
        *(["--calibration", calibration] if calibration is not None else []),
        *extra_args,
    ]
    return build_parser().parse_args(args_list)


def _write_zones_file(path: Path, *, calibration_reference: str) -> None:
    """새 구역 정의 snapshot 포맷(464)의 최소 파일을 만든다.

    `ZoneRegistry`가 최상위 키를 정확히 세 개로 제한하므로 옛
    `"calibration"` 지문 dict는 더 이상 넣을 수 없다.
    """

    payload = {
        "zoneDefinitionVersion": 1,
        "calibrationReference": calibration_reference,
        "zones": [
            {
                "zoneId": 1,
                "zoneType": "DISABLED",
                "polygon": [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3], [0.1, 0.3]],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _expected_reference(calibration: Path) -> str:
    return calibration_fingerprint(calibration, DEFAULT_REMAP_BALANCE)["calibrationSha256"]


def test_defaults_match_documented_baseline_values():
    args = _parse()

    assert args.tracker_config == "bytetrack.yaml"
    assert args.confidence == 0.5
    assert args.min_overlap_ratio == 0.40
    assert args.movement_epsilon == 0.01
    assert args.remap_balance == 0.5
    assert args.crop_left_px == 0
    assert args.crop_right_px == 0


def test_defaults_reuse_existing_codebase_values_only():
    """기본값이 있는 정책 플래그는 코드·설정에 이미 있던 값만 재사용한다."""

    args = _parse()

    # EntryMatchCoordinator.__init__의 기존 기본값
    assert args.entry_zone_min_overlap_ratio == 0.40
    # InMemoryIncidentReducer.__init__의 기존 기본값
    assert args.incident_confirm_seconds == 0.0
    assert args.incident_clear_seconds == 0.0
    # .env.example이 '요구사항 값'이라고 명시한 값
    assert args.parking_confirm_seconds == 600.0


def test_build_policy_passes_every_cli_value_through_unchanged():
    """CLI가 MonitoringPolicy의 모든 값을 채운다(숨은 기본값 없음)."""

    args = _parse("--min-overlap-ratio", "0.6")
    policy = build_policy(args)

    assert policy.zone_entry_confirm_seconds == 3.0
    assert policy.zone_exit_confirm_seconds == 3.0
    assert policy.parking_move_confirm_seconds == 0.5
    assert policy.absence_confirmation_seconds == 5.0
    assert policy.trusted_sample_max_gap_seconds == 1.0
    assert policy.reidentification_max_gap_seconds == 4.0
    assert policy.reidentification_min_score == 0.42
    assert policy.reidentification_ambiguity_margin == 0.08
    assert policy.assignment_min_overlap_ratio == 0.5
    assert policy.assignment_ambiguous_margin == 0.05
    assert policy.bad_parking_min_primary_overlap_ratio == 0.75
    assert policy.zone_presence_min_overlap_ratio == 0.6
    assert policy.entry_zone_min_overlap_ratio == 0.40
    assert policy.parking_confirm_seconds == 600.0
    assert policy.incident_confirm_seconds == 0.0
    assert policy.incident_clear_seconds == 0.0
    assert policy.blocking_relation_confirm_seconds == 3.0
    assert policy.blocking_relation_clear_seconds == 3.0


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
    _write_zones_file(zones_file, calibration_reference=_expected_reference(calibration))
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    validate_args(args)  # 예외가 나지 않아야 한다


@pytest.mark.parametrize(
    "flag",
    [
        "--zone-entry-confirm-seconds",
        "--zone-exit-confirm-seconds",
        "--parking-move-confirm-seconds",
        "--absence-confirmation-seconds",
        "--trusted-sample-max-gap-seconds",
        "--reidentification-max-gap-seconds",
        "--reidentification-min-score",
        "--reidentification-ambiguity-margin",
        "--assignment-min-overlap-ratio",
        "--assignment-ambiguous-margin",
        "--blocking-relation-confirm-seconds",
        "--blocking-relation-clear-seconds",
    ],
)
def test_each_threshold_flag_is_required(flag):
    """실측 대상 임계값은 하나라도 빠지면 파싱 단계에서 멈춘다."""

    index = REQUIRED_THRESHOLD_ARGS.index(flag)
    remaining = REQUIRED_THRESHOLD_ARGS[:index] + REQUIRED_THRESHOLD_ARGS[index + 2:]
    argv = [
        "--video", "docs/video/video1.mp4",
        "--zones-file", "zones.json",
        "--model-path", "model.pt",
        "--out-events", "out/events.jsonl",
        "--out-zone-visits", "out/zone_visits.jsonl",
        *remaining,
    ]

    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_zone_calibration_matching_reference_is_accepted(tmp_path):
    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(b"fake-calibration-bytes")
    zones_file = tmp_path / "zones.json"
    _write_zones_file(zones_file, calibration_reference=_expected_reference(calibration))
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    verify_zone_calibration(args)  # 예외가 나지 않아야 한다


def test_zone_calibration_mismatched_reference_is_rejected(tmp_path):
    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(b"fake-calibration-bytes")
    zones_file = tmp_path / "zones.json"
    _write_zones_file(zones_file, calibration_reference="0" * 16)
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    with pytest.raises(ReplayArgumentError, match="좌표계"):
        verify_zone_calibration(args)


def test_legacy_zones_file_format_is_rejected_with_a_readable_error(tmp_path):
    """464 이전 포맷(zoneNumber·calibration 지문 dict)은 조용히 통과하지 않는다."""

    calibration = tmp_path / "calibration.json"
    calibration.write_bytes(b"fake-calibration-bytes")
    zones_file = tmp_path / "zones.json"
    zones_file.write_text(
        json.dumps(
            {
                "source": "local",
                "cameraCode": "PILOT-VIDEO",
                "calibration": {"remap": True, "calibrationSha256": "a" * 16, "balance": 0.5},
                "zones": [
                    {
                        "zoneId": 1,
                        "zoneNumber": "GEN-L1",
                        "zoneType": "GENERAL",
                        "allowedMinutes": None,
                        "polygon": [[0.1, 0.1], [0.3, 0.1], [0.3, 0.3]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    args = _parse(calibration=str(calibration), zones_file=str(zones_file))

    with pytest.raises(ReplayArgumentError, match="구역 정의 파일"):
        verify_zone_calibration(args)

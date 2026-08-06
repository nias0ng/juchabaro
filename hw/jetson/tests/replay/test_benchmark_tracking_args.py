"""벤치마크 스크립트의 CLI 계약 테스트.

측정 결과의 신뢰도가 인자 기본값에 걸려 있다 — warmup을 세지 않거나 프레임
소스를 두 개 동시에 받으면 숫자가 조용히 왜곡된다.
"""

import pytest

from scripts.benchmark_tracking import build_parser


def test_video_source_defaults_start_at_beginning() -> None:
    args = build_parser().parse_args(
        ["--model", "best.pt", "--video", "pilot.mp4"]
    )

    assert args.video == "pilot.mp4"
    assert args.start_seconds == 0.0
    assert args.frames == 60
    assert args.warmup == 10
    assert args.conf == 0.5
    assert args.tracker == "bytetrack.yaml"
    assert args.half is False
    assert args.imgsz is None


def test_start_seconds_selects_a_segment_with_vehicles() -> None:
    args = build_parser().parse_args(
        ["--model", "best.pt", "--video", "pilot.mp4", "--start-seconds", "30"]
    )

    assert args.start_seconds == 30.0


def test_video_and_camera_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "--model",
                "best.pt",
                "--video",
                "pilot.mp4",
                "--camera-index",
                "0",
            ]
        )


def test_a_frame_source_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--model", "best.pt"])


def test_model_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--video", "pilot.mp4"])

#!/usr/bin/env python3
"""녹화된 파일럿 영상을 판정 파이프라인에 흘려넣어 오버레이 영상과 이벤트 로그를 만든다.

판정 로직은 건드리지 않는다. 프레임 공급과 결과 발행만 교체해서, 실제 런타임과
같은 ViolationMonitor가 같은 파라미터로 내리는 판정을 관찰한다.

리포 루트에서 실행한다:
    python ai/tracking/replay_pilot_video.py --video docs/video/video1.mp4 \
        --zones-file ai/tracking/zones_pilot.json \
        --calibration ai/tracking/camera_calibration.json \
        --model-path ai/training/runs/.../weights/best.pt \
        --min-dwell-seconds 20 \
        --out-video out/video1_overlay.mp4 --out-events out/video1_events.jsonl
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from jetson_vehicle_tracking_baseline import (
    BaselineError,
    RemapFrameSource,
    UltralyticsVehicleTracker,
    ViolationMonitor,
    ZoneRegistry,
    build_parser as build_baseline_parser,
    verify_zone_calibration,
)
from replay.jsonl_publisher import JsonlResultPublisher
from replay.overlay import OverlayWriter
from replay.video_source import EPOCH, EndOfVideo, VideoFileFrameSource

LOGGER = logging.getLogger("replay_pilot_video")

# 판정 파라미터의 기본값은 baseline이 단일 출처다. 여기서 따로 정의하면 두 값이
# 갈라져 검증 결과가 실제 런타임 동작과 달라진다.
_INHERITED_DEFAULTS = (
    "model_path",
    "tracker_config",
    "confidence",
    "min_overlap_ratio",
    "spot_intrusion_ratio",
    "min_dwell_seconds",
    "movement_epsilon",
    "track_grace_seconds",
    "entry_match_window_seconds",
    "entry_zone_min_overlap_ratio",
    "remap_balance",
)


def build_parser() -> argparse.ArgumentParser:
    # 베이스라인의 판정 파라미터 기본값만 빌려온다. `modes`가 required 배타
    # 그룹이라 모드 플래그를 하나 줘야 파싱이 통과하는데, 여기서는 파싱만 하고
    # 실행하지 않으므로 어느 것이든 무방하다(409에서 `--self-test`가 사라져
    # `--run`으로 바꿨다).
    baseline_defaults = build_baseline_parser().parse_args(["--run"])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--zones-file", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, default=None)
    parser.add_argument("--out-video", type=Path, required=True)
    parser.add_argument("--out-events", type=Path, required=True)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--end-seconds", type=float, default=None)
    parser.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )
    for name in _INHERITED_DEFAULTS:
        parser.add_argument(f"--{name.replace('_', '-')}", default=getattr(baseline_defaults, name))
    return parser


def coerce_numeric_args(args: argparse.Namespace) -> None:
    """baseline에서 상속한 기본값은 이미 올바른 타입이지만, CLI로 준 값은 문자열이다."""

    for name in _INHERITED_DEFAULTS:
        if name in ("model_path", "tracker_config"):
            continue
        setattr(args, name, float(getattr(args, name)))


def validate_args(args: argparse.Namespace) -> None:
    """리플레이 실행 전 필수 옵션과 수치 범위를 검증한다.

    jetson_vehicle_tracking_baseline.validate_args가 `--run`에 요구하는 것과 같은
    검증을 여기서도 그대로 요구한다 — 이 스크립트가 그 검증을 우회하면, 캘리브레이션
    없는 zones 파일과 캘리브레이션 없는 리플레이가 지문상 서로 일치해버려서(둘 다
    remap=false), 왜곡이 남은 원본 프레임으로 오버레이와 "검증됨" 판정을 만들어낼 수
    있다 — 모델은 remap 보정된 프레임으로 학습됐는데도.
    """

    if not (0.0 <= args.remap_balance <= 1.0):
        # OpenCV는 범위를 벗어난 balance도 조용히 받아들여 엉뚱한 new_K를 만든다.
        raise BaselineError("remap-balance는 0~1 범위여야 합니다.")
    if args.calibration is None:
        # 모델은 remap 보정된 프레임으로 학습됐다. 보정 없이 리플레이하면 조용히
        # 정확도만 떨어져 원인 파악이 어려우므로 실행 자체를 막는다.
        raise BaselineError(
            "리플레이에는 --calibration이 필요합니다(모델이 remap 보정된 프레임으로 "
            "학습됨). ai/tracking/camera_calibration.json 경로를 지정하세요."
        )
    if not args.calibration.is_file():
        raise BaselineError(f"calibration 파일을 찾을 수 없습니다: {args.calibration}")


def warn_if_dwell_exceeds_video(min_dwell_seconds: float, video_seconds: float) -> None:
    """이 설정으로 위반이 발생할 수 없으면 알린다.

    min_dwell_seconds 기본값은 600초(10분)인데 파일럿 영상은 최장 490초다.
    침묵하면 "위반 0건"을 정상 동작으로 오독한다.
    """

    if min_dwell_seconds >= video_seconds:
        LOGGER.warning(
            "min_dwell_seconds(%.1fs)가 영상 길이(%.1fs) 이상입니다 — 이 설정으로는 위반이 "
            "발생할 수 없습니다. 검증에는 20~30초를 권합니다.",
            min_dwell_seconds,
            video_seconds,
        )


def run(args: argparse.Namespace) -> int:
    """영상 → 트래커 → 판정 → 오버레이·JSONL 루프를 끝까지 돌린다."""

    zones = ZoneRegistry.from_file(args.zones_file)
    verify_zone_calibration(args)

    inner = VideoFileFrameSource(
        path=args.video, t0=EPOCH, start_seconds=args.start_seconds, end_seconds=args.end_seconds
    )
    inner.open()
    fps, frame_size = inner.fps, inner.frame_size
    effective_seconds = args.end_seconds if args.end_seconds is not None else inner.duration_seconds
    warn_if_dwell_exceeds_video(args.min_dwell_seconds, effective_seconds - args.start_seconds)

    source = (
        RemapFrameSource(
            inner=inner, calibration_path=str(args.calibration), balance=args.remap_balance
        )
        if args.calibration is not None
        else inner
    )
    tracker = UltralyticsVehicleTracker(
        model_path=args.model_path, tracker_config=args.tracker_config, confidence=args.confidence
    )
    monitor = ViolationMonitor(
        zones,
        min_overlap_ratio=args.min_overlap_ratio,
        min_dwell_seconds=args.min_dwell_seconds,
        movement_epsilon=args.movement_epsilon,
        track_grace_seconds=args.track_grace_seconds,
        spot_intrusion_ratio=args.spot_intrusion_ratio,
        entry_match_window_seconds=args.entry_match_window_seconds,
        entry_zone_min_overlap_ratio=args.entry_zone_min_overlap_ratio,
    )
    overlay = OverlayWriter(path=args.out_video, fps=fps, frame_size=frame_size, zones=zones)
    events_out = JsonlResultPublisher(path=args.out_events)

    total_events = 0
    frames = 0
    # RemapFrameSource.open()은 inner.open()을 다시 부르지만 두 번째는 무시된다.
    source.open()
    overlay.open()
    events_out.open()
    try:
        tracker.open()
        try:
            while True:
                try:
                    frame = source.capture()
                except EndOfVideo:
                    break
                detections = tracker.track(frame)
                new_events = monitor.update(detections)
                snapshot = monitor.track_snapshot(frame.captured_at)
                for event in new_events:
                    events_out.publish(event)
                total_events += len(new_events)
                overlay.write(frame, detections, snapshot, new_events)
                frames += 1
                if frames % 300 == 0:
                    LOGGER.info("%d 프레임 처리, 이벤트 %d건", frames, total_events)
        finally:
            tracker.close()
    finally:
        # 중단해도 여기까지 쓴 프레임은 볼 수 있어야 한다.
        events_out.close()
        overlay.close()
        source.close()

    LOGGER.info(
        "완료: %d 프레임, 이벤트 %d건 → %s / %s", frames, total_events, args.out_video, args.out_events
    )
    if total_events == 0:
        LOGGER.warning(
            "위반 이벤트가 0건입니다. min_dwell_seconds(%.1fs), min_overlap_ratio(%.2f), "
            "zones 폴리곤이 영상과 맞는지 오버레이를 확인하세요.",
            args.min_dwell_seconds,
            args.min_overlap_ratio,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    coerce_numeric_args(args)
    validate_args(args)
    return run(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaselineError as exc:
        LOGGER.error("%s", exc)
        sys.exit(1)

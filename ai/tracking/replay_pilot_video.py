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
    baseline_defaults = build_baseline_parser().parse_args(["--self-test"])
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
    return run(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaselineError as exc:
        LOGGER.error("%s", exc)
        sys.exit(1)

#!/usr/bin/env python3
"""녹화된 파일럿 영상을 새 모듈 파이프라인(camera→tracking→parking→outbox)에
흘려보내 사건 전이 로그와 구역 방문 전이 로그를 만든다(465/T-17).

`ai/tracking/replay_pilot_video.py`(옛 baseline용)를 대체하지 않는다 — 그
스크립트와 `ai/tracking/jetson_vehicle_tracking_baseline.py`의 폐기는 T-23의
범위다. 이 스크립트는 실제 FastAPI 앱이 카메라 루프에서 쓰게 될 것과 같은
`src.*` 프로덕션 클래스들을 그대로 조립해, 파일럿 영상으로 §4.7의 임계값을
산출할 수 있는 리플레이 경로를 새로 연다.

**왜 사건 로그만으로는 부족한가.** `restricted_zone` 규칙은 `VehicleContext`가
없으면 항상 `confirmable=False`다(`src/parking/rules/restricted_zone.py`).
파일럿 영상 리플레이에는 백엔드 입차 이벤트가 없어 `context`가 항상 `None`이므로,
프로덕션 outbox(`--out-events`)는 이 리플레이에서 절대 채워지지 않는다. §4.7의
임계값 산출은 확정된 사건이 아니라 ZoneVisit의 ENTERING→INSIDE 오탐 횟수를
사람이 라벨링한 정답과 비교해 측정하므로, `--out-zone-visits`가 실제로 쓰는
산출물이다. `--out-events`는 향후 게이트 이벤트를 리플레이에 주입하게 될 때를
대비해 그대로 남겨 둔다.

레포 루트에서 `hw/jetson`으로 이동한 뒤 모듈로 실행한다(README의 `python -m
uvicorn src.main:app`과 같은 이유 — `src`/`scripts`를 패키지로 해석하려면
`hw/jetson`이 사실상의 루트여야 한다):

    cd hw/jetson
    python -m scripts.replay_pilot_video \\
        --video ../../docs/video/video1.mp4 \\
        --zones-file ../../ai/tracking/zones_pilot.json \\
        --calibration ../../ai/tracking/camera_calibration.json \\
        --model-path ../../ai/training/runs/.../weights/best.pt \\
        --zone-entry-confirm-seconds 3.0 --zone-exit-confirm-seconds 3.0 \\
        --out-events out/video1_events.jsonl \\
        --out-zone-visits out/video1_zone_visits.jsonl
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.application.monitoring_pipeline import MonitoringPipeline
from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE
from src.camera.frame_source import EndOfVideo, RemapFrameSource, VideoFileFrameSource
from src.communication.outbox import JsonlOutbox
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.pipeline import ParkingPipeline
from src.parking.zone_registry import ZoneRegistry
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.replay.zone_visit_publisher import ZoneVisitJsonlPublisher
from src.tracking.adapters.ultralytics_bytetrack import UltralyticsVehicleTracker
from src.tracking.pipeline import TrackingPipeline

LOGGER = logging.getLogger("replay_pilot_video")


class ReplayArgumentError(RuntimeError):
    """리플레이 인자 검증에 실패했다."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--zones-file", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, default=None)
    parser.add_argument("--camera-id", default="PILOT-VIDEO")
    parser.add_argument("--model-path", default="ai/training/yolo26n.pt")
    parser.add_argument("--out-events", type=Path, required=True, help="확정된 사건 전이 JSONL(프로덕션 outbox 포맷).")
    parser.add_argument(
        "--out-zone-visits", type=Path, required=True,
        help="ZoneVisit 상태 전이 JSONL — §4.7 임계값 산출은 이 파일을 쓴다.",
    )
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--end-seconds", type=float, default=None)
    parser.add_argument(
        "--zone-entry-confirm-seconds", type=float, required=True,
        help="구역 진입 확인시간(초). 기본값을 두지 않는다 — config/settings.py와 같은 이유(§4.7).",
    )
    parser.add_argument(
        "--zone-exit-confirm-seconds", type=float, required=True,
        help="구역 이탈 확인시간(초). 기본값을 두지 않는다 — config/settings.py와 같은 이유(§4.7).",
    )
    parser.add_argument("--min-overlap-ratio", type=float, default=0.40)
    parser.add_argument("--movement-epsilon", type=float, default=0.01)
    parser.add_argument("--tracker-config", default="bytetrack.yaml")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--remap-balance", type=float, default=DEFAULT_REMAP_BALANCE)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    """리플레이 실행 전 필수 옵션과 수치 범위를 검증한다.

    `ai/tracking/replay_pilot_video.py`의 같은 검증과 같은 이유다 — 보정 없는
    리플레이는 모델이 remap 보정된 프레임으로 학습됐다는 전제를 조용히
    깨뜨려 위반 판정 전체를 틀리게 만든다.
    """

    if not (0.0 <= args.remap_balance <= 1.0):
        raise ReplayArgumentError("remap-balance는 0~1 범위여야 합니다.")
    if args.calibration is None:
        raise ReplayArgumentError(
            "리플레이에는 --calibration이 필요합니다(모델이 remap 보정된 프레임으로 학습됨)."
        )
    if not args.calibration.is_file():
        raise ReplayArgumentError(f"calibration 파일을 찾을 수 없습니다: {args.calibration}")


def build_pipeline(args: argparse.Namespace) -> tuple[MonitoringPipeline, ZoneVisitJsonlPublisher]:
    """CLI 인자로 MonitoringPipeline과 ZoneVisit 발행기를 조립한다."""

    inner = VideoFileFrameSource(
        camera_id=args.camera_id, path=args.video, start_seconds=args.start_seconds, end_seconds=args.end_seconds
    )
    frame_source = RemapFrameSource(inner=inner, calibration_path=str(args.calibration), balance=args.remap_balance)

    detector = UltralyticsVehicleTracker(
        model_path=args.model_path, tracker_config=args.tracker_config, confidence=args.confidence
    )
    tracking_pipeline = TrackingPipeline(camera_id=args.camera_id, detector=detector)

    zones = ZoneRegistry.from_file(args.zones_file)
    parking_pipeline = ParkingPipeline(
        zones=zones,
        zone_visit_tracker=InMemoryZoneVisitTracker(
            entry_confirm_seconds=args.zone_entry_confirm_seconds,
            exit_confirm_seconds=args.zone_exit_confirm_seconds,
        ),
        incident_reducer=InMemoryIncidentReducer(),
        min_overlap_ratio=args.min_overlap_ratio,
    )

    pipeline = MonitoringPipeline(
        frame_source=frame_source,
        tracking_pipeline=tracking_pipeline,
        parking_pipeline=parking_pipeline,
        outbox=JsonlOutbox(args.out_events),
    )
    zone_visit_publisher = ZoneVisitJsonlPublisher(path=args.out_zone_visits)
    return pipeline, zone_visit_publisher


def run(args: argparse.Namespace) -> int:
    """영상 → 추적 → 판정 루프를 끝까지 돌리고 두 JSONL 로그를 채운다."""

    pipeline, zone_visit_publisher = build_pipeline(args)

    frames = 0
    total_zone_visits = 0
    pipeline.open()
    zone_visit_publisher.open()
    try:
        while True:
            try:
                result = pipeline.process_next_frame()
            except EndOfVideo:
                break
            for visit in result.zone_visit_updates:
                zone_visit_publisher.publish(visit)
            total_zone_visits += len(result.zone_visit_updates)
            frames += 1
            if frames % 300 == 0:
                LOGGER.info("%d 프레임 처리, 방문 전이 %d건", frames, total_zone_visits)
    finally:
        zone_visit_publisher.close()
        pipeline.close()

    LOGGER.info(
        "완료: %d 프레임, 방문 전이 %d건 → %s / %s", frames, total_zone_visits, args.out_events, args.out_zone_visits
    )
    if total_zone_visits == 0:
        LOGGER.warning(
            "구역 방문 전이가 0건입니다. zones-file 폴리곤이 영상과 맞는지, "
            "min-overlap-ratio(%.2f)가 너무 높지 않은지 확인하세요.",
            args.min_overlap_ratio,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    validate_args(args)
    return run(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ReplayArgumentError as exc:
        LOGGER.error("%s", exc)
        sys.exit(1)

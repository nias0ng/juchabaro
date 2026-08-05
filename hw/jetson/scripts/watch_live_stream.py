#!/usr/bin/env python3
"""파일럿 영상 또는 노트북 웹캠으로 라이브 오버레이+판정 로직을 로컬 창에 띄워 확인한다.

프로덕션 코드가 아니다 — 젯슨이나 `/live/stream` HTTP 엔드포인트(480, 아직
미구현) 없이 `LiveStreamLoop`(479)의 동작을 수동으로 검증하기 위한 개발용
스크립트다. `replay_pilot_video.py`와 같은 프로덕션 조립기
(`build_monitoring_pipeline`)를 그대로 쓰되, `--video`(`VideoFileFrameSource`)
또는 `--camera-index`(`OpenCvWebcamFrameSource`) 둘 중 하나를 프레임 소스로
주입한다. `OpenCvWebcamFrameSource`는 젯슨 전용이 아닌 일반 cv2.VideoCapture
래퍼라 노트북 내장/USB 웹캠으로도 그대로 동작한다.

레포 루트에서 `hw/jetson`으로 이동한 뒤 모듈로 실행한다:

    cd hw/jetson

    # 파일럿 영상으로
    python -m scripts.watch_live_stream \\
        --video ../../docs/video/video1.mp4 \\
        --zones-file config/zone_definition.pilot.json \\
        --calibration ../../ai/tracking/camera_calibration.json \\
        --model-path ../../ai/training/runs/detect/runs/train/vehicle_detector-yolov8s-20260729-153946/weights/best.pt

    # 노트북 웹캠으로 (재연결 로직까지 보려면 실행 중 웹캠을 물리적으로 뽑았다 꽂아본다)
    python -m scripts.watch_live_stream \\
        --camera-index 0 \\
        --zones-file config/zone_definition.pilot.json \\
        --calibration ../../ai/tracking/camera_calibration.json \\
        --model-path ../../ai/training/runs/detect/runs/train/vehicle_detector-yolov8s-20260729-153946/weights/best.pt

주의: 기존 calibration/zones 파일은 젯슨 카메라·주차장 배치 기준으로 만들어져
있다. 노트북 웹캠은 렌즈·화각이 다르므로 왜곡 보정은 정확하지 않고, 구역
폴리곤도 화면 속 실제 사물과 맞아떨어지지 않는다 — 그래도 코드 경로(추적·
판정·오버레이·재연결)가 정상 동작하는지 눈으로 보는 데는 문제 없다. 실물
차량이 없다면 차량 bbox는 거의 안 잡히는 게 정상이다(YOLO가 주차 차량 전용
모델이라서다) — 재연결/스로틀/오버레이 배선 자체를 확인하는 용도로 쓴다.

창이 뜨면 아무 키나 누르면(q 또는 ESC 권장) 종료한다. 영상이 끝나면 루프가
"VIDEO ENDED" 안내 프레임에서 멈춘 채 창은 계속 떠 있으니 그때 종료하면 된다.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

# 콘솔 코드페이지(cp949 등)가 이 파일의 em dash 같은 특수문자를 인코딩하지
# 못해 크래시하는 것을 막는다 - 인코딩 자체는 그대로 두고 못 그리는 문자만
# 대체한다(한글 표시는 그대로 유지).
sys.stdout.reconfigure(errors="replace")
sys.stderr.reconfigure(errors="replace")

from src.application.monitoring_factory import (
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.camera.calibration_utils import DEFAULT_REMAP_BALANCE
from src.camera.frame_source import (
    CropFrameSource,
    FrameSource,
    OpenCvWebcamFrameSource,
    RemapFrameSource,
    VideoFileFrameSource,
)
from src.live.live_overlay_renderer import render_overlay_jpeg
from src.live.live_stream_loop import LiveStreamLoop
from src.parking.zone_registry import ZoneRegistry
from src.replay.publication_preparer import JsonlPublicationPreparer
from src.storage.database import connect_database, open_database
from src.tracking.adapters.ultralytics_bytetrack import UltralyticsVehicleTracker

LOGGER = logging.getLogger("watch_live_stream")


class _TransitionLogger:
    """ZoneVisit/ParkingEpisode의 실제 상태 전이만 골라 로그로 남긴다.

    `zone_visit_updates`/`parking_episode_updates`는 같은 상태가 이어지는 동안
    프레임마다 거의 같은 레코드를 반환한다(`scripts/replay_pilot_video.py`
    docstring 참고) - visit_id/episode_id별 마지막으로 로그를 남긴 상태를
    기억해 두고, 그 상태가 바뀌었을 때만 다시 로그를 남긴다.
    """

    def __init__(self) -> None:
        self._last_zone_visit_state: dict = {}
        self._last_episode_state: dict = {}

    def log(self, result) -> None:
        for visit in result.parking_result.zone_visit_updates:
            if self._last_zone_visit_state.get(visit.visit_id) == visit.state:
                continue
            self._last_zone_visit_state[visit.visit_id] = visit.state
            LOGGER.info(
                "ZoneVisit vehicle=%s zone=%s -> %s",
                str(visit.physical_vehicle_id)[:8], visit.zone_id, visit.state.value,
            )
        for episode in result.parking_result.parking_episode_updates:
            if self._last_episode_state.get(episode.episode_id) == episode.state:
                continue
            self._last_episode_state[episode.episode_id] = episode.state
            zone_id = episode.assignment.zone_id if episode.assignment is not None else None
            LOGGER.info(
                "ParkingEpisode vehicle=%s zone=%s -> %s",
                str(episode.physical_vehicle_id)[:8], zone_id, episode.state.value,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--video", type=Path, help="파일럿 영상 경로 (VideoFileFrameSource)")
    source_group.add_argument(
        "--camera-index", type=int, help="웹캠 장치 인덱스, 보통 0 (OpenCvWebcamFrameSource)"
    )
    parser.add_argument("--camera-width", type=int, default=0, help="웹캠 요청 해상도 폭. 0이면 장치 기본값")
    parser.add_argument("--camera-height", type=int, default=0, help="웹캠 요청 해상도 높이. 0이면 장치 기본값")
    parser.add_argument("--zones-file", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--camera-id", default="WATCH-LIVE")
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--end-seconds", type=float, default=None)

    # 판정 임계값 — replay_pilot_video.py 문서의 예시값을 그대로 기본값으로 쓴다.
    # (이 스크립트는 임계값 측정 도구가 아니라 눈으로 보는 용도라 기본값을 둔다.)
    parser.add_argument("--zone-entry-confirm-seconds", type=float, default=3.0)
    parser.add_argument("--zone-exit-confirm-seconds", type=float, default=3.0)
    parser.add_argument("--parking-move-confirm-seconds", type=float, default=0.5)
    parser.add_argument("--absence-confirmation-seconds", type=float, default=5.0)
    parser.add_argument("--trusted-sample-max-gap-seconds", type=float, default=1.0)
    parser.add_argument("--reidentification-max-gap-seconds", type=float, default=4.0)
    parser.add_argument("--reidentification-min-score", type=float, default=0.42)
    parser.add_argument("--reidentification-ambiguity-margin", type=float, default=0.08)
    parser.add_argument("--assignment-min-overlap-ratio", type=float, default=0.5)
    parser.add_argument("--assignment-ambiguous-margin", type=float, default=0.05)
    parser.add_argument("--bad-parking-min-primary-overlap-ratio", type=float, default=0.75)
    parser.add_argument("--bad-parking-min-secondary-overlap-ratio", type=float, default=0.25)
    parser.add_argument("--out-of-zone-min-spot-overlap-ratio", type=float, default=0.50)
    parser.add_argument("--blocking-relation-confirm-seconds", type=float, default=3.0)
    parser.add_argument("--blocking-relation-clear-seconds", type=float, default=3.0)
    parser.add_argument(
        "--parking-confirm-seconds", type=float, default=5.0,
        help="정차 후 주차로 확정하기까지 걸리는 시간(초). 시연용 기본값 5초 "
        "(실제 요구사항 값 600초와 다름 - 눈으로 빠르게 확인하려는 목적).",
    )
    parser.add_argument("--entry-zone-min-overlap-ratio", type=float, default=0.40)
    parser.add_argument("--incident-confirm-seconds", type=float, default=0.0)
    parser.add_argument("--incident-clear-seconds", type=float, default=0.0)
    parser.add_argument("--min-overlap-ratio", type=float, default=0.40)

    parser.add_argument("--motion-window-seconds", type=float, default=0.75)
    parser.add_argument("--motion-min-observation-span-seconds", type=float, default=0.20)
    parser.add_argument("--motion-max-sample-gap-seconds", type=float, default=0.50)
    parser.add_argument("--motion-stationary-threshold", type=float, default=0.03)
    parser.add_argument("--motion-moving-threshold", type=float, default=0.10)
    parser.add_argument("--motion-min-samples", type=int, default=3)
    parser.add_argument("--motion-min-trend-consistency", type=float, default=0.60)
    parser.add_argument("--tracker-config", default="bytetrack.yaml")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--remap-balance", type=float, default=DEFAULT_REMAP_BALANCE)
    parser.add_argument(
        "--crop-left-px", type=int, default=0,
        help="remap 이후 프레임에서 왼쪽 여백을 잘라낼 픽셀 수. 기본 0(자르지 않음).",
    )
    parser.add_argument(
        "--crop-right-px", type=int, default=0,
        help="remap 이후 프레임에서 오른쪽 여백을 잘라낼 픽셀 수. 기본 0(자르지 않음).",
    )
    parser.add_argument("--target-fps", type=float, default=15.0)
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument("--window-name", default="live_stream_loop (q/ESC to quit)")
    parser.add_argument(
        "--display-width", type=int, default=1280,
        help="미리보기 창 크기(픽셀). 실제 캡처/판정 해상도와는 무관 — 화면에 맞게 보기용으로만 축소한다.",
    )
    parser.add_argument("--display-height", type=int, default=720)
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def build_policy(args: argparse.Namespace) -> MonitoringPolicy:
    return MonitoringPolicy(
        zone_entry_confirm_seconds=args.zone_entry_confirm_seconds,
        zone_exit_confirm_seconds=args.zone_exit_confirm_seconds,
        entry_zone_min_overlap_ratio=args.entry_zone_min_overlap_ratio,
        parking_confirm_seconds=args.parking_confirm_seconds,
        parking_move_confirm_seconds=args.parking_move_confirm_seconds,
        absence_confirmation_seconds=args.absence_confirmation_seconds,
        trusted_sample_max_gap_seconds=args.trusted_sample_max_gap_seconds,
        reidentification_max_gap_seconds=args.reidentification_max_gap_seconds,
        reidentification_min_score=args.reidentification_min_score,
        reidentification_ambiguity_margin=args.reidentification_ambiguity_margin,
        incident_confirm_seconds=args.incident_confirm_seconds,
        incident_clear_seconds=args.incident_clear_seconds,
        zone_presence_min_overlap_ratio=args.min_overlap_ratio,
        assignment_min_overlap_ratio=args.assignment_min_overlap_ratio,
        assignment_ambiguous_margin=args.assignment_ambiguous_margin,
        bad_parking_min_primary_overlap_ratio=(
            args.bad_parking_min_primary_overlap_ratio
        ),
        bad_parking_min_secondary_overlap_ratio=(
            args.bad_parking_min_secondary_overlap_ratio
        ),
        out_of_zone_min_spot_overlap_ratio=args.out_of_zone_min_spot_overlap_ratio,
        blocking_relation_confirm_seconds=args.blocking_relation_confirm_seconds,
        blocking_relation_clear_seconds=args.blocking_relation_clear_seconds,
        motion_window_seconds=args.motion_window_seconds,
        motion_min_observation_span_seconds=(
            args.motion_min_observation_span_seconds
        ),
        motion_max_sample_gap_seconds=args.motion_max_sample_gap_seconds,
        motion_stationary_threshold=args.motion_stationary_threshold,
        motion_moving_threshold=args.motion_moving_threshold,
        motion_min_samples=args.motion_min_samples,
        motion_min_trend_consistency=args.motion_min_trend_consistency,
    )


def run(args: argparse.Namespace) -> int:
    zones = ZoneRegistry.from_file(args.zones_file)
    workspace = Path(tempfile.mkdtemp(prefix="watch-live-stream-"))
    try:
        database_path = workspace / "watch.db"
        open_database(database_path).close()

        inner: FrameSource
        if args.video is not None:
            inner = VideoFileFrameSource(
                camera_id=args.camera_id, path=args.video,
                start_seconds=args.start_seconds, end_seconds=args.end_seconds,
            )
        else:
            inner = OpenCvWebcamFrameSource(
                camera_id=args.camera_id, camera_index=args.camera_index,
                width=args.camera_width, height=args.camera_height,
            )
        frame_source = RemapFrameSource(
            inner=inner, calibration_path=str(args.calibration), balance=args.remap_balance
        )
        frame_source = CropFrameSource(
            inner=frame_source, crop_left_px=args.crop_left_px, crop_right_px=args.crop_right_px
        )
        detector = UltralyticsVehicleTracker(
            model_path=args.model_path, tracker_config=args.tracker_config, confidence=args.confidence
        )
        pipeline = build_monitoring_pipeline(
            zones=zones,
            policy=build_policy(args),
            dependencies=MonitoringDependencies(
                camera_id=args.camera_id,
                frame_source=frame_source,
                detector=detector,
                publication_preparer=JsonlPublicationPreparer(),
                connection_factory=lambda: connect_database(database_path),
            ),
        )

        transition_logger = _TransitionLogger()

        def render(frame, tracking_batch, result):
            transition_logger.log(result)
            return render_overlay_jpeg(frame, tracking_batch, result, zones=zones, jpeg_quality=args.jpeg_quality)

        loop = LiveStreamLoop(pipeline, render=render, target_fps=args.target_fps)
        loop.start()
        LOGGER.info("스트림 루프 시작. 창에서 q 또는 ESC를 누르면 종료합니다.")
        # WINDOW_NORMAL로 만들어야 창 크기를 조절할 수 있다 — 기본(WINDOW_AUTOSIZE)은
        # 원본 해상도(예: 2560x1440) 그대로 창을 만들어 노트북 화면보다 커질 수 있다.
        cv2.namedWindow(args.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(args.window_name, args.display_width, args.display_height)
        try:
            while True:
                jpeg_bytes = loop.latest_jpeg()
                if jpeg_bytes is not None:
                    frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is not None:
                        cv2.imshow(args.window_name, frame)
                key = cv2.waitKey(30) & 0xFF
                if key in (ord("q"), 27):  # 27 == ESC
                    break
                if loop.failure is not None:
                    LOGGER.error("스트림 루프가 예기치 않게 종료됐습니다: %s", loop.failure)
                    break
        finally:
            loop.stop()
            cv2.destroyAllWindows()
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(levelname)s %(message)s")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

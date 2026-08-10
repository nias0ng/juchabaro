#!/usr/bin/env python3
"""젯슨 프레임 처리 비용을 단계별로 쪼개 측정한다.

프로덕션 코드가 아니다 — "6.5fps의 원인이 모델인가 우리 로직인가"를 숫자로
가르기 위한 진단용 스크립트다.

측정하는 단계는 프로덕션 프레임 경로와 같은 순서다.

    decode      VideoFileFrameSource / OpenCvWebcamFrameSource
    remap       RemapFrameSource(fisheye 왜곡 보정)   --calibration 지정 시
    cvtColor    RGB→BGR (UltralyticsVehicleTracker가 매 프레임 하는 변환)
    predict     YOLO 추론만
    track       YOLO 추론 + ByteTrack 연관
    adapter     UltralyticsVehicleTracker.track() 전체(추론+ByteTrack+정규화)
    encode      JPEG 인코딩(라이브 스트리밍을 켰을 때 추가되는 비용의 하한)

`predict`와 `track`의 차이가 ByteTrack 비용이고, `track`과 `adapter`의 차이가
우리 정규화 코드 비용이다. `adapter`가 전체의 대부분을 차지하면 병목은 모델이지
판정 로직이 아니다 — 판정(ZoneVisit·ParkingEpisode·Incident)은 이 뒤에 오며
차량 몇 대에 대한 순수 파이썬 연산이라 여기 측정값과 자릿수가 다르다.

**정지 화면으로 재지 마라.** 빈 프레임은 검출이 0건이라 NMS도 ByteTrack도
거의 일하지 않아 실제보다 빠르게 나온다. 반드시 실제 영상이나 카메라를 쓴다.

레포 루트가 아니라 `hw/jetson`에서 모듈로 실행한다:

    cd hw/jetson

    # 파일럿 영상으로 (.pt 기준선)
    python -m scripts.benchmark_tracking \\
        --model /home/e202/model/yolov8s.pt \\
        --video ../../docs/video/video4.mp4 \\
        --calibration /home/e202/config/camera_calibration.json

    # TensorRT 엔진으로 변환한 뒤 같은 조건으로 다시
    python -m scripts.benchmark_tracking \\
        --model /home/e202/model/yolov8s.engine \\
        --video ../../docs/video/video4.mp4 \\
        --calibration /home/e202/config/camera_calibration.json

    # 실제 카메라로
    python -m scripts.benchmark_tracking \\
        --model /home/e202/model/yolov8s.pt \\
        --camera-index 0 \\
        --width 1280 --height 720 \\
        --fourcc MJPG --camera-fps 30

`--calibration`을 생략하면 remap 없이 원본 프레임으로 잰다. 모델 비용만
비교할 때는 생략하는 쪽이 변수를 줄인다.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from src.camera.frame_source import (
    EndOfVideo,
    FrameSource,
    OpenCvWebcamFrameSource,
    RemapFrameSource,
    VideoFileFrameSource,
)
from src.camera.models import CapturedFrame
from src.tracking.adapters.ultralytics_bytetrack import UltralyticsVehicleTracker


class Stage:
    """한 단계의 측정 샘플을 모은다."""

    def __init__(self, name: str, note: str = "") -> None:
        self.name = name
        self.note = note
        self.samples: list[float] = []

    @contextmanager
    def measure(self) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.samples.append((time.perf_counter() - started) * 1000.0)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.samples) if self.samples else 0.0

    @property
    def p50(self) -> float:
        return statistics.median(self.samples) if self.samples else 0.0

    @property
    def p95(self) -> float:
        if not self.samples:
            return 0.0
        ordered = sorted(self.samples)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[index]


def _build_source(args: argparse.Namespace) -> FrameSource:
    if args.video:
        inner: FrameSource = VideoFileFrameSource(
            camera_id="bench",
            path=Path(args.video),
            start_seconds=args.start_seconds,
        )
    else:
        inner = OpenCvWebcamFrameSource(
            camera_id="bench",
            camera_index=args.camera_index,
            width=args.width,
            height=args.height,
            fourcc=args.fourcc,
            fps=args.camera_fps,
        )
    if args.calibration:
        return RemapFrameSource(
            inner=inner,
            calibration_path=args.calibration,
            balance=args.remap_balance,
        )
    return inner


def _collect_frames(
    args: argparse.Namespace, count: int, decode: Stage
) -> list[CapturedFrame]:
    """decode(+remap) 비용을 재면서 프레임을 메모리에 모은다.

    이후 추론 pass들이 완전히 같은 입력을 보도록 미리 모은다 — pass마다 다른
    프레임을 보면 검출 수가 달라져 비교가 무의미해진다.
    """

    source = _build_source(args)
    source.open()
    frames: list[CapturedFrame] = []
    try:
        while len(frames) < count:
            with decode.measure():
                frame = source.capture()
            frames.append(frame)
    except EndOfVideo:
        if not frames:
            raise SystemExit("영상에서 프레임을 하나도 읽지 못했습니다.")
        print(
            f"  영상이 {len(frames)}프레임에서 끝났습니다 "
            f"(요청 {count}프레임).",
            file=sys.stderr,
        )
    finally:
        source.close()
    return frames


def _import_cv2() -> Any:
    import cv2

    return cv2


def _run_predict(
    args: argparse.Namespace,
    frames: list[CapturedFrame],
    warmup: int,
    cvt: Stage,
    predict: Stage,
) -> int:
    from ultralytics import YOLO

    cv2 = _import_cv2()
    model = YOLO(args.model)
    kwargs: dict[str, Any] = {"conf": args.conf, "verbose": False}
    if args.imgsz:
        kwargs["imgsz"] = args.imgsz
    if args.half:
        kwargs["half"] = True

    detections = 0
    for index, frame in enumerate(frames):
        measured = index >= warmup
        if measured:
            with cvt.measure():
                source_bgr = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
            with predict.measure():
                results = model.predict(source=source_bgr, **kwargs)
        else:
            source_bgr = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
            results = model.predict(source=source_bgr, **kwargs)
        if measured and results:
            boxes = getattr(results[0], "boxes", None)
            detections += 0 if boxes is None else len(boxes)
    return detections


def _run_track(
    args: argparse.Namespace,
    frames: list[CapturedFrame],
    warmup: int,
    track: Stage,
) -> None:
    from ultralytics import YOLO

    cv2 = _import_cv2()
    model = YOLO(args.model)
    kwargs: dict[str, Any] = {
        "persist": True,
        "tracker": args.tracker,
        "conf": args.conf,
        "verbose": False,
    }
    if args.imgsz:
        kwargs["imgsz"] = args.imgsz
    if args.half:
        kwargs["half"] = True

    for index, frame in enumerate(frames):
        source_bgr = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
        if index >= warmup:
            with track.measure():
                model.track(source=source_bgr, **kwargs)
        else:
            model.track(source=source_bgr, **kwargs)


def _run_adapter(
    args: argparse.Namespace,
    frames: list[CapturedFrame],
    warmup: int,
    adapter: Stage,
) -> None:
    tracker = UltralyticsVehicleTracker(
        model_path=args.model,
        tracker_config=args.tracker,
        confidence=args.conf,
    )
    tracker.open()
    try:
        for index, frame in enumerate(frames):
            if index >= warmup:
                with adapter.measure():
                    tracker.track(frame)
            else:
                tracker.track(frame)
    finally:
        tracker.close()


def _run_encode(
    frames: list[CapturedFrame], warmup: int, quality: int, encode: Stage
) -> None:
    cv2 = _import_cv2()
    for index, frame in enumerate(frames):
        canvas = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
        if index >= warmup:
            with encode.measure():
                cv2.imencode(
                    ".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
                )
        else:
            cv2.imencode(
                ".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            )


def _report(stages: list[Stage], frames: list[CapturedFrame]) -> None:
    print()
    print(f"프레임 {frames[0].width}x{frames[0].height}, 측정 표본 "
          f"{len(stages[0].samples) if stages[0].samples else 0}개")
    print()
    print(f"{'단계':<12}{'평균(ms)':>10}{'p50':>9}{'p95':>9}   설명")
    print("-" * 72)
    for stage in stages:
        if not stage.samples:
            continue
        print(
            f"{stage.name:<12}{stage.mean:>10.1f}{stage.p50:>9.1f}"
            f"{stage.p95:>9.1f}   {stage.note}"
        )
    print()

    by_name = {stage.name: stage for stage in stages if stage.samples}
    adapter = by_name.get("adapter")
    if adapter is not None:
        fps = 1000.0 / adapter.mean if adapter.mean else 0.0
        print(f"adapter 단독 처리율: {fps:.1f} fps")

    predict = by_name.get("predict")
    track = by_name.get("track")
    if predict is not None and track is not None:
        print(f"ByteTrack 비용 (track - predict): {track.mean - predict.mean:+.1f} ms")
    if track is not None and adapter is not None:
        print(f"정규화 비용 (adapter - track):    {adapter.mean - track.mean:+.1f} ms")
    print()


def build_parser() -> argparse.ArgumentParser:
    """CLI 계약을 테스트에서도 검증할 수 있도록 파서를 노출한다."""

    parser = argparse.ArgumentParser(
        description="젯슨 프레임 처리 비용을 단계별로 측정한다.",
    )
    parser.add_argument("--model", required=True, help=".pt 또는 .engine 경로")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--video", help="측정에 사용할 영상 파일")
    parser.add_argument(
        "--start-seconds",
        type=float,
        default=0.0,
        help="영상에서 측정을 시작할 지점(초). 차량이 보이는 구간을 골라야 한다",
    )
    source_group.add_argument(
        "--camera-index", type=int, help="측정에 사용할 카메라 인덱스"
    )
    parser.add_argument("--calibration", help="fisheye calibration JSON 경로")
    parser.add_argument("--remap-balance", type=float, default=0.5)
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    parser.add_argument(
        "--fourcc",
        help="카메라 pixel format FOURCC 네 글자. 예: MJPG",
    )
    parser.add_argument(
        "--camera-fps",
        type=float,
        default=0.0,
        help="카메라에 요청할 FPS. 0이면 장치 기본값",
    )
    parser.add_argument("--tracker", default="bytetrack.yaml")
    parser.add_argument("--conf", type=float, default=0.5)
    parser.add_argument(
        "--imgsz", type=int, help="지정하면 추론 입력 크기를 고정한다"
    )
    parser.add_argument(
        "--half", action="store_true", help="FP16 추론 (.pt에서 효과 확인용)"
    )
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--jpeg-quality", type=int, default=80)
    parser.add_argument(
        "--skip-encode", action="store_true", help="JPEG 인코딩 측정을 건너뛴다"
    )
    return parser


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.warmup >= args.frames:
        raise SystemExit("--warmup은 --frames보다 작아야 합니다.")

    remap_note = "fisheye 보정" if args.calibration else "(생략됨)"
    decode = Stage("decode", f"프레임 획득 + {remap_note}")
    cvt = Stage("cvtColor", "RGB→BGR (트래커가 매 프레임 수행)")
    predict = Stage("predict", "YOLO 추론만")
    track = Stage("track", "YOLO 추론 + ByteTrack 연관")
    adapter = Stage("adapter", "프로덕션 경로 전체(추론+ByteTrack+정규화)")
    encode = Stage("encode", "JPEG 인코딩 (라이브 스트리밍 추가 비용)")

    print(f"모델: {args.model}")
    print(f"프레임 수집 중 ({args.frames}개)...")
    frames = _collect_frames(args, args.frames, decode)
    warmup = min(args.warmup, max(0, len(frames) - 1))

    print("1/4 predict (추론만)...")
    detections = _run_predict(args, frames, warmup, cvt, predict)
    measured = max(1, len(frames) - warmup)
    print(f"    측정 구간 검출 {detections}건 (프레임당 {detections / measured:.1f})")
    if detections == 0:
        print(
            "    ⚠ 검출이 0건입니다. 차량이 없는 구간이면 실제보다 빠르게 "
            "측정됩니다 — 차량이 보이는 구간으로 다시 재세요.",
            file=sys.stderr,
        )

    print("2/4 track (추론 + ByteTrack)...")
    _run_track(args, frames, warmup, track)

    print("3/4 adapter (프로덕션 경로)...")
    _run_adapter(args, frames, warmup, adapter)

    if args.skip_encode:
        print("4/4 encode 건너뜀")
    else:
        print("4/4 encode (JPEG)...")
        _run_encode(frames, warmup, args.jpeg_quality, encode)

    _report([decode, cvt, predict, track, adapter, encode], frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

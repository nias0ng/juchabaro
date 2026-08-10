#!/usr/bin/env python3
"""보정된 프레임에서 마우스로 주차구역 폴리곤을 찍어 zones 파일을 만든다.

구역 계약 스펙 §12 한계 3("폴리곤 좌표 찍기는 수동이다")을 대체한다. 프레임을
VideoFileFrameSource + RemapFrameSource로 뽑기 때문에 리플레이·추론과 좌표계가
구조적으로 일치한다 — 보정 전 프레임에서 찍으면 아무 에러 없이 최대 133px
어긋난다(계약 스펙 §4).

리포 루트에서 실행한다:
    python ai/tracking/annotate_zones.py --video docs/video/video1.mp4 \
        --frame-seconds 5 --calibration ai/tracking/camera_calibration.json \
        --out ai/tracking/zones_pilot.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from jetson_vehicle_tracking_baseline import (
    DEFAULT_REMAP_BALANCE,
    BaselineError,
    RemapFrameSource,
    ZoneRegistry,
    ZoneType,
    _import_cv2,
    calibration_fingerprint,
    verify_zone_calibration,
)
from replay.video_source import VideoFileFrameSource
from replay.zone_annotator import ZoneAnnotator

LOGGER = logging.getLogger("annotate_zones")

# 숫자키 → 구역 종류. 확정 시 프롬프트에 표시된다.
_TYPE_KEYS = {
    "1": ZoneType.GENERAL,
    "2": ZoneType.DISABLED,
    "3": ZoneType.EV_FAST,
    "4": ZoneType.EV_SLOW,
    "5": ZoneType.AISLE,
    "6": ZoneType.ENTRY_EXIT,
}

_ZONE_COLORS = {
    ZoneType.GENERAL: (0, 200, 0),
    ZoneType.DISABLED: (0, 128, 255),
    ZoneType.EV_FAST: (255, 128, 0),
    ZoneType.EV_SLOW: (255, 200, 0),
    ZoneType.AISLE: (128, 128, 128),
    ZoneType.ENTRY_EXIT: (200, 0, 200),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True, help="폴리곤을 찍을 기준 영상.")
    parser.add_argument(
        "--frame-seconds",
        type=float,
        default=0.0,
        help="기준 프레임의 영상 내 시각(초). 차량이 구역을 가리지 않는 시점을 고른다.",
    )
    parser.add_argument("--calibration", type=Path, default=None, help="camera_calibration.json 경로.")
    parser.add_argument(
        "--remap-balance",
        type=float,
        default=DEFAULT_REMAP_BALANCE,
        help="학습 데이터 생성 시 쓴 값과 같아야 한다.",
    )
    parser.add_argument("--camera-code", default="PILOT-VIDEO", help="이 좌표계를 식별하는 카메라 코드.")
    parser.add_argument("--out", type=Path, required=True, help="생성할 zones 파일 경로.")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    """주석 작업 실행 전 수치 범위와 파일 존재를 검증한다.

    `--calibration`은 여기서는 필수로 만들지 않는다 — 보정 안 된 프레임에 일부러
    폴리곤을 찍고 싶은 경우(예: 임시 점검)가 있을 수 있어서다. 대신 생략 시 아래
    LOGGER.warning으로 결과물의 좌표계와 이후 리플레이가 막힐 것임을 크게 알린다.
    """

    if not (0.0 <= args.remap_balance <= 1.0):
        # OpenCV는 범위를 벗어난 balance도 조용히 받아들여 엉뚱한 new_K를 만든다.
        raise BaselineError("remap-balance는 0~1 범위여야 합니다.")
    if args.calibration is not None and not args.calibration.is_file():
        raise BaselineError(f"calibration 파일을 찾을 수 없습니다: {args.calibration}")
    if args.calibration is None:
        LOGGER.warning(
            "--calibration 없이 폴리곤을 찍습니다 — 생성될 폴리곤은 왜곡 보정 전(원본) "
            "좌표계 기준입니다. 이 zones 파일의 calibration 지문에는 remap: false만 "
            "기록되므로, verify_zone_calibration은 나중에 이 파일을 다른 보정 설정과 "
            "함께 쓰더라도 이 좌표계 불일치를 잡아내지 못합니다. 그리고 "
            "replay_pilot_video.py는 이제 --calibration을 필수로 요구하므로, 이 zones "
            "파일로 리플레이를 실행하면 그 자리에서 거부됩니다."
        )


def grab_reference_frame(args: argparse.Namespace):
    """리플레이와 같은 코드 경로로 보정된 기준 프레임 한 장을 얻는다."""

    inner = VideoFileFrameSource(path=args.video, start_seconds=args.frame_seconds)
    source = (
        RemapFrameSource(
            inner=inner, calibration_path=str(args.calibration), balance=args.remap_balance
        )
        if args.calibration is not None
        else inner
    )
    source.open()
    try:
        return source.capture()
    finally:
        source.close()


def draw(image, annotator: ZoneAnnotator, cv2):
    """확정된 구역과 진행 중인 폴리곤을 프레임 복사본에 그린다."""

    import numpy as np

    canvas = cv2.cvtColor(image, cv2.COLOR_RGB2BGR).copy()
    height, width = canvas.shape[:2]
    for zone in annotator.zones:
        color = _ZONE_COLORS[ZoneType(zone["zoneType"])]
        points = np.array(
            [[int(x * width), int(y * height)] for x, y in zone["polygon"]], dtype=np.int32
        )
        cv2.polylines(canvas, [points], isClosed=True, color=color, thickness=2)
        cv2.putText(
            canvas, zone["zoneNumber"], tuple(points[0]),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2,
        )
    for index, (px, py) in enumerate(annotator.pending_points):
        cv2.circle(canvas, (px, py), 4, (255, 255, 255), -1)
        if index:
            previous = annotator.pending_points[index - 1]
            cv2.line(canvas, previous, (px, py), (255, 255, 255), 1)
    cv2.putText(
        canvas,
        "L-click=point  R-click=undo point  Enter=commit  u=undo zone  s=save  Esc=quit",
        (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1,
    )
    return canvas


def prompt_zone(annotator: ZoneAnnotator) -> None:
    """확정 시 구역 종류·번호·허용시간을 터미널에서 입력받는다."""

    print("\n구역 종류를 선택하세요: " + ", ".join(f"{key}={zone.value}" for key, zone in _TYPE_KEYS.items()))
    key = input("번호: ").strip()
    if key not in _TYPE_KEYS:
        print(f"알 수 없는 선택입니다: {key!r} — 확정을 취소합니다(폴리곤은 유지됩니다).")
        return
    zone_type = _TYPE_KEYS[key]
    default_number = f"{zone_type.value}-{len(annotator.zones) + 1:02d}"
    zone_number = input(f"zone_number [{default_number}]: ").strip() or default_number
    allowed_minutes: float | None = None
    if zone_type in (ZoneType.EV_FAST, ZoneType.EV_SLOW):
        allowed_minutes = float(input("allowed_minutes (분): ").strip())
    try:
        annotator.commit(zone_type=zone_type, zone_number=zone_number, allowed_minutes=allowed_minutes)
    except BaselineError as exc:
        print(f"확정 실패: {exc} — 폴리곤은 유지됩니다.")
        return
    print(f"확정: {zone_number} ({zone_type.value})")


def save(args: argparse.Namespace, annotator: ZoneAnnotator) -> None:
    """페이로드를 쓰고, 쓴 파일을 스스로 다시 읽어 검증한다."""

    payload = annotator.payload()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    registry = ZoneRegistry.from_file(args.out)
    verify_zone_calibration(args)
    print(f"저장 완료: {args.out} (구역 {len(registry.all())}개) — 재파싱과 좌표계 검증을 통과했습니다.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    validate_args(args)
    if args.out.exists():
        answer = input(f"{args.out}가 이미 있습니다. 덮어쓸까요? [y/N]: ").strip().lower()
        if answer != "y":
            print("취소했습니다.")
            return 1
    # verify_zone_calibration이 args.zones_file을 읽으므로 저장 경로를 미리 채워둔다.
    args.zones_file = args.out

    cv2 = _import_cv2()
    frame = grab_reference_frame(args)
    height, width = frame.image.shape[:2]
    annotator = ZoneAnnotator(
        frame_width=width,
        frame_height=height,
        camera_code=args.camera_code,
        calibration=calibration_fingerprint(args.calibration, args.remap_balance),
    )

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            try:
                annotator.add_point(x, y)
            except BaselineError as exc:
                print(f"클릭 무시: {exc}")
        elif event == cv2.EVENT_RBUTTONDOWN:
            annotator.undo_point()

    window = "annotate zones"
    cv2.namedWindow(window)
    cv2.setMouseCallback(window, on_mouse)
    try:
        while True:
            cv2.imshow(window, draw(frame.image, annotator, cv2))
            key = cv2.waitKey(20) & 0xFF
            if key in (13, 10):          # Enter
                prompt_zone(annotator)
            elif key == ord("u"):
                annotator.undo_zone()
            elif key == 8:               # Backspace
                annotator.undo_point()
            elif key == ord("s"):
                save(args, annotator)
                return 0
            elif key == 27:              # Esc
                print("저장하지 않고 종료합니다.")
                return 1
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BaselineError as exc:
        LOGGER.error("%s", exc)
        sys.exit(1)

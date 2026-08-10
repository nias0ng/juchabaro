from __future__ import annotations
import argparse
from pathlib import Path

import cv2
import numpy as np

from calibration_utils import DEFAULT_REMAP_BALANCE, load_calibration, scale_K


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract remap-corrected frames from a pilot video within a valid time range")
    parser.add_argument("--video", required=True)
    parser.add_argument("--calibration", default="camera_calibration.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start-seconds", type=float, default=0.0)
    parser.add_argument("--end-seconds", type=float, required=True, help="only extract frames up to this timestamp (valid footage cutoff)")
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument(
        "--balance",
        type=float,
        default=DEFAULT_REMAP_BALANCE,
        help="0=crop to valid pixels only, 1=keep full FOV with black borders. Must match the "
        "value used at inference time (--remap-balance in jetson_vehicle_tracking_baseline.py).",
    )
    args = parser.parse_args()

    K_cal, D, cal_size = load_calibration(args.calibration)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        raise SystemExit(f"could not open video: {args.video}")
    video_size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    fps = cap.get(cv2.CAP_PROP_FPS)
    duration = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps if fps else 0

    if args.end_seconds > duration + 0.5:
        print(f"warning: --end-seconds {args.end_seconds} exceeds video duration {duration:.1f}s")

    K = scale_K(K_cal, cal_size, video_size)
    if cal_size != video_size:
        print(f"scaled intrinsics from calibration size {cal_size} to video size {video_size}")

    new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(K, D, video_size, np.eye(3), balance=args.balance)
    map1, map2 = cv2.fisheye.initUndistortRectifyMap(K, D, np.eye(3), new_K, video_size, cv2.CV_16SC2)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.video).stem

    t = args.start_seconds
    saved = 0
    while t < min(args.end_seconds, duration):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            print(f"  warning: failed to read frame at {t:.1f}s")
            t += args.interval_seconds
            continue

        undistorted = cv2.remap(frame, map1, map2, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        out_path = output_dir / f"{stem}_{int(t * 1000):07d}ms.png"
        cv2.imwrite(str(out_path), undistorted)
        saved += 1
        t += args.interval_seconds

    cap.release()
    print(f"saved {saved} frames to {output_dir} (valid range 0-{args.end_seconds:.0f}s of {duration:.1f}s total)")


if __name__ == "__main__":
    main()

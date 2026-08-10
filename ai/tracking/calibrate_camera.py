from __future__ import annotations
import argparse
import glob
import json
from pathlib import Path

import cv2
import numpy as np


def find_corners(image_paths: list[str], cols: int, rows: int) -> tuple[list[np.ndarray], list[np.ndarray], tuple[int, int]]:
    """Detect checkerboard corners in each image. Returns (objpoints, imgpoints, image_size)."""
    objp = np.zeros((1, cols * rows, 3), np.float64)
    objp[0, :, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_FAST_CHECK + cv2.CALIB_CB_NORMALIZE_IMAGE

    objpoints, imgpoints = [], []
    image_size = None
    for path in image_paths:
        img = cv2.imread(path)
        if img is None:
            print(f"  skip (unreadable): {path}")
            continue
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if image_size is None:
            image_size = (gray.shape[1], gray.shape[0])

        found, corners = cv2.findChessboardCorners(gray, (cols, rows), flags)
        if not found:
            print(f"  no checkerboard found: {path}")
            continue

        corners = cv2.cornerSubPix(gray, corners, (5, 5), (-1, -1), criteria)
        objpoints.append(objp)
        imgpoints.append(corners.reshape(1, -1, 2).astype(np.float64))
        print(f"  ok: {path}")

    return objpoints, imgpoints, image_size


def calibrate_fisheye(objpoints, imgpoints, image_size, square_size_mm: float) -> dict:
    n = len(objpoints)
    K = np.zeros((3, 3))
    D = np.zeros((4, 1))
    rvecs = [np.zeros((1, 1, 3), dtype=np.float64) for _ in range(n)]
    tvecs = [np.zeros((1, 1, 3), dtype=np.float64) for _ in range(n)]

    flags = (
        cv2.CALIB_RECOMPUTE_EXTRINSIC
        + cv2.CALIB_CHECK_COND
        + cv2.CALIB_FIX_SKEW
    )
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-6)

    # square_size_mm only rescales the translation vectors (real-world units); K/D are unaffected.
    scaled_objpoints = [op * square_size_mm for op in objpoints]

    rms, K, D, rvecs, tvecs = cv2.fisheye.calibrate(
        scaled_objpoints, imgpoints, image_size, K, D, rvecs, tvecs, flags, criteria
    )

    return {"rms": rms, "K": K, "D": D, "image_size": image_size, "num_images": n}


def main() -> None:
    parser = argparse.ArgumentParser(description="Fisheye camera calibration from checkerboard photos")
    parser.add_argument("--images-dir", default="../../docs/calibration")
    parser.add_argument("--pattern", default="*.jpg")
    parser.add_argument("--cols", type=int, default=9, help="internal corners, horizontal")
    parser.add_argument("--rows", type=int, default=6, help="internal corners, vertical")
    parser.add_argument("--square-size", type=float, default=25.0, help="square size in mm")
    parser.add_argument("--output", default=None, help="output .npz path (default: <images-dir>/camera_calibration.npz)")
    args = parser.parse_args()

    images_dir = Path(args.images_dir)
    image_paths = sorted(glob.glob(str(images_dir / args.pattern)))
    print(f"found {len(image_paths)} images in {images_dir}")

    objpoints, imgpoints, image_size = find_corners(image_paths, args.cols, args.rows)
    if len(objpoints) < 3:
        raise SystemExit(f"only {len(objpoints)} usable images (need >= 3) — capture more or check --cols/--rows")

    result = calibrate_fisheye(objpoints, imgpoints, image_size, args.square_size)

    output_path = Path(args.output) if args.output else images_dir / "camera_calibration.npz"
    np.savez(output_path, K=result["K"], D=result["D"], image_size=np.array(result["image_size"]))

    summary_path = output_path.with_suffix(".json")
    summary = {
        "rms_reprojection_error": result["rms"],
        "num_images_used": result["num_images"],
        "num_images_found": len(image_paths),
        "image_size": result["image_size"],
        "K": result["K"].tolist(),
        "D": result["D"].flatten().tolist(),
        "square_size_mm": args.square_size,
        "board_internal_corners": [args.cols, args.rows],
    }
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nused {result['num_images']}/{len(image_paths)} images")
    print(f"RMS reprojection error: {result['rms']:.4f} px")
    print(f"saved: {output_path}")
    print(f"saved: {summary_path}")


if __name__ == "__main__":
    main()

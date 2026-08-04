#!/usr/bin/env python3
"""좌우 crop 이후에 맞게 zone_definition JSON의 polygon x좌표를 재계산한다.

`CropFrameSource`(RemapFrameSource 뒤에서 프레임 좌우 여백을 잘라냄)를 쓰면
zone polygon은 원래 폭(old_width) 기준 정규화 좌표라서 crop 이후 폭
(new_width) 기준으로 다시 정규화해야 한다. y좌표는 crop 대상이 아니므로
바꾸지 않는다.

`calibrationReference`는 그대로 유지한다 — CropFrameSource는 calibration_id에
영향을 주지 않는다(RemapFrameSource가 채우는 calibration_id는 캘리브레이션
파일 자체의 지문이라 프레임 크기와 무관하다, `src/camera/frame_source.py`의
`calibration_fingerprint()` 참고).

    cd hw/jetson
    python -m scripts.recrop_zone_definition \\
        --zones-file config/zone_definition.pilot.json \\
        --old-width 1920 \\
        --crop-left-px 150 --crop-right-px 0 \\
        --out config/zone_definition.pilot.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


class RecropError(RuntimeError):
    """crop 파라미터가 잘못됐거나, crop 후 폴리곤 좌표가 [0, 1] 범위를 벗어났다."""


def recrop_x(x: float, *, old_width: int, crop_left_px: int, new_width: int) -> float:
    return (x * old_width - crop_left_px) / new_width


def recrop_payload(
    payload: dict, *, old_width: int, crop_left_px: int, crop_right_px: int
) -> dict:
    """zone_definition JSON payload(dict)의 polygon x좌표를 재정규화한 새 dict를 반환한다."""

    new_width = old_width - crop_left_px - crop_right_px
    if new_width <= 0:
        raise RecropError(
            "crop 합이 프레임 폭 이상입니다: "
            f"old_width={old_width}, crop_left_px={crop_left_px}, crop_right_px={crop_right_px}"
        )

    new_zones = []
    for zone in payload["zones"]:
        new_polygon = []
        for x, y in zone["polygon"]:
            new_x = recrop_x(x, old_width=old_width, crop_left_px=crop_left_px, new_width=new_width)
            if not (0.0 <= new_x <= 1.0):
                raise RecropError(
                    f"zoneId {zone['zoneId']}의 좌표가 crop 후 [0, 1] 범위를 벗어났습니다: "
                    f"x={x} -> {new_x}"
                )
            new_polygon.append([round(new_x, 6), y])
        new_zones.append({**zone, "polygon": new_polygon})

    return {
        "zoneDefinitionVersion": payload["zoneDefinitionVersion"] + 1,
        "calibrationReference": payload["calibrationReference"],
        "zones": new_zones,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--zones-file", type=Path, required=True)
    parser.add_argument(
        "--old-width", type=int, required=True,
        help="crop 전 프레임 폭(px). RemapFrameSource 출력 폭과 같아야 한다.",
    )
    parser.add_argument("--crop-left-px", type=int, required=True)
    parser.add_argument("--crop-right-px", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = json.loads(args.zones_file.read_text(encoding="utf-8"))
    new_payload = recrop_payload(
        payload,
        old_width=args.old_width,
        crop_left_px=args.crop_left_px,
        crop_right_px=args.crop_right_px,
    )
    args.out.write_text(json.dumps(new_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"완료: zoneDefinitionVersion {payload['zoneDefinitionVersion']} -> "
        f"{new_payload['zoneDefinitionVersion']}, {args.out}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RecropError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        sys.exit(1)

"""카메라가 생산하는 프레임과 촬영 메타데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class CapturedFrame:
    """카메라 한 대가 한 시점에 만든 보정 완료 프레임.

    `image`는 왜곡 보정이 끝난 RGB uint8 (H x W x 3) 배열이다. `calibration_id`는
    이 프레임이 어떤 보정 설정으로 만들어졌는지 식별하며, 구역 polygon도 같은
    `calibration_id` 좌표계를 사용해야 한다(데이터흐름.md §1).
    """

    camera_id: str
    frame_id: int
    captured_at: datetime
    image: Any
    width: int
    height: int
    calibration_id: str | None

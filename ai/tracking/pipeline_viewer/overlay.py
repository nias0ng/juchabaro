"""운영 tracking·parking 출력만 사용해 viewer용 overlay를 그린다.

이 모듈은 overlap, 주차 또는 Incident를 다시 판정하지 않는다. 정규화된
운영 출력 좌표를 화면 픽셀로 옮기고 이미지 복사본에 표시하는 역할만 가진다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.application.frame_observation_workflow import FrameObservationResult
from src.parking.models import ZoneDefinition, ZoneType
from src.tracking.models import PhysicalVehicleId, TrackingBatch


_ZONE_COLORS_RGB = {
    ZoneType.ENTRY_EXIT: (66, 165, 245),
    ZoneType.GENERAL: (99, 210, 151),
    ZoneType.DISABLED: (255, 159, 67),
    ZoneType.EV_CHARGING: (175, 125, 255),
    ZoneType.AISLE: (180, 180, 180),
}
_VEHICLE_COLOR_RGB = (39, 222, 245)
_INCIDENT_COLOR_RGB = (255, 76, 76)
_ASSIGNMENT_COLOR_RGB = (255, 222, 89)


def draw_frame_overlay(
    image_rgb: np.ndarray,
    *,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
    zones: Sequence[ZoneDefinition],
    alias_for: Callable[[PhysicalVehicleId], str],
) -> np.ndarray:
    """보정 완료 RGB 프레임의 복사본에 실제 typed output을 표시한다."""

    rendered = np.array(image_rgb, copy=True)
    if rendered.ndim != 3 or rendered.shape[2] != 3:
        raise ValueError("viewer overlay requires an RGB HxWx3 image")
    height, width = rendered.shape[:2]
    if height <= 0 or width <= 0:
        raise ValueError("viewer overlay requires a non-empty image")

    for zone in zones:
        points = _polygon_pixels(zone.polygon, width=width, height=height)
        color = _ZONE_COLORS_RGB.get(zone.zone_type, (200, 200, 200))
        cv2.polylines(rendered, [points], True, color, 2, cv2.LINE_AA)
        anchor = tuple(int(value) for value in points[0, 0])
        _put_label(
            rendered,
            f"Z{zone.zone_id} {zone.zone_type.value}",
            anchor,
            color,
        )

    active_incident_vehicle_ids = {
        incident.physical_vehicle_id for incident in result.active_incidents
    }
    incident_rules: dict[PhysicalVehicleId, list[str]] = {}
    for incident in result.active_incidents:
        incident_rules.setdefault(incident.physical_vehicle_id, []).append(
            incident.key.rule_code
        )

    for vehicle in tracking_batch.vehicles:
        bbox = vehicle.bbox
        x1 = int(round(bbox.x1 * width))
        y1 = int(round(bbox.y1 * height))
        x2 = int(round(bbox.x2 * width))
        y2 = int(round(bbox.y2 * height))
        has_incident = vehicle.physical_vehicle_id in active_incident_vehicle_ids
        color = _INCIDENT_COLOR_RGB if has_incident else _VEHICLE_COLOR_RGB
        cv2.rectangle(rendered, (x1, y1), (x2, y2), color, 3, cv2.LINE_AA)
        label = (
            f"{alias_for(vehicle.physical_vehicle_id)} "
            f"T{vehicle.track_segment_id} {vehicle.motion_signal.value} "
            f"{vehicle.confidence:.2f}"
        )
        if has_incident:
            label += " | " + ",".join(
                sorted(incident_rules[vehicle.physical_vehicle_id])
            )
        _put_label(rendered, label, (x1, max(16, y1 - 4)), color)

    for episode in result.parking_result.parking_episode_updates:
        if episode.assignment is None:
            continue
        points = _polygon_pixels(
            episode.assignment.representative_footprint,
            width=width,
            height=height,
        )
        cv2.polylines(
            rendered,
            [points],
            True,
            _ASSIGNMENT_COLOR_RGB,
            2,
            cv2.LINE_AA,
        )

    return rendered


def write_jpeg(path: Path, image_rgb: np.ndarray, *, quality: int = 82) -> None:
    """RGB 이미지를 viewer workspace의 JPEG로 기록한다."""

    if not 1 <= quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100")
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    ok, encoded = cv2.imencode(
        ".jpg",
        bgr,
        [int(cv2.IMWRITE_JPEG_QUALITY), quality],
    )
    if not ok:
        raise OSError(f"viewer frame JPEG encoding failed: {path}")
    path.write_bytes(encoded.tobytes())


def _polygon_pixels(
    polygon: Sequence[tuple[float, float]],
    *,
    width: int,
    height: int,
) -> np.ndarray:
    points = [
        (
            min(width - 1, max(0, int(round(x * width)))),
            min(height - 1, max(0, int(round(y * height)))),
        )
        for x, y in polygon
    ]
    return np.asarray(points, dtype=np.int32).reshape((-1, 1, 2))


def _put_label(
    image: np.ndarray,
    text: str,
    origin: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    x, y = origin
    cv2.putText(
        image,
        text,
        (max(0, x), max(14, y)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.48,
        color,
        2,
        cv2.LINE_AA,
    )

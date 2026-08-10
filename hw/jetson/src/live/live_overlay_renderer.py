"""판정 결과를 실시간 프레임 위에 그려 JPEG로 인코딩한다.

`ai/tracking/replay/overlay.py`의 `OverlayWriter`는 재사용하지 않는다 —
그 코드는 폐기 예정인 옛 baseline(`ViolationStatus` 등) 계약에 물려 있고,
여기서는 466 이후 정착된 `ZoneVisit`/`ParkingEpisode` 계약을 그린다.

그리기(`draw_overlay`)와 JPEG 인코딩(`encode_jpeg`)을 분리했다 — 그리기는
순수 numpy 연산이라 픽셀 단위로 정확히 테스트할 수 있고, JPEG는 손실
압축이라 같은 방식으로 테스트할 수 없다.
"""

from __future__ import annotations

from typing import Mapping

import cv2
import numpy as np

from src.application.frame_observation_workflow import FrameObservationResult
from src.camera.models import CapturedFrame
from src.parking.models import (
    Incident,
    IncidentState,
    ParkingEpisode,
    ParkingState,
    ZoneType,
    ZoneVisit,
    ZoneVisitState,
)
from src.parking.zone_registry import ZoneRegistry
from src.tracking.models import PhysicalVehicleId, TrackingBatch

_ZONE_COLORS: dict[ZoneType, tuple[int, int, int]] = {
    ZoneType.GENERAL: (0, 200, 0),
    ZoneType.DISABLED: (0, 128, 255),
    ZoneType.EV_CHARGING: (255, 128, 0),
    ZoneType.AISLE: (128, 128, 128),
    ZoneType.ENTRY_EXIT: (200, 0, 200),
}
_THICK_ZONE_TYPES = frozenset({ZoneType.DISABLED, ZoneType.EV_CHARGING})
_NEUTRAL_COLOR = (160, 160, 160)
_ZONE_VISIT_COLORS: dict[ZoneVisitState, tuple[int, int, int]] = {
    ZoneVisitState.ENTERING: (0, 220, 220),
    ZoneVisitState.INSIDE: (0, 255, 0),
    ZoneVisitState.EXITING: (0, 165, 255),
    ZoneVisitState.ENDED: (100, 100, 180),
    ZoneVisitState.CANCELED: (100, 180, 180),
}
_ZONE_VISIT_PRIORITY: tuple[ZoneVisitState, ...] = (
    ZoneVisitState.INSIDE,
    ZoneVisitState.ENTERING,
    ZoneVisitState.EXITING,
    ZoneVisitState.ENDED,
    ZoneVisitState.CANCELED,
)
_ZONE_VISIT_PRIORITY_RANK: dict[ZoneVisitState, int] = {
    state: rank for rank, state in enumerate(_ZONE_VISIT_PRIORITY)
}
_UNKNOWN_ZONE_VISIT_RANK = len(_ZONE_VISIT_PRIORITY)
_PARKING_EPISODE_COLORS: dict[ParkingState, tuple[int, int, int]] = {
    ParkingState.STOP_PENDING: (0, 255, 255),
    ParkingState.PARKED: (0, 0, 255),
    ParkingState.MOVE_PENDING: (255, 0, 255),
}
_ACTIVE_PARKING_STATES = frozenset(_PARKING_EPISODE_COLORS)
# 사건 표시색은 bbox 상태 팔레트와 다른 축이다 — bbox 색은 주차·구역 상태를
# 계속 나타내고, 사건은 그 위에 겹쳐 그리는 별도 배지·배너로만 쓴다.
_INCIDENT_COLOR = (40, 40, 255)
_INCIDENT_BANNER_HEIGHT = 40
_ACTIVE_INCIDENT_STATES = frozenset({IncidentState.OPEN, IncidentState.CLEAR_PENDING})
_DEFAULT_JPEG_QUALITY = 80


def draw_overlay(
    frame: CapturedFrame,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
    *,
    zones: ZoneRegistry,
) -> np.ndarray:
    """RGB `CapturedFrame` 위에 구역·bbox·판정상태를 그린 BGR uint8 canvas를 반환한다.

    `cv2.cvtColor`가 항상 새 배열을 할당하므로 `frame.image`를 그대로 두고 그린다 —
    이 함수는 `frame.image`를 in-place로 수정해서는 안 된다(`RemapFrameSource`가 dst
    버퍼를 재사용하므로 원본을 건드리면 다음 프레임에 낙서가 남는다).
    """

    canvas = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
    _draw_zones(canvas, zones)
    _draw_vehicles(canvas, tracking_batch, result)
    _draw_incidents(canvas, tracking_batch, result)
    return canvas


def encode_jpeg(canvas: np.ndarray, *, jpeg_quality: int = _DEFAULT_JPEG_QUALITY) -> bytes:
    """BGR canvas를 JPEG bytes로 인코딩한다.

    인코딩 실패 시 `ValueError`를 던진다. 이 예외를 잡아 placeholder 프레임으로
    대체하는 책임은 호출자(향후 479의 `live_stream_loop`)에 있다 —
    `MonitoringPipeline`으로 전파되면 `MonitoringWorker`가 이를 치명 오류로 처리해
    전체 카메라·모델을 끈다.
    """

    ok, buffer = cv2.imencode(".jpg", canvas, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        raise ValueError("JPEG 인코딩에 실패했습니다")
    return buffer.tobytes()


def render_overlay_jpeg(
    frame: CapturedFrame,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
    *,
    zones: ZoneRegistry,
    jpeg_quality: int = _DEFAULT_JPEG_QUALITY,
) -> bytes:
    """`(frame, tracking_batch, result)` -> JPEG bytes. `FrameObserver`에 zones/jpeg_quality를 고정해 연결하는 진입점."""

    canvas = draw_overlay(frame, tracking_batch, result, zones=zones)
    return encode_jpeg(canvas, jpeg_quality=jpeg_quality)


def _draw_zones(canvas: np.ndarray, zones: ZoneRegistry) -> None:
    height, width = canvas.shape[:2]
    for zone in zones.all():
        color = _ZONE_COLORS.get(zone.zone_type, (255, 255, 255))
        thickness = 3 if zone.zone_type in _THICK_ZONE_TYPES else 1
        points = np.array(
            [[int(x * width), int(y * height)] for x, y in zone.polygon], dtype=np.int32
        )
        cv2.polylines(canvas, [points], isClosed=True, color=color, thickness=thickness)
        cv2.putText(
            canvas, str(zone.zone_id), tuple(int(v) for v in points[0]),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )


def _draw_vehicles(
    canvas: np.ndarray,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
) -> None:
    height, width = canvas.shape[:2]
    episode_by_vehicle = _index_episodes(result.parking_result.parking_episode_updates)
    visit_by_vehicle = _index_zone_visits(result.parking_result.zone_visit_updates)

    for vehicle in tracking_batch.vehicles:
        color, label_suffix = _vehicle_status(
            vehicle.physical_vehicle_id, episode_by_vehicle, visit_by_vehicle
        )
        x1 = int(vehicle.bbox.x1 * width)
        y1 = int(vehicle.bbox.y1 * height)
        x2 = int(vehicle.bbox.x2 * width)
        y2 = int(vehicle.bbox.y2 * height)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        short_id = str(vehicle.physical_vehicle_id)[:8]
        cv2.putText(
            canvas, f"#{short_id} {label_suffix}".rstrip(), (x1, max(12, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1,
        )


def _draw_incidents(
    canvas: np.ndarray,
    tracking_batch: TrackingBatch,
    result: FrameObservationResult,
) -> None:
    """확정된 사건을 차량별 배지와 상단 배너로 그린다.

    `incident_transitions`가 아니라 `incident_updates`를 읽는다 — 전자는 OPEN·
    RESOLVE가 일어난 프레임에만 값이 있어 배지가 한 프레임만 번쩍인다.
    """

    height, width = canvas.shape[:2]
    incidents_by_vehicle = _index_incidents(result.parking_result.incident_updates)
    if not incidents_by_vehicle:
        return

    for vehicle in tracking_batch.vehicles:
        incidents = incidents_by_vehicle.get(vehicle.physical_vehicle_id)
        if not incidents:
            continue
        x1 = int(vehicle.bbox.x1 * width)
        y2 = int(vehicle.bbox.y2 * height)
        for offset, incident in enumerate(incidents):
            baseline = min(height - 4, y2 + 18 + offset * 18)
            cv2.putText(
                canvas, incident.key.rule_code, (x1, baseline),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, _INCIDENT_COLOR, 2,
            )

    _draw_incident_banner(canvas, incidents_by_vehicle)


def _draw_incident_banner(
    canvas: np.ndarray,
    incidents_by_vehicle: Mapping[PhysicalVehicleId, tuple[Incident, ...]],
) -> None:
    """발표장 뒷자리에서도 읽히도록 활성 규칙코드를 상단에 크게 띄운다."""

    rule_codes = sorted(
        {
            incident.key.rule_code
            for incidents in incidents_by_vehicle.values()
            for incident in incidents
        }
    )
    width = canvas.shape[1]
    cv2.rectangle(
        canvas, (0, 0), (width, _INCIDENT_BANNER_HEIGHT), (0, 0, 0), thickness=-1
    )
    cv2.putText(
        canvas, " / ".join(rule_codes), (8, _INCIDENT_BANNER_HEIGHT - 12),
        cv2.FONT_HERSHEY_SIMPLEX, 0.8, _INCIDENT_COLOR, 2,
    )


def _index_incidents(
    incidents: tuple[Incident, ...]
) -> Mapping[PhysicalVehicleId, tuple[Incident, ...]]:
    """확정된(OPEN·CLEAR_PENDING) 사건만 차량별로 모은다.

    CANDIDATE는 아직 확정 전이고 RESOLVED·CANCELED는 끝났으므로 그리지 않는다.
    """

    grouped: dict[PhysicalVehicleId, list[Incident]] = {}
    for incident in incidents:
        if incident.state not in _ACTIVE_INCIDENT_STATES:
            continue
        grouped.setdefault(incident.physical_vehicle_id, []).append(incident)
    return {
        vehicle_id: tuple(sorted(group, key=lambda item: item.key.rule_code))
        for vehicle_id, group in grouped.items()
    }


def _index_episodes(
    episodes: tuple[ParkingEpisode, ...]
) -> Mapping[PhysicalVehicleId, ParkingEpisode]:
    return {episode.physical_vehicle_id: episode for episode in episodes}


def _index_zone_visits(
    visits: tuple[ZoneVisit, ...]
) -> Mapping[PhysicalVehicleId, tuple[ZoneVisit, ...]]:
    grouped: dict[PhysicalVehicleId, list[ZoneVisit]] = {}
    for visit in visits:
        grouped.setdefault(visit.physical_vehicle_id, []).append(visit)
    return {vehicle_id: tuple(group) for vehicle_id, group in grouped.items()}


def _pick_primary_visit(visits: tuple[ZoneVisit, ...]) -> ZoneVisit:
    return min(
        visits,
        key=lambda visit: _ZONE_VISIT_PRIORITY_RANK.get(visit.state, _UNKNOWN_ZONE_VISIT_RANK),
    )


def _vehicle_status(
    vehicle_id: PhysicalVehicleId,
    episode_by_vehicle: Mapping[PhysicalVehicleId, ParkingEpisode],
    visit_by_vehicle: Mapping[PhysicalVehicleId, tuple[ZoneVisit, ...]],
) -> tuple[tuple[int, int, int], str]:
    episode = episode_by_vehicle.get(vehicle_id)
    if episode is not None and episode.state in _ACTIVE_PARKING_STATES:
        return _PARKING_EPISODE_COLORS.get(episode.state, _NEUTRAL_COLOR), episode.state.value

    visits = visit_by_vehicle.get(vehicle_id)
    if visits:
        visit = _pick_primary_visit(visits)
        return _ZONE_VISIT_COLORS.get(visit.state, _NEUTRAL_COLOR), f"zone{visit.zone_id} {visit.state.value}"

    return _NEUTRAL_COLOR, ""

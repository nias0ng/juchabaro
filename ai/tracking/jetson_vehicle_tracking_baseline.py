#!/usr/bin/env python3
"""천장 카메라 기반 차량 탐지·트래킹·주차 위반 판정 베이스라인 (초안).

데모 단계에서는 일반 웹캠으로 동작을 확인하고, 실제 배치에서는 Jetson Orin
Nano + TensorRT로 내보낸 가중치로 `--model-path`만 교체하는 것을 전제로 한다.
탐지는 Ultralytics YOLOv8, 트래킹은 같은 라이브러리의 ByteTrack 통합
(`model.track(...)`)을 사용한다.

이 파일은 `ai/ocr/rpi_ocr_baseline.py`와 같은 설계 방식을 따른다: 프레임
공급, 탐지+트래킹, 위반 판정, 결과 발행을 각각 Protocol 뒤에 두어 카메라나
모델, 전송 방식을 교체해도 핵심 로직(구역 겹침·정차 시간 판정)이 바뀌지
않도록 격리한다.

아직 다루지 않은 부분(팀 검토 후 이어서 구현 필요):
- 입차 게이트 OCR과의 트랙 매칭(§2.2): `ViolationMonitor.attach_plate`가
  결과를 반영하는 훅만 제공하며, 실제 매칭 로직(시간·공간 근접도 계산)은
  이 파일 밖(입차-트래킹 매칭 단계)에서 구현되어야 한다.
- 장애인/전기차 구역의 "등록 차량 여부" 서버 조회: 여기서는 구역을
  점유했다는 사실만 `RESTRICTED_ZONE`으로 표시하고, 실제 인증 여부 판단은
  서버 몫으로 남겨둔다(조회 실패 시 안전 우선 정책으로 위반 의심 유지).
- 트랙이 한두 프레임 잠깐 사라졌다가 같은 차량으로 복귀하는 경우의 유예
  처리는 없다(사라지면 즉시 상태를 초기화한다).

CLI 모드: 웹캠 점검(`--probe-camera`), 캘리브레이션용 프레임 저장
(`--capture-frame`), 실시간 루프(`--run`), 하드웨어 비의존 자체 테스트
(`--self-test`).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import logging
import math
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
import unittest


LOGGER = logging.getLogger("jetson_vehicle_tracking_baseline")


class BaselineError(RuntimeError):
    """CLI 경계까지 원인 메시지를 보존하는 트래킹 베이스라인 오류."""


class ZoneType(str, Enum):
    """주차구역 종류. §5.0: 설치 시 관리자가 폴리곤과 함께 1회 등록한다."""

    GENERAL = "GENERAL"
    DISABLED = "DISABLED"
    EV_FAST = "EV_FAST"
    EV_SLOW = "EV_SLOW"
    AISLE = "AISLE"
    ENTRY_EXIT = "ENTRY_EXIT"


# 전용구역(장애인/전기차) 점유는 위반 의심으로 표시한다. 실제 등록 차량
# 여부는 서버 조회로 확정하며 이 파일의 책임 범위가 아니다.
RESTRICTED_ZONE_TYPES = frozenset({ZoneType.DISABLED, ZoneType.EV_FAST, ZoneType.EV_SLOW})
# 입출차 감지용 참고 구역은 주차 위반 판정 대상에서 제외한다.
IGNORED_ZONE_TYPES_FOR_PARKING = frozenset({ZoneType.ENTRY_EXIT})


class ViolationStatus(str, Enum):
    """트랙 하나의 현재 위반 판정 상태."""

    NONE = "NONE"
    OBSERVING = "OBSERVING"
    RESTRICTED_ZONE = "RESTRICTED_ZONE"
    LINE_CROSS = "LINE_CROSS"
    AISLE_BLOCK = "AISLE_BLOCK"
    DOUBLE_PARK = "DOUBLE_PARK"


@dataclass(frozen=True)
class NormalizedPolygon:
    """0~1 정규화 좌표 정점으로 표현한 구역 경계 (3개 이상, 단순 다각형 가정)."""

    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("폴리곤은 정점이 3개 이상이어야 합니다.")
        for x, y in self.points:
            if not (isinstance(x, (int, float)) and isinstance(y, (int, float))):
                raise ValueError("폴리곤 좌표는 숫자여야 합니다.")
            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError("폴리곤 좌표는 유한한 숫자여야 합니다.")
            if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
                raise ValueError("폴리곤 좌표는 0~1 범위여야 합니다.")


@dataclass(frozen=True)
class BoundingBox:
    """0~1 정규화 좌표의 차량 바운딩박스."""

    x1: float
    y1: float
    x2: float
    y2: float

    def __post_init__(self) -> None:
        values = (self.x1, self.y1, self.x2, self.y2)
        if not all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in values):
            raise ValueError("바운딩박스 좌표는 0~1 범위의 유한한 숫자여야 합니다.")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("바운딩박스는 x2>x1, y2>y1 이어야 합니다.")

    def area(self) -> float:
        """바운딩박스 면적(정규화 단위)을 반환한다."""

        return (self.x2 - self.x1) * (self.y2 - self.y1)

    def center(self) -> tuple[float, float]:
        """바운딩박스 중심 좌표를 반환한다."""

        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)


def _lerp_x(a: tuple[float, float], b: tuple[float, float], x: float) -> tuple[float, float]:
    t = (x - a[0]) / (b[0] - a[0])
    return (x, a[1] + t * (b[1] - a[1]))


def _lerp_y(a: tuple[float, float], b: tuple[float, float], y: float) -> tuple[float, float]:
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), y)


def _clip_polygon_half_plane(
    points: Sequence[tuple[float, float]],
    inside: Callable[[tuple[float, float]], bool],
    intersect: Callable[[tuple[float, float], tuple[float, float]], tuple[float, float]],
) -> list[tuple[float, float]]:
    """Sutherland-Hodgman 알고리즘으로 다각형을 반평면 하나로 자른다."""

    if not points:
        return []
    output: list[tuple[float, float]] = []
    prev = points[-1]
    prev_inside = inside(prev)
    for curr in points:
        curr_inside = inside(curr)
        if curr_inside:
            if not prev_inside:
                output.append(intersect(prev, curr))
            output.append(curr)
        elif prev_inside:
            output.append(intersect(prev, curr))
        prev, prev_inside = curr, curr_inside
    return output


def clip_polygon_to_bbox(
    points: Sequence[tuple[float, float]], bbox: BoundingBox
) -> list[tuple[float, float]]:
    """구역 폴리곤을 차량 바운딩박스(축 정렬 사각형) 범위로 잘라낸다."""

    clipped = list(points)
    clipped = _clip_polygon_half_plane(clipped, lambda p: p[0] >= bbox.x1, lambda a, b: _lerp_x(a, b, bbox.x1))
    clipped = _clip_polygon_half_plane(clipped, lambda p: p[0] <= bbox.x2, lambda a, b: _lerp_x(a, b, bbox.x2))
    clipped = _clip_polygon_half_plane(clipped, lambda p: p[1] >= bbox.y1, lambda a, b: _lerp_y(a, b, bbox.y1))
    clipped = _clip_polygon_half_plane(clipped, lambda p: p[1] <= bbox.y2, lambda a, b: _lerp_y(a, b, bbox.y2))
    return clipped


def _polygon_area(points: Sequence[tuple[float, float]]) -> float:
    """신 발끈(Shoelace) 공식으로 다각형 면적을 계산한다."""

    if len(points) < 3:
        return 0.0
    total = 0.0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def overlap_ratio(polygon: NormalizedPolygon, bbox: BoundingBox) -> float:
    """구역 폴리곤과 차량 바운딩박스의 겹침 비율(차체 기준, §5.1)을 계산한다."""

    bbox_area = bbox.area()
    if bbox_area <= 0.0:
        return 0.0
    clipped = clip_polygon_to_bbox(polygon.points, bbox)
    return _polygon_area(clipped) / bbox_area


def _bbox_to_polygon(bbox: BoundingBox) -> NormalizedPolygon:
    """바운딩박스를 겹침 계산에 재사용할 수 있도록 4점 폴리곤으로 변환한다(이중주차 판정용)."""

    return NormalizedPolygon(((bbox.x1, bbox.y1), (bbox.x2, bbox.y1), (bbox.x2, bbox.y2), (bbox.x1, bbox.y2)))


@dataclass(frozen=True)
class ParkingZone:
    """설치 시 1회 캘리브레이션으로 등록되는 주차구역 정의 (§5.0)."""

    zone_id: str
    zone_type: ZoneType
    polygon: NormalizedPolygon


class ZoneRegistry:
    """구역 정의 목록을 보관한다. 스키마는 백엔드 `/internal/zones`와 동일하게 맞춘다."""

    def __init__(self, zones: Sequence[ParkingZone]) -> None:
        self._zones: dict[str, ParkingZone] = {zone.zone_id: zone for zone in zones}

    @classmethod
    def from_file(cls, path: Path) -> "ZoneRegistry":
        """구역 정의 JSON 파일을 읽어 레지스트리를 만든다."""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise BaselineError(f"구역 정의 파일을 읽을 수 없습니다({path}): {exc}") from exc
        except json.JSONDecodeError as exc:
            raise BaselineError(f"구역 정의 JSON 형식이 올바르지 않습니다({path}): {exc}") from exc
        zones = [cls._parse_zone(item) for item in payload.get("zones", [])]
        if not zones:
            raise BaselineError(f"구역 정의가 비어 있습니다: {path}")
        return cls(zones)

    @staticmethod
    def _parse_zone(item: Mapping[str, Any]) -> ParkingZone:
        try:
            zone_id = str(item["zone_id"])
            zone_type = ZoneType(item["zone_type"])
            points = tuple((float(x), float(y)) for x, y in item["polygon"])
        except (KeyError, ValueError, TypeError) as exc:
            raise BaselineError(f"구역 정의 항목이 올바르지 않습니다: {item!r} ({exc})") from exc
        return ParkingZone(zone_id=zone_id, zone_type=zone_type, polygon=NormalizedPolygon(points))

    def all(self) -> tuple[ParkingZone, ...]:
        """등록된 모든 구역을 반환한다."""

        return tuple(self._zones.values())

    def get(self, zone_id: str) -> ParkingZone:
        """구역 ID로 구역 정의를 조회한다."""

        return self._zones[zone_id]


@dataclass(frozen=True)
class ZoneOverlap:
    """구역 하나와 차량 바운딩박스 간 겹침 비율."""

    zone: ParkingZone
    ratio: float


def classify_zone_overlaps(
    bbox: BoundingBox,
    zones: Sequence[ParkingZone],
    *,
    min_overlap_ratio: float,
) -> list[ZoneOverlap]:
    """겹침 비율이 임계값 이상인 구역만 비율 내림차순으로 반환한다."""

    overlaps = [
        ZoneOverlap(zone, overlap_ratio(zone.polygon, bbox))
        for zone in zones
        if zone.zone_type not in IGNORED_ZONE_TYPES_FOR_PARKING
    ]
    overlaps = [item for item in overlaps if item.ratio >= min_overlap_ratio]
    overlaps.sort(key=lambda item: -item.ratio)
    return overlaps


def classify_violation(
    overlaps: Sequence[ZoneOverlap],
    *,
    dwell_seconds: float,
    min_dwell_seconds: float,
    blocked_vehicle_overlap_ratio: float | None = None,
) -> tuple[ViolationStatus, ParkingZone | None, float]:
    """§5.1 규칙으로 겹침 구역·다른 차량과의 겹침·정차 시간을 종합해 위반 상태를 판정한다.

    여러 조건이 동시에 걸리면 통행 방해(AISLE_BLOCK) > 이중주차(DOUBLE_PARK) >
    전용구역 점유(RESTRICTED_ZONE) > 선 침범(LINE_CROSS) 순으로 하나만 보고한다.
    `blocked_vehicle_overlap_ratio`는 이미 정차 중인 다른 차량과 40% 이상
    겹칠 때(§5.1) 그 비율을 전달받는다 — 어떤 차량이 다른 차량을 막고
    있는지는 이 함수가 아니라 호출부(ViolationMonitor)가 정차 시작 시각을
    비교해 결정한다(나중에 자리 잡은 차만 가해자로 판정).
    """

    if not overlaps and blocked_vehicle_overlap_ratio is None:
        return ViolationStatus.NONE, None, 0.0

    aisle = next((item for item in overlaps if item.zone.zone_type is ZoneType.AISLE), None)
    restricted = next((item for item in overlaps if item.zone.zone_type in RESTRICTED_ZONE_TYPES), None)

    if dwell_seconds < min_dwell_seconds:
        # 정차는 감지됐지만 최소 정차 시간(FR-PARK-008, 확정치 10분)에 미달
        candidate = aisle or restricted or (overlaps[0] if overlaps else None)
        if candidate is not None:
            return ViolationStatus.OBSERVING, candidate.zone, candidate.ratio
        return ViolationStatus.OBSERVING, None, blocked_vehicle_overlap_ratio or 0.0
    if aisle is not None:
        return ViolationStatus.AISLE_BLOCK, aisle.zone, aisle.ratio
    if blocked_vehicle_overlap_ratio is not None:
        return ViolationStatus.DOUBLE_PARK, None, blocked_vehicle_overlap_ratio
    if restricted is not None:
        return ViolationStatus.RESTRICTED_ZONE, restricted.zone, restricted.ratio
    if len(overlaps) >= 2:
        # 일반 구역 2곳 이상에 임계값 이상 걸쳐 있음 = 선 침범
        return ViolationStatus.LINE_CROSS, overlaps[0].zone, overlaps[0].ratio
    if overlaps:
        return ViolationStatus.NONE, overlaps[0].zone, overlaps[0].ratio
    return ViolationStatus.NONE, None, 0.0


@dataclass(frozen=True)
class CapturedFrame:
    """촬영 순번, 시각, RGB uint8 이미지로 구성된 카메라 프레임."""

    frame_id: int
    captured_at: datetime
    image: Any


@dataclass(frozen=True)
class VehicleBox:
    """한 프레임에서 트래커가 반환한 차량 하나의 위치."""

    track_id: int
    bbox: BoundingBox
    confidence: float
    frame_id: int
    captured_at: datetime


@dataclass
class TrackState:
    """트랙별 정차 상태를 프레임 간 유지하는 누적 상태 (가변)."""

    track_id: int
    last_bbox: BoundingBox
    last_seen_at: datetime
    stationary_since: datetime
    plate_number: str | None = None
    open_violation: ViolationStatus = ViolationStatus.NONE


@dataclass(frozen=True)
class ModelInfo:
    """결과 재현을 위해 기록하는 트래킹 라이브러리와 모델 정보."""

    library: str
    library_version: str
    model_name: str
    tracker_config: str


@dataclass(frozen=True)
class ViolationEvent:
    """서버로 발행할 위반(의심) 이벤트 한 건. 최종 확정은 관리자 몫이다(OR-001/002)."""

    track_id: int
    plate_number: str | None
    status: ViolationStatus
    zone_id: str | None
    zone_type: ZoneType | None
    overlap_ratio: float
    dwell_seconds: float
    detected_at: datetime


def to_jsonable(value: Any) -> Any:
    """결과 데이터 모델을 외부 객체 없이 JSON 직렬화 가능한 값으로 바꾼다."""

    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: to_jsonable(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


class FrameSource(Protocol):
    """프레임 공급자의 초기화, 촬영, 해제 생명주기 계약."""

    def open(self) -> None:
        """프레임 공급자를 한 번 초기화한다."""

    def capture(self) -> CapturedFrame:
        """RGB uint8 프레임 한 장을 촬영한다."""

    def close(self) -> None:
        """프레임 공급자의 자원을 해제한다."""


class VehicleTracker(Protocol):
    """전체 프레임에서 차량을 탐지하고 track_id를 부여하는 계약."""

    @property
    def model_info(self) -> ModelInfo:
        """현재 설정 또는 초기화된 모델 정보를 반환한다."""

    def open(self) -> None:
        """탐지·트래킹 모델을 애플리케이션 시작 시 한 번 초기화한다."""

    def track(self, frame: CapturedFrame) -> list[VehicleBox]:
        """프레임 한 장에서 차량 목록(track_id 포함)을 반환한다."""

    def close(self) -> None:
        """모델이 점유한 참조를 해제한다."""


class ResultPublisher(Protocol):
    """위반 이벤트를 출력하거나 외부로 전달하는 계약."""

    def publish(self, event: ViolationEvent) -> None:
        """위반 이벤트 한 건을 발행한다."""


def _centroid_distance(a: BoundingBox, b: BoundingBox) -> float:
    ax, ay = a.center()
    bx, by = b.center()
    return math.hypot(ax - bx, ay - by)


class ViolationMonitor:
    """트랙별 정차 시간과 구역 겹침을 누적해 신규 위반 이벤트만 골라낸다.

    동일 차량의 동일 사건은 종료(이동)될 때까지 하나로 통합한다(FR-PARK-010).
    새로 나타난 트랙은 첫 프레임부터 정차 중인 것으로 간주하는 단순화를
    적용했다. 실제로는 진입 직후 잠깐의 움직임을 무시해야 할 수 있으니
    현장 데이터로 검증 후 조정이 필요하다.
    """

    def __init__(
        self,
        zones: ZoneRegistry,
        *,
        min_overlap_ratio: float = 0.40,
        min_dwell_seconds: float = 600.0,
        movement_epsilon: float = 0.01,
    ) -> None:
        self._zones = zones
        self._min_overlap_ratio = min_overlap_ratio
        self._min_dwell_seconds = min_dwell_seconds
        self._movement_epsilon = movement_epsilon
        self._tracks: dict[int, TrackState] = {}

    def attach_plate(self, track_id: int, plate_number: str) -> None:
        """§2.2 입차-트래킹 매칭 결과를 트랙에 연결한다 (실제 매칭 로직은 이 파일 밖에서 구현)."""

        state = self._tracks.get(track_id)
        if state is not None:
            state.plate_number = plate_number

    def update(self, detections: Sequence[VehicleBox]) -> list[ViolationEvent]:
        """한 프레임의 트랙 목록을 반영하고, 새로 발생한 위반 이벤트만 반환한다.

        정차 상태 갱신(1차)과 위반 판정(2차)을 나눠서 처리한다 — 이중주차
        판정이 같은 프레임 안의 다른 차량들 정차 시간을 참조하는데, 갱신
        순서에 따라 결과가 달라지지 않도록 모든 트랙의 정차 상태를 먼저
        확정한 뒤에 판정한다.
        """

        events: list[ViolationEvent] = []
        seen_ids: set[int] = set()

        for detection in detections:
            seen_ids.add(detection.track_id)
            state = self._tracks.get(detection.track_id)
            if state is None:
                state = TrackState(
                    track_id=detection.track_id,
                    last_bbox=detection.bbox,
                    last_seen_at=detection.captured_at,
                    stationary_since=detection.captured_at,
                )
                self._tracks[detection.track_id] = state
            else:
                # state.last_bbox는 "정차 시작 시점의 위치" 기준점으로 유지한다.
                # 매 프레임 갱신하면 프레임 간 이동량이 매번 movement_epsilon 이하일 때
                # 누적 이동거리가 커도 계속 "정지 상태"로 남는 문제가 생긴다(리뷰 반영).
                moved = _centroid_distance(state.last_bbox, detection.bbox) > self._movement_epsilon
                if moved:
                    state.stationary_since = detection.captured_at
                    state.last_bbox = detection.bbox
                    state.open_violation = ViolationStatus.NONE
                state.last_seen_at = detection.captured_at

        for detection in detections:
            state = self._tracks[detection.track_id]
            dwell_seconds = (detection.captured_at - state.stationary_since).total_seconds()

            blocked_ratio: float | None = None
            for other in detections:
                if other.track_id == detection.track_id:
                    continue
                other_state = self._tracks[other.track_id]
                # 나중에 정차한 차량만 "이중주차 중"으로 판정한다 — 먼저 자리
                # 잡은 차는 피해자이지 가해자가 아니다.
                if other_state.stationary_since >= state.stationary_since:
                    continue
                other_dwell = (detection.captured_at - other_state.stationary_since).total_seconds()
                if other_dwell < self._min_dwell_seconds:
                    continue
                ratio = overlap_ratio(_bbox_to_polygon(other.bbox), detection.bbox)
                if ratio >= self._min_overlap_ratio and (blocked_ratio is None or ratio > blocked_ratio):
                    blocked_ratio = ratio

            overlaps = classify_zone_overlaps(
                detection.bbox, self._zones.all(), min_overlap_ratio=self._min_overlap_ratio
            )
            status, zone, ratio = classify_violation(
                overlaps,
                dwell_seconds=dwell_seconds,
                min_dwell_seconds=self._min_dwell_seconds,
                blocked_vehicle_overlap_ratio=blocked_ratio,
            )

            if status not in (ViolationStatus.NONE, ViolationStatus.OBSERVING) and status != state.open_violation:
                events.append(
                    ViolationEvent(
                        track_id=detection.track_id,
                        plate_number=state.plate_number,
                        status=status,
                        zone_id=zone.zone_id if zone else None,
                        zone_type=zone.zone_type if zone else None,
                        overlap_ratio=ratio,
                        dwell_seconds=dwell_seconds,
                        detected_at=detection.captured_at,
                    )
                )
            if status != ViolationStatus.OBSERVING:
                state.open_violation = status

        # 이번 프레임에 보이지 않는 트랙은 화면 밖으로 나간 것으로 보고 상태를 정리한다.
        for missing_id in set(self._tracks) - seen_ids:
            del self._tracks[missing_id]

        return events


def _import_cv2() -> Any:
    try:
        import cv2
    except ImportError as exc:
        raise BaselineError(
            f"OpenCV import에 실패했습니다. `pip install opencv-python`으로 설치하세요. 원인: {exc}"
        ) from exc
    return cv2


class OpenCvWebcamFrameSource:
    """일반 웹캠(데모 단계의 천장 카메라)에서 RGB 프레임을 공급한다."""

    def __init__(self, *, camera_index: int, width: int, height: int) -> None:
        self._camera_index = camera_index
        self._width = width
        self._height = height
        self._capture: Any | None = None
        self._next_frame_id = 1

    def open(self) -> None:
        """OpenCV VideoCapture를 연다."""

        if self._capture is not None:
            return
        cv2 = _import_cv2()
        capture = cv2.VideoCapture(self._camera_index)
        if self._width:
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        if self._height:
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        if not capture.isOpened():
            capture.release()
            raise BaselineError(f"웹캠 {self._camera_index}를 열 수 없습니다.")
        self._capture = capture

    def capture(self) -> CapturedFrame:
        """BGR로 읽은 프레임을 RGB로 변환해 반환한다."""

        if self._capture is None:
            raise BaselineError("웹캠이 초기화되지 않았습니다.")
        cv2 = _import_cv2()
        ok, frame_bgr = self._capture.read()
        if not ok or frame_bgr is None:
            raise BaselineError("웹캠 프레임 캡처에 실패했습니다.")
        image = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame = CapturedFrame(frame_id=self._next_frame_id, captured_at=datetime.now(timezone.utc), image=image)
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        """웹캠 장치를 해제한다."""

        capture, self._capture = self._capture, None
        if capture is not None:
            capture.release()


class UltralyticsVehicleTracker:
    """Ultralytics YOLO + ByteTrack 결과를 정규화 VehicleBox로 변환하는 어댑터.

    실제 Jetson 배치 시에는 `model_path`를 TensorRT `.engine` 가중치로,
    파인튜닝이 끝나면 `ai/training/configs/yolo_vehicle.yaml`로 학습한
    가중치로 교체한다.
    """

    def __init__(self, *, model_path: str, tracker_config: str, confidence: float) -> None:
        self._model_path = model_path
        self._tracker_config = tracker_config
        self._confidence = confidence
        self._model: Any | None = None
        self._library_version = "not-initialized"

    @property
    def model_info(self) -> ModelInfo:
        """현재 Ultralytics 설정과 확인된 라이브러리 버전을 반환한다."""

        return ModelInfo(
            library="ultralytics",
            library_version=self._library_version,
            model_name=self._model_path,
            tracker_config=self._tracker_config,
        )

    def open(self) -> None:
        """YOLO 모델을 한 번만 로드한다."""

        if self._model is not None:
            return
        try:
            import ultralytics
            from ultralytics import YOLO
        except ImportError as exc:
            missing = getattr(exc, "name", None) or "ultralytics"
            raise BaselineError(
                f"트래킹 의존성 '{missing}' import에 실패했습니다. `pip install ultralytics`로 설치하세요. 원인: {exc}"
            ) from exc
        self._library_version = getattr(ultralytics, "__version__", "unknown")
        try:
            self._model = YOLO(self._model_path)
        except Exception as exc:
            raise BaselineError(f"YOLO 모델 로드에 실패했습니다(model={self._model_path}): {exc}") from exc

    def track(self, frame: CapturedFrame) -> list[VehicleBox]:
        """YOLO 탐지 + ByteTrack 결과를 정규화 좌표의 VehicleBox 목록으로 변환한다."""

        if self._model is None:
            raise BaselineError("트래커가 초기화되지 않았습니다.")
        shape = getattr(frame.image, "shape", None)
        if shape is None or len(shape) < 2:
            raise BaselineError("프레임 이미지 크기를 확인할 수 없습니다.")
        image_height, image_width = int(shape[0]), int(shape[1])
        if image_height <= 0 or image_width <= 0:
            # 카메라가 순간적으로 빈 프레임을 반환하는 경우(리뷰 반영) 나눗셈 전에 걸러낸다.
            raise BaselineError(f"프레임 크기가 올바르지 않습니다: shape={shape}")
        try:
            results = self._model.track(
                source=frame.image,
                persist=True,
                tracker=self._tracker_config,
                conf=self._confidence,
                verbose=False,
            )
        except Exception as exc:
            raise BaselineError(f"YOLO/ByteTrack 추론에 실패했습니다: {exc}") from exc

        boxes: list[VehicleBox] = []
        if not results:
            return boxes
        result_boxes = getattr(results[0], "boxes", None)
        if result_boxes is None or result_boxes.id is None:
            return boxes
        xyxy = result_boxes.xyxy.tolist()
        track_ids = result_boxes.id.tolist()
        confidences = result_boxes.conf.tolist()
        for (x1, y1, x2, y2), track_id, confidence in zip(xyxy, track_ids, confidences):
            nx1 = max(0.0, min(1.0, x1 / image_width))
            ny1 = max(0.0, min(1.0, y1 / image_height))
            nx2 = max(0.0, min(1.0, x2 / image_width))
            ny2 = max(0.0, min(1.0, y2 / image_height))
            if nx2 <= nx1 or ny2 <= ny1:
                continue
            boxes.append(
                VehicleBox(
                    track_id=int(track_id),
                    bbox=BoundingBox(x1=nx1, y1=ny1, x2=nx2, y2=ny2),
                    confidence=float(confidence),
                    frame_id=frame.frame_id,
                    captured_at=frame.captured_at,
                )
            )
        return boxes

    def close(self) -> None:
        """모델 참조를 해제한다."""

        self._model = None


class StdoutResultPublisher:
    """서버 MQTT 발행(edge/{deviceId}/detection)으로 교체되기 전까지 표준출력에 발행한다."""

    def __init__(self, *, plain: bool) -> None:
        self._plain = plain

    def publish(self, event: ViolationEvent) -> None:
        """plain 모드는 한 줄 요약, 기본은 JSON으로 출력한다."""

        if self._plain:
            zone = event.zone_id or "-"
            plate = event.plate_number or "UNKNOWN"
            print(f"{event.status.value} track={event.track_id} zone={zone} plate={plate}", flush=True)
            return
        print(json.dumps(to_jsonable(event), ensure_ascii=False, sort_keys=True), flush=True)


def save_rgb_image(path: Path, image: Any) -> None:
    """RGB 배열을 OpenCV가 기대하는 BGR로 변환하여 이미지 파일로 저장한다."""

    cv2 = _import_cv2()
    bgr_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    if not cv2.imwrite(str(path), bgr_image):
        raise BaselineError(f"이미지 저장에 실패했습니다: {path}")


def build_parser() -> argparse.ArgumentParser:
    """베이스라인 실행 모드와 카메라·트래킹·판정 설정 CLI를 정의한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--probe-camera", action="store_true", help="웹캠 연결과 한 프레임 촬영을 점검합니다.")
    modes.add_argument("--capture-frame", metavar="PATH", help="구역 폴리곤 캘리브레이션용 전체 프레임을 저장합니다.")
    modes.add_argument("--run", action="store_true", help="탐지+트래킹+위반 판정 루프를 실행합니다(Ctrl+C로 종료).")
    modes.add_argument("--self-test", action="store_true", help="하드웨어·모델 없이 순수 판정 로직만 테스트합니다.")

    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--zones-file", type=Path, default=None, help="ParkingZone 목록 JSON (--run에 필수).")
    parser.add_argument("--model-path", default="yolov8n.pt")
    parser.add_argument("--tracker-config", default="bytetrack.yaml")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--min-overlap-ratio", type=float, default=0.40, help="주차선 침범 판정 임계값(§5.1 확정치).")
    parser.add_argument("--min-dwell-seconds", type=float, default=600.0, help="위반 후보 등록 전 최소 정차 시간(§5.1 확정치, FR-PARK-008).")
    parser.add_argument("--movement-epsilon", type=float, default=0.01, help="정차 판정을 위한 중심 이동 허용 오차(정규화 단위).")
    parser.add_argument("--frame-interval-ms", type=int, default=200)
    parser.add_argument("--plain", action="store_true")
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    """실행 전에 수치 범위와 모드별 필수 옵션을 검증한다."""

    if args.width <= 0 or args.height <= 0:
        raise BaselineError("width와 height는 0보다 커야 합니다.")
    if args.camera_index < 0:
        raise BaselineError("camera-index는 음수일 수 없습니다.")
    if not (0.0 <= args.min_overlap_ratio <= 1.0):
        raise BaselineError("min-overlap-ratio는 0~1 범위여야 합니다.")
    if args.min_dwell_seconds < 0:
        raise BaselineError("min-dwell-seconds는 0 이상이어야 합니다.")
    if args.movement_epsilon < 0:
        raise BaselineError("movement-epsilon은 0 이상이어야 합니다.")
    if args.frame_interval_ms < 0:
        raise BaselineError("frame-interval-ms는 0 이상이어야 합니다.")
    if args.run:
        if args.zones_file is None:
            raise BaselineError("--run에는 --zones-file이 필요합니다.")
        if not args.zones_file.is_file():
            raise BaselineError(f"zones-file을 찾을 수 없습니다: {args.zones_file}")


def probe_camera(args: argparse.Namespace) -> dict[str, Any]:
    """모델 없이 웹캠 초기화와 한 프레임 촬영만 점검한다."""

    source = OpenCvWebcamFrameSource(camera_index=args.camera_index, width=args.width, height=args.height)
    source.open()
    try:
        frame = source.capture()
    finally:
        source.close()
    return {
        "status": "SUCCESS",
        "camera_index": args.camera_index,
        "frame_shape": list(frame.image.shape),
        "frame_dtype": str(frame.image.dtype),
        "captured_at": frame.captured_at.isoformat(),
    }


def capture_calibration_frame(args: argparse.Namespace, path: Path) -> dict[str, Any]:
    """모델 없이 전체 웹캠 프레임을 지정한 경로에 저장한다(구역 폴리곤 좌표 산출용)."""

    source = OpenCvWebcamFrameSource(camera_index=args.camera_index, width=args.width, height=args.height)
    source.open()
    try:
        frame = source.capture()
        save_rgb_image(path, frame.image)
    finally:
        source.close()
    return {
        "status": "SUCCESS",
        "path": str(path),
        "frame_shape": list(frame.image.shape),
        "captured_at": frame.captured_at.isoformat(),
    }


def run_monitor(args: argparse.Namespace) -> int:
    """웹캠 → 트래커 → 위반 판정 → 발행까지 이어지는 실시간 루프를 실행한다."""

    zones = ZoneRegistry.from_file(args.zones_file)
    frame_source = OpenCvWebcamFrameSource(camera_index=args.camera_index, width=args.width, height=args.height)
    tracker = UltralyticsVehicleTracker(
        model_path=args.model_path, tracker_config=args.tracker_config, confidence=args.confidence
    )
    monitor = ViolationMonitor(
        zones,
        min_overlap_ratio=args.min_overlap_ratio,
        min_dwell_seconds=args.min_dwell_seconds,
        movement_epsilon=args.movement_epsilon,
    )
    publisher = StdoutResultPublisher(plain=args.plain)

    frame_source.open()
    try:
        tracker.open()
        try:
            LOGGER.info("모니터링을 시작합니다. Ctrl+C로 종료하세요.")
            while True:
                frame = frame_source.capture()
                detections = tracker.track(frame)
                for event in monitor.update(detections):
                    publisher.publish(event)
                if args.frame_interval_ms:
                    time.sleep(args.frame_interval_ms / 1000.0)
        finally:
            tracker.close()
    finally:
        frame_source.close()
    return 0


class _FakeImage:
    """테스트에서 프레임 크기만 흉내 내는 최소 이미지 스텁."""

    def __init__(self, shape: tuple[int, ...]) -> None:
        self.shape = shape


class BaselineLogicTests(unittest.TestCase):
    """카메라·모델 없이 실행하는 순수 판정 로직 회귀 테스트."""

    @staticmethod
    def make_zone(zone_id: str, zone_type: ZoneType, points: Sequence[tuple[float, float]]) -> ParkingZone:
        return ParkingZone(zone_id=zone_id, zone_type=zone_type, polygon=NormalizedPolygon(tuple(points)))

    def test_polygon_area_of_square(self) -> None:
        polygon = NormalizedPolygon(((0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)))
        self.assertAlmostEqual(_polygon_area(polygon.points), 0.04)

    def test_overlap_ratio_full_containment(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.2, 0.2, 0.4, 0.4)
        self.assertAlmostEqual(overlap_ratio(zone.polygon, bbox), 1.0)

    def test_overlap_ratio_no_overlap(self) -> None:
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)])
        bbox = BoundingBox(0.5, 0.5, 0.7, 0.7)
        self.assertEqual(overlap_ratio(zone.polygon, bbox), 0.0)

    def test_overlap_ratio_half_overlap(self) -> None:
        zone = self.make_zone("GEN-02", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)])
        bbox = BoundingBox(0.1, 0.0, 0.3, 0.2)
        self.assertAlmostEqual(overlap_ratio(zone.polygon, bbox), 0.5)

    def test_restricted_zone_flagged_after_min_dwell(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.RESTRICTED_ZONE)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_id, "DIS-01")

    def test_observing_before_min_dwell(self) -> None:
        zone = self.make_zone("EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=100.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)

    def test_line_cross_across_two_general_zones(self) -> None:
        gen1 = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        gen2 = self.make_zone("GEN-02", ZoneType.GENERAL, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.3), (0.2, 0.3)])
        bbox = BoundingBox(0.1, 0.0, 0.3, 0.3)
        overlaps = classify_zone_overlaps(bbox, [gen1, gen2], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.LINE_CROSS)

    def test_aisle_block_takes_priority_over_restricted_zone(self) -> None:
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        disabled = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.2, 0.2, 0.5, 0.5)
        overlaps = classify_zone_overlaps(bbox, [aisle, disabled], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_id, "AISLE-01")

    def test_double_park_priority_between_aisle_and_restricted(self) -> None:
        # 통행로 겹침이 있으면 이중주차보다 AISLE_BLOCK이 우선한다.
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        overlaps = classify_zone_overlaps(BoundingBox(0.2, 0.2, 0.5, 0.5), [aisle], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_vehicle_overlap_ratio=0.9
        )
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)

        # 전용구역 겹침만 있으면 이중주차가 그보다 우선한다(막힌 차량이 실존 피해자이므로).
        disabled = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        overlaps = classify_zone_overlaps(BoundingBox(0.2, 0.2, 0.5, 0.5), [disabled], min_overlap_ratio=0.40)
        status, _zone, ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_vehicle_overlap_ratio=0.9
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)
        self.assertAlmostEqual(ratio, 0.9)

        # 구역 겹침이 전혀 없어도 다른 차량과 겹치면 이중주차로 판정한다.
        status, zone, ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_vehicle_overlap_ratio=0.6
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)
        self.assertIsNone(zone)
        self.assertAlmostEqual(ratio, 0.6)

        # 최소 정차 시간 미달이면 겹침이 있어도 아직 OBSERVING이다.
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=10.0, min_dwell_seconds=600.0, blocked_vehicle_overlap_ratio=0.6
        )
        self.assertEqual(status, ViolationStatus.OBSERVING)

    def test_monitor_double_park_flags_later_arrival_not_earlier_car(self) -> None:
        registry = ZoneRegistry([])  # 구역을 아예 없애서 순수하게 이중주차 판정만 검증한다.
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, movement_epsilon=0.01)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        car_b_bbox = BoundingBox(0.10, 0.10, 0.30, 0.30)
        car_a_bbox = BoundingBox(0.15, 0.10, 0.35, 0.30)  # car_b와 크게 겹침

        events_t0 = monitor.update(
            [VehicleBox(track_id=1, bbox=car_b_bbox, confidence=0.9, frame_id=1, captured_at=base_time)]
        )

        events_t6 = monitor.update(
            [
                VehicleBox(track_id=1, bbox=car_b_bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=6)),
                VehicleBox(track_id=2, bbox=car_a_bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=6)),
            ]
        )

        events_t12 = monitor.update(
            [
                VehicleBox(track_id=1, bbox=car_b_bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=12)),
                VehicleBox(track_id=2, bbox=car_a_bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=12)),
            ]
        )

        self.assertEqual(len(events_t0), 0)
        self.assertEqual(len(events_t6), 0)  # car_a는 방금 도착해 아직 OBSERVING
        self.assertEqual(len(events_t12), 1)
        self.assertEqual(events_t12[0].track_id, 2)  # 나중에 온 car_a만 이중주차로 판정
        self.assertEqual(events_t12[0].status, ViolationStatus.DOUBLE_PARK)

    def test_entry_exit_zone_ignored_for_parking_violation(self) -> None:
        entry = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.2, 0.2, 0.5, 0.5)
        overlaps = classify_zone_overlaps(bbox, [entry], min_overlap_ratio=0.40)
        self.assertEqual(overlaps, [])

    def test_monitor_emits_violation_once_then_suppresses_duplicates(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        first = VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)
        second = VehicleBox(
            track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=2)
        )
        third = VehicleBox(
            track_id=1, bbox=bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=4)
        )

        events_first = monitor.update([first])
        events_second = monitor.update([second])
        events_third = monitor.update([third])

        self.assertEqual(len(events_first), 0)  # 최소 정차 시간(1초) 미달로 아직 OBSERVING
        self.assertEqual(len(events_second), 1)
        self.assertEqual(events_second[0].status, ViolationStatus.RESTRICTED_ZONE)
        self.assertEqual(len(events_third), 0)  # 같은 위반이 계속 열려 있으므로 중복 발행하지 않음

    def test_slow_continuous_drift_never_reaches_min_dwell(self) -> None:
        """리뷰 반영: 매 프레임 이동량이 movement_epsilon 이하라도 누적 이동거리가 크면
        정지 상태로 오판하면 안 된다 (기존에는 last_bbox를 매 프레임 갱신해 이 문제가 있었음)."""

        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, movement_epsilon=0.01)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        events: list[ViolationEvent] = []
        for index, x1 in enumerate((0.100, 0.106, 0.112, 0.118)):
            detection = VehicleBox(
                track_id=1,
                bbox=BoundingBox(x1, 0.1, x1 + 0.2, 0.3),
                confidence=0.9,
                frame_id=index + 1,
                captured_at=base_time + timedelta(seconds=2 * index),
            )
            events.extend(monitor.update([detection]))

        self.assertEqual(len(events), 0)  # 계속 조금씩 움직이는 차량은 위반으로 확정되면 안 됨

    def test_tracker_rejects_zero_sized_frame(self) -> None:
        """리뷰 반영: 카메라가 순간적으로 빈 프레임을 반환하면 ZeroDivisionError 대신
        BaselineError로 처리되어야 한다."""

        tracker = UltralyticsVehicleTracker(model_path="unused.pt", tracker_config="bytetrack.yaml", confidence=0.5)
        tracker._model = object()  # open() 없이 track()의 프레임 크기 검증만 확인
        frame = CapturedFrame(frame_id=1, captured_at=datetime.now(timezone.utc), image=_FakeImage((0, 0, 3)))
        with self.assertRaises(BaselineError):
            tracker.track(frame)

    def test_monitor_attach_plate_updates_track_state(self) -> None:
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=600.0)
        bbox = BoundingBox(0.1, 0.1, 0.2, 0.2)
        monitor.update(
            [VehicleBox(track_id=5, bbox=bbox, confidence=0.9, frame_id=1, captured_at=datetime.now(timezone.utc))]
        )
        monitor.attach_plate(5, "1234")
        self.assertEqual(monitor._tracks[5].plate_number, "1234")

    def test_zone_registry_from_file_parses_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zone_id": "GEN-01",
                                "zone_type": "GENERAL",
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = ZoneRegistry.from_file(path)
        self.assertEqual(registry.get("GEN-01").zone_type, ZoneType.GENERAL)

    def test_zone_registry_from_file_rejects_empty_zones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(json.dumps({"zones": []}), encoding="utf-8")
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)


def run_self_tests() -> int:
    """선택 의존성을 불러오지 않고 내장 unittest 모음을 실행한다."""

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BaselineLogicTests)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    summary = {
        "status": "SUCCESS" if result.wasSuccessful() else "FAILED",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    return 0 if result.wasSuccessful() else 1


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 모드를 선택하고 최상위 오류를 구조화된 결과로 변환한다."""

    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.self_test:
        return run_self_tests()

    try:
        validate_args(args)
        if args.probe_camera:
            print(json.dumps(probe_camera(args), ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        if args.capture_frame is not None:
            output = capture_calibration_frame(args, Path(args.capture_frame))
            print(json.dumps(output, ensure_ascii=False, sort_keys=True), flush=True)
            return 0
        return run_monitor(args)
    except BaselineError as exc:
        LOGGER.exception("실행에 실패했습니다: %s", exc)
        print(json.dumps({"status": "ERROR", "message": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 2
    except KeyboardInterrupt:
        LOGGER.info("사용자 요청으로 종료합니다.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

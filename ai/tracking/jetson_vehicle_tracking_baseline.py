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
- 입차 게이트 OCR과의 트랙 매칭(§2.2)은 초안으로 구현했다
  (`ViolationMonitor.add_entry_event` + ENTRY_EXIT 구역 진입 시 FIFO
  매칭). 실제 entryEvent 필드 형식·시간창·공간 조건은 게이트 OCR 팀과
  확정이 필요하다.
- 장애인/전기차 구역의 "등록 차량 여부" 서버 조회: 여기서는 구역을
  점유했다는 사실만 `RESTRICTED_ZONE`으로 표시하고, 실제 인증 여부 판단은
  서버 몫으로 남겨둔다(조회 실패 시 안전 우선 정책으로 위반 의심 유지).
- DOUBLE_PARK/LINE_CROSS 판정에서, 어떤 스팟에 아직 아무도 정착
  완료(min_dwell_seconds)하지 못한 동안은 그 스팟에 대한 침범 판정을
  보류한다(리뷰 반영: 정착 확정 전에 LINE_CROSS로 잘못 보고됐다가
  DOUBLE_PARK로 다시 보고되는 이벤트 중복을 막기 위함). 그런데 트래킹
  노이즈로 어떤 차량이 movement_epsilon을 계속 넘나들어 정차 시간이
  누적되지 않으면, 그 스팟은 계속 "미확정" 상태로 남아 침범 판정 자체가
  무기한 보류될 수 있다 — 현장 데이터로 실제 발생 빈도를 확인하고, 필요하면
  "N초 이상 미확정이면 미점유로 간주" 같은 타임아웃을 추가해야 할 수 있다.
- OUT_OF_ZONE(리뷰 반영, 317번 MR 코드리뷰 I-1/I-2/I-4) 관련, 알려진 한계:
  · AISLE(통행로) 폴리곤은 보통 길고 얇게 그려지는데, OUT_OF_ZONE의
    "구역 없음" 판단이 몸체 겹침 40%(min_overlap_ratio) 기준이라, 통행로
    입구를 앞머리로만 살짝 막은 흔한 통행 방해 상황은 몸체 겹침이 40%에
    못 미쳐 AISLE_BLOCK 대신 OUT_OF_ZONE으로 잘못 분류될 수 있다. AISLE도
    구역 면적 기준(zone_coverage_ratio) 판정을 도입하는 게 정석이나 이번
    MR 범위에서는 보류했다.
  · 관리자가 카메라 화면 전체를 폴리곤으로 덮을 의무는 없으므로(§5.0),
    인접 도로·주차장 밖 노면처럼 "감시 영역이지만 등록 안 된 곳"에 있는
    차량도 전부 OUT_OF_ZONE으로 잡힌다. 다른 위반들은 폴리곤 겹침이
    있어야 발동해 미등록 구역에서는 미탐(안전) 쪽으로 기우는데, 이
    판정만 반대로 오탐(위험) 쪽으로 기운다. 주차장 외곽 경계 폴리곤
    도입이나 CLI 온/오프 플래그로 파일럿 기간 리스크를 낮추는 방안이
    필요하다(팀 확인 필요).
  · `min_dwell_seconds=0`이면 이동 중인 차량도 프레임마다 즉시
    OUT_OF_ZONE이 확정되고, 이동 감지 시 상태가 리셋되어 매 프레임
    이벤트가 발행될 수 있다(다른 위반 판정도 동일한 구조적 한계를
    공유하나, OUT_OF_ZONE은 대상 면적이 훨씬 넓어 영향이 커진다).
  · (N-1 수정 후에도 남는 것, N-2) 게이트에 앞머리만 걸친 차량(예:
    entry_zone_min_overlap_ratio 기준 몸겹침 25%)은 여전히 OUT_OF_ZONE으로
    발행된다 — I-1(AISLE 부분겹침)과 같은 뿌리 원인(몸체 겹침 임계값
    미달)이다. 게이트는 차가 정당하게 오래 서 있을 수 있는 유일한
    장소라, 파일럿에서 `--min-dwell-seconds`를 낮추면 체감 빈도가 올라갈
    수 있다.
  · (N-3) 피해 차량이 흔들려 정착(min_dwell_seconds)이 풀렸다가 다시
    정착하면, 같은 물리적 상황에 대해 DOUBLE_PARK가 두 번 발행될 수
    있다 — 이건 이번 MR이 만든 게 아니라, `pending_home_zone_ids` 보류
    메커니즘이 막으려던 "이벤트만 바뀌며 중복 발행"의 잔여 형태다. 후속
    정리가 필요하다.

CLI 모드: 웹캠 점검(`--probe-camera`), 캘리브레이션용 프레임 저장
(`--capture-frame`), 실시간 루프(`--run`), 하드웨어 비의존 자체 테스트
(`--self-test`).

배포 시 주의: 이 스크립트는 단독 실행 파일이 아니다. 같은 디렉터리의
`calibration_utils.py`(왜곡 보정 파라미터 로딩)와 `camera_calibration.json`을
함께 복사해야 `--calibration`이 동작한다. remap 관련 테스트는 이 파일의
`--self-test`가 아니라 `ai/training/tests/`(pytest)에 있다 — cv2/numpy가 필요해
"하드웨어·의존성 없이 도는 자체 테스트"라는 `--self-test`의 성격과 맞지 않기 때문.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
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

# 왜곡 보정 시 crop(0)~풀 화각 유지(1) 비율. 학습 데이터를 만든 extract_pilot_frames.py와
# 반드시 같은 값이어야 한다 — 다르면 같은 K/D로도 다른 좌표계가 나온다.
DEFAULT_REMAP_BALANCE = 0.5


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
    OUT_OF_ZONE = "OUT_OF_ZONE"


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


def zone_coverage_ratio(zone: ParkingZone, bbox: BoundingBox) -> float:
    """차량 바운딩박스가 구역 폴리곤 면적의 몇 %를 덮고 있는지(구역 기준) 계산한다.

    `overlap_ratio`(차체 기준)와 반대로 분모가 구역 자신의 면적이라, 차량 크기와
    무관하게 "이 구역이 얼마나 침범당했는지"를 일관되게 잴 수 있다(이중주차 판정용).
    """

    zone_area = _polygon_area(zone.polygon.points)
    if zone_area <= 0.0:
        return 0.0
    clipped = clip_polygon_to_bbox(zone.polygon.points, bbox)
    return _polygon_area(clipped) / zone_area


@dataclass(frozen=True)
class ParkingZone:
    """설치 시 1회 캘리브레이션으로 등록되는 주차구역 정의 (§5.0).

    zone_id는 백엔드가 발급하는 기계 식별자이고, zone_number는 사람이 읽는
    구역 번호다(구역 계약 스펙 결정 4). 서버로 나가는 페이로드는 zone_id를,
    로그·오버레이는 zone_number를 쓴다.
    """

    zone_id: int
    zone_number: str
    zone_type: ZoneType
    polygon: NormalizedPolygon


class ZoneRegistry:
    """구역 정의 목록을 보관한다. 스키마는 백엔드 `/internal/zones`와 동일하게 맞춘다."""

    def __init__(self, zones: Sequence[ParkingZone]) -> None:
        self._zones: dict[int, ParkingZone] = {zone.zone_id: zone for zone in zones}

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
            zone_id = int(item["zoneId"])
            zone_number = str(item["zoneNumber"])
            zone_type = ZoneType(item["zoneType"])
            points = tuple((float(x), float(y)) for x, y in item["polygon"])
        except (KeyError, ValueError, TypeError) as exc:
            raise BaselineError(f"구역 정의 항목이 올바르지 않습니다: {item!r} ({exc})") from exc
        return ParkingZone(
            zone_id=zone_id,
            zone_number=zone_number,
            zone_type=zone_type,
            polygon=NormalizedPolygon(points),
        )

    def all(self) -> tuple[ParkingZone, ...]:
        """등록된 모든 구역을 반환한다."""

        return tuple(self._zones.values())

    def get(self, zone_id: int) -> ParkingZone:
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


# 이중주차 판정에서 "내 자리"로 볼 수 있는 구역 타입. 통행로(AISLE)는 주차
# 스팟이 아니므로 홈 구역 후보에서 제외한다(AISLE_BLOCK이 별도로 처리).
_SPOT_ZONE_TYPES = frozenset({ZoneType.GENERAL, ZoneType.DISABLED, ZoneType.EV_FAST, ZoneType.EV_SLOW})


def _home_zone_overlap(overlaps: Sequence[ZoneOverlap]) -> ZoneOverlap | None:
    """겹치는 구역들 중 차량의 '홈 구역'으로 볼 수 있는 스팟형 구역을 고른다.

    `overlaps`는 이미 비율 내림차순으로 정렬돼 있다고 가정한다
    (`classify_zone_overlaps`의 반환값). AISLE 같은 비-스팟 구역이 더 높은
    비율로 앞에 있어도 건너뛰고 스팟형 구역 중 가장 비율이 높은 것을 고른다.
    """

    for item in overlaps:
        if item.zone.zone_type in _SPOT_ZONE_TYPES:
            return item
    return None


def _ignored_zone_overlap(
    bbox: BoundingBox, zones: Sequence[ParkingZone], *, min_overlap_ratio: float
) -> ZoneOverlap | None:
    """차량이 판정 제외 구역(§IGNORED_ZONE_TYPES_FOR_PARKING, 예: ENTRY_EXIT)에
    min_overlap_ratio 이상 겹치는지 확인한다(리뷰 반영, C-1).

    `classify_zone_overlaps`는 이 구역들을 애초에 후보에서 제외하므로, 그
    결과만으로는 "판정 제외 구역 안에 있다"와 "정말 아무 구역도 없다"를
    구분할 수 없다. OUT_OF_ZONE 판정이 게이트에서 대기 중인 차량까지
    "구역 외 주차"로 오인하지 않으려면 이 구분이 반드시 필요하다.
    """

    best: ZoneOverlap | None = None
    for zone in zones:
        if zone.zone_type not in IGNORED_ZONE_TYPES_FOR_PARKING:
            continue
        ratio = overlap_ratio(zone.polygon, bbox)
        if ratio >= min_overlap_ratio and (best is None or ratio > best.ratio):
            best = ZoneOverlap(zone, ratio)
    return best


def classify_violation(
    overlaps: Sequence[ZoneOverlap],
    *,
    dwell_seconds: float,
    min_dwell_seconds: float,
    blocked_zone: ZoneOverlap | None = None,
    intruded_zone: ZoneOverlap | None = None,
    in_ignored_zone: bool = False,
    deferred_intrusion: bool = False,
) -> tuple[ViolationStatus, ParkingZone | None, float]:
    """§5.1 규칙으로 겹침 구역·스팟 침범·정차 시간을 종합해 위반 상태를 판정한다.

    여러 조건이 동시에 걸리면 통행 방해(AISLE_BLOCK) > 이중주차(DOUBLE_PARK) >
    전용구역 점유(RESTRICTED_ZONE) > 선 침범(LINE_CROSS) > 구역 외 주차
    (OUT_OF_ZONE) 순으로 하나만 보고한다. OUT_OF_ZONE은 다른 어떤 위반 신호도
    없을 때만 성립하는 배타적 폴백이며(우선순위표가 아니라 아래 early-return의
    배타 조건), 새 위반 신호를 추가하면 그 조건도 함께 확장해야 한다.

    `blocked_zone`/`intruded_zone`은 둘 다 "내 홈 구역이 아닌 스팟을 얼마나
    덮었는가"라는 같은 계산(구역 면적 기준, `zone_coverage_ratio`)에서 나오며,
    그 구역에 이미 정착한 다른 차가 있으면 `blocked_zone`(DOUBLE_PARK), 없으면
    `intruded_zone`(LINE_CROSS)으로 나뉜다 — 어떤 차량이 어느 구역의 진짜
    주인인지는 이 함수가 아니라 호출부(ViolationMonitor)가 구역별 최고
    점유자 정보로 결정한다(시간순이 아니라 공간 정보 기준).

    `in_ignored_zone`/`deferred_intrusion`(리뷰 반영, C-1/C-2): `overlaps`가
    비어 있는 이유는 최소 세 가지로 서로 다르다 — ① 정말 어느 구역과도
    안 겹침(OUT_OF_ZONE 대상), ② ENTRY_EXIT 같은 판정 제외 구역 안에 있음
    (`in_ignored_zone`), ③ 다른 트랙이 아직 정착 확정 못 해 해당 구역이
    `pending_home_zone_ids`로 보류 중이라 이번 프레임엔 침범 여부를 알 수
    없음(`deferred_intrusion`). ②·③은 "구역 없음"이 아니라 "판정 보류"이므로
    OUT_OF_ZONE으로 확정하면 안 되고, 기존과 동일하게 NONE으로 둔다.

    참고: 이제 DOUBLE_PARK가 구역 면적 기준으로 넓게 잡히다 보니, 전용구역
    (RESTRICTED_ZONE)에 주차된 차가 동시에 남의 스팟을 침범한 경우 이
    우선순위 때문에 RESTRICTED_ZONE 대신 DOUBLE_PARK로 보고된다. 옛 방식
    (차체 접촉 필요)에서는 드물었지만 이제는 흔해졌으니, 이 우선순위가
    여전히 의도한 동작인지 팀 확인이 필요하다.
    """

    if not overlaps and blocked_zone is None and intruded_zone is None:
        if in_ignored_zone or deferred_intrusion:
            # 판정 제외 구역(게이트 등) 안에 있거나, 다른 트랙의 정착 미확정으로
            # 이번 프레임엔 침범 여부를 알 수 없다 — "구역 없음"이 아니므로
            # OUT_OF_ZONE으로 확정하지 않고 기존과 동일하게 NONE으로 둔다.
            return ViolationStatus.NONE, None, 0.0
        # 어떤 구역(통행로 포함)에도 겹치지 않고 스팟 침범도, 판정 제외/보류
        # 대상도 아니다 — 등록된 주차구역 밖에 서 있다는 뜻이다. 최소 정차
        # 시간을 채우기 전에는 다른 위반들과 동일하게 OBSERVING으로만 표시한다.
        if dwell_seconds < min_dwell_seconds:
            return ViolationStatus.OBSERVING, None, 0.0
        return ViolationStatus.OUT_OF_ZONE, None, 0.0

    aisle = next((item for item in overlaps if item.zone.zone_type is ZoneType.AISLE), None)
    restricted = next((item for item in overlaps if item.zone.zone_type in RESTRICTED_ZONE_TYPES), None)

    if dwell_seconds < min_dwell_seconds:
        # 정차는 감지됐지만 최소 정차 시간(FR-PARK-008, 확정치 10분)에 미달
        candidate = aisle or restricted or (overlaps[0] if overlaps else None)
        if candidate is not None:
            return ViolationStatus.OBSERVING, candidate.zone, candidate.ratio
        if blocked_zone is not None:
            return ViolationStatus.OBSERVING, blocked_zone.zone, blocked_zone.ratio
        if intruded_zone is not None:
            return ViolationStatus.OBSERVING, intruded_zone.zone, intruded_zone.ratio
        return ViolationStatus.OBSERVING, None, 0.0
    if aisle is not None:
        return ViolationStatus.AISLE_BLOCK, aisle.zone, aisle.ratio
    if blocked_zone is not None:
        return ViolationStatus.DOUBLE_PARK, blocked_zone.zone, blocked_zone.ratio
    if restricted is not None:
        return ViolationStatus.RESTRICTED_ZONE, restricted.zone, restricted.ratio
    if intruded_zone is not None:
        return ViolationStatus.LINE_CROSS, intruded_zone.zone, intruded_zone.ratio
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
class TrackSnapshot:
    """오버레이·디버깅용 트랙 상태 스냅샷 (읽기 전용).

    plate_number를 담지 않는다 — 리플레이 검증에는 게이트 OCR 입차 이벤트를
    공급하는 경로가 없어 항상 None이다.
    """

    track_id: int
    dwell_seconds: float
    open_violation: ViolationStatus


@dataclass(frozen=True)
class ModelInfo:
    """결과 재현을 위해 기록하는 트래킹 라이브러리와 모델 정보."""

    library: str
    library_version: str
    model_name: str
    tracker_config: str


@dataclass(frozen=True)
class ViolationEvent:
    """서버로 발행할 위반(의심) 이벤트 한 건. 최종 확정은 관리자 몫이다(OR-001/002).

    status가 DOUBLE_PARK/LINE_CROSS인 경우 zone_id/zone_type은 이 차량이
    "자기 홈 구역이 아닌데 침범한" 스팟을 가리키며(DOUBLE_PARK는 그 스팟에
    이미 다른 차가 정착해 있는 경우, LINE_CROSS는 비어있는 경우),
    overlap_ratio도 그 구역 면적 대비 침범 비율(구역 기준)이다. AISLE_BLOCK/
    RESTRICTED_ZONE에서는 zone_id가 이 차량 자신이 있는 구역을 가리키고
    overlap_ratio도 이 차량 자신의 몸체 면적 기준(차체 기준)이라 의미가 다르다.
    OUT_OF_ZONE(리뷰 반영)은 애초에 매핑되는 구역이 없으므로 zone_id/
    zone_type은 항상 None이고 overlap_ratio도 항상 0.0으로 발행된다. zone_number도
    마찬가지로 None이 된다.
    """

    track_id: int
    plate_number: str | None
    status: ViolationStatus
    zone_id: int | None
    zone_number: str | None
    zone_type: ZoneType | None
    overlap_ratio: float
    dwell_seconds: float
    detected_at: datetime


@dataclass(frozen=True)
class EntryEvent:
    """게이트 OCR이 인식한 입차 이벤트(§2.2). 실제 필드 형식은 OCR 팀과 확정 필요."""

    plate_number: str
    captured_at: datetime


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

    트랙이 한두 프레임 잠깐 안 보였다가 같은 track_id로 복귀하면
    `track_grace_seconds` 이내에서는 상태(정차 시작 시각 등)를 그대로
    유지한다 — 매 프레임 최소 하나의 탐지가 있어야 경과 시간을 계산할 수
    있어, 프레임이 통째로 비는 동안에는 유예 판정이 지연될 수 있다.

    통행로를 막는 "일반적인 이중주차"(차 여러 대의 진출입로를 막는 경우)는
    AISLE_BLOCK이 담당한다(구역 폴리곤만 있으면 판정 가능). DOUBLE_PARK와
    LINE_CROSS는 둘 다 "내가 진짜 주인이 아닌 스팟 구역을 얼마나 침범했는가"
    라는 같은 계산(`zone_coverage_ratio`, 구역 자기 면적 기준)에서 갈라진다.
    매 프레임 "각 스팟의 진짜 주인"(그 구역에 몸 겹침 비율이 가장 높고
    §5.1 최소 정차 시간을 채운 차)을 먼저 정하고, 어떤 차가 자기 소유가
    아닌 스팟을 `spot_intrusion_ratio` 이상 덮으면: 그 스팟에 이미 진짜
    주인이 있으면 DOUBLE_PARK(그 주인이 피해자), 비어있으면 LINE_CROSS로
    판정한다. 판정은 시간순(누가 먼저 왔는지)이 아니라 순수하게 공간
    정보(누가 그 구역의 더 정당한 주인인지)로만 한다. 이 방식은 피해
    차량이 스팟 구역(zone) 안에 있어야 동작한다.

    등록된 구역 어디에도 매핑되지 않는 차량은 `classify_violation`이
    최소 정차 시간 이후 OUT_OF_ZONE으로 별도 판정한다(리뷰 반영 - 인용 정정:
    요구사항 정의서.md:25 주차 상태 분류, ERD.md:119-125 event_type과 대응).
    다만 "구역 밖에 정차한 차량을 다른
    차가 막는" 복합 상황까지는 다루지 않는다 — 그 경우 피해 차량은
    독립적으로 OUT_OF_ZONE만 보고되고, 막은 차량 쪽에서 별도 판정이
    나오지 않는 한 "누가 누구를 막았는지"는 연결되지 않는다.

    §2.2 입차-트래킹 매칭(초안): `add_entry_event`로 게이트 OCR 이벤트를
    받아두면, ENTRY_EXIT 구역 안에 있고 아직 plate_number가 없는 트랙에
    시간창 내 가장 오래된(촬영 시각 기준) 이벤트를 매 프레임 재시도로
    연결한다(`attach_plate` 직접 호출도 여전히 가능). 트랙 생성 시점
    한 번만 시도하지 않는 이유(리뷰 반영): OCR 이벤트가 늦게 도착하거나
    첫 프레임의 구역 겹침이 임계값에 못 미치는 경우가 드물지 않아서다.
    실제 entryEvent 필드 형식·시간창·공간 조건은 게이트 OCR 팀과 맞춰서
    조정이 필요한 초안이다. 매칭에 끝내 실패한 트랙은 plate_number가
    None으로 남고, 그 상태로 위반이 발생하면 ViolationEvent.plate_number도
    None으로 발행된다 — 서버가 이를 UNREGISTERED와 구분되는
    PLATE_UNMATCHED로 처리한다(§2.2).

    알려진 한계(리뷰 반영, 아직 미해결): 같은 프레임에 여러 차량이 동시에
    새로 나타나면 `detections` 순서가 실제 물리적 입차 순서와 다를 수
    있어 번호판이 뒤바뀔 위험이 있다. 파일럿에서 동시 입차 빈도를 보고
    공간적 근접도까지 반영할지 결정해야 한다.
    """

    def __init__(
        self,
        zones: ZoneRegistry,
        *,
        min_overlap_ratio: float = 0.40,
        min_dwell_seconds: float = 600.0,
        movement_epsilon: float = 0.01,
        track_grace_seconds: float = 2.0,
        spot_intrusion_ratio: float = 0.15,
        # 이 0.15는 예전 두 임계값(구역 판정용 min_overlap_ratio=0.40,
        # 옛 차량 대 차량 지표에서 물려받은 spot_intrusion_ratio=0.15)을
        # 하나로 합치면서 후자 값을 그대로 가져온 임시값이다 — 아직 현장
        # 데이터로 재검증되지 않았다.
        entry_match_window_seconds: float = 10.0,
        entry_zone_min_overlap_ratio: float = 0.40,
    ) -> None:
        self._zones = zones
        self._min_overlap_ratio = min_overlap_ratio
        self._min_dwell_seconds = min_dwell_seconds
        self._movement_epsilon = movement_epsilon
        self._track_grace_seconds = track_grace_seconds
        self._spot_intrusion_ratio = spot_intrusion_ratio
        self._entry_match_window_seconds = entry_match_window_seconds
        self._entry_zone_min_overlap_ratio = entry_zone_min_overlap_ratio
        self._tracks: dict[int, TrackState] = {}
        self._pending_entry_events: list[EntryEvent] = []

    def attach_plate(self, track_id: int, plate_number: str) -> None:
        """트랙에 직접 번호판을 연결한다 (자동 매칭 없이 수동으로 붙일 때 사용)."""

        state = self._tracks.get(track_id)
        if state is not None:
            state.plate_number = plate_number

    def add_entry_event(self, event: EntryEvent) -> None:
        """§2.2 게이트 OCR의 입차 이벤트를 매칭 대기열에 추가한다."""

        self._pending_entry_events.append(event)

    def _prune_expired_entry_events(self, now: datetime) -> None:
        """시간창을 넘긴 대기 이벤트를 버린다. 매칭 시도 여부와 무관하게 매 update()마다 호출한다.

        (리뷰 반영) 예전에는 `_try_match_entry_event`가 호출될 때만 정리했는데,
        그 구역 근처로 신규 트랙이 한동안 안 생기면 오래된 미매칭 이벤트가
        대기열에 무한정 쌓이는 문제가 있었다(§264 트랙 상태와 같은 종류의 누수).
        """

        self._pending_entry_events = [
            event
            for event in self._pending_entry_events
            if (now - event.captured_at).total_seconds() <= self._entry_match_window_seconds
        ]

    def _try_match_entry_event(self, detection: VehicleBox) -> None:
        """ENTRY_EXIT 구역 안에 있는 미매칭 트랙에 대기 이벤트를 시간순으로 매칭한다.

        (리뷰 반영) 트랙이 처음 생성되는 프레임에서만 시도하면, OCR 이벤트가
        늦게 도착하거나 첫 프레임의 구역 겹침이 임계값에 못 미치는 흔한
        경우에 영구히 매칭이 안 되는 문제가 있었다. 그래서 이제
        `plate_number`가 아직 없는 트랙이면 매 프레임 재시도한다.
        """

        entry_zones = [zone for zone in self._zones.all() if zone.zone_type is ZoneType.ENTRY_EXIT]
        if not entry_zones:
            return
        near_entrance = any(
            overlap_ratio(zone.polygon, detection.bbox) >= self._entry_zone_min_overlap_ratio
            for zone in entry_zones
        )
        if not near_entrance:
            return

        now = detection.captured_at
        # (리뷰 반영) 삽입 순서가 아니라 실제 촬영 시각(captured_at) 순으로 골라야
        # add_entry_event 호출 순서가 실제 입차 순서와 어긋나도(비동기 처리 등)
        # "가장 먼저 들어온" 이벤트가 정확히 매칭된다.
        eligible = sorted(
            (event for event in self._pending_entry_events if event.captured_at <= now),
            key=lambda event: event.captured_at,
        )
        if not eligible:
            return
        matched = eligible[0]
        self._pending_entry_events.remove(matched)
        self._tracks[detection.track_id].plate_number = matched.plate_number

    def track_snapshot(self, now: datetime) -> dict[int, TrackSnapshot]:
        """현재 트랙별 정차 상태를 읽기 전용으로 반환한다. 판정에 영향을 주지 않는다.

        update()는 중복 억제 때문에 "새로 발생한" 이벤트만 반환하므로, 매 프레임
        "이 차가 몇 초 정차했고 지금 어떤 상태인가"를 그리려면 누적 상태가 필요하다.
        오버레이가 이를 재계산하면 화면에 보이는 값과 실제 판정이 갈라질 수 있어,
        검증 도구가 검증 대상과 다른 답을 내게 된다.

        dwell 계산식은 update()가 dwell_by_track을 채울 때 쓰는 것과 같아야 한다.
        """

        return {
            track_id: TrackSnapshot(
                track_id=track_id,
                dwell_seconds=(now - state.stationary_since).total_seconds(),
                open_violation=state.open_violation,
            )
            for track_id, state in self._tracks.items()
        }

    def update(self, detections: Sequence[VehicleBox]) -> list[ViolationEvent]:
        """한 프레임의 트랙 목록을 반영하고, 새로 발생한 위반 이벤트만 반환한다.

        정차 상태 갱신(1차) → 구역 겹침·홈 구역·구역별 최고 점유자 계산(2차)
        → 위반 판정(3차) 순으로 나눠서 처리한다. DOUBLE_PARK/LINE_CROSS
        판정이 같은 프레임 안의 다른 차량들이 점유한 구역을 참조하는데,
        갱신/계산 순서에 따라 결과가 달라지지 않도록 모든 트랙의 정차
        상태와 구역 정보를 먼저 확정한 뒤에 판정한다.
        """

        events: list[ViolationEvent] = []
        seen_ids: set[int] = set()

        if detections:
            self._prune_expired_entry_events(max(detection.captured_at for detection in detections))

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

        zone_overlaps_by_track: dict[int, list[ZoneOverlap]] = {}
        home_zone_by_track: dict[int, ZoneOverlap | None] = {}
        dwell_by_track: dict[int, float] = {}
        ignored_overlap_by_track: dict[int, ZoneOverlap | None] = {}
        for detection in detections:
            state = self._tracks[detection.track_id]
            if state.plate_number is None:
                # (리뷰 반영) 신규 트랙 생성 시점에만 시도하면 늦게 도착한
                # OCR 이벤트나 첫 프레임의 낮은 구역 겹침 때문에 영구 미매칭이
                # 되는 경우가 있어서, 매칭 전까지는 매 프레임 재시도한다.
                self._try_match_entry_event(detection)

            overlaps = classify_zone_overlaps(
                detection.bbox, self._zones.all(), min_overlap_ratio=self._min_overlap_ratio
            )
            zone_overlaps_by_track[detection.track_id] = overlaps
            home_zone_by_track[detection.track_id] = _home_zone_overlap(overlaps)
            ignored_overlap_by_track[detection.track_id] = _ignored_zone_overlap(
                # (리뷰 반영, N-1) "게이트 안에 있다"는 같은 기하학적 질문을 §2.2
                # 입차매칭(_try_match_entry_event)도 판단하는데, 거기는
                # entry_zone_min_overlap_ratio를 쓴다. 여기서 min_overlap_ratio(0.40,
                # 스팟 판정용)를 쓰면 --entry-zone-min-overlap-ratio를 낮췄을 때
                # "입차매칭은 게이트로 인정 + OUT_OF_ZONE은 게이트 아님"이라는
                # 모순된 판정이 같은 프레임에 나온다 — 같은 질문에는 같은 임계값을 써야 한다.
                detection.bbox, self._zones.all(), min_overlap_ratio=self._entry_zone_min_overlap_ratio
            )
            state = self._tracks[detection.track_id]
            dwell_by_track[detection.track_id] = (detection.captured_at - state.stationary_since).total_seconds()

        # 각 스팟 구역의 "진짜 주인" — 그 구역을 홈으로 삼고 최소 정차 시간을
        # 채운 트랙 중, 몸 겹침 비율이 가장 높은 트랙. 같은 구역을 두 트랙이
        # 공유(경계선 타이 등)하면 비율이 더 높은 쪽만 주인으로 인정한다.
        best_claimant_by_zone_id: dict[int, tuple[int, float]] = {}
        for track_id, home in home_zone_by_track.items():
            if home is None or dwell_by_track[track_id] < self._min_dwell_seconds:
                continue
            current_best = best_claimant_by_zone_id.get(home.zone.zone_id)
            if current_best is None or home.ratio > current_best[1]:
                best_claimant_by_zone_id[home.zone.zone_id] = (track_id, home.ratio)

        # 누군가의 홈으로 걸려 있지만 아직 아무도 정착 완료하지 못한 구역 —
        # 비어있는 건지 곧 누군가의 스팟이 될 건지 이번 프레임엔 알 수 없다.
        # 이런 구역을 침범 판정에 넣으면, 나중에 그 차가 정착하는 순간
        # LINE_CROSS로 한 번 보고됐다가 DOUBLE_PARK로 다시 보고되는 식으로
        # 같은 상황이 이벤트만 바뀌며 중복 발행된다(리뷰 반영) — 그래서
        # 판정을 보류하고 침범 후보에서 제외한다. 트래킹 노이즈로 정착이
        # 계속 안 되면 이 보류가 여러 프레임에 걸쳐(이론상 무기한) 이어질 수
        # 있다는 트레이드오프가 있다 — 모듈 docstring의 한계 목록 참고.
        pending_home_zone_ids: set[int] = {
            home.zone.zone_id
            for home in home_zone_by_track.values()
            if home is not None and home.zone.zone_id not in best_claimant_by_zone_id
        }

        for detection in detections:
            state = self._tracks[detection.track_id]
            dwell_seconds = dwell_by_track[detection.track_id]
            own_home = home_zone_by_track[detection.track_id]
            own_claim = best_claimant_by_zone_id.get(own_home.zone.zone_id) if own_home is not None else None
            own_zone_id_if_rightful = (
                own_home.zone.zone_id if own_claim is not None and own_claim[0] == detection.track_id else None
            )

            blocked_zone: ZoneOverlap | None = None
            intruded_zone: ZoneOverlap | None = None
            deferred_intrusion = False
            for zone in self._zones.all():
                if zone.zone_type not in _SPOT_ZONE_TYPES or zone.zone_id == own_zone_id_if_rightful:
                    continue  # 통행로/입출차 구역이거나, 내가 정당한 주인인 내 홈 구역이면 침범이 아니다
                if zone.zone_id in pending_home_zone_ids:
                    # 점유 여부가 아직 불확실한 구역은 이번 프레임엔 판정 보류.
                    # 다만 보류 중인 구역을 이미 침범 기준(spot_intrusion_ratio)
                    # 이상 덮고 있다면(리뷰 반영, C-2), 그건 "구역 없음"이 아니라
                    # "판정 보류"이므로 OUT_OF_ZONE으로 확정되면 안 된다는 신호를
                    # classify_violation에 넘겨야 한다.
                    if zone_coverage_ratio(zone, detection.bbox) >= self._spot_intrusion_ratio:
                        deferred_intrusion = True
                    continue
                intrusion_ratio = zone_coverage_ratio(zone, detection.bbox)
                if intrusion_ratio < self._spot_intrusion_ratio:
                    continue
                claimant = best_claimant_by_zone_id.get(zone.zone_id)
                if claimant is not None and claimant[0] != detection.track_id:
                    if blocked_zone is None or intrusion_ratio > blocked_zone.ratio:
                        blocked_zone = ZoneOverlap(zone, intrusion_ratio)
                else:
                    if intruded_zone is None or intrusion_ratio > intruded_zone.ratio:
                        intruded_zone = ZoneOverlap(zone, intrusion_ratio)

            overlaps = zone_overlaps_by_track[detection.track_id]
            status, zone, ratio = classify_violation(
                overlaps,
                dwell_seconds=dwell_seconds,
                min_dwell_seconds=self._min_dwell_seconds,
                blocked_zone=blocked_zone,
                intruded_zone=intruded_zone,
                in_ignored_zone=ignored_overlap_by_track[detection.track_id] is not None,
                deferred_intrusion=deferred_intrusion,
            )

            if status not in (ViolationStatus.NONE, ViolationStatus.OBSERVING) and status != state.open_violation:
                events.append(
                    ViolationEvent(
                        track_id=detection.track_id,
                        plate_number=state.plate_number,
                        status=status,
                        zone_id=zone.zone_id if zone else None,
                        zone_number=zone.zone_number if zone else None,
                        zone_type=zone.zone_type if zone else None,
                        overlap_ratio=ratio,
                        dwell_seconds=dwell_seconds,
                        detected_at=detection.captured_at,
                    )
                )
            if status != ViolationStatus.OBSERVING:
                state.open_violation = status

        # 이번 프레임에 안 보인 트랙은 track_grace_seconds를 넘겨야 삭제한다.
        # "지금 시각"은 이번 프레임에 실제로 탐지된 차량의 시각으로만 알 수
        # 있어서, detections가 완전히 비어 있는 프레임에서는 정리를 건너뛴다.
        if detections:
            now = max(detection.captured_at for detection in detections)
            stale_ids = [
                track_id
                for track_id, state in self._tracks.items()
                if track_id not in seen_ids
                and (now - state.last_seen_at).total_seconds() > self._track_grace_seconds
            ]
            for track_id in stale_ids:
                del self._tracks[track_id]

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


def calibration_fingerprint(calibration_path: Path | None, balance: float) -> dict[str, Any]:
    """zone 폴리곤이 어떤 보정 좌표계에서 찍혔는지 식별하는 지문.

    remap은 1080p/balance 0.5에서 픽셀을 평균 44px, 최대 133px 옮긴다. 보정 없이 찍은
    구 zone 파일을 `--calibration`과 함께 쓰면 아무 에러 없이 폴리곤이 그만큼 어긋나
    위반 판정이 전부 틀어지므로, 캡처 시점의 설정을 기록해두고 실행 시 비교한다.
    """

    if calibration_path is None:
        return {"remap": False}
    try:
        digest = hashlib.sha256(calibration_path.read_bytes()).hexdigest()[:16]
    except OSError as exc:
        raise BaselineError(f"calibration 파일을 읽을 수 없습니다({calibration_path}): {exc}") from exc
    return {"remap": True, "calibrationSha256": digest, "balance": round(float(balance), 6)}


def normalize_fingerprint(raw: Mapping[str, Any]) -> dict[str, Any]:
    """서버·캐시·사이드카에서 온 지문을 비교 가능한 정규형으로 바꾼다.

    dict를 통째로 비교하면 두 군데서 깨진다(구역 계약 스펙 §7.2). remap=False일 때
    이 파일은 {"remap": False} 한 키만 만들지만 서버는 나머지를 null로 채워 보내고,
    balance는 MySQL DECIMAL(8,6)을 거치며 0.5가 0.500000으로 돌아온다. 둘 다
    정상 상황인데 불일치로 판정되면 기동이 거부된다.
    """

    if not bool(raw.get("remap", False)):
        return {"remap": False}
    try:
        return {
            "remap": True,
            "calibrationSha256": str(raw["calibrationSha256"]).lower(),
            "balance": round(float(raw["balance"]), 6),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise BaselineError(f"calibration 지문 형식이 올바르지 않습니다: {raw!r} ({exc})") from exc


def _import_calibration_utils() -> Any:
    try:
        import calibration_utils
    except ImportError as exc:
        raise BaselineError(
            f"calibration_utils import에 실패했습니다(ai/tracking/calibration_utils.py 확인). 원인: {exc}"
        ) from exc
    return calibration_utils


class RemapFrameSource:
    """다른 FrameSource가 공급하는 프레임에 fisheye remap(왜곡 보정)을 씌운다.

    `ai/tracking/calibrate_camera.py`(#301)로 계산한 캘리브레이션 값을 실시간
    캡처 루프에 적용하는 역할이다. 학습 데이터도 `extract_pilot_frames.py`
    (#313)로 동일하게 remap 보정된 프레임을 썼으므로, 추론 시에도 같은 보정을
    거치지 않으면 모델이 학습 때 본 적 없는 원본(왜곡) 화면을 받게 된다.

    보정 맵은 첫 프레임의 실제 크기를 확인한 뒤 한 번만 계산해 재사용한다
    (캘리브레이션 사진 해상도와 카메라 해상도가 다르면 자동으로 스케일링). 스트림
    중간에 해상도가 바뀌면(USB 재연결·v4l2 재협상) 캐시된 맵이 조용히 잘못된 좌표를
    만들기 때문에 — cv2.remap은 크기가 달라도 예외를 던지지 않고 원본 맵 크기의
    이미지를 반환한다 — 매 프레임 크기를 확인하고 달라지면 맵을 다시 만든다.
    """

    def __init__(self, *, inner: Any, calibration_path: str, balance: float = DEFAULT_REMAP_BALANCE) -> None:
        self._inner = inner
        self._calibration_path = calibration_path
        self._balance = balance
        self._map1: Any | None = None
        self._map2: Any | None = None
        self._map_size: tuple[int, int] | None = None
        self._dst: Any | None = None

    def open(self) -> None:
        self._inner.open()

    def capture(self) -> CapturedFrame:
        frame = self._inner.capture()
        cv2 = _import_cv2()
        frame_size = self._frame_size(frame.image)
        if self._map1 is None or frame_size != self._map_size:
            if self._map_size is not None:
                LOGGER.warning(
                    "프레임 해상도가 %s에서 %s로 바뀌어 보정 맵을 다시 만듭니다.", self._map_size, frame_size
                )
            self._map1, self._map2 = self._build_maps(frame_size, cv2)
            self._map_size = frame_size
            self._dst = None
        # dst 버퍼를 재사용해 프레임당 수 MB 할당을 없앤다(측정상 30% 이상 빠름).
        undistorted = cv2.remap(
            frame.image,
            self._map1,
            self._map2,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            dst=self._dst,
        )
        self._dst = undistorted
        return CapturedFrame(frame_id=frame.frame_id, captured_at=frame.captured_at, image=undistorted)

    @staticmethod
    def _frame_size(image: Any) -> tuple[int, int]:
        """(width, height)를 돌려주되, 보정 맵을 만들 수 없는 프레임은 미리 걸러낸다.

        하류 트래커에도 같은 가드가 있지만(빈 프레임에서 ZeroDivisionError 방지),
        remap은 그보다 상류라 여기서 막지 않으면 cv2.remap이 생짜 cv2.error를 던진다.
        """

        shape = getattr(image, "shape", None)
        if shape is None or len(shape) < 2:
            raise BaselineError("프레임 이미지 크기를 확인할 수 없습니다.")
        height, width = int(shape[0]), int(shape[1])
        if height <= 0 or width <= 0:
            raise BaselineError(f"프레임 크기가 올바르지 않아 왜곡 보정을 할 수 없습니다: shape={shape}")
        return width, height

    def _build_maps(self, frame_size: tuple[int, int], cv2: Any) -> tuple[Any, Any]:
        calibration_utils = _import_calibration_utils()
        import numpy as np

        try:
            K_cal, D, cal_size = calibration_utils.load_calibration(self._calibration_path)
            K = calibration_utils.scale_K(K_cal, cal_size, frame_size)
        except calibration_utils.CalibrationError as exc:
            raise BaselineError(str(exc)) from exc
        if cal_size != frame_size:
            LOGGER.info("캘리브레이션 해상도 %s를 프레임 해상도 %s로 스케일링했습니다.", cal_size, frame_size)
        new_K = cv2.fisheye.estimateNewCameraMatrixForUndistortRectify(
            K, D, frame_size, np.eye(3), balance=self._balance
        )
        return cv2.fisheye.initUndistortRectifyMap(K, D, np.eye(3), new_K, frame_size, cv2.CV_16SC2)

    def close(self) -> None:
        # 맵/버퍼는 1080p에서 12~22MB라, 재연결 루프가 추가될 경우를 대비해 여기서 놓아준다.
        self._map1 = None
        self._map2 = None
        self._map_size = None
        self._dst = None
        self._inner.close()


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
        cv2 = _import_cv2()
        # CapturedFrame.image는 RGB인데 Ultralytics는 ndarray source를 BGR로 해석한다
        # (ultralytics/data/loaders.py: "NumPy color inputs are assumed to use
        # OpenCV-compatible BGR order"). 학습 데이터는 cv2.imwrite로 BGR 저장 → BGR로
        # 로드되므로, 여기서 되돌리지 않으면 R/B가 뒤바뀐 입력으로 추론하게 된다.
        source_bgr = cv2.cvtColor(frame.image, cv2.COLOR_RGB2BGR)
        try:
            results = self._model.track(
                source=source_bgr,
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
            zone = event.zone_number or "-"
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
    parser.add_argument(
        "--calibration",
        type=Path,
        default=None,
        help="camera_calibration.json 경로. 캡처된 프레임에 fisheye remap 보정을 적용한다(#323). --run에는 필수.",
    )
    parser.add_argument(
        "--remap-balance",
        type=float,
        default=DEFAULT_REMAP_BALANCE,
        help="remap 시 crop(0)~풀 화각 유지(1) 비율. 학습 데이터 생성 시 쓴 값과 같아야 한다.",
    )
    parser.add_argument("--model-path", default="yolov8n.pt")
    parser.add_argument("--tracker-config", default="bytetrack.yaml")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--min-overlap-ratio", type=float, default=0.40, help="주차선 침범 판정 임계값(§5.1 확정치).")
    parser.add_argument("--spot-intrusion-ratio", type=float, default=0.15, help="스팟 침범 판정 임계값 — 자기 홈 구역이 아닌 주차구역을 이 비율 이상 덮으면 위반(그 구역에 이미 정착한 차가 있으면 DOUBLE_PARK, 없으면 LINE_CROSS). 구역 겹침 임계값보다 낮게 잡음, 현장 데이터로 재검증 필요.")
    parser.add_argument("--min-dwell-seconds", type=float, default=600.0, help="위반 후보 등록 전 최소 정차 시간(§5.1 확정치, FR-PARK-008).")
    parser.add_argument("--movement-epsilon", type=float, default=0.01, help="정차 판정을 위한 중심 이동 허용 오차(정규화 단위).")
    parser.add_argument("--track-grace-seconds", type=float, default=2.0, help="트랙이 잠깐 안 보여도 상태를 유지하는 유예 시간.")
    parser.add_argument("--entry-match-window-seconds", type=float, default=10.0, help="게이트 OCR 입차 이벤트와 신규 트랙을 매칭하는 시간창(§2.2).")
    parser.add_argument("--entry-zone-min-overlap-ratio", type=float, default=0.40, help="ENTRY_EXIT 구역 진입 판정 임계값.")
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
    if not (0.0 <= args.spot_intrusion_ratio <= 1.0):
        raise BaselineError("spot-intrusion-ratio는 0~1 범위여야 합니다.")
    if args.min_dwell_seconds < 0:
        raise BaselineError("min-dwell-seconds는 0 이상이어야 합니다.")
    if args.movement_epsilon < 0:
        raise BaselineError("movement-epsilon은 0 이상이어야 합니다.")
    if args.track_grace_seconds < 0:
        raise BaselineError("track-grace-seconds는 0 이상이어야 합니다.")
    if args.entry_match_window_seconds < 0:
        raise BaselineError("entry-match-window-seconds는 0 이상이어야 합니다.")
    if not (0.0 <= args.entry_zone_min_overlap_ratio <= 1.0):
        raise BaselineError("entry-zone-min-overlap-ratio는 0~1 범위여야 합니다.")
    if args.frame_interval_ms < 0:
        raise BaselineError("frame-interval-ms는 0 이상이어야 합니다.")
    if not (0.0 <= args.remap_balance <= 1.0):
        # OpenCV는 범위를 벗어난 balance도 조용히 받아들여 엉뚱한 new_K를 만든다.
        raise BaselineError("remap-balance는 0~1 범위여야 합니다.")
    # 캘리브레이션 파일은 첫 프레임에서야 읽히므로, 여기서 미리 확인하지 않으면 Jetson에서
    # TensorRT 엔진 로딩을 다 기다린 뒤에 경로 오타를 발견하게 된다.
    if args.calibration is not None and not args.calibration.is_file():
        raise BaselineError(f"calibration 파일을 찾을 수 없습니다: {args.calibration}")
    if args.run:
        if args.zones_file is None:
            raise BaselineError("--run에는 --zones-file이 필요합니다.")
        if not args.zones_file.is_file():
            raise BaselineError(f"zones-file을 찾을 수 없습니다: {args.zones_file}")
        if args.calibration is None:
            # 모델은 remap 보정된 프레임으로 학습됐다. 보정 없이 추론하면 조용히 정확도만
            # 떨어져 원인 파악이 어려우므로 실행 자체를 막는다.
            raise BaselineError(
                "--run에는 --calibration이 필요합니다(모델이 remap 보정된 프레임으로 학습됨). "
                "ai/tracking/camera_calibration.json 경로를 지정하세요."
            )


def _build_frame_source(args: argparse.Namespace) -> FrameSource:
    """웹캠 FrameSource를 만들고, `--calibration`이 지정되면 remap 보정을 씌운다.

    zone 폴리곤 캘리브레이션(`--capture-frame`)도 실시간 탐지(`--run`)와 같은
    보정된 좌표계를 봐야 폴리곤과 탐지 bbox가 어긋나지 않으므로, 세 진입점
    (probe/capture-frame/run) 모두 이 헬퍼를 통해 FrameSource를 만든다.
    """

    source: FrameSource = OpenCvWebcamFrameSource(
        camera_index=args.camera_index, width=args.width, height=args.height
    )
    if args.calibration is None:
        # --run은 validate_args에서 이미 막혔으므로, 여기 오는 건 probe/capture-frame뿐이다.
        LOGGER.warning("--calibration이 없어 왜곡 보정 없이 원본 프레임을 사용합니다.")
        return source
    LOGGER.info("왜곡 보정을 적용합니다(calibration=%s, balance=%s).", args.calibration, args.remap_balance)
    return RemapFrameSource(
        inner=source, calibration_path=str(args.calibration), balance=args.remap_balance
    )


def probe_camera(args: argparse.Namespace) -> dict[str, Any]:
    """모델 없이 웹캠 초기화와 한 프레임 촬영만 점검한다."""

    source = _build_frame_source(args)
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

    source = _build_frame_source(args)
    source.open()
    try:
        frame = source.capture()
        save_rgb_image(path, frame.image)
    finally:
        source.close()
    fingerprint = calibration_fingerprint(args.calibration, args.remap_balance)
    # 이 프레임 위에 폴리곤을 찍어 zones.json을 만들 사람이 그대로 복사해 넣도록 남긴다.
    # zones.json의 최상위에 "calibration" 키로 넣으면 --run이 좌표계 일치를 검증한다.
    sidecar = path.with_suffix(path.suffix + ".provenance.json")
    sidecar.write_text(json.dumps({"calibration": fingerprint}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "SUCCESS",
        "path": str(path),
        "provenance_path": str(sidecar),
        "calibration": fingerprint,
        "frame_shape": list(frame.image.shape),
        "captured_at": frame.captured_at.isoformat(),
    }


def verify_zone_calibration(args: argparse.Namespace) -> None:
    """zones 파일이 현재 보정 설정과 같은 좌표계에서 찍혔는지 확인한다.

    `--capture-frame`이 남긴 `calibration` 지문을 zones.json에 복사해둔 경우에만 검증할 수
    있다. 없으면 경고만 하고 통과시킨다(기존 zones 파일과의 호환).
    """

    payload = json.loads(args.zones_file.read_text(encoding="utf-8"))
    recorded = payload.get("calibration")
    expected = calibration_fingerprint(args.calibration, args.remap_balance)
    if recorded is None:
        LOGGER.warning(
            "zones 파일에 calibration 지문이 없어 좌표계 일치를 검증할 수 없습니다(%s). "
            "보정 없이 캡처한 폴리곤이면 최대 130px 어긋날 수 있습니다 — "
            "--capture-frame으로 다시 캡처하고 생성된 provenance를 zones에 복사하세요.",
            args.zones_file,
        )
        return
    if normalize_fingerprint(recorded) != normalize_fingerprint(expected):
        raise BaselineError(
            f"zones 파일의 좌표계가 현재 보정 설정과 다릅니다. zones={recorded}, 현재={expected}. "
            f"같은 --calibration/--remap-balance로 --capture-frame을 다시 실행해 폴리곤을 재작성하세요."
        )


def run_monitor(args: argparse.Namespace) -> int:
    """웹캠 → 트래커 → 위반 판정 → 발행까지 이어지는 실시간 루프를 실행한다."""

    zones = ZoneRegistry.from_file(args.zones_file)
    verify_zone_calibration(args)
    frame_source = _build_frame_source(args)
    tracker = UltralyticsVehicleTracker(
        model_path=args.model_path, tracker_config=args.tracker_config, confidence=args.confidence
    )
    monitor = ViolationMonitor(
        zones,
        min_overlap_ratio=args.min_overlap_ratio,
        min_dwell_seconds=args.min_dwell_seconds,
        movement_epsilon=args.movement_epsilon,
        track_grace_seconds=args.track_grace_seconds,
        spot_intrusion_ratio=args.spot_intrusion_ratio,
        entry_match_window_seconds=args.entry_match_window_seconds,
        entry_zone_min_overlap_ratio=args.entry_zone_min_overlap_ratio,
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

    _ZONE_IDS: dict[str, int] = {}

    @classmethod
    def make_zone(
        cls, zone_number: str, zone_type: ZoneType, points: Sequence[tuple[float, float]]
    ) -> ParkingZone:
        """테스트용 구역 하나. zone_id는 zone_number당 하나로 안정적으로 발급한다.

        같은 zone_number면 항상 같은 zone_id가 나와야 한다 — 테스트가 여러
        레지스트리를 만들어도 구역 동일성이 유지되어야 하기 때문이다.
        """

        zone_id = cls._ZONE_IDS.setdefault(zone_number, len(cls._ZONE_IDS) + 1)
        return ParkingZone(
            zone_id=zone_id,
            zone_number=zone_number,
            zone_type=zone_type,
            polygon=NormalizedPolygon(tuple(points)),
        )

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

    def test_zone_coverage_ratio_full_containment_regardless_of_bbox_size(self) -> None:
        """리뷰에서 발견된 회귀 시나리오: 작은 구역을 훨씬 큰 바운딩박스가 완전히
        덮어도(트럭이 오토바이 스팟을 덮는 경우), 구역 자기 면적 기준이므로
        100%로 나와야 한다 — 기존 overlap_ratio(차체 기준)로는 7.1%밖에 안 됐다."""
        moto_spot = self.make_zone("GEN-MOTO", ZoneType.GENERAL, [(0.10, 0.10), (0.15, 0.10), (0.15, 0.20), (0.10, 0.20)])
        truck_bbox = BoundingBox(0.06, 0.05, 0.40, 0.25)  # moto_spot을 완전히 포함
        self.assertAlmostEqual(zone_coverage_ratio(moto_spot, truck_bbox), 1.0)

    def test_zone_coverage_ratio_partial_overlap(self) -> None:
        spot = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        intruding_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)  # spot 안쪽 0.15 + 바깥쪽 0.04
        self.assertAlmostEqual(zone_coverage_ratio(spot, intruding_bbox), 0.75)

    def test_zone_coverage_ratio_no_overlap(self) -> None:
        spot = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        far_bbox = BoundingBox(0.50, 0.50, 0.70, 0.70)
        self.assertEqual(zone_coverage_ratio(spot, far_bbox), 0.0)

    def test_restricted_zone_flagged_after_min_dwell(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.RESTRICTED_ZONE)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "DIS-01")

    def test_observing_before_min_dwell(self) -> None:
        zone = self.make_zone("EV-01", ZoneType.EV_FAST, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        overlaps = classify_zone_overlaps(bbox, [zone], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(overlaps, dwell_seconds=100.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)

    def test_out_of_zone_flagged_after_min_dwell_with_no_zone_overlap(self) -> None:
        """등록된 구역 어디에도 겹치지 않고 스팟 침범도 아니면, 최소 정차
        시간 이후 OUT_OF_ZONE으로 판정한다(요구사항 정의서.md:25, ERD.md:119-125)."""
        status, zone_hit, ratio = classify_violation([], dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OUT_OF_ZONE)
        self.assertIsNone(zone_hit)
        self.assertEqual(ratio, 0.0)

    def test_out_of_zone_observing_before_min_dwell(self) -> None:
        """구역 겹침이 전혀 없어도, 최소 정차 시간을 채우기 전에는 다른
        위반들과 동일하게 OBSERVING으로만 표시하고 OUT_OF_ZONE으로 확정하지 않는다."""
        status, zone_hit, _ratio = classify_violation([], dwell_seconds=100.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)
        self.assertIsNone(zone_hit)

    def test_out_of_zone_boundary_at_exact_min_dwell(self) -> None:
        """dwell_seconds가 min_dwell_seconds와 정확히 같으면(리뷰 반영, 경계값
        테스트), 다른 위반 판정들과 동일하게 '미달'이 아니므로 OUT_OF_ZONE으로 확정한다."""
        status, _zone, _ratio = classify_violation([], dwell_seconds=600.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OUT_OF_ZONE)

        status, _zone, _ratio = classify_violation([], dwell_seconds=599.999, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.OBSERVING)

    def test_out_of_zone_not_flagged_when_intruded_zone_present(self) -> None:
        """구역 겹침(overlaps)은 없어도 spot_intrusion_ratio 기준 침범(intruded_zone)이
        있으면, 그건 OUT_OF_ZONE이 아니라 LINE_CROSS 판정으로 이어져야 한다."""
        gen = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        intruded_zone = ZoneOverlap(gen, 0.5)
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, intruded_zone=intruded_zone
        )
        self.assertEqual(status, ViolationStatus.LINE_CROSS)

    def test_out_of_zone_not_flagged_when_blocked_zone_present(self) -> None:
        """리뷰 반영(I-5): intruded_zone과 대칭 — overlaps가 비어도 blocked_zone이
        있으면 OUT_OF_ZONE이 아니라 DOUBLE_PARK여야 한다."""
        gen = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=ZoneOverlap(gen, 0.5)
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)

    def test_out_of_zone_not_flagged_when_in_ignored_zone(self) -> None:
        """리뷰 반영(C-1): 판정 제외 구역(ENTRY_EXIT 등) 안에 있다는 신호가
        오면, overlaps가 비어 있어도 OUT_OF_ZONE이 아니라 기존과 동일하게
        NONE으로 유지한다."""
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, in_ignored_zone=True
        )
        self.assertEqual(status, ViolationStatus.NONE)

    def test_out_of_zone_not_flagged_when_intrusion_deferred(self) -> None:
        """리뷰 반영(C-2): 다른 트랙의 정착 미확정으로 침범 판정이 보류
        중이라는 신호가 오면, overlaps가 비어 있어도 OUT_OF_ZONE으로
        확정하지 않고 기존과 동일하게 NONE으로 유지한다."""
        status, _zone, _ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, deferred_intrusion=True
        )
        self.assertEqual(status, ViolationStatus.NONE)

    def test_line_cross_uses_intruded_zone(self) -> None:
        """LINE_CROSS는 이제 classify_zone_overlaps의 len(overlaps)>=2가 아니라
        호출부가 넘겨주는 intruded_zone(빈 스팟 침범)으로 판정한다."""
        gen1 = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        gen2 = self.make_zone("GEN-02", ZoneType.GENERAL, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.3), (0.2, 0.3)])
        bbox = BoundingBox(0.1, 0.0, 0.3, 0.3)
        overlaps = classify_zone_overlaps(bbox, [gen1], min_overlap_ratio=0.40)  # 내 홈(GEN-01)만
        intruded_zone = ZoneOverlap(gen2, 0.5)  # GEN-02를 50% 침범(구역 면적 기준)
        status, zone, ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, intruded_zone=intruded_zone
        )
        self.assertEqual(status, ViolationStatus.LINE_CROSS)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-02")
        self.assertAlmostEqual(ratio, 0.5)

    def test_monitor_line_cross_when_intruded_spot_is_empty(self) -> None:
        """차 한 대가 혼자 두 스팟에 걸쳐 주차했는데, 침범한 쪽 스팟이 비어있으면
        DOUBLE_PARK가 아니라 LINE_CROSS로 판정한다(피해자가 없으므로)."""
        gen1 = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        gen2 = self.make_zone("GEN-02", ZoneType.GENERAL, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.3), (0.2, 0.3)])
        registry = ZoneRegistry([gen1, gen2])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        straddling_bbox = BoundingBox(0.1, 0.0, 0.3, 0.3)  # GEN-01/GEN-02 각각 50%

        monitor.update(
            [VehicleBox(track_id=1, bbox=straddling_bbox, confidence=0.9, frame_id=0, captured_at=base_time)]
        )
        events_at_min_dwell = monitor.update(  # 정차 시간이 처음 5초를 넘기는 프레임에서 이벤트가 발행된다
            [VehicleBox(track_id=1, bbox=straddling_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6))]
        )
        events_after = monitor.update(  # 같은 상태가 계속되면 중복 발행하지 않는다
            [VehicleBox(track_id=1, bbox=straddling_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12))]
        )
        self.assertEqual(len(events_at_min_dwell), 1)
        self.assertEqual(events_at_min_dwell[0].status, ViolationStatus.LINE_CROSS)
        self.assertIn(events_at_min_dwell[0].zone_number, ("GEN-01", "GEN-02"))  # 홈이 아닌 쪽이 침범 구역으로 보고됨
        self.assertEqual(events_after, [])

    def test_aisle_block_takes_priority_over_restricted_zone(self) -> None:
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        disabled = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.2, 0.2, 0.5, 0.5)
        overlaps = classify_zone_overlaps(bbox, [aisle, disabled], min_overlap_ratio=0.40)
        status, zone_hit, _ratio = classify_violation(overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0)
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)
        assert zone_hit is not None
        self.assertEqual(zone_hit.zone_number, "AISLE-01")

    def test_home_zone_overlap_picks_spot_type_ignoring_aisle(self) -> None:
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        spot = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.5, 0.0), (0.5, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        overlaps = classify_zone_overlaps(bbox, [aisle, spot], min_overlap_ratio=0.40)
        home = _home_zone_overlap(overlaps)
        assert home is not None
        self.assertEqual(home.zone.zone_number, "GEN-01")

    def test_home_zone_overlap_none_when_only_aisle(self) -> None:
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        overlaps = classify_zone_overlaps(bbox, [aisle], min_overlap_ratio=0.40)
        self.assertIsNone(_home_zone_overlap(overlaps))

    def test_home_zone_overlap_none_when_no_overlaps(self) -> None:
        self.assertIsNone(_home_zone_overlap([]))

    def test_double_park_priority_between_aisle_and_restricted(self) -> None:
        victim_spot = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.6, 0.6), (0.9, 0.6), (0.9, 0.9), (0.6, 0.9)])
        blocked_zone = ZoneOverlap(victim_spot, 0.9)

        # 통행로 겹침이 있으면 이중주차보다 AISLE_BLOCK이 우선한다.
        aisle = self.make_zone("AISLE-01", ZoneType.AISLE, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        overlaps = classify_zone_overlaps(BoundingBox(0.2, 0.2, 0.5, 0.5), [aisle], min_overlap_ratio=0.40)
        status, _zone, _ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.AISLE_BLOCK)

        # 전용구역 겹침만 있으면 이중주차가 그보다 우선한다(막힌 차량이 실존 피해자이므로).
        disabled = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])
        overlaps = classify_zone_overlaps(BoundingBox(0.2, 0.2, 0.5, 0.5), [disabled], min_overlap_ratio=0.40)
        status, zone, ratio = classify_violation(
            overlaps, dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-01")  # 이제 피해 차량이 점유한 구역이 실제로 실린다
        self.assertAlmostEqual(ratio, 0.9)

        # 구역 겹침이 전혀 없어도 다른 차량의 홈 구역을 침범했으면 이중주차로 판정한다.
        status, zone, ratio = classify_violation(
            [], dwell_seconds=700.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.DOUBLE_PARK)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-01")
        self.assertAlmostEqual(ratio, 0.9)

        # 최소 정차 시간 미달이면 겹침이 있어도 아직 OBSERVING이다.
        status, zone, _ratio = classify_violation(
            [], dwell_seconds=10.0, min_dwell_seconds=600.0, blocked_zone=blocked_zone
        )
        self.assertEqual(status, ViolationStatus.OBSERVING)
        assert zone is not None
        self.assertEqual(zone.zone_number, "GEN-01")  # OBSERVING 중에도 어떤 구역이 위험한지 확인 가능

    def test_monitor_double_park_flags_whoever_intrudes_regardless_of_arrival_order(self) -> None:
        """리뷰에서 발견된 회귀: 먼저 온 차가 실제로 옆 칸(나중에 온 차의 자리)을
        침범했다면, 시간순이 아니라 누가 실제로 침범했는지로 판정해야 한다.
        옛 로직은 '나중에 온 차만 가해자'였어서, 제대로 주차한 나중 차가 억울하게
        잡히고 실제 침범자(먼저 온 차)는 절대 안 잡혔다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.20, 0.0), (0.40, 0.0), (0.40, 0.3), (0.20, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        # 먼저 온 차(track 1)가 자기 칸(GEN-A)을 벗어나 GEN-B로 침범해서 나쁘게 주차
        intruder_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)
        # 나중에 온 차(track 2)는 자기 칸(GEN-B) 안에 올바르게 주차
        victim_bbox = BoundingBox(0.24, 0.0, 0.38, 0.3)

        monitor.update([VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        # track 2(피해자)는 아직 정착 전(리뷰 반영: 이 프레임엔 GEN-B 점유 여부가
        # 불확실하므로 LINE_CROSS로 잘못 보고되면 안 되고, 아무 이벤트도 없어야 한다)
        events_before_victim_settles = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
            ]
        )
        self.assertEqual(events_before_victim_settles, [])

        events = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
            ]
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 1)  # 먼저 왔지만 실제로 침범한 쪽(track 1)이 잡힌다
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-B")  # 침범당한 구역이 실제로 실린다

    def test_monitor_no_line_cross_to_double_park_flap_while_victim_settles(self) -> None:
        """리뷰에서 발견된 회귀: 침입자가 피해자보다 먼저 정착 완료(min_dwell 도달)
        하면, 피해자가 아직 정착 전인 짧은 구간 동안 그 구역이 "비어있는 것"으로
        오인되어 LINE_CROSS 이벤트가 먼저 발행됐다가, 피해자가 정착하는 순간
        DOUBLE_PARK로 다시 발행되는 이벤트 중복(플래핑)이 있었다. 이제는 아직
        아무도 정착하지 못한 구역은 판정을 보류해서, LINE_CROSS 없이 DOUBLE_PARK
        하나만 발행돼야 한다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.20, 0.0), (0.40, 0.0), (0.40, 0.3), (0.20, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        intruder_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)  # GEN-A가 홈, GEN-B를 20% 침범
        victim_bbox = BoundingBox(0.24, 0.0, 0.38, 0.3)

        monitor.update([VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=0, captured_at=base_time)])

        # 침입자는 정착 완료(dwell 6≥5), 피해자는 방금 등장(dwell 0<5) — GEN-B
        # 점유 여부가 아직 불확실한 구간. LINE_CROSS가 잘못 발행되면 안 된다.
        events_while_victim_unsettled = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=6, captured_at=base_time + timedelta(seconds=6)),
            ]
        )
        self.assertEqual(events_while_victim_unsettled, [])

        events_after_victim_settles = monitor.update(
            [
                VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
                VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=12, captured_at=base_time + timedelta(seconds=12)),
            ]
        )
        self.assertEqual(len(events_after_victim_settles), 1)  # DOUBLE_PARK 딱 한 번만 발행(LINE_CROSS 거치지 않음)
        self.assertEqual(events_after_victim_settles[0].track_id, 1)
        self.assertEqual(events_after_victim_settles[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events_after_victim_settles[0].zone_number, "GEN-B")

    def test_monitor_double_park_catches_large_vehicle_intruding_small_spot(self) -> None:
        """리뷰에서 발견된 회귀: 가해 차량이 피해 차량보다 훨씬 크면(트럭이 오토바이
        스팟을 덮는 경우), 옛 방식(차량 대 차량 비교, 가해 차량 자신이 분모)은
        가해 차량 면적이 커서 비율이 낮게 나와 못 잡았다. 이제는 피해 차량이
        점유한 구역 면적이 분모라 가해 차량 크기와 무관하게 잡힌다."""
        moto_spot = self.make_zone("GEN-MOTO", ZoneType.GENERAL, [(0.10, 0.10), (0.15, 0.10), (0.15, 0.20), (0.10, 0.20)])
        registry = ZoneRegistry([moto_spot])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        moto_bbox = BoundingBox(0.10, 0.10, 0.15, 0.20)  # 자기 스팟에 정확히 주차
        truck_bbox = BoundingBox(0.06, 0.05, 0.40, 0.25)  # 몸집이 훨씬 큰 트럭이 스팟을 완전히 덮음

        monitor.update([VehicleBox(track_id=1, bbox=moto_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=moto_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=truck_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 2)
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-MOTO")

    def test_monitor_double_park_not_flagged_when_victim_has_no_home_zone(self) -> None:
        """피해 후보가 어떤 스팟 구역과도 40% 이상 안 겹치는 애매한 위치에 있으면
        (홈 구역이 없으면), 그 차를 기준으로 다른 차를 이중주차로 판정하지 않는다.

        (리뷰 반영, I-3) 두 차량 다 등록 구역(GEN-A)과 전혀 안 겹치는 위치라
        각자 독립적으로 정착 시점에 OUT_OF_ZONE이 한 번씩 발행된다(track 1은
        6초째, track 2는 자신의 정착 시점인 12초째) — 루프의 마지막
        `update()` 반환값만 보면 track 2 것만 보이므로, 전체 프레임에 걸쳐
        발행된 이벤트를 다 모아서 정확히 단정한다. 핵심은 어느 프레임에서도
        DOUBLE_PARK는 절대 나오면 안 된다는 것이다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        registry = ZoneRegistry([spot_a])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        ambiguous_bbox = BoundingBox(0.50, 0.50, 0.70, 0.70)  # 어떤 구역과도 안 겹침
        overlapping_bbox = BoundingBox(0.55, 0.55, 0.75, 0.75)  # ambiguous_bbox와 상당히 겹침

        monitor.update([VehicleBox(track_id=1, bbox=ambiguous_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        all_events: list[ViolationEvent] = []
        for seconds in (6, 12):
            all_events.extend(
                monitor.update(
                    [
                        VehicleBox(track_id=1, bbox=ambiguous_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                        VehicleBox(track_id=2, bbox=overlapping_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    ]
                )
            )

        self.assertEqual(
            [(event.track_id, event.status) for event in all_events],
            [(1, ViolationStatus.OUT_OF_ZONE), (2, ViolationStatus.OUT_OF_ZONE)],
        )

    def test_monitor_double_park_respects_custom_threshold(self) -> None:
        """spot_intrusion_ratio를 높이면 약한 침범(20%)은 더 이상 안 잡힌다 —
        임계값이 실제로 동작함을 확인."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.00, 0.0), (0.20, 0.0), (0.20, 0.3), (0.00, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.20, 0.0), (0.40, 0.0), (0.40, 0.3), (0.20, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.40)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        intruder_bbox = BoundingBox(0.05, 0.0, 0.24, 0.3)  # GEN-B를 20%만 침범(0.40 임계값 미달)
        victim_bbox = BoundingBox(0.24, 0.0, 0.38, 0.3)

        monitor.update([VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=intruder_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=victim_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        self.assertEqual(events, [])

    def test_monitor_double_park_correctly_parked_vehicle_not_blamed_when_sharing_home_zone(self) -> None:
        """리뷰에서 발견된 Critical 회귀: 두 차량의 홈 구역 판정이 우연히 같은
        스팟(경계선 근처 타이)으로 겹칠 때, 그 스팟에 제대로(거의 전부) 주차한
        차량까지 침범자로 몰리면 안 된다 — 점유율이 더 낮은 쪽(track 1, 경계선에
        걸친 차)만 침범자여야 하고, 점유율이 더 높은 쪽(track 2, 자기 자리에
        똑바로 주차)은 절대 잡히면 안 된다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.3), (0.0, 0.3)])
        spot_b = self.make_zone("GEN-B", ZoneType.GENERAL, [(0.2, 0.0), (0.4, 0.0), (0.4, 0.3), (0.2, 0.3)])
        registry = ZoneRegistry([spot_a, spot_b])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        straddler_bbox = BoundingBox(0.14, 0.0, 0.26, 0.3)  # GEN-A/GEN-B 경계에 걸쳐 있음(사실상 타이)
        correct_bbox = BoundingBox(0.28, 0.0, 0.38, 0.3)  # GEN-B 안에 온전히 들어간 정상 주차

        monitor.update([VehicleBox(track_id=1, bbox=straddler_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])
        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=straddler_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=correct_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        flagged_ids = {event.track_id for event in events}
        self.assertNotIn(2, flagged_ids, "제대로 주차한 차량은 절대 침범자로 잡히면 안 된다")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 1)
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-B")

    def test_monitor_double_park_only_lower_occupancy_side_blamed_when_sharing_one_spot(self) -> None:
        """한 스팟을 두 차가 나눠 점유하는 상황(진짜 겹주차)에서는, 그 스팟을 거의
        온전히 차지한 차(occupancy ratio ~1.0)가 아니라 절반만 걸친 차(occupancy
        ratio ~0.5)만 침범자로 잡혀야 한다 — 둘 다 잡히거나 둘 다 안 잡히면 안 된다."""
        spot_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([spot_a])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        mostly_inside_bbox = BoundingBox(0.02, 0.02, 0.28, 0.28)  # 스팟 안에 거의 전부(ratio ~1.0)
        half_inside_bbox = BoundingBox(0.15, 0.0, 0.45, 0.3)  # 스팟에 절반만(ratio ~0.5)

        monitor.update([VehicleBox(track_id=1, bbox=mostly_inside_bbox, confidence=0.9, frame_id=1, captured_at=base_time)])
        events = []
        for seconds in (6, 12):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=mostly_inside_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=half_inside_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].track_id, 2)  # 점유율이 더 낮은 쪽만 침범자
        self.assertEqual(events[0].status, ViolationStatus.DOUBLE_PARK)
        self.assertEqual(events[0].zone_number, "GEN-A")

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

    def test_monitor_out_of_zone_flagged_when_parked_outside_all_zones(self) -> None:
        """등록된 구역과 전혀 겹치지 않는 곳에 정착하면(요구사항 정의서.md:25), 최소 정차 시간
        이후 OUT_OF_ZONE 이벤트가 한 번 발행되고 중복 발행되지 않는다."""
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        outside_bbox = BoundingBox(0.6, 0.6, 0.8, 0.8)  # 등록 구역과 전혀 겹치지 않는 위치
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)

        first = VehicleBox(track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=1, captured_at=base_time)
        second = VehicleBox(
            track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=2)
        )
        third = VehicleBox(
            track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=4)
        )

        events_first = monitor.update([first])
        events_second = monitor.update([second])
        events_third = monitor.update([third])

        self.assertEqual(len(events_first), 0)  # 최소 정차 시간(1초) 미달로 아직 OBSERVING
        self.assertEqual(len(events_second), 1)
        self.assertEqual(events_second[0].status, ViolationStatus.OUT_OF_ZONE)
        self.assertIsNone(events_second[0].zone_id)
        self.assertEqual(len(events_third), 0)  # 같은 위반이 계속 열려 있으므로 중복 발행하지 않음

    def test_monitor_out_of_zone_transitions_to_aisle_block_after_moving(self) -> None:
        """리뷰 반영: 구역 외(OUT_OF_ZONE)에 정착해있던 차량이 이동해서 통행로에
        들어가면, 이전 OUT_OF_ZONE 상태는 자동으로 닫히고 AISLE_BLOCK이 새로
        (중복 없이 한 번만) 발행돼야 한다."""
        aisle = self.make_zone("AISLE-1", ZoneType.AISLE, [(0.5, 0.0), (0.9, 0.0), (0.9, 0.3), (0.5, 0.3)])
        registry = ZoneRegistry([aisle])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        outside_bbox = BoundingBox(0.0, 0.5, 0.2, 0.7)  # 등록 구역과 안 겹침
        aisle_bbox = BoundingBox(0.55, 0.05, 0.85, 0.25)  # AISLE 구역 안

        events_at = {}
        for seconds in (0, 2, 4):
            events_at[seconds] = monitor.update(
                [VehicleBox(track_id=1, bbox=outside_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds))]
            )
        self.assertEqual(len(events_at[0]), 0)  # 정착 전(1초 미달), OBSERVING
        self.assertEqual([e.status for e in events_at[2]], [ViolationStatus.OUT_OF_ZONE])  # 정착 -> OUT_OF_ZONE 1회 발행
        self.assertEqual(len(events_at[4]), 0)  # 같은 위반 계속 열려있으므로 중복 없음

        for seconds in (6, 8, 10):
            events_at[seconds] = monitor.update(
                [VehicleBox(track_id=1, bbox=aisle_bbox, confidence=0.9, frame_id=seconds, captured_at=base_time + timedelta(seconds=seconds))]
            )
        self.assertEqual(len(events_at[6]), 0)  # 이동 직후 정차 타이머 리셋, 1초 미달로 OBSERVING
        # 재정착 -> AISLE_BLOCK 1회 발행. 이전 OUT_OF_ZONE이 "자동으로 닫히는" 게
        # 아니라, 이동 감지 시 open_violation이 NONE으로 리셋되기 때문이다(위 이동 시점 코드 참고).
        self.assertEqual([e.status for e in events_at[8]], [ViolationStatus.AISLE_BLOCK])
        self.assertEqual(len(events_at[10]), 0)  # 같은 위반 계속 열려있으므로 중복 없음

    def test_monitor_vehicle_inside_entry_exit_zone_is_not_out_of_zone(self) -> None:
        """리뷰 반영(C-1): 게이트(ENTRY_EXIT) 구역 안에 대기 중인 차량은 판정
        제외 구역 안에 있으므로 OUT_OF_ZONE이 아니어야 한다
        (`IGNORED_ZONE_TYPES_FOR_PARKING` 판정 제외 불변식, §5.1)."""
        ent = self.make_zone("ENT-1", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)])
        monitor = ViolationMonitor(ZoneRegistry([ent]), min_overlap_ratio=0.40, min_dwell_seconds=1.0, movement_epsilon=0.01)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        at_gate = BoundingBox(0.1, 0.1, 0.4, 0.4)  # ENTRY_EXIT 안에 100% 포함

        monitor.update([VehicleBox(track_id=1, bbox=at_gate, confidence=0.9, frame_id=0, captured_at=base_time)])
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=at_gate, confidence=0.9, frame_id=1, captured_at=base_time + timedelta(seconds=2))]
        )
        self.assertNotIn(ViolationStatus.OUT_OF_ZONE, [e.status for e in events])

    def test_monitor_gate_overlap_uses_entry_zone_threshold_not_general_threshold(self) -> None:
        """리뷰 반영(N-1): "게이트 안에 있다" 판단은 §2.2 입차매칭과 같은
        entry_zone_min_overlap_ratio를 써야 한다. 몸겹침이 entry_zone_min_overlap_ratio는
        넘고(그래서 입차매칭은 성공) min_overlap_ratio(스팟 판정용, 더 높음)는 못 넘는
        차량이, 같은 프레임에서 "게이트에 있다(번호판 매칭 성공)"와 "구역 외 주차"라는
        모순된 판정을 동시에 받으면 안 된다."""
        ent = self.make_zone("ENT-1", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)])
        monitor = ViolationMonitor(
            ZoneRegistry([ent]),
            min_overlap_ratio=0.40,
            min_dwell_seconds=1.0,
            movement_epsilon=0.01,
            entry_zone_min_overlap_ratio=0.20,
        )
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        # ENT-1과 몸겹침 37.5% — entry_zone_min_overlap_ratio(0.20)는 넘지만
        # min_overlap_ratio(0.40)는 못 넘는 위치.
        gate_bbox = BoundingBox(0.35, 0.0, 0.75, 0.3)

        monitor.add_entry_event(EntryEvent(plate_number="12가3456", captured_at=base_time))
        monitor.update([VehicleBox(track_id=1, bbox=gate_bbox, confidence=0.9, frame_id=0, captured_at=base_time)])
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=gate_bbox, confidence=0.9, frame_id=1, captured_at=base_time + timedelta(seconds=2))]
        )
        self.assertNotIn(ViolationStatus.OUT_OF_ZONE, [e.status for e in events])

    def test_monitor_out_of_zone_not_flagged_while_neighbor_home_zone_pending(self) -> None:
        """리뷰 반영(C-2): 옆 트랙이 홈 구역에 정착하지 못해 그 구역이
        pending_home_zone_ids로 보류 중이면, 그 구역을 침범 기준 이상 덮고
        있는 다른 트랙도 OUT_OF_ZONE으로 잘못 확정되면 안 된다(판정 보류 유지)."""
        gen_a = self.make_zone("GEN-A", ZoneType.GENERAL, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        monitor = ViolationMonitor(
            ZoneRegistry([gen_a]), min_overlap_ratio=0.40, min_dwell_seconds=5.0, spot_intrusion_ratio=0.15, movement_epsilon=0.01
        )
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        # track1: 매 프레임 살짝 위치가 바뀌어(움직임 감지) 계속 정착 실패 -> GEN-A가 pending으로 남음
        track1_positions = [BoundingBox(0.0, 0.0, 0.25, 0.25), BoundingBox(0.02, 0.02, 0.27, 0.27)]
        # track2: GEN-A 몸겹침은 40% 미만(overlaps=[])이지만, 구역 면적 기준으로는 침범 후보(>=15%)
        track2_bbox = BoundingBox(0.15, 0.0, 0.55, 0.3)

        events: list[ViolationEvent] = []
        for i, seconds in enumerate((0, 3, 6, 9, 12)):
            events = monitor.update(
                [
                    VehicleBox(track_id=1, bbox=track1_positions[i % 2], confidence=0.9, frame_id=i, captured_at=base_time + timedelta(seconds=seconds)),
                    VehicleBox(track_id=2, bbox=track2_bbox, confidence=0.9, frame_id=i, captured_at=base_time + timedelta(seconds=seconds)),
                ]
            )
            self.assertNotIn(ViolationStatus.OUT_OF_ZONE, [e.status for e in events if e.track_id == 2])

    def test_monitor_multi_vehicle_frame_does_not_mix_up_track_state(self) -> None:
        """한 프레임에 차량이 2대 이상 잡혀도, 마지막 차량이 아닌 다른 차량의
        상태(open_violation, plate_number)를 잘못 참조하면 안 된다."""

        restricted_zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        general_zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.6, 0.0), (0.9, 0.0), (0.9, 0.3), (0.6, 0.3)])
        registry = ZoneRegistry([restricted_zone, general_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, min_dwell_seconds=1.0)
        base_time = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)
        restricted_bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)

        for index in range(2):
            monitor.update(
                [
                    VehicleBox(
                        track_id=1,
                        bbox=restricted_bbox,
                        confidence=0.9,
                        frame_id=index + 1,
                        captured_at=base_time + timedelta(seconds=2 * index),
                    )
                ]
            )
        monitor.attach_plate(1, "11가1111")

        # track 1의 RESTRICTED_ZONE 위반이 이미 열려 있는 상태에서, 같은 프레임에
        # track 2(위반 없는 신규 차량)가 track 1보다 뒤에 detections에 들어온다.
        events = monitor.update(
            [
                VehicleBox(
                    track_id=1,
                    bbox=restricted_bbox,
                    confidence=0.9,
                    frame_id=3,
                    captured_at=base_time + timedelta(seconds=4),
                ),
                VehicleBox(
                    track_id=2,
                    bbox=BoundingBox(0.65, 0.05, 0.85, 0.25),
                    confidence=0.9,
                    frame_id=3,
                    captured_at=base_time + timedelta(seconds=4),
                ),
            ]
        )

        self.assertEqual(len(events), 0)  # track1의 위반은 이미 열려 있으므로 중복 발행되면 안 됨

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

    def test_track_survives_brief_disappearance_within_grace_period(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0, 0), (1, 0), (1, 1), (0, 1)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, track_grace_seconds=5.0
        )
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        other_bbox = BoundingBox(0.5, 0.5, 0.6, 0.6)

        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        # 3초간 안 보임 — 유예 시간(5초) 이내라 트랙이 살아있어야 한다.
        # "지금 시각"을 전달하기 위해 이 프레임엔 다른 차량을 하나 넣는다.
        monitor.update(
            [
                VehicleBox(
                    track_id=99, bbox=other_bbox, confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertIn(1, monitor._tracks)

        # 다시 나타남 — 정차 시작 시각(base_time)이 유지되어 dwell이 끊기지 않아야 한다.
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=12))]
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].status, ViolationStatus.RESTRICTED_ZONE)
        self.assertAlmostEqual(events[0].dwell_seconds, 12.0)

    def test_track_purged_after_grace_period_exceeded(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0, 0), (1, 0), (1, 1), (0, 1)])
        registry = ZoneRegistry([zone])
        monitor = ViolationMonitor(
            registry, min_overlap_ratio=0.40, min_dwell_seconds=10.0, track_grace_seconds=2.0
        )
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        other_bbox = BoundingBox(0.5, 0.5, 0.6, 0.6)

        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)])

        # 유예 시간(2초)을 훨씬 넘겨서 사라짐 → 트랙이 삭제되어야 한다.
        monitor.update(
            [
                VehicleBox(
                    track_id=99, bbox=other_bbox, confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=10),
                )
            ]
        )
        self.assertNotIn(1, monitor._tracks)

        # 다시 나타나면 완전히 새 트랙으로 취급되어 dwell이 0부터 다시 시작한다.
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=3, captured_at=base_time + timedelta(seconds=11))]
        )
        self.assertEqual(len(events), 0)

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

    def test_track_snapshot_matches_dwell_used_by_update(self) -> None:
        zone = self.make_zone("GEN-01", ZoneType.GENERAL, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        monitor = ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=10.0)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=start)])
        later = start + timedelta(seconds=4)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=later)])

        snapshot = monitor.track_snapshot(later)

        self.assertEqual(set(snapshot), {1})
        self.assertAlmostEqual(snapshot[1].dwell_seconds, 4.0)

    def test_track_snapshot_reports_open_violation(self) -> None:
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        monitor = ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=1.0)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=start)])
        later = start + timedelta(seconds=5)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=later)])

        self.assertEqual(monitor.track_snapshot(later)[1].open_violation, ViolationStatus.RESTRICTED_ZONE)

    def test_track_snapshot_does_not_affect_judgment(self) -> None:
        """오버레이가 판정을 바꾸면 검증 도구가 검증 대상을 오염시킨다."""
        zone = self.make_zone("DIS-01", ZoneType.DISABLED, [(0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4)])
        monitor = ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=1.0)
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=start)])
        later = start + timedelta(seconds=5)

        for _ in range(3):
            monitor.track_snapshot(later)
        events = monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=later)]
        )

        self.assertEqual([event.status for event in events], [ViolationStatus.RESTRICTED_ZONE])

    def test_entry_event_matches_new_track_in_entry_zone(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1234")

    def test_entry_event_not_matched_outside_entry_zone(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.6, 0.6, 0.8, 0.8), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertIsNone(monitor._tracks[1].plate_number)

    def test_entry_event_expires_outside_time_window(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=20),  # 시간창(10초) 초과
                )
            ]
        )
        self.assertIsNone(monitor._tracks[1].plate_number)

    def test_multiple_entry_events_matched_fifo_in_order(self) -> None:
        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1111", captured_at=base_time))
        monitor.add_entry_event(EntryEvent(plate_number="2222", captured_at=base_time + timedelta(seconds=1)))

        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=2),
                )
            ]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1111")  # 먼저 들어온 이벤트부터 매칭

        monitor.update(
            [
                VehicleBox(
                    track_id=2, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=3),
                )
            ]
        )
        self.assertEqual(monitor._tracks[2].plate_number, "2222")

    def test_entry_event_matches_on_later_frame_when_event_arrives_late(self) -> None:
        """리뷰 반영: OCR 이벤트가 트랙 생성 이후에 도착해도, 다음 프레임에서 매칭돼야 한다."""

        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)

        # 트랙이 먼저 생기고, 이 시점엔 대기열이 비어 있어 매칭 실패.
        monitor.update([VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=1, captured_at=base_time)])
        self.assertIsNone(monitor._tracks[1].plate_number)

        # 그 다음에야 OCR 이벤트가 도착(시간창 안).
        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))

        # 같은 트랙이 다음 프레임에도 여전히 구역 안에 있으면 재시도로 매칭돼야 한다.
        monitor.update(
            [VehicleBox(track_id=1, bbox=bbox, confidence=0.9, frame_id=2, captured_at=base_time + timedelta(seconds=1))]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1234")

    def test_entry_event_matches_once_zone_overlap_increases_on_later_frame(self) -> None:
        """리뷰 반영: 첫 프레임의 구역 겹침이 임계값 미만이어도, 다음 프레임에 임계값을 넘으면 매칭돼야 한다."""

        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)
        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))

        # 첫 프레임: 구역 겹침이 임계값(40%) 미만 (막 진입 중).
        low_overlap_bbox = BoundingBox(0.20, 0.20, 0.50, 0.50)
        monitor.update(
            [VehicleBox(track_id=1, bbox=low_overlap_bbox, confidence=0.9, frame_id=1, captured_at=base_time)]
        )
        self.assertIsNone(monitor._tracks[1].plate_number)

        # 다음 프레임: 완전히 진입해서 겹침이 임계값을 넘음 → 재시도로 매칭돼야 한다.
        high_overlap_bbox = BoundingBox(0.05, 0.05, 0.25, 0.25)
        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=high_overlap_bbox, confidence=0.9, frame_id=2,
                    captured_at=base_time + timedelta(seconds=1),
                )
            ]
        )
        self.assertEqual(monitor._tracks[1].plate_number, "1234")

    def test_entry_events_matched_in_captured_at_order_not_insertion_order(self) -> None:
        """리뷰 반영: add_entry_event 호출 순서가 아니라 captured_at 순으로 매칭돼야 한다."""

        entry_zone = self.make_zone("ENTRY-01", ZoneType.ENTRY_EXIT, [(0.0, 0.0), (0.3, 0.0), (0.3, 0.3), (0.0, 0.3)])
        registry = ZoneRegistry([entry_zone])
        monitor = ViolationMonitor(registry, min_overlap_ratio=0.40, entry_match_window_seconds=10.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        # 나중에(시간상) 입차한 차의 이벤트를 먼저 추가하고, 더 이른 이벤트를 나중에 추가한다.
        monitor.add_entry_event(EntryEvent(plate_number="LATER", captured_at=base_time + timedelta(seconds=5)))
        monitor.add_entry_event(EntryEvent(plate_number="EARLIER", captured_at=base_time))

        monitor.update(
            [
                VehicleBox(
                    track_id=1, bbox=BoundingBox(0.05, 0.05, 0.25, 0.25), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=6),
                )
            ]
        )
        # 삽입 순서(LATER가 먼저)가 아니라 촬영 시각 순(EARLIER가 더 이름)으로 매칭돼야 한다.
        self.assertEqual(monitor._tracks[1].plate_number, "EARLIER")

    def test_pending_entry_events_pruned_even_without_matching_attempt(self) -> None:
        """리뷰 반영: 매칭 시도가 한 번도 없어도(구역 근처에 트랙이 안 생겨도) 대기열이 계속 정리돼야 한다."""

        registry = ZoneRegistry([])  # ENTRY_EXIT 구역 자체가 없어서 매칭 시도가 전혀 발생하지 않는다.
        monitor = ViolationMonitor(registry, entry_match_window_seconds=5.0)
        base_time = datetime(2026, 7, 27, 12, 0, 0, tzinfo=timezone.utc)

        monitor.add_entry_event(EntryEvent(plate_number="1234", captured_at=base_time))
        self.assertEqual(len(monitor._pending_entry_events), 1)

        # 시간창(5초)을 넘긴 뒤에도, 아무 트랙도 없이 update()만 호출되면 정리돼야 한다.
        monitor.update(
            [
                VehicleBox(
                    track_id=99, bbox=BoundingBox(0.6, 0.6, 0.8, 0.8), confidence=0.9, frame_id=1,
                    captured_at=base_time + timedelta(seconds=10),
                )
            ]
        )
        self.assertEqual(len(monitor._pending_entry_events), 0)

    def test_zone_registry_from_file_parses_wire_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "zones.json"
            path.write_text(
                json.dumps(
                    {
                        "zones": [
                            {
                                "zoneId": 12,
                                "zoneNumber": "GEN-01",
                                "zoneType": "GENERAL",
                                "allowedMinutes": None,
                                "polygon": [[0.0, 0.0], [0.2, 0.0], [0.2, 0.2], [0.0, 0.2]],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            registry = ZoneRegistry.from_file(path)
        zone = registry.get(12)
        self.assertEqual(zone.zone_type, ZoneType.GENERAL)
        self.assertEqual(zone.zone_number, "GEN-01")
        self.assertIsInstance(zone.zone_id, int)

    def test_zone_registry_from_file_rejects_legacy_snake_case(self) -> None:
        """구 포맷을 조용히 무시하면 빈 레지스트리로 돌아 판정이 전부 없어진다."""
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
            with self.assertRaises(BaselineError):
                ZoneRegistry.from_file(path)

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

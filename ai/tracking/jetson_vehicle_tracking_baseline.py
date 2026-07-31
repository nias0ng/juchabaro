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
  전기차 충전구역(EV_FAST/EV_SLOW)은 여기서 한 걸음 더 나아가, `zones` 파일에
  `allowed_minutes`(구역별 허용 점유 시간, ERD `parking_zones.allowed_minutes`)가
  설정돼 있으면 그 시간을 넘긴 정차를 `EV_OVERSTAY`로 별도 판정한다(319번,
  등록 여부와 무관 — 등록된 차라도 시간 초과면 EV_OVERSTAY). `allowed_minutes`가
  없는 구역은 기존과 동일하게 `RESTRICTED_ZONE`만 계속 보고한다(안전 쪽 기본값).
  허용 시간 초과 판정을 서버가 아니라 엣지에서 수행하기로 결정했다(319 리뷰
  C-3). AI 설계 스펙 §6은 원래 "엣지는 점유 시작 시각만 기록하고 판단은 서버"
  였으나, 파일럿 검증에 바로 쓸 수 있는 쪽을 택했다. 서버도 같은 판정 수단을
  갖고 있으므로(parking_zones.allowed_minutes, ParkingEventType.EV_OVERSTAY,
  NotificationType.EV_OVERSTAY) **백엔드 쪽에 중복 발행 억제가 필요하다** —
  양쪽이 각자 판정하면 같은 상황에 이벤트·알림이 두 번 나간다.
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
(`--capture-frame`), 실시간 루프(`--run`).

테스트: 판정 로직 테스트는 `ai/training/tests/test_tracking_baseline.py`에 있고
`pytest ai/training/tests`로 돌린다(409). 예전에는 이 파일 안에 `--self-test`
모드로 들어 있었으나, 4,264줄 중 2,269줄이 테스트인 상태에서 판정 상태 기계를
고칠 때 결함이 반복해서 빠져나가 분리했다. `--self-test`를 남기면 프로덕션
코드가 테스트 디렉터리를 import해야 해서 함께 제거했다.

배포 시 주의: 이 스크립트는 단독 실행 파일이 아니다. 같은 디렉터리의
`calibration_utils.py`(왜곡 보정 파라미터 로딩)와 `camera_calibration.json`을
함께 복사해야 `--calibration`이 동작한다.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
import math
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping, Protocol, Sequence


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


# "전기차 충전구역이란 무엇인가"의 단일 정의. 이 질문을 하는 곳이 세 군데
# (RESTRICTED_ZONE_TYPES, _SPOT_ZONE_TYPES, classify_violation의 시간 초과
# 검사)라 상수 하나로 모은다 — 값이 늘거나 줄면 여기만 고치면 된다.
EV_ZONE_TYPES = frozenset({ZoneType.EV_FAST, ZoneType.EV_SLOW})
# 전용구역(장애인/전기차) 점유는 위반 의심으로 표시한다. 실제 등록 차량
# 여부는 서버 조회로 확정하며 이 파일의 책임 범위가 아니다.
#
# (319 리뷰 재검토, C-2) 백엔드 구현·DB·프론트는 현재 EV_CHARGING 하나만
# 쓰지만 값을 거기 맞추지 않는다 — 주차구역 계약 설계 §5.2가 DB를
# EV_FAST/EV_SLOW로 확장하고 EV_CHARGING을 ENUM에서 제거하기로 확정했고,
# 급속/완속별 허용 시간 차등(FR-EV-009)은 값을 하나로 합치면 표현할 수 없다.
# 백엔드 V2 마이그레이션이 선행돼야 이 계약이 완성된다(후속 이슈).
RESTRICTED_ZONE_TYPES = frozenset({ZoneType.DISABLED}) | EV_ZONE_TYPES
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
    EV_OVERSTAY = "EV_OVERSTAY"


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

    `allowed_minutes`(ERD `parking_zones.allowed_minutes`)는 전기차 충전구역
    (EV_FAST/EV_SLOW)의 장기 점유(EV_OVERSTAY) 판단 기준이다. 다른 구역
    타입에는 의미가 없어 기본값 None(백엔드 미설정 시 무제한 허용, 안전
    쪽으로 기움)이다.

    `allowed_minutes * 60`을 `ViolationMonitor.min_dwell_seconds`(정착 확정
    시간, 기본 600초)보다 작게 설정하면 안 된다. 예전 이 docstring은 그 경우
    "정착 확정 전까지 OBSERVING으로만 표시되고 EV_OVERSTAY 발행이
    min_dwell_seconds까지 지연된다"고 적고 있었는데, **게이트 우회가 들어온
    뒤로 둘 다 거짓이다**(319 최종 리뷰에서 정정). 실제 동작은 이렇다
    (`classify_violation`의 EV 분기가 `min_dwell_seconds` 게이트 앞에 있고,
    `test_ev_overstay_bypasses_min_dwell_gate_when_allowed_minutes_is_smaller`가
    이를 고정한다):

    - **지연되지 않는다.** EV_OVERSTAY는 게이트를 우회하므로 점유 시간이
      `allowed_minutes * 60`을 넘는 순간 발행된다. `allowed_minutes=1`,
      `min_dwell_seconds=600`이면 첫 이벤트가 600초가 아니라 60초에 나간다.
    - **그 구역에서는 RESTRICTED_ZONE이 한 번도 발행되지 않을 수 있다.**
      `allowed_minutes * 60 <= min_dwell_seconds`면 게이트가 열리는 시점에 이미
      시간 초과가 성립해 EV_OVERSTAY로 바로 대체되므로, RESTRICTED_ZONE은
      영구히 스킵된다(경계값 포함 확인). 즉 "OBSERVING으로만 표시"가 아니라
      더 이른 이벤트 1건 + 신호 1종 누락이다. RESTRICTED_ZONE은 "등록 차량
      여부 서버 조회"를 촉발하는 신호이므로 그것까지 같이 사라진다.
      이것은 원래 리뷰의 I-1 지적사항이고 **이번 MR 범위 밖(후속)이다** —
      값 검증/경고를 여기서 추가하지 않았다.
    - 위 스킵은 `allowed_minutes * 60 > min_dwell_seconds`인 정상 설정에서도
      일어날 수 있다(실측 확인). 점유 시계는 미세 이동으로 리셋되지 않지만
      게이트가 쓰는 `dwell_seconds`는 리셋되므로, 미세 이동이 잦은 차는
      `dwell_seconds`가 게이트를 못 넘는 동안 점유 시계만 자라 RESTRICTED_ZONE
      없이 EV_OVERSTAY가 첫 이벤트로 나간다(그때 이벤트에는
      `dwell_seconds ≈ 0`과 큰 `occupancy_seconds`가 함께 실린다).
      두 시계를 분리한 것(C-1)의 의도된 대가이지, 설정 실수에만 국한된
      현상이 아니다.

    DB 컬럼이 `INT`(분)이라 1~10분은 정상적으로 입력 가능한 값이고
    `min_dwell_seconds` 기본값은 600초다 — 즉 위 조합은 운영에서 실제로
    만들어질 수 있다. `allowed_minutes`는 `min_dwell_seconds`보다 충분히 크게
    설정해야 한다(운영값 60~120분).
    """

    zone_id: int
    zone_number: str
    zone_type: ZoneType
    polygon: NormalizedPolygon
    allowed_minutes: float | None = None


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
        # zoneId가 이제 사람이 직접 매기는 정수라, 폴리곤을 고치다가 구역 블록을
        # 복사-붙여넣기하면 zoneId나 zoneNumber가 중복될 수 있다. ZoneRegistry.__init__은
        # zone_id로 dict를 만들어 나중 항목이 앞 항목을 조용히 덮어쓰므로, 여기서 막지
        # 않으면 판정의 유일한 입력인 zones 파일에서 구역 하나가 에러 없이 사라진다.
        seen_ids: set[int] = set()
        seen_numbers: set[str] = set()
        for zone in zones:
            if zone.zone_id in seen_ids:
                raise BaselineError(f"구역 정의에 zoneId가 중복되었습니다: {zone.zone_id} ({path})")
            if zone.zone_number in seen_numbers:
                raise BaselineError(f"구역 정의에 zoneNumber가 중복되었습니다: {zone.zone_number} ({path})")
            seen_ids.add(zone.zone_id)
            seen_numbers.add(zone.zone_number)
        return cls(zones)

    @staticmethod
    def _parse_zone(item: Mapping[str, Any]) -> ParkingZone:
        # 예약된 wire 키: allowedMinutes(카멜케이스)는 전기차 구역의 초과주차 허용
        # 시간(분) 필드로 백엔드 계약과 zones_pilot.json이 이미 이 이름을 쓴다
        # (319번 병합 시 camelCase로 맞춤 — snake_case로 읽으면 zones_pilot.json에서
        # 항상 None이 나와 EV 구역의 초과주차 위반이 조용히 무시된다).
        try:
            zone_id = int(item["zoneId"])
            zone_number = str(item["zoneNumber"])
            zone_type = ZoneType(item["zoneType"])
            points = tuple((float(x), float(y)) for x, y in item["polygon"])
            allowed_minutes_raw = item.get("allowedMinutes")
            if isinstance(allowed_minutes_raw, bool):
                # (319 리뷰 재검토, I-3) bool은 int의 하위 타입이라 float(True) -> 1.0으로
                # 조용히 통과한다. 아래 유한 양수 검사도 못 막는다.
                raise BaselineError(f"allowedMinutes에 bool을 쓸 수 없습니다: {item!r}")
            allowed_minutes = None if allowed_minutes_raw is None else float(allowed_minutes_raw)
        except (KeyError, ValueError, TypeError) as exc:
            raise BaselineError(f"구역 정의 항목이 올바르지 않습니다: {item!r} ({exc})") from exc
        # (리뷰 반영, I-3/319) json.loads는 표준이 아닌 NaN/Infinity 리터럴을 float로
        # 그대로 파싱한다 — `nan <= 0`은 항상 False라서 `<= 0` 검사만으로는 NaN이
        # 통과해버린다. 통과하면 classify_violation의 `dwell_seconds >= allowed_minutes
        # * 60.0` 비교가 항상 False가 돼, 크래시 없이 EV_OVERSTAY가 영구적으로
        # 발동하지 않는 조용한 실패가 된다(재현 확인됨) — math.isfinite로 명시적으로 막는다.
        if allowed_minutes is not None and not (math.isfinite(allowed_minutes) and allowed_minutes > 0):
            raise BaselineError(f"allowedMinutes는 유한한 양수여야 합니다: {item!r}")
        return ParkingZone(
            zone_id=zone_id,
            zone_number=zone_number,
            zone_type=zone_type,
            polygon=NormalizedPolygon(points),
            allowed_minutes=allowed_minutes,
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
_SPOT_ZONE_TYPES = frozenset({ZoneType.GENERAL, ZoneType.DISABLED}) | EV_ZONE_TYPES


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
    occupancy_seconds: float | None = None,
) -> tuple[ViolationStatus, ParkingZone | None, float]:
    """§5.1 규칙으로 겹침 구역·스팟 침범·정차 시간을 종합해 위반 상태를 판정한다.

    여러 조건이 동시에 걸리면 통행 방해(AISLE_BLOCK) > 이중주차(DOUBLE_PARK) >
    전기차 충전구역 장기 점유(EV_OVERSTAY) > 전용구역 점유(RESTRICTED_ZONE) >
    선 침범(LINE_CROSS) > 구역 외 주차(OUT_OF_ZONE)
    순으로 하나만 보고한다.
    OUT_OF_ZONE은 다른 어떤 위반 신호도 없을 때만 성립하는 배타적 폴백이며
    (우선순위표가 아니라 아래 early-return의 배타 조건), 새 위반 신호를
    추가하면 그 조건도 함께 확장해야 한다.

    EV_OVERSTAY는 이 우선순위에 예외가 하나 있다 — 겹치는 전용구역이 둘 이상일
    때(예: 장애인 구역과 EV 구역이 붙어 있고 캘리브레이션 오차로 겹침),
    **겹침 비율이 더 높은 쪽이 DISABLED여도 시간 초과 중인 EV 구역이 있으면
    EV_OVERSTAY를 보고한다**(319 리뷰 I-4). "비율이 가장 높은 전용구역"이
    아니라 "겹치는 전용구역 전체"에서 시간 초과를 찾기 때문이다.

    EV 시간 초과는 `min_dwell_seconds` 게이트만 우회하고, 우선순위에서는
    여전히 AISLE_BLOCK·DOUBLE_PARK에 밀린다(319 최종 리뷰). 게이트를 우회하는
    이유는 게이트가 쓰는 `dwell_seconds`가 "연속 무이동 시간"이라 미세 이동이
    잦으면 영영 게이트를 못 넘어 2시간을 점유해도 OBSERVING에 머물기
    때문이다 — 이건 게이트 문제이고 우선순위 문제가 아니다.

    EV_OVERSTAY(요구사항 정의서.md:25, ERD.md:119-125 event_type)는
    RESTRICTED_ZONE의 특수화다 — 등록 여부와 무관하게 "전기차 충전구역을
    점유했다"는 사실 자체는 RESTRICTED_ZONE과 똑같이 판정하지만, 그 구역의
    `allowed_minutes`(구역별 허용 점유 시간)를 넘겨 정차했으면 "등록된
    차량이라도 시간 초과"라는 더 구체적인 상태로 대체한다. `allowed_minutes`가
    설정 안 된 구역이나 EV 충전구역이 아닌 구역에는 적용되지 않는다.

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
    여전히 의도한 동작인지 팀 확인이 필요하다. 그 특수화인 EV_OVERSTAY도
    같은 가림을 받는다 — 통행로를 막고 있거나 남의 스팟을 침범하고 있는
    동안에는 AISLE_BLOCK/DOUBLE_PARK가 EV_OVERSTAY를 가린다. 차가 그
    상황에서 벗어나면(통행로에서 빠지거나 침범을 그치면) 시간 초과는
    그대로 남아 있으므로 EV_OVERSTAY가 그때 보고된다.
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
    restricted_overlaps = [item for item in overlaps if item.zone.zone_type in RESTRICTED_ZONE_TYPES]
    restricted = restricted_overlaps[0] if restricted_overlaps else None
    # (리뷰 반영, I-4/319) 정상 배치라면 전용구역끼리 겹치지 않아야 하지만, 캘리브레이션
    # 오차 등으로 두 전용구역이 겹치는 경우 겹침 비율이 더 높은 쪽(overlaps 정렬 순서상
    # 첫 번째, 위 restricted)만 보면 그 구역이 EV 충전구역이 아닐 때 실제로는 시간
    # 초과 중인 EV 구역이 영구히 가려진다(재현 확인됨) — 겹치는 전용구역 전체에서
    # 시간 초과 중인 구역이 있는지 먼저 확인한다.
    #
    # (319 리뷰 재검토, C-1) EV 시간 초과만 "구역 점유 시간"으로 잰다.
    # dwell_seconds는 "연속 무이동 시간"이라 미세 이동/짧은 미탐지로 리셋되는데,
    # 60~120분 임계값에서는 그 리셋이 상시 발생해 기능이 발화하지 않는다.
    # occupancy_seconds를 안 넘기면 dwell_seconds로 폴백한다 — 이 함수를 직접
    # 부르는 단위 테스트가 많아서 둔 기본값이고, 실제 호출부는 ViolationMonitor
    # 하나뿐이며 항상 넘긴다.
    #
    # 한계(리뷰 Minor 2, 승인된 채로 둔다): occupancy_seconds는 호출부에서 "홈
    # 구역"(겹침 비율 1등 스팟) 점유 시간으로 계산되는데, 아래 비교는 겹치는 EV
    # 구역 전체의 allowed_minutes를 상대로 한다. 두 전용구역이 겹치는 비정상
    # 배치에서는 홈 구역이 아닌 EV 구역의 허용 시간과 비교될 수 있다.
    ev_elapsed_seconds = dwell_seconds if occupancy_seconds is None else occupancy_seconds
    overstayed_restricted = next(
        (
            item
            for item in restricted_overlaps
            if item.zone.zone_type in EV_ZONE_TYPES
            and item.zone.allowed_minutes is not None
            and ev_elapsed_seconds >= item.zone.allowed_minutes * 60.0
        ),
        None,
    )

    # (319 리뷰 재검토, C-1) 점유 시계가 허용 시간을 넘겼으면 최소 정차 시간
    # 게이트보다 먼저 확정한다. 게이트가 dwell_seconds(연속 무이동)를 쓰는데,
    # 미세 이동이 min_dwell_seconds보다 잦으면 dwell이 영영 게이트를 못 넘어
    # 2시간을 점유해도 OBSERVING에 머문다. 허용 시간(운영값 60~120분)을 넘긴
    # 점유는 그 자체로 "정착했다"는 판단에 충분하다.
    #
    # allowed_minutes를 min_dwell_seconds보다 작게 설정하면 이 분기가 게이트를
    # 실질적으로 무력화한다 — 그건 설정 오류이고 별도 지적사항(I-1)이다.
    if overstayed_restricted is not None:
        # 게이트만 우회하고 우선순위는 원래대로다(319 최종 리뷰) — AISLE_BLOCK·
        # DOUBLE_PARK가 먼저다. EV_OVERSTAY를 최상위로 올리면 점유 시계가 단조
        # 증가하는 탓에 한 번 열린 EV_OVERSTAY가 매 프레임 계속 이기고,
        # 중복 판정 키 (status, zone_id)도 안 바뀌어 그 뒤에 새로 시작된
        # AISLE_BLOCK/DOUBLE_PARK가 주차 세션 내내 영구히 보고되지 않는다
        # (재현 확인됨). 통행로 막힘은 소방 진입로·비상 통행 문제라 몇 시간을
        # 놓칠 수 없다.
        #
        # 이 분기 안에서는 게이트 없이 정상 우선순위를 적용한다 — 허용 시간
        # 초과 자체가 "정착했다"의 증거이므로 게이트가 더 붙잡아 둘 이유가 없고,
        # 같은 차에 대해 게이트만 우회한 EV_OVERSTAY와 게이트에 걸린
        # AISLE_BLOCK을 섞으면 우선순위가 뒤집힌다.
        #
        # 그 결과 무엇이 새로 발행될 수 있는가(319 최종 재리뷰: acceptable but
        # must be documented) — 게이트 우회가 EV_OVERSTAY뿐 아니라 여기의
        # AISLE_BLOCK/DOUBLE_PARK에도 적용되므로, 시간 초과 중인 차가 방금
        # 움직여 dwell_seconds가 리셋된 프레임에도 판정이 즉시 확정된다.
        # 두 갈래로 갈린다:
        #   ① 재배치 후 계속 통행로를 막는 경우 — 즉시 보고가 옳다. 게이트가 묻는
        #      질문("주차한 건가 지나가는 건가")은 이미 60~120분 점유로 답이 나와
        #      있고, 소방 진입로 보고를 min_dwell_seconds만큼 더 늦출 이유가 없다.
        #   ② 자리에서 빠져나가는 중인 경우 — 일시적으로 통행로에 걸치면서
        #      AISLE_BLOCK 1건이 새로 나간다. 이건 신규 오탐이다(56e3bb8에서는
        #      OBSERVING, 4ce596d에서는 이미 열린 EV_OVERSTAY 키가 안 바뀌어
        #      무이벤트였다).
        # 오탐이 유계인 근거: 온셋 이벤트 1건이고((status, zone_id) 키가 중복을
        # 막는다), EV 겹침이 min_overlap_ratio 아래로 떨어지는 순간 이 분기 자체가
        # 성립하지 않아 자연히 끝나며, 발행되는 이벤트에 dwell_seconds ≈ 0과
        # occupancy_seconds >= allowed_minutes*60이 함께 실리므로 서버가 이 경우를
        # ①과 구분할 수 있다. 도착(입차) 시점은 영향받지 않는다 — 누적 점유가
        # 없으면 애초에 overstayed_restricted가 None이라 이 분기에 들어오지 못한다.
        if aisle is not None:
            return ViolationStatus.AISLE_BLOCK, aisle.zone, aisle.ratio
        if blocked_zone is not None:
            return ViolationStatus.DOUBLE_PARK, blocked_zone.zone, blocked_zone.ratio
        return ViolationStatus.EV_OVERSTAY, overstayed_restricted.zone, overstayed_restricted.ratio

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
    # 매칭된 EntryEvent.gate_tracking_id(383번) — 라즈베리파이 발급 UUID.
    gate_tracking_id: str | None = None
    # (319 리뷰 재검토 2차, C-1) 중복 발행 판정 키는 status 단독이 아니라
    # (status, zone_id) 쌍이다. status만 보면 같은 위반 종류로 구역만 옮긴 경우
    # (AISLE-1을 막던 차가 AISLE-2로 이동)가 "같은 사건 계속"으로 묻혀 서버가
    # 영영 옛 구역을 막고 있다고 알게 된다. 이 키가 사건의 동일성을 담당하므로
    # open_violation을 따로 NONE으로 리셋하는 지점은 없다.
    open_violation_zone_id: str | None = None
    # (319 리뷰 재검토 2차, C-1) 마지막으로 판정이 확정된(OBSERVING이 아닌) 뒤
    # 차가 실제로 movement_epsilon을 넘겨 위치를 옮겼는가. 위 키에서 zone_id가
    # 바뀐 것을 믿을지 가르는 신호다 — 겹침 비율 1등이 흔들림만으로 뒤바뀌는
    # flapping과 진짜 구역 이동을 구분할 수 있는 유일한 정보다. 이번 프레임의
    # moved만 보면 안 된다: 이동은 과거 프레임에 일어나고, 새 구역에서 정차
    # 시간을 채워 판정이 확정되는 프레임에서는 이미 moved가 False이기 때문이다.
    moved_since_last_decision: bool = False
    # (319 리뷰 재검토, C-1) 홈 구역 점유 시계. stationary_since와 분리한 이유는
    # EV_OVERSTAY가 재는 값이 "안 움직인 시간"이 아니라 "이 자리를 차지한
    # 시간"이기 때문이다 — 같은 자리에서 13px 흔들렸다고 2시간 타이머를 0으로
    # 되돌리면 기능이 현장에서 발화하지 않는다. 실제로 움직여서(moved) 홈 구역이
    # 바뀌거나 구역을 벗어날 때만 리셋된다.
    #
    # 단, 시계의 "시작"에는 moved가 필요하지 않다(319 리뷰 재검토 3차 / 최종 리뷰).
    # occupied_zone_id가 None인 동안에는 moved와 무관하게 홈 구역을 잡는 즉시
    # 시계가 켜진다 — 홈 구역을 첫 프레임이 아니라 나중에 획득하는 트랙(겹침
    # 비율이 min_overlap_ratio 아래에서 시작해 올라가는 흔한 경우)은 그 프레임의
    # moved가 False라서, 시작에도 moved를 요구하면 occupied_zone_id가 영구히
    # None으로 남고 EV_OVERSTAY가 아예 발화하지 못한다. 이 "시작 예외"는 갱신
    # 조건식(ViolationMonitor.update)에만 적혀 있었는데, 그 조건식이 수정 라운드에서
    # 두 번 연속 결함을 냈고 그중 한 번이 정확히 이 시작을 놓친 것이었다 —
    # 규칙을 여기 필드 옆에도 남겨 둔다.
    occupied_zone_id: str | None = None
    zone_occupied_since: datetime | None = None


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
    RESTRICTED_ZONE(및 그 특수화인 EV_OVERSTAY, 319번)에서는 zone_id가 이
    차량 자신이 있는 구역을 가리키고 overlap_ratio도 이 차량 자신의 몸체
    면적 기준(차체 기준)이라 의미가 다르다.
    OUT_OF_ZONE(리뷰 반영)은 애초에 매핑되는 구역이 없으므로 zone_id/
    zone_type은 항상 None이고 overlap_ratio도 항상 0.0으로 발행된다. zone_number도
    마찬가지로 None이 된다.

    `dwell_seconds`와 `occupancy_seconds`는 서로 다른 시계다(319 리뷰 재검토,
    C-1) — 전자는 "연속 무이동 시간"(미세 이동/재정차로 리셋됨), 후자는 "홈
    구역을 점유한 시간"(실제로 움직여 구역이 바뀔 때만 리셋됨)이다. EV_OVERSTAY는
    후자로 발화하므로 전자만 보면 임계값보다 훨씬 작은 값이 보인다. 어느 시계로
    판정됐는지 서버가 알 수 있도록 둘 다 실어보낸다. 스팟형 홈 구역을 점유한
    적이 없는 차량(통행로만 걸친 AISLE_BLOCK, 구역 외 OUT_OF_ZONE 등)은
    `occupancy_seconds`가 0.0이다.
    """

    track_id: int
    plate_number: str | None
    status: ViolationStatus
    zone_id: int | None
    zone_number: str | None
    zone_type: ZoneType | None
    overlap_ratio: float
    dwell_seconds: float
    occupancy_seconds: float
    detected_at: datetime


@dataclass(frozen=True)
class EntryEvent:
    """게이트 OCR이 인식한 입차 이벤트(§2.2).

    `gate_tracking_id`(383번)는 라즈베리파이가 입차 건마다 발급하는 UUID다.
    ByteTrack이 이 트랙에 부여하는 정수 `track_id`와는 이름이 비슷하지만
    완전히 다른 값이다 — 게이트 쪽 사건 식별자와 카메라 쪽 추적 식별자를
    혼동하지 않도록 필드명을 다르게 뒀다. 매칭에는 쓰이지 않고(매칭은
    `plate_number`/`captured_at`만 사용), 매칭 성공 시 `TrackState`에
    실려 이후 위반 이벤트를 원래 입차 건과 대조할 수 있게 한다.
    """

    plate_number: str
    captured_at: datetime
    gate_tracking_id: str | None = None


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

    `track_grace_seconds`를 넘겨 트랙이 삭제된 뒤에도, 같은 자리에 차가
    `dwell_reunification_seconds` 이내에 다시 나타나면 보관해둔 `TrackState`를
    통째로 되살린다(리뷰 반영, C-1/319) — `track_grace_seconds`는 짧게 유지하되
    (스팟 회전이 빠른 일반 구역에서 떠난 차를 빨리 잊어야 다른 차가 그
    스팟의 새 주인이 될 수 있다), EV_OVERSTAY처럼 수십~백분 단위로 누적
    정차 시간을 재는 판정은 그보다 훨씬 긴 순간적 미탐지(사람/다른 차에
    잠깐 가려짐, 프레임 드롭 등)에도 견뎌야 한다는 상충을 분리해서 다룬다.
    되살아나는 것은 정차 시작 시각(`stationary_since`)만이 아니다 — 구역 점유
    시계(`occupied_zone_id`/`zone_occupied_since`), 마지막으로 발행한 사건의
    동일성(`open_violation`/`open_violation_zone_id`),
    `moved_since_last_decision`, 그리고 연결돼 있던 `plate_number`까지 그대로
    이어받는다. 번호판 상속은 재식별이 틀렸을 때(자리를 비운 앞차의 항목을
    뒷차가 물려받는 경우) 위반이 엉뚱한 차량에 귀속된다는 뜻이라, 이 정책을
    유지할지는 파일럿 관찰 후 판단할 사안으로 열어둔다.
    `dwell_reunification_seconds`보다 오래 끊기면 여전히 새 트랙으로
    취급되어 정차 시간이 리셋된다 — 이 상한을 얼마로 잡을지는 실제
    운영 환경의 가림/미탐지 지속 시간을 관찰해서 정해야 한다.
    이 값(현재 기본 30초)과 위 번호판 상속 결정은 묶여 있으므로 한쪽만 건드리면
    안 된다(319 최종 리뷰): 창을 짧게 잡은 것 자체가 번호판을 상속하기 때문에
    오귀속 노출을 줄이려는 선택이라 값을 올리려면 번호판 상속을 유지할지 함께
    재고해야 하고, 반대로 짧은 창의 대가도 실측해야 한다 — 30초를 넘는 가림은
    2시간 점유 시계를 리셋하는데 주차장에서 가장 그럴듯한 가림 원인은 그 칸 앞
    통행로에 서 있는 차(바로 이 시스템이 잡으려는 상황)이고, 리셋 후에는
    `allowed_minutes`를 다시 채워야 EV_OVERSTAY가 재발행된다. 둘 다 파일럿
    실측 항목이다.
    재식별은 track_id가 아니라 중심점 근접으로 한다 — ByteTrack은
    track_buffer(기본 30프레임)를 넘기면 새 번호를 발급하므로 번호로는 이을
    수 없다.

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
        dwell_reunification_seconds: float = 30.0,
    ) -> None:
        self._zones = zones
        self._min_overlap_ratio = min_overlap_ratio
        self._min_dwell_seconds = min_dwell_seconds
        self._movement_epsilon = movement_epsilon
        self._track_grace_seconds = track_grace_seconds
        self._spot_intrusion_ratio = spot_intrusion_ratio
        self._entry_match_window_seconds = entry_match_window_seconds
        self._entry_zone_min_overlap_ratio = entry_zone_min_overlap_ratio
        self._dwell_reunification_seconds = dwell_reunification_seconds
        self._tracks: dict[int, TrackState] = {}
        # track_grace_seconds를 넘겨 self._tracks에서 삭제된 트랙을 잠시 보관한다
        # (319 리뷰 재검토, C-1). dwell_reunification_seconds 이내에 같은 자리에
        # 차가 다시 나타나면 여기서 꺼내 정차·점유 시계를 이어간다. 그 창을 넘기면
        # _prune_reunification_archive가 버린다(메모리 누수 방지).
        #
        # track_id를 키로 쓰지 않는 이유는 _claim_reunifiable의 docstring 참고.
        self._reunification_archive: list[TrackState] = []
        self._pending_entry_events: list[EntryEvent] = []

    def _prune_reunification_archive(self, now: datetime) -> None:
        self._reunification_archive = [
            state
            for state in self._reunification_archive
            if (now - state.last_seen_at).total_seconds() <= self._dwell_reunification_seconds
        ]

    def _claim_reunifiable(self, detection: VehicleBox) -> TrackState | None:
        """보관함에서 이 탐지와 같은 차로 볼 수 있는 트랙을 찾아 꺼낸다.

        track_id로만 찾지 않는 이유: ByteTrack은 track_buffer(bytetrack.yaml 기본
        30프레임, --frame-interval-ms 200이면 약 6초)를 넘겨 사라진 트랙을 잊고,
        재등장 시 새 번호를 발급한다. 번호로만 찾으면 그 시점부터 영영 못 잇는다.

        근접 판정에 movement_epsilon을 그대로 쓴다 — 앵커 이동 판정과 같은
        잣대라 "같은 자리"의 정의가 한 곳으로 유지된다.

        다만 track_id 일치는 근접보다 우선한다(319 최종 리뷰 Minor) — 같은
        track_id 항목이 시간·거리 필터를 둘 다 통과했으면 다른 항목이 조금 더
        가까워도 그것을 claim한다. 아래 불변식이 쓰는 근거대로 track_id 일치는
        "같은 트래커 트랙"과 동의어이므로 근접보다 강한 증거다. 그 증거로 항목을
        삭제하면서 매칭에서는 무시하면, 그 차 자신의 번호판·점유 시계를 버리고
        남의 상태를 물려받게 된다(= 엉뚱한 번호판에 붙는 조작된 EV_OVERSTAY).

        불변식(리뷰 Important 1): 이 함수를 지나면 보관함에 `detection.track_id`를
        든 항목이 남지 않는다. 보관 항목과 같은 track_id를 든 탐지가 다른
        위치에서 들어왔다면(ByteTrack이 track_buffer 안에서 lost 트랙을 재획득한
        흔한 경우), 그 차가 그 자리를 떠났다는 양(+)의 증거다 — 항목을 남기면
        유령이 되어, 뒤에 그 자리에 들어온 무관한 차가 claim해버린다. 트래커는
        `persist=True`로 돌고 reset하지 않으므로 track_id는 프로세스 수명 동안
        단조 증가한다. 따라서 track_id 일치는 "같은 트래커 트랙"과 동의어다.

        선형 스캔이지만 새 트랙이 생길 때만 돌아 프레임당 비용은 무시할 수준이고,
        자료구조를 새로 만들지 않는다(`enumerate` 이터레이터 하나가 전부다).
        보관함 길이는 dwell_reunification_seconds 안에 삭제된 트랙 수가 상한이라,
        스팟 회전이 빠른 구역에서는 수십 개까지 갈 수 있다.
        """

        best_index: int | None = None
        best_distance: float | None = None
        same_id_index: int | None = None
        same_id_eligible = False
        for index, archived in enumerate(self._reunification_archive):
            is_same_id = archived.track_id == detection.track_id
            if is_same_id:
                same_id_index = index
            elapsed = (detection.captured_at - archived.last_seen_at).total_seconds()
            if not (0.0 <= elapsed <= self._dwell_reunification_seconds):
                continue
            distance = _centroid_distance(archived.last_bbox, detection.bbox)
            if distance > self._movement_epsilon:
                continue
            if is_same_id:
                same_id_eligible = True
            if best_distance is None or distance < best_distance:
                best_index, best_distance = index, distance
        if same_id_eligible:
            # (319 최종 리뷰 Minor) 같은 track_id 항목이 시간·거리 필터를 둘 다
            # 통과했으면 거리와 무관하게 그것을 claim한다. 아래 불변식이 쓰는
            # 근거("track_id 일치는 같은 트래커 트랙과 동의어")는 매칭에도 그대로
            # 유효하다 — 13px 근접보다 강한 증거다. 그 증거로 항목을 삭제하면서
            # 매칭에서는 무시하면, 조금 더 가까운 남의 항목이 이겨 그 차 자신의
            # 상태(번호판 + 점유 시계)가 버려지고 엉뚱한 번호판에 조작된
            # EV_OVERSTAY가 붙는다. same_id_eligible이 True면 same_id_index도
            # 반드시 설정돼 있다(같은 루프 반복에서 둘을 함께 정한다).
            best_index = same_id_index
        if best_index is None:
            if same_id_index is not None:
                del self._reunification_archive[same_id_index]  # 위 불변식 — 유령 방지
            return None
        state = self._reunification_archive.pop(best_index)
        if same_id_index is not None and same_id_index != best_index:
            # 근접상 다른 항목을 claim했더라도 같은 track_id를 든 항목은 같은
            # 이유로 남길 수 없다. best_index를 빼면서 그보다 뒤쪽 인덱스는
            # 한 칸 당겨진다.
            del self._reunification_archive[
                same_id_index - 1 if same_id_index > best_index else same_id_index
            ]
        state.track_id = detection.track_id  # 추적기가 새 번호를 붙였을 수 있다
        return state

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
        state = self._tracks[detection.track_id]
        state.plate_number = matched.plate_number
        state.gate_tracking_id = matched.gate_tracking_id

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
        # (319 리뷰 재검토 2차, C-1) 첫 루프가 계산한 "이번 프레임에 실제로
        # 움직였는가"를 두 번째 루프의 점유 시계 판정에 넘긴다. 홈 구역 변경만으로
        # 시계를 리셋하면, 두 스팟에 걸쳐 선 차가 가만히 있어도 겹침 비율 1등이
        # 뒤바뀔 때마다(_home_zone_overlap은 1등만 고른다) 시계가 0이 되어
        # EV_OVERSTAY가 영영 발화하지 못한다.
        moved_by_track: dict[int, bool] = {}

        if detections:
            self._prune_expired_entry_events(max(detection.captured_at for detection in detections))

        for detection in detections:
            seen_ids.add(detection.track_id)
            state = self._tracks.get(detection.track_id)
            is_new_track = state is None
            if is_new_track:
                # (319 리뷰 재검토, C-1) track_grace_seconds를 넘겨 삭제된 트랙이라도
                # 같은 자리에 dwell_reunification_seconds 이내로 다시 나타나면
                # "새 트랙"이 아니라 이어진 것으로 본다 — 안 그러면 잠깐의
                # 미탐지/가림 한 번으로 정차·점유 시계가 리셋돼, 수십~백분 단위
                # 누적 시간을 재는 EV_OVERSTAY 같은 판정이 무력화된다(재현 확인됨).
                archived = self._claim_reunifiable(detection)
                if archived is not None:
                    state = archived
                    is_new_track = False
                else:
                    state = TrackState(
                        track_id=detection.track_id,
                        last_bbox=detection.bbox,
                        last_seen_at=detection.captured_at,
                        stationary_since=detection.captured_at,
                    )
                self._tracks[detection.track_id] = state

            if not is_new_track:
                # state.last_bbox는 "정차 시작 시점의 위치" 기준점으로 유지한다.
                # 매 프레임 갱신하면 프레임 간 이동량이 매번 movement_epsilon 이하일 때
                # 누적 이동거리가 커도 계속 "정지 상태"로 남는 문제가 생긴다(리뷰 반영).
                # 재등장(reunify) 직후에도 같은 기준으로 판단한다 — 끊긴 동안 차가
                # 실제로 옮겨졌다면(anchor 대비 movement_epsilon 초과) 정당하게 리셋된다.
                moved = _centroid_distance(state.last_bbox, detection.bbox) > self._movement_epsilon
                if moved:
                    state.stationary_since = detection.captured_at
                    state.last_bbox = detection.bbox
                    state.moved_since_last_decision = True
                    # (319 리뷰 재검토, C-1) open_violation은 여기서 리셋하지 않는다.
                    # 미세 이동마다 "이미 발행한 사건"을 잊으면 같은 차·같은 자리에
                    # 대해 같은 이벤트가 반복 발행돼 FR-PARK-010을 위반한다.
                    # 중복 판정은 리셋이 아니라 (status, zone_id) 키로 한다.
                state.last_seen_at = detection.captured_at
            else:
                # 새 트랙은 비교할 앵커(last_bbox)가 없다 — "움직였다"로 취급해
                # 점유 시계를 이번 프레임부터 시작하게 한다.
                moved = True
            moved_by_track[detection.track_id] = moved

        zone_overlaps_by_track: dict[int, list[ZoneOverlap]] = {}
        home_zone_by_track: dict[int, ZoneOverlap | None] = {}
        dwell_by_track: dict[int, float] = {}
        occupancy_by_track: dict[int, float] = {}
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
            # (319 리뷰 재검토, C-1) 홈 구역 점유 시계 갱신. 같은 구역을 계속
            # 점유하는 동안에는 미세 이동과 무관하게 시계를 이어간다.
            #
            # (319 리뷰 재검토 2차, C-1) 리셋 조건에 moved를 AND로 걸었다.
            # _home_zone_overlap은 겹침 비율 1등 스팟만 고르므로, 두 스팟에 걸쳐
            # 선 차(이 코드베이스가 DOUBLE_PARK/LINE_CROSS로 모델링하는 배치)는
            # movement_epsilon 안에서 가만히 있어도 bbox 흔들림만으로 1등이
            # 뒤바뀐다. 그때마다 시계를 0으로 만들면 이 태스크가 없애려던 문제를
            # 그대로 재생산한다 — 걸쳐 선 차에는 EV_OVERSTAY가 영영 발화하지
            # 못한다. 반대로 실제 이동은 앵커 대비 movement_epsilon을 넘으므로
            # moved가 True가 되어 정상 리셋된다.
            #
            # (319 리뷰 재검토 3차, C-1) 단, moved는 시계의 "전환"에만 요구하고
            # "시작"에는 요구하지 않는다(occupied_zone_id is None). 둘을 같이 막으면,
            # 홈 구역을 첫 프레임이 아니라 나중에 획득하는 트랙(겹침 비율이
            # min_overlap_ratio 아래에서 시작해 탐지 노이즈로 위로 올라가는 흔한
            # 경우)은 그 프레임의 moved가 False라서 occupied_zone_id가 영구히 None으로
            # 남는다. 그러면 occupancy_seconds가 영영 0.0이고, EV_OVERSTAY는 이제
            # 이 시계로만 발화하므로 아예 발화하지 못한다 — C-1이 없애려던 실패
            # 유형을 그대로 재생산한다. 시계가 한 번 시작된 뒤의 모든 변경(None으로
            # 돌아가는 것 포함)은 여전히 moved를 요구하므로 flapping 방어는 유지된다.
            home = home_zone_by_track[detection.track_id]
            home_zone_id = home.zone.zone_id if home is not None else None
            if home_zone_id != state.occupied_zone_id and (
                state.occupied_zone_id is None or moved_by_track[detection.track_id]
            ):
                state.occupied_zone_id = home_zone_id
                state.zone_occupied_since = detection.captured_at if home_zone_id is not None else None
            occupancy_by_track[detection.track_id] = (
                (detection.captured_at - state.zone_occupied_since).total_seconds()
                if state.zone_occupied_since is not None
                else 0.0
            )

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
                occupancy_seconds=occupancy_by_track[detection.track_id],
            )

            # (319 리뷰 재검토 2차, C-1) 중복 판정 키는 (status, zone_id)다.
            # status 단독으로 보면 같은 위반 종류로 구역만 옮긴 경우가 묻힌다 —
            # AISLE-1을 막아 AISLE_BLOCK이 발행된 차가 AISLE-2로 이동하면 새
            # 이벤트가 안 나가고 서버는 영영 AISLE-1이 막혀 있다고 알게 된다.
            # 홈 구역이 스팟형이 아닌 트랙(AISLE_BLOCK/OUT_OF_ZONE 등)은 홈 구역이
            # 계속 None이라 "홈 구역 변경" 기반 리셋으로는 이 경우를 닫을 수 없다.
            #
            # 단, zone_id가 바뀐 것은 마지막 판정 이후 차가 실제로 움직였을 때만
            # 믿는다. _home_zone_overlap/restricted 선택은 겹침 비율 1등을 고르므로,
            # 두 스팟에 걸쳐 선 차는 가만히 있어도 1등이 뒤바뀌며(flapping) zone_id가
            # 매 프레임 요동친다 — 그걸 그대로 믿으면 같은 자리에 대해 이벤트가
            # 무한히 중복 발행된다(테스트로 재현 확인).
            event_zone_id = zone.zone_id if zone is not None else None
            zone_changed = state.moved_since_last_decision and event_zone_id != state.open_violation_zone_id
            if status not in (ViolationStatus.NONE, ViolationStatus.OBSERVING) and (
                status != state.open_violation or zone_changed
            ):
                events.append(
                    ViolationEvent(
                        track_id=detection.track_id,
                        plate_number=state.plate_number,
                        status=status,
                        zone_id=event_zone_id,
                        zone_number=zone.zone_number if zone else None,
                        zone_type=zone.zone_type if zone else None,
                        overlap_ratio=ratio,
                        dwell_seconds=dwell_seconds,
                        occupancy_seconds=occupancy_by_track[detection.track_id],
                        detected_at=detection.captured_at,
                    )
                )
            if status != ViolationStatus.OBSERVING:
                state.open_violation = status
                state.open_violation_zone_id = event_zone_id
                # 판정이 확정됐으므로 "이동 이후 미확정" 상태를 닫는다. 진짜 구역
                # 이동은 반드시 정차 시계 리셋 -> OBSERVING 구간을 지나므로 이
                # 플래그가 그 구간을 넘어 살아남고, 제자리 flapping은 애초에 이
                # 플래그를 세우지 못한다.
                state.moved_since_last_decision = False

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
                # (319 리뷰 재검토, C-1) 바로 버리지 않고 재결합 보관함으로 옮긴다 —
                # dwell_reunification_seconds 이내에 같은 자리에 차가 돌아오면
                # 정차·점유 시계와 open_violation을 이어간다.
                self._reunification_archive.append(self._tracks.pop(track_id))
            self._prune_reunification_archive(now)

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
    parser.add_argument("--dwell-reunification-seconds", type=float, default=30.0, help="track-grace-seconds를 넘겨 트랙이 삭제된 뒤에도, 같은 자리(중심점이 movement-epsilon 이내)에 이 시간 이내로 차가 다시 나타나면 정차·점유 시각을 이어간다(리뷰 반영, C-1/319). track_id가 아니라 위치로 재식별하므로 ByteTrack이 새 번호를 붙여도 이어진다. 너무 크게 잡으면 앞차가 나가고 뒷차가 같은 자리에 들어온 것을 같은 차로 오인할 수 있다.")
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
    if args.dwell_reunification_seconds < 0:
        raise BaselineError("dwell-reunification-seconds는 0 이상이어야 합니다.")
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
        dwell_reunification_seconds=args.dwell_reunification_seconds,
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


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 모드를 선택하고 최상위 오류를 구조화된 결과로 변환한다."""

    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
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

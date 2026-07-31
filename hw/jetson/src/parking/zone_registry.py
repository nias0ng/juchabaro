"""구역 정의 로딩과 구역 종류 분류.

`ai/tracking/jetson_vehicle_tracking_baseline.py:112-137`(구역 타입 상수)과
`:284-415`(`ParkingZone`, `ZoneRegistry`)에서 이관했다. 서버 GET·캐시 경로는
T-14 범위이므로 이 모듈은 파일 기반 로딩만 한다.

와이어 포맷은 camelCase다(`zoneId`, `zoneNumber`, `zoneType`, `polygon`,
`allowedMinutes`). 백엔드 응답과 `zones_pilot.json`이 이미 이 이름을 쓰므로
snake_case로 읽으면 구역이 조용히 사라진다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.parking.geometry import NormalizedPolygon
from src.parking.models import ZoneId


class ZoneRegistryError(RuntimeError):
    """구역 정의를 읽거나 검증하는 데 실패했다. 기동을 거부해야 하는 오류다."""


class ZoneType(str, Enum):
    """주차구역 종류. 설치 시 관리자가 폴리곤과 함께 1회 등록한다."""

    GENERAL = "GENERAL"
    DISABLED = "DISABLED"
    EV_FAST = "EV_FAST"
    EV_SLOW = "EV_SLOW"
    AISLE = "AISLE"
    ENTRY_EXIT = "ENTRY_EXIT"


# "전기차 충전구역이란 무엇인가"의 단일 정의. 값이 늘거나 줄면 여기만 고친다.
EV_ZONE_TYPES = frozenset({ZoneType.EV_FAST, ZoneType.EV_SLOW})
# 전용구역 — 자격 없는 차량의 진입이 위반이 되는 구역.
RESTRICTED_ZONE_TYPES = frozenset({ZoneType.DISABLED}) | EV_ZONE_TYPES
# 차를 세우는 칸. 통행로·입출차 구역은 판정용 참조 도형이라 제외한다.
SPOT_ZONE_TYPES = frozenset({ZoneType.GENERAL, ZoneType.DISABLED}) | EV_ZONE_TYPES
# 입출차 감지용 참고 구역은 주차 위반 판정 대상에서 제외한다.
IGNORED_ZONE_TYPES_FOR_PARKING = frozenset({ZoneType.ENTRY_EXIT})


@dataclass(frozen=True)
class ParkingZone:
    """설치 시 1회 캘리브레이션으로 등록되는 주차구역 정의.

    `zone_id`는 백엔드가 발급하는 기계 식별자이고 `zone_number`는 사람이 읽는
    구역 번호다. 백엔드로 나가는 페이로드는 `zone_id`를, 로그·오버레이는
    `zone_number`를 쓴다.

    `allowed_minutes`는 전기차 충전구역(`EV_FAST`/`EV_SLOW`)의 장기 점유 판단
    기준(분)이다. 다른 구역 타입에는 의미가 없어 기본값이 `None`이며, 이는
    "허용 시간 미설정"으로 해석해 초과 판정을 하지 않는다.
    """

    zone_id: ZoneId
    zone_number: str
    zone_type: ZoneType
    polygon: NormalizedPolygon
    allowed_minutes: float | None = None


class ZoneRegistry:
    """구역 정의 목록을 보관한다. 스키마는 백엔드 구역 API와 동일하게 맞춘다."""

    def __init__(self, zones: Sequence[ParkingZone]) -> None:
        self._zones: dict[ZoneId, ParkingZone] = {zone.zone_id: zone for zone in zones}

    @classmethod
    def from_file(cls, path: Path) -> "ZoneRegistry":
        """구역 정의 JSON 파일을 읽어 레지스트리를 만든다."""

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ZoneRegistryError(f"구역 정의 파일을 읽을 수 없습니다({path}): {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ZoneRegistryError(f"구역 정의 JSON 형식이 올바르지 않습니다({path}): {exc}") from exc

        zones = [cls._parse_zone(item) for item in payload.get("zones", [])]
        if not zones:
            raise ZoneRegistryError(f"구역 정의가 비어 있습니다: {path}")

        # __init__이 zone_id로 dict를 만들어 나중 항목이 앞 항목을 조용히 덮어쓴다.
        # 여기서 막지 않으면 판정의 유일한 입력에서 구역 하나가 에러 없이 사라진다.
        seen_ids: set[ZoneId] = set()
        seen_numbers: set[str] = set()
        for zone in zones:
            if zone.zone_id in seen_ids:
                raise ZoneRegistryError(f"구역 정의에 zoneId가 중복되었습니다: {zone.zone_id} ({path})")
            if zone.zone_number in seen_numbers:
                raise ZoneRegistryError(f"구역 정의에 zoneNumber가 중복되었습니다: {zone.zone_number} ({path})")
            seen_ids.add(zone.zone_id)
            seen_numbers.add(zone.zone_number)
        return cls(zones)

    @staticmethod
    def _parse_zone(item: Mapping[str, Any]) -> ParkingZone:
        try:
            zone_id = ZoneId(int(item["zoneId"]))
            zone_number = str(item["zoneNumber"])
            zone_type = ZoneType(item["zoneType"])
            points = tuple((float(x), float(y)) for x, y in item["polygon"])
            raw_minutes = item.get("allowedMinutes")
            if isinstance(raw_minutes, bool):
                # bool은 int의 하위 타입이라 float(True) -> 1.0으로 조용히 통과한다.
                raise ZoneRegistryError(f"allowedMinutes에 bool을 쓸 수 없습니다: {item!r}")
            allowed_minutes = None if raw_minutes is None else float(raw_minutes)
            polygon = NormalizedPolygon(points)
        except ZoneRegistryError:
            raise
        except (KeyError, ValueError, TypeError) as exc:
            raise ZoneRegistryError(f"구역 정의 항목이 올바르지 않습니다: {item!r} ({exc})") from exc

        # json.loads는 표준이 아닌 NaN/Infinity 리터럴을 float로 그대로 파싱한다.
        # `nan <= 0`은 항상 False라서 양수 검사만으로는 NaN이 통과한다. 통과하면
        # 초과 비교가 항상 False가 돼 위반이 영구히 발동하지 않는 조용한 실패가 된다.
        if allowed_minutes is not None and not (math.isfinite(allowed_minutes) and allowed_minutes > 0):
            raise ZoneRegistryError(f"allowedMinutes는 유한한 양수여야 합니다: {item!r}")

        return ParkingZone(
            zone_id=zone_id,
            zone_number=zone_number,
            zone_type=zone_type,
            polygon=polygon,
            allowed_minutes=allowed_minutes,
        )

    def all(self) -> tuple[ParkingZone, ...]:
        """등록된 모든 구역을 반환한다."""

        return tuple(self._zones.values())

    def get(self, zone_id: ZoneId) -> ParkingZone:
        """구역 ID로 구역 정의를 조회한다."""

        try:
            return self._zones[zone_id]
        except KeyError as exc:
            raise ZoneRegistryError(f"등록되지 않은 zoneId입니다: {zone_id}") from exc

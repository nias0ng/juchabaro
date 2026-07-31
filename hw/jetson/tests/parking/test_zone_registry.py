"""구역 정의 파일 파싱 테스트. baseline test_tracking_baseline.py:2063-2200 이관."""

import json
from pathlib import Path

import pytest

from src.parking.zone_registry import (
    EV_ZONE_TYPES,
    RESTRICTED_ZONE_TYPES,
    ParkingZone,
    ZoneNotFoundError,
    ZoneRegistry,
    ZoneRegistryError,
    ZoneType,
)

SQUARE = [[0.10, 0.20], [0.28, 0.20], [0.28, 0.55], [0.10, 0.55]]


def write_zones(tmp_path: Path, zones: list[dict]) -> Path:
    path = tmp_path / "zones.json"
    path.write_text(json.dumps({"zones": zones}, ensure_ascii=False), encoding="utf-8")
    return path


def test_parses_wire_format_camel_case(tmp_path: Path) -> None:
    path = write_zones(tmp_path, [
        {"zoneId": 12, "zoneNumber": "GEN-01", "zoneType": "GENERAL", "polygon": SQUARE},
    ])
    registry = ZoneRegistry.from_file(path)
    zone = registry.get(12)
    assert zone.zone_id == 12
    assert zone.zone_number == "GEN-01"
    assert zone.zone_type is ZoneType.GENERAL
    assert zone.allowed_minutes is None


def test_rejects_legacy_snake_case(tmp_path: Path) -> None:
    """snake_case로 읽으면 zone_id를 못 찾아 구역이 조용히 사라진다."""
    path = write_zones(tmp_path, [
        {"zone_id": 12, "zone_number": "GEN-01", "zone_type": "GENERAL", "polygon": SQUARE},
    ])
    with pytest.raises(ZoneRegistryError):
        ZoneRegistry.from_file(path)


def test_accepts_all_zone_types(tmp_path: Path) -> None:
    zones = [
        {"zoneId": i, "zoneNumber": f"Z-{i}", "zoneType": zone_type.value, "polygon": SQUARE,
         "allowedMinutes": 60 if zone_type in EV_ZONE_TYPES else None}
        for i, zone_type in enumerate(ZoneType, start=1)
    ]
    registry = ZoneRegistry.from_file(write_zones(tmp_path, zones))
    assert len(registry.all()) == len(ZoneType)


def test_rejects_empty_zones(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="비어 있습니다"):
        ZoneRegistry.from_file(write_zones(tmp_path, []))


def test_rejects_duplicate_zone_id(tmp_path: Path) -> None:
    """ZoneRegistry가 zone_id로 dict를 만들므로 중복을 막지 않으면 구역이 조용히 덮인다."""
    path = write_zones(tmp_path, [
        {"zoneId": 1, "zoneNumber": "GEN-01", "zoneType": "GENERAL", "polygon": SQUARE},
        {"zoneId": 1, "zoneNumber": "GEN-02", "zoneType": "GENERAL", "polygon": SQUARE},
    ])
    with pytest.raises(ZoneRegistryError, match="zoneId가 중복"):
        ZoneRegistry.from_file(path)


def test_rejects_duplicate_zone_number(tmp_path: Path) -> None:
    path = write_zones(tmp_path, [
        {"zoneId": 1, "zoneNumber": "GEN-01", "zoneType": "GENERAL", "polygon": SQUARE},
        {"zoneId": 2, "zoneNumber": "GEN-01", "zoneType": "GENERAL", "polygon": SQUARE},
    ])
    with pytest.raises(ZoneRegistryError, match="zoneNumber가 중복"):
        ZoneRegistry.from_file(path)


def test_parses_allowed_minutes(tmp_path: Path) -> None:
    path = write_zones(tmp_path, [
        {"zoneId": 1, "zoneNumber": "EV-01", "zoneType": "EV_FAST", "polygon": SQUARE,
         "allowedMinutes": 60},
    ])
    assert ZoneRegistry.from_file(path).get(1).allowed_minutes == 60.0


def test_rejects_bool_allowed_minutes(tmp_path: Path) -> None:
    """bool은 int의 하위 타입이라 float(True) -> 1.0으로 조용히 통과한다."""
    path = write_zones(tmp_path, [
        {"zoneId": 1, "zoneNumber": "EV-01", "zoneType": "EV_FAST", "polygon": SQUARE,
         "allowedMinutes": True},
    ])
    with pytest.raises(ZoneRegistryError, match="bool"):
        ZoneRegistry.from_file(path)


def test_rejects_non_positive_allowed_minutes(tmp_path: Path) -> None:
    path = write_zones(tmp_path, [
        {"zoneId": 1, "zoneNumber": "EV-01", "zoneType": "EV_FAST", "polygon": SQUARE,
         "allowedMinutes": 0},
    ])
    with pytest.raises(ZoneRegistryError, match="양수"):
        ZoneRegistry.from_file(path)


def test_rejects_non_finite_allowed_minutes(tmp_path: Path) -> None:
    """json.loads는 표준이 아닌 Infinity 리터럴을 float로 파싱한다.

    통과하면 초과 비교가 항상 False가 돼 EV_OVERSTAY가 영구히 발동하지 않는
    조용한 실패가 된다.
    """
    path = tmp_path / "zones.json"
    path.write_text(
        '{"zones": [{"zoneId": 1, "zoneNumber": "EV-01", "zoneType": "EV_FAST",'
        f' "polygon": {json.dumps(SQUARE)}, "allowedMinutes": Infinity}}]}}',
        encoding="utf-8",
    )
    with pytest.raises(ZoneRegistryError, match="유한한"):
        ZoneRegistry.from_file(path)


def test_rejects_invalid_polygon(tmp_path: Path) -> None:
    path = write_zones(tmp_path, [
        {"zoneId": 1, "zoneNumber": "GEN-01", "zoneType": "GENERAL",
         "polygon": [[0.1, 0.2], [0.3, 0.4]]},
    ])
    with pytest.raises(ZoneRegistryError):
        ZoneRegistry.from_file(path)


def test_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="읽을 수 없습니다"):
        ZoneRegistry.from_file(tmp_path / "does-not-exist.json")


def test_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "zones.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ZoneRegistryError, match="JSON 형식"):
        ZoneRegistry.from_file(path)


def test_get_raises_zone_not_found_for_unknown_zone() -> None:
    """조회 실패는 기동 거부 오류(ZoneRegistryError)와 다른 계층이어야 한다.

    한 타입으로 묶어 두면 프레임 하나의 조회 실패를 설정 오류와 같은 무게로
    다루게 된다.
    """
    registry = ZoneRegistry([])
    with pytest.raises(ZoneNotFoundError):
        registry.get(999)
    assert not issubclass(ZoneNotFoundError, ZoneRegistryError)


def test_get_or_none_returns_none_for_unknown_zone() -> None:
    """매 프레임 도는 판정 경로가 쓰는 조회다."""
    assert ZoneRegistry([]).get_or_none(999) is None


def test_restricted_zone_types_cover_disabled_and_ev() -> None:
    assert ZoneType.DISABLED in RESTRICTED_ZONE_TYPES
    assert EV_ZONE_TYPES <= RESTRICTED_ZONE_TYPES
    assert ZoneType.GENERAL not in RESTRICTED_ZONE_TYPES

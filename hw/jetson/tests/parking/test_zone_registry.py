"""Versioned ZoneDefinition JSON 파싱과 snapshot 관계 검증."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import (
    EV_ZONE_TYPES,
    RESTRICTED_ZONE_TYPES,
    SPOT_ZONE_TYPES,
    ZoneNotFoundError,
    ZoneRegistry,
    ZoneRegistryError,
)


SQUARE = [[0.10, 0.20], [0.28, 0.20], [0.28, 0.55], [0.10, 0.55]]


def zone(
    zone_id: int,
    zone_type: str = "GENERAL",
    **optional: Any,
) -> dict[str, Any]:
    payload = {"zoneId": zone_id, "zoneType": zone_type, "polygon": SQUARE, **optional}
    if zone_type == "ENTRY_EXIT" and "entryExitRole" not in payload:
        payload["entryExitRole"] = "ENTRY"
    return payload


def write_snapshot(
    tmp_path: Path,
    zones: list[dict[str, Any]],
    *,
    version: Any = 7,
    calibration_reference: Any = "camera-1:v2",
    **extra: Any,
) -> Path:
    path = tmp_path / "zone_definition.json"
    payload = {
        "zoneDefinitionVersion": version,
        "calibrationReference": calibration_reference,
        "zones": zones,
        **extra,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def definition(
    zone_id: int,
    *,
    zone_type: ZoneType = ZoneType.GENERAL,
    version: int = 7,
    calibration_reference: str = "camera-1:v2",
    egress_zone_ids: tuple[ZoneId, ...] = (),
    entry_exit_role: EntryExitRole | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=tuple(tuple(point) for point in SQUARE),
        zone_definition_version=ZoneDefinitionVersion(version),
        calibration_reference=calibration_reference,
        egress_zone_ids=egress_zone_ids,
        entry_exit_role=entry_exit_role,
    )


def test_parses_versioned_snapshot_into_canonical_zone_definitions(tmp_path: Path) -> None:
    path = write_snapshot(
        tmp_path,
        [
            zone(1, egressZoneIds=[2]),
            zone(2, "AISLE"),
            zone(
                3,
                "EV_CHARGING",
                allowedDurationSeconds=7200,
                chargerClass="FAST",
                egressZoneIds=[2],
            ),
        ],
    )

    registry = ZoneRegistry.from_file(path)

    assert registry.zone_definition_version == ZoneDefinitionVersion(7)
    assert registry.calibration_reference == "camera-1:v2"
    assert registry.get(1).egress_zone_ids == (ZoneId(2),)
    assert registry.get(3).zone_type is ZoneType.EV_CHARGING
    assert registry.get(3).allowed_duration_seconds == 7200.0
    assert registry.get(3).charger_class == "FAST"
    assert not hasattr(registry.get(3), "allowed_minutes")


def test_loads_tracked_pilot_deployment_snapshot() -> None:
    path = Path(__file__).parents[2] / "config" / "zone_definition.pilot.json"

    registry = ZoneRegistry.from_file(path)

    assert registry.zone_definition_version == ZoneDefinitionVersion(3)
    assert len(registry.all()) == 9
    assert registry.get(1).zone_type is ZoneType.EV_CHARGING
    assert registry.get(1).allowed_duration_seconds == 7200.0
    assert registry.get(1).egress_zone_ids == (ZoneId(7),)
    assert registry.get(7).zone_type is ZoneType.AISLE
    assert registry.get(8).zone_type is ZoneType.ENTRY_EXIT
    assert registry.get(8).entry_exit_role is EntryExitRole.ENTRY
    assert registry.get(9).zone_type is ZoneType.ENTRY_EXIT
    assert registry.get(9).entry_exit_role is EntryExitRole.EXIT


def test_accepts_all_canonical_zone_types(tmp_path: Path) -> None:
    zones = [zone(index, zone_type.value) for index, zone_type in enumerate(ZoneType, start=1)]

    registry = ZoneRegistry.from_file(write_snapshot(tmp_path, zones))

    assert {item.zone_type for item in registry.all()} == set(ZoneType)


@pytest.mark.parametrize(
    ("version", "message"),
    [(0, "양수"), (-1, "양수"), (True, "integer"), ("7", "integer")],
)
def test_rejects_invalid_zone_definition_version(
    tmp_path: Path, version: Any, message: str
) -> None:
    with pytest.raises(ZoneRegistryError, match=message):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [zone(1)], version=version))


@pytest.mark.parametrize("calibration_reference", [None, "", " camera-1:v2"])
def test_rejects_invalid_calibration_reference(
    tmp_path: Path, calibration_reference: Any
) -> None:
    with pytest.raises(ZoneRegistryError, match="calibrationReference"):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1)],
                calibration_reference=calibration_reference,
            )
        )


def test_rejects_legacy_or_unknown_fields(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="지원하지 않는 필드"):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1, "EV_CHARGING", allowedMinutes=60)],
            )
        )

    with pytest.raises(ZoneRegistryError, match="지원하지 않는 필드"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [zone(1)], source="local"))


def test_rejects_legacy_ev_fast_type(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="zoneType"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [zone(1, "EV_FAST")]))


def test_entry_exit_zone_requires_entry_or_exit_role(tmp_path: Path) -> None:
    missing_role = zone(1, "ENTRY_EXIT")
    del missing_role["entryExitRole"]

    with pytest.raises(ZoneRegistryError, match="entryExitRole"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [missing_role]))

    with pytest.raises(ZoneRegistryError, match="entryExitRole"):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1, "ENTRY_EXIT", entryExitRole="BOTH")],
            )
        )


def test_non_entry_exit_zone_rejects_entry_exit_role(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="entryExitRole"):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1, "GENERAL", entryExitRole="ENTRY")],
            )
        )


def test_rejects_empty_or_non_array_zones(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="하나 이상의"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, []))

    path = write_snapshot(tmp_path, [zone(1)])
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["zones"] = {"zoneId": 1}
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ZoneRegistryError, match="배열"):
        ZoneRegistry.from_file(path)


def test_rejects_duplicate_zone_id(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="zoneId가 중복"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [zone(1), zone(1, "AISLE")]))


@pytest.mark.parametrize("value", [True, 0, -1, "600"])
def test_rejects_invalid_allowed_duration(tmp_path: Path, value: Any) -> None:
    with pytest.raises(ZoneRegistryError, match="allowedDurationSeconds"):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1, "EV_CHARGING", allowedDurationSeconds=value)],
            )
        )


def test_rejects_non_finite_json_number(tmp_path: Path) -> None:
    path = tmp_path / "zone_definition.json"
    path.write_text(
        '{"zoneDefinitionVersion": 1, "calibrationReference": "camera-1:v2", '
        '"zones": [{"zoneId": 1, "zoneType": "EV_CHARGING", '
        f'"polygon": {json.dumps(SQUARE)}, "allowedDurationSeconds": Infinity}}]}}',
        encoding="utf-8",
    )

    with pytest.raises(ZoneRegistryError, match="유한하지 않은"):
        ZoneRegistry.from_file(path)


def test_rejects_ev_only_fields_on_non_ev_zone(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="EV_CHARGING"):
        ZoneRegistry.from_file(
            write_snapshot(tmp_path, [zone(1, allowedDurationSeconds=600)])
        )


def test_rejects_invalid_polygon(tmp_path: Path) -> None:
    invalid = zone(1)
    invalid["polygon"] = [[0.1, 0.2], [0.3, 0.4]]

    with pytest.raises(ZoneRegistryError, match="polygon"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [invalid]))


def test_accepts_spot_to_aisle_egress_relation(tmp_path: Path) -> None:
    registry = ZoneRegistry.from_file(
        write_snapshot(
            tmp_path,
            [zone(1, egressZoneIds=[2]), zone(2, "AISLE")],
        )
    )

    assert registry.get(1).egress_zone_ids == (ZoneId(2),)


@pytest.mark.parametrize(
    ("zones", "message"),
    [
        ([zone(1, egressZoneIds=[9])], "존재하지 않는"),
        ([zone(1, egressZoneIds=[2]), zone(2)], "AISLE"),
        ([zone(1, "AISLE", egressZoneIds=[2]), zone(2, "AISLE")], "주차면"),
        ([zone(1, egressZoneIds=[2, 2]), zone(2, "AISLE")], "중복"),
    ],
)
def test_rejects_invalid_egress_relation(
    tmp_path: Path, zones: list[dict[str, Any]], message: str
) -> None:
    with pytest.raises(ZoneRegistryError, match=message):
        ZoneRegistry.from_file(write_snapshot(tmp_path, zones))


def test_direct_registry_rejects_mixed_snapshot_identity() -> None:
    with pytest.raises(ZoneRegistryError, match="zoneDefinitionVersion"):
        ZoneRegistry([definition(1), definition(2, version=8)])

    with pytest.raises(ZoneRegistryError, match="calibrationReference"):
        ZoneRegistry(
            [definition(1), definition(2, calibration_reference="camera-1:v3")]
        )


def test_rejects_missing_file_and_malformed_json(tmp_path: Path) -> None:
    with pytest.raises(ZoneRegistryError, match="읽을 수 없습니다"):
        ZoneRegistry.from_file(tmp_path / "does-not-exist.json")

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not json", encoding="utf-8")
    with pytest.raises(ZoneRegistryError, match="JSON 형식"):
        ZoneRegistry.from_file(malformed)


def test_get_contract_for_unknown_zone() -> None:
    registry = ZoneRegistry([definition(1)])

    with pytest.raises(ZoneNotFoundError):
        registry.get(ZoneId(999))
    assert registry.get_or_none(ZoneId(999)) is None
    assert not issubclass(ZoneNotFoundError, ZoneRegistryError)


def test_zone_type_classifications_use_canonical_types() -> None:
    assert EV_ZONE_TYPES == {ZoneType.EV_CHARGING}
    assert RESTRICTED_ZONE_TYPES == {ZoneType.DISABLED, ZoneType.EV_CHARGING}
    assert SPOT_ZONE_TYPES == {
        ZoneType.GENERAL,
        ZoneType.DISABLED,
        ZoneType.EV_CHARGING,
    }
    assert not hasattr(ZoneType, "EV_FAST")

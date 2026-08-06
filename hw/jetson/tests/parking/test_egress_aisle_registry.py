"""egress aisle snapshot이 Zone 관측과 분리되는지 검증한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.parking.egress_aisle_registry import (
    EgressAisleRegistry,
    EgressAisleRegistryError,
)
from src.parking.models import (
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry


CALIBRATION = "pilot-calibration"


def _zones() -> ZoneRegistry:
    return ZoneRegistry(
        (
            ZoneDefinition(
                zone_id=ZoneId(1),
                zone_type=ZoneType.GENERAL,
                polygon=((0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2)),
                zone_definition_version=ZoneDefinitionVersion(3),
                calibration_reference=CALIBRATION,
            ),
            ZoneDefinition(
                zone_id=ZoneId(2),
                zone_type=ZoneType.AISLE,
                polygon=((0.2, 0.0), (0.5, 0.0), (0.5, 0.2), (0.2, 0.2)),
                zone_definition_version=ZoneDefinitionVersion(3),
                calibration_reference=CALIBRATION,
            ),
        )
    )


def _write(path: Path, **overrides) -> None:
    payload = {
        "egressAisleDefinitionVersion": 1,
        "zoneDefinitionVersion": 3,
        "calibrationReference": CALIBRATION,
        "areas": [
            {
                "egressZoneId": 101,
                "parkingZoneId": 1,
                "polygon": [[0.2, 0.0], [0.4, 0.0], [0.4, 0.2], [0.2, 0.2]],
            }
        ],
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_loads_relation_only_areas_without_adding_observed_zones(
    tmp_path: Path,
) -> None:
    path = tmp_path / "egress_aisle.json"
    zones = _zones()
    _write(path)

    registry = EgressAisleRegistry.from_file(path, zones=zones)

    assert len(zones.all()) == 2
    assert [area.egress_zone_id for area in registry.all()] == [101]
    assert registry.for_parking_zone(ZoneId(1)) == registry.all()
    assert registry.for_parking_zone(ZoneId(2)) == ()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"zoneDefinitionVersion": 4}, "version"),
        ({"calibrationReference": "other"}, "calibrationReference"),
        (
            {
                "areas": [
                    {
                        "egressZoneId": 101,
                        "parkingZoneId": 2,
                        "polygon": [[0.2, 0.0], [0.4, 0.0], [0.4, 0.2]],
                    }
                ]
            },
            "주차면",
        ),
    ],
)
def test_rejects_snapshot_mismatches(
    tmp_path: Path,
    overrides: dict,
    message: str,
) -> None:
    path = tmp_path / "invalid.json"
    _write(path, **overrides)

    with pytest.raises(EgressAisleRegistryError, match=message):
        EgressAisleRegistry.from_file(path, zones=_zones())


def test_main_snapshot_matches_zone_snapshot() -> None:
    config = Path(__file__).parents[2] / "config"
    zones = ZoneRegistry.from_file(config / "zone_definition.json")

    registry = EgressAisleRegistry.from_file(
        config / "egress_aisle.json",
        zones=zones,
    )

    assert len(registry.all()) == 6
    assert {int(area.parking_zone_id) for area in registry.all()} == set(range(1, 7))


def test_cropped_pilot_snapshot_matches_cropped_zone_snapshot() -> None:
    config = Path(__file__).parents[2] / "config"
    zones = ZoneRegistry.from_file(config / "zone_definition.pilot.json")

    registry = EgressAisleRegistry.from_file(
        config / "egress_aisle.pilot.json",
        zones=zones,
    )

    assert len(registry.all()) == 6


def test_main_and_cropped_egress_snapshots_describe_same_physical_areas() -> None:
    config = Path(__file__).parents[2] / "config"
    main_zones = ZoneRegistry.from_file(config / "zone_definition.json")
    pilot_zones = ZoneRegistry.from_file(
        config / "zone_definition.pilot.json"
    )
    main = EgressAisleRegistry.from_file(
        config / "egress_aisle.json",
        zones=main_zones,
    )
    pilot = EgressAisleRegistry.from_file(
        config / "egress_aisle.pilot.json",
        zones=pilot_zones,
    )

    # pilot 좌표는 1920px full frame의 왼쪽 150px을 자른 1770px 폭 기준이다.
    for main_area, pilot_area in zip(main.all(), pilot.all(), strict=True):
        assert main_area.egress_zone_id == pilot_area.egress_zone_id
        assert main_area.parking_zone_id == pilot_area.parking_zone_id
        expected_main_polygon = tuple(
            ((x * 1770.0 + 150.0) / 1920.0, y)
            for x, y in pilot_area.polygon
        )
        for actual, expected in zip(
            main_area.polygon,
            expected_main_polygon,
            strict=True,
        ):
            assert actual == pytest.approx(expected, abs=1e-6)

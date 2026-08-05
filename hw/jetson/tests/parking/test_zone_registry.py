"""Versioned ZoneDefinition JSON 파싱과 snapshot 관계 검증."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.parking.geometry import polygon_area, polygon_centroid
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
    polygon: tuple[tuple[float, float], ...] | None = None,
) -> ZoneDefinition:
    return ZoneDefinition(
        zone_id=ZoneId(zone_id),
        zone_type=zone_type,
        polygon=(
            tuple(tuple(point) for point in SQUARE)
            if polygon is None
            else polygon
        ),
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
                polygon=[
                    [0.28, 0.20],
                    [0.46, 0.20],
                    [0.46, 0.55],
                    [0.28, 0.55],
                ],
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


def test_loads_tracked_deployment_snapshot() -> None:
    path = Path(__file__).parents[2] / "config" / "zone_definition.json"

    registry = ZoneRegistry.from_file(path)

    assert registry.zone_definition_version == ZoneDefinitionVersion(6)
    assert len(registry.all()) == 9
    assert registry.get(1).zone_type is ZoneType.GENERAL
    assert registry.get(1).egress_zone_ids == (ZoneId(7),)
    assert registry.get(5).zone_type is ZoneType.EV_CHARGING
    assert registry.get(5).allowed_duration_seconds == 7200.0
    assert registry.get(7).zone_type is ZoneType.AISLE
    assert registry.get(8).zone_type is ZoneType.ENTRY_EXIT
    assert registry.get(8).entry_exit_role is EntryExitRole.ENTRY
    assert registry.get(9).zone_type is ZoneType.ENTRY_EXIT
    assert registry.get(9).entry_exit_role is EntryExitRole.EXIT


def test_accepts_all_canonical_zone_types(tmp_path: Path) -> None:
    zones = []
    for index, zone_type in enumerate(ZoneType, start=1):
        left = 0.05 * index
        polygon = [
            [left, 0.20],
            [left + 0.04, 0.20],
            [left + 0.04, 0.55],
            [left, 0.55],
        ]
        zones.append(zone(index, zone_type.value, polygon=polygon))

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


def test_spot_polygons_may_share_boundary_without_overlapping_area() -> None:
    left = ((0.1, 0.1), (0.2, 0.1), (0.2, 0.3), (0.1, 0.3))
    right = ((0.2, 0.1), (0.3, 0.1), (0.3, 0.3), (0.2, 0.3))

    registry = ZoneRegistry(
        (definition(1, polygon=left), definition(2, polygon=right))
    )

    assert tuple(item.zone_id for item in registry.all()) == (ZoneId(1), ZoneId(2))


def test_spot_polygons_reject_material_interior_overlap() -> None:
    first = ((0.1, 0.1), (0.25, 0.1), (0.25, 0.3), (0.1, 0.3))
    second = ((0.2, 0.1), (0.3, 0.1), (0.3, 0.3), (0.2, 0.3))

    with pytest.raises(ZoneRegistryError, match="overlapArea"):
        ZoneRegistry(
            (definition(2, polygon=second), definition(1, polygon=first))
        )


def test_small_identical_spot_polygons_are_still_rejected() -> None:
    tiny = (
        (0.50000, 0.50000),
        (0.50002, 0.50000),
        (0.50002, 0.50002),
        (0.50000, 0.50002),
    )

    with pytest.raises(ZoneRegistryError, match="overlapRatio"):
        ZoneRegistry((definition(1, polygon=tiny), definition(2, polygon=tiny)))


def test_spot_polygon_must_be_non_degenerate_and_convex() -> None:
    concave = (
        (0.1, 0.1),
        (0.3, 0.1),
        (0.2, 0.2),
        (0.3, 0.3),
        (0.1, 0.3),
    )

    with pytest.raises(ZoneRegistryError, match="convex"):
        ZoneRegistry((definition(1, polygon=concave),))


def test_spot_and_aisle_may_overlap() -> None:
    registry = ZoneRegistry(
        (definition(1), definition(2, zone_type=ZoneType.AISLE))
    )

    assert len(registry.all()) == 2


def _aisle_and_exit_registry() -> ZoneRegistry:
    """aisle이 아래쪽, exit이 위쪽인 최소 구성. 외부 방향은 -y다."""

    aisle = ZoneDefinition(
        zone_id=ZoneId(7),
        zone_type=ZoneType.AISLE,
        polygon=((0.0, 0.5), (1.0, 0.5), (1.0, 1.0), (0.0, 1.0)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
    )
    exit_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.EXIT,
    )
    return ZoneRegistry((aisle, exit_zone))


def test_exit_outward_polygon_is_the_half_away_from_the_aisle() -> None:
    registry = _aisle_and_exit_registry()
    outward = registry.exit_outward_polygons()

    assert set(outward) == {ZoneId(9)}
    piece = outward[ZoneId(9)]
    # exit 구역은 y 0.0~0.4, 중심 y=0.2. aisle이 아래(y 0.5~1.0)이므로
    # 외부 방향은 -y이고 외부측 조각은 y <= 0.2다.
    assert polygon_area(piece) == pytest.approx(0.2)
    assert max(y for _, y in piece) == pytest.approx(0.2)


def test_entry_role_zone_gets_no_outward_polygon() -> None:
    aisle = ZoneDefinition(
        zone_id=ZoneId(7),
        zone_type=ZoneType.AISLE,
        polygon=((0.0, 0.5), (1.0, 0.5), (1.0, 1.0), (0.0, 1.0)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
    )
    entry_zone = ZoneDefinition(
        zone_id=ZoneId(8),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.ENTRY,
    )
    assert ZoneRegistry((aisle, entry_zone)).exit_outward_polygons() == {}


def test_registry_without_aisle_yields_no_outward_polygon() -> None:
    """외부 방향을 유도할 수 없으면 통과를 확정하지 않는다(fail-safe)."""

    exit_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.EXIT,
    )
    assert ZoneRegistry((exit_zone,)).exit_outward_polygons() == {}


def test_exit_outward_polygons_are_cached_and_identical_across_calls() -> None:
    registry = _aisle_and_exit_registry()
    assert registry.exit_outward_polygons() == registry.exit_outward_polygons()


@pytest.mark.parametrize(
    "filename",
    ["zone_definition.json", "zone_definition.pilot.json"],
)
def test_deployed_configs_derive_outward_direction_into_upper_right(
    filename: str,
) -> None:
    """배포 설정의 외부 방향이 화면 오른쪽 위(+x, -y)임을 고정한다(571).

    현장 확인으로 차량이 화면 오른쪽 위로 빠져나간다는 것을 검증했다.
    폴리곤이 재작성되어 이 사분면을 벗어나면 판정이 조용히 반대가 되므로
    여기서 잡는다.
    """

    # 이 파일의 기존 테스트와 같은 CWD 독립 경로 관례를 쓴다
    # (`test_loads_tracked_deployment_snapshot` 참고).
    path = Path(__file__).parents[2] / "config" / filename
    registry = ZoneRegistry.from_file(path)
    outward = registry.exit_outward_polygons()
    assert set(outward) == {ZoneId(9)}

    exit_definition = registry.get(ZoneId(9))
    exit_center = polygon_centroid(exit_definition.polygon)
    piece_center = polygon_centroid(outward[ZoneId(9)])
    assert piece_center[0] > exit_center[0]
    assert piece_center[1] < exit_center[1]


_DEGENERATE_POLYGON = ((0.1, 0.1), (0.2, 0.2), (0.3, 0.3))


def test_degenerate_aisle_polygon_is_skipped_without_raising() -> None:
    """면적이 0인 AISLE polygon(CVAT 라벨링 실수 등)이 있어도 registry 구성이

    죽지 않아야 한다(fail-safe, 571). 중심을 계산할 수 없는 AISLE은
    외부 방향 유도에서 제외되고, 유효한 AISLE이 남지 않으면 그 EXIT 구역은
    결과에서 빠진다.
    """

    degenerate_aisle = ZoneDefinition(
        zone_id=ZoneId(7),
        zone_type=ZoneType.AISLE,
        polygon=_DEGENERATE_POLYGON,
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
    )
    exit_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.EXIT,
    )

    registry = ZoneRegistry((degenerate_aisle, exit_zone))

    assert registry.exit_outward_polygons() == {}


def test_degenerate_exit_polygon_is_skipped_without_raising() -> None:
    """면적이 0인 EXIT polygon이 있어도 registry 구성이 죽지 않아야 한다

    (fail-safe, 571). 중심을 계산할 수 없는 EXIT 구역은 결과에서 빠진다.
    """

    aisle = ZoneDefinition(
        zone_id=ZoneId(7),
        zone_type=ZoneType.AISLE,
        polygon=((0.0, 0.5), (1.0, 0.5), (1.0, 1.0), (0.0, 1.0)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
    )
    degenerate_exit = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=_DEGENERATE_POLYGON,
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.EXIT,
    )

    registry = ZoneRegistry((aisle, degenerate_exit))

    assert registry.exit_outward_polygons() == {}

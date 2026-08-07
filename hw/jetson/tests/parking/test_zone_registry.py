"""Versioned ZoneDefinition JSON 파싱과 snapshot 관계 검증."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from src.parking.geometry import bbox_center
from src.parking.models import (
    EntryExitRole,
    ExitTraversalDefinition,
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
from src.tracking.models import BoundingBox


SQUARE = [[0.10, 0.20], [0.28, 0.20], [0.28, 0.55], [0.10, 0.55]]
EXIT_TRAVERSAL_JSON = {
    "line": [[0.10, 0.40], [0.28, 0.40]],
    "outwardPoint": [0.19, 0.25],
    "hysteresis": 0.01,
}


def exit_traversal_definition() -> ExitTraversalDefinition:
    return ExitTraversalDefinition(
        line=((0.10, 0.40), (0.28, 0.40)),
        outward_point=(0.19, 0.25),
        hysteresis=0.01,
    )


def zone(
    zone_id: int,
    zone_type: str = "GENERAL",
    **optional: Any,
) -> dict[str, Any]:
    payload = {"zoneId": zone_id, "zoneType": zone_type, "polygon": SQUARE, **optional}
    if zone_type == "ENTRY_EXIT" and "entryExitRole" not in payload:
        payload["entryExitRole"] = "ENTRY"
    if (
        zone_type == "ENTRY_EXIT"
        and payload.get("entryExitRole") == "EXIT"
        and "exitTraversal" not in payload
    ):
        payload["exitTraversal"] = EXIT_TRAVERSAL_JSON
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
    exit_traversal: ExitTraversalDefinition | None = None,
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
        exit_traversal=(
            exit_traversal_definition()
            if entry_exit_role is EntryExitRole.EXIT and exit_traversal is None
            else exit_traversal
        ),
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


def test_loads_tracked_main_deployment_snapshot() -> None:
    path = Path(__file__).parents[2] / "config" / "zone_definition.json"

    registry = ZoneRegistry.from_file(path)

    assert registry.zone_definition_version == ZoneDefinitionVersion(2)
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
    assert registry.get(9).exit_traversal is not None


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


def test_exit_role_requires_exit_traversal(tmp_path: Path) -> None:
    exit_zone = zone(1, "ENTRY_EXIT", entryExitRole="EXIT")
    del exit_zone["exitTraversal"]

    with pytest.raises(ZoneRegistryError, match="exitTraversal.*반드시"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [exit_zone]))


@pytest.mark.parametrize(
    "zone_payload",
    [
        zone(1, "ENTRY_EXIT", entryExitRole="ENTRY", exitTraversal=EXIT_TRAVERSAL_JSON),
        zone(1, "GENERAL", exitTraversal=EXIT_TRAVERSAL_JSON),
    ],
)
def test_entry_and_other_zones_reject_exit_traversal(
    tmp_path: Path,
    zone_payload: dict[str, Any],
) -> None:
    with pytest.raises(ZoneRegistryError, match="exitTraversal.*만 사용"):
        ZoneRegistry.from_file(write_snapshot(tmp_path, [zone_payload]))


@pytest.mark.parametrize("missing", ["line", "outwardPoint", "hysteresis"])
def test_exit_traversal_requires_exact_fields(tmp_path: Path, missing: str) -> None:
    traversal = {
        "line": [[0.1, 0.4], [0.3, 0.4]],
        "outwardPoint": [0.2, 0.2],
        "hysteresis": 0.01,
    }
    del traversal[missing]

    with pytest.raises(ZoneRegistryError, match="필수 필드"):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1, "ENTRY_EXIT", entryExitRole="EXIT", exitTraversal=traversal)],
            )
        )

    traversal[missing] = EXIT_TRAVERSAL_JSON[missing]
    traversal["mode"] = "AUTO"
    with pytest.raises(ZoneRegistryError, match="지원하지 않는 필드"):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1, "ENTRY_EXIT", entryExitRole="EXIT", exitTraversal=traversal)],
            )
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("line", [[0.1, 0.4]], "두 개"),
        ("line", [[0.1, 0.4], [0.1, 0.4]], "distinct"),
        ("line", [[-0.1, 0.4], [0.3, 0.4]], "0~1"),
        ("outwardPoint", [0.2, 0.4], "must not lie"),
        ("outwardPoint", [0.2], r"\[x, y\]"),
        ("hysteresis", -0.01, "0 이상"),
        ("hysteresis", True, "숫자"),
        ("hysteresis", float("inf"), "유한하지 않은"),
    ],
)
def test_rejects_invalid_exit_traversal_geometry(
    tmp_path: Path,
    field: str,
    value: Any,
    message: str,
) -> None:
    traversal = {
        "line": [[0.1, 0.4], [0.3, 0.4]],
        "outwardPoint": [0.2, 0.2],
        "hysteresis": 0.01,
    }
    traversal[field] = value

    with pytest.raises(ZoneRegistryError, match=message):
        ZoneRegistry.from_file(
            write_snapshot(
                tmp_path,
                [zone(1, "ENTRY_EXIT", entryExitRole="EXIT", exitTraversal=traversal)],
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


def _exit_registry() -> ZoneRegistry:
    exit_zone = ZoneDefinition(
        zone_id=ZoneId(9),
        zone_type=ZoneType.ENTRY_EXIT,
        polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="cam-1-v1",
        entry_exit_role=EntryExitRole.EXIT,
        exit_traversal=ExitTraversalDefinition(
            line=((0.0, 0.5), (1.0, 0.5)),
            outward_point=(0.5, 0.1),
            hysteresis=0.01,
        ),
    )
    return ZoneRegistry((exit_zone,))


def test_exit_traversal_signed_offset_points_to_explicit_outward_point() -> None:
    registry = _exit_registry()
    traversals = registry.exit_traversals()

    assert set(traversals) == {ZoneId(9)}
    traversal = traversals[ZoneId(9)]
    assert traversal.signed_offset((0.5, 0.1)) > 0.0
    assert traversal.signed_offset((0.5, 0.9)) < 0.0
    assert traversal.signed_offset((0.5, 0.5)) == pytest.approx(0.0)
    assert traversal.outward_unit_normal == pytest.approx((0.0, -1.0))
    assert math.hypot(*traversal.outward_unit_normal) == pytest.approx(1.0)


def test_reversing_line_points_does_not_reverse_outward_sign() -> None:
    forward = ExitTraversalDefinition(
        line=((0.0, 0.5), (1.0, 0.5)),
        outward_point=(0.5, 0.1),
        hysteresis=0.0,
    )
    reversed_line = ExitTraversalDefinition(
        line=((1.0, 0.5), (0.0, 0.5)),
        outward_point=(0.5, 0.1),
        hysteresis=0.0,
    )

    assert forward.signed_offset((0.5, 0.1)) > 0.0
    assert reversed_line.signed_offset((0.5, 0.1)) > 0.0
    assert forward.outward_unit_normal == pytest.approx(
        reversed_line.outward_unit_normal
    )


def test_entry_role_zone_gets_no_outward_baseline() -> None:
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
    assert ZoneRegistry((aisle, entry_zone)).exit_traversals() == {}


def test_exit_traversal_does_not_depend_on_an_aisle_zone() -> None:
    assert set(_exit_registry().exit_traversals()) == {ZoneId(9)}


def test_exit_traversal_query_returns_an_isolated_mapping() -> None:
    registry = _exit_registry()
    first = registry.exit_traversals()
    first.clear()

    assert set(registry.exit_traversals()) == {ZoneId(9)}


@pytest.mark.parametrize(
    "filename",
    ["zone_definition.json", "zone_definition.pilot.json"],
)
def test_deployed_configs_explicitly_define_outward_direction_into_upper_right(
    filename: str,
) -> None:
    """배포 설정의 명시적 외향 방향을 화면 오른쪽 위로 고정한다.

    현장 확인으로 차량이 화면 오른쪽 위로 빠져나간다는 것을 검증했다.
    폴리곤이 재작성되어 이 사분면을 벗어나면 판정이 조용히 반대가 되므로
    여기서 잡는다.
    """

    # 이 파일의 기존 테스트와 같은 CWD 독립 경로 관례를 쓴다
    # (`test_loads_tracked_deployment_snapshot` 참고).
    path = Path(__file__).parents[2] / "config" / filename
    registry = ZoneRegistry.from_file(path)
    traversals = registry.exit_traversals()
    assert set(traversals) == {ZoneId(9)}

    direction = traversals[ZoneId(9)].outward_unit_normal
    assert direction[0] > 0.0
    assert direction[1] < 0.0
    assert traversals[ZoneId(9)].hysteresis == pytest.approx(0.01)


@pytest.mark.parametrize(
    "filename",
    ["zone_definition.json", "zone_definition.pilot.json"],
)
def test_real_scale_car_bbox_center_determines_outward_side(filename: str) -> None:
    """Finding 1 회귀: bbox와 outward sub-polygon의 겹침 대신 중심의 부호를

    검사해야 하는 이유를 실측 스케일로 고정한다. 실제 차량 bbox(약
    0.11 x 0.16)는 outward half-zone보다 커서, "겹침 면적 > 0"으로
    판정하면 출차 통로 안쪽에 정지한 차도 거의 항상 outward로 오판된다
    (독립적으로 검산: zone_definition.json에서 안쪽 절반 깊이가 outward
    축 기준 약 0.105인데 실측 차량 투영은 약 0.193으로 1.84배 크다).
    중심 판정은 이 문제가 없다.

    아래 두 bbox는 두 배포 snapshot의 명시적 `exitTraversal`
    기준선에 투영했을 때 각각 양수·음수가 되도록 고정한 실차량
    크기의 회귀 샘플이다.
    """

    outer_bbox = BoundingBox(0.624012, 0.059889, 0.734012, 0.219889)
    inner_bbox = BoundingBox(0.595881, 0.112886, 0.705881, 0.272886)

    path = Path(__file__).parents[2] / "config" / filename
    registry = ZoneRegistry.from_file(path)
    traversal = registry.exit_traversals()[ZoneId(9)]

    outer_offset = traversal.signed_offset(bbox_center(outer_bbox))
    inner_offset = traversal.signed_offset(bbox_center(inner_bbox))

    assert outer_offset > 0.0
    assert inner_offset < 0.0


def test_direct_zone_definition_enforces_exit_traversal_scope() -> None:
    with pytest.raises(ValueError, match="requires exit_traversal"):
        ZoneDefinition(
            zone_id=ZoneId(9),
            zone_type=ZoneType.ENTRY_EXIT,
            polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
            zone_definition_version=ZoneDefinitionVersion(1),
            calibration_reference="cam-1-v1",
            entry_exit_role=EntryExitRole.EXIT,
        )

    with pytest.raises(ValueError, match="must not carry"):
        ZoneDefinition(
            zone_id=ZoneId(8),
            zone_type=ZoneType.ENTRY_EXIT,
            polygon=((0.0, 0.0), (1.0, 0.0), (1.0, 0.4), (0.0, 0.4)),
            zone_definition_version=ZoneDefinitionVersion(1),
            calibration_reference="cam-1-v1",
            entry_exit_role=EntryExitRole.ENTRY,
            exit_traversal=exit_traversal_definition(),
        )

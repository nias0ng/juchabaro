"""이중주차 판정용 egress aisle snapshot을 검증하고 조회한다.

Egress aisle은 ZoneVisit·Assignment·AISLE_BLOCK의 관측 Zone이 아니다.
주차면별 출차 방해 관계의 기하 근거만 제공하며, 실행 중에
hot replacement하지 않는다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import math
from pathlib import Path
from typing import Any

from src.parking.geometry import is_convex_polygon
from src.parking.models import (
    EgressAisleDefinition,
    EgressAisleDefinitionVersion,
    EgressAisleId,
    NormalizedPolygon,
    ZoneDefinitionVersion,
    ZoneId,
)
from src.parking.zone_registry import SPOT_ZONE_TYPES, ZoneRegistry


_SNAPSHOT_FIELDS = frozenset(
    {
        "egressAisleDefinitionVersion",
        "zoneDefinitionVersion",
        "calibrationReference",
        "areas",
    }
)
_AREA_FIELDS = frozenset({"egressZoneId", "parkingZoneId", "polygon"})


class EgressAisleRegistryError(RuntimeError):
    """egress aisle snapshot 전체를 적용할 수 없다."""


class EgressAisleNotFoundError(LookupError):
    """실행 중 registry에 없는 egress ID를 조회했다."""


class EgressAisleRegistry:
    """한 배포의 검증된 egress aisle 정의 집합."""

    def __init__(
        self,
        definitions: Sequence[EgressAisleDefinition],
        *,
        egress_aisle_definition_version: EgressAisleDefinitionVersion,
        zone_definition_version: ZoneDefinitionVersion,
        calibration_reference: str,
        zones: ZoneRegistry,
    ) -> None:
        ordered = tuple(definitions)
        self._validate_snapshot(
            ordered,
            egress_aisle_definition_version=egress_aisle_definition_version,
            zone_definition_version=zone_definition_version,
            calibration_reference=calibration_reference,
            zones=zones,
        )
        self._definitions = ordered
        self._by_id = {
            definition.egress_zone_id: definition for definition in ordered
        }
        by_parking_zone: dict[ZoneId, list[EgressAisleDefinition]] = {}
        for definition in ordered:
            by_parking_zone.setdefault(definition.parking_zone_id, []).append(
                definition
            )
        self._by_parking_zone = {
            zone_id: tuple(areas) for zone_id, areas in by_parking_zone.items()
        }
        self._egress_aisle_definition_version = (
            egress_aisle_definition_version
        )
        self._zone_definition_version = zone_definition_version
        self._calibration_reference = calibration_reference

    @classmethod
    def empty(cls, zones: ZoneRegistry) -> "EgressAisleRegistry":
        """이중주차 관계를 사용하지 않는 테스트·배포용 빈 snapshot."""

        return cls(
            (),
            egress_aisle_definition_version=EgressAisleDefinitionVersion(1),
            zone_definition_version=zones.zone_definition_version,
            calibration_reference=zones.calibration_reference,
            zones=zones,
        )

    @classmethod
    def from_file(
        cls,
        path: Path,
        *,
        zones: ZoneRegistry,
    ) -> "EgressAisleRegistry":
        """UTF-8 JSON snapshot과 ZoneDefinition 좌표계를 함께 검증한다."""

        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EgressAisleRegistryError(
                f"egress aisle 정의 파일을 읽을 수 없습니다({path}): {exc}"
            ) from exc
        try:
            payload = json.loads(raw_text, parse_constant=_reject_non_finite)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EgressAisleRegistryError(
                f"egress aisle JSON 형식이 올바르지 않습니다({path}): {exc}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise EgressAisleRegistryError(
                "egress aisle snapshot 최상위 값은 object여야 합니다"
            )
        _require_exact_fields(payload, _SNAPSHOT_FIELDS, "egress aisle snapshot")

        egress_version = EgressAisleDefinitionVersion(
            _parse_positive_integer(
                payload["egressAisleDefinitionVersion"],
                "egressAisleDefinitionVersion",
            )
        )
        zone_version = ZoneDefinitionVersion(
            _parse_positive_integer(
                payload["zoneDefinitionVersion"], "zoneDefinitionVersion"
            )
        )
        calibration_reference = _parse_non_empty_string(
            payload["calibrationReference"], "calibrationReference"
        )
        raw_areas = payload["areas"]
        if not isinstance(raw_areas, list):
            raise EgressAisleRegistryError("areas는 배열이어야 합니다")

        definitions = tuple(
            cls._parse_area(
                item,
                index=index,
                egress_version=egress_version,
                zone_version=zone_version,
                calibration_reference=calibration_reference,
            )
            for index, item in enumerate(raw_areas)
        )
        return cls(
            definitions,
            egress_aisle_definition_version=egress_version,
            zone_definition_version=zone_version,
            calibration_reference=calibration_reference,
            zones=zones,
        )

    @staticmethod
    def _parse_area(
        item: Any,
        *,
        index: int,
        egress_version: EgressAisleDefinitionVersion,
        zone_version: ZoneDefinitionVersion,
        calibration_reference: str,
    ) -> EgressAisleDefinition:
        context = f"areas[{index}]"
        if not isinstance(item, Mapping):
            raise EgressAisleRegistryError(f"{context}는 object여야 합니다")
        _require_exact_fields(item, _AREA_FIELDS, context)
        try:
            return EgressAisleDefinition(
                egress_zone_id=EgressAisleId(
                    _parse_positive_integer(
                        item["egressZoneId"],
                        f"{context}.egressZoneId",
                    )
                ),
                parking_zone_id=ZoneId(
                    _parse_positive_integer(
                        item["parkingZoneId"],
                        f"{context}.parkingZoneId",
                    )
                ),
                polygon=_parse_polygon(item["polygon"], f"{context}.polygon"),
                egress_aisle_definition_version=egress_version,
                zone_definition_version=zone_version,
                calibration_reference=calibration_reference,
            )
        except ValueError as exc:
            raise EgressAisleRegistryError(
                f"{context}가 계약을 위반했습니다: {exc}"
            ) from exc

    @staticmethod
    def _validate_snapshot(
        definitions: tuple[EgressAisleDefinition, ...],
        *,
        egress_aisle_definition_version: EgressAisleDefinitionVersion,
        zone_definition_version: ZoneDefinitionVersion,
        calibration_reference: str,
        zones: ZoneRegistry,
    ) -> None:
        if int(egress_aisle_definition_version) <= 0:
            raise EgressAisleRegistryError(
                "egressAisleDefinitionVersion은 양의 정수여야 합니다"
            )
        if zone_definition_version != zones.zone_definition_version:
            raise EgressAisleRegistryError(
                "egress aisle과 ZoneDefinition version이 다릅니다: "
                f"egress={zone_definition_version}, "
                f"zones={zones.zone_definition_version}"
            )
        if calibration_reference != zones.calibration_reference:
            raise EgressAisleRegistryError(
                "egress aisle과 ZoneDefinition calibrationReference가 다릅니다: "
                f"egress={calibration_reference}, zones={zones.calibration_reference}"
            )

        seen_ids: set[EgressAisleId] = set()
        for definition in definitions:
            if definition.egress_zone_id in seen_ids:
                raise EgressAisleRegistryError(
                    "egressZoneId가 중복되었습니다: "
                    f"{definition.egress_zone_id}"
                )
            seen_ids.add(definition.egress_zone_id)
            if (
                definition.egress_aisle_definition_version
                != egress_aisle_definition_version
                or definition.zone_definition_version != zone_definition_version
                or definition.calibration_reference != calibration_reference
            ):
                raise EgressAisleRegistryError(
                    "egress aisle 항목이 snapshot metadata와 다릅니다"
                )
            parking_zone = zones.get_or_none(definition.parking_zone_id)
            if parking_zone is None:
                raise EgressAisleRegistryError(
                    "egress aisle이 없는 parkingZoneId를 참조합니다: "
                    f"{definition.parking_zone_id}"
                )
            if parking_zone.zone_type not in SPOT_ZONE_TYPES:
                raise EgressAisleRegistryError(
                    "egress aisle의 parkingZoneId는 주차면이어야 합니다: "
                    f"{definition.parking_zone_id}"
                )
            if not is_convex_polygon(definition.polygon):
                raise EgressAisleRegistryError(
                    f"egressZoneId {definition.egress_zone_id}의 polygon은 "
                    "non-degenerate convex polygon이어야 합니다"
                )

    @property
    def egress_aisle_definition_version(self) -> EgressAisleDefinitionVersion:
        return self._egress_aisle_definition_version

    @property
    def zone_definition_version(self) -> ZoneDefinitionVersion:
        return self._zone_definition_version

    @property
    def calibration_reference(self) -> str:
        return self._calibration_reference

    def all(self) -> tuple[EgressAisleDefinition, ...]:
        return self._definitions

    def get(self, egress_zone_id: EgressAisleId) -> EgressAisleDefinition:
        definition = self._by_id.get(egress_zone_id)
        if definition is None:
            raise EgressAisleNotFoundError(
                f"egress aisle을 찾을 수 없습니다: {egress_zone_id}"
            )
        return definition

    def get_or_none(
        self, egress_zone_id: EgressAisleId
    ) -> EgressAisleDefinition | None:
        return self._by_id.get(egress_zone_id)

    def for_parking_zone(
        self, parking_zone_id: ZoneId
    ) -> tuple[EgressAisleDefinition, ...]:
        return self._by_parking_zone.get(parking_zone_id, ())


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], context: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise EgressAisleRegistryError(
            f"{context} 필드가 정확히 일치하지 않습니다: "
            f"missing={missing}, unknown={unknown}"
        )


def _parse_positive_integer(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EgressAisleRegistryError(f"{field_name}은 양의 정수여야 합니다")
    return value


def _parse_non_empty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EgressAisleRegistryError(
            f"{field_name}은 빈 문자열이면 안 됩니다"
        )
    return value


def _parse_polygon(value: Any, field_name: str) -> NormalizedPolygon:
    if not isinstance(value, list) or len(value) < 3:
        raise EgressAisleRegistryError(
            f"{field_name}은 3개 이상의 점을 가진 배열이어야 합니다"
        )
    points: list[tuple[float, float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, list) or len(point) != 2:
            raise EgressAisleRegistryError(
                f"{field_name}[{index}]는 [x, y]여야 합니다"
            )
        coordinates: list[float] = []
        for coordinate in point:
            if (
                isinstance(coordinate, bool)
                or not isinstance(coordinate, (int, float))
                or not math.isfinite(float(coordinate))
                or not 0.0 <= float(coordinate) <= 1.0
            ):
                raise EgressAisleRegistryError(
                    f"{field_name}[{index}]의 좌표는 "
                    "0~1 유한 숫자여야 합니다"
                )
            coordinates.append(float(coordinate))
        points.append((coordinates[0], coordinates[1]))
    return tuple(points)


def _reject_non_finite(value: str) -> None:
    raise ValueError(
        f"유한하지 않은 JSON 숫자는 허용하지 않습니다: {value}"
    )

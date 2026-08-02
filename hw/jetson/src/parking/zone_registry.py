"""Versioned JSON 구역 정의를 읽어 불변 ``ZoneRegistry``를 구성한다.

구역 JSON은 배포 설정의 원본이며 SQLite로 옮기지 않는다. 한 파일은 하나의
``zoneDefinitionVersion``과 ``calibrationReference``를 가지며, 모든 항목을
검증한 뒤에만 registry를 만든다. 실행 중 교체나 부분 갱신은 이 모듈의 책임이
아니다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.parking.models import (
    NormalizedPolygon,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)


EV_ZONE_TYPES = frozenset({ZoneType.EV_CHARGING})
RESTRICTED_ZONE_TYPES = frozenset({ZoneType.DISABLED, ZoneType.EV_CHARGING})
SPOT_ZONE_TYPES = frozenset({ZoneType.GENERAL, ZoneType.DISABLED, ZoneType.EV_CHARGING})
IGNORED_ZONE_TYPES_FOR_PARKING = frozenset({ZoneType.ENTRY_EXIT})

_SNAPSHOT_FIELDS = frozenset({"zoneDefinitionVersion", "calibrationReference", "zones"})
_ZONE_REQUIRED_FIELDS = frozenset({"zoneId", "zoneType", "polygon"})
_ZONE_OPTIONAL_FIELDS = frozenset(
    {"allowedDurationSeconds", "chargerClass", "egressZoneIds"}
)


class ZoneRegistryError(RuntimeError):
    """구역 정의 파일을 읽거나 전체 snapshot을 검증하지 못했다."""


class ZoneNotFoundError(LookupError):
    """실행 중 registry에 없는 ``zoneId``를 조회했다."""


class ZoneRegistry:
    """한 배포 version의 검증된 ``ZoneDefinition`` 집합.

    생성 후 내용을 바꾸는 API를 제공하지 않는다. 새 version 적용은 active scope가
    없는 통제된 재기동에서 새 registry를 구성하는 방식으로만 수행한다.
    """

    def __init__(self, definitions: Sequence[ZoneDefinition]) -> None:
        ordered = tuple(definitions)
        self._validate_definitions(ordered)
        self._definitions = ordered
        self._zones = {definition.zone_id: definition for definition in ordered}
        self._zone_definition_version = ordered[0].zone_definition_version
        self._calibration_reference = ordered[0].calibration_reference

    @property
    def zone_definition_version(self) -> ZoneDefinitionVersion:
        """이 registry에 원자적으로 적용된 구역 정의 version."""

        return self._zone_definition_version

    @property
    def calibration_reference(self) -> str:
        """polygon 좌표계와 일치해야 하는 카메라 calibration 식별자."""

        return self._calibration_reference

    @classmethod
    def from_file(cls, path: Path) -> "ZoneRegistry":
        """UTF-8 JSON snapshot 전체를 검증하고 registry를 만든다.

        파일 누락, 구형 필드, 잘못된 relation 또는 일부 항목 오류가 있으면 빈
        registry로 대체하지 않고 기동 오류인 ``ZoneRegistryError``를 발생시킨다.
        """

        try:
            raw_text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ZoneRegistryError(f"구역 정의 파일을 읽을 수 없습니다({path}): {exc}") from exc

        try:
            payload = json.loads(raw_text, parse_constant=_reject_non_finite_json_number)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ZoneRegistryError(f"구역 정의 JSON 형식이 올바르지 않습니다({path}): {exc}") from exc

        if not isinstance(payload, Mapping):
            raise ZoneRegistryError(f"구역 정의 최상위 값은 object여야 합니다: {path}")

        _require_exact_fields(payload, _SNAPSHOT_FIELDS, context="구역 정의 snapshot")
        version = _parse_positive_integer(
            payload["zoneDefinitionVersion"], field_name="zoneDefinitionVersion"
        )
        calibration_reference = _parse_non_empty_string(
            payload["calibrationReference"], field_name="calibrationReference"
        )

        raw_zones = payload["zones"]
        if not isinstance(raw_zones, list) or not raw_zones:
            raise ZoneRegistryError("zones는 하나 이상의 구역을 가진 배열이어야 합니다")

        definitions = tuple(
            cls._parse_zone(
                item,
                version=ZoneDefinitionVersion(version),
                calibration_reference=calibration_reference,
                index=index,
            )
            for index, item in enumerate(raw_zones)
        )
        return cls(definitions)

    @staticmethod
    def _parse_zone(
        item: Any,
        *,
        version: ZoneDefinitionVersion,
        calibration_reference: str,
        index: int,
    ) -> ZoneDefinition:
        context = f"zones[{index}]"
        if not isinstance(item, Mapping):
            raise ZoneRegistryError(f"{context}는 object여야 합니다")

        _require_fields(
            item,
            required=_ZONE_REQUIRED_FIELDS,
            optional=_ZONE_OPTIONAL_FIELDS,
            context=context,
        )

        zone_id = ZoneId(_parse_integer(item["zoneId"], field_name=f"{context}.zoneId"))
        try:
            zone_type = ZoneType(item["zoneType"])
        except (TypeError, ValueError) as exc:
            allowed = ", ".join(zone_type.value for zone_type in ZoneType)
            raise ZoneRegistryError(
                f"{context}.zoneType은 다음 중 하나여야 합니다: {allowed}"
            ) from exc

        polygon = _parse_polygon(item["polygon"], field_name=f"{context}.polygon")
        allowed_duration_seconds = _parse_optional_positive_number(
            item.get("allowedDurationSeconds"),
            field_name=f"{context}.allowedDurationSeconds",
        )
        charger_class = _parse_optional_non_empty_string(
            item.get("chargerClass"), field_name=f"{context}.chargerClass"
        )
        egress_zone_ids = _parse_zone_id_array(
            item.get("egressZoneIds", []), field_name=f"{context}.egressZoneIds"
        )

        try:
            return ZoneDefinition(
                zone_id=zone_id,
                zone_type=zone_type,
                polygon=polygon,
                zone_definition_version=version,
                calibration_reference=calibration_reference,
                allowed_duration_seconds=allowed_duration_seconds,
                charger_class=charger_class,
                egress_zone_ids=egress_zone_ids,
            )
        except ValueError as exc:
            raise ZoneRegistryError(f"{context}가 ZoneDefinition 계약을 위반했습니다: {exc}") from exc

    @staticmethod
    def _validate_definitions(definitions: tuple[ZoneDefinition, ...]) -> None:
        if not definitions:
            raise ZoneRegistryError("구역 정의가 비어 있습니다")

        versions = {definition.zone_definition_version for definition in definitions}
        if len(versions) != 1:
            raise ZoneRegistryError("한 registry의 모든 구역은 같은 zoneDefinitionVersion이어야 합니다")

        calibration_references = {definition.calibration_reference for definition in definitions}
        if len(calibration_references) != 1:
            raise ZoneRegistryError("한 registry의 모든 구역은 같은 calibrationReference를 사용해야 합니다")

        zones: dict[ZoneId, ZoneDefinition] = {}
        for definition in definitions:
            if definition.zone_id in zones:
                raise ZoneRegistryError(f"구역 정의에 zoneId가 중복되었습니다: {definition.zone_id}")
            if len(set(definition.egress_zone_ids)) != len(definition.egress_zone_ids):
                raise ZoneRegistryError(
                    f"zoneId {definition.zone_id}의 egressZoneIds가 중복되었습니다"
                )
            if definition.egress_zone_ids and definition.zone_type not in SPOT_ZONE_TYPES:
                raise ZoneRegistryError(
                    f"zoneId {definition.zone_id}: egressZoneIds는 주차면 Zone에만 유효합니다"
                )
            zones[definition.zone_id] = definition

        for definition in definitions:
            for egress_zone_id in definition.egress_zone_ids:
                egress = zones.get(egress_zone_id)
                if egress is None:
                    raise ZoneRegistryError(
                        f"zoneId {definition.zone_id}가 존재하지 않는 egress zoneId "
                        f"{egress_zone_id}를 참조합니다"
                    )
                if egress.zone_type is not ZoneType.AISLE:
                    raise ZoneRegistryError(
                        f"zoneId {definition.zone_id}의 egress zoneId {egress_zone_id}는 AISLE이어야 합니다"
                    )

    def all(self) -> tuple[ZoneDefinition, ...]:
        """파일에 기록된 순서대로 모든 구역 정의를 반환한다."""

        return self._definitions

    def get(self, zone_id: ZoneId) -> ZoneDefinition:
        """``zoneId``로 조회하고, 없으면 ``ZoneNotFoundError``를 발생시킨다."""

        zone = self._zones.get(zone_id)
        if zone is None:
            raise ZoneNotFoundError(f"등록되지 않은 zoneId입니다: {zone_id}")
        return zone

    def get_or_none(self, zone_id: ZoneId) -> ZoneDefinition | None:
        """판정 경로에서 ``zoneId``를 조회하고, 없으면 ``None``을 반환한다."""

        return self._zones.get(zone_id)


def _reject_non_finite_json_number(value: str) -> None:
    raise ValueError(f"유한하지 않은 숫자를 사용할 수 없습니다: {value}")


def _require_exact_fields(payload: Mapping[str, Any], expected: frozenset[str], *, context: str) -> None:
    _require_fields(payload, required=expected, optional=frozenset(), context=context)


def _require_fields(
    payload: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str],
    context: str,
) -> None:
    actual = set(payload)
    missing = sorted(required - actual)
    unknown = sorted(actual - required - optional)
    if missing:
        raise ZoneRegistryError(f"{context}에 필수 필드가 없습니다: {', '.join(missing)}")
    if unknown:
        raise ZoneRegistryError(f"{context}에 지원하지 않는 필드가 있습니다: {', '.join(unknown)}")


def _parse_integer(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ZoneRegistryError(f"{field_name}은 JSON integer여야 합니다")
    return value


def _parse_positive_integer(value: Any, *, field_name: str) -> int:
    parsed = _parse_integer(value, field_name=field_name)
    if parsed <= 0:
        raise ZoneRegistryError(f"{field_name}은 양수여야 합니다")
    return parsed


def _parse_non_empty_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ZoneRegistryError(f"{field_name}은 비어 있지 않은 문자열이어야 합니다")
    if value != value.strip():
        raise ZoneRegistryError(f"{field_name} 앞뒤에 공백을 둘 수 없습니다")
    return value


def _parse_optional_non_empty_string(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _parse_non_empty_string(value, field_name=field_name)


def _parse_optional_positive_number(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ZoneRegistryError(f"{field_name}은 숫자여야 합니다")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ZoneRegistryError(f"{field_name}은 유한한 양수여야 합니다")
    return parsed


def _parse_polygon(value: Any, *, field_name: str) -> NormalizedPolygon:
    if not isinstance(value, list):
        raise ZoneRegistryError(f"{field_name}은 좌표 배열이어야 합니다")

    points: list[tuple[float, float]] = []
    for index, point in enumerate(value):
        if not isinstance(point, list) or len(point) != 2:
            raise ZoneRegistryError(f"{field_name}[{index}]는 [x, y] 배열이어야 합니다")
        coordinates: list[float] = []
        for coordinate in point:
            if isinstance(coordinate, bool) or not isinstance(coordinate, (int, float)):
                raise ZoneRegistryError(f"{field_name}[{index}] 좌표는 숫자여야 합니다")
            coordinates.append(float(coordinate))
        points.append((coordinates[0], coordinates[1]))
    return tuple(points)


def _parse_zone_id_array(value: Any, *, field_name: str) -> tuple[ZoneId, ...]:
    if not isinstance(value, list):
        raise ZoneRegistryError(f"{field_name}은 zoneId 배열이어야 합니다")
    return tuple(
        ZoneId(_parse_integer(item, field_name=f"{field_name}[{index}]"))
        for index, item in enumerate(value)
    )

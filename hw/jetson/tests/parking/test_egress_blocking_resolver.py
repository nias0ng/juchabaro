"""Assignment와 같은 convex footprint 기반 egress evidence를 검증한다."""

import pytest

from src.parking.egress_blocking_resolver import analyze
from src.parking.models import (
    EgressAisleDefinition,
    EgressAisleDefinitionVersion,
    EgressAisleId,
    ZoneDefinitionVersion,
    ZoneId,
)
from src.tracking.models import BoundingBox


def _area(polygon) -> EgressAisleDefinition:
    return EgressAisleDefinition(
        egress_zone_id=EgressAisleId(101),
        parking_zone_id=ZoneId(1),
        polygon=polygon,
        egress_aisle_definition_version=EgressAisleDefinitionVersion(1),
        zone_definition_version=ZoneDefinitionVersion(1),
        calibration_reference="camera-v1",
    )


def test_small_egress_can_be_fully_covered_without_large_vehicle_overlap() -> None:
    egress = _area(((0.2, 0.2), (0.3, 0.2), (0.3, 0.3), (0.2, 0.3)))

    evidence = analyze(BoundingBox(0.1, 0.1, 0.5, 0.5), egress)

    assert evidence.subject_overlap_ratio == pytest.approx(0.0625)
    assert evidence.egress_coverage_ratio == pytest.approx(1.0)
    assert evidence.intersection_area == pytest.approx(0.01)


def test_partial_overlap_reports_both_denominators() -> None:
    egress = _area(((0.2, 0.2), (0.4, 0.2), (0.4, 0.4), (0.2, 0.4)))

    evidence = analyze(BoundingBox(0.3, 0.2, 0.5, 0.4), egress)

    assert evidence.subject_overlap_ratio == pytest.approx(0.5)
    assert evidence.egress_coverage_ratio == pytest.approx(0.5)

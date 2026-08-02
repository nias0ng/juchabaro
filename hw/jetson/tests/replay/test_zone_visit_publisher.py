"""ZoneVisit JSONL 발행 테스트(465/T-17)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.parking.models import ZoneVisit, ZoneVisitState
from src.replay.zone_visit_publisher import ZoneVisitJsonlPublisher, ZoneVisitPublisherError, zone_visit_to_jsonable

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
VISIT = ZoneVisit(
    visit_id=UUID(int=1),
    physical_vehicle_id=UUID(int=2),
    zone_id=1,
    state=ZoneVisitState.INSIDE,
    entered_candidate_at=T0,
    entered_at=T0,
)


def test_zone_visit_to_jsonable_uses_camel_case_wire_format():
    payload = zone_visit_to_jsonable(VISIT)

    assert payload == {
        "zoneVisitId": str(VISIT.visit_id),
        "physicalVehicleId": str(VISIT.physical_vehicle_id),
        "zoneId": 1,
        "state": "INSIDE",
        "enteredCandidateAt": T0.isoformat(),
        "enteredAt": T0.isoformat(),
        "exitCandidateAt": None,
        "exitedAt": None,
    }


def test_publisher_writes_one_json_line_per_visit(tmp_path):
    path = tmp_path / "zone_visits.jsonl"

    with ZoneVisitJsonlPublisher(path=path) as publisher:
        publisher.publish(VISIT)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["zoneVisitId"] == str(VISIT.visit_id)


def test_publisher_converts_write_oserror_to_zone_visit_publisher_error(tmp_path):
    path = tmp_path / "zone_visits.jsonl"
    publisher = ZoneVisitJsonlPublisher(path=path)
    publisher.open()

    # Monkeypatch the handle to raise OSError on write
    original_write = publisher._handle.write
    publisher._handle.write = lambda line: (_ for _ in ()).throw(OSError("disk full"))

    with pytest.raises(ZoneVisitPublisherError) as exc_info:
        publisher.publish(VISIT)

    assert "zone visit 파일에 쓰지 못했습니다" in str(exc_info.value)
    assert str(path) in str(exc_info.value)
    assert exc_info.value.__cause__.__class__ == OSError
    publisher.close()

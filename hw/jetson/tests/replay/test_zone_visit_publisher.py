"""ZoneVisit JSONL 발행 테스트(465/T-17)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID

from src.parking.models import ZoneVisit, ZoneVisitState
from src.replay.zone_visit_publisher import ZoneVisitJsonlPublisher, zone_visit_to_jsonable

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

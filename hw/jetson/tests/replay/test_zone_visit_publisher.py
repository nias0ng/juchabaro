"""ZoneVisit JSONL 발행 테스트(465/T-17)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from src.parking.models import ZoneVisit, ZoneVisitState
from src.replay.zone_visit_publisher import (
    DedupingZoneVisitPublisher,
    ZoneVisitJsonlPublisher,
    ZoneVisitPublisherError,
    zone_visit_to_jsonable,
)

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
        "observedAt": T0.isoformat(),
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


def test_publisher_converts_write_oserror_to_zone_visit_publisher_error(tmp_path, monkeypatch):
    path = tmp_path / "zone_visits.jsonl"
    publisher = ZoneVisitJsonlPublisher(path=path)
    publisher.open()

    # 핸들의 write()를 몽키패치해 디스크 꽉 참 같은 쓰기 실패를 재현한다.
    monkeypatch.setattr(publisher._handle, "write", lambda line: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(ZoneVisitPublisherError) as exc_info:
        publisher.publish(VISIT)

    assert "zone visit 파일에 쓰지 못했습니다" in str(exc_info.value)
    assert str(path) in str(exc_info.value)
    assert exc_info.value.__cause__.__class__ == OSError
    publisher.close()


def test_publisher_converts_close_oserror_to_zone_visit_publisher_error(tmp_path, monkeypatch):
    path = tmp_path / "zone_visits.jsonl"
    publisher = ZoneVisitJsonlPublisher(path=path)
    publisher.open()

    # 핸들의 close()를 몽키패치해 flush 시점의 쓰기 실패를 재현한다.
    monkeypatch.setattr(publisher._handle, "close", lambda: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(ZoneVisitPublisherError) as exc_info:
        publisher.close()

    assert "zone visit 파일을 닫지 못했습니다" in str(exc_info.value)
    assert str(path) in str(exc_info.value)
    assert exc_info.value.__cause__.__class__ == OSError


def test_deduping_publisher_skips_repeated_state_for_same_visit_id(tmp_path):
    """같은 visit_id의 상태가 그대로면 두 번째 이후 호출은 발행을 건너뛴다."""

    path = tmp_path / "zone_visits.jsonl"
    entering = replace(VISIT, state=ZoneVisitState.ENTERING, entered_at=None, entered_candidate_at=T0)
    inside = replace(VISIT, state=ZoneVisitState.INSIDE)  # VISIT은 이미 INSIDE

    with ZoneVisitJsonlPublisher(path=path) as publisher:
        deduper = DedupingZoneVisitPublisher(publisher)

        published = deduper.publish_all([entering, inside, inside, inside])

    lines = path.read_text(encoding="utf-8").splitlines()
    assert published == 2
    assert len(lines) == 2
    assert json.loads(lines[0])["state"] == "ENTERING"
    assert json.loads(lines[1])["state"] == "INSIDE"


def test_deduping_publisher_tracks_state_independently_per_visit_id():
    """visit_id가 다르면 같은 state라도 각각 발행된다."""

    other_visit = replace(VISIT, visit_id=UUID(int=99))
    published_visits: list[ZoneVisit] = []

    class _RecordingPublisher:
        def publish(self, visit: ZoneVisit) -> None:
            published_visits.append(visit)

    deduper = DedupingZoneVisitPublisher(_RecordingPublisher())  # type: ignore[arg-type]

    published = deduper.publish_all([VISIT, other_visit, VISIT, other_visit])

    assert published == 2
    assert published_visits == [VISIT, other_visit]

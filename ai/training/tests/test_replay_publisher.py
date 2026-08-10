"""JsonlResultPublisher 계약 테스트.

바이트 단위 결정론이 핵심이다. 같은 영상·같은 설정을 다시 돌렸을 때 출력이
바이트로 같아야 파라미터 변경의 영향을 diff로 회귀 검사할 수 있다.
"""

import json
from datetime import datetime, timezone

from jetson_vehicle_tracking_baseline import ViolationEvent, ViolationStatus, ZoneType
from replay.jsonl_publisher import JsonlResultPublisher


def make_event(track_id=1, session_id=None):
    return ViolationEvent(
        track_id=track_id,
        plate_number=None,
        # 리플레이에는 입차 이벤트를 공급하는 경로가 없어 기본값이 미확정(None)이다.
        session_id=session_id,
        status=ViolationStatus.RESTRICTED_ZONE,
        zone_id=3,
        zone_number="DIS-01",
        zone_type=ZoneType.DISABLED,
        overlap_ratio=0.5123456789,
        dwell_seconds=42.5,
        occupancy_seconds=42.5,
        detected_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_writes_one_json_object_per_line(tmp_path):
    path = tmp_path / "events.jsonl"
    with JsonlResultPublisher(path=path) as publisher:
        publisher.publish(make_event(1))
        publisher.publish(make_event(2))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["track_id"] for line in lines] == [1, 2]


def test_event_fields_round_trip(tmp_path):
    path = tmp_path / "events.jsonl"
    with JsonlResultPublisher(path=path) as publisher:
        publisher.publish(make_event())

    record = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert record["status"] == "RESTRICTED_ZONE"
    assert record["zone_id"] == 3
    assert record["zone_number"] == "DIS-01"
    assert record["zone_type"] == "DISABLED"
    assert record["detected_at"] == "2026-01-01T00:00:00+00:00"


def test_records_session_id_so_unidentified_events_can_be_counted(tmp_path):
    """계약 문서 §9 — 파일럿에서 신원 미확정 사건이 몇 건인지 세어 스키마 완화(§3)의
    시급성을 판단한다. session_id가 JSONL에 남지 않으면 그 집계가 불가능하다."""
    path = tmp_path / "events.jsonl"
    with JsonlResultPublisher(path=path) as publisher:
        publisher.publish(make_event())
        publisher.publish(make_event(session_id=55))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [record["session_id"] for record in records] == [None, 55]


def test_same_event_serializes_byte_identically(tmp_path):
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    for path in (first, second):
        with JsonlResultPublisher(path=path) as publisher:
            publisher.publish(make_event())

    assert first.read_bytes() == second.read_bytes()


def test_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "events.jsonl"
    with JsonlResultPublisher(path=path) as publisher:
        publisher.publish(make_event())

    assert path.exists()

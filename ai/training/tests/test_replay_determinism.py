"""리플레이 결정론 테스트 — 이 검증 하네스의 토대.

같은 영상·같은 설정이면 이벤트 JSONL이 바이트로 같아야, 파라미터를 바꿔가며
diff로 회귀 검사를 할 수 있다. 판정이 벽시계를 쓰지 않는다는 성질에 의존한다.
"""

from datetime import datetime, timedelta, timezone

import pytest
from jetson_vehicle_tracking_baseline import (
    BoundingBox,
    NormalizedPolygon,
    ParkingZone,
    VehicleBox,
    ViolationMonitor,
    ZoneRegistry,
    ZoneType,
)
from replay.jsonl_publisher import JsonlResultPublisher
from replay.video_source import EPOCH


def make_monitor():
    zone = ParkingZone(
        zone_id=1,
        zone_number="DIS-01",
        zone_type=ZoneType.DISABLED,
        polygon=NormalizedPolygon(((0.0, 0.0), (0.4, 0.0), (0.4, 0.4), (0.0, 0.4))),
    )
    return ViolationMonitor(ZoneRegistry([zone]), min_dwell_seconds=1.0)


def replay(path, t0, fps=30.0, frames=90):
    """트래커를 스텁으로 대체하고 판정 → JSONL 경로만 결정론적으로 돌린다."""
    monitor = make_monitor()
    bbox = BoundingBox(0.1, 0.1, 0.3, 0.3)
    with JsonlResultPublisher(path=path) as publisher:
        for index in range(frames):
            captured_at = t0 + timedelta(seconds=index / fps)
            detections = [
                VehicleBox(
                    track_id=1, bbox=bbox, confidence=0.9, frame_id=index + 1, captured_at=captured_at
                )
            ]
            for event in monitor.update(detections):
                publisher.publish(event)
    return path.read_bytes()


def test_two_runs_produce_byte_identical_events(tmp_path):
    first = replay(tmp_path / "a.jsonl", EPOCH)
    second = replay(tmp_path / "b.jsonl", EPOCH)

    assert first == second
    assert first, "이벤트가 하나도 없으면 결정론을 확인한 것이 아니다"


def test_shifting_t0_shifts_event_timestamps_only(tmp_path):
    import json

    base = tmp_path / "base.jsonl"
    shifted = tmp_path / "shifted.jsonl"
    offset = timedelta(hours=3)
    replay(base, EPOCH)
    replay(shifted, EPOCH + offset)

    base_records = [json.loads(line) for line in base.read_text(encoding="utf-8").splitlines()]
    shifted_records = [json.loads(line) for line in shifted.read_text(encoding="utf-8").splitlines()]

    assert len(base_records) == len(shifted_records)
    for before, after in zip(base_records, shifted_records):
        assert datetime.fromisoformat(after["detected_at"]) - datetime.fromisoformat(
            before["detected_at"]
        ) == offset
        assert before["status"] == after["status"]
        assert before["dwell_seconds"] == after["dwell_seconds"]

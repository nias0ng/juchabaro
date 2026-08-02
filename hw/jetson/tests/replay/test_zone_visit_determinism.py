"""ZoneVisit 리플레이(`--out-zone-visits`) 결정론 테스트(465/T-17 최종 리뷰).

`tests/application/test_replay_determinism.py`는 `--out-events`(프로덕션
outbox)의 결정론만 확인한다. 하지만 `restricted_zone`은 `VehicleContext`가
없으면 항상 `confirmable=False`라(`scripts/replay_pilot_video.py` 모듈
docstring 참고) 실제 파일럿 영상 리플레이에서 outbox는 항상 비어 있고,
§4.7 임계값 산출이 실제로 쓰는 산출물은 `--out-zone-visits`다. 그런데도
그 파일이 결정론적이라는 것을 증명하는 테스트가 없었다 — 이 파일이 그
공백을 채운다.

`DedupingZoneVisitPublisher`(465/T-17 최종 리뷰로 추가)로 상태 전이만 걸러
발행한다 — CLI(`scripts/replay_pilot_video.py`)가 쓰는 것과 같은 helper라
두 곳의 dedup 규칙이 갈라질 일이 없다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from uuid import UUID

from src.application.monitoring_pipeline import MonitoringPipeline
from src.camera.frame_source import EndOfVideo
from src.camera.models import CapturedFrame
from src.communication.outbox import JsonlOutbox
from src.parking.geometry import NormalizedPolygon
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.pipeline import ParkingPipeline
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.replay.zone_visit_publisher import DedupingZoneVisitPublisher, ZoneVisitJsonlPublisher
from src.tracking.models import BoundingBox, TrackObservation, TrackSegmentId
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import ModelInfo

# 한 구역에 완전히 들어간 bbox와 완전히 벗어난 bbox. 겹침 비율이 각각
# 1.0/0.0에 가까워 min_overlap_ratio=0.5 경계 근처의 우연한 흔들림이 없다.
INSIDE_BBOX = BoundingBox(0.15, 0.15, 0.25, 0.25)
OUTSIDE_BBOX = BoundingBox(0.6, 0.6, 0.7, 0.7)
DISABLED_ZONE = ParkingZone(
    zone_id=1,
    zone_number="D-01",
    zone_type=ZoneType.DISABLED,
    polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
)

# 프레임 순서: INSIDE 두 프레임 만에 진입 확정(entry_confirm=1.0, 프레임 간격
# 1초) → INSIDE에 한 프레임 더 머물러 "그대로"인 프레임을 만든 뒤(dedup 없이
# 발행하면 중복 레코드가 되는 지점) → OUTSIDE 두 프레임 만에 이탈 확정.
_BBOX_BY_FRAME_ID = {
    1: INSIDE_BBOX,
    2: INSIDE_BBOX,
    3: INSIDE_BBOX,
    4: OUTSIDE_BBOX,
    5: OUTSIDE_BBOX,
}


def _patch_deterministic_uuids(monkeypatch) -> None:
    """`entity_resolver`/`zone_visit_tracker`의 uuid4()를 호출 순서 기반 카운터로 고정한다.

    `test_replay_determinism.py`의 `_patch_deterministic_uuids`와 같은 이유다
    — physicalVehicleId(entity_resolver)와 zoneVisitId(zone_visit_tracker)를
    둘 다 uuid4()로 발급하므로, 두 실행이 처음부터 같은 카운터로 시작해야
    발급 순서가 재현된다. incident_reducer는 여기서 쓰지 않는다(§4.7은
    zone-visits만 본다) — 그쪽 uuid4()까지 패치하면 오히려 이 파일이 검증하지
    않는 관심사를 끌어들이게 된다.
    """

    counter = count(1)

    def _uuid4() -> UUID:
        return UUID(int=next(counter))

    monkeypatch.setattr("src.tracking.entity_resolver.uuid4", _uuid4)
    monkeypatch.setattr("src.parking.zone_visit_tracker.uuid4", _uuid4)


class _ScriptedFrameSource:
    """미리 정해둔 (시각, 없음) 프레임 개수만큼 캡처하고, 그 뒤엔 EndOfVideo를 던진다."""

    def __init__(self, *, frame_count: int, t0: datetime) -> None:
        self._frame_count = frame_count
        self._t0 = t0
        self._next_frame_id = 1

    def open(self) -> None:
        pass

    def capture(self) -> CapturedFrame:
        if self._next_frame_id > self._frame_count:
            raise EndOfVideo("프레임 소진")
        frame = CapturedFrame(
            camera_id="cam-1",
            frame_id=self._next_frame_id,
            captured_at=self._t0 + timedelta(seconds=self._next_frame_id - 1),
            image=object(),
            width=640,
            height=480,
            calibration_id=None,
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        pass


class _ScriptedDetector:
    """차 한 대가 전용구역에 들어갔다가 나가는 고정 궤적."""

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(library="fake", library_version="0", model_name="fake.pt", tracker_config="fake.yaml")

    def open(self) -> None:
        pass

    def track(self, frame: CapturedFrame) -> list[TrackObservation]:
        bbox = _BBOX_BY_FRAME_ID.get(frame.frame_id)
        if bbox is None:
            return []
        return [
            TrackObservation(
                track_segment_id=TrackSegmentId(1), bbox=bbox, confidence=0.9, observed_at=frame.captured_at
            )
        ]

    def close(self) -> None:
        pass


def _run_zone_visit_replay(tmp_path: Path, *, run_label: str, t0: datetime) -> tuple[bytes, int]:
    """스크립트 더블로 5프레임을 돌리고, (zone-visits jsonl 바이트, 원본 zone_visit_updates 총 건수)를 반환한다."""

    tracking_pipeline = TrackingPipeline(camera_id="cam-1", detector=_ScriptedDetector())
    parking_pipeline = ParkingPipeline(
        zones=ZoneRegistry([DISABLED_ZONE]),
        zone_visit_tracker=InMemoryZoneVisitTracker(entry_confirm_seconds=1.0, exit_confirm_seconds=1.0),
        incident_reducer=InMemoryIncidentReducer(),
        min_overlap_ratio=0.5,
    )
    pipeline = MonitoringPipeline(
        frame_source=_ScriptedFrameSource(frame_count=5, t0=t0),
        tracking_pipeline=tracking_pipeline,
        parking_pipeline=parking_pipeline,
        outbox=JsonlOutbox(tmp_path / f"{run_label}_events.jsonl"),
    )
    zone_visits_path = tmp_path / f"{run_label}_zone_visits.jsonl"
    zone_visit_publisher = ZoneVisitJsonlPublisher(path=zone_visits_path)
    deduper = DedupingZoneVisitPublisher(zone_visit_publisher)

    raw_update_count = 0
    pipeline.open()
    zone_visit_publisher.open()
    try:
        while True:
            try:
                result = pipeline.process_next_frame()
            except EndOfVideo:
                break
            raw_update_count += len(result.zone_visit_updates)
            deduper.publish_all(result.zone_visit_updates)
    finally:
        zone_visit_publisher.close()
        pipeline.close()

    return zone_visits_path.read_bytes(), raw_update_count


def test_two_runs_produce_byte_identical_zone_visits(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    first, _ = _run_zone_visit_replay(tmp_path, run_label="a", t0=t0)

    _patch_deterministic_uuids(monkeypatch)
    second, _ = _run_zone_visit_replay(tmp_path, run_label="b", t0=t0)

    assert first == second
    assert first, "zone visit이 하나도 없으면 결정론을 확인한 것이 아니다"


def test_zone_visit_dedup_drops_repeated_state_but_keeps_every_transition(tmp_path, monkeypatch):
    """dedup이 raw 업데이트 수보다 적게 쓰되, 네 가지 상태 전이는 모두 남긴다."""

    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    out_bytes, raw_update_count = _run_zone_visit_replay(tmp_path, run_label="dedup", t0=t0)

    records = [json.loads(line) for line in out_bytes.decode("utf-8").splitlines()]
    states = [record["state"] for record in records]

    # frame3(INSIDE 유지)이 원본에는 INSIDE를 한 번 더 반환하지만 dedup이
    # 걸러야 한다 — 그래서 발행 건수가 raw 건수보다 적어야 한다.
    assert len(records) < raw_update_count
    assert states == ["ENTERING", "INSIDE", "EXITING", "OUTSIDE"]


def test_zone_visit_records_carry_state_matched_observed_at(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    out_bytes, _ = _run_zone_visit_replay(tmp_path, run_label="observed-at", t0=t0)

    records = [json.loads(line) for line in out_bytes.decode("utf-8").splitlines()]
    by_state = {record["state"]: record for record in records}

    assert by_state["ENTERING"]["observedAt"] == by_state["ENTERING"]["enteredCandidateAt"]
    assert by_state["INSIDE"]["observedAt"] == by_state["INSIDE"]["enteredAt"]
    assert by_state["EXITING"]["observedAt"] == by_state["EXITING"]["exitCandidateAt"]
    assert by_state["OUTSIDE"]["observedAt"] == by_state["OUTSIDE"]["exitedAt"]

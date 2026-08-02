"""MonitoringPipeline 리플레이 결정론 테스트(465/T-17).

같은 입력이면 outbox JSONL이 바이트로 같아야, 파라미터를 바꿔가며 diff로
회귀 검사를 할 수 있다 — §4.7 임계값 산출의 전제다. 새 파이프라인은
PhysicalVehicleId/ZoneVisitId/IncidentId를 각각 entity_resolver,
zone_visit_tracker, incident_reducer가 uuid4()로 발급하므로, 몽키패치로 그
발급 순서만 고정해야 두 실행이 바이트로 같아진다 — 판정 로직 자체는
건드리지 않는다. 판정이 벽시계를 쓰지 않는다는 성질도 t0 이동 테스트로
함께 확인한다.
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
from src.communication.models import EntryContext
from src.communication.outbox import JsonlOutbox
from src.parking.geometry import NormalizedPolygon
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.pipeline import ParkingPipeline
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.tracking.context_matcher import ContextMatcher
from src.tracking.models import BoundingBox, TrackObservation, TrackSegmentId
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import ModelInfo

ENTRY_BBOX = BoundingBox(0.41, 0.41, 0.49, 0.49)
INSIDE_BBOX = BoundingBox(0.15, 0.15, 0.25, 0.25)
OUTSIDE_BBOX = BoundingBox(0.6, 0.6, 0.7, 0.7)
DISABLED_ZONE = ParkingZone(
    zone_id=1,
    zone_number="D-01",
    zone_type=ZoneType.DISABLED,
    polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
)
ENTRY_ZONE = ParkingZone(
    zone_id=9,
    zone_number="E-01",
    zone_type=ZoneType.ENTRY_EXIT,
    polygon=NormalizedPolygon(((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5))),
)


def _patch_deterministic_uuids(monkeypatch) -> None:
    """entity_resolver/zone_visit_tracker/incident_reducer의 uuid4()를 호출
    순서 기반 카운터로 고정한다. 세 모듈이 같은 카운터를 공유해야 한 실행
    안에서 발급 순서가 재현되고, 호출마다 새 카운터를 만들어야 두 실행이
    똑같이 1부터 시작한다 — 이 함수를 실행 직전마다 다시 불러야 한다."""

    counter = count(1)

    def _uuid4() -> UUID:
        return UUID(int=next(counter))

    monkeypatch.setattr("src.tracking.entity_resolver.uuid4", _uuid4)
    monkeypatch.setattr("src.parking.zone_visit_tracker.uuid4", _uuid4)
    monkeypatch.setattr("src.parking.incident_reducer.uuid4", _uuid4)


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
    """차 한 대가 입출차 구역을 지나 전용구역에 들어갔다 나가는 고정 궤적."""

    _BBOX_BY_FRAME_ID = {1: ENTRY_BBOX, 2: INSIDE_BBOX, 3: INSIDE_BBOX, 4: OUTSIDE_BBOX, 5: OUTSIDE_BBOX}

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(library="fake", library_version="0", model_name="fake.pt", tracker_config="fake.yaml")

    def open(self) -> None:
        pass

    def track(self, frame: CapturedFrame) -> list[TrackObservation]:
        bbox = self._BBOX_BY_FRAME_ID.get(frame.frame_id)
        if bbox is None:
            return []
        return [
            TrackObservation(
                track_segment_id=TrackSegmentId(1), bbox=bbox, confidence=0.9, observed_at=frame.captured_at
            )
        ]

    def close(self) -> None:
        pass


def _run_replay(out_path: Path, *, t0: datetime) -> bytes:
    matcher = ContextMatcher(zones=ZoneRegistry([DISABLED_ZONE, ENTRY_ZONE]))
    matcher.add_entry_context(
        EntryContext(
            tracking_id="gate-uuid-1",
            recognized_plate_number="12가3456",
            entry_time=t0,
            access_decision="ALLOW",
            registered=True,
            vehicle_id=10,
            is_disabled_vehicle=False,
            is_electric=True,
            vehicle_status="ACTIVE",
            session_id=55,
            duplicate_request=False,
        ),
        idempotency_key="rpi-request-1",
    )
    tracking_pipeline = TrackingPipeline(camera_id="cam-1", detector=_ScriptedDetector(), context_matcher=matcher)
    parking_pipeline = ParkingPipeline(
        zones=ZoneRegistry([DISABLED_ZONE, ENTRY_ZONE]),
        zone_visit_tracker=InMemoryZoneVisitTracker(entry_confirm_seconds=1.0, exit_confirm_seconds=1.0),
        incident_reducer=InMemoryIncidentReducer(),
        min_overlap_ratio=0.5,
    )
    pipeline = MonitoringPipeline(
        frame_source=_ScriptedFrameSource(frame_count=5, t0=t0),
        tracking_pipeline=tracking_pipeline,
        parking_pipeline=parking_pipeline,
        outbox=JsonlOutbox(out_path),
    )
    pipeline.open()
    pipeline.run()
    pipeline.close()
    return out_path.read_bytes()


def test_two_runs_produce_byte_identical_outbox(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    first = _run_replay(tmp_path / "a.jsonl", t0=t0)

    _patch_deterministic_uuids(monkeypatch)
    second = _run_replay(tmp_path / "b.jsonl", t0=t0)

    assert first == second
    assert first, "이벤트가 하나도 없으면 결정론을 확인한 것이 아니다"


def test_shifting_t0_shifts_event_timestamps_only(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
    offset = timedelta(hours=3)

    _patch_deterministic_uuids(monkeypatch)
    base_bytes = _run_replay(tmp_path / "base.jsonl", t0=t0)
    _patch_deterministic_uuids(monkeypatch)
    shifted_bytes = _run_replay(tmp_path / "shifted.jsonl", t0=t0 + offset)

    base_records = [json.loads(line) for line in base_bytes.decode("utf-8").splitlines()]
    shifted_records = [json.loads(line) for line in shifted_bytes.decode("utf-8").splitlines()]

    assert base_records, "이벤트가 하나도 없으면 시간 이동을 확인한 것이 아니다"
    assert len(base_records) == len(shifted_records)
    for before, after in zip(base_records, shifted_records):
        assert before["incidentId"] == after["incidentId"]
        assert before["transitionType"] == after["transitionType"]
        assert before["ruleCode"] == after["ruleCode"]
        assert datetime.fromisoformat(after["firstObservedAt"]) - datetime.fromisoformat(
            before["firstObservedAt"]
        ) == offset
        # firstObservedAt만 옮겨서는 "시간만 옮겨가고 다른 건 안 바뀐다"는 것을
        # 증명하지 못한다 — confirmedAt/resolvedAt도 같은 offset만큼 옮겨야
        # 판정 로직 자체가 벽시계가 아니라 t0 기준 상대 시간으로만 돈다는 뜻이다.
        if before["confirmedAt"] is not None and after["confirmedAt"] is not None:
            assert datetime.fromisoformat(after["confirmedAt"]) - datetime.fromisoformat(
                before["confirmedAt"]
            ) == offset
        if before["resolvedAt"] is not None and after["resolvedAt"] is not None:
            assert datetime.fromisoformat(after["resolvedAt"]) - datetime.fromisoformat(
                before["resolvedAt"]
            ) == offset

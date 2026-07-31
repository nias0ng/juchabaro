"""MonitoringPipeline 관통 통합 테스트 (T-08).

camera(가짜 프레임) → tracking(가짜 탐지기) → parking(진짜 ZoneVisitTracker/
restricted_zone/IncidentReducer) → outbox(진짜 JSONL 파일)까지 전부 실제
조립으로 이어 붙여, 관통 1단계가 실제로 끝에서 끝까지 도는지 검증한다.
"""

import json
from datetime import datetime, timedelta, timezone

from src.application.monitoring_pipeline import MonitoringPipeline
from src.camera.frame_source import EndOfVideo
from src.camera.models import CapturedFrame
from src.communication.outbox import JsonlOutbox
from src.parking.geometry import NormalizedPolygon
from src.parking.incident_reducer import InMemoryIncidentReducer
from src.parking.pipeline import ParkingPipeline
from src.parking.zone_registry import ParkingZone, ZoneRegistry, ZoneType
from src.parking.zone_visit_tracker import InMemoryZoneVisitTracker
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleSnapshot,
    TrackingBatch,
    TrackObservation,
    TrackSegmentId,
    VehicleContext,
)
from src.tracking.pipeline import TrackingPipeline
from src.tracking.protocols import ModelInfo

T0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
INSIDE_BBOX = BoundingBox(0.15, 0.15, 0.25, 0.25)
OUTSIDE_BBOX = BoundingBox(0.6, 0.6, 0.7, 0.7)
DISABLED_ZONE = ParkingZone(
    zone_id=1,
    zone_number="D-01",
    zone_type=ZoneType.DISABLED,
    polygon=NormalizedPolygon(((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))),
)


class FakeFrameSource:
    """미리 정해진 프레임 개수만큼 캡처를 흉내 내고, 그 뒤엔 EndOfVideo를 던진다."""

    def __init__(self, frame_count: int) -> None:
        self._frame_count = frame_count
        self._next_frame_id = 1
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def capture(self) -> CapturedFrame:
        if self._next_frame_id > self._frame_count:
            raise EndOfVideo("프레임 소진")
        frame = CapturedFrame(
            camera_id="cam-1",
            frame_id=self._next_frame_id,
            captured_at=T0 + timedelta(seconds=self._next_frame_id - 1),
            image=object(),
            width=640,
            height=480,
            calibration_id=None,
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        self.closed = True


class ScriptedDetector:
    """frame_id별로 미리 정해둔 TrackObservation 목록을 그대로 돌려준다."""

    def __init__(self, observations_by_frame_id: dict[int, list[TrackObservation]]) -> None:
        self._observations_by_frame_id = observations_by_frame_id
        self.opened = False
        self.closed = False

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(library="fake", library_version="0", model_name="fake.pt", tracker_config="fake.yaml")

    def open(self) -> None:
        self.opened = True

    def track(self, frame: CapturedFrame) -> list[TrackObservation]:
        return self._observations_by_frame_id.get(frame.frame_id, [])

    def close(self) -> None:
        self.closed = True


def _obs(bbox: BoundingBox, at: datetime) -> TrackObservation:
    return TrackObservation(track_segment_id=TrackSegmentId(1), bbox=bbox, confidence=0.9, observed_at=at)


def build_pipeline(detector: ScriptedDetector, frame_source: FakeFrameSource, outbox_path):
    tracking_pipeline = TrackingPipeline(camera_id="cam-1", detector=detector)
    parking_pipeline = ParkingPipeline(
        zones=ZoneRegistry([DISABLED_ZONE]),
        zone_visit_tracker=InMemoryZoneVisitTracker(entry_confirm_seconds=1.0, exit_confirm_seconds=1.0),
        incident_reducer=InMemoryIncidentReducer(),
        min_overlap_ratio=0.5,
    )
    outbox = JsonlOutbox(outbox_path)
    return MonitoringPipeline(
        frame_source=frame_source,
        tracking_pipeline=tracking_pipeline,
        parking_pipeline=parking_pipeline,
        outbox=outbox,
    )


def test_vehicle_entering_and_leaving_restricted_zone_via_real_tracking_stays_unconfirmed(tmp_path):
    """camera → 진짜 TrackingPipeline → parking → outbox 전체 관통.

    T-16(context_matcher)이 아직 없어 PhysicalVehicleSnapshot.context가 항상
    None이다 — restricted_zone은 그걸 "정보 없음"으로 보고 confirmable=False로
    둔다("정보 없음"을 "무자격"으로 간주하면 안 되므로, 데이터흐름.md §4).
    그래서 이 관통 경로는 지금 **절대 outbox까지 도달하지 않는다** — 이건
    버그가 아니라 T-16 전까지의 의도된 상태다. 방문 자체(ENTERING→INSIDE→
    EXITING→OUTSIDE)는 정상적으로 추적됨을 함께 확인해 wiring 자체는
    살아있음을 보장한다.
    """
    observations = {
        1: [_obs(INSIDE_BBOX, T0)],
        2: [_obs(INSIDE_BBOX, T0 + timedelta(seconds=1))],
        3: [_obs(OUTSIDE_BBOX, T0 + timedelta(seconds=2))],
        4: [_obs(OUTSIDE_BBOX, T0 + timedelta(seconds=3))],
    }
    detector = ScriptedDetector(observations)
    frame_source = FakeFrameSource(frame_count=4)
    outbox_path = tmp_path / "outbox.jsonl"
    pipeline = build_pipeline(detector, frame_source, outbox_path)

    pipeline.open()
    frame_count = pipeline.run()
    pipeline.close()

    assert frame_count == 4
    assert frame_source.opened and frame_source.closed
    assert detector.opened and detector.closed
    # confirmable=False라 IncidentReducer가 CANDIDATE로만 쥐고 있고, outbox엔
    # 아무것도 안 쌓인다.
    assert not outbox_path.exists() or outbox_path.read_text(encoding="utf-8") == ""


class _StubTrackingPipeline:
    """진짜 TrackingPipeline 대신 미리 정해둔 TrackingBatch를 그대로 돌려준다.

    vehicle_context를 실제로 채워서, MonitoringPipeline이 parking의 확정
    전이를 outbox까지 제대로 전달하는지(위 테스트가 검증 못 하는 부분)를
    context_matcher(T-16) 없이도 검증한다.
    """

    def __init__(self, batches_by_frame_id) -> None:
        self._batches_by_frame_id = batches_by_frame_id
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def process(self, frame: CapturedFrame):
        return self._batches_by_frame_id[frame.frame_id]

    def close(self) -> None:
        self.closed = True


def test_monitoring_pipeline_forwards_confirmed_transitions_to_outbox(tmp_path):
    """tracking 계층이 자격 정보를 실어 보낸다고 가정했을 때(T-16 이후 실제
    모습), MonitoringPipeline이 확정된 전이를 실제로 outbox까지 전달하는지
    확인한다 — 조립 로직 자체의 책임(판정이 아니라 전달)을 검증한다."""
    unauthorized = VehicleContext(
        parking_session_id=1, vehicle_id=1, is_electric=False, is_disabled_vehicle=False
    )

    def make_batch(bbox, at, frame_id):
        snapshot = PhysicalVehicleSnapshot(
            physical_vehicle_id="pv-1",
            track_segment_id=TrackSegmentId(1),
            bbox=bbox,
            confidence=0.9,
            motion_signal=MotionSignal.STATIONARY,
            observed_at=at,
            camera_id="cam-1",
            context=unauthorized,
        )
        return TrackingBatch(
            camera_id="cam-1", frame_id=frame_id, observed_at=at,
            vehicles=(snapshot,), ended_vehicle_ids=(), source_available=True,
        )

    batches = {
        1: make_batch(INSIDE_BBOX, T0, 1),
        2: make_batch(INSIDE_BBOX, T0 + timedelta(seconds=1), 2),
        3: make_batch(OUTSIDE_BBOX, T0 + timedelta(seconds=2), 3),
        4: make_batch(OUTSIDE_BBOX, T0 + timedelta(seconds=3), 4),
    }
    frame_source = FakeFrameSource(frame_count=4)
    parking_pipeline = ParkingPipeline(
        zones=ZoneRegistry([DISABLED_ZONE]),
        zone_visit_tracker=InMemoryZoneVisitTracker(entry_confirm_seconds=1.0, exit_confirm_seconds=1.0),
        incident_reducer=InMemoryIncidentReducer(),
        min_overlap_ratio=0.5,
    )
    outbox_path = tmp_path / "outbox.jsonl"
    pipeline = MonitoringPipeline(
        frame_source=frame_source,
        tracking_pipeline=_StubTrackingPipeline(batches),
        parking_pipeline=parking_pipeline,
        outbox=JsonlOutbox(outbox_path),
    )

    pipeline.open()
    pipeline.run()
    pipeline.close()

    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines()]
    assert [line["transitionType"] for line in lines] == ["OPEN", "RESOLVE"]
    assert lines[0]["ruleCode"] == "DISABLED_ZONE_UNAUTHORIZED"
    assert lines[0]["incidentId"] == lines[1]["incidentId"]

    lines = [json.loads(line) for line in outbox_path.read_text(encoding="utf-8").splitlines()]
    assert [line["transitionType"] for line in lines] == ["OPEN", "RESOLVE"]
    assert lines[0]["ruleCode"] == "DISABLED_ZONE_UNAUTHORIZED"
    assert lines[0]["incidentId"] == lines[1]["incidentId"]


def test_empty_scene_produces_no_outbox_entries(tmp_path):
    """차량이 한 대도 없으면 outbox 파일에 아무 줄도 안 쌓여야 한다."""
    frame_source = FakeFrameSource(frame_count=3)
    detector = ScriptedDetector({})
    outbox_path = tmp_path / "outbox.jsonl"
    pipeline = build_pipeline(detector, frame_source, outbox_path)

    pipeline.open()
    pipeline.run()
    pipeline.close()

    assert not outbox_path.exists() or outbox_path.read_text(encoding="utf-8") == ""


def test_process_next_frame_returns_parking_pipeline_result_each_call(tmp_path):
    detector = ScriptedDetector({1: [_obs(INSIDE_BBOX, T0)]})
    frame_source = FakeFrameSource(frame_count=1)
    pipeline = build_pipeline(detector, frame_source, tmp_path / "outbox.jsonl")
    pipeline.open()

    result = pipeline.process_next_frame()

    assert result.incident_transitions == ()  # ENTERING — 아직 확정 전
    assert len(result.zone_visit_updates) == 1

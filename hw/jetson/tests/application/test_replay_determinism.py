"""MonitoringPipeline 리플레이 결정론 테스트(465/T-17).

같은 입력이면 outbox JSONL이 바이트로 같아야, 파라미터를 바꿔가며 diff로
회귀 검사를 할 수 있다 — §4.7 임계값 산출의 전제다. 새 파이프라인은
PhysicalVehicleId/ZoneVisitId/ParkingEpisodeId/IncidentId를 각각
entity_resolver, zone_visit_tracker, parking_episode_tracker,
incident_reducer가 uuid4()로 발급하므로, 몽키패치로 그 발급 순서만 고정해야
두 실행이 바이트로 같아진다 — 판정 로직 자체는 건드리지 않는다. 판정이
벽시계를 쓰지 않는다는 성질도 t0 이동 테스트로 함께 확인한다.

**여기서는 백엔드 입차 이벤트를 일부러 주입한다.** 확정 전이가 outbox까지
가려면 `ParkingSession` correlation이 필요하고, 그게 없으면 events 파일이
아예 비어 결정론을 확인할 대상이 사라진다(세션 없는 조건은
`tests/replay/test_zone_visit_determinism.py`가 따로 확인한다). 464 이전
버전은 `ContextMatcher.add_entry_context()`로 in-memory 주입을 했지만, 그
경로는 사라졌고 지금은 `EntryEventIntake`가 durable 접수 경계다 — 실제
FastAPI 라우터가 쓰는 것과 같은 경로로 주입한다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from itertools import count
from pathlib import Path
from uuid import UUID

import pytest

# camera module은 calibration runtime에서 numpy를 사용한다
# (tests/application/test_monitoring_factory.py와 같은 이유).
pytest.importorskip("numpy")

from src.application.entry_event_intake import EntryEventIntake
from src.application.monitoring_factory import (
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.camera.frame_source import EndOfVideo
from src.camera.models import CapturedFrame
from src.communication.models import (
    EntryAccessDecision,
    EntryDecisionInput,
    EntrySessionContextInput,
)
from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.parking.egress_aisle_registry import EgressAisleRegistry
from src.replay.publication_preparer import JsonlPublicationPreparer
from src.session.entry_match_coordinator import EntryMatchCoordinator
from src.storage.database import connect_database, open_database
from src.tracking.models import BoundingBox, TrackerFrameResult, TrackObservation, TrackSegmentId
from src.tracking.protocols import ModelInfo

CALIBRATION_REFERENCE = "pilot-calibration"
TRACKING_ID = "11111111-1111-4111-8111-111111111111"

ENTRY_BBOX = BoundingBox(0.41, 0.41, 0.49, 0.49)
INSIDE_BBOX = BoundingBox(0.15, 0.15, 0.25, 0.25)
OUTSIDE_BBOX = BoundingBox(0.6, 0.6, 0.7, 0.7)
DISABLED_ZONE = ZoneDefinition(
    zone_id=ZoneId(1),
    zone_type=ZoneType.DISABLED,
    polygon=((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)),
    zone_definition_version=ZoneDefinitionVersion(1),
    calibration_reference=CALIBRATION_REFERENCE,
)
ENTRY_ZONE = ZoneDefinition(
    zone_id=ZoneId(9),
    zone_type=ZoneType.ENTRY_EXIT,
    polygon=((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5)),
    zone_definition_version=ZoneDefinitionVersion(1),
    calibration_reference=CALIBRATION_REFERENCE,
    entry_exit_role=EntryExitRole.ENTRY,
)

# 입출차 구역에서 매칭된 차가 전용구역으로 들어가 주차를 확정하고
# (parking_confirm=1.0) 다시 움직여 나가는 궤적. PARKED/UNPARKED와
# restricted_zone 사건 전이가 모두 나오도록 프레임을 넉넉히 둔다.
_BBOX_BY_FRAME_ID = {
    1: ENTRY_BBOX,
    2: ENTRY_BBOX,
    3: INSIDE_BBOX,
    4: INSIDE_BBOX,
    5: INSIDE_BBOX,
    6: INSIDE_BBOX,
    7: INSIDE_BBOX,
    8: OUTSIDE_BBOX,
    9: OUTSIDE_BBOX,
    10: OUTSIDE_BBOX,
}
FRAME_COUNT = len(_BBOX_BY_FRAME_ID)


def _policy() -> MonitoringPolicy:
    return MonitoringPolicy(
        zone_entry_confirm_seconds=1.0,
        zone_exit_confirm_seconds=1.0,
        exit_reentry_confirmation_seconds=1.0,
        entry_zone_min_overlap_ratio=0.4,
        parking_confirm_seconds=1.0,
        parking_move_confirm_seconds=1.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.5,
        reidentification_max_gap_seconds=1.0,
        reidentification_min_score=0.42,
        reidentification_ambiguity_margin=0.08,
        incident_confirm_seconds=0.0,
        incident_clear_seconds=0.0,
        zone_presence_min_overlap_ratio=0.5,
        assignment_min_overlap_ratio=0.5,
        assignment_ambiguous_margin=0.05,
        bad_parking_min_primary_overlap_ratio=0.75,
        bad_parking_min_secondary_overlap_ratio=0.25,
        out_of_zone_min_spot_overlap_ratio=0.50,
        blocking_relation_confirm_seconds=1.0,
        blocking_relation_clear_seconds=1.0,
        blocking_min_subject_overlap_ratio=0.40,
        blocking_min_egress_coverage_ratio=0.40,
        # Scripted frames are one second apart. Keep enough history for the
        # replay fixture to confirm PARKED before restricted-zone incidents.
        motion_window_seconds=3.0,
        motion_min_observation_span_seconds=0.20,
        motion_max_sample_gap_seconds=1.50,
        motion_stationary_threshold=0.03,
        motion_moving_threshold=0.10,
        motion_min_samples=3,
        motion_min_trend_consistency=0.60,
    )


def _patch_deterministic_uuids(monkeypatch) -> None:
    """네 발급처의 uuid4()를 호출 순서 기반 카운터로 고정한다.

    네 모듈이 같은 카운터를 공유해야 한 실행 안에서 발급 순서가 재현되고,
    호출마다 새 카운터를 만들어야 두 실행이 똑같이 1부터 시작한다 — 이
    함수를 실행 직전마다 다시 불러야 한다."""

    counter = count(1)

    def _uuid4() -> UUID:
        return UUID(int=next(counter))

    monkeypatch.setattr("src.tracking.entity_resolver.uuid4", _uuid4)
    monkeypatch.setattr("src.parking.zone_visit_tracker.uuid4", _uuid4)
    monkeypatch.setattr("src.parking.parking_episode_tracker.uuid4", _uuid4)
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
            calibration_id=CALIBRATION_REFERENCE,
        )
        self._next_frame_id += 1
        return frame

    def close(self) -> None:
        pass


class _ScriptedDetector:
    """차 한 대가 입출차 구역을 지나 전용구역에 들어갔다 나가는 고정 궤적."""

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(library="fake", library_version="0", model_name="fake.pt", tracker_config="fake.yaml")

    def open(self) -> None:
        pass

    def track(self, frame: CapturedFrame) -> TrackerFrameResult:
        bbox = _BBOX_BY_FRAME_ID.get(frame.frame_id)
        if bbox is None:
            return TrackerFrameResult(observations=(), all_detections_tracked=True)
        return TrackerFrameResult(
            observations=(
                TrackObservation(
                    track_segment_id=TrackSegmentId(1), bbox=bbox, confidence=0.9, observed_at=frame.captured_at
                ),
            ),
            all_detections_tracked=True,
        )

    def close(self) -> None:
        pass


def _receive_entry_event(connection: sqlite3.Connection, *, t0: datetime) -> None:
    """백엔드 입차 이벤트 한 건을 실제 접수 경계로 durable 저장한다."""

    intake = EntryEventIntake(
        EntryMatchCoordinator(zones=ZoneRegistry((DISABLED_ZONE, ENTRY_ZONE))),
        match_window_seconds=10.0,
    )
    intake.receive(
        EntryDecisionInput(
            entry_attempt_id=UUID(TRACKING_ID),
            decision_revision=1,
            entry_time=t0,
            access_decision=EntryAccessDecision.ALLOW,
            session_context=EntrySessionContextInput(
                session_id=55,
                vehicle_id=10,
                is_disabled_vehicle=False,
                is_electric=True,
            ),
        ),
        idempotency_key="rpi-request-1",
        connection=connection,
    )


def _run_replay(tmp_path: Path, *, run_label: str, t0: datetime) -> bytes:
    database_path = tmp_path / f"{run_label}.db"
    connection = open_database(database_path)
    try:
        _receive_entry_event(connection, t0=t0)
    finally:
        connection.close()

    events_path = tmp_path / f"{run_label}_events.jsonl"
    with events_path.open("w", encoding="utf-8", newline="\n") as events_handle:
        zones = ZoneRegistry((DISABLED_ZONE, ENTRY_ZONE))
        pipeline = build_monitoring_pipeline(
            zones=zones,
            egress_aisles=EgressAisleRegistry.empty(zones),
            policy=_policy(),
            dependencies=MonitoringDependencies(
                camera_id="cam-1",
                frame_source=_ScriptedFrameSource(frame_count=FRAME_COUNT, t0=t0),
                detector=_ScriptedDetector(),
                publication_preparer=JsonlPublicationPreparer(events_handle=events_handle),
                connection_factory=lambda: connect_database(database_path),
            ),
        )
        pipeline.open()
        try:
            pipeline.run()
        finally:
            pipeline.close()
    return events_path.read_bytes()


def _records(payload: bytes) -> list[dict]:
    return [json.loads(line) for line in payload.decode("utf-8").splitlines()]


def test_two_runs_produce_byte_identical_outbox(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    first = _run_replay(tmp_path, run_label="a", t0=t0)

    _patch_deterministic_uuids(monkeypatch)
    second = _run_replay(tmp_path, run_label="b", t0=t0)

    assert first == second
    assert first, "이벤트가 하나도 없으면 결정론을 확인한 것이 아니다"


def test_delivery_ids_are_derived_from_aggregate_identity(tmp_path, monkeypatch):
    """`deliveryId`가 난수가 아니라 집계 identity에서 나온다.

    `JsonlPublicationPreparer`가 새 비결정 요소를 들이지 않는다는 것이
    위 바이트 동등성의 전제다 — envelope 4-tuple만으로 재구성되는지
    직접 확인한다.
    """

    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    records = _records(_run_replay(tmp_path, run_label="delivery", t0=t0))

    assert records
    for record in records:
        assert record["deliveryId"] == (
            f"{record['aggregateType']}:{record['aggregateId']}:"
            f"{record['transitionType']}:{record['publicationRevision']}"
        )
    assert len({record["deliveryId"] for record in records}) == len(records)


def test_shifting_t0_shifts_event_timestamps_only(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)
    offset = timedelta(hours=3)

    _patch_deterministic_uuids(monkeypatch)
    base_records = _records(_run_replay(tmp_path, run_label="base", t0=t0))
    _patch_deterministic_uuids(monkeypatch)
    shifted_records = _records(_run_replay(tmp_path, run_label="shifted", t0=t0 + offset))

    assert base_records, "이벤트가 하나도 없으면 시간 이동을 확인한 것이 아니다"
    assert len(base_records) == len(shifted_records)
    for before, after in zip(base_records, shifted_records):
        assert before["aggregateType"] == after["aggregateType"]
        assert before["aggregateId"] == after["aggregateId"]
        assert before["transitionType"] == after["transitionType"]
        assert before["publicationRevision"] == after["publicationRevision"]
        # occurredAt만 옮겨서는 "시간만 옮겨가고 다른 건 안 바뀐다"는 것을
        # 증명하지 못한다 — 각 전이가 들고 있는 다른 시각들도 같은 offset만큼
        # 옮겨야 판정 로직이 벽시계가 아니라 t0 기준 상대 시간으로만 돈다는
        # 뜻이다.
        for field in ("occurredAt", "firstObservedAt", "confirmedAt", "resolvedAt"):
            if before.get(field) is None or after.get(field) is None:
                continue
            assert datetime.fromisoformat(after[field]) - datetime.fromisoformat(
                before[field]
            ) == offset

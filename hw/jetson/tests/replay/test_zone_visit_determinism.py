"""ZoneVisit 리플레이(`--out-zone-visits`) 결정론 테스트(465/T-17 최종 리뷰).

`tests/application/test_replay_determinism.py`는 `--out-events`(프로덕션
outbox)의 결정론을 확인한다. 그쪽은 결정론을 보이기 위해 백엔드 입차
이벤트를 일부러 주입해야 한다 — 확정 전이가 outbox까지 가려면
`ParkingSession` correlation이 필요하기 때문이다
(`scripts/replay_pilot_video.py` 모듈 docstring 참고). 반면 §4.7 임계값
산출이 실제로 쓰는 산출물은 세션 없이도 채워지는 `--out-zone-visits`다.
그 파일이 결정론적이라는 것을 증명하는 테스트가 없었다 — 이 파일이 그
공백을 채운다. 여기서는 세션을 주입하지 않아 파일럿 영상 리플레이와 같은
조건(백엔드 이벤트 없음)을 그대로 재현한다.

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

import pytest

# camera module은 calibration runtime에서 numpy를 사용한다
# (tests/application/test_monitoring_factory.py와 같은 이유).
pytest.importorskip("numpy")

from src.application.monitoring_factory import (
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.camera.frame_source import EndOfVideo
from src.camera.models import CapturedFrame
from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.replay.publication_preparer import JsonlPublicationPreparer
from src.replay.zone_visit_publisher import DedupingZoneVisitPublisher, ZoneVisitJsonlPublisher
from src.storage.database import connect_database, open_database
from src.tracking.models import BoundingBox, TrackerFrameResult, TrackObservation, TrackSegmentId
from src.tracking.protocols import ModelInfo

CALIBRATION_REFERENCE = "pilot-calibration"

# 한 구역에 완전히 들어간 bbox와 완전히 벗어난 bbox. 겹침 비율이 각각
# 1.0/0.0에 가까워 min_overlap_ratio=0.5 경계 근처의 우연한 흔들림이 없다.
INSIDE_BBOX = BoundingBox(0.15, 0.15, 0.25, 0.25)
OUTSIDE_BBOX = BoundingBox(0.6, 0.6, 0.7, 0.7)
DISABLED_ZONE = ZoneDefinition(
    zone_id=ZoneId(1),
    zone_type=ZoneType.DISABLED,
    polygon=((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3)),
    zone_definition_version=ZoneDefinitionVersion(1),
    calibration_reference=CALIBRATION_REFERENCE,
)
# ENTRY_EXIT 구역은 이 시나리오에서 쓰이지 않지만, 실제 배포 registry와 같은
# 구성으로 두어 EntryMatchCoordinator가 빈 입차 구역으로 조립되지 않게 한다.
ENTRY_ZONE = ZoneDefinition(
    zone_id=ZoneId(9),
    zone_type=ZoneType.ENTRY_EXIT,
    polygon=((0.4, 0.4), (0.5, 0.4), (0.5, 0.5), (0.4, 0.5)),
    zone_definition_version=ZoneDefinitionVersion(1),
    calibration_reference=CALIBRATION_REFERENCE,
    entry_exit_role=EntryExitRole.ENTRY,
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


def _policy() -> MonitoringPolicy:
    return MonitoringPolicy(
        zone_entry_confirm_seconds=1.0,
        zone_exit_confirm_seconds=1.0,
        entry_zone_min_overlap_ratio=0.4,
        parking_confirm_seconds=600.0,
        parking_move_confirm_seconds=1.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.5,
        incident_confirm_seconds=0.0,
        incident_clear_seconds=0.0,
        zone_presence_min_overlap_ratio=0.5,
        assignment_min_overlap_ratio=0.5,
        assignment_ambiguous_margin=0.05,
        blocking_relation_confirm_seconds=1.0,
        blocking_relation_clear_seconds=1.0,
    )


def _patch_deterministic_uuids(monkeypatch) -> None:
    """uuid4()를 호출 순서 기반 카운터로 고정한다.

    `test_replay_determinism.py`의 `_patch_deterministic_uuids`와 같은 이유다
    — physicalVehicleId(entity_resolver)와 zoneVisitId(zone_visit_tracker)를
    둘 다 uuid4()로 발급하므로, 두 실행이 처음부터 같은 카운터로 시작해야
    발급 순서가 재현된다. parking_episode_tracker도 같은 카운터를 공유해야
    한 실행 안의 발급 순서가 재현된다. incident_reducer는 여기서 쓰지
    않는다(§4.7은 zone-visits만 본다).
    """

    counter = count(1)

    def _uuid4() -> UUID:
        return UUID(int=next(counter))

    monkeypatch.setattr("src.tracking.entity_resolver.uuid4", _uuid4)
    monkeypatch.setattr("src.parking.zone_visit_tracker.uuid4", _uuid4)
    monkeypatch.setattr("src.parking.parking_episode_tracker.uuid4", _uuid4)


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
            # RemapFrameSource가 실제 리플레이에서 찍는 값과 같은 역할 —
            # zones의 calibration_reference와 일치해야 full_area_observed다.
            calibration_id=CALIBRATION_REFERENCE,
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


def _run_zone_visit_replay(tmp_path: Path, *, run_label: str, t0: datetime) -> tuple[bytes, int, bytes]:
    """스크립트 더블로 5프레임을 돌리고 산출물을 반환한다.

    반환값은 (zone-visits JSONL 바이트, 원본 zone_visit_updates 총 건수,
    events JSONL 바이트)다.
    """

    database_path = tmp_path / f"{run_label}.db"
    open_database(database_path).close()

    zone_visits_path = tmp_path / f"{run_label}_zone_visits.jsonl"
    events_path = tmp_path / f"{run_label}_events.jsonl"
    zone_visit_publisher = ZoneVisitJsonlPublisher(path=zone_visits_path)
    deduper = DedupingZoneVisitPublisher(zone_visit_publisher)

    raw_update_count = 0
    with events_path.open("w", encoding="utf-8", newline="\n") as events_handle:
        pipeline = build_monitoring_pipeline(
            zones=ZoneRegistry((DISABLED_ZONE, ENTRY_ZONE)),
            policy=_policy(),
            dependencies=MonitoringDependencies(
                camera_id="cam-1",
                frame_source=_ScriptedFrameSource(frame_count=5, t0=t0),
                detector=_ScriptedDetector(),
                publication_preparer=JsonlPublicationPreparer(events_handle=events_handle),
                connection_factory=lambda: connect_database(database_path),
            ),
        )
        pipeline.open()
        zone_visit_publisher.open()
        try:
            while True:
                try:
                    result = pipeline.process_next_frame()
                except EndOfVideo:
                    break
                updates = result.parking_result.zone_visit_updates
                raw_update_count += len(updates)
                deduper.publish_all(updates)
        finally:
            zone_visit_publisher.close()
            pipeline.close()

    return zone_visits_path.read_bytes(), raw_update_count, events_path.read_bytes()


def test_two_runs_produce_byte_identical_zone_visits(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    first, _, _ = _run_zone_visit_replay(tmp_path, run_label="a", t0=t0)

    _patch_deterministic_uuids(monkeypatch)
    second, _, _ = _run_zone_visit_replay(tmp_path, run_label="b", t0=t0)

    assert first == second
    assert first, "zone visit이 하나도 없으면 결정론을 확인한 것이 아니다"


def test_zone_visit_dedup_drops_repeated_state_but_keeps_every_transition(tmp_path, monkeypatch):
    """dedup이 raw 업데이트 수보다 적게 쓰되, 상태 전이는 모두 남긴다."""

    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    out_bytes, raw_update_count, _ = _run_zone_visit_replay(tmp_path, run_label="dedup", t0=t0)

    records = [json.loads(line) for line in out_bytes.decode("utf-8").splitlines()]
    states = [record["state"] for record in records]

    # frame3(INSIDE 유지)이 원본에는 INSIDE를 한 번 더 반환하지만 dedup이
    # 걸러야 한다 — 그래서 발행 건수가 raw 건수보다 적어야 한다.
    assert len(records) < raw_update_count
    # 464에서 OUTSIDE가 사라지고 종료 상태가 ENDED/CANCELED로 갈렸다.
    assert states == ["ENTERING", "INSIDE", "EXITING", "ENDED"]


def test_events_file_stays_empty_without_backend_session(tmp_path, monkeypatch):
    """백엔드 입차 이벤트가 없으면 `--out-events`는 비어 있다(실측).

    `scripts/replay_pilot_video.py`와 `src/replay/zone_visit_publisher.py`의
    docstring이 주장하는 성질이다. 옛 docstring은 이유를 `restricted_zone`
    규칙의 `confirmable=False` 하나로 설명했지만, 실제 차단 지점은 그보다
    앞단인 session correlation이라 세 전이(ParkingTransition,
    IncidentTransition, SessionExitTransition) 모두에 걸린다 — 이 테스트는
    차량이 전용구역에 정말 들어갔다 나가는(=ZoneVisit이 4건 발행되는) 같은
    실행에서 events가 0줄인지를 직접 확인해 그 서술을 붙잡아 둔다.
    """

    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    zone_visits, _, events = _run_zone_visit_replay(tmp_path, run_label="no-session", t0=t0)

    assert zone_visits, "방문이 0건이면 '사건만 비어 있다'를 확인한 것이 아니다"
    assert events == b""


def test_zone_visit_records_carry_state_matched_observed_at(tmp_path, monkeypatch):
    t0 = datetime(2026, 7, 31, 10, 0, 0, tzinfo=timezone.utc)

    _patch_deterministic_uuids(monkeypatch)
    out_bytes, _, _ = _run_zone_visit_replay(tmp_path, run_label="observed-at", t0=t0)

    records = [json.loads(line) for line in out_bytes.decode("utf-8").splitlines()]
    by_state = {record["state"]: record for record in records}

    assert by_state["ENTERING"]["observedAt"] == by_state["ENTERING"]["enteredCandidateAt"]
    assert by_state["INSIDE"]["observedAt"] == by_state["INSIDE"]["enteredAt"]
    assert by_state["EXITING"]["observedAt"] == by_state["EXITING"]["exitCandidateAt"]
    assert by_state["ENDED"]["observedAt"] == by_state["ENDED"]["endedAt"]

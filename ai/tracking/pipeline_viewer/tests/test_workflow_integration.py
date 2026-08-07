"""Viewer trace가 실제 Jetson workflow의 commit 출력을 받는 통합 테스트."""

from datetime import timedelta
from pathlib import Path

import numpy as np

from pipeline_viewer.service import build_allow_example, parse_entry_event
from pipeline_viewer.tracing import TraceCollector, parse_entry_attempt_id
from src.application.entry_event_intake import EntryEventIntake
from src.application.monitoring_factory import (
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.camera.frame_source import EPOCH, EndOfVideo
from src.camera.models import CapturedFrame
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
from src.session.models import EntryMatchState
from src.storage.database import connect_database, open_database
from src.tracking.models import (
    BoundingBox,
    TrackerFrameResult,
    TrackObservation,
    TrackSegmentId,
)
from src.tracking.protocols import ModelInfo


CALIBRATION_REFERENCE = "viewer-test-calibration"
ENTRY_ZONE = ZoneDefinition(
    zone_id=ZoneId(9),
    zone_type=ZoneType.ENTRY_EXIT,
    polygon=((0.4, 0.4), (0.6, 0.4), (0.6, 0.6), (0.4, 0.6)),
    zone_definition_version=ZoneDefinitionVersion(1),
    calibration_reference=CALIBRATION_REFERENCE,
    entry_exit_role=EntryExitRole.ENTRY,
)


class _OneFrameSource:
    def __init__(self) -> None:
        self._captured = False

    def open(self) -> None:
        pass

    def capture(self) -> CapturedFrame:
        if self._captured:
            raise EndOfVideo("done")
        self._captured = True
        return CapturedFrame(
            camera_id="cam-1",
            frame_id=1,
            captured_at=EPOCH,
            image=np.zeros((100, 100, 3), dtype=np.uint8),
            width=100,
            height=100,
            calibration_id=CALIBRATION_REFERENCE,
        )

    def close(self) -> None:
        pass


class _EntryDetector:
    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo(
            library="fake",
            library_version="0",
            model_name="fake.pt",
            tracker_config="fake.yaml",
        )

    def open(self) -> None:
        pass

    def track(self, frame: CapturedFrame) -> TrackerFrameResult:
        return TrackerFrameResult(
            observations=(
                TrackObservation(
                    track_segment_id=TrackSegmentId(1),
                    bbox=BoundingBox(0.45, 0.45, 0.55, 0.55),
                    confidence=0.95,
                    observed_at=frame.captured_at,
                ),
            ),
            all_detections_tracked=True,
        )

    def close(self) -> None:
        pass


def _policy() -> MonitoringPolicy:
    return MonitoringPolicy(
        zone_entry_confirm_seconds=1.0,
        zone_exit_confirm_seconds=1.0,
        exit_reentry_confirmation_seconds=1.0,
        entry_zone_min_overlap_ratio=0.4,
        parking_confirm_seconds=600.0,
        parking_move_confirm_seconds=1.0,
        absence_confirmation_seconds=5.0,
        trusted_sample_max_gap_seconds=1.5,
        motion_window_seconds=0.75,
        motion_min_observation_span_seconds=0.20,
        motion_max_sample_gap_seconds=0.50,
        motion_stationary_threshold=0.03,
        motion_moving_threshold=0.10,
        motion_min_samples=3,
        motion_min_trend_consistency=0.60,
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
    )


def test_trace_observes_real_entry_match_and_frame_workflow(tmp_path: Path) -> None:
    zones = ZoneRegistry((ENTRY_ZONE,))
    database_path = tmp_path / "viewer.db"
    connection = open_database(database_path)
    payload = parse_entry_event(build_allow_example())
    try:
        acceptance = EntryEventIntake(
            EntryMatchCoordinator(zones=zones),
            match_window_seconds=10.0,
        ).receive(
            payload.to_input(),
            idempotency_key="viewer-test",
            connection=connection,
        )
    finally:
        connection.close()
    assert acceptance.created is True

    connection_factory = lambda: connect_database(database_path)
    collector = TraceCollector(
        frames_directory=tmp_path / "frames",
        zones=zones.all(),
        entry_attempt_id=parse_entry_attempt_id(payload.entry_attempt_id),
        connection_factory=connection_factory,
    )
    pipeline = build_monitoring_pipeline(
        zones=zones,
        egress_aisles=EgressAisleRegistry.empty(zones),
        policy=_policy(),
        dependencies=MonitoringDependencies(
            camera_id="cam-1",
            frame_source=_OneFrameSource(),
            detector=_EntryDetector(),
            publication_preparer=JsonlPublicationPreparer(),
            connection_factory=connection_factory,
        ),
    )

    pipeline.open()
    try:
        result = pipeline.process_next_frame(frame_observer=collector.observe)
    finally:
        pipeline.close()

    assert len(collector.frames) == 1
    trace = collector.frames[0]
    assert trace.result is result
    assert trace.tracking_batch.frame_id == 1
    assert trace.entry_attempt is not None
    assert trace.entry_attempt.match_state is EntryMatchState.MATCHED
    assert trace.image_path.is_file()
    assert list(collector.aliases.values()) == ["V1"]
    assert any(
        change.category == "EntryMatch" and change.current_state == "MATCHED"
        for change in trace.changes
    )

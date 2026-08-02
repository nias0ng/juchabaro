"""Monitoring composition root가 owner를 실제 durable pipeline으로 잇는지 확인한다."""

from __future__ import annotations

from pathlib import Path

import pytest

# camera module은 calibration runtime에서 numpy를 사용한다. Jetson/full dev
# 환경에서는 실행하고 storage 전용 경량 환경에서는 module 단위로 건너뛴다.
pytest.importorskip("numpy")

from src.application.monitoring_factory import (
    MonitoringDependencies,
    MonitoringPolicy,
    build_monitoring_pipeline,
)
from src.camera.frame_source import EndOfVideo
from src.communication.outbox import PreparedPublication
from src.parking.models import (
    EntryExitRole,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.storage.database import connect_database, open_database
from src.tracking.models import TrackerFrameResult
from src.tracking.protocols import ModelInfo


class _FrameSource:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def capture(self):
        raise EndOfVideo("empty source")

    def close(self) -> None:
        self.closed = True


class _Detector:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False

    @property
    def model_info(self) -> ModelInfo:
        return ModelInfo("fake", "1", "none", "none")

    def open(self) -> None:
        self.opened = True

    def track(self, _frame) -> TrackerFrameResult:
        return TrackerFrameResult(
            observations=(),
            all_detections_tracked=True,
            ended_track_segment_ids=(),
        )

    def close(self) -> None:
        self.closed = True


class _PublicationPreparer:
    def prepare_parking(self, _transition) -> PreparedPublication:
        raise AssertionError("empty source must not publish")

    def prepare_incident(self, _transition) -> PreparedPublication:
        raise AssertionError("empty source must not publish")

    def prepare_session_exit(self, _transition) -> PreparedPublication:
        raise AssertionError("empty source must not publish")


def _zones() -> ZoneRegistry:
    return ZoneRegistry(
        (
            ZoneDefinition(
                zone_id=ZoneId(1),
                zone_type=ZoneType.ENTRY_EXIT,
                polygon=((0.0, 0.0), (0.2, 0.0), (0.2, 0.2)),
                zone_definition_version=ZoneDefinitionVersion(1),
                calibration_reference="pilot-calibration",
                entry_exit_role=EntryExitRole.ENTRY,
            ),
        )
    )


def _policy(**overrides: float) -> MonitoringPolicy:
    values = {
        "zone_entry_confirm_seconds": 1.0,
        "zone_exit_confirm_seconds": 1.0,
        "entry_zone_min_overlap_ratio": 0.4,
        "parking_confirm_seconds": 600.0,
        "parking_move_confirm_seconds": 1.0,
        "absence_confirmation_seconds": 5.0,
        "trusted_sample_max_gap_seconds": 1.0,
        "incident_confirm_seconds": 0.0,
        "incident_clear_seconds": 0.0,
        "zone_presence_min_overlap_ratio": 0.5,
        "assignment_min_overlap_ratio": 0.5,
        "assignment_ambiguous_margin": 0.05,
    }
    values.update(overrides)
    return MonitoringPolicy(**values)


def test_factory_builds_one_recoverable_monitoring_owner(tmp_path: Path) -> None:
    database_path = tmp_path / "factory.db"
    connection = open_database(database_path)
    connection.close()
    frame_source = _FrameSource()
    detector = _Detector()
    pipeline = build_monitoring_pipeline(
        zones=_zones(),
        policy=_policy(),
        dependencies=MonitoringDependencies(
            camera_id="camera-1",
            frame_source=frame_source,
            detector=detector,
            publication_preparer=_PublicationPreparer(),
            connection_factory=lambda: connect_database(database_path),
        ),
    )

    pipeline.open()
    try:
        assert pipeline.run() == 0
    finally:
        pipeline.close()

    assert frame_source.opened and frame_source.closed
    assert detector.opened and detector.closed


def test_factory_delegates_invalid_policy_to_domain_owner(tmp_path: Path) -> None:
    database_path = tmp_path / "invalid.db"
    connection = open_database(database_path)
    connection.close()

    with pytest.raises(ValueError, match="entry_zone_min_overlap_ratio"):
        build_monitoring_pipeline(
            zones=_zones(),
            policy=_policy(entry_zone_min_overlap_ratio=0.0),
            dependencies=MonitoringDependencies(
                camera_id="camera-1",
                frame_source=_FrameSource(),
                detector=_Detector(),
                publication_preparer=_PublicationPreparer(),
                connection_factory=lambda: connect_database(database_path),
            ),
        )

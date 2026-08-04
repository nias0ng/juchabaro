"""Pipeline Viewer CSV export의 행 계약과 진단 경계."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import StringIO
from types import SimpleNamespace
from uuid import UUID

import pytest
from pipeline_viewer.export import (
    DIAGNOSTIC_FIELDS,
    STATE_CHANGE_FIELDS,
    csv_bytes,
    diagnostic_rows,
    state_change_rows,
)
from src.domain.models import ObservationState, ObservationStatus
from src.tracking.models import (
    BoundingBox,
    DetectionObservation,
    MotionSignal,
    PhysicalVehicleSnapshot,
    TrackingBatch,
)


OBSERVED_AT = datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc)
VEHICLE_ID = UUID("12345678-1234-5678-1234-567812345678")


def _frame(*, with_detection: bool) -> SimpleNamespace:
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=OBSERVED_AT,
    )
    if with_detection:
        detections = (
            DetectionObservation(
                bbox=BoundingBox(0.1, 0.2, 0.3, 0.4),
                confidence=0.27,
                class_id=0,
            ),
        )
        vehicles = (
            PhysicalVehicleSnapshot(
                physical_vehicle_id=VEHICLE_ID,
                track_segment_id=7,
                bbox=BoundingBox(0.1, 0.2, 0.3, 0.4),
                confidence=0.31,
                motion_signal=MotionSignal.STATIONARY,
                observed_at=OBSERVED_AT,
                camera_id="PIPELINE-VIEWER",
                observation=observation,
            ),
        )
    else:
        detections = ()
        vehicles = ()
    return SimpleNamespace(
        frame_id=7 if with_detection else 8,
        video_seconds=0.2 if with_detection else 0.233,
        captured_at=OBSERVED_AT,
        tracking_batch=TrackingBatch(
            camera_id="PIPELINE-VIEWER",
            frame_id=7 if with_detection else 8,
            observed_at=OBSERVED_AT,
            vehicles=vehicles,
            ended_track_segment_ids=(),
            unobserved_physical_vehicle_ids=(),
            absence_progress=(),
            observation=observation,
            full_area_observed=True,
            all_detections_tracked=True,
            detection_count=len(detections),
            detections=detections,
        ),
        changes=(
            (
                SimpleNamespace(
                    category="ParkingEpisode",
                    scope_id="episode-1",
                    previous_state="STOP_PENDING",
                    current_state="PARKED",
                ),
            )
            if with_detection
            else ()
        ),
        elapsed_ms=12.5,
    )


def test_state_change_export_preserves_existing_column_contract() -> None:
    rows = state_change_rows((_frame(with_detection=True),))

    assert rows == [
        {
            "frame": 7,
            "videoTime": "00:00.200",
            "category": "ParkingEpisode",
            "scopeId": "episode-1",
            "previous": "STOP_PENDING",
            "current": "PARKED",
        }
    ]


def test_diagnostic_export_keeps_empty_frames_and_separates_stages() -> None:
    rows = diagnostic_rows(
        (_frame(with_detection=True), _frame(with_detection=False)),
        aliases={VEHICLE_ID: "V1"},
        detection_threshold=0.01,
        model_path="hw/jetson/model/yolov8s.pt",
        tracker_config="bytetrack.yaml",
    )

    assert [row["rowType"] for row in rows] == [
        "FRAME",
        "DETECTION",
        "TRACKED_VEHICLE",
        "FRAME",
    ]
    detection = rows[1]
    tracked = rows[2]
    empty_frame = rows[3]
    assert detection["detectionStage"] == "POST_THRESHOLD_PRE_TRACK"
    assert detection["confidence"] == pytest.approx(0.27)
    assert detection["detectionThreshold"] == pytest.approx(0.01)
    assert detection["modelPath"] == "hw/jetson/model/yolov8s.pt"
    assert detection["trackerConfig"] == "bytetrack.yaml"
    assert tracked["detectionStage"] == "POST_TRACK"
    assert tracked["confidence"] == pytest.approx(0.31)
    assert tracked["vehicleAlias"] == "V1"
    assert empty_frame["pretrackDetectionCount"] == 0
    assert empty_frame["trackedVehicleCount"] == 0


def test_csv_bytes_emits_utf8_bom_and_requested_header() -> None:
    rows = state_change_rows((_frame(with_detection=True),))

    payload = csv_bytes(rows, fieldnames=STATE_CHANGE_FIELDS)
    parsed = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))

    assert payload.startswith(b"\xef\xbb\xbf")
    assert tuple(parsed[0]) == STATE_CHANGE_FIELDS
    assert parsed[0]["frame"] == "7"
    assert set(DIAGNOSTIC_FIELDS).issuperset({"rowType", "confidence"})

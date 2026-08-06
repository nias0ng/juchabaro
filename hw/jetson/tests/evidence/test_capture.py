"""Incident frame crop 정책과 RESERVED→READY 배선을 검증한다."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import cv2
import numpy as np

from src.camera.models import CapturedFrame
from src.diagnostics import DiagnosticEvent, DiagnosticEventType
from src.domain.models import ObservationState, ObservationStatus
from src.evidence.capture import (
    EvidenceCaptureCoordinator,
    IncidentEvidenceRenderer,
)
from src.evidence.capture_models import EvidenceCaptureIntent, EvidenceCropKind
from src.evidence.models import EvidenceArtifact, EvidenceId, EvidenceState
from src.parking.models import (
    IncidentId,
    ZoneDefinition,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneType,
)
from src.parking.zone_registry import ZoneRegistry
from src.storage.database import connect_database, open_database
from src.storage.evidence_repository import EvidenceArtifactRepository
from src.storage.unit_of_work import UnitOfWork
from src.tracking.models import (
    BoundingBox,
    MotionSignal,
    PhysicalVehicleId,
    PhysicalVehicleSnapshot,
    TrackSegmentId,
    TrackingBatch,
)


NOW = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
SUBJECT = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000021")
)
VICTIM = PhysicalVehicleId(
    UUID("10000000-0000-4000-8000-000000000022")
)
INCIDENT = IncidentId(
    UUID("50000000-0000-4000-8000-000000000021")
)
OBSERVED = ObservationStatus(
    state=ObservationState.OBSERVED,
    last_reliable_observed_at=NOW,
)


class RecordingDiagnosticsSink:
    def __init__(self) -> None:
        self.events: list[DiagnosticEvent] = []

    def emit(self, event: DiagnosticEvent) -> None:
        self.events.append(event)


def _zones() -> ZoneRegistry:
    return ZoneRegistry(
        (
            ZoneDefinition(
                zone_id=ZoneId(1),
                zone_type=ZoneType.DISABLED,
                polygon=(
                    (0.15, 0.35),
                    (0.35, 0.35),
                    (0.35, 0.65),
                    (0.15, 0.65),
                ),
                zone_definition_version=ZoneDefinitionVersion(1),
                calibration_reference="pilot-v1",
            ),
            ZoneDefinition(
                zone_id=ZoneId(7),
                zone_type=ZoneType.AISLE,
                polygon=(
                    (0.02, 0.05),
                    (0.98, 0.05),
                    (0.98, 0.95),
                    (0.02, 0.95),
                ),
                zone_definition_version=ZoneDefinitionVersion(1),
                calibration_reference="pilot-v1",
            ),
        )
    )


def _snapshot(
    vehicle_id: PhysicalVehicleId,
    track_id: int,
    bbox: BoundingBox,
) -> PhysicalVehicleSnapshot:
    return PhysicalVehicleSnapshot(
        physical_vehicle_id=vehicle_id,
        track_segment_id=TrackSegmentId(track_id),
        bbox=bbox,
        confidence=0.95,
        motion_signal=MotionSignal.STATIONARY,
        observed_at=NOW,
        camera_id="camera-1",
        observation=OBSERVED,
    )


def _frame_and_batch() -> tuple[CapturedFrame, TrackingBatch]:
    width, height = 1920, 1080
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 1] = np.linspace(0, 255, width, dtype=np.uint8)
    frame = CapturedFrame(
        camera_id="camera-1",
        frame_id=10,
        captured_at=NOW,
        image=image,
        width=width,
        height=height,
        calibration_id="pilot-v1",
    )
    snapshots = (
        _snapshot(SUBJECT, 1, BoundingBox(0.47, 0.42, 0.57, 0.62)),
        _snapshot(VICTIM, 2, BoundingBox(0.18, 0.40, 0.28, 0.60)),
    )
    return frame, TrackingBatch(
        camera_id="camera-1",
        frame_id=10,
        observed_at=NOW,
        vehicles=snapshots,
        ended_track_segment_ids=(),
        unobserved_physical_vehicle_ids=(),
        absence_progress=(),
        observation=OBSERVED,
        full_area_observed=True,
        all_detections_tracked=True,
    )


def _intent(
    *,
    rule_code: str,
    crop_kind: EvidenceCropKind = EvidenceCropKind.CONTEXT,
    zone_id: ZoneId | None = None,
    victim: PhysicalVehicleId | None = None,
    evidence_id: EvidenceId | None = None,
) -> EvidenceCaptureIntent:
    return EvidenceCaptureIntent(
        evidence_id=evidence_id or EvidenceId(uuid4()),
        incident_id=INCIDENT,
        rule_code=rule_code,
        physical_vehicle_id=SUBJECT,
        victim_physical_vehicle_id=victim,
        zone_id=zone_id,
        captured_at=NOW,
        crop_kind=crop_kind,
    )


def test_large_aisle_polygon_uses_vehicle_anchored_local_context() -> None:
    frame, batch = _frame_and_batch()
    renderer = IncidentEvidenceRenderer(zones=_zones())

    window = renderer.plan_crop(
        frame,
        batch,
        _intent(rule_code="AISLE_BLOCK", zone_id=ZoneId(7)),
    )

    assert window.width < frame.width
    assert window.width <= int(frame.width * 0.71)
    assert window.x1 <= int(frame.width * 0.47)
    assert window.x2 >= int(frame.width * 0.57)


def test_double_parking_context_contains_pair_and_detail_focuses_subject() -> None:
    frame, batch = _frame_and_batch()
    renderer = IncidentEvidenceRenderer(zones=_zones())

    context = renderer.plan_crop(
        frame,
        batch,
        _intent(rule_code="DOUBLE_PARKING", victim=VICTIM),
    )
    detail = renderer.plan_crop(
        frame,
        batch,
        _intent(
            rule_code="DOUBLE_PARKING",
            victim=VICTIM,
            crop_kind=EvidenceCropKind.DETAIL,
        ),
    )

    assert context.x1 <= int(frame.width * 0.18)
    assert context.x2 >= int(frame.width * 0.57)
    assert context.width > detail.width


def test_renderer_outputs_frontend_friendly_bounded_jpeg() -> None:
    frame, batch = _frame_and_batch()
    payload = IncidentEvidenceRenderer(zones=_zones()).render_jpeg(
        frame,
        batch,
        _intent(
            rule_code="DISABLED_ZONE_UNAUTHORIZED",
            zone_id=ZoneId(1),
        ),
    )

    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[:2] == (720, 1280)
    assert len(payload) <= 512 * 1024


def test_capture_coordinator_completes_reserved_artifact_to_ready(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "capture.db"
    connection = open_database(database_path)
    evidence_id = EvidenceId(uuid4())
    artifact = EvidenceArtifact(
        evidence_id=evidence_id,
        incident_id=INCIDENT,
        publication_revision=1,
        captured_at=NOW,
        image_type="image/jpeg",
        state=EvidenceState.RESERVED,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    try:
        with UnitOfWork(connection):
            EvidenceArtifactRepository(connection).add(artifact)
    finally:
        connection.close()

    frame, batch = _frame_and_batch()
    diagnostics = RecordingDiagnosticsSink()
    EvidenceCaptureCoordinator(
        connection_factory=lambda: connect_database(database_path),
        zones=_zones(),
        spool_path=tmp_path / "evidence",
        spool_cap_bytes=8 * 1024 * 1024,
        filesystem_floor_ratio=0.0,
        capture_stop_free_ratio=0.0,
        diagnostics_sink=diagnostics,
    ).capture(
        frame,
        batch,
        (_intent(rule_code="AISLE_BLOCK", evidence_id=evidence_id),),
    )

    connection = connect_database(database_path)
    try:
        ready = EvidenceArtifactRepository(connection).get(evidence_id)
    finally:
        connection.close()
    assert ready is not None
    assert ready.state is EvidenceState.READY
    assert ready.local_path is not None and ready.local_path.is_file()
    assert ready.byte_size is not None and ready.byte_size <= 512 * 1024
    assert [event.attributes["result"] for event in diagnostics.events] == [
        "CAPTURE_REQUESTED",
        "CAPTURE_READY",
    ]
    assert all(
        event.event_type
        is DiagnosticEventType.EVIDENCE_PUBLICATION_EVALUATED
        for event in diagnostics.events
    )

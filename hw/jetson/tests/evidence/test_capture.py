"""Incident frame crop 정책과 RESERVED→READY 배선을 검증한다."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import cv2
import numpy as np
import pytest

from src.camera.models import CapturedFrame
from src.diagnostics import DiagnosticEvent, DiagnosticEventType
from src.domain.models import ObservationState, ObservationStatus
from src.evidence.capture import (
    EvidenceCaptureError,
    EvidenceCaptureCoordinator,
    IncidentEvidenceRenderer,
)
from src.evidence.capture_models import EvidenceCaptureIntent, EvidenceCropKind
from src.evidence.models import (
    EvidenceArtifact,
    EvidenceId,
    EvidenceRetentionDisposition,
    EvidenceState,
)
from src.evidence.spool import EvidenceSpool
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


def _reserve(
    connection,
    evidence_id: EvidenceId,
    *,
    incident_id: IncidentId = INCIDENT,
) -> EvidenceArtifact:
    artifact = EvidenceArtifact(
        evidence_id=evidence_id,
        incident_id=incident_id,
        publication_revision=1,
        captured_at=NOW,
        image_type="image/jpeg",
        state=EvidenceState.RESERVED,
        record_version=1,
        created_at=NOW,
        updated_at=NOW,
    )
    with UnitOfWork(connection):
        EvidenceArtifactRepository(connection).add(artifact)
    return artifact


def _coordinator(
    database_path: Path,
    spool_path: Path,
    diagnostics: RecordingDiagnosticsSink,
    *,
    monotonic_clock=None,
) -> EvidenceCaptureCoordinator:
    options = (
        {}
        if monotonic_clock is None
        else {"monotonic_clock": monotonic_clock}
    )
    return EvidenceCaptureCoordinator(
        connection_factory=lambda: connect_database(database_path),
        zones=_zones(),
        spool_path=spool_path,
        spool_cap_bytes=8 * 1024 * 1024,
        filesystem_floor_ratio=0.0,
        capture_stop_free_ratio=0.0,
        diagnostics_sink=diagnostics,
        **options,
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
    try:
        _reserve(connection, evidence_id)
    finally:
        connection.close()

    frame, batch = _frame_and_batch()
    diagnostics = RecordingDiagnosticsSink()
    _coordinator(
        database_path,
        tmp_path / "evidence",
        diagnostics,
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


def test_capture_connection_failure_uses_backoff_and_forced_flush(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "capture.db"
    connection = open_database(database_path)
    evidence_id = EvidenceId(uuid4())
    try:
        _reserve(connection, evidence_id)
    finally:
        connection.close()

    frame, batch = _frame_and_batch()
    diagnostics = RecordingDiagnosticsSink()
    connection_attempts = 0
    monotonic_now = 0.0

    def intermittent_connection():
        nonlocal connection_attempts
        connection_attempts += 1
        if connection_attempts <= 2:
            raise OSError("database unavailable")
        return connect_database(database_path)

    coordinator = EvidenceCaptureCoordinator(
        connection_factory=intermittent_connection,
        zones=_zones(),
        spool_path=tmp_path / "evidence",
        spool_cap_bytes=8 * 1024 * 1024,
        filesystem_floor_ratio=0.0,
        capture_stop_free_ratio=0.0,
        diagnostics_sink=diagnostics,
        monotonic_clock=lambda: monotonic_now,
    )

    coordinator.capture(
        frame,
        batch,
        (_intent(rule_code="AISLE_BLOCK", evidence_id=evidence_id),),
    )

    connection = connect_database(database_path)
    try:
        deferred = EvidenceArtifactRepository(connection).get(evidence_id)
    finally:
        connection.close()
    assert deferred is not None and deferred.state is EvidenceState.RESERVED

    coordinator.capture(frame, batch, ())
    assert connection_attempts == 1

    monotonic_now = 1.0
    coordinator.capture(frame, batch, ())
    assert connection_attempts == 2

    monotonic_now = 2.0
    coordinator.capture(frame, batch, ())
    assert connection_attempts == 2

    coordinator.flush_pending()

    connection = connect_database(database_path)
    try:
        recovered = EvidenceArtifactRepository(connection).get(evidence_id)
    finally:
        connection.close()
    assert recovered is not None and recovered.state is EvidenceState.FAILED
    assert connection_attempts == 3

    assert [event.attributes["result"] for event in diagnostics.events] == [
        "CAPTURE_REQUESTED",
        "CAPTURE_RECOVERY_PENDING",
        "CAPTURE_RECOVERY_PENDING",
        "CAPTURE_RECOVERED_FAILED",
    ]


def test_spool_open_failure_marks_every_reservation_failed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "capture.db"
    connection = open_database(database_path)
    evidence_ids = (EvidenceId(uuid4()), EvidenceId(uuid4()))
    try:
        for evidence_id in evidence_ids:
            _reserve(connection, evidence_id)
    finally:
        connection.close()

    spool_path = tmp_path / "shared-directory"
    spool_path.mkdir()
    (spool_path / "operator-owned.dat").write_bytes(b"not a spool")
    diagnostics = RecordingDiagnosticsSink()
    coordinator = _coordinator(database_path, spool_path, diagnostics)
    frame, batch = _frame_and_batch()
    intents = tuple(
        _intent(
            rule_code="DOUBLE_PARKING",
            victim=VICTIM,
            evidence_id=evidence_id,
            crop_kind=(
                EvidenceCropKind.CONTEXT
                if index == 0
                else EvidenceCropKind.DETAIL
            ),
        )
        for index, evidence_id in enumerate(evidence_ids)
    )

    coordinator.capture(frame, batch, intents)

    connection = connect_database(database_path)
    try:
        artifacts = tuple(
            EvidenceArtifactRepository(connection).get(evidence_id)
            for evidence_id in evidence_ids
        )
    finally:
        connection.close()
    assert all(artifact is not None for artifact in artifacts)
    assert all(artifact.state is EvidenceState.FAILED for artifact in artifacts)
    assert all(
        artifact.retention_disposition
        is EvidenceRetentionDisposition.LOST_OR_CORRUPTED
        for artifact in artifacts
    )
    assert [event.attributes["result"] for event in diagnostics.events] == [
        "CAPTURE_REQUESTED",
        "CAPTURE_REQUESTED",
        "SPOOL_OPEN_FAILED",
        "SPOOL_OPEN_FAILED",
    ]


def test_renderer_failure_marks_one_failed_and_continues_next_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "capture.db"
    connection = open_database(database_path)
    failed_id = EvidenceId(uuid4())
    ready_id = EvidenceId(uuid4())
    try:
        _reserve(connection, failed_id)
        _reserve(connection, ready_id)
    finally:
        connection.close()

    original_render = IncidentEvidenceRenderer.render_jpeg

    def fail_first_render(self, frame, batch, intent):
        if intent.evidence_id == failed_id:
            raise EvidenceCaptureError("subject bbox unavailable")
        return original_render(self, frame, batch, intent)

    monkeypatch.setattr(
        IncidentEvidenceRenderer,
        "render_jpeg",
        fail_first_render,
    )
    diagnostics = RecordingDiagnosticsSink()
    coordinator = _coordinator(
        database_path,
        tmp_path / "evidence",
        diagnostics,
    )
    frame, batch = _frame_and_batch()
    intents = (
        _intent(
            rule_code="DOUBLE_PARKING",
            victim=VICTIM,
            evidence_id=failed_id,
        ),
        _intent(
            rule_code="DOUBLE_PARKING",
            victim=VICTIM,
            evidence_id=ready_id,
            crop_kind=EvidenceCropKind.DETAIL,
        ),
    )

    coordinator.capture(frame, batch, intents)

    connection = connect_database(database_path)
    try:
        failed = EvidenceArtifactRepository(connection).get(failed_id)
        ready = EvidenceArtifactRepository(connection).get(ready_id)
    finally:
        connection.close()
    assert failed is not None and failed.state is EvidenceState.FAILED
    assert ready is not None and ready.state is EvidenceState.READY
    assert [event.attributes["result"] for event in diagnostics.events] == [
        "CAPTURE_REQUESTED",
        "CAPTURE_REQUESTED",
        "CAPTURE_FAILED",
        "CAPTURE_READY",
    ]


def test_post_rename_failure_is_reconciled_before_processing_next_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "capture.db"
    spool_path = tmp_path / "evidence"
    connection = open_database(database_path)
    writing_id = EvidenceId(uuid4())
    ready_id = EvidenceId(uuid4())
    try:
        EvidenceSpool(
            connection=connection,
            root=spool_path,
            spool_cap_bytes=8 * 1024 * 1024,
            filesystem_floor_ratio=0.0,
            capture_stop_free_ratio=0.0,
        )
        _reserve(connection, writing_id)
        _reserve(connection, ready_id)
    finally:
        connection.close()

    original_fsync_directory = EvidenceSpool._fsync_directory
    fsync_calls = 0

    def fail_first_directory_fsync(self) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == 1:
            raise OSError("directory fsync failed")
        original_fsync_directory(self)

    monkeypatch.setattr(
        EvidenceSpool,
        "_fsync_directory",
        fail_first_directory_fsync,
    )
    diagnostics = RecordingDiagnosticsSink()
    coordinator = _coordinator(
        database_path,
        spool_path,
        diagnostics,
    )
    frame, batch = _frame_and_batch()
    intents = (
        _intent(
            rule_code="DOUBLE_PARKING",
            victim=VICTIM,
            evidence_id=writing_id,
        ),
        _intent(
            rule_code="DOUBLE_PARKING",
            victim=VICTIM,
            evidence_id=ready_id,
            crop_kind=EvidenceCropKind.DETAIL,
        ),
    )

    coordinator.capture(frame, batch, intents)

    connection = connect_database(database_path)
    try:
        reconciled = EvidenceArtifactRepository(connection).get(writing_id)
        ready = EvidenceArtifactRepository(connection).get(ready_id)
    finally:
        connection.close()
    assert reconciled is not None and reconciled.state is EvidenceState.READY
    assert ready is not None and ready.state is EvidenceState.READY
    assert fsync_calls == 3
    assert [event.attributes["result"] for event in diagnostics.events] == [
        "CAPTURE_REQUESTED",
        "CAPTURE_REQUESTED",
        "SPOOL_STORE_FAILED",
        "CAPTURE_READY",
    ]

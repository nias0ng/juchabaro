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
from src.parking.assignment_resolver import NO_ELIGIBLE_ZONE
from src.domain.models import ObservationState, ObservationStatus
from src.parking.models import (
    AssignmentState,
    IncidentKey,
    IncidentRuleTiming,
    IncidentSignal,
    IncidentSignalDiagnostic,
    IncidentSignalValue,
    ParkingAssignment,
    ParkingPipelineResult,
    ParkingState,
    PlacementDiagnostic,
    PlacementEvidence,
    PlacementEvidenceSource,
    ZoneDefinitionVersion,
    ZoneId,
    ZoneOverlapEvidence,
)
from src.tracking.models import (
    BoundingBox,
    DetectionObservation,
    IdentityResolution,
    IdentityResolutionOutcome,
    IdentityResolutionReason,
    MotionEstimate,
    MotionEstimateReason,
    MotionSignal,
    PhysicalVehicleSnapshot,
    TrackingBatch,
    TrackSegmentId,
)


OBSERVED_AT = datetime(2026, 8, 4, 1, 2, 3, tzinfo=timezone.utc)
VEHICLE_ID = UUID("12345678-1234-5678-1234-567812345678")


def _placement_diagnostic(*, out_of_zone: bool = False) -> PlacementDiagnostic:
    footprint = ((0.1, 0.1), (0.3, 0.1), (0.3, 0.3), (0.1, 0.3))
    if out_of_zone:
        candidates = (
            ZoneOverlapEvidence(zone_id=ZoneId(1), overlap_ratio=0.3),
        )
        evidence = PlacementEvidence(
            representative_footprint=footprint,
            zone_definition_version=ZoneDefinitionVersion(5),
            observed_at=OBSERVED_AT,
            candidate_overlaps=candidates,
            primary_zone_id=ZoneId(1),
            primary_overlap_ratio=0.3,
            secondary_zone_id=None,
            secondary_overlap_ratio=0.0,
            dominance_gap=0.3,
            spot_union_overlap_ratio=0.3,
            outside_spot_overlap_ratio=0.7,
        )
        assignment = ParkingAssignment(
            state=AssignmentState.UNASSIGNED,
            representative_footprint=footprint,
            confidence=0.3,
            last_stable_at=OBSERVED_AT,
            unassigned_reason=NO_ELIGIBLE_ZONE,
        )
        bad_value = IncidentSignalValue.NOT_MATCHED
        bad_reasons: tuple[str, ...] = ()
        out_value = IncidentSignalValue.MATCHED
        out_reasons = ("INSUFFICIENT_SPOT_UNION_OVERLAP",)
    else:
        candidates = (
            ZoneOverlapEvidence(zone_id=ZoneId(1), overlap_ratio=0.51),
            ZoneOverlapEvidence(zone_id=ZoneId(2), overlap_ratio=0.49),
        )
        evidence = PlacementEvidence(
            representative_footprint=footprint,
            zone_definition_version=ZoneDefinitionVersion(5),
            observed_at=OBSERVED_AT,
            candidate_overlaps=candidates,
            primary_zone_id=ZoneId(1),
            primary_overlap_ratio=0.51,
            secondary_zone_id=ZoneId(2),
            secondary_overlap_ratio=0.49,
            dominance_gap=0.02,
            spot_union_overlap_ratio=1.0,
            outside_spot_overlap_ratio=0.0,
        )
        assignment = ParkingAssignment(
            state=AssignmentState.AMBIGUOUS,
            representative_footprint=footprint,
            confidence=0.51,
            last_stable_at=OBSERVED_AT,
            unassigned_reason="AMBIGUOUS_ZONE_OVERLAP",
        )
        bad_value = IncidentSignalValue.MATCHED
        bad_reasons = (
            "LOW_PRIMARY_OVERLAP",
            "MULTI_SPOT_OVERLAP",
        )
        out_value = IncidentSignalValue.NOT_MATCHED
        out_reasons = ()

    return PlacementDiagnostic(
        physical_vehicle_id=VEHICLE_ID,
        track_segment_id=TrackSegmentId(7),
        source=PlacementEvidenceSource.PARKED_SNAPSHOT,
        evidence=evidence,
        assignment=assignment,
        parking_state=ParkingState.PARKED,
        bad_parking_signal=IncidentSignal(
            key=IncidentKey.for_physical_vehicle(VEHICLE_ID, "BAD_PARKING"),
            value=bad_value,
            confirmable=bad_value is IncidentSignalValue.MATCHED,
            observed_at=OBSERVED_AT,
            evidence={"reasons": bad_reasons},
        ),
        out_of_zone_signal=IncidentSignal(
            key=IncidentKey.for_physical_vehicle(VEHICLE_ID, "OUT_OF_ZONE"),
            value=out_value,
            confirmable=out_value is IncidentSignalValue.MATCHED,
            observed_at=OBSERVED_AT,
            evidence={"reasons": out_reasons},
        ),
    )


def _frame(
    *,
    with_detection: bool,
    out_of_zone: bool = False,
) -> SimpleNamespace:
    observation = ObservationStatus(
        state=ObservationState.OBSERVED,
        last_reliable_observed_at=OBSERVED_AT,
    )
    motion_estimate = MotionEstimate(
        physical_vehicle_id=VEHICLE_ID,
        signal=MotionSignal.STATIONARY,
        reason=MotionEstimateReason.STATIONARY_EVIDENCE,
        observed_at=OBSERVED_AT,
        sample_count=4,
        window_span_seconds=0.3,
        latest_sample_gap_seconds=0.1,
        normalized_displacement=0.01,
        normalized_trend=0.008,
        trend_consistency=0.9,
        reference_bbox_diagonal=0.22,
        stationary_threshold=0.03,
        moving_threshold=0.10,
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
                motion_estimate=motion_estimate,
            ),
        )
    else:
        detections = ()
        vehicles = ()
    identity_resolutions = (
        (
            IdentityResolution(
                track_segment_id=7,
                outcome=IdentityResolutionOutcome.CREATED,
                physical_vehicle_id=VEHICLE_ID,
                candidate_count=0,
                reason=IdentityResolutionReason.NO_ELIGIBLE_CANDIDATE,
            ),
        )
        if with_detection
        else ()
    )
    placement_diagnostic = (
        _placement_diagnostic(out_of_zone=out_of_zone)
        if with_detection
        else None
    )
    incident_signal_diagnostics = (
        (
            IncidentSignalDiagnostic(
                physical_vehicle_id=VEHICLE_ID,
                track_segment_id=TrackSegmentId(7),
                signal=placement_diagnostic.bad_parking_signal,
                timing=IncidentRuleTiming(
                    rule_code="BAD_PARKING",
                    confirm_duration_seconds=1.5,
                    clear_duration_seconds=2.5,
                ),
            ),
        )
        if placement_diagnostic is not None
        else ()
    )
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
            identity_resolutions=identity_resolutions,
            detection_count=len(detections),
            detections=detections,
        ),
        result=SimpleNamespace(
            parking_result=ParkingPipelineResult(
                zone_visit_updates=(),
                parking_episode_updates=(),
                incident_transitions=(),
                placement_diagnostics=(
                    (placement_diagnostic,)
                    if placement_diagnostic is not None
                    else ()
                ),
                incident_signal_diagnostics=incident_signal_diagnostics,
            )
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
        policy_snapshot_json='{"parking_confirm_seconds":5.0}',
        asset_snapshot_json='{"model":{"sha256":"abc"}}',
    )

    assert [row["rowType"] for row in rows] == [
        "FRAME",
        "DETECTION",
        "IDENTITY_RESOLUTION",
        "MOTION_ESTIMATE",
        "TRACKED_VEHICLE",
        "INCIDENT_SIGNAL",
        "PLACEMENT_EVIDENCE",
        "FRAME",
    ]
    detection = rows[1]
    identity = rows[2]
    motion = rows[3]
    tracked = rows[4]
    incident_signal = rows[5]
    placement = rows[6]
    empty_frame = rows[7]
    assert detection["detectionStage"] == "POST_THRESHOLD_PRE_TRACK"
    assert detection["confidence"] == pytest.approx(0.27)
    assert detection["detectionThreshold"] == pytest.approx(0.01)
    assert detection["modelPath"] == "hw/jetson/model/yolov8s.pt"
    assert detection["trackerConfig"] == "bytetrack.yaml"
    assert identity["detectionStage"] == "POST_TRACK_IDENTITY"
    assert identity["identityOutcome"] == "CREATED"
    assert identity["identityReason"] == "NO_ELIGIBLE_CANDIDATE"
    assert identity["trackSegmentId"] == 7
    assert motion["detectionStage"] == "POST_IDENTITY_MOTION"
    assert motion["motionSignal"] == "STATIONARY"
    assert motion["motionReason"] == "STATIONARY_EVIDENCE"
    assert motion["motionSampleCount"] == 4
    assert motion["motionWindowSpanSeconds"] == pytest.approx(0.3)
    assert motion["motionLatestSampleGapSeconds"] == pytest.approx(0.1)
    assert motion["motionNormalizedDisplacement"] == pytest.approx(0.01)
    assert motion["motionNormalizedTrend"] == pytest.approx(0.008)
    assert motion["motionTrendConsistency"] == pytest.approx(0.9)
    assert motion["motionReferenceBboxDiagonal"] == pytest.approx(0.22)
    assert motion["motionStationaryThreshold"] == pytest.approx(0.03)
    assert motion["motionMovingThreshold"] == pytest.approx(0.10)
    assert tracked["detectionStage"] == "POST_TRACK"
    assert tracked["confidence"] == pytest.approx(0.31)
    assert tracked["vehicleAlias"] == "V1"
    assert incident_signal["incidentScopeType"] == "PHYSICAL_VEHICLE"
    assert incident_signal["incidentScopeId"] == str(VEHICLE_ID)
    assert incident_signal["incidentRuleCode"] == "BAD_PARKING"
    assert incident_signal["incidentSignalValue"] == "MATCHED"
    assert incident_signal["incidentSignalConfirmable"] is True
    assert incident_signal["incidentSignalEvidenceJson"] == (
        '{"reasons":["LOW_PRIMARY_OVERLAP","MULTI_SPOT_OVERLAP"]}'
    )
    assert incident_signal["incidentConfirmSeconds"] == pytest.approx(1.5)
    assert incident_signal["incidentClearSeconds"] == pytest.approx(2.5)
    assert placement["vehicleAlias"] == "V1"
    assert placement["trackSegmentId"] == 7
    assert placement["evidenceSource"] == "PARKED_SNAPSHOT"
    assert placement["zoneDefinitionVersion"] == 5
    assert placement["candidateOverlapsJson"] == (
        '[{"overlapRatio":0.51,"zoneId":1},'
        '{"overlapRatio":0.49,"zoneId":2}]'
    )
    assert placement["primaryZoneId"] == 1
    assert placement["primaryOverlapRatio"] == pytest.approx(0.51)
    assert placement["secondaryZoneId"] == 2
    assert placement["secondaryOverlapRatio"] == pytest.approx(0.49)
    assert placement["dominanceGap"] == pytest.approx(0.02)
    assert placement["spotUnionOverlapRatio"] == pytest.approx(1.0)
    assert placement["outsideSpotOverlapRatio"] == pytest.approx(0.0)
    assert placement["assignmentState"] == "AMBIGUOUS"
    assert placement["assignmentZoneId"] is None
    assert placement["assignmentReason"] == "AMBIGUOUS_ZONE_OVERLAP"
    assert placement["assignmentConfidence"] == pytest.approx(0.51)
    assert placement["parkingState"] == "PARKED"
    assert placement["badParkingValue"] == "MATCHED"
    assert placement["badParkingReason"] is None
    assert placement["badParkingReasonsJson"] == (
        '["LOW_PRIMARY_OVERLAP","MULTI_SPOT_OVERLAP"]'
    )
    assert placement["badParkingConfirmable"] is True
    assert placement["outOfZoneValue"] == "NOT_MATCHED"
    assert placement["outOfZoneReason"] is None
    assert placement["outOfZoneReasonsJson"] == "[]"
    assert placement["outOfZoneConfirmable"] is False
    assert empty_frame["pretrackDetectionCount"] == 0
    assert empty_frame["trackedVehicleCount"] == 0
    assert rows[0]["diagnosticSchemaVersion"] == 5
    assert rows[0]["policySnapshotJson"] == '{"parking_confirm_seconds":5.0}'
    assert rows[0]["assetSnapshotJson"] == '{"model":{"sha256":"abc"}}'
    assert empty_frame["diagnosticSchemaVersion"] == 5


def test_diagnostic_export_preserves_out_of_zone_rule_reason() -> None:
    rows = diagnostic_rows(
        (_frame(with_detection=True, out_of_zone=True),),
        aliases={VEHICLE_ID: "V1"},
        detection_threshold=0.25,
        model_path="model.pt",
        tracker_config="bytetrack.yaml",
        policy_snapshot_json="{}",
        asset_snapshot_json="{}",
    )

    placement = next(
        row for row in rows if row["rowType"] == "PLACEMENT_EVIDENCE"
    )
    assert placement["candidateOverlapsJson"] == (
        '[{"overlapRatio":0.3,"zoneId":1}]'
    )
    assert placement["assignmentState"] == "UNASSIGNED"
    assert placement["outOfZoneValue"] == "MATCHED"
    assert placement["outOfZoneReason"] is None
    assert placement["outOfZoneReasonsJson"] == (
        '["INSUFFICIENT_SPOT_UNION_OVERLAP"]'
    )
    assert placement["outOfZoneConfirmable"] is True


def test_csv_bytes_emits_utf8_bom_and_requested_header() -> None:
    rows = state_change_rows((_frame(with_detection=True),))

    payload = csv_bytes(rows, fieldnames=STATE_CHANGE_FIELDS)
    parsed = list(csv.DictReader(StringIO(payload.decode("utf-8-sig"))))

    assert payload.startswith(b"\xef\xbb\xbf")
    assert tuple(parsed[0]) == STATE_CHANGE_FIELDS
    assert parsed[0]["frame"] == "7"
    assert set(DIAGNOSTIC_FIELDS).issuperset(
        {
            "rowType",
            "confidence",
            "allIdentitiesResolved",
            "identityOutcome",
            "identityScoreMargin",
            "policySnapshotJson",
            "assetSnapshotJson",
            "motionReason",
            "motionNormalizedTrend",
            "candidateOverlapsJson",
            "badParkingValue",
            "badParkingReasonsJson",
            "outOfZoneValue",
            "outOfZoneReasonsJson",
            "incidentRuleCode",
            "incidentSignalValue",
            "incidentConfirmSeconds",
            "incidentClearSeconds",
        }
    )

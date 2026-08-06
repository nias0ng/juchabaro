"""Viewer frame trace를 분석 가능한 CSV 행으로 직렬화한다.

상태 변경 export와 모델·tracking 진단 export를 분리한다. 진단 export는
판정 입력을 다시 계산하지 않고, commit된 ``FrameTrace``가 이미 보존한
pre-track detection, identity·motion projection과 PhysicalVehicle observation을
평탄화한다.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from io import StringIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tracing import FrameTrace


STATE_CHANGE_FIELDS = (
    "frame",
    "videoTime",
    "category",
    "scopeId",
    "previous",
    "current",
)

DIAGNOSTIC_FIELDS = (
    "frame",
    "videoTime",
    "videoSeconds",
    "capturedAt",
    "rowType",
    "diagnosticSchemaVersion",
    "policySnapshotJson",
    "detectionStage",
    "detectionThreshold",
    "modelPath",
    "trackerConfig",
    "frameObservation",
    "frameObservationReason",
    "fullAreaObserved",
    "allDetectionsTracked",
    "allIdentitiesResolved",
    "pretrackDetectionCount",
    "projectedDetectionCount",
    "trackedVehicleCount",
    "unobservedVehicleCount",
    "detectionIndex",
    "classId",
    "vehicleAlias",
    "physicalVehicleId",
    "trackSegmentId",
    "identityOutcome",
    "identityReason",
    "identityCandidateCount",
    "identityScore",
    "identityRunnerUpScore",
    "identityScoreMargin",
    "reidentificationGapSeconds",
    "identityCenterDistanceRatio",
    "identityPredictedIou",
    "identityAreaRatio",
    "confidence",
    "motionSignal",
    "motionReason",
    "motionSampleCount",
    "motionWindowSpanSeconds",
    "motionLatestSampleGapSeconds",
    "motionNormalizedDisplacement",
    "motionNormalizedTrend",
    "motionTrendConsistency",
    "motionReferenceBboxDiagonal",
    "motionStationaryThreshold",
    "motionMovingThreshold",
    "vehicleObservation",
    "bboxX1",
    "bboxY1",
    "bboxX2",
    "bboxY2",
    "absenceTrustedSeconds",
    "absenceConfirmedAt",
    "notPresentConfirmed",
    "evidenceSource",
    "placementObservedAt",
    "zoneDefinitionVersion",
    "representativeFootprintJson",
    "candidateOverlapsJson",
    "primaryZoneId",
    "primaryOverlapRatio",
    "secondaryZoneId",
    "secondaryOverlapRatio",
    "dominanceGap",
    "spotUnionOverlapRatio",
    "outsideSpotOverlapRatio",
    "assignmentState",
    "assignmentZoneId",
    "assignmentReason",
    "assignmentConfidence",
    "parkingState",
    "badParkingValue",
    "badParkingReason",
    "badParkingReasonsJson",
    "badParkingConfirmable",
    "outOfZoneValue",
    "outOfZoneReason",
    "outOfZoneReasonsJson",
    "outOfZoneConfirmable",
    "incidentScopeType",
    "incidentScopeId",
    "incidentRuleCode",
    "incidentSignalValue",
    "incidentSignalConfirmable",
    "incidentSignalEvidenceJson",
    "incidentConfirmSeconds",
    "incidentClearSeconds",
    "endedTrackSegmentIds",
    "elapsedMs",
)

DIAGNOSTIC_SCHEMA_VERSION = 4


def state_change_rows(frames: Sequence[FrameTrace]) -> list[dict[str, Any]]:
    """기존 authoritative state 변경 timeline을 같은 열 계약으로 반환한다."""

    return [
        {
            "frame": frame.frame_id,
            "videoTime": _format_seconds(frame.video_seconds),
            "category": change.category,
            "scopeId": change.scope_id,
            "previous": change.previous_state,
            "current": change.current_state,
        }
        for frame in frames
        for change in frame.changes
    ]


def diagnostic_rows(
    frames: Sequence[FrameTrace],
    *,
    aliases: Mapping[Any, str],
    detection_threshold: float,
    model_path: str,
    tracker_config: str,
    policy_snapshot_json: str,
) -> list[dict[str, Any]]:
    """프레임·pre-track detection·차량 관측을 한 CSV용 테이블로 평탄화한다.

    ``FRAME`` 행은 detection이 0건이어도 항상 한 행을 남긴다.
    ``DETECTION``은 threshold 통과 후 ByteTrack 적용 전 후보이고,
    ``IDENTITY_RESOLUTION``은 EntityResolver의 결정과 근거이며,
    ``MOTION_ESTIMATE``는 MotionEstimator의 시간 창 판정과 근거이고,
    ``TRACKED_VEHICLE``은 ID가 부여돼 도메인에 전달된 관측이다.
    ``INCIDENT_SIGNAL``은 reducer에 실제 전달한 삼상태 rule 입력과 선택된
    confirm/clear 정책을 보존한다.
    ``PLACEMENT_EVIDENCE``는 pipeline이 규칙 평가에 실제 사용한
    geometry·assignment·BAD_PARKING/OUT_OF_ZONE 근거를 재계산 없이 보존한다.
    """

    rows: list[dict[str, Any]] = []
    for frame in frames:
        batch = frame.tracking_batch
        common = {
            "frame": frame.frame_id,
            "videoTime": _format_seconds(frame.video_seconds),
            "videoSeconds": frame.video_seconds,
            "capturedAt": frame.captured_at.isoformat(),
            "detectionThreshold": detection_threshold,
            "modelPath": model_path,
            "trackerConfig": tracker_config,
            "frameObservation": batch.observation.state.value,
            "frameObservationReason": (
                None
                if batch.observation.reason is None
                else batch.observation.reason.value
            ),
            "fullAreaObserved": batch.full_area_observed,
            "allDetectionsTracked": batch.all_detections_tracked,
            "allIdentitiesResolved": batch.all_identities_resolved,
            "pretrackDetectionCount": batch.detection_count,
            "projectedDetectionCount": len(batch.detections),
            "trackedVehicleCount": len(batch.vehicles),
            "unobservedVehicleCount": len(
                batch.unobserved_physical_vehicle_ids
            ),
            "endedTrackSegmentIds": ",".join(
                str(int(track_segment_id))
                for track_segment_id in batch.ended_track_segment_ids
            ),
            "elapsedMs": frame.elapsed_ms,
        }
        rows.append(
            {
                **common,
                "rowType": "FRAME",
                "diagnosticSchemaVersion": DIAGNOSTIC_SCHEMA_VERSION,
                "policySnapshotJson": policy_snapshot_json,
            }
        )

        for index, detection in enumerate(batch.detections, start=1):
            rows.append(
                {
                    **common,
                    "rowType": "DETECTION",
                    "detectionStage": "POST_THRESHOLD_PRE_TRACK",
                    "detectionIndex": index,
                    "classId": detection.class_id,
                    "confidence": detection.confidence,
                    **_bbox_values(detection.bbox),
                }
            )

        for resolution in batch.identity_resolutions:
            physical_vehicle_id = resolution.physical_vehicle_id
            rows.append(
                {
                    **common,
                    "rowType": "IDENTITY_RESOLUTION",
                    "detectionStage": "POST_TRACK_IDENTITY",
                    "vehicleAlias": (
                        None
                        if physical_vehicle_id is None
                        else aliases.get(
                            physical_vehicle_id,
                            str(physical_vehicle_id)[:8],
                        )
                    ),
                    "physicalVehicleId": (
                        None
                        if physical_vehicle_id is None
                        else str(physical_vehicle_id)
                    ),
                    "trackSegmentId": int(resolution.track_segment_id),
                    "identityOutcome": resolution.outcome.value,
                    "identityReason": (
                        None
                        if resolution.reason is None
                        else resolution.reason.value
                    ),
                    "identityCandidateCount": resolution.candidate_count,
                    "identityScore": resolution.score,
                    "identityRunnerUpScore": resolution.runner_up_score,
                    "identityScoreMargin": resolution.score_margin,
                    "reidentificationGapSeconds": resolution.gap_seconds,
                    "identityCenterDistanceRatio": (
                        resolution.center_distance_ratio
                    ),
                    "identityPredictedIou": resolution.predicted_iou,
                    "identityAreaRatio": resolution.area_ratio,
                }
            )

        segment_by_vehicle = {
            vehicle.physical_vehicle_id: vehicle.track_segment_id
            for vehicle in batch.vehicles
        }
        for estimate in batch.motion_estimates:
            physical_vehicle_id = estimate.physical_vehicle_id
            rows.append(
                {
                    **common,
                    "rowType": "MOTION_ESTIMATE",
                    "detectionStage": "POST_IDENTITY_MOTION",
                    "vehicleAlias": aliases.get(
                        physical_vehicle_id,
                        str(physical_vehicle_id)[:8],
                    ),
                    "physicalVehicleId": str(physical_vehicle_id),
                    "trackSegmentId": int(
                        segment_by_vehicle[physical_vehicle_id]
                    ),
                    "motionSignal": estimate.signal.value,
                    "motionReason": estimate.reason.value,
                    "motionSampleCount": estimate.sample_count,
                    "motionWindowSpanSeconds": estimate.window_span_seconds,
                    "motionLatestSampleGapSeconds": (
                        estimate.latest_sample_gap_seconds
                    ),
                    "motionNormalizedDisplacement": (
                        estimate.normalized_displacement
                    ),
                    "motionNormalizedTrend": estimate.normalized_trend,
                    "motionTrendConsistency": estimate.trend_consistency,
                    "motionReferenceBboxDiagonal": (
                        estimate.reference_bbox_diagonal
                    ),
                    "motionStationaryThreshold": (
                        estimate.stationary_threshold
                    ),
                    "motionMovingThreshold": estimate.moving_threshold,
                }
            )

        for vehicle in batch.vehicles:
            rows.append(
                {
                    **common,
                    "rowType": "TRACKED_VEHICLE",
                    "detectionStage": "POST_TRACK",
                    "vehicleAlias": aliases.get(
                        vehicle.physical_vehicle_id,
                        str(vehicle.physical_vehicle_id)[:8],
                    ),
                    "physicalVehicleId": str(vehicle.physical_vehicle_id),
                    "trackSegmentId": int(vehicle.track_segment_id),
                    "confidence": vehicle.confidence,
                    "motionSignal": vehicle.motion_signal.value,
                    "vehicleObservation": vehicle.observation.state.value,
                    **_bbox_values(vehicle.bbox),
                }
            )

        absence_by_vehicle = {
            item.physical_vehicle_id: item for item in batch.absence_progress
        }
        confirmed_ids = set(batch.not_present_confirmed_vehicle_ids)
        for physical_vehicle_id in batch.unobserved_physical_vehicle_ids:
            progress = absence_by_vehicle[physical_vehicle_id]
            rows.append(
                {
                    **common,
                    "rowType": "UNOBSERVED_VEHICLE",
                    "vehicleAlias": aliases.get(
                        physical_vehicle_id,
                        str(physical_vehicle_id)[:8],
                    ),
                    "physicalVehicleId": str(physical_vehicle_id),
                    "absenceTrustedSeconds": progress.trusted_seconds,
                    "absenceConfirmedAt": (
                        None
                        if progress.confirmed_at is None
                        else progress.confirmed_at.isoformat()
                    ),
                    "notPresentConfirmed": physical_vehicle_id in confirmed_ids,
                }
            )

        for diagnostic in (
            frame.result.parking_result.incident_signal_diagnostics
        ):
            signal = diagnostic.signal
            timing = diagnostic.timing
            rows.append(
                {
                    **common,
                    "rowType": "INCIDENT_SIGNAL",
                    "vehicleAlias": aliases.get(
                        diagnostic.physical_vehicle_id,
                        str(diagnostic.physical_vehicle_id)[:8],
                    ),
                    "physicalVehicleId": str(
                        diagnostic.physical_vehicle_id
                    ),
                    "trackSegmentId": int(diagnostic.track_segment_id),
                    "incidentScopeType": signal.key.scope_type.value,
                    "incidentScopeId": str(signal.key.scope_id),
                    "incidentRuleCode": signal.key.rule_code,
                    "incidentSignalValue": signal.value.value,
                    "incidentSignalConfirmable": signal.confirmable,
                    "incidentSignalEvidenceJson": _canonical_json(
                        signal.evidence
                    ),
                    "incidentConfirmSeconds": (
                        timing.confirm_duration_seconds
                    ),
                    "incidentClearSeconds": timing.clear_duration_seconds,
                }
            )

        for diagnostic in frame.result.parking_result.placement_diagnostics:
            evidence = diagnostic.evidence
            assignment = diagnostic.assignment
            rows.append(
                {
                    **common,
                    "rowType": "PLACEMENT_EVIDENCE",
                    "vehicleAlias": aliases.get(
                        diagnostic.physical_vehicle_id,
                        str(diagnostic.physical_vehicle_id)[:8],
                    ),
                    "physicalVehicleId": str(
                        diagnostic.physical_vehicle_id
                    ),
                    "trackSegmentId": int(diagnostic.track_segment_id),
                    "evidenceSource": diagnostic.source.value,
                    "placementObservedAt": evidence.observed_at.isoformat(),
                    "zoneDefinitionVersion": int(
                        evidence.zone_definition_version
                    ),
                    "representativeFootprintJson": _canonical_json(
                        evidence.representative_footprint
                    ),
                    "candidateOverlapsJson": _canonical_json(
                        [
                            {
                                "overlapRatio": candidate.overlap_ratio,
                                "zoneId": int(candidate.zone_id),
                            }
                            for candidate in evidence.candidate_overlaps
                        ]
                    ),
                    "primaryZoneId": (
                        None
                        if evidence.primary_zone_id is None
                        else int(evidence.primary_zone_id)
                    ),
                    "primaryOverlapRatio": evidence.primary_overlap_ratio,
                    "secondaryZoneId": (
                        None
                        if evidence.secondary_zone_id is None
                        else int(evidence.secondary_zone_id)
                    ),
                    "secondaryOverlapRatio": (
                        evidence.secondary_overlap_ratio
                    ),
                    "dominanceGap": evidence.dominance_gap,
                    "spotUnionOverlapRatio": (
                        evidence.spot_union_overlap_ratio
                    ),
                    "outsideSpotOverlapRatio": (
                        evidence.outside_spot_overlap_ratio
                    ),
                    "assignmentState": assignment.state.value,
                    "assignmentZoneId": (
                        None
                        if assignment.zone_id is None
                        else int(assignment.zone_id)
                    ),
                    "assignmentReason": assignment.unassigned_reason,
                    "assignmentConfidence": assignment.confidence,
                    "parkingState": (
                        None
                        if diagnostic.parking_state is None
                        else diagnostic.parking_state.value
                    ),
                    "badParkingValue": (
                        diagnostic.bad_parking_signal.value.value
                    ),
                    "badParkingReason": _signal_reason(
                        diagnostic.bad_parking_signal
                    ),
                    "badParkingReasonsJson": _signal_reasons_json(
                        diagnostic.bad_parking_signal
                    ),
                    "badParkingConfirmable": (
                        diagnostic.bad_parking_signal.confirmable
                    ),
                    "outOfZoneValue": (
                        diagnostic.out_of_zone_signal.value.value
                    ),
                    "outOfZoneReason": _signal_reason(
                        diagnostic.out_of_zone_signal
                    ),
                    "outOfZoneReasonsJson": _signal_reasons_json(
                        diagnostic.out_of_zone_signal
                    ),
                    "outOfZoneConfirmable": (
                        diagnostic.out_of_zone_signal.confirmable
                    ),
                }
            )
    return rows


def csv_bytes(
    rows: Sequence[Mapping[str, Any]],
    *,
    fieldnames: Sequence[str],
) -> bytes:
    """Excel에서도 UTF-8로 바로 열 수 있는 BOM 포함 CSV를 반환한다."""

    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=fieldnames,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _bbox_values(bbox: Any) -> dict[str, float]:
    return {
        "bboxX1": bbox.x1,
        "bboxY1": bbox.y1,
        "bboxX2": bbox.x2,
        "bboxY2": bbox.y2,
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _signal_reason(signal: Any) -> str | None:
    reason = signal.evidence.get("reason")
    return None if reason is None else str(reason)


def _signal_reasons_json(signal: Any) -> str:
    reasons = signal.evidence.get("reasons")
    return _canonical_json(() if reasons is None else reasons)


def _format_seconds(value: float) -> str:
    sign = "-" if value < 0 else ""
    absolute = abs(value)
    minutes, seconds = divmod(absolute, 60.0)
    return f"{sign}{int(minutes):02d}:{seconds:06.3f}"
